"""Tests for nup_files.add_files on small synthetic NUP containers."""

import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

import zstandard

from nup import format as F
from nup.access import iter_children, meta_records, resolve_path
from nup.pack import pack
from nup.read import NupReader
from nup.verify import verify

from oot_randomizer.nup_chest_patcher import NupChestPatcher, _restbl_entry_offset
from oot_randomizer.nup_files import NupFilesError, _Toc, add_files, toc_space
from oot_randomizer.sarc import write_sarc

BASE_TREE = {
    "romfs/a/b/deep.bin": b"deep file " * 20,
    "romfs/a/b/zeta.txt": b"zeta",
    "romfs/a/Middle.bin": b"M" * 300,
    "romfs/a/alpha.txt": b"alpha",
    "romfs/a/omega.txt": b"omega" * 40,
    "romfs/c/other.bin": bytes(range(256)) * 4,
    "romfs/System/Resource/placeholder.txt": b"x",
    "romfs/top.txt": b"top",
    "exefs/main": b"\x00" * 64,
}
UPDATE_TREE = {
    "romfs/a/b/deep.bin": b"updated deep file",
    "romfs/a/upd.txt": b"update only",
}


def _align16(v: int) -> int:
    return (v + 15) & ~15


def _write_tree(root: Path, tree: dict[str, bytes]) -> None:
    for rel, data in tree.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def move_meta_before_blob(path: Path, slack: int = 0, gap_before_meta: int = 0) -> None:
    """Re-lay a packed NUP like the retail dump: TOC, then meta blocks, then blobs.
    `gap_before_meta` free bytes go between TOC and meta, `slack` between meta and blobs."""
    r = NupReader(str(path))
    try:
        s = r.super
        toc = bytearray(r._mm[s["toc_offset"]:s["toc_offset"] + s["toc_size"]])
        metas = [bytes(r._mm[p.meta_offset:p.meta_offset + p.meta_size]) for p in r.packages]
        blob_end = min(p.meta_offset for p in r.packages if p.meta_size)
        blob = bytes(r._mm[s["blob_offset"]:blob_end])
        old_blob = s["blob_offset"]
        dir_count, file_count = r.dir_count, r.file_count
        header = bytes(r._mm[:F.HEADER_SIZE])
    finally:
        r.close()
    toc += b"\x00" * (-len(toc) % 16)  # retail pads the TOC to 16 bytes after the pool
    toc_end = s["toc_offset"] + len(toc)
    cursor = toc_end + gap_before_meta
    meta_offsets = []
    for m in metas:
        cursor = _align16(cursor)
        meta_offsets.append(cursor)
        cursor += len(m)
    new_blob = _align16(cursor + slack)
    delta = new_blob - old_blob
    for i, (mo, m) in enumerate(zip(meta_offsets, metas)):
        struct.pack_into("<QI", toc, F._toc_head_s.size + i * F.PKG_SIZE + 32, mo, len(m))
    files_base = F._toc_head_s.size + len(metas) * F.PKG_SIZE + dir_count * F.DIR_SIZE
    for fi in range(file_count):
        e = files_base + fi * F.FILE_SIZE
        size, eoff = struct.unpack_from("<QQ", toc, e + 8)
        if size:
            struct.pack_into("<Q", toc, e + 0x10, eoff + delta)
    out = bytearray(new_blob + len(blob))
    out[toc_end - len(toc):toc_end] = toc
    for mo, m in zip(meta_offsets, metas):
        out[mo:mo + len(m)] = m
    out[new_blob:] = blob
    sup = F.parse_super(header)
    out[:F.HEADER_SIZE] = F.pack_super(header[:4], sup["header_size"], sup["header_version"],
                                       sup["toc_offset"], len(toc),
                                       hashlib.sha256(toc).digest(), new_blob, len(out),
                                       sup["package_count"], sup["flags"], sup["uuid"])
    path.write_bytes(out)


def build_nup(tmp: Path, *, slack: int | None = 0, gap_before_meta: int = 0,
              with_update: bool = True, name: str = "test.nup") -> Path:
    """Pack BASE_TREE (+ UPDATE_TREE) with nup.pack. slack=None keeps nup's own layout
    (meta at the end); otherwise meta is moved right after the TOC (like the retail
    dump), followed by `slack` free bytes before the blob region."""
    src = tmp / ("src_" + name)
    if with_update:
        _write_tree(src / "base", BASE_TREE)
        _write_tree(src / "updates" / "131072", UPDATE_TREE)
    else:
        _write_tree(src, BASE_TREE)
    out = tmp / name
    # A long title gives the base meta block ~1.5 KB, which is what add_files can reclaim.
    pack(str(out), str(src), names={None: "Synthetic Test Title " * 75})
    if slack is not None:
        move_meta_before_blob(out, slack, gap_before_meta)
    return out


def snapshot(path: Path) -> dict[tuple[int, str], bytes]:
    """{(package, romfs path): content} for every file in every package."""
    out = {}
    with NupReader(str(path)) as r:
        for p in r.packages:
            stack = [(p.root_dir, "")]
            while stack:
                di, prefix = stack.pop()
                for ref in iter_children(r, di):
                    rel = prefix + ref.name.decode()
                    if ref.is_dir:
                        stack.append((ref.index, rel + "/"))
                    else:
                        out[(p.index, rel)] = r.read_file(ref.index)
    return out


def child_names(path: Path, package: int, rel: str) -> list[bytes]:
    with NupReader(str(path)) as r:
        ref = resolve_path(r, r.packages[package], rel)
        return [c.name for c in iter_children(r, ref.index)]


def metas(path: Path) -> list[list[tuple[int, bytes]]]:
    with NupReader(str(path)) as r:
        return [meta_records(r, p) for p in r.packages]


class AddFilesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def assertVerifies(self, path: Path):
        ok, problems = verify(str(path), deep=True)
        self.assertTrue(ok, problems)

    def test_synthetic_layout_matches_retail_shape(self):
        nup = build_nup(self.tmp)
        self.assertVerifies(nup)
        space = toc_space(nup)
        self.assertGreater(space["meta_bytes_before_blob"], 0)
        self.assertEqual(space["free_bytes_after_meta_move"],
                         space["blob_offset"] - space["toc_end"])
        with NupReader(str(nup)) as r:
            s = r.super
            raw = bytes(r._mm[s["toc_offset"]:s["toc_offset"] + s["toc_size"]])
            self.assertEqual(_Toc(r, raw).serialize(), raw)
        # nup.pack's own (unpadded) TOC also round-trips
        packed = build_nup(self.tmp, slack=None, name="plain.nup")
        with NupReader(str(packed)) as r:
            s = r.super
            raw = bytes(r._mm[s["toc_offset"]:s["toc_offset"] + s["toc_size"]])
            self.assertEqual(_Toc(r, raw).serialize(), raw)

    def test_add_into_dirs_sorted_readable_and_verifies(self):
        nup = build_nup(self.tmp)
        before = snapshot(nup)
        meta_before = metas(nup)
        new = [
            ("a/beta.txt", b"beta content"),
            ("a/b/aaa.bin", b"\x00\x01" * 50),
            ("a/AAA_upper.txt", b"upper"),
            ("a/zzz_last.txt", b"last"),
            ("a/b/zzzz.txt", b"after zeta"),
        ]
        indices = add_files(nup, 0, new)
        self.assertVerifies(nup)
        with NupReader(str(nup)) as r:
            self.assertEqual(r.super["toc_size"] % 16, 0)
            self.assertEqual(len(indices), len(new))
            for fi, (rel, data) in zip(indices, new):
                self.assertEqual(r.read_file(fi), data)
                self.assertEqual(r.files[fi][5], F.CODEC_RAW)
                self.assertEqual(r.files[fi][2], hashlib.sha256(data).digest())
                ref = resolve_path(r, r.packages[0], "romfs/" + rel)
                self.assertIsNotNone(ref, rel)
                self.assertEqual(ref.index, fi)
                self.assertEqual(r.files[fi][3] % 16, 0)
        names_a = child_names(nup, 0, "romfs/a")
        self.assertEqual(names_a, sorted(names_a))
        self.assertEqual(names_a, [b"AAA_upper.txt", b"Middle.bin", b"alpha.txt", b"b",
                                   b"beta.txt", b"omega.txt", b"zzz_last.txt"])
        self.assertEqual(child_names(nup, 0, "romfs/a/b"),
                         [b"aaa.bin", b"deep.bin", b"zeta.txt", b"zzzz.txt"])
        after = snapshot(nup)
        for key, data in before.items():
            self.assertEqual(after[key], data, key)
        self.assertEqual(len(after), len(before) + len(new))
        self.assertEqual(metas(nup), meta_before)

    def test_second_add_and_other_package(self):
        nup = build_nup(self.tmp)
        before = snapshot(nup)
        add_files(nup, 0, [("a/first.txt", b"1")])
        add_files(nup, 0, [("a/b/second.txt", b"22"), ("c/third.txt", b"333")])
        add_files(nup, 1, [("a/b/upd_new.txt", b"in update")])
        self.assertVerifies(nup)
        after = snapshot(nup)
        for key, data in before.items():
            self.assertEqual(after[key], data, key)
        self.assertEqual(after[(0, "romfs/a/first.txt")], b"1")
        self.assertEqual(after[(0, "romfs/a/b/second.txt")], b"22")
        self.assertEqual(after[(0, "romfs/c/third.txt")], b"333")
        self.assertEqual(after[(1, "romfs/a/b/upd_new.txt")], b"in update")
        self.assertNotIn((0, "romfs/a/b/upd_new.txt"), after)

    def test_meta_blocks_moved_to_end_only_when_needed(self):
        nup = build_nup(self.tmp, slack=0, gap_before_meta=512)
        with NupReader(str(nup)) as r:
            offsets = [p.meta_offset for p in r.packages]
        add_files(nup, 0, [("a/small.txt", b"s")])
        with NupReader(str(nup)) as r:
            self.assertEqual([p.meta_offset for p in r.packages], offsets)
        self.assertVerifies(nup)

        # Retail shape: meta directly after the TOC, nothing free before blob_offset.
        # Only the block the grown TOC overlaps is moved.
        tight = build_nup(self.tmp, slack=0, name="tight.nup")
        meta_before = metas(tight)
        with NupReader(str(tight)) as r:
            second_meta = r.packages[1].meta_offset
        add_files(tight, 0, [("a/s", b"s")])
        with NupReader(str(tight)) as r:
            self.assertGreater(r.packages[0].meta_offset, r.super["blob_offset"])
            self.assertEqual(r.packages[1].meta_offset, second_meta)
            for p in r.packages:
                self.assertLessEqual(p.meta_offset + p.meta_size, r.super["file_size"])
        self.assertEqual(metas(tight), meta_before)
        self.assertVerifies(tight)

        # Growing past the second block moves it as well.
        moved = False
        for i in range(40):
            add_files(tight, 0, [(f"a/t{i:02d}", b"t")])
            with NupReader(str(tight)) as r:
                if r.packages[1].meta_offset != second_meta:
                    moved = True
                    for p in r.packages:
                        self.assertGreater(p.meta_offset, r.super["blob_offset"])
                    break
        self.assertTrue(moved)
        self.assertEqual(metas(tight), meta_before)
        self.assertVerifies(tight)

    def test_zstd_codec_and_empty_file(self):
        nup = build_nup(self.tmp)
        data = b"compress me " * 200
        fz, fe = add_files(nup, 0, [("a/z.bin", data), ("a/empty.bin", b"")], codec="zstd")
        self.assertVerifies(nup)
        with NupReader(str(nup)) as r:
            self.assertEqual(r.files[fz][5], F.CODEC_ZSTD)
            self.assertLess(r.files[fz][4], len(data))
            self.assertEqual(r.read_file(fz), data)
            self.assertEqual(r.files[fz][2], hashlib.sha256(data).digest())
            self.assertEqual(r.read_file(fe), b"")

    def test_errors_leave_file_untouched(self):
        nup = build_nup(self.tmp)
        original = nup.read_bytes()
        cases = [
            [("missing/x.txt", b"x")],
            [("a/alpha.txt/x.txt", b"x")],  # parent is a file
            [("a/alpha.txt", b"dup")],
            [("a/n.txt", b"1"), ("a/n.txt", b"2")],
            [("a/../x", b"x")],
        ]
        for files in cases:
            with self.subTest(files=files[0][0]):
                with self.assertRaises(NupFilesError):
                    add_files(nup, 0, files)
                self.assertEqual(nup.read_bytes(), original)
        with self.assertRaises(NupFilesError):
            add_files(nup, 5, [("a/x", b"x")])

    def test_too_many_files_reports_bytes_needed(self):
        nup = build_nup(self.tmp)
        original = nup.read_bytes()
        files = [(f"a/many_{i:04d}_with_a_long_descriptive_name.bin", b"x") for i in range(200)]
        with self.assertRaises(NupFilesError) as cm:
            add_files(nup, 0, files)
        self.assertIn("more bytes needed", str(cm.exception))
        self.assertEqual(nup.read_bytes(), original)

    def test_pack_layout_without_room_raises(self):
        nup = build_nup(self.tmp, slack=None)  # nup.pack puts meta after the blobs
        with self.assertRaises(NupFilesError):
            add_files(nup, 0, [("a/x_quite_long_name_for_sure.txt", b"x")])

    def test_relocate_extents_allows_unbounded_growth(self):
        nup = build_nup(self.tmp)
        before = snapshot(nup)
        files = [(f"a/b/many_{i:04d}.bin", bytes([i % 256]) * (i + 1)) for i in range(150)]
        indices = add_files(nup, 0, files, relocate_extents=True)
        self.assertVerifies(nup)
        after = snapshot(nup)
        for key, data in before.items():
            self.assertEqual(after[key], data, key)
        with NupReader(str(nup)) as r:
            for fi, (_, data) in zip(indices, files):
                self.assertEqual(r.read_file(fi), data)

        plain = build_nup(self.tmp, slack=None, name="plain.nup")  # meta after the blobs
        plain_before = snapshot(plain)
        plain_meta = metas(plain)
        add_files(plain, 1, files[:40], relocate_extents=True)
        self.assertVerifies(plain)
        self.assertEqual(metas(plain), plain_meta)
        plain_after = snapshot(plain)
        for key, data in plain_before.items():
            self.assertEqual(plain_after[key], data, key)

    def test_add_then_replace_then_add(self):
        nup = build_nup(self.tmp)
        before = snapshot(nup)
        payload = b"original resource " * 30
        add_files(nup, 0, [("a/b/new_res.bin.zs", zstandard.ZstdCompressor().compress(payload))])
        patcher = NupChestPatcher(nup, write_sarc({}))
        self.assertEqual(patcher.replace_file("new_res.bin.zs", lambda d: d + b"PATCHED"), 1)
        self.assertVerifies(nup)
        add_files(nup, 0, [("a/after_replace.txt", b"after")])
        self.assertVerifies(nup)
        with NupReader(str(nup)) as r:
            ref = resolve_path(r, r.packages[0], "romfs/a/b/new_res.bin.zs")
            got = zstandard.ZstdDecompressor().decompressobj().decompress(r.read_file(ref.index))
            self.assertEqual(got, payload + b"PATCHED")
            ref = resolve_path(r, r.packages[0], "romfs/a/after_replace.txt")
            self.assertEqual(r.read_file(ref.index), b"after")
        after = snapshot(nup)
        for key, data in before.items():
            self.assertEqual(after[key], data, key)

    def test_replace_file_passes_through_uncompressed_entries(self):
        nup = build_nup(self.tmp)
        payload = b"YB\x07\x00" + b"plain byml setting " * 20
        add_files(nup, 0, [("a/b/raw_setting.bgyml", payload)])
        patcher = NupChestPatcher(nup, write_sarc({}))
        self.assertEqual(patcher.replace_file("raw_setting.bgyml", lambda d: d + b"PATCHED"), 1)
        self.assertVerifies(nup)
        with NupReader(str(nup)) as r:
            ref = resolve_path(r, r.packages[0], "romfs/a/b/raw_setting.bgyml")
            self.assertEqual(r.read_file(ref.index), payload + b"PATCHED")

    def test_add_resource_sizes_on_added_restbl(self):
        nup = build_nup(self.tmp)
        table = bytearray(b"RESTBL" + struct.pack("<IIII", 1, 160, 0, 0))
        add_files(nup, 0, [("System/Resource/ResourceSizeTable.Product.100.rsizetable.zs",
                            zstandard.ZstdCompressor().compress(bytes(table)))])
        add_files(nup, 1, [("a/ResourceSizeTable.Product.100.rsizetable.zs",
                            zstandard.ZstdCompressor().compress(bytes(table)))])
        patcher = NupChestPatcher(nup, write_sarc({}))
        sizes = {"Pack/Actor/Shop_Item_Hookshot.pack": 4096, "a/b/c.bgyml": 1000}
        self.assertEqual(patcher.add_resource_sizes(sizes), 2)
        self.assertVerifies(nup)
        snap = snapshot(nup)
        for key in [(0, "romfs/System/Resource/ResourceSizeTable.Product.100.rsizetable.zs"),
                    (1, "romfs/a/ResourceSizeTable.Product.100.rsizetable.zs")]:
            t = zstandard.ZstdDecompressor().decompressobj().decompress(snap[key])
            for path, size in sizes.items():
                off = _restbl_entry_offset(t, path)
                self.assertIsNotNone(off, path)
                self.assertEqual(struct.unpack_from("<I", t, off)[0], size)


if __name__ == "__main__":
    unittest.main()
