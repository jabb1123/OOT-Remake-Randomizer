"""Tests for the AINB reader/writer, using two logic modules extracted from the NUP dump."""

import struct
import unittest
from pathlib import Path

from oot_randomizer import ainb
from oot_randomizer.ainb import AinbError, Pool

NUP_DIR = Path(r"C:\Users\jabb1123\Desktop\Roms\The Legend of Zelda Ocarina of Time + U2")
NUP_PATH = NUP_DIR / "The Legend of Zelda Ocarina of Time   U2.0.0.nup"
ZSDIC_PATH = NUP_DIR / "ZsDic.pack"
ROOT_ZSDIC_PATH = Path("ZsDic.pack")

EDC2 = "Market_Adult_Prefab_edc2.logic.module.ainb"
C668 = "Market_Adult_Prefab_c668.logic.module.ainb"
ELEMENT = "HoldGameDataGetBoolExpSimple"
STR_INPUT = "GameDataNameBoolExp"
EXISTING = "SageOfForest_IsCompleted_Exp"
NEW_STRING = "AllSage_IsAfter_Step01_02_Exp"


def _zsdic_bytes() -> bytes | None:
    if ZSDIC_PATH.exists():
        return ZSDIC_PATH.read_bytes()
    if ROOT_ZSDIC_PATH.exists():
        return ROOT_ZSDIC_PATH.read_bytes()
    return None


def _extract(name: str) -> bytes | None:
    """Read one logic module out of the NUP, or return None if the dump is unavailable."""
    zsdic = _zsdic_bytes()
    if not NUP_PATH.exists() or zsdic is None:
        return None
    try:
        from oot_randomizer.nup_chest_patcher import NupChestPatcher
    except ImportError:
        return None
    return NupChestPatcher(NUP_PATH, zsdic).read_file(name)


_NUP_SKIP = "NUP dump or ZsDic.pack not available"


@unittest.skipUnless(NUP_PATH.exists() and (_zsdic_bytes() is not None), _NUP_SKIP)
class AinbNupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.edc2 = _extract(EDC2)
        cls.c668 = _extract(C668)

    def test_extracted_sizes(self) -> None:
        self.assertEqual(len(self.edc2), 2430)
        self.assertEqual(len(self.c668), 2541)
        self.assertEqual(self.edc2[:4], b"AIB ")
        self.assertEqual(struct.unpack_from("<I", self.edc2, 4)[0], ainb.VERSION)

    def test_roundtrip_is_byte_identical(self) -> None:
        for data in (self.edc2, self.c668):
            with self.subTest(size=len(data)):
                self.assertEqual(ainb.parse(data).write(), data)

    def test_pool_add_roundtrip(self) -> None:
        mod = ainb.parse(self.edc2)
        old_pool = bytes(mod.pool.data)
        off = mod.pool.add(NEW_STRING)
        self.assertEqual(off, len(old_pool))
        self.assertEqual(mod.pool.get(off), NEW_STRING)
        self.assertEqual(mod.pool.add(NEW_STRING), off)

        out = mod.write()
        again = ainb.parse(out)
        self.assertEqual(again.pool.get(off), NEW_STRING)
        self.assertEqual(bytes(again.pool.data[: len(old_pool)]), old_pool)
        self.assertEqual(again.write(), out)

    def test_existing_string_readable_at_input(self) -> None:
        mod = ainb.parse(self.edc2)
        (elem,) = mod.find_els(ELEMENT)
        self.assertEqual(mod.in_str(elem, STR_INPUT), EXISTING)

    def test_set_string_input_grows_pool_and_roundtrips(self) -> None:
        mod = ainb.parse(self.edc2)
        (elem,) = mod.find_els(ELEMENT)
        mod.set_str_input(elem, STR_INPUT, NEW_STRING)
        out = mod.write()

        again = ainb.parse(out)
        self.assertEqual(again.in_str(elem, STR_INPUT), NEW_STRING)
        self.assertEqual(again.write(), out)
        self.assertEqual(len(out), len(self.edc2) + len(NEW_STRING) + 1)

    def test_layout_shift_relocates_blobs(self) -> None:
        """Growing an input table moves every later blob; re-parse must still be consistent."""
        mod = ainb.parse(self.edc2)
        mod.ins[3] += bytearray(ainb.INSZ[3])
        out = mod.write()
        again = ainb.parse(out)
        self.assertEqual(len(out), len(self.edc2) + ainb.INSZ[3])
        self.assertEqual(again.write(), out)
        shift = ainb.INSZ[3]
        jump_at = struct.unpack_from("<I", self.edc2, 0x38)[0]
        multi_at = struct.unpack_from("<I", self.edc2, 0x30)[0]
        self.assertEqual(again.jump, ainb._relocate(mod.jump, jump_at, jump_at + shift))
        self.assertEqual(again.multi, ainb._relocate(mod.multi, multi_at, multi_at + shift))
        (elem,) = again.find_els(ELEMENT)
        self.assertEqual(again.in_str(elem, STR_INPUT), EXISTING)


class AinbSyntheticTests(unittest.TestCase):
    def test_pool_add_and_find(self) -> None:
        pool = Pool(bytearray(b"abc\0def\0"))
        self.assertEqual(pool.find("def"), 4)
        self.assertIsNone(pool.find("de"))
        self.assertEqual(pool.add("abc"), 0)
        self.assertEqual(pool.add("new"), 8)
        self.assertEqual(pool.get(8), "new")
        self.assertEqual(bytes(pool.data), b"abc\0def\0new\0")

    def test_pool_add_pads_unterminated_tail(self) -> None:
        pool = Pool(bytearray(b"abc"))
        off = pool.add("x")
        self.assertEqual(off, 4)
        self.assertEqual(bytes(pool.data), b"abc\0x\0")

    def test_relocate_fixes_internal_pointers(self) -> None:
        blob = struct.pack("<II", 108, 4) + b"abcd"
        out = ainb._relocate(blob, 100, 200)
        self.assertEqual(struct.unpack_from("<I", out, 0)[0], 208)
        self.assertEqual(struct.unpack_from("<I", out, 4)[0], 4)
        self.assertEqual(out[8:], b"abcd")

    def test_rejects_bad_magic(self) -> None:
        with self.assertRaises(AinbError):
            ainb.parse(b"XXXX" + b"\0" * 0x80)

    def test_rejects_attachments(self) -> None:
        data = bytearray(0x80)
        data[0:4] = b"AIB "
        struct.pack_into("<I", data, 4, ainb.VERSION)
        struct.pack_into("<I", data, 0x18, 1)
        with self.assertRaises(AinbError):
            ainb.parse(bytes(data))


if __name__ == "__main__":
    unittest.main()
