"""NUP container parser and chunked structure scanner.

The .nup header layout (all values big-endian):
  0x00  4B  magic         "NUP\\x01"
  0x04  4B  flags_ver     version / flags word
  0x08  4B  content_size  size of main content region
  0x0C  4B  reserved
  0x10  8B  content_hash  first 8 bytes of a 32-byte hash block

Actual game-data offsets are resolved by scan_nup_structure(), which walks
the file in chunks with a sliding overlap so no cross-boundary markers are missed.
"""

from __future__ import annotations

import json
import struct
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable


NUP_MAGIC = b"NUP\x01"
_SCAN_WINDOW = 1024 * 1024  # 1 MB for the fast header scan

# ---------------------------------------------------------------------------
# Known structural offsets in this specific NUP file (discovered by scanning).
# ---------------------------------------------------------------------------
# All offsets are absolute byte positions in the .nup file.
KNOWN_LAYOUT: dict[str, dict] = {
    "nup_header": {
        "offset": 0x0,
        "size": 0x80,
        "description": "NUP\\x01 magic, file hash, version fields",
    },
    "toc": {
        "offset": 0x80,
        "description": "TOC\\x01 table-of-contents: 2 top-level content entries",
        "entry_count": 2,
        "entry_0_offset_ptr": 0xD0,   # LE64 at 0xD0 → 0x231BF80 (app block)
        "entry_1_offset_ptr": 0xF0,   # LE32 at 0xF0 → 0x24DEC000 (data block)
    },
    "app_metadata": {
        "offset": 0x231BF80,
        "description": "NPDM/META — application capabilities, service access list (ACI0)",
        "notable_strings": ["Application", "fsp-srv", "hid", "aud:u", "nifm:u", "time:u"],
    },
    "nso_main": {
        "offset": 0x231CE40,
        "magic": "NSO0",
        "description": "Main game executable — 78 MB decompressed, sections use ZBIC compression",
        "text_csize_kb": 23664,
        "text_dsize_kb": 61338,
        "rodata_offset": 0x3A39302,   # absolute file offset of compressed .rodata
        "rodata_csize_kb": 4751,
        "rodata_dsize_kb": 12292,
        "compression": "ZBIC",        # proprietary; magic 'ZBIC', not LZ4/ZSTD/zlib
        "build_id": "33fa6c2c23848282a77e8b88a0a93f4887c55920",
    },
    "nso_sdk_stub": {"offset": 0x3F928B0, "magic": "NSO0", "description": "Small SDK stub (9 KB decompressed)"},
    "nso_sdk_lib":  {"offset": 0x3F951D0, "magic": "NSO0", "description": "SDK/middleware library (16 MB decompressed)"},
    "nso_runtime":  {"offset": 0x470DEB0, "magic": "NSO0", "description": "Small runtime shim (0.9 MB decompressed)"},
    "romfs_encrypted": {
        "offset": 0x24DEC000,
        "description": "Encrypted RomFS — AES-CTR, contains all game asset files (SARC/BFRES/etc.)",
        "status": "encrypted — requires title key to access",
    },
}


@dataclass(slots=True)
class NupRegion:
    name: str
    offset: int
    size: int
    description: str


@dataclass(slots=True)
class NupHeader:
    magic: bytes
    flags_version: int
    declared_content_size: int
    file_size: int
    header_hash_hex: str
    regions: list[NupRegion]

    def is_valid(self) -> bool:
        return self.magic == NUP_MAGIC


@dataclass(slots=True)
class ScanFinding:
    marker_name: str
    offset: int
    offset_hex: str
    context_hex: str    # 32 bytes of context around the match
    description: str


@dataclass(slots=True)
class ScanReport:
    path: str
    file_size: int
    bytes_scanned: int
    elapsed_seconds: float
    chunk_size: int
    findings: list[ScanFinding]

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, indent=2)

    def summary(self) -> str:
        mb = self.bytes_scanned / (1024 ** 2)
        pct = 100.0 * self.bytes_scanned / self.file_size if self.file_size else 0
        lines = [
            f"Scanned {mb:.1f} MB / {self.file_size / (1024**3):.2f} GB ({pct:.2f}%)"
            f"  in {self.elapsed_seconds:.1f}s",
            f"Found {len(self.findings)} marker(s):",
        ]
        for f in self.findings:
            lines.append(f"  {f.offset_hex}  {f.marker_name:20s}  {f.description}")
        return "\n".join(lines)


class NupParseError(ValueError):
    pass


# ---------------------------------------------------------------------------
# All binary markers the scanner looks for — keep in length-descending order
# so longer markers are tried first and don't get masked by prefixes.
# ---------------------------------------------------------------------------
ALL_MARKERS: list[tuple[bytes, str, str]] = [
    # Nintendo Switch container formats
    (b"NCA3",    "nca3_archive",        "Nintendo Content Archive v3"),
    (b"NCA2",    "nca2_archive",        "Nintendo Content Archive v2"),
    (b"NCA0",    "nca0_archive",        "Nintendo Content Archive v0"),
    (b"PFS0",    "pfs0_partition",      "Partition FileSystem"),
    (b"HFS0",    "hfs0_partition",      "Hashed FileSystem"),
    (b"BKTR",    "bktr_reloc",          "BKTR relocation table"),
    (b"NACP",    "nacp_control",        "Application Control Property"),
    (b"CNMT",    "cnmt_meta",           "Content Meta (title metadata)"),
    (b"NPDM",    "npdm_meta",           "Process Data Meta"),
    # Compression / archive formats common in Zelda titles
    (b"Yaz0",    "yaz0_compressed",     "Yaz0 compressed block"),
    (b"SARC",    "sarc_archive",        "SARC archive"),
    (b"BFRES",   "bfres_resource",      "Binary Cafe Resource (3D/textures)"),
    (b"BFEVFL",  "bfevfl_eventflow",    "Event flow script"),
    (b"BFSTM",   "bfstm_audio",         "Binary audio stream"),
    (b"MSBT",    "msbt_text",           "Message Studio Binary Text"),
    # OoT-specific strings that appear in scene and actor tables
    (b"zelda\x00",   "zelda_string",    "Zelda scene/actor string"),
    (b"ZRET\x00",    "zret_string",     "ZRET actor marker"),
    # Raw ELF / NSO executable
    (b"\x7fELF",     "elf_executable",  "ELF executable"),
    (b"NSO0",        "nso_executable",  "Nintendo Switch executable (NSO)"),
    # Zlib stream start bytes (common compression inside containers)
    (b"\x78\x9c",    "zlib_stream_default",  "Zlib stream (default compression)"),
    (b"\x78\xda",    "zlib_stream_best",     "Zlib stream (best compression)"),
]

_OVERLAP = max(len(m) for m, _, _ in ALL_MARKERS)  # bytes carried between chunks


def parse_nup_header(path: str | Path) -> NupHeader:
    rom_path = Path(path)
    if not rom_path.exists():
        raise FileNotFoundError(f"NUP file not found: {rom_path}")

    file_size = rom_path.stat().st_size

    with rom_path.open("rb") as f:
        header_bytes = f.read(64)

    if len(header_bytes) < 16:
        raise NupParseError("File is too short to contain a NUP header.")

    magic = header_bytes[0:4]
    if magic != NUP_MAGIC:
        raise NupParseError(
            f"Unexpected magic bytes: {magic!r}. Expected {NUP_MAGIC!r}."
        )

    (flags_version,) = struct.unpack_from(">I", header_bytes, 4)
    (declared_content_size,) = struct.unpack_from(">I", header_bytes, 8)
    hash_region = header_bytes[16:48] if len(header_bytes) >= 48 else header_bytes[16:]
    header_hash_hex = hash_region.hex()
    regions = _scan_regions(rom_path, file_size)

    return NupHeader(
        magic=magic,
        flags_version=flags_version,
        declared_content_size=declared_content_size,
        file_size=file_size,
        header_hash_hex=header_hash_hex,
        regions=regions,
    )


def _scan_regions(path: Path, file_size: int) -> list[NupRegion]:
    regions: list[NupRegion] = [NupRegion("header", 0, 64, "NUP container header")]

    with path.open("rb") as f:
        window = f.read(_SCAN_WINDOW)

    _locate_known_markers(window, regions)
    regions.append(NupRegion("content", 64, file_size - 64, "Main content payload"))
    return regions


def _locate_known_markers(window: bytes, out: list[NupRegion]) -> None:
    for marker, name, description in ALL_MARKERS:
        pos = window.find(marker)
        if pos != -1:
            out.append(NupRegion(name, pos, -1, description))


# ---------------------------------------------------------------------------
# Chunked deep scanner
# ---------------------------------------------------------------------------

def scan_nup_structure(
    path: str | Path,
    *,
    max_bytes: int = 256 * 1024 * 1024,   # 256 MB default
    chunk_size: int = 4 * 1024 * 1024,    # 4 MB chunks
    progress: Callable[[int, int], None] | None = None,
) -> ScanReport:
    """Walk the file in overlapping chunks and record every marker occurrence.

    Args:
        path: Path to the .nup file.
        max_bytes: Stop after scanning this many bytes.
        chunk_size: Bytes read per iteration (excluding overlap).
        progress: Optional callback(bytes_scanned, file_size) called each chunk.
    """
    rom_path = Path(path)
    file_size = rom_path.stat().st_size
    limit = min(max_bytes, file_size)

    findings: list[ScanFinding] = []
    seen_offsets: set[tuple[str, int]] = set()  # (marker_name, offset) dedup

    t_start = time.monotonic()
    overlap = b""
    file_offset = 0  # byte position of the start of the current chunk (before overlap)

    with rom_path.open("rb") as f:
        while file_offset < limit:
            to_read = min(chunk_size, limit - file_offset)
            raw = f.read(to_read)
            if not raw:
                break

            buf = overlap + raw
            buf_base = file_offset - len(overlap)  # absolute offset of buf[0]

            for marker, name, description in ALL_MARKERS:
                search_from = 0
                while True:
                    pos = buf.find(marker, search_from)
                    if pos == -1:
                        break
                    abs_offset = buf_base + pos
                    key = (name, abs_offset)
                    if key not in seen_offsets and abs_offset >= file_offset - len(overlap):
                        seen_offsets.add(key)
                        ctx_start = max(0, pos - 8)
                        ctx_end = min(len(buf), pos + len(marker) + 24)
                        findings.append(ScanFinding(
                            marker_name=name,
                            offset=abs_offset,
                            offset_hex=hex(abs_offset),
                            context_hex=buf[ctx_start:ctx_end].hex(" "),
                            description=description,
                        ))
                    search_from = pos + 1

            file_offset += len(raw)
            overlap = buf[-_OVERLAP:]

            if progress:
                progress(file_offset, file_size)

    elapsed = time.monotonic() - t_start
    findings.sort(key=lambda f: f.offset)

    return ScanReport(
        path=str(rom_path),
        file_size=file_size,
        bytes_scanned=file_offset,
        elapsed_seconds=elapsed,
        chunk_size=chunk_size,
        findings=findings,
    )


# Marker bytes for known sub-formats that may appear after the NUP header.
_REGION_MARKERS: list[tuple[bytes, str, str]] = [
    (b"PFS0", "pfs0_partition",   "Partition filesystem (PFS0)"),
    (b"HFS0", "hfs0_partition",   "Hashed filesystem (HFS0)"),
    (b"NCA0", "nca_archive",      "Nintendo Content Archive v0"),
    (b"NCA2", "nca_archive",      "Nintendo Content Archive v2"),
    (b"NCA3", "nca_archive",      "Nintendo Content Archive v3"),
    (b"BKTR", "bktr_section",     "BKTR relocation section"),
    (b"NACP", "nacp_control",     "Application Control Property"),
    (b"CNMT", "cnmt_meta",        "Content Meta (title metadata)"),
    (b"Yaz0", "yaz0_compressed",  "Yaz0 compressed data block"),
]


def _locate_known_markers(window: bytes, out: list[NupRegion]) -> None:
    for marker, name, description in _REGION_MARKERS:
        pos = window.find(marker)
        if pos != -1:
            out.append(NupRegion(name, pos, -1, description))
