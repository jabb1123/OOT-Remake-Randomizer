"""Little-endian SARC archive reader/writer (the container inside .pack files).

Layout written by `write_sarc` mirrors the game's own packs:
  SARC header (0x14) | SFAT header (0x0C) | SFAT nodes (0x10 each, sorted by name hash)
  | SFNT header (0x08) | names (NUL-terminated, each padded to 4 bytes)
  | zero padding up to data_offset | file data (each start aligned, zero padded)

Real Pack/Actor/*.pack files use an 8-byte alignment for every file (BYML and AINB)
and align data_offset to the largest file alignment, with file data stored in SFAT order.
With these defaults every .pack.zs/.sarc.zs in the base ROM re-writes byte-identically.
"""

from __future__ import annotations

import struct

SARC_HEADER_SIZE = 0x14
SFAT_HEADER_SIZE = 0x0C
SFAT_NODE_SIZE = 0x10
SFNT_HEADER_SIZE = 0x08
DEFAULT_HASH_KEY = 0x65
DEFAULT_ALIGNMENT = 8
# Formats without an NX binary header that the game still page-aligns (seen in Shader/ and Lib/ sarcs).
DEFAULT_EXTENSION_ALIGNMENTS: dict[str, int] = {".sharcb": 0x1000}
_NAME_FLAG = 0x01000000


class SarcError(ValueError):
    pass


def sarc_name_hash(name: str | bytes, key: int = DEFAULT_HASH_KEY) -> int:
    """SFAT name hash: h = h * key + signed_byte, truncated to 32 bits."""
    raw = name.encode("utf-8") if isinstance(name, str) else name
    h = 0
    for b in raw:
        h = (h * key + (b - 256 if b >= 0x80 else b)) & 0xFFFFFFFF
    return h


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def read_sarc(data: bytes) -> dict[str, bytes]:
    """Parse a little-endian SARC. Returns {name: data} in SFAT order."""
    if len(data) < SARC_HEADER_SIZE or data[:4] != b"SARC":
        raise SarcError("not a SARC archive")
    hdr_len, bom = struct.unpack_from("<HH", data, 4)
    if bom != 0xFEFF:
        raise SarcError("only little-endian SARC archives are supported")
    _, data_offset, _version, _ = struct.unpack_from("<IIHH", data, 8)
    sfat = hdr_len
    magic, sfat_len, count, _key = struct.unpack_from("<4sHHI", data, sfat)
    if magic != b"SFAT":
        raise SarcError("missing SFAT section")
    nodes = sfat + sfat_len
    sfnt = nodes + count * SFAT_NODE_SIZE
    magic, sfnt_len = struct.unpack_from("<4sH", data, sfnt)
    if magic != b"SFNT":
        raise SarcError("missing SFNT section")
    names_base = sfnt + sfnt_len

    out: dict[str, bytes] = {}
    for i in range(count):
        _h, attr, start, end = struct.unpack_from("<IIII", data, nodes + i * SFAT_NODE_SIZE)
        if attr & 0xFF000000:
            name_off = names_base + (attr & 0xFFFF) * 4
            name_end = data.index(b"\x00", name_off)
            name = data[name_off:name_end].decode("utf-8")
        else:
            name = f"{_h:08x}.bin"
        if end < start or data_offset + end > len(data):
            raise SarcError(f"file {name!r} out of bounds")
        out[name] = bytes(data[data_offset + start:data_offset + end])
    return out


def sarc_file_alignment(name: str, data: bytes, default: int = DEFAULT_ALIGNMENT,
                        by_extension: dict[str, int] | None = None) -> int:
    """Alignment for one file: max of the default, an extension override, and the
    alignment declared in an NX binary header (BOM 0xFEFF at 0x0C, log2 align at 0x0E)."""
    alignment = default
    if by_extension is None:
        by_extension = DEFAULT_EXTENSION_ALIGNMENTS
    if by_extension:
        for ext, a in by_extension.items():
            if name.endswith(ext):
                alignment = max(alignment, a)
    if len(data) >= 0x20 and data[0x0C:0x0E] == b"\xff\xfe" and data[0x0E] < 16:
        alignment = max(alignment, 1 << data[0x0E])
    return alignment


def write_sarc(files: dict[str, bytes], *, alignment: int = DEFAULT_ALIGNMENT,
               by_extension: dict[str, int] | None = None,
               hash_key: int = DEFAULT_HASH_KEY) -> bytes:
    """Build a little-endian SARC.

    alignment:     minimum alignment of every file's data (game packs use 8).
    by_extension:  {suffix: alignment} overrides (max is taken); None means
                   DEFAULT_EXTENSION_ALIGNMENTS. NX binary headers (bfsha, bfres, ...)
                   contribute their declared alignment automatically.
    data_offset is aligned to the largest file alignment; files are stored in
    SFAT (hash-sorted) order.
    """
    names = list(files)
    if len(set(sarc_name_hash(n, hash_key) for n in names)) != len(names):
        raise SarcError("SARC name hash collision")
    entries = sorted(names, key=lambda n: sarc_name_hash(n, hash_key))

    sfnt = bytearray()
    name_offsets: dict[str, int] = {}
    for n in entries:
        name_offsets[n] = len(sfnt)
        sfnt += n.encode("utf-8") + b"\x00"
        sfnt += b"\x00" * (_align(len(sfnt), 4) - len(sfnt))
        if name_offsets[n] // 4 > 0xFFFF:
            raise SarcError("SFNT too large")

    aligns = {n: sarc_file_alignment(n, files[n], alignment, by_extension) for n in entries}
    max_align = max(aligns.values(), default=alignment)

    names_end = SARC_HEADER_SIZE + SFAT_HEADER_SIZE + len(entries) * SFAT_NODE_SIZE \
        + SFNT_HEADER_SIZE + len(sfnt)
    data_offset = _align(names_end, max_align)

    body = bytearray()
    nodes = bytearray()
    for n in entries:
        start = _align(len(body), aligns[n])
        body += b"\x00" * (start - len(body))
        body += files[n]
        nodes += struct.pack("<IIII", sarc_name_hash(n, hash_key),
                             _NAME_FLAG | (name_offsets[n] // 4), start, len(body))

    total = data_offset + len(body)
    out = bytearray()
    out += struct.pack("<4sHHIIHH", b"SARC", SARC_HEADER_SIZE, 0xFEFF, total, data_offset, 0x0100, 0)
    out += struct.pack("<4sHHI", b"SFAT", SFAT_HEADER_SIZE, len(entries), hash_key)
    out += nodes
    out += struct.pack("<4sHH", b"SFNT", SFNT_HEADER_SIZE, 0)
    out += sfnt
    out += b"\x00" * (data_offset - len(out))
    out += body
    return bytes(out)
