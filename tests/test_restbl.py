"""Tests for RESTBL size insertion (restbl_set_sizes) on synthetic tables."""

import struct
import unittest
import zlib

from oot_randomizer.nup_chest_patcher import (
    NupPatchError,
    _restbl_entry_offset,
    restbl_set_sizes,
)

# crc32 collision pair (found by brute force)
COLLIDE_A = "Pack/Actor/Test_29685295.pack"
COLLIDE_B = "Pack/Actor/Test_32060020.pack"


def make_table(crc_paths: dict[str, int], names: dict[str, int], version: int = 1) -> bytes:
    crcs = sorted((zlib.crc32(p.encode()), s) for p, s in crc_paths.items())
    out = bytearray(b"RESTBL" + struct.pack("<IIII", version, 160, len(crcs), len(names)))
    for c, s in crcs:
        out += struct.pack("<II", c, s)
    for n, s in sorted(names.items()):
        out += n.encode().ljust(160, b"\x00") + struct.pack("<I", s)
    return bytes(out)


def parse_table(t: bytes):
    _, crc_count, name_count = struct.unpack_from("<III", t, 10)
    crcs = [struct.unpack_from("<II", t, 22 + i * 8) for i in range(crc_count)]
    base = 22 + crc_count * 8
    names = [(t[base + i * 164:base + i * 164 + 160].rstrip(b"\x00").decode(),
              struct.unpack_from("<I", t, base + i * 164 + 160)[0]) for i in range(name_count)]
    return crcs, names


def size_of(t: bytes, path: str) -> int | None:
    off = _restbl_entry_offset(t, path)
    return None if off is None else struct.unpack_from("<I", t, off)[0]


class RestblSetSizesTests(unittest.TestCase):
    def setUp(self):
        self.table = make_table(
            {"Pack/Actor/Item_Hookshot.pack": 7416, "Pack/Actor/Shop_Mask_Keaton.pack": 32000,
             "Banc/X/X_Static.bcett.byml": 50000, COLLIDE_A: 111},
            {"Some/Named/Resource.bgyml": 999},
        )

    def test_collision_pair_is_real(self):
        self.assertEqual(zlib.crc32(COLLIDE_A.encode()), zlib.crc32(COLLIDE_B.encode()))

    def test_updates_existing_crc_and_name_entries(self):
        t = restbl_set_sizes(self.table, {"Pack/Actor/Item_Hookshot.pack": 9000,
                                          "Some/Named/Resource.bgyml": 1234})
        self.assertEqual(len(t), len(self.table))
        self.assertEqual(size_of(t, "Pack/Actor/Item_Hookshot.pack"), 9000)
        self.assertEqual(size_of(t, "Some/Named/Resource.bgyml"), 1234)
        self.assertEqual(size_of(t, "Pack/Actor/Shop_Mask_Keaton.pack"), 32000)

    def test_inserts_missing_paths_sorted(self):
        new = {f"Pack/Actor/Shop_New_{i}.pack": 1000 + i for i in range(20)}
        t = restbl_set_sizes(self.table, new)
        crcs, names = parse_table(t)
        self.assertEqual(len(crcs), 4 + 20)
        self.assertEqual([c for c, _ in crcs], sorted(c for c, _ in crcs))
        self.assertEqual(len(names), 1)
        self.assertEqual(t[:10], self.table[:10])
        self.assertEqual(struct.unpack_from("<I", t, 10)[0], 160)
        for path, size in new.items():
            self.assertEqual(size_of(t, path), size)
        self.assertEqual(size_of(t, "Banc/X/X_Static.bcett.byml"), 50000)
        self.assertEqual(size_of(t, "Some/Named/Resource.bgyml"), 999)

    def test_new_path_colliding_with_existing_goes_to_name_table(self):
        t = restbl_set_sizes(self.table, {COLLIDE_B: 4242}, new_paths={COLLIDE_B})
        crcs, names = parse_table(t)
        self.assertEqual(len(crcs), 4)
        self.assertIn((COLLIDE_B, 4242), names)
        self.assertEqual([n for n, _ in names], sorted(n for n, _ in names))
        self.assertEqual(size_of(t, COLLIDE_B), 4242)
        self.assertEqual(size_of(t, COLLIDE_A), 111)  # colliding vanilla entry untouched

    def test_crc_match_without_new_paths_is_treated_as_existing(self):
        t = restbl_set_sizes(self.table, {COLLIDE_B: 4242})
        crcs, names = parse_table(t)
        self.assertEqual(len(crcs), 4)
        self.assertEqual(len(names), 1)
        self.assertEqual(size_of(t, COLLIDE_A), 4242)

    def test_two_new_colliding_paths(self):
        table = make_table({"x.bgyml": 1}, {})
        t = restbl_set_sizes(table, {COLLIDE_A: 10, COLLIDE_B: 20})
        crcs, names = parse_table(t)
        self.assertEqual(len(crcs), 2)
        self.assertEqual(names, [(COLLIDE_B, 20)])
        self.assertEqual(size_of(t, COLLIDE_A), 10)
        self.assertEqual(size_of(t, COLLIDE_B), 20)

    def test_input_is_not_modified_and_idempotent(self):
        original = bytes(self.table)
        sizes = {"Pack/Actor/New.pack": 5, "Pack/Actor/Item_Hookshot.pack": 6}
        t1 = restbl_set_sizes(self.table, sizes)
        self.assertEqual(self.table, original)
        self.assertEqual(restbl_set_sizes(t1, sizes), t1)

    def test_rejects_non_restbl(self):
        with self.assertRaises(NupPatchError):
            restbl_set_sizes(b"NOTRES" + b"\x00" * 16, {"a": 1})

    def test_rejects_too_long_name_for_name_table(self):
        long_a = "x" * 200
        table = make_table({long_a: 1}, {})
        with self.assertRaises(NupPatchError):
            restbl_set_sizes(table, {long_a: 2}, new_paths={long_a})


if __name__ == "__main__":
    unittest.main()
