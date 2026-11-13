"""Game data extraction pipeline: NUP → SARC → BYML with ZSTD dictionary decompression.

This module knows how to read individual files from the .nup archive by name,
decompress them using the per-type ZSTD dictionary from ZsDic.pack.zs, and
expose the raw BYML bytes for the downstream parser.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import zstandard as zstd

try:
    from nup.read import NupReader
    from nup.access import iter_children
    _HAS_NUP = True
except ImportError:
    _HAS_NUP = False

ZSTD_DIC_MAGIC = 0xEC30A437
SARC_MAGIC = b"SARC"


class GameDataError(RuntimeError):
    pass


@dataclass(slots=True)
class ZsDictSet:
    """Holds the 4 ZSTD dictionaries extracted from ZsDic.pack."""
    dicts: dict[int, bytes]  # dict_id → raw dictionary bytes

    def decompressor_for(self, compressed: bytes) -> zstd.ZstdDecompressor:
        """Return a ZstdDecompressor configured for the dictionary required by this frame."""
        if len(compressed) < 9:
            raise GameDataError("Compressed buffer too short to contain ZSTD frame header.")
        frame_magic = struct.unpack_from("<I", compressed, 0)[0]
        if frame_magic != 0xFD2FB528:
            raise GameDataError(f"Not a ZSTD frame: magic={hex(frame_magic)}")
        fhd = compressed[4]
        did_flag = (fhd >> 5) & 0x03
        if did_flag == 0:
            return zstd.ZstdDecompressor()
        did_size = [0, 1, 2, 4][did_flag]
        req_id = int.from_bytes(compressed[5:5 + did_size], "little")
        if req_id not in self.dicts:
            raise GameDataError(
                f"Required ZSTD dictionary ID {req_id} not found in ZsDic.pack. "
                f"Available: {sorted(self.dicts.keys())}"
            )
        dic = zstd.ZstdCompressionDict(self.dicts[req_id])
        return zstd.ZstdDecompressor(dict_data=dic)

    def decompress(self, data: bytes) -> bytes:
        return self.decompressor_for(data).stream_reader(data).read()


def parse_sarc(data: bytes) -> dict[str, bytes]:
    """Parse a Nintendo SARC archive and return {filename: bytes}."""
    if data[:4] != SARC_MAGIC:
        raise GameDataError(f"Not a SARC archive: magic={data[:4]!r}")
    hdr_size, _bom, _fsize, data_offset = struct.unpack_from("<HHxIx", data, 4)  # rough parse
    # Proper parse with correct offsets
    hdr_size, bom_val, file_size, data_offset = struct.unpack_from("<HHII", data, 4)
    sfat_off = hdr_size
    sfat_hdr_size, node_count = struct.unpack_from("<HH", data, sfat_off + 4)
    sfat_node_start = sfat_off + sfat_hdr_size
    sfnt_off = sfat_node_start + node_count * 16
    sfnt_hdr_size = struct.unpack_from("<H", data, sfnt_off + 4)[0]
    sfnt_data_off = sfnt_off + sfnt_hdr_size

    result: dict[str, bytes] = {}
    for i in range(node_count):
        node_off = sfat_node_start + i * 16
        name_hash, name_meta, start, end = struct.unpack_from("<IIII", data, node_off)
        name_off_bytes = ((name_meta >> 8) & 0xFFFF) * 4
        nstart = sfnt_data_off + name_off_bytes
        nend = data.index(b"\x00", nstart)
        name = data[nstart:nend].decode()
        abs_start = data_offset + start
        abs_end = data_offset + end
        # Use index suffix for duplicate names
        key = name if name not in result else f"{name}[{i}]"
        result[key] = data[abs_start:abs_end]

    return result


def load_zsdic_pack(nup_path: str, pkg_index: int = 0) -> ZsDictSet:
    """Read ZsDic.pack.zs from the NUP archive and return a ZsDictSet."""
    if not _HAS_NUP:
        raise GameDataError("nup package not installed. Run: pip install ./tools/nup")

    r = NupReader(nup_path)
    try:
        pkg = r.packages[pkg_index]
        dic_file_idx = _find_file(r, pkg.romfs_dir, "ZsDic.pack.zs")
        if dic_file_idx is None:
            raise GameDataError("ZsDic.pack.zs not found in romfs.")
        raw = r.read_file(dic_file_idx)
    finally:
        r.close()

    # ZsDic.pack.zs is ZSTD without a dictionary (meta-compressed)
    sarc_bytes = zstd.ZstdDecompressor().stream_reader(raw).read()
    sarc_entries = parse_sarc(sarc_bytes)

    dicts: dict[int, bytes] = {}
    for _name, dic_bytes in sarc_entries.items():
        if len(dic_bytes) >= 8:
            magic, dic_id = struct.unpack_from("<II", dic_bytes, 0)
            if magic == ZSTD_DIC_MAGIC:
                dicts[dic_id] = dic_bytes

    if not dicts:
        raise GameDataError("No valid ZSTD dictionaries found in ZsDic.pack.")
    return ZsDictSet(dicts=dicts)


def read_zs_file(nup_path: str, romfs_path: str, zsdic: ZsDictSet, pkg_index: int = 0) -> bytes:
    """Read and decompress a single .zs file from the NUP by its romfs path."""
    if not _HAS_NUP:
        raise GameDataError("nup package not installed.")

    parts = [p for p in romfs_path.split("/") if p]
    filename = parts[-1]
    dir_parts = parts[:-1]

    r = NupReader(nup_path)
    try:
        pkg = r.packages[pkg_index]
        dir_index = pkg.romfs_dir
        for part in dir_parts:
            dir_index = _find_child_dir(r, dir_index, part)
            if dir_index is None:
                raise GameDataError(f"Directory not found in romfs: {'/'.join(dir_parts)}")
        file_idx = _find_file(r, dir_index, filename)
        if file_idx is None:
            raise GameDataError(f"File not found in romfs: {romfs_path}")
        raw = r.read_file(file_idx)
    finally:
        r.close()

    return zsdic.decompress(raw)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_file(r: "NupReader", dir_index: int, name: str) -> int | None:
    for ref in iter_children(r, dir_index):
        if not ref.is_dir and ref.name.decode(errors="replace") == name:
            return ref.index
        if ref.is_dir:
            result = _find_file(r, ref.index, name)
            if result is not None:
                return result
    return None


def _find_child_dir(r: "NupReader", dir_index: int, name: str) -> int | None:
    for ref in iter_children(r, dir_index):
        if ref.is_dir and ref.name.decode(errors="replace") == name:
            return ref.index
    return None


def iter_romfs_files(nup_path: str, pkg_index: int = 0) -> Iterator[tuple[str, int]]:
    """Yield (romfs_relative_path, file_index) for every file in romfs."""
    if not _HAS_NUP:
        raise GameDataError("nup package not installed.")

    r = NupReader(nup_path)
    try:
        pkg = r.packages[pkg_index]

        def _walk(dir_index: int, prefix: str) -> Iterator[tuple[str, int]]:
            for ref in iter_children(r, dir_index):
                name = ref.name.decode(errors="replace")
                path = f"{prefix}/{name}" if prefix else name
                if ref.is_dir:
                    yield from _walk(ref.index, path)
                else:
                    yield path, ref.index

        yield from _walk(pkg.romfs_dir, "")
    finally:
        r.close()
