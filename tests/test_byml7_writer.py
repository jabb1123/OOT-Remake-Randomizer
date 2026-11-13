"""Tests for the BYML v7 writer (dump_byml7) and typed parser."""

import math
import os
import struct
import unittest
from pathlib import Path

from oot_randomizer.byml7 import (
    BinaryParam,
    BymlError,
    Byml7,
    F64,
    I64,
    U32,
    U64,
    dump_byml7,
    parse_byml7,
    parse_byml7_typed,
)

SAMPLE_DIR = Path(os.environ.get(
    "BYML7_SAMPLE_DIR",
    r"C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405\files\byml_samples",
))

_OUT_OF_LINE = {0xD4: 8, 0xD5: 8, 0xD6: 8}


def assert_typed_equal(tc: unittest.TestCase, a, b, path="root"):
    """Deep equality that also requires identical Python types (and float bits)."""
    tc.assertIs(type(a), type(b), f"type mismatch at {path}: {type(a)} vs {type(b)}")
    if isinstance(a, dict):
        tc.assertEqual(set(a), set(b), f"key mismatch at {path}")
        for k in a:
            assert_typed_equal(tc, a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        tc.assertEqual(len(a), len(b), f"length mismatch at {path}")
        for i, (x, y) in enumerate(zip(a, b)):
            assert_typed_equal(tc, x, y, f"{path}[{i}]")
    elif isinstance(a, float):
        tc.assertEqual(struct.pack("<d", a), struct.pack("<d", b), f"float mismatch at {path}")
    elif isinstance(a, BinaryParam):
        tc.assertEqual((bytes(a), a.param), (bytes(b), b.param), f"binary mismatch at {path}")
    else:
        tc.assertEqual(a, b, f"value mismatch at {path}")


def validate_structure(tc: unittest.TestCase, data: bytes):
    """Check structural invariants of a BYML v7 file produced by the writer."""
    be = data[:2] == b"BY"
    tc.assertIn(data[:2], (b"BY", b"YB"))
    e = ">" if be else "<"
    order = "big" if be else "little"
    u24 = lambda o: int.from_bytes(data[o:o + 3], order)
    u32 = lambda o: struct.unpack_from(e + "I", data, o)[0]
    tc.assertEqual(len(data) % 4, 0)
    hk, st, root = u32(4), u32(8), u32(12)

    def table(off):
        if off == 0:
            return []
        tc.assertEqual(off % 4, 0)
        tc.assertEqual(data[off], 0xC2)
        n = u24(off + 1)
        offs = [u32(off + 4 + 4 * i) for i in range(n + 1)]
        strs = [data[off + offs[i]:off + offs[i + 1] - 1] for i in range(n)]
        for i in range(n):
            tc.assertEqual(data[off + offs[i + 1] - 1], 0)
        tc.assertEqual(strs, sorted(strs), "string table not sorted by raw bytes")
        tc.assertEqual(len(set(strs)), len(strs), "duplicate table entries")
        return strs

    keys, strings = table(hk), table(st)
    seen = set()

    def value(t, slot_off):
        v = u32(slot_off)
        if t == 0xA0:
            tc.assertLess(v, len(strings))
        elif t in (0xC0, 0xC1):
            node(v)
        elif t in _OUT_OF_LINE:
            tc.assertEqual(v % 8, 0, "8-byte value not 8-byte aligned")
            tc.assertLessEqual(v + 8, len(data))
        elif t in (0xA1, 0xA2):
            tc.assertEqual(v % 4, 0)
            hdr = 4 if t == 0xA1 else 8
            tc.assertLessEqual(v + hdr + u32(v), len(data))
        elif t == 0xD0:
            tc.assertIn(v, (0, 1))

    def node(off):
        if off in seen:
            return
        seen.add(off)
        tc.assertEqual(off % 4, 0, "node not 4-byte aligned")
        t, n = data[off], u24(off + 1)
        if t == 0xC1:
            idxs = [u24(off + 4 + 8 * i) for i in range(n)]
            tc.assertEqual(idxs, sorted(idxs), "hash entries not sorted by key index")
            tc.assertEqual(len(set(idxs)), len(idxs))
            for i in range(n):
                tc.assertLess(idxs[i], len(keys))
                value(data[off + 4 + 8 * i + 3], off + 8 + 8 * i)
        elif t == 0xC0:
            slots = (off + 4 + n + 3) & ~3
            for i in range(n):
                value(data[off + 4 + i], slots + 4 * i)
        else:
            tc.fail(f"unexpected container type {t:#x}")

    node(root)


SYNTHETIC = {
    "str": "hello",
    "empty_str": "",
    "unicode": "Hyrule ✓ ゼルダ",
    "bool_t": True,
    "bool_f": False,
    "i32": -123,
    "i32_max": 2**31 - 1,
    "f32": 1.5,
    "f32_neg_zero": -0.0,
    "u32": U32(0xDEADBEEF),
    "i64": I64(-(2**63)),
    "u64": U64(2**64 - 1),
    "f64": F64(math.pi),
    "null": None,
    "bin": b"\x00\x01\x02binary",
    "bin_empty": b"",
    "binp": BinaryParam(b"abc", 0x10),
    "empty_hash": {},
    "empty_arr": [],
    "arr": [1, "x", 2.5, U64(5), I64(-5), F64(0.1), None, True, [], {}, b"zz"],
    "nested": {"a": [{"b": [U32(1), U32(2)]}, {"b": [U32(1), U32(2)]}],
               "Zeta": "x", "alpha": "y"},
}


class SyntheticRoundTripTests(unittest.TestCase):
    def roundtrip(self, obj, **kw):
        data = dump_byml7(obj, **kw)
        validate_structure(self, data)
        back = parse_byml7_typed(data)
        assert_typed_equal(self, back, obj)
        return data, back

    def test_all_types_little_endian(self):
        data, _ = self.roundtrip(SYNTHETIC)
        self.assertEqual(data[:4], b"YB\x07\x00")

    def test_all_types_big_endian(self):
        data, _ = self.roundtrip(SYNTHETIC, big_endian=True)
        self.assertEqual(data[:4], b"BY\x00\x07")
        self.assertEqual(Byml7(data).version, 7)

    def test_array_root(self):
        self.roundtrip([{"k": 1}, {"k": 2}, "s", U32(3)])

    def test_redump_is_stable(self):
        a = dump_byml7(SYNTHETIC)
        b = dump_byml7(parse_byml7_typed(a))
        self.assertEqual(a, b)

    def test_plain_parse_values(self):
        plain = parse_byml7(dump_byml7(SYNTHETIC))
        self.assertEqual(plain["u32"], 0xDEADBEEF)
        self.assertIs(type(plain["u32"]), int)
        self.assertIs(type(plain["u64"]), int)
        self.assertEqual(plain["u64"], 2**64 - 1)
        self.assertEqual(plain["i64"], -(2**63))
        self.assertIs(type(plain["f64"]), float)
        self.assertEqual(plain["bin"], b"\x00\x01\x02binary")
        self.assertEqual(plain["binp"], b"abc")
        self.assertEqual(plain["nested"]["a"][1]["b"], [1, 2])

    def test_plain_objects_serialize(self):
        plain = {"small": 5, "u32": 0xFFFFFFFF, "neg64": -(2**40), "u64": 2**63,
                 "s": "x", "f": 0.25, "l": [1, 2]}
        back = parse_byml7_typed(dump_byml7(plain))
        self.assertIs(type(back["small"]), int)
        self.assertIs(type(back["u32"]), U32)
        self.assertIs(type(back["neg64"]), I64)
        self.assertIs(type(back["u64"]), U64)
        self.assertEqual(back, plain)

    def test_tables_sorted_and_indices_correct(self):
        obj = {"zeta": "b", "Alpha": "a", "_x": "B", "\u00e9": "\u00e9", "A": ["z", "a"]}
        data, back = self.roundtrip(obj)
        r = Byml7(data)
        self.assertEqual(r._hash_keys, sorted(obj, key=lambda s: s.encode()))
        self.assertEqual(r._str_table, sorted({"b", "a", "B", "\u00e9", "z"},
                                              key=lambda s: s.encode()))

    def test_empty_tables_have_zero_offset(self):
        data = dump_byml7([1, 2, 3])
        hk, st = struct.unpack_from("<II", data, 4)
        self.assertEqual((hk, st), (0, 0))
        self.assertEqual(parse_byml7_typed(data), [1, 2, 3])
        data = dump_byml7({"a": 1})
        hk, st = struct.unpack_from("<II", data, 4)
        self.assertNotEqual(hk, 0)
        self.assertEqual(st, 0)

    def test_dedupe_shares_identical_containers(self):
        shared = {"x": [1, 2, 3], "y": I64(7)}
        obj = {"a": shared, "b": dict(shared), "c": [shared, shared]}
        deduped, _ = self.roundtrip(obj)
        separate, _ = self.roundtrip(obj, dedupe=False)
        self.assertLess(len(deduped), len(separate))

    def test_dedupe_respects_types(self):
        obj = {"a": [1], "b": [U32(1)], "c": [1.0], "d": [True], "e": [I64(1)], "f": [U64(1)]}
        self.roundtrip(obj)

    def test_tuple_serializes_as_array(self):
        self.assertEqual(parse_byml7_typed(dump_byml7({"t": (1, 2)})), {"t": [1, 2]})

    def test_nan_f32_and_f64(self):
        obj = {"f": float("nan"), "d": F64(float("inf"))}
        back = parse_byml7_typed(dump_byml7(obj))
        self.assertTrue(math.isnan(back["f"]))
        self.assertIs(type(back["d"]), F64)
        self.assertEqual(back["d"], float("inf"))

    def test_errors(self):
        with self.assertRaises(BymlError):
            dump_byml7("not a container")
        with self.assertRaises(BymlError):
            dump_byml7({1: "non-str key"})
        with self.assertRaises(BymlError):
            dump_byml7({"x": object()})
        with self.assertRaises(BymlError):
            dump_byml7({"x": 2**64})
        with self.assertRaises(BymlError):
            U32(-1)
        cyc: list = []
        cyc.append(cyc)
        with self.assertRaises(BymlError):
            dump_byml7(cyc)
        with self.assertRaises(BymlError):
            dump_byml7(cyc, dedupe=False)

    def test_wrapper_reprs(self):
        self.assertEqual(repr(U32(1)), "U32(1)")
        self.assertEqual(repr(F64(0.5)), "F64(0.5)")
        self.assertEqual(BinaryParam(b"a", 1), BinaryParam(b"a", 1))
        self.assertNotEqual(BinaryParam(b"a", 1), BinaryParam(b"a", 2))


@unittest.skipUnless(SAMPLE_DIR.is_dir(), f"sample dir not found: {SAMPLE_DIR}")
class SampleRoundTripTests(unittest.TestCase):
    def sample_files(self):
        files = sorted(p for p in SAMPLE_DIR.iterdir()
                       if p.is_file() and p.read_bytes()[:2] in (b"BY", b"YB"))
        self.assertTrue(files, "no BYML samples found")
        return files

    def test_samples_round_trip(self):
        for path in self.sample_files():
            with self.subTest(sample=path.name):
                data = path.read_bytes()
                reader = Byml7(data)
                typed = parse_byml7_typed(data)
                out = dump_byml7(typed, big_endian=not reader.is_little_endian,
                                 version=reader.version)
                validate_structure(self, out)
                self.assertEqual(out[:4], data[:4])
                assert_typed_equal(self, parse_byml7_typed(out), typed)
                plain = parse_byml7(data)
                self.assertEqual(parse_byml7(out), plain)
                self.assertNotIn("<type:", repr(plain))
                self.assertNotIn("<parse_error", repr(plain))
                self.assertNotIn("<unknown_node", repr(plain))
                # Re-dumping the round-tripped data must be a fixed point.
                self.assertEqual(dump_byml7(parse_byml7_typed(out),
                                            big_endian=not reader.is_little_endian,
                                            version=reader.version), out)

    def test_samples_round_trip_without_dedupe(self):
        for path in self.sample_files():
            data = path.read_bytes()
            if len(data) > 200_000:
                continue
            with self.subTest(sample=path.name):
                reader = Byml7(data)
                typed = parse_byml7_typed(data)
                out = dump_byml7(typed, big_endian=not reader.is_little_endian,
                                 version=reader.version, dedupe=False)
                validate_structure(self, out)
                assert_typed_equal(self, parse_byml7_typed(out), typed)


if __name__ == "__main__":
    unittest.main()
