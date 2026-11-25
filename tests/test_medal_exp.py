"""Tests for the medal formulas on Kakariko Burning and the Forest prelude (medal_exp.py)."""

import unittest
from pathlib import Path

from oot_randomizer import ainb
from oot_randomizer.byml7 import U64, dump_byml7, parse_byml7_typed
from oot_randomizer.gamedata_list import murmur3_32
from oot_randomizer.medal_exp import (
    KAKARIKO_EXP,
    LACS_EXP,
    LACS_PLAYED,
    PRELUDE_EXP,
    PRELUDE_MODULE,
    PRELUDE_READ_EXP,
    medal_flag,
    patch_gamedata_medal_exps,
    patch_prelude_module,
)

NUP_DIR = Path(r"C:\Users\jabb1123\Desktop\Roms\The Legend of Zelda Ocarina of Time + U2")
NUP_PATH = NUP_DIR / "The Legend of Zelda Ocarina of Time   U2.0.0.nup"
ZSDIC_PATH = NUP_DIR / "ZsDic.pack"
ROOT_ZSDIC_PATH = Path("ZsDic.pack")
_NUP_SKIP = "NUP dump or ZsDic.pack not available"


def _zsdic_bytes() -> bytes | None:
    if ZSDIC_PATH.exists():
        return ZSDIC_PATH.read_bytes()
    if ROOT_ZSDIC_PATH.exists():
        return ROOT_ZSDIC_PATH.read_bytes()
    return None


def _h(name: str) -> int:
    return murmur3_32(name.encode())


def _synthetic_list(medals: tuple[str, ...], played: bool = True) -> bytes:
    bools = [{"Hash": U64(_h(medal_flag(m))), "DefaultValue": False} for m in medals]
    if played:
        bools.append({"Hash": U64(_h(LACS_PLAYED)), "DefaultValue": False})
    kakariko = [[U64(10), U64(_h("SageOfForest_IsCompleted_Exp"))], [U64(10), U64(_h("x"))], [U64(3)], [U64(3)]]
    prelude = [[U64(12), U64(3577013)], [U64(2), U64(1439316577)]]
    lacs = [[U64(10), U64(_h("x"))], [U64(3)]]
    exps = [
        {"Hash": U64(_h(KAKARIKO_EXP)), "Values": kakariko},
        {"Hash": U64(_h(PRELUDE_EXP)), "Values": prelude},
        {"Hash": U64(_h(LACS_EXP)), "Values": lacs},
    ]
    root = {"Data": {"Bool": bools, "BoolExp": exps}}
    return dump_byml7(root, big_endian=True, version=7)


def _formula(raw: bytes, name: str) -> list:
    root = parse_byml7_typed(raw)
    (row,) = [r for r in root["Data"]["BoolExp"] if int(r["Hash"]) == _h(name)]
    return [[int(x) for x in term] for term in row["Values"]]


_ALL_MEDALS = ("Forest", "Fire", "Water", "Shadow", "Spirit", "Light")


class MedalFormulaTests(unittest.TestCase):
    def test_kakariko_needs_forest_fire_and_water_medals(self):
        raw = patch_gamedata_medal_exps(_synthetic_list(_ALL_MEDALS))
        self.assertEqual(
            _formula(raw, KAKARIKO_EXP),
            [
                [0, _h(medal_flag("Forest"))],
                [0, _h(medal_flag("Fire"))],
                [0, _h(medal_flag("Water"))],
                [3],
                [3],
            ],
        )

    def test_prelude_flag_needs_the_forest_medal(self):
        raw = patch_gamedata_medal_exps(_synthetic_list(_ALL_MEDALS))
        self.assertEqual(_formula(raw, PRELUDE_EXP), [[0, _h(medal_flag("Forest"))]])

    def test_light_arrows_needs_shadow_and_spirit_and_the_scene_unplayed(self):
        raw = patch_gamedata_medal_exps(_synthetic_list(_ALL_MEDALS))
        self.assertEqual(
            _formula(raw, LACS_EXP),
            [
                [0, _h(medal_flag("Shadow"))],
                [0, _h(medal_flag("Spirit"))],
                [3],
                [0, _h(LACS_PLAYED)],
                [5],
                [3],
            ],
        )

    def test_light_arrows_formula_needs_the_played_bool_registered(self):
        raw = _synthetic_list(_ALL_MEDALS, played=False)
        with self.assertRaisesRegex(ValueError, "HavePlayedEvent.Dm_TimeTemple_0130"):
            patch_gamedata_medal_exps(raw)

    def test_second_run_leaves_the_bytes_unchanged(self):
        once = patch_gamedata_medal_exps(_synthetic_list(_ALL_MEDALS))
        self.assertEqual(patch_gamedata_medal_exps(once), once)

    def test_missing_medal_bool_is_an_error(self):
        raw = _synthetic_list(("Forest", "Fire"))
        with self.assertRaisesRegex(ValueError, "IsGet.Item_Medal_Water"):
            patch_gamedata_medal_exps(raw)


@unittest.skipUnless(NUP_PATH.exists() and _zsdic_bytes() is not None, _NUP_SKIP)
class MedalFormulaNupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from oot_randomizer.gamedata_list import GAME_DATA_LIST
        from oot_randomizer.nup_chest_patcher import NupChestPatcher

        patcher = NupChestPatcher(NUP_PATH, _zsdic_bytes())
        cls.module = patcher.read_file(PRELUDE_MODULE)
        cls.game_data = patcher.read_file(GAME_DATA_LIST)

    def test_prelude_module_reads_the_new_flag_only(self):
        patched = patch_prelude_module(self.module)
        ainb_out = ainb.parse(patched)
        reads = [ainb_out.in_str(i, "GameDataNameBoolExp") for i in ainb_out.find_els("HoldGameDataGetBoolExpSimple")]
        self.assertIn(PRELUDE_EXP, reads)
        self.assertNotIn(PRELUDE_READ_EXP, reads)
        self.assertEqual(patch_prelude_module(patched), patched)

    def test_game_data_list_formulas_follow_the_medals(self):
        raw = patch_gamedata_medal_exps(self.game_data)
        self.assertEqual(_formula(raw, PRELUDE_EXP), [[0, _h(medal_flag("Forest"))]])
        self.assertEqual(len(_formula(raw, KAKARIKO_EXP)), 5)
        self.assertEqual(len(_formula(raw, LACS_EXP)), 6)
        self.assertEqual(patch_gamedata_medal_exps(raw), raw)


if __name__ == "__main__":
    unittest.main()
