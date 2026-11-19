"""Tests for world logic parsing, reachability search, and assumed-fill planning."""

import tempfile
import unittest
from collections import Counter
from pathlib import Path

from oot_randomizer.engine import load_chest_slots, load_default_slots
from oot_randomizer.event_items import EVENT_SLOTS, event_location_name
from oot_randomizer.npc_grants import NPC_SLOTS
from oot_randomizer.item_ids import MAJOR_ITEM_ACTORS
from oot_randomizer.logic_template import build_template
from oot_randomizer.planner import PlanOptions, PlanningError, known_locations, plan_seed
from oot_randomizer.skulltula_rewards import SKULL_REWARDS, TOKEN_ITEM, skull_location_name
from oot_randomizer.songs import SONG_SLOTS, song_location_name
from oot_randomizer.shop_slots import VANILLA_SHOP_LOGIC_ITEMS
from oot_randomizer.world_logic import (
    DEFAULT_WORLD_PATH,
    TOTAL_TOKENS,
    LogicError,
    evaluate,
    load_world,
    logic_files,
    parse_requirement,
    resolve_item,
)


def _world(text: str):
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "world.toml"
        path.write_text(text, encoding="utf-8")
        return load_world(path)


class RequirementTests(unittest.TestCase):
    def test_friendly_and_actor_names_resolve(self):
        self.assertEqual(resolve_item("Bow"), "Item_Range_Bow")
        self.assertEqual(resolve_item("Zeldas_Lullaby"), "Item_Melody_ZeldaLullaby")
        self.assertEqual(resolve_item("Kokiri_Sword"), "Item_Sword_Kokiri")
        self.assertEqual(resolve_item("Item_Hookshot"), "Item_Hookshot")
        self.assertEqual(resolve_item("Sticks"), "Item_DekuStickBundle_Small")
        self.assertIsNone(resolve_item("Hookshoot"))

    def test_and_binds_tighter_than_or(self):
        world = _world(
            '[settings]\ngoal = "Bow or Hookshot and Longshot"\n'
            '[regions.Root.locations]\n'
        )
        self.assertEqual(world.errors, [])
        has = lambda *items: evaluate(world.goal, Counter(items), set(), "child", {})  # noqa: E731
        self.assertTrue(has("Item_Range_Bow"))
        self.assertFalse(has("Item_Hookshot"))
        self.assertTrue(has("Item_Hookshot", "Item_Longshot"))

    def test_counts_and_parse_errors(self):
        node = parse_requirement("Bombchus:2")
        self.assertEqual(node, ("name", "Bombchus", 2))
        for bad in ("Bow and", "(Bow", "Bow Hookshot", "Bow & Hookshot", ""):
            with self.assertRaises(LogicError):
                parse_requirement(bad)

    def test_unknown_names_and_bad_exits_are_reported(self):
        world = _world(
            '[regions.Root.exits]\nNowhere = "true"\n'
            '[regions.Root.locations]\nA = "Hookshoot"\n'
        )
        self.assertTrue(any("Hookshoot" in e for e in world.errors))
        self.assertTrue(any("Nowhere" in e for e in world.errors))


class HelperTests(unittest.TestCase):
    HELPERS = (
        '[helpers]\n'
        'has_ocarina = "Fairy_Ocarina or Ocarina_of_Time"\n'
        '"can_play(song)" = "has_ocarina and song"\n'
        'lift = "Goron_Bracelet or (is_adult and Silver_Gauntlets)"\n'
        'has_bombs = "Bomb_Bag and lift"\n'
        '[regions.Root.exits]\n'
    )

    def _check(self, text: str, items, age="child", events=()):
        world = _world(text)
        self.assertEqual(world.errors, [])
        return evaluate(world.goal, Counter(items), set(events), age, {})

    def test_plain_and_nested_helpers_inline(self):
        text = self.HELPERS + '[settings]\ngoal = "has_bombs"\n'
        self.assertFalse(self._check(text, ["Item_BombBag_Small"]))
        self.assertTrue(self._check(text, ["Item_BombBag_Small", "Item_Gauntlet_Goron"]))
        self.assertFalse(self._check(text, ["Item_BombBag_Small", "Item_Gauntlet_Silver"], age="child"))
        self.assertTrue(self._check(text, ["Item_BombBag_Small", "Item_Gauntlet_Silver"], age="adult"))

    def test_helper_arguments_are_substituted(self):
        text = self.HELPERS + '[settings]\ngoal = "can_play(Song_of_Storms or Zeldas_Lullaby)"\n'
        self.assertFalse(self._check(text, ["Item_Melody_StormSong"]))
        self.assertTrue(self._check(text, ["Item_Melody_StormSong", "Item_Ocarina_Fairy"]))
        self.assertTrue(self._check(text, ["Item_Melody_ZeldaLullaby", "Item_Ocarina_Time"]))

    def test_can_light_accepts_sticks_or_din_fire(self):
        text = (
            '[helpers]\ncan_light = "Sticks or Dins_Fire"\n'
            '[settings]\ngoal = "can_light"\n[regions.Root.exits]\n'
        )
        self.assertTrue(self._check(text, ["Item_DekuStickBundle_Small"]))
        self.assertTrue(self._check(text, ["Item_DinFire"]))
        self.assertFalse(self._check(text, []))

    def test_helper_items_count_as_progression(self):
        world = _world(self.HELPERS + '[settings]\ngoal = "can_play(Song_of_Time)"\n')
        self.assertTrue({"Item_Ocarina_Fairy", "Item_Ocarina_Time", "Item_Melody_TimeSong"} <= world.referenced_items)

    def test_with_requirements_understands_helpers(self):
        world = _world(self.HELPERS + '[regions.Root.locations]\nA = "true"\n')
        seed = world.with_requirements({"A": "can_play(Song_of_Time)"})
        self.assertNotIn("A", seed.explore({"A": None}).locations)
        self.assertIn("A", seed.explore({"A": None}, extra_items=Counter(
            {"Item_Ocarina_Fairy": 1, "Item_Melody_TimeSong": 1})).locations)

    def test_helper_errors(self):
        cases = {
            '[helpers]\na = "b"\nb = "a"\n': "loop",
            '[helpers]\na = "a"\n': "loop",
            '[helpers]\nBow = "true"\n': "already an item",
            '[helpers]\n"f(x)" = "x"\n[settings]\ngoal = "f"\n': "needs 1 argument",
            '[helpers]\n"f(x)" = "x"\n[settings]\ngoal = "f(Bow, Hookshot)"\n': "takes 1 argument",
            '[settings]\ngoal = "nope(Bow)"\n': "unknown helper",
            '[helpers]\na = "Hookshoot"\n': "unknown name 'Hookshoot'",
            '[helpers]\n"bad name" = "true"\n': "name must look like",
        }
        for text, expected in cases.items():
            world = _world(text + '[regions.Root]\n')
            self.assertTrue(any(expected in e for e in world.errors), (text, world.errors))

    def test_comma_only_inside_calls(self):
        with self.assertRaises(LogicError):
            parse_requirement("Bow, Hookshot")
        with self.assertRaises(LogicError):
            parse_requirement("Bombchus:2(Bow)")

    def test_split_files_reject_duplicate_helpers(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "a.toml").write_text('[helpers]\nx = "true"\n[regions.Root]\n', encoding="utf-8")
            Path(d, "b.toml").write_text('[helpers]\n"x(y)" = "y"\n', encoding="utf-8")
            with self.assertRaises(LogicError) as ctx:
                load_world(Path(d))
            self.assertIn("a.toml", str(ctx.exception))
            self.assertIn("b.toml", str(ctx.exception))


class ExploreTests(unittest.TestCase):
    WORLD = """
[settings]
time_travel = "Time_Travel"
goal = "Done"
[regions.Root.exits]
Forest = "true"
Temple = "Bow"
[regions.Forest.locations]
F1 = "true"
F2 = "is_adult"
[regions.Forest.events]
Time_Travel = "Hookshot"
[regions.Temple.locations]
T1 = "true"
[regions.Temple.events]
Done = "is_adult"
"""

    def test_items_events_and_time_travel_unlock_progress(self):
        world = _world(self.WORLD)
        self.assertEqual(world.errors, [])
        res = world.explore({"F1": "Item_Hookshot", "F2": "Item_Range_Bow", "T1": "TBox_Rupee_Red"})
        self.assertEqual(res.locations, {"F1", "F2", "T1"})
        self.assertTrue(world.goal_met(res))

    def test_blocked_seed_is_detected(self):
        world = _world(self.WORLD)
        res = world.explore({"F1": "Item_Range_Bow", "F2": "Item_Hookshot", "T1": "TBox_Rupee_Red"})
        self.assertNotIn("F2", res.locations)
        self.assertFalse(world.goal_met(res))

    def test_unlisted_locations_count_as_reachable(self):
        world = _world(self.WORLD)
        res = world.explore({"F1": "TBox_Rupee_Red", "Elsewhere": "Item_Hookshot", "F2": "Item_Range_Bow"})
        self.assertIn("Elsewhere", res.locations)
        self.assertIn("F2", res.locations)


@unittest.skipUnless(load_default_slots(), "chest_locations_summary.json not available")
class TemplatePlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.slots = load_default_slots()
        cls.world = _world(build_template(cls.slots))
        cls.world.check_locations(known_locations(cls.slots))

    def test_template_is_valid_and_vanilla_is_beatable(self):
        self.assertEqual(self.world.errors, [])
        vanilla = {s.name: s.vanilla_item for s in self.slots}
        vanilla |= {song_location_name(f): s for f, s in SONG_SLOTS.items()}
        vanilla |= {event_location_name(f): item for f, item in EVENT_SLOTS.items()}
        vanilla |= {loc: slot.item for loc, slot in NPC_SLOTS.items()}
        vanilla |= {skull_location_name(n): i for n, i in SKULL_REWARDS.items()}
        res = self.world.explore(vanilla, {"bombchus_in_logic": True})
        self.assertTrue(self.world.goal_met(res))
        self.assertEqual(set(vanilla) - res.locations, set())

    def test_planned_seeds_are_beatable_permutations(self):
        options = PlanOptions()
        pool = Counter([s.vanilla_item for s in self.slots] + list(SKULL_REWARDS.values())
                       + list(SONG_SLOTS.values()) + list(EVENT_SLOTS.values())
                       + [s.item for s in NPC_SLOTS.values()])
        for seed in range(15):
            plan = plan_seed(seed, self.slots, self.world, options)
            placed = {s.name: item for s, item in plan.chest_assignments}
            placed |= {song_location_name(f): s for f, s in plan.song_assignments.items()}
            placed |= {event_location_name(f): item for f, item in plan.event_assignments.items()}
            placed |= plan.npc_assignments
            placed |= {skull_location_name(n): i for n, i in plan.skull_assignments.items()}
            res = self.world.explore(placed, options.logic_options)
            # Every pool item is placed exactly once, in any kind of location.
            self.assertEqual(Counter(placed.values()), pool, f"seed {seed}")
            self.assertTrue(self.world.goal_met(res), f"seed {seed}")
            self.assertEqual(set(placed) - res.locations, set(), f"seed {seed}")

    def test_excluded_region_keeps_vanilla_items(self):
        plan = plan_seed(3, self.slots, self.world, PlanOptions())
        for slot, item in plan.chest_assignments:
            if slot.scene == "BossRushIntervalRoom":
                self.assertEqual(item, slot.vanilla_item)

    def test_one_major_per_dungeon(self):
        dungeon_of = self.world.dungeon_locations
        majors = MAJOR_ITEM_ACTORS | set(SONG_SLOTS.values())
        for seed in range(10):
            plan = plan_seed(seed, self.slots, self.world, PlanOptions(one_major_per_dungeon=True))
            placed = {s.name: item for s, item in plan.chest_assignments}
            placed |= {song_location_name(f): s for f, s in plan.song_assignments.items()}
            per_dungeon = Counter(dungeon_of[loc] for loc, item in placed.items() if loc in dungeon_of and item in majors)
            self.assertTrue(all(n <= 1 for n in per_dungeon.values()), per_dungeon)

    def test_impossible_rules_raise(self):
        text = build_template(self.slots).replace('goal = "Ganon_Defeated"', 'goal = "false"')
        world = _world(text)
        with self.assertRaises(PlanningError):
            plan_seed(1, self.slots, world, PlanOptions(max_attempts=3))


@unittest.skipUnless(load_default_slots(), "chest_locations_summary.json not available")
class ShippedWorldTests(unittest.TestCase):
    """logic/world/ is hand-edited, so guard against typos and unwinnable rules."""

    @classmethod
    def setUpClass(cls):
        cls.slots = load_default_slots()
        cls.world = load_world()
        cls.world.check_locations(known_locations(cls.slots))

    def test_default_is_the_split_directory(self):
        self.assertTrue(DEFAULT_WORLD_PATH.is_dir())
        self.assertGreater(len(logic_files(DEFAULT_WORLD_PATH)), 1)
        self.assertEqual(len(self.world.token_locations), TOTAL_TOKENS)
        self.assertEqual(self.world.warnings, [])

    def test_world_has_no_errors_and_vanilla_is_beatable(self):
        self.assertEqual(self.world.errors, [])
        vanilla = {s.name: s.vanilla_item for s in self.slots}
        vanilla |= {song_location_name(f): s for f, s in SONG_SLOTS.items()}
        vanilla |= {event_location_name(f): item for f, item in EVENT_SLOTS.items()}
        vanilla |= {loc: slot.item for loc, slot in NPC_SLOTS.items()}
        vanilla |= {skull_location_name(n): i for n, i in SKULL_REWARDS.items()}
        vanilla |= {loc: TOKEN_ITEM for loc in self.world.token_locations}
        vanilla |= VANILLA_SHOP_LOGIC_ITEMS
        res = self.world.explore(vanilla, {"bombchus_in_logic": True})
        self.assertTrue(self.world.goal_met(res))
        self.assertEqual(set(vanilla) - res.locations, set())
        self.assertEqual(res.items[TOKEN_ITEM], TOTAL_TOKENS)

    def test_child_bolero_warp_needs_a_second_warp_song(self):
        crater = self.world.global_exits["DeathMountainCraterInner"]

        def can_enter(age, *songs):
            items = Counter({resolve_item("Fairy_Ocarina"): 1} | {resolve_item(s): 1 for s in songs})
            return evaluate(crater, items, set(), age, {})

        bolero, requiem = "Bolero_of_Fire", "Requiem_of_Spirit"
        self.assertFalse(can_enter("child", bolero, requiem))
        self.assertFalse(can_enter("child", bolero))
        self.assertTrue(can_enter("child", bolero, "Nocturne_of_Shadow"))
        self.assertTrue(can_enter("child", bolero, "Prelude_of_Light"))
        self.assertTrue(can_enter("adult", bolero))

    def test_planned_seeds_are_beatable(self):
        options = PlanOptions()
        for seed in range(10):
            plan = plan_seed(seed, self.slots, self.world, options)
            placed = {s.name: item for s, item in plan.chest_assignments}
            placed |= {song_location_name(f): s for f, s in plan.song_assignments.items()}
            placed |= {event_location_name(f): item for f, item in plan.event_assignments.items()}
            placed |= plan.npc_assignments
            placed |= {skull_location_name(n): i for n, i in plan.skull_assignments.items()}
            placed |= {loc: TOKEN_ITEM for loc in self.world.token_locations}
            placed |= {loc: item for loc, item, _ in plan.shop_assignments}
            placed |= dict(plan.heart_assignments)
            world = self.world.with_requirements(plan.extra_requirements)
            res = world.explore(placed, options.logic_options)
            self.assertTrue(world.goal_met(res), f"seed {seed}")
            self.assertEqual(set(placed) - res.locations, set(), f"seed {seed}")


class DirectoryLoadingTests(unittest.TestCase):
    def _load(self, files: dict[str, str]):
        with tempfile.TemporaryDirectory() as d:
            for name, text in files.items():
                path = Path(d) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            return load_world(Path(d))

    SETTINGS = '[settings]\ngoal = "Done"\n'
    FOREST = (
        '[regions.Root.exits]\nForest = "true"\n'
        '[regions.Forest]\n'
        '[regions.Forest.locations]\nF1 = "true"\n'
        '[regions.Forest.skulltulas]\n"GS Forest" = "true"\n'
    )
    TEMPLE = (
        '[regions.Root.exits]\nTemple = "Bow"\n'
        '[regions.Temple]\ndungeon = true\n'
        '[regions.Temple.events]\nDone = "true"\n'
        '[regions.Temple.locations]\nT1 = "true"\n'
    )

    def test_directory_is_loaded_recursively_and_merged(self):
        world = self._load({
            "_settings.toml": self.SETTINGS,
            "overworld/Forest.toml": self.FOREST,
            "dungeons/Temple.toml": self.TEMPLE,
            "notes.txt": "not logic",
        })
        self.assertEqual(world.errors, [])
        self.assertEqual(set(world.regions["Root"].exits), {"Forest", "Temple"})
        self.assertEqual(world.location_region, {"F1": "Forest", "GS Forest": "Forest", "T1": "Temple"})
        self.assertEqual(world.token_locations, {"GS Forest"})
        self.assertTrue(world.regions["Temple"].dungeon)
        res = world.explore({"F1": "Item_Range_Bow", "T1": "TBox_Rupee_Red"})
        self.assertTrue(world.goal_met(res))

    def test_region_tables_deep_merge_across_files(self):
        world = self._load({
            "_settings.toml": self.SETTINGS,
            "a/Temple.toml": self.TEMPLE,
            "b/TempleExtra.toml": (
                '[regions.Temple]\ndungeon = true\n'
                '[regions.Temple.locations]\nT2 = "Hookshot"\n'
                '[regions.Temple.exits]\nRoot = "true"\n'
            ),
        })
        self.assertEqual(world.errors, [])
        temple = world.regions["Temple"]
        self.assertEqual(set(temple.locations), {"T1", "T2"})
        self.assertEqual(set(temple.events), {"Done"})
        self.assertEqual(set(temple.exits), {"Root"})
        self.assertTrue(temple.dungeon)

    def test_duplicate_key_names_both_files(self):
        with self.assertRaises(LogicError) as ctx:
            self._load({
                "_settings.toml": self.SETTINGS,
                "overworld/Forest.toml": self.FOREST,
                "overworld/Forest2.toml": '[regions.Root.exits]\nForest = "Bow"\n',
            })
        msg = str(ctx.exception)
        self.assertIn("overworld/Forest.toml", msg)
        self.assertIn("overworld/Forest2.toml", msg)
        self.assertIn("Forest", msg)

    def test_conflicting_flag_is_an_error(self):
        with self.assertRaises(LogicError) as ctx:
            self._load({
                "_settings.toml": self.SETTINGS,
                "dungeons/Temple.toml": self.TEMPLE,
                "overworld/Temple.toml": '[regions.Temple]\ndungeon = false\n',
            })
        msg = str(ctx.exception)
        self.assertIn("dungeon", msg)
        self.assertIn("dungeons/Temple.toml", msg)
        self.assertIn("overworld/Temple.toml", msg)

    def test_settings_only_in_one_file(self):
        with self.assertRaises(LogicError) as ctx:
            self._load({"_settings.toml": self.SETTINGS, "x/Forest.toml": self.SETTINGS + self.FOREST})
        self.assertIn("_settings.toml", str(ctx.exception))
        self.assertIn("x/Forest.toml", str(ctx.exception))

    def test_single_file_and_split_directory_load_the_same(self):
        def body(text: str) -> str:
            return text.split("\n", 2)[2]  # drop the Root exit lines

        single = _world(self.SETTINGS + '[regions.Root.exits]\nForest = "true"\nTemple = "Bow"\n'
                        + body(self.FOREST) + body(self.TEMPLE))
        split = self._load({"_settings.toml": self.SETTINGS, "Forest.toml": self.FOREST, "Temple.toml": self.TEMPLE})
        self.assertEqual(single.errors, [])
        self.assertEqual(single.regions, split.regions)
        self.assertEqual(single.token_locations, split.token_locations)

    def test_empty_directory_is_an_error(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(LogicError):
            load_world(Path(d))

    def test_top_level_exit_reaches_region_without_a_direct_exit(self):
        world = self._load({
            "_settings.toml": self.SETTINGS,
            "_warps.toml": '[exits]\nForest = "true"\n',
            "overworld/Forest.toml": '[regions.Forest]\n[regions.Forest.locations]\nF1 = "true"\n',
            "dungeons/Temple.toml": self.TEMPLE,
        })
        self.assertEqual(world.errors, [])
        self.assertEqual(set(world.regions["Root"].exits), {"Temple"})
        self.assertIn("Forest", world.global_exits)
        res = world.explore({"F1": "Item_Range_Bow", "T1": "TBox_Rupee_Red"})
        self.assertIn("F1", res.locations)

    def test_duplicate_top_level_exit_names_both_files(self):
        with self.assertRaises(LogicError) as ctx:
            self._load({
                "_settings.toml": self.SETTINGS,
                "_warps.toml": '[exits]\nForest = "true"\n',
                "_more_warps.toml": '[exits]\nForest = "Bow"\n',
            })
        msg = str(ctx.exception)
        self.assertIn("_warps.toml", msg)
        self.assertIn("_more_warps.toml", msg)

    def test_top_level_exit_to_undefined_region_is_an_error(self):
        world = self._load({
            "_settings.toml": self.SETTINGS,
            "_warps.toml": '[exits]\nNowhere = "true"\n',
            "overworld/Forest.toml": self.FOREST,
        })
        self.assertTrue(any("Nowhere" in e for e in world.errors), world.errors)


class SmallKeyTests(unittest.TestCase):
    TEXT = (
        '[settings]\ngoal = "Done"\n'
        '[regions.Root.exits]\nTemple = "true"\n'
        '[regions.Temple]\ndungeon = true\n'
        '[regions.Temple.locations]\n'
        '"Temple Static room 1 #0 (Item_Dungeon_SmallKey)" = "true"\n'
        '"Temple Static room 2 #0 (Item_Dungeon_SmallKey)" = "true"\n'
        '[regions.Temple.events]\nDone = "Small_Key_Temple:2"\n'
    )
    KEY_1 = "Temple Static room 1 #0 (Item_Dungeon_SmallKey)"
    KEY_2 = "Temple Static room 2 #0 (Item_Dungeon_SmallKey)"

    def test_unplaced_small_keys_count_toward_their_dungeon(self):
        world = _world(self.TEXT)
        self.assertEqual(world.errors, [])
        res = world.explore({})
        self.assertEqual(res.items["Small_Key_Temple"], 2)
        self.assertTrue(world.goal_met(res))

    def test_generic_small_key_placement_counts_toward_the_chest_dungeon(self):
        world = _world(self.TEXT)
        res = world.explore({self.KEY_1: "Item_Dungeon_SmallKey"})
        self.assertEqual(res.items["Small_Key_Temple"], 2)
        self.assertEqual(res.items["Item_Dungeon_SmallKey"], 0)
        self.assertTrue(world.goal_met(res))

    def test_empty_placement_grants_no_key(self):
        world = _world(self.TEXT)
        res = world.explore({self.KEY_2: None})
        self.assertEqual(res.items["Small_Key_Temple"], 1)
        self.assertFalse(world.goal_met(res))

    def test_small_key_must_name_a_dungeon(self):
        world = _world(
            '[settings]\ngoal = "true"\n'
            '[regions.Root.exits]\nField = "true"\n'
            '[regions.Field]\n'
            '[regions.Field.events]\nDone = "Small_Key_Nowhere:1"\n'
        )
        self.assertTrue(any("Small_Key_Nowhere" in e for e in world.errors), world.errors)

    def test_rooms_sharing_a_dungeon_name_share_one_key_counter(self):
        world = _world(
            '[settings]\ngoal = "Done"\n'
            '[regions.Root.exits]\nTempleA = "true"\n'
            '[regions.TempleA]\ndungeon = "Temple"\n'
            '[regions.TempleA.exits]\nTempleB = "Small_Key_Temple:1"\n'
            '[regions.TempleA.locations]\n'
            '"Temple Static room 1 #0 (Item_Dungeon_SmallKey)" = "true"\n'
            '[regions.TempleB]\ndungeon = "Temple"\n'
            '[regions.TempleB.locations]\n'
            '"Temple Static room 2 #0 (Item_Dungeon_SmallKey)" = "true"\n'
            '[regions.TempleB.events]\nDone = "Small_Key_Temple:2"\n'
        )
        self.assertEqual(world.errors, [])
        res = world.explore({})
        self.assertEqual(res.items["Small_Key_Temple"], 2)
        self.assertNotIn("Small_Key_TempleA", res.items)
        self.assertTrue(world.goal_met(res))

    def test_dungeon_name_must_match_a_dungeon(self):
        world = _world(
            '[settings]\ngoal = "true"\n'
            '[regions.Root.exits]\nTemple = "true"\n'
            '[regions.Temple]\ndungeon = "Temple"\n'
            '[regions.Temple.events]\nDone = "Small_Key_Other:1"\n'
        )
        self.assertTrue(any("Small_Key_Other" in e for e in world.errors), world.errors)


class BossKeyTests(unittest.TestCase):
    TEXT = (
        '[settings]\ngoal = "Done"\n'
        '[regions.Root.exits]\nTemple = "true"\n'
        '[regions.Temple]\ndungeon = true\n'
        '[regions.Temple.locations]\n'
        '"Temple Static room 3 #0 (Item_Dungeon_BossKey)" = "true"\n'
        '[regions.Temple.events]\nDone = "Boss_Key_Temple"\n'
    )
    BOSS_KEY = "Temple Static room 3 #0 (Item_Dungeon_BossKey)"

    def test_unplaced_boss_key_counts_toward_its_dungeon(self):
        world = _world(self.TEXT)
        self.assertEqual(world.errors, [])
        res = world.explore({})
        self.assertEqual(res.items["Boss_Key_Temple"], 1)
        self.assertTrue(world.goal_met(res))

    def test_generic_boss_key_placement_counts_toward_the_chest_dungeon(self):
        world = _world(self.TEXT)
        res = world.explore({self.BOSS_KEY: "Item_Dungeon_BossKey"})
        self.assertEqual(res.items["Boss_Key_Temple"], 1)
        self.assertTrue(world.goal_met(res))

    def test_boss_key_must_name_a_dungeon(self):
        world = _world(
            '[settings]\ngoal = "true"\n'
            '[regions.Root.exits]\nField = "true"\n'
            '[regions.Field]\n'
            '[regions.Field.events]\nDone = "Boss_Key_Nowhere"\n'
        )
        self.assertTrue(any("Boss_Key_Nowhere" in e for e in world.errors), world.errors)


class SlotNameTests(unittest.TestCase):
    def test_static_and_dynamic_layers_get_distinct_names(self):
        summary = [
            {"scene_file": "Banc/A/Kokiri_Static.bcett.byml.zs", "chests": [{"room_index": 0, "vanilla_drop": "TBox_Rupee_Green"}]},
            {"scene_file": "Banc/A/Kokiri_Dynamic.bcett.byml.zs", "chests": [{"room_index": 0, "vanilla_drop": "TBox_Rupee_Green"}]},
        ]
        names = {s.name for s in load_chest_slots(summary)}
        self.assertEqual(names, {"Kokiri Static room 0 #0 (TBox_Rupee_Green)", "Kokiri Dynamic room 0 #0 (TBox_Rupee_Green)"})


if __name__ == "__main__":
    unittest.main()
