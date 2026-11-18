"""NUP-aware chest item patcher.

This module handles the full pipeline for a single bcett placement file:
  1. Find the file in a NUP by romfs path.
  2. Decompress it (ZSTD + per-type dictionary from ZsDic.pack).
  3. Walk the BYML v7 binary and locate every Obj_TBox actor's
     Drop__DropActor string-index value byte offset.
  4. Apply a {vanilla_drop_name: replacement_drop_name} swap map.
  5. Recompress and append a new extent to the NUP copy.
  6. Update the NupFile TOC entry (size, extent_offset, extent_size, sha256).
  7. Recompute and write the TOC SHA-256 and superblock file_size.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import zstandard as zstd

try:
    from nup.read import NupReader
    from nup.access import iter_children
    _HAS_NUP = True
except ImportError:
    _HAS_NUP = False


class NupPatchError(RuntimeError):
    pass


def _extend_string_table(byml: bytearray, strings: list[str], new_strings: list[str]) -> list[str]:
    """Rewrite the BYML value string table at the end of the buffer with new_strings appended.

    Existing indices are preserved, so no other node needs to change; only the header's
    string-table offset is repointed. Returns the extended string list.
    """
    missing = [s for s in dict.fromkeys(new_strings) if s not in strings]
    if not missing:
        return strings
    all_strings = strings + missing
    count = len(all_strings)
    encoded = [s.encode("utf-8") + b"\x00" for s in all_strings]
    header_len = 4 + (count + 1) * 4
    offsets = []
    pos = header_len
    for e in encoded:
        offsets.append(pos)
        pos += len(e)
    offsets.append(pos)
    node = bytearray(struct.pack("<I", 0xC2 | (count << 8)))
    for o in offsets:
        node += struct.pack("<I", o)
    for e in encoded:
        node += e
    while len(byml) % 4:
        byml.append(0)
    new_off = len(byml)
    byml += node
    while len(byml) % 4:
        byml.append(0)
    struct.pack_into("<I", byml, 8, new_off)
    return all_strings


# ---------------------------------------------------------------------------
# ZSTD dict helpers
# ---------------------------------------------------------------------------

_ZSTD_DIC_MAGIC = 0xEC30A437


def _load_dicts_from_sarc(sarc: bytes) -> dict[int, bytes]:
    """Extract all ZSTD dictionaries from a ZsDic.pack SARC archive."""
    hdr_size, _, _, data_offset = struct.unpack_from("<HHII", sarc, 4)
    sfat_off = hdr_size
    sfat_hdr, node_count = struct.unpack_from("<HH", sarc, sfat_off + 4)
    sfat_ns = sfat_off + sfat_hdr
    sfnt_off = sfat_ns + node_count * 16
    sfnt_hdr = struct.unpack_from("<H", sarc, sfnt_off + 4)[0]
    sfnt_d = sfnt_off + sfnt_hdr
    result: dict[int, bytes] = {}
    for i in range(node_count):
        _, _, s, e = struct.unpack_from("<IIII", sarc, sfat_ns + i * 16)
        db = sarc[data_offset + s : data_offset + e]
        if len(db) >= 8:
            m, did = struct.unpack_from("<II", db, 0)
            if m == _ZSTD_DIC_MAGIC:
                result[did] = db
    return result


def _detect_dict_id(data: bytes) -> int | None:
    """Return the ZSTD dictionary ID required by this frame, or None."""
    if len(data) < 6 or struct.unpack_from("<I", data, 0)[0] != 0xFD2FB528:
        return None
    fhd = data[4]
    ss_flag = (fhd >> 5) & 1
    did_flag = fhd & 3
    if did_flag == 0:
        return None
    pos = 5 + (0 if ss_flag else 1)  # skip window descriptor if present
    return int.from_bytes(data[pos : pos + [0, 1, 2, 4][did_flag]], "little")


def _is_zstd_frame(data: bytes) -> bool:
    return len(data) >= 4 and struct.unpack_from("<I", data, 0)[0] == 0xFD2FB528


def _decompress(data: bytes, dicts: dict[int, bytes]) -> bytes:
    req = _detect_dict_id(data)
    if req is None:
        return zstd.ZstdDecompressor().stream_reader(data).read()
    if req not in dicts:
        raise NupPatchError(f"Required ZSTD dict_id {req} not in ZsDic.pack")
    d = zstd.ZstdCompressionDict(dicts[req])
    return zstd.ZstdDecompressor(dict_data=d).stream_reader(data).read()


def _recompress(data: bytes, dicts: dict[int, bytes], dict_id: int, level: int = 22) -> bytes:
    """Compress with the given dict embedded in the ZSTD frame header."""
    if dict_id not in dicts:
        raise NupPatchError(f"dict_id {dict_id} not in ZsDic.pack")
    d = zstd.ZstdCompressionDict(dicts[dict_id])
    # Use ZstdCompressor directly (not ZstdCompressionParameters) so dict_id is embedded
    return zstd.ZstdCompressor(level=level, dict_data=d).compress(data)


# ---------------------------------------------------------------------------
# BYML v7 LE chest scanner
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ChestEntry:
    """One chest actor located in a bcett BYML file."""
    gyaml: str               # "Obj_TBox_A_01" or "Obj_TBox_A_02"
    room_index: int
    vanilla_drop: str        # current Drop__DropActor string
    str_table_index: int     # index of vanilla_drop in this file's string table
    byml_val_offset: int     # absolute byte offset of the u32 str-index in the decompressed BYML
    replacement_drop: str = ""  # filled in by the patcher
    dynamic_ptr_offset: int = -1  # offset of the actor's u32 pointer to its Dynamic hash
    dynamic_offset: int = -1      # offset of the Dynamic hash node (may be shared between actors)


def _walk_byml_chests(byml: bytes) -> list[ChestEntry]:
    """Scan a BYML v7 LE file and return every Obj_TBox chest actor."""
    if byml[:2] != b"YB":
        raise NupPatchError(f"Expected LE BYML (YB), got {byml[:2]!r}")

    _, version, hk_off, st_off, root_off = struct.unpack_from("<2sHIII", byml, 0)

    def u8(o: int) -> int: return byml[o] if 0 <= o < len(byml) else 0
    def u24(o: int) -> int: return int.from_bytes(byml[o:o+3], "little")
    def u32(o: int) -> int: return struct.unpack_from("<I", byml, o)[0] if o+4 <= len(byml) else 0

    def read_str_arr(off: int) -> list[str]:
        count = u24(off + 1)
        result = []
        for i in range(count):
            rel = u32(off + 4 + i * 4)
            abs_ = off + rel
            if abs_ < len(byml):
                end = byml.index(b"\x00", abs_)
                result.append(byml[abs_:end].decode(errors="replace"))
        return result

    hash_keys = read_str_arr(hk_off)
    str_table = read_str_arr(st_off)

    # Build a str→index lookup for the string table
    str_to_idx = {s: i for i, s in enumerate(str_table)}

    def ki(name: str) -> int:
        try: return hash_keys.index(name)
        except ValueError: return -1

    actors_ki   = ki("Actors")
    gyaml_ki    = ki("Gyaml")
    dynamic_ki  = ki("Dynamic")
    drop_ki     = ki("Drop__DropActor")
    room_ki     = ki("DefaultDungeonRoomIndex")

    if any(x == -1 for x in [actors_ki, gyaml_ki, dynamic_ki, drop_ki]):
        return []

    # Walk root hash → Actors array
    def find_in_hash(hash_off: int, want_ki: int) -> tuple[int, int] | None:
        """Return (val_off, val_type) for the first entry with key index want_ki."""
        count = u24(hash_off + 1)
        entry_off = hash_off + 4
        for _ in range(count):
            if entry_off + 8 > len(byml): break
            k = u24(entry_off)
            t = u8(entry_off + 3)
            if k == want_ki:
                return entry_off + 4, t
            entry_off += 8
        return None

    root_t = u8(root_off)
    if root_t != 0xC1:  # root must be a hash
        return []

    actors_res = find_in_hash(root_off, actors_ki)
    if actors_res is None:
        return []
    actors_val_off, actors_vtype = actors_res
    if actors_vtype != 0xC0:  # Actors must be an array (0xC0)
        return []

    actors_off = u32(actors_val_off)
    actors_count = u24(actors_off + 1)
    # 0xC0 array: type bytes at actors_off+4, values at aligned position
    types_base = actors_off + 4
    vals_base  = (types_base + actors_count + 3) & ~3

    chests: list[ChestEntry] = []
    for i in range(actors_count):
        actor_type = u8(types_base + i)
        if actor_type != 0xC1:  # actor must be a hash
            continue
        actor_off = u32(vals_base + i * 4)

        # Read Gyaml
        gyaml_res = find_in_hash(actor_off, gyaml_ki)
        if gyaml_res is None:
            continue
        gyaml_val_off, gyaml_t = gyaml_res
        if gyaml_t != 0xA0:
            continue
        gyaml_str = str_table[u32(gyaml_val_off)] if u32(gyaml_val_off) < len(str_table) else ""
        if not gyaml_str.startswith("Obj_TBox"):
            continue

        # Read Dynamic hash
        dyn_res = find_in_hash(actor_off, dynamic_ki)
        if dyn_res is None:
            continue
        dyn_val_off, dyn_t = dyn_res
        if dyn_t != 0xC1:
            continue
        dyn_off = u32(dyn_val_off)

        # Read Drop__DropActor from Dynamic
        drop_res = find_in_hash(dyn_off, drop_ki)
        if drop_res is None:
            continue
        drop_val_off, drop_t = drop_res
        if drop_t != 0xA0:
            continue
        drop_str_idx = u32(drop_val_off)
        drop_str = str_table[drop_str_idx] if drop_str_idx < len(str_table) else ""

        # Read DefaultDungeonRoomIndex from Dynamic
        room_index = 0
        if room_ki >= 0:
            room_res = find_in_hash(dyn_off, room_ki)
            if room_res:
                room_val_off, room_t = room_res
                room_index = struct.unpack_from("<i", byml, room_val_off)[0] if room_t == 0xD1 else 0

        chests.append(ChestEntry(
            gyaml=gyaml_str,
            room_index=room_index,
            vanilla_drop=drop_str,
            str_table_index=drop_str_idx,
            byml_val_offset=drop_val_off,  # absolute byte offset of the u32 we patch
            dynamic_ptr_offset=dyn_val_off,
            dynamic_offset=dyn_off,
        ))

    return chests


# ---------------------------------------------------------------------------
# NUP file entry helpers
# ---------------------------------------------------------------------------

def _nup_struct(r: "NupReader") -> tuple[int, int, int, int, int]:
    """Return (toc_offset, toc_size, package_count, dir_count, file_size)."""
    return (
        r.super["toc_offset"],
        r.super["toc_size"],
        r.super["package_count"],
        r.dir_count,
        r.super["file_size"],
    )


def _file_entry_abs_offset(toc_offset: int, package_count: int,
                            dir_count: int, file_index: int) -> int:
    """Absolute byte offset of the 0x50-byte NupFile entry in the NUP."""
    return (toc_offset + 0x30
            + package_count * 0x40
            + dir_count * 0x18
            + file_index * 0x50)


def _walk_nup(r: "NupReader", dir_index: int):
    for ref in iter_children(r, dir_index):
        if not ref.is_dir:
            yield ref
        else:
            yield from _walk_nup(r, ref.index)


def _find_nup_file(r: "NupReader", dir_index: int, filename: str):
    for ref in _walk_nup(r, dir_index):
        if ref.name.decode(errors="replace") == filename:
            return ref
    return None


def _find_nup_path(r: "NupReader", dir_index: int, filename: str, prefix: str = "") -> str | None:
    """Return the romfs-relative path (e.g. 'Banc/X/X_Static.bcett.byml.zs') of filename."""
    for ref in iter_children(r, dir_index):
        name = ref.name.decode(errors="replace")
        path = f"{prefix}{name}"
        if ref.is_dir:
            found = _find_nup_path(r, ref.index, filename, path + "/")
            if found:
                return found
        elif name == filename:
            return path
    return None


_RESTBL_NAME_LEN = 160


def _restbl_entry_offset(table: bytes, resource_path: str) -> int | None:
    """Return the byte offset of a RESTBL entry's u32 size field, or None if absent."""
    _, crc_count, name_count = struct.unpack_from("<III", table, 10)
    names_base = 22 + crc_count * 8
    encoded = resource_path.encode()
    for i in range(name_count):
        off = names_base + i * (_RESTBL_NAME_LEN + 4)
        if table[off:off + _RESTBL_NAME_LEN].rstrip(b"\x00") == encoded:
            return off + _RESTBL_NAME_LEN
    crc = zlib.crc32(encoded)
    lo, hi = 0, crc_count
    while lo < hi:
        mid = (lo + hi) // 2
        if struct.unpack_from("<I", table, 22 + mid * 8)[0] < crc:
            lo = mid + 1
        else:
            hi = mid
    if lo < crc_count and struct.unpack_from("<I", table, 22 + lo * 8)[0] == crc:
        return 22 + lo * 8 + 4
    return None


def restbl_set_sizes(table: bytes, sizes: dict[str, int],
                     new_paths: set[str] | frozenset[str] = frozenset()) -> bytes:
    """Return a copy of a RESTBL with each path's size set, inserting missing paths.

    Paths are resource paths without the .zs suffix (e.g. "Pack/Actor/X.pack").
    Existing entries (name table first, then CRC table) are overwritten. A path whose crc32
    is not in the CRC table is inserted there in sorted position. The CRC table stores only
    hashes, so a crc match normally means "this path"; for paths listed in `new_paths`
    (resources known not to exist in vanilla) a crc match is a collision with another
    resource, and the path goes into the name table instead (kept sorted by name), which
    the game checks before the CRC table. Two new paths colliding with each other are
    handled the same way.
    """
    if table[:6] != b"RESTBL":
        raise NupPatchError("not a RESTBL table")
    _, name_len, crc_count, name_count = struct.unpack_from("<IIII", table, 6)
    entry_len = name_len + 4
    names_base = 22 + crc_count * 8
    crc_entries = [struct.unpack_from("<II", table, 22 + i * 8) for i in range(crc_count)]
    name_entries = [
        (table[names_base + i * entry_len:names_base + i * entry_len + name_len].rstrip(b"\x00"),
         struct.unpack_from("<I", table, names_base + i * entry_len + name_len)[0])
        for i in range(name_count)
    ]
    trailer = table[names_base + name_count * entry_len:]

    name_index = {n: i for i, (n, _) in enumerate(name_entries)}
    crc_index = {c: i for i, (c, _) in enumerate(crc_entries)}
    new_crcs: dict[int, int] = {}
    new_names: dict[bytes, int] = {}
    for path, size in sizes.items():
        if not 0 <= size <= 0xFFFFFFFF:
            raise NupPatchError(f"RESTBL size out of range for {path!r}: {size}")
        encoded = path.encode()
        if encoded in name_index:
            name_entries[name_index[encoded]] = (encoded, size)
            continue
        crc = zlib.crc32(encoded)
        if crc in crc_index and path not in new_paths:
            crc_entries[crc_index[crc]] = (crc, size)
        elif crc in crc_index or crc in new_crcs:
            if len(encoded) >= name_len:
                raise NupPatchError(f"RESTBL path too long for name table: {path!r}")
            new_names[encoded] = size
        else:
            new_crcs[crc] = size

    crc_entries.extend(new_crcs.items())
    crc_entries.sort()
    name_entries.extend(new_names.items())
    name_entries.sort()

    out = bytearray(table[:10])
    out += struct.pack("<III", name_len, len(crc_entries), len(name_entries))
    for crc, size in crc_entries:
        out += struct.pack("<II", crc, size)
    for name, size in name_entries:
        out += name.ljust(name_len, b"\x00") + struct.pack("<I", size)
    out += trailer
    return bytes(out)


# ---------------------------------------------------------------------------
# Main patcher class
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ChestSwapResult:
    scene_file: str
    chests_found: int
    chests_patched: int
    swaps: list[dict]        # [{chest_gyaml, room, vanilla, replacement}]
    new_extent_offset: int
    new_extent_size: int


class NupChestPatcher:
    """Patches Drop__DropActor fields in bcett placement files inside a NUP copy.

    Usage:
        patcher = NupChestPatcher(nup_path, zsdic_pack_bytes)
        result = patcher.patch_scene(
            scene_bcett_filename="InsideTheDekuTree_Static.bcett.byml.zs",
            swap_map={"Item_Dungeon_Compass": "Item_Range_SlingShot",
                      "Item_Range_SlingShot": "Item_Dungeon_Compass"},
        )
    """

    def __init__(self, nup_path: Path, zsdic_pack: bytes) -> None:
        if not _HAS_NUP:
            raise NupPatchError("nup package not installed — run: pip install ./tools/nup")
        self.nup_path = Path(nup_path)
        if not self.nup_path.exists():
            raise FileNotFoundError(self.nup_path)
        self._dicts = _load_dicts_from_sarc(zsdic_pack)
        # romfs resource path (without .zs) -> (original decompressed size, patched size)
        self.size_changes: dict[str, tuple[int, int]] = {}

    def _write_extent(self, file_indices: list[int], data: bytes) -> int:
        """Append `data` as a new raw extent and repoint the given TOC file entries at it."""
        r = NupReader(str(self.nup_path))
        try:
            toc_offset, toc_size, package_count, dir_count, orig_file_size = _nup_struct(r)
        finally:
            r.close()
        new_extent_offset = (orig_file_size + 15) & ~15
        new_file_size = new_extent_offset + len(data)
        # The per-file hash covers the stored extent bytes (codec RAW), not decompressed content.
        sha = hashlib.sha256(data).digest()

        with self.nup_path.open("r+b") as f:
            f.seek(toc_offset)
            toc_bytes = bytearray(f.read(toc_size))
            for idx in file_indices:
                e = _file_entry_abs_offset(toc_offset, package_count, dir_count, idx) - toc_offset
                struct.pack_into("<Q", toc_bytes, e + 0x08, len(data))           # size
                struct.pack_into("<Q", toc_bytes, e + 0x10, new_extent_offset)   # extent_offset
                struct.pack_into("<Q", toc_bytes, e + 0x18, len(data))           # extent_size
                toc_bytes[e + 0x20 : e + 0x40] = sha
                toc_bytes[e + 0x40 : e + 0x42] = b"\x00\x00"                   # codec RAW, no flags
            f.seek(toc_offset)
            f.write(toc_bytes)
            f.seek(0x18)
            f.write(hashlib.sha256(bytes(toc_bytes)).digest())  # toc_sha256
            f.seek(0x40)
            f.write(struct.pack("<Q", new_file_size))          # file_size
            f.seek(orig_file_size)
            f.write(b"\x00" * (new_extent_offset - orig_file_size))
            f.write(data)
            f.truncate(new_file_size)
        return new_extent_offset

    def replace_file(self, filename: str, transform) -> int:
        """Apply `transform(decompressed_bytes) -> bytes` to every package copy of a romfs file.

        Zstd-framed entries are decompressed before the transform and recompressed after it;
        uncompressed entries are passed through as-is. Copies sharing one extent are rewritten
        together. Returns the number of extents written.
        """
        r = NupReader(str(self.nup_path))
        try:
            groups: dict[int, tuple[list[int], bytes, str]] = {}
            for pkg in r.packages:
                ref = _find_nup_file(r, pkg.romfs_dir, filename)
                if ref is None:
                    continue
                extent = r.file_info(ref.index)[3]
                if extent in groups:
                    groups[extent][0].append(ref.index)
                else:
                    path = _find_nup_path(r, pkg.romfs_dir, filename) or filename
                    groups[extent] = ([ref.index], r.read_file(ref.index), path)
        finally:
            r.close()
        if not groups:
            raise NupPatchError(f"{filename!r} not found in NUP romfs")

        for indices, compressed, path in groups.values():
            # Some entries (e.g. plain BYML setting files) are stored without zstd framing.
            stored_raw = not _is_zstd_frame(compressed)
            original = compressed if stored_raw else _decompress(compressed, self._dicts)
            patched = transform(original)
            if stored_raw:
                recompressed = patched
            else:
                dict_id = _detect_dict_id(compressed)
                if dict_id is None:
                    recompressed = zstd.ZstdCompressor(level=19).compress(patched)
                else:
                    recompressed = _recompress(patched, self._dicts, dict_id)
            self._write_extent(indices, recompressed)
            key = path.removesuffix(".zs")
            prev_orig = self.size_changes.get(key, (len(original), 0))[0]
            self.size_changes[key] = (prev_orig, len(patched))
        return len(groups)

    def read_file(self, filename: str) -> bytes:
        """Return the decompressed bytes of a romfs file, read from the first package that has it."""
        r = NupReader(str(self.nup_path))
        try:
            for pkg in r.packages:
                ref = _find_nup_file(r, pkg.romfs_dir, filename)
                if ref is not None:
                    compressed = r.read_file(ref.index)
                    break
            else:
                raise NupPatchError(f"{filename!r} not found in NUP romfs")
        finally:
            r.close()
        if _is_zstd_frame(compressed):
            return _decompress(compressed, self._dicts)
        return compressed

    def update_resource_size_tables(self) -> int:
        """Grow RESTBL entries for every patched resource in every package. Returns entries updated."""
        if not self.size_changes:
            return 0
        r = NupReader(str(self.nup_path))
        try:
            tables: list[tuple[int, bytes]] = []
            for pkg in r.packages:
                for ref in _walk_nup(r, pkg.romfs_dir):
                    name = ref.name.decode(errors="replace")
                    if name.startswith("ResourceSizeTable") and name.endswith(".rsizetable.zs"):
                        tables.append((ref.index, r.read_file(ref.index)))
        finally:
            r.close()

        updated = 0
        for file_index, raw in tables:
            table = bytearray(zstd.ZstdDecompressor().decompress(raw, max_output_size=1 << 28))
            if table[:6] != b"RESTBL":
                continue
            for path, (orig_len, new_len) in self.size_changes.items():
                growth = new_len - orig_len
                size_off = _restbl_entry_offset(table, path)
                if growth <= 0 or size_off is None:
                    continue
                current = struct.unpack_from("<I", table, size_off)[0]
                struct.pack_into("<I", table, size_off, (current + growth + 31) & ~31)
                updated += 1
            self._write_extent([file_index], zstd.ZstdCompressor(level=19).compress(bytes(table)))
        return updated

    def add_resource_sizes(self, sizes: dict[str, int],
                           new_paths: set[str] | frozenset[str] = frozenset()) -> int:
        """Set (and insert if missing) RESTBL sizes in every package's ResourceSizeTable.

        `sizes` maps resource paths without .zs (e.g. "Pack/Actor/X.pack") to sizes;
        see restbl_set_sizes for `new_paths`. Returns the number of tables rewritten.
        """
        if not sizes:
            return 0
        r = NupReader(str(self.nup_path))
        try:
            tables: list[tuple[int, bytes]] = []
            for pkg in r.packages:
                for ref in _walk_nup(r, pkg.romfs_dir):
                    name = ref.name.decode(errors="replace")
                    if name.startswith("ResourceSizeTable") and name.endswith(".rsizetable.zs"):
                        tables.append((ref.index, r.read_file(ref.index)))
        finally:
            r.close()

        written = 0
        for file_index, raw in tables:
            table = zstd.ZstdDecompressor().decompress(raw, max_output_size=1 << 28)
            if table[:6] != b"RESTBL":
                continue
            table = restbl_set_sizes(table, sizes, new_paths)
            self._write_extent([file_index], zstd.ZstdCompressor(level=19).compress(table))
            written += 1
        return written

    def scan_chests(self, scene_bcett_filename: str, pkg_index: int = 0) -> list[ChestEntry]:
        """Return all chest actors in a bcett file without modifying anything."""
        r = NupReader(str(self.nup_path))
        try:
            pkg = r.packages[pkg_index]
            ref = _find_nup_file(r, pkg.romfs_dir, scene_bcett_filename)
            if ref is None:
                raise NupPatchError(f"{scene_bcett_filename!r} not found in NUP romfs")
            raw = r.read_file(ref.index)
        finally:
            r.close()

        byml = _decompress(raw, self._dicts)
        return _walk_byml_chests(byml)

    def patch_scene(
        self,
        scene_bcett_filename: str,
        swap_map: dict[str, str],
        pkg_index: int = 0,
        compress_level: int = 22,
        target_replacements: list[dict] | None = None,
    ) -> ChestSwapResult:
        """Apply a vanilla→replacement swap map to one bcett file in the NUP.

        swap_map keys are vanilla Drop__DropActor strings; values are replacements.
        When target_replacements are provided, patching is narrowed to the matching
        scene room and logical chest index, which avoids replacing every duplicate item.
        The original NUP extent is left untouched; the new extent is appended.
        """
        # --- Read metadata and compressed bytes from the NUP ---
        r = NupReader(str(self.nup_path))
        try:
            pkg = r.packages[pkg_index]
            ref = _find_nup_file(r, pkg.romfs_dir, scene_bcett_filename)
            if ref is None:
                raise NupPatchError(f"{scene_bcett_filename!r} not found in NUP romfs")
            resource_path = _find_nup_path(r, pkg.romfs_dir, scene_bcett_filename) or scene_bcett_filename
            file_index = ref.index
            _, _, _, orig_extent_offset, orig_extent_size, _ = r.file_info(file_index)
            orig_compressed = r.read_file(file_index)
            # Other packages may reference the same extent; all must point at the patched data.
            file_indices = [file_index]
            for other in r.packages:
                other_ref = _find_nup_file(r, other.romfs_dir, scene_bcett_filename)
                if other_ref is None or other_ref.index in file_indices:
                    continue
                if r.file_info(other_ref.index)[3] == orig_extent_offset:
                    file_indices.append(other_ref.index)
        finally:
            r.close()

        # --- Decompress ---
        orig_dict_id = _detect_dict_id(orig_compressed)
        if orig_dict_id is None:
            raise NupPatchError(f"No ZSTD dictionary in frame for {scene_bcett_filename}")
        byml = bytearray(_decompress(orig_compressed, self._dicts))
        orig_len = len(byml)

        # --- Scan chests and apply swaps ---
        chests = _walk_byml_chests(bytes(byml))
        swaps_applied: list[dict] = []
        patched_count = 0

        target_entries = target_replacements or []
        target_by_room: dict[int, list[dict]] = {}
        for entry in target_entries:
            room_index = entry.get("room_index")
            if room_index is not None:
                target_by_room.setdefault(room_index, []).append(entry)

        # Build a string→index lookup from the BYML's own string table
        _, _, hk_off, st_off, _ = struct.unpack_from("<2sHIII", byml, 0)

        def u24(o: int) -> int: return int.from_bytes(byml[o:o+3], "little")
        def u32(o: int) -> int: return struct.unpack_from("<I", byml, o)[0]

        def read_str_arr(off: int) -> list[str]:
            count = u24(off + 1)
            result = []
            for i in range(count):
                rel = u32(off + 4 + i * 4)
                abs_ = off + rel
                if abs_ < len(byml):
                    end = byml.index(b"\x00", abs_)
                    result.append(byml[abs_:end].decode(errors="replace"))
            return result

        str_table = read_str_arr(st_off)
        wanted = list(swap_map.values()) + [
            str(t["replacement_item"]) for t in target_entries if t.get("replacement_item")
        ]
        str_table = _extend_string_table(byml, str_table, wanted)
        str_to_idx = {s: i for i, s in enumerate(str_table)}

        used_targets: set[int] = set()
        for chest_order, chest in enumerate(chests):
            replacement = None
            if target_entries:
                applicable = []
                for t_idx, target in enumerate(target_entries):
                    if t_idx in used_targets:
                        continue
                    room_index = target.get("room_index")
                    check_index = target.get("check_index")
                    if target.get("chest_order") is not None:
                        if chest_order != target["chest_order"]:
                            continue
                    elif room_index is not None:
                        if chest.room_index != room_index:
                            continue
                    elif check_index is not None and chest_order != check_index:
                        continue
                    if target.get("vanilla_item") and chest.vanilla_drop != target.get("vanilla_item"):
                        continue
                    applicable.append((t_idx, str(target.get("replacement_item", ""))))
                if applicable:
                    used_targets.add(applicable[0][0])
                    replacement = applicable[0][1]
                else:
                    continue
            if replacement is None:
                replacement = swap_map.get(chest.vanilla_drop)
            if replacement is None:
                continue
            if replacement not in str_to_idx:
                raise NupPatchError(
                    f"Replacement item {replacement!r} not in this file's string table. "
                    "It must already be a string present in the bcett file."
                )
            new_idx = str_to_idx[replacement]
            # The BYML writer dedupes identical Dynamic hashes, so give this chest its own copy.
            dyn_size = 4 + int.from_bytes(byml[chest.dynamic_offset + 1:chest.dynamic_offset + 4], "little") * 8
            while len(byml) % 4:
                byml.append(0)
            clone_off = len(byml)
            byml += byml[chest.dynamic_offset:chest.dynamic_offset + dyn_size]
            struct.pack_into("<I", byml, chest.dynamic_ptr_offset, clone_off)
            struct.pack_into("<I", byml, clone_off + (chest.byml_val_offset - chest.dynamic_offset), new_idx)
            swaps_applied.append({
                "chest": chest.gyaml,
                "room": chest.room_index,
                "vanilla": chest.vanilla_drop,
                "replacement": replacement,
            })
            patched_count += 1

        # --- Recompress and write ---
        new_compressed = _recompress(bytes(byml), self._dicts, orig_dict_id, compress_level)
        new_extent_offset = self._write_extent(file_indices, new_compressed)
        key = resource_path.removesuffix(".zs")
        prev_orig = self.size_changes.get(key, (orig_len, 0))[0]
        self.size_changes[key] = (prev_orig, len(byml))

        return ChestSwapResult(
            scene_file=scene_bcett_filename,
            chests_found=len(chests),
            chests_patched=patched_count,
            swaps=swaps_applied,
            new_extent_offset=new_extent_offset,
            new_extent_size=len(new_compressed),
        )
