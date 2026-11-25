"""Tests for the Light Arrows gate: the c668 logic module and the Market map's Light Arrows area (lacs_gate.py)."""

import unittest
from pathlib import Path

from oot_randomizer import ainb
from oot_randomizer.byml7 import U64, dump_byml7, parse_byml7_typed
from oot_randomizer.lacs_gate import (
    LACS_AREA,
    LACS_AREA_HASH,
    LACS_MAP_FILE,
    LACS_MODULE,
    lacs_step,
    patch_lacs_map,
    patch_lacs_module,
    reads_of,
)
from oot_randomizer.medal_exp import LACS_EXP, PRELUDE_MODULE

NUP_DIR = Path(r"C:\Users\jabb1123\Desktop\Roms\The Legend of Zelda Ocarina of Time + U2")
NUP_PATH = NUP_DIR / "The Legend of Zelda Ocarina of Time   U2.0.0.nup"
ZSDIC_PATH = NUP_DIR / "ZsDic.pack"
ROOT_ZSDIC_PATH = Path("ZsDic.pack")
_NUP_SKIP = "NUP dump or ZsDic.pack not available"
_BOOL = 1


def _zsdic_bytes() -> bytes | None:
    if ZSDIC_PATH.exists():
        return ZSDIC_PATH.read_bytes()
    if ROOT_ZSDIC_PATH.exists():
        return ROOT_ZSDIC_PATH.read_bytes()
    return None


def _map_bytes(area: dict) -> bytes:
    root = {
        "Actors": [
            {"Hash": U64(7), "Gyaml": "Obj_Other", "Translate": [1.0, 2.0, 3.0]},
            area,
        ]
    }
    return dump_byml7(root, big_endian=False, version=7)


def _area(**extra) -> dict:
    base = {"Hash": U64(LACS_AREA_HASH), "Gyaml": "Area", "Translate": [0.0, 0.0, 0.0]}
    base.update(extra)
    return base


_EXPECTED_PRESENCE = {"FlagName": LACS_EXP, "IsCheckLazy": False, "IsNegation": False}


class LacsMapSyntheticTests(unittest.TestCase):
    def test_area_gets_the_presence_flag_and_other_actors_are_kept(self):
        raw = _map_bytes(_area())
        out = patch_lacs_map(raw)
        before = parse_byml7_typed(raw)["Actors"]
        after = parse_byml7_typed(out)["Actors"]
        self.assertEqual(len(after), len(before))
        self.assertEqual(after[0], before[0])
        self.assertEqual(after[1]["Presence"], _EXPECTED_PRESENCE)
        self.assertEqual(after[1]["Gyaml"], "Area")
        self.assertEqual(after[1]["Translate"], before[1]["Translate"])

    def test_second_run_leaves_the_bytes_unchanged(self):
        once = patch_lacs_map(_map_bytes(_area()))
        self.assertEqual(patch_lacs_map(once), once)

    def test_area_with_another_presence_is_refused(self):
        raw = _map_bytes(_area(Presence={"FlagName": "Other", "IsCheckLazy": False, "IsNegation": False}))
        with self.assertRaisesRegex(ValueError, "already has a presence flag"):
            patch_lacs_map(raw)

    def test_missing_area_is_refused(self):
        root = {"Actors": [{"Hash": U64(7), "Gyaml": "Obj_Other"}]}
        with self.assertRaisesRegex(ValueError, "expected one Light Arrows area, found 0"):
            patch_lacs_map(dump_byml7(root, big_endian=False, version=7))

    def test_actor_that_is_not_an_area_is_refused(self):
        raw = _map_bytes(_area(Gyaml="Obj_Other"))
        with self.assertRaisesRegex(ValueError, "not an Area"):
            patch_lacs_map(raw)

    def test_map_without_actors_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no actors"):
            patch_lacs_map(dump_byml7({"Other": 1}, big_endian=False, version=7))


@unittest.skipUnless(NUP_PATH.exists() and _zsdic_bytes() is not None, _NUP_SKIP)
class LacsNupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from oot_randomizer.nup_chest_patcher import NupChestPatcher

        patcher = NupChestPatcher(NUP_PATH, _zsdic_bytes())
        cls.module = patcher.read_file(LACS_MODULE)
        cls.prelude = patcher.read_file(PRELUDE_MODULE)
        cls.map = patcher.read_file(LACS_MAP_FILE)

    def test_module_no_longer_reads_the_step_and_the_area_is_forced_on(self):
        patched = patch_lacs_module(self.module)
        a = ainb.parse(patched)
        step = lacs_step(a)
        self.assertEqual(reads_of(a, step), 0)
        area = next(i for i in a.find_els("ActorLogicAreaActor") if a.prop_str(i, "InstanceName") == LACS_AREA)
        create = a.input(_BOOL, a.find_in(area, _BOOL, "Logic_Create"))
        self.assertEqual((create.src, int.from_bytes(create.val, "little")), (-1, 1))
        hit = a.find_els("HoldActorObserverBySensorHitInfo")[0]
        gate = a.find_els("OperateAND")[0]
        first, count = a.multi_range(gate)
        self.assertTrue(all(a.multi_entry(j)[0] == hit for j in range(first, first + count)))
        self.assertEqual(ainb.audit(a), [])
        self.assertLess(len(patched), len(self.module))

    def test_patched_module_round_trips(self):
        patched = patch_lacs_module(self.module)
        self.assertEqual(ainb.parse(patched).write(), patched)

    def test_second_run_leaves_the_module_unchanged(self):
        patched = patch_lacs_module(self.module)
        self.assertEqual(patch_lacs_module(patched), patched)

    def test_unrelated_module_is_refused(self):
        with self.assertRaisesRegex(ValueError, "expected one AllSage Step02 check"):
            patch_lacs_module(self.prelude)

    def test_map_gets_the_presence_flag_on_the_light_arrows_area_only(self):
        patched = patch_lacs_map(self.map)
        before = parse_byml7_typed(self.map)["Actors"]
        after = parse_byml7_typed(patched)["Actors"]
        self.assertEqual(len(after), len(before))
        changed = [(b, a) for b, a in zip(before, after) if a != b]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0][1]["Hash"], LACS_AREA_HASH)
        self.assertEqual(changed[0][1]["Presence"], _EXPECTED_PRESENCE)
        self.assertEqual(patch_lacs_map(patched), patched)


if __name__ == "__main__":
    unittest.main()
