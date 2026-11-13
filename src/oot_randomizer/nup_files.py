"""Add new files to an existing NUP container in place.

The TOC lives at a fixed offset (0x80) directly before blob_offset, so growing it
needs free bytes in front of the blob region. In the retail dump that gap is
occupied by the package meta blocks; they are moved to the end of the file (the
reader only requires meta blocks to lie inside file_size) to make room. New file
data is appended as 16-byte-aligned extents. Nothing else in the blob region is
touched, so existing files stay byte-identical, and the result is compatible with
NupChestPatcher._write_extent (which only rewrites fixed-size file records).
"""

from __future__ import annotations

import bisect
import hashlib
import os
import struct
from pathlib import Path

import zstandard

from nup import format as F
from nup.read import NupReader

_ZERO_CHUNK = 1 << 20


class NupFilesError(RuntimeError):
    pass


def _align16(value: int) -> int:
    return (value + F.EXTENT_ALIGN - 1) & ~(F.EXTENT_ALIGN - 1)


def _split_path(path: str) -> list[bytes]:
    parts = path.replace("\\", "/").strip("/").split("/")
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise NupFilesError(f"invalid romfs path {path!r}")
    return [p.encode("utf-8") for p in parts]


class _Toc:
    """Mutable in-memory copy of a parsed TOC."""

    def __init__(self, r: NupReader, raw: bytes) -> None:
        magic, pkg_count, dir_count, file_count, pool_off, pool_size, _ = \
            F._toc_head_s.unpack_from(raw, 0)
        pos = F._toc_head_s.size
        self.packages = [F.parse_pkg(raw, pos + i * F.PKG_SIZE) for i in range(pkg_count)]
        pos += pkg_count * F.PKG_SIZE
        self.dirs = [list(F._dir_s.unpack_from(raw, pos + i * F.DIR_SIZE)[:4])
                     for i in range(dir_count)]  # [name_off, name_len, first, count]
        pos += dir_count * F.DIR_SIZE
        self.file_records = bytearray(raw[pos:pos + file_count * F.FILE_SIZE])
        self.dir_count = dir_count
        self.file_count = file_count
        self.children = list(r.children)
        self.pool = bytearray(raw[pool_off:pool_off + pool_size])
        # Some producers (the retail dump) zero-pad the TOC to 16 bytes after the pool.
        self.pad_align = 16 if len(raw) > pool_off + pool_size and len(raw) % 16 == 0 else 1
        self.dir_names = [d[0] for d in r.dirs]
        self.file_names = [f[0] for f in r.files]

    def child_name(self, cid: int) -> bytes:
        if cid < self.dir_count:
            return self.dir_names[cid]
        return self.file_names[cid - self.dir_count]

    def child_names(self, dir_index: int) -> list[bytes]:
        _, _, first, count = self.dirs[dir_index]
        return [self.child_name(c) for c in self.children[first:first + count]]

    def find_child(self, dir_index: int, name: bytes) -> int | None:
        _, _, first, count = self.dirs[dir_index]
        names = self.child_names(dir_index)
        i = bisect.bisect_left(names, name)
        if i < len(names) and names[i] == name:
            return self.children[first + i]
        return None

    def intern(self, name: bytes) -> int:
        # Pool strings are (offset, length) slices, so any existing occurrence can be reused.
        off = self.pool.find(name)
        if off < 0:
            off = len(self.pool)
            self.pool += name
        return off

    def insert_child(self, dir_index: int, cid: int, name: bytes) -> None:
        _, _, first, count = self.dirs[dir_index]
        ins = first + bisect.bisect_left(self.child_names(dir_index), name)
        self.children.insert(ins, cid)
        for i, d in enumerate(self.dirs):
            if i == dir_index:
                continue
            # Empty ranges sitting exactly at the insertion point only move when the
            # insertion extends the parent's range past them.
            if d[2] > ins or (d[2] == ins and (d[3] > 0 or ins > first)):
                d[2] += 1
        self.dirs[dir_index][3] += 1

    def add_file_record(self, name: bytes, size: int, eoff: int, esz: int,
                        sha: bytes, codec: int) -> int:
        fi = self.file_count
        rec = F._file_s.pack(self.intern(name), len(name), size, eoff, esz, sha, codec, 0, 0)
        self.file_records += rec
        self.file_names.append(name)
        self.file_count += 1
        return fi

    def set_extent_offset(self, fi: int, eoff: int) -> None:
        struct.pack_into("<Q", self.file_records, fi * F.FILE_SIZE + 0x10, eoff)

    def extent(self, fi: int) -> tuple[int, int, int]:
        """(size, extent_offset, extent_size)"""
        return struct.unpack_from("<QQQ", self.file_records, fi * F.FILE_SIZE + 0x08)

    def size_with(self, extra_files: int = 0, extra_pool: int = 0) -> int:
        size = (F._toc_head_s.size + len(self.packages) * F.PKG_SIZE
                + self.dir_count * F.DIR_SIZE + (self.file_count + extra_files) * F.FILE_SIZE
                + (len(self.children) + extra_files) * 4 + len(self.pool) + extra_pool)
        return -(-size // self.pad_align) * self.pad_align

    def serialize(self) -> bytes:
        out = bytearray(F._toc_head_s.size)
        for p in self.packages:
            out += F.pack_pkg(p)
        for name_off, name_len, first, count in self.dirs:
            out += F._dir_s.pack(name_off, name_len, first, count, 0)
        out += self.file_records
        out += struct.pack(f"<{len(self.children)}I", *self.children)
        pool_off = len(out)
        out += self.pool
        out += b"\x00" * (-len(out) % self.pad_align)
        F._toc_head_s.pack_into(out, 0, F.TOC_MAGIC, len(self.packages), self.dir_count,
                                self.file_count, pool_off, len(self.pool), 0)
        return bytes(out)


def _encode(data: bytes, codec: str, level: int) -> tuple[bytes, int]:
    if codec == "raw":
        return data, F.CODEC_RAW
    if codec == "zstd":
        return zstandard.ZstdCompressor(level=level).compress(data), F.CODEC_ZSTD
    raise NupFilesError(f"unknown codec {codec!r} (expected 'raw' or 'zstd')")


def add_files(nup_path: str | os.PathLike[str], package_index: int,
              files: list[tuple[str, bytes]], *, codec: str = "raw",
              zstd_level: int = 19, relocate_extents: bool = False) -> list[int]:
    """Add new files under an existing package's romfs, in place. Returns new file indices.

    files:  [(romfs-relative path, content)]; parent directories must already exist and
            the file must not. codec="raw" stores bytes as given (CODEC_RAW); codec="zstd"
            stores a NUP-level zstd frame (CODEC_ZSTD) that readers decompress transparently.
            The recorded sha256 is over the content as read back (NupReader.read_file), which
            is what nup.verify checks.
    relocate_extents: when the grown TOC does not fit before blob_offset even after moving
            the meta blocks, move the first blob extents to the end of the file and raise
            blob_offset instead of failing.
    """
    nup_path = Path(nup_path)
    if not files:
        return []

    r = NupReader(str(nup_path))
    try:
        s = r.super
        toc_offset, old_toc_size = s["toc_offset"], s["toc_size"]
        blob_offset, file_size = s["blob_offset"], s["file_size"]
        magic = bytes(r._mm[0:4])
        toc = _Toc(r, bytes(r._mm[toc_offset:toc_offset + old_toc_size]))
        if not 0 <= package_index < len(toc.packages):
            raise NupFilesError(f"package index {package_index} out of range")
        romfs = toc.packages[package_index].romfs_dir
        if romfs == F.NO_DIR:
            raise NupFilesError(f"package {package_index} has no romfs")

        # --- tree edits ---
        seen: set[tuple[int, bytes]] = set()
        payloads: list[tuple[int, bytes]] = []  # (file index, stored bytes)
        for path, data in files:
            parts = _split_path(path)
            cur = romfs
            for i, part in enumerate(parts[:-1]):
                nxt = toc.find_child(cur, part)
                if nxt is None or nxt >= toc.dir_count:
                    missing = b"/".join(parts[:i + 1]).decode("utf-8", "replace")
                    raise NupFilesError(f"parent directory {missing!r} does not exist "
                                        f"(adding {path!r})")
                cur = nxt
            name = parts[-1]
            if toc.find_child(cur, name) is not None or (cur, name) in seen:
                raise NupFilesError(f"{path!r} already exists in package {package_index}")
            seen.add((cur, name))
            data = bytes(data)
            stored, codec_id = _encode(data, codec, zstd_level) if data else (b"", F.CODEC_RAW)
            sha = hashlib.sha256(data).digest()
            fi = toc.add_file_record(name, len(data), 0, len(stored), sha, codec_id)
            toc.insert_child(cur, toc.dir_count + fi, name)
            payloads.append((fi, stored))

        # --- space planning before blob_offset ---
        new_toc_size = toc.size_with()
        toc_end = toc_offset + new_toc_size
        new_blob_offset = blob_offset
        moved_extents: dict[int, tuple[int, list[int]]] = {}  # old eoff -> (esz, file idx)
        if toc_end > blob_offset:
            if not relocate_extents:
                meta_bytes = sum(p.meta_size for p in toc.packages
                                 if p.meta_size and toc_offset <= p.meta_offset < blob_offset)
                raise NupFilesError(
                    f"grown TOC needs {new_toc_size} bytes but only {blob_offset - toc_offset} "
                    f"are available before blob_offset (after moving {meta_bytes} bytes of meta "
                    f"blocks); {toc_end - blob_offset} more bytes needed. Add fewer/shorter-named "
                    f"files or pass relocate_extents=True.")
            new_blob_offset = _align16(toc_end)
            for fi in range(toc.file_count):
                size, eoff, esz = toc.extent(fi)
                if size and eoff < new_blob_offset:
                    moved_extents.setdefault(eoff, (esz, []))[1].append(fi)

        region_end = new_blob_offset if new_blob_offset != blob_offset else toc_end
        moved_meta: list[tuple[int, bytes]] = []
        for pi, p in enumerate(toc.packages):
            if p.meta_size and p.meta_offset < region_end and p.meta_offset + p.meta_size > toc_offset:
                moved_meta.append((pi, bytes(r._mm[p.meta_offset:p.meta_offset + p.meta_size])))
        moved_extent_data = {eoff: bytes(r._mm[eoff:eoff + esz])
                             for eoff, (esz, _) in moved_extents.items()}
        old_meta = [(p.meta_offset, p.meta_size) for p in toc.packages]
    finally:
        r.close()

    # --- tail layout: relocated extents, new extents, relocated meta blocks ---
    tail: list[tuple[int, bytes]] = []
    cursor = max(file_size, new_blob_offset)
    for eoff, (esz, users) in sorted(moved_extents.items()):
        cursor = _align16(cursor)
        for fi in users:
            toc.set_extent_offset(fi, cursor)
        tail.append((cursor, moved_extent_data[eoff]))
        cursor += esz
    new_indices = []
    for fi, stored in payloads:
        new_indices.append(fi)
        if not stored:
            continue
        cursor = _align16(cursor)
        toc.set_extent_offset(fi, cursor)
        tail.append((cursor, stored))
        cursor += len(stored)
    for pi, block in moved_meta:
        cursor = _align16(cursor)
        toc.packages[pi].meta_offset = cursor
        tail.append((cursor, block))
        cursor += len(block)
    new_file_size = cursor

    toc_bytes = toc.serialize()
    assert len(toc_bytes) == new_toc_size

    # Bytes between the new TOC end and blob_offset that held moved data are zeroed;
    # meta blocks that stayed in place are preserved.
    kept = sorted((mo, mo + ms) for i, (mo, ms) in enumerate(old_meta)
                  if ms and i not in {pi for pi, _ in moved_meta}
                  and toc_end <= mo < new_blob_offset)
    zero_ranges = []
    pos = toc_end
    for a, b in kept:
        if a > pos:
            zero_ranges.append((pos, a))
        pos = max(pos, b)
    if pos < new_blob_offset:
        zero_ranges.append((pos, new_blob_offset))

    with nup_path.open("r+b") as f:
        prev_end = file_size
        for off, blob in tail:
            f.seek(prev_end)
            f.write(b"\x00" * (off - prev_end))
            f.write(blob)
            prev_end = off + len(blob)
        f.truncate(new_file_size)
        f.flush()
        os.fsync(f.fileno())
        f.seek(toc_offset)
        f.write(toc_bytes)
        for a, b in zero_ranges:
            f.seek(a)
            while a < b:
                n = min(_ZERO_CHUNK, b - a)
                f.write(b"\x00" * n)
                a += n
        f.seek(0)
        f.write(F.pack_super(magic, s["header_size"], s["header_version"], toc_offset,
                             new_toc_size, hashlib.sha256(toc_bytes).digest(), new_blob_offset,
                             new_file_size, s["package_count"], s["flags"], s["uuid"]))
        f.flush()
        os.fsync(f.fileno())

    NupReader(str(nup_path)).close()  # structural validation of the result
    return new_indices


def toc_space(nup_path: str | os.PathLike[str]) -> dict[str, int]:
    """Report TOC/meta/blob space numbers for planning how many files fit."""
    with NupReader(str(nup_path)) as r:
        s = r.super
        toc_end = s["toc_offset"] + s["toc_size"]
        meta_before_blob = sum(p.meta_size for p in r.packages
                               if p.meta_size and p.meta_offset < s["blob_offset"])
        return {
            "toc_offset": s["toc_offset"],
            "toc_size": s["toc_size"],
            "toc_end": toc_end,
            "blob_offset": s["blob_offset"],
            "meta_bytes_before_blob": meta_before_blob,
            "free_bytes_after_meta_move": s["blob_offset"] - toc_end,
        }
