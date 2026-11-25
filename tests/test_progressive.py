"""Tests for progressive item families: the model, logic expansion, placement and chest flows."""

import unittest
from collections import Counter
from pathlib import Path

from evfl import EventFlow
from evfl.event import SubFlowEvent, SwitchEvent

from oot_randomizer import progressive, progressive_chests as pc
from oot_randomizer.byml7 import dump_byml7, parse_byml7
from oot_randomizer.engine import ChestSlot, build_shuffle_patches, load_default_slots
from oot_randomizer.planner import PlanOptions, plan_seed
from oot_randomizer.world_logic import DEFAULT_WORLD_PATH, load_world

REPO = Path(__file__).resolve().parents[1]
NUP = REPO.parent / "The Legend of Zelda Ocarina of Time + U2" / "The Legend of Zelda Ocarina of Time   U2.0.0.nup"
ZSDIC = REPO / "ZsDic.pack"


def _world(text: str):
    path = REPO / "tmp" / "progressive_world_test.toml"
    path.write_text(text, encoding="utf-8")
    try:
        return load_world(path)
    finally:
        path.unlink()


def _patcher():
    from oot_randomizer.nup_chest_patcher import NupChestPatcher

    return NupChestPatcher(NUP, ZSDIC.read_bytes())


class FamilyModelTests(unittest.TestCase):
    def test_families_follow_the_tier_order_of_the_randomizer(self):
        self.assertEqual(
            [f.key for f in progressive.FAMILIES],
            ["Hookshot", "Strength", "BombBag", "Bow", "Slingshot", "Wallet", "Scale", "NutBag", "StickBag",
             "Magic", "Ocarina"],
        )
        self.assertEqual(progressive.family("Hookshot").tiers, ("Item_Hookshot", "Item_Longshot"))
        self.assertEqual(progressive.family("Strength").tiers,
                         ("Item_Gauntlet_Goron", "Item_Gauntlet_Silver", "Item_Gauntlet_Gold"))

    def test_owners_match_tiers_and_copy_names_are_unique(self):
        for fam in progressive.FAMILIES:
            self.assertEqual(len(fam.owners), len(fam.tiers), fam.key)
            self.assertTrue(fam.copy.startswith("Progressive "), fam.copy)
        self.assertEqual(len({f.copy for f in progressive.FAMILIES}), len(progressive.FAMILIES))
        self.assertEqual(progressive.family("Strength").owners[0], "Armor_Child_Gauntlet_Goron")
        self.assertEqual(progressive.family("Bow").owners[0], "Weapon_Range_Bow")

    def test_tier_for_copy_counts_from_the_lowest_tier(self):
        self.assertEqual(progressive.tier_for_copy("Progressive Hookshot", 1), "Item_Hookshot")
        self.assertEqual(progressive.tier_for_copy("Progressive Hookshot", 2), "Item_Longshot")
        self.assertIsNone(progressive.tier_for_copy("Progressive Hookshot", 3))
        self.assertIsNone(progressive.tier_for_copy("Item_Hookshot", 1))

    def test_k_copies_expand_to_the_first_k_tiers(self):
        self.assertEqual(progressive.expand({"Progressive Hookshot": 1}), Counter({"Item_Hookshot": 1}))
        self.assertEqual(progressive.expand({"Progressive Hookshot": 2}),
                         Counter({"Item_Hookshot": 1, "Item_Longshot": 1}))
        self.assertEqual(progressive.expand({"Item_Bomb": 2, "Progressive Wallet": 0}), Counter({"Item_Bomb": 2}))

    def test_first_tier_is_what_a_chest_drops(self):
        self.assertEqual(progressive.first_tier("Progressive Strength Upgrade"), "Item_Gauntlet_Goron")
        self.assertEqual(progressive.first_tier("Item_Longshot"), "Item_Longshot")

    def test_only_complete_families_convert(self):
        pool = [("Item_Hookshot", "chest"), ("Item_Longshot", "chest"), ("Item_Wallet_Medium", "chest"), ("Item_Bomb", "chest")]
        converted = progressive.convert_pool(pool, True)
        self.assertEqual(converted, [("Progressive Hookshot", "chest"), ("Progressive Hookshot", "chest"),
                                     ("Item_Wallet_Medium", "chest"), ("Item_Bomb", "chest")])
        self.assertIs(progressive.convert_pool(pool, False), pool)

    def test_a_family_with_a_tier_outside_the_pool_stays_vanilla(self):
        pool = [("Item_Hookshot", "chest"), ("Item_Bomb", "chest")]
        self.assertEqual(progressive.convert_pool(pool, True), pool)

    def test_copies_with_any_finds_families_by_tier(self):
        self.assertEqual(progressive.copies_with_any({"Item_Longshot"}), {"Progressive Hookshot"})
        self.assertEqual(progressive.copies_with_any({"Item_Bomb"}), set())


class LogicExpansionTests(unittest.TestCase):
    WORLD = """
[settings]
goal = "Item_Longshot"
[regions.Root.locations]
L1 = "true"
L2 = "true"
"""

    def test_one_copy_is_not_enough_for_the_longshot(self):
        world = _world(self.WORLD)
        self.assertEqual(world.errors, [])
        self.assertFalse(world.goal_met(world.explore({"L1": "Progressive Hookshot", "L2": "Item_Bomb"})))

    def test_two_copies_give_the_hookshot_and_the_longshot(self):
        world = _world(self.WORLD)
        res = world.explore({"L1": "Progressive Hookshot", "L2": "Progressive Hookshot"})
        self.assertEqual(res.items["Item_Hookshot"], 1)
        self.assertTrue(world.goal_met(res))

    def test_assumed_copies_expand_the_same_way(self):
        world = _world(self.WORLD)
        res = world.explore({}, extra_items=Counter({"Progressive Hookshot": 2}))
        self.assertTrue(world.goal_met(res))

    def test_referenced_tiers_make_their_copy_a_progression_item(self):
        world = _world(self.WORLD)
        self.assertIn("Item_Longshot", world.referenced_items)
        self.assertIn("Progressive Hookshot", progressive.copies_with_any(world.referenced_items))


class ChainTests(unittest.TestCase):
    def test_ascending_chain_asks_each_lower_tier_then_gives_the_next(self):
        self.assertEqual(pc.ask_chain(2), [(0, ("give", 1), ("give", 0))])
        self.assertEqual(pc.ask_chain(3), [(0, ("ask", 1), ("give", 0)), (1, ("give", 2), ("give", 1))])

    def test_event_names_are_per_family_and_size(self):
        self.assertEqual(pc.event_name("Hookshot", "Small"), "OOTREM_Prog_Hookshot_Small")
        self.assertEqual(pc.entry_name("Hookshot"), "Success_Prog_Hookshot")
        self.assertEqual(pc.size_of("Obj_TBox_A_01"), "Small")
        self.assertEqual(pc.size_of("Obj_TBox_A_03_NoBake"), "Big")


@unittest.skipUnless(NUP.exists() and ZSDIC.exists(), "retail NUP or ZsDic.pack not present")
class ChestFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patcher = _patcher()

    def _flow(self, name):
        return self.patcher.read_file(name)

    def _run(self, flow, owned, entry_name):
        """Follow the chain from the entry with the given owned owner names; return the ContentName given."""
        entry = next(e for e in flow.flowchart.entry_points if e.name == entry_name)
        node = entry.main_event.v
        while isinstance(node.data, SwitchEvent):
            owner = node.data.params.data["ActorName"]
            node = node.data.cases[0 if owner in owned else 1].v
        self.assertIsInstance(node.data, SubFlowEvent)
        self.assertEqual(node.data.entry_point_name, pc.ROOT_ENTRY)
        return node.data.params.data["ContentName"]

    def test_small_and_big_flows_gain_one_entry_per_family(self):
        for name in (pc.SMALL_FLOW, pc.BIG_FLOW):
            raw = self._flow(name)
            out = pc.wrap_flow_bytes(raw, ["Hookshot", "Strength"])
            flow = EventFlow()
            flow.read(out)
            names = [e.name for e in flow.flowchart.entry_points]
            self.assertIn("Success_Prog_Hookshot", names)
            self.assertIn("Success_Prog_Strength", names)
            self.assertEqual(pc.wrap_flow_bytes(out, ["Hookshot", "Strength"]), out, "wrapping twice is a no-op")

    def test_chain_gives_the_lowest_unowned_tier(self):
        flow = EventFlow()
        flow.read(pc.wrap_flow_bytes(self._flow(pc.SMALL_FLOW), ["Hookshot", "Strength"]))
        hook = progressive.family("Hookshot")
        self.assertEqual(self._run(flow, set(), "Success_Prog_Hookshot"), "Item_Hookshot")
        self.assertEqual(self._run(flow, {hook.owners[0]}, "Success_Prog_Hookshot"), "Item_Longshot")
        strength = progressive.family("Strength")
        self.assertEqual(self._run(flow, set(), "Success_Prog_Strength"), strength.tiers[0])
        self.assertEqual(self._run(flow, {strength.owners[0]}, "Success_Prog_Strength"), strength.tiers[1])
        self.assertEqual(self._run(flow, set(strength.owners[:2]), "Success_Prog_Strength"), strength.tiers[2])

    def test_the_original_success_entry_is_kept(self):
        raw = self._flow(pc.BIG_FLOW)
        flow = EventFlow()
        flow.read(pc.wrap_flow_bytes(raw, ["Bow"]))
        self.assertTrue(any(e.name == pc.ROOT_ENTRY for e in flow.flowchart.entry_points))

    def test_retarget_marks_a_chest_without_a_named_event(self):
        raw = self._flow("DodongoCavern_Static.bcett.byml.zs")
        self.assertNotIn(("DodongoCavern_Static.bcett.byml.zs", 0), pc.NAMED_EVENT_CHESTS)
        used: set = set()
        out = pc.retarget_chests(raw, {0: "Hookshot"}, used)
        root = parse_byml7(out)
        chest = pc.chest_actors(root)[0]
        self.assertEqual(chest["Dynamic"]["GetEventName"], pc.event_name("Hookshot", pc.size_of(chest["Gyaml"])))
        self.assertEqual(chest["Dynamic"]["Drop__DropActor"], "Item_Hookshot")
        self.assertEqual(len(used), 1)

    def test_every_named_chest_is_refused(self):
        raw = self._flow("DodongoCavern_Static.bcett.byml.zs")
        with self.assertRaises(pc.ProgressiveChestError):
            pc.retarget_chests(raw, {2: "BombBag"}, set())

    def test_rstbl_rows_are_added_from_the_template(self):
        table = parse_byml7(self._flow(pc.SETTING_TABLE))
        rows = pc.add_rows(table, pc.SMALL_TEMPLATE, [("OOTREM_Prog_Hookshot_Small", pc.entry_name("Hookshot"))])
        self.assertEqual(rows, 1)
        added = next(r for r in table if r["__RowId"] == "OOTREM_Prog_Hookshot_Small")
        base = next(r for r in table if r["__RowId"] == pc.SMALL_TEMPLATE)
        self.assertEqual(added["EntryPointName"], "Success_Prog_Hookshot")
        self.assertEqual(added["FlowchartFileName"], base["FlowchartFileName"])
        self.assertEqual(len(parse_byml7(dump_byml7(table))), len(table))


class ChestTableTests(unittest.TestCase):
    ROOM_ROWS = [
        {"__RowId": "Dm_SY_Treasurebox", "EntryPointName": "Success", "FlowchartFileName": "Big.bfevfl"},
        {"__RowId": "Dm_SY_TreasureboxSmall", "EntryPointName": "Success", "FlowchartFileName": "Small.bfevfl"},
        {"__RowId": "Z_Other", "EntryPointName": "Success", "FlowchartFileName": "Z.bfevfl"},
    ]

    def test_rows_insert_in_order_and_replace_existing_ids(self):
        rows = [dict(r) for r in self.ROOM_ROWS]
        pc.add_rows(rows, "Dm_SY_TreasureboxSmall", [("OOTREM_Prog_Bow_Small", "Success_Prog_Bow")])
        pc.add_rows(rows, "Dm_SY_TreasureboxSmall", [("OOTREM_Prog_Bow_Small", "Success_Prog_Bow")])
        ids = [r["__RowId"] for r in rows]
        self.assertEqual(ids.count("OOTREM_Prog_Bow_Small"), 1)
        self.assertEqual(ids, sorted(ids))

    def test_a_missing_template_row_is_an_error(self):
        with self.assertRaises(pc.ProgressiveChestError):
            pc.add_rows([dict(r) for r in self.ROOM_ROWS], "Nope", [("X", None)])

    def test_retarget_writes_both_sizes_and_keeps_other_chests(self):
        root = {"Actors": [
            {"Gyaml": "Obj_TBox_A_01", "Dynamic": {"Drop__DropActor": "Item_Longshot", "DefaultDungeonRoomIndex": 1}},
            {"Gyaml": "Prop_Rock", "Dynamic": {"Drop__DropActor": "Item_Bomb"}},
            {"Gyaml": "Obj_TBox_A_02", "Dynamic": {"Drop__DropActor": "Item_Bomb"}},
            {"Gyaml": "Obj_TBox_A_02", "Dynamic": {"Drop__DropActor": "Item_Bomb", "GetEventName": "Keep"}},
        ]}
        used: set = set()
        raw = dump_byml7(root)
        out = pc.retarget_chests(raw, {0: "Hookshot", 1: "Hookshot"}, used)
        self.assertEqual(used, {("Hookshot", "Small"), ("Hookshot", "Big")})
        actors = parse_byml7(out)["Actors"]
        self.assertEqual(actors[0]["Dynamic"]["GetEventName"], "OOTREM_Prog_Hookshot_Small")
        self.assertEqual(actors[0]["Dynamic"]["Drop__DropActor"], "Item_Hookshot")
        self.assertEqual(actors[0]["Dynamic"]["DefaultDungeonRoomIndex"], 1)
        self.assertNotIn("GetEventName", actors[1]["Dynamic"])
        self.assertEqual(actors[2]["Dynamic"]["GetEventName"], "OOTREM_Prog_Hookshot_Big")

    def test_out_of_range_and_already_named_chests_are_errors(self):
        root = {"Actors": [{"Gyaml": "Obj_TBox_A_01", "Dynamic": {"Drop__DropActor": "Item_Bomb", "GetEventName": "X"}}]}
        raw = dump_byml7(root)
        with self.assertRaises(pc.ProgressiveChestError):
            pc.retarget_chests(raw, {0: "Hookshot"}, set())
        with self.assertRaises(pc.ProgressiveChestError):
            pc.retarget_chests(dump_byml7({"Actors": []}), {0: "Hookshot"}, set())

    def test_progressive_targets_list_every_scene_of_a_copy(self):
        slot = ChestSlot("s", "Item_Longshot", 1, (("A_Child.bcett.byml.zs", 3), ("A_Adult.bcett.byml.zs", 2)))
        other = ChestSlot("t", "Item_Bomb", 1, (("B.bcett.byml.zs", 0),))
        targets = pc.progressive_targets([(slot, "Progressive Hookshot"), (other, "Item_Bomb")])
        self.assertEqual(targets, [("A_Child.bcett.byml.zs", 3, "Hookshot"), ("A_Adult.bcett.byml.zs", 2, "Hookshot")])

    def test_named_chests_are_excluded_from_copies(self):
        scene, order = next(iter(pc.NAMED_EVENT_CHESTS))
        named = ChestSlot("named", "Item_Bomb", 1, ((scene, order),))
        plain = ChestSlot("plain", "Item_Bomb", 1, (("Nowhere.bcett.byml.zs", 0),))
        self.assertEqual(pc.excluded_slots([named, plain]), frozenset({"named"}))
        self.assertEqual(len(pc.NAMED_EVENT_CHESTS), 49)


class PlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.slots = load_default_slots()
        cls.excluded = pc.excluded_slots(cls.slots)

    def _plan(self, seed, enabled):
        options = PlanOptions(progressive_items=enabled,
                              progressive_excluded=self.excluded if enabled else frozenset())
        return plan_seed(seed, self.slots, None, options)

    def test_copies_are_only_placed_in_chest_locations(self):
        plan = self._plan(7, True)
        copies = [i for _, i in plan.chest_assignments if progressive.is_copy(i)]
        self.assertTrue(copies)
        for loc in (plan.song_assignments, plan.event_assignments, plan.npc_assignments, plan.skull_assignments):
            self.assertFalse(any(progressive.is_copy(i) for i in loc.values()))
        self.assertFalse(any(progressive.is_copy(i) for _, i, _ in plan.shop_assignments))
        self.assertFalse(any(progressive.is_copy(i) for _, i in plan.heart_assignments))

    def test_copies_never_take_a_named_chest(self):
        for seed in (1, 2, 3):
            plan = self._plan(seed, True)
            for slot, item in plan.chest_assignments:
                if progressive.is_copy(item):
                    self.assertNotIn(slot.name, self.excluded)

    def test_no_family_gets_more_copies_than_it_has_tiers(self):
        plan = self._plan(5, True)
        copies = Counter(i for _, i in plan.chest_assignments if progressive.is_copy(i))
        for name, n in copies.items():
            self.assertLessEqual(n, len(progressive.family_of_copy(name).tiers), name)
        self.assertEqual(len(plan.chest_assignments), len(self._plan(5, False).chest_assignments))

    def test_every_copy_lands_in_a_plain_chest_with_the_shipped_logic(self):
        world = load_world(DEFAULT_WORLD_PATH)
        options = PlanOptions(progressive_items=True, progressive_excluded=self.excluded)
        plan = plan_seed(3, self.slots, world, options)
        copies = Counter(i for _, i in plan.chest_assignments if progressive.is_copy(i))
        # With the default settings every family is complete, so every tier is one copy in the pool.
        self.assertEqual(sum(copies.values()), sum(len(f.tiers) for f in progressive.FAMILIES))
        self.assertFalse(any(progressive.is_copy(i) for i in plan.skull_assignments.values()))
        self.assertEqual(plan.unreachable, [])

    def test_flag_off_keeps_the_patch_records_identical(self):
        off = self._plan(9, False)
        mapped = [(slot, progressive.first_tier(item)) for slot, item in off.chest_assignments]
        self.assertEqual(build_shuffle_patches(mapped), build_shuffle_patches(off.chest_assignments))
        self.assertEqual(pc.progressive_targets(off.chest_assignments), [])
        self.assertEqual(progressive.convert_pool([("Item_Hookshot", "chest")], False), [("Item_Hookshot", "chest")])


if __name__ == "__main__":
    unittest.main()
