"""Tests for Gold Skulltula logic and House of Skulltula reward shuffle."""

import tempfile
import unittest
from collections import Counter
from pathlib import Path

from oot_randomizer.engine import ChestSlot
from oot_randomizer.item_ids import MAJOR_ITEM_ACTORS
from oot_randomizer.planner import PlanOptions, known_locations, plan_seed
from oot_randomizer.skulltula_rewards import (
    SKULL_LOCATIONS,
    SKULL_REWARDS,
    TOKEN_ITEM,
    can_hand_over,
    patch_skull_rewards,
    skull_location_name,
)
from oot_randomizer.songs import SONG_SLOTS, song_location_name
from oot_randomizer.world_logic import load_world

RAW_FLOW = Path(
    r"C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405\files\raw\GatheringTokenGold.bfevfl"
)

CHESTS = {
    "Field chest 1": ("Field", "Item_Hookshot"),
    "Field chest 2": ("Field", "TBox_Rupee_Red"),
    "Field chest 3": ("Field", "TBox_Rupee_Blue"),
    "Field chest 4": ("Field", "TBox_Rupee_Green"),
    "Town chest 1": ("Town", "Item_Range_Bow"),
    "Town chest 2": ("Town", "TBox_Rupee_Red"),
    "Dungeon chest 1": ("Dungeon", "Item_Hammer"),
    "Dungeon chest 2": ("Dungeon", "TBox_Rupee_Blue"),
    "Dungeon chest 3": ("Dungeon", "TBox_Rupee_Green"),
}
SLOTS = [ChestSlot(name, item, 0, ((f"{region}.bcett.byml.zs", i),), region)
         for i, (name, (region, item)) in enumerate(CHESTS.items())]


def _world_text(skulltulas: bool = True) -> str:
    lines = [
        "[settings]",
        'goal = "Done"',
        "[regions.Root.exits]",
        'Field = "true"',
        'Town = "Hookshot"',
        'Dungeon = "Bow"',
        "[regions.Dungeon]",
        "dungeon = true",
        "[regions.Dungeon.events]",
        'Done = "Megaton_Hammer"',
    ]
    for region in ("Field", "Town", "Dungeon"):
        lines.append(f"[regions.{region}.locations]")
        lines += [f'"{name}" = "true"' for name, (r, _) in CHESTS.items() if r == region]
        if region == "Town":
            lines += [f'"{skull_location_name(n)}" = "Gold_Skulltula_Token:{n}"' for n in SKULL_REWARDS]
    if skulltulas:
        lines.append("[regions.Field.skulltulas]")
        lines += [f'"GS Field {i}" = "true"' for i in range(1, 31)]
        lines.append("[regions.Town.skulltulas]")
        lines += [f'"GS Town {i}" = "true"' for i in range(1, 21)]
    return "\n".join(lines) + "\n"


def _world(text: str):
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "world.toml"
        path.write_text(text, encoding="utf-8")
        return load_world(path)


def _placed(plan, world) -> dict[str, str]:
    placed = {s.name: item for s, item in plan.chest_assignments}
    placed |= {song_location_name(f): s for f, s in plan.song_assignments.items()}
    placed |= {skull_location_name(n): item for n, item in plan.skull_assignments.items()}
    placed |= {loc: TOKEN_ITEM for loc in world.token_locations}
    return placed


class SkulltulaWorldTests(unittest.TestCase):
    def setUp(self):
        self.world = _world(_world_text())
        self.world.check_locations(known_locations(SLOTS))

    def test_skulltulas_become_token_locations(self):
        self.assertEqual(self.world.errors, [])
        self.assertEqual(len(self.world.token_locations), 50)
        self.assertEqual(self.world.location_region["GS Town 3"], "Town")
        self.assertIn("GS Field 7", self.world.regions["Field"].locations)
        self.assertTrue(set(SKULL_LOCATIONS) <= set(self.world.location_region))

    def test_rewards_need_collected_tokens(self):
        vanilla = {s.name: s.vanilla_item for s in SLOTS}
        res = self.world.explore(vanilla)
        self.assertEqual(res.items[TOKEN_ITEM], 0)
        self.assertNotIn(skull_location_name(10), res.locations)
        res = self.world.explore(vanilla | {loc: TOKEN_ITEM for loc in self.world.token_locations})
        self.assertEqual(res.items[TOKEN_ITEM], 50)
        self.assertTrue(set(SKULL_LOCATIONS) <= res.locations)

    def test_world_without_skulltulas_assumes_tokens(self):
        world = _world(_world_text(skulltulas=False))
        self.assertEqual(world.token_locations, set())
        res = world.explore({s.name: s.vanilla_item for s in SLOTS})
        self.assertTrue(set(SKULL_LOCATIONS) <= res.locations)

    def test_known_locations_include_skull_rewards(self):
        self.assertTrue(set(SKULL_LOCATIONS) <= known_locations(SLOTS))


class SkullPlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = _world(_world_text())

    def test_planned_seeds_are_beatable(self):
        options = PlanOptions()
        for seed in range(40):
            plan = plan_seed(seed, SLOTS, self.world, options)
            placed = _placed(plan, self.world)
            res = self.world.explore(placed, options.logic_options)
            self.assertTrue(self.world.goal_met(res), f"seed {seed}")
            self.assertEqual(set(placed) - res.locations, set(), f"seed {seed}")
            self.assertEqual(plan.unreachable, [])
            self.assertEqual(
                sorted([i for _, i in plan.chest_assignments] + list(plan.skull_assignments.values())),
                sorted([s.vanilla_item for s in SLOTS] + list(SKULL_REWARDS.values())),
            )

    def test_skull_rewards_only_get_hand_over_items(self):
        moved = Counter()
        for seed in range(60):
            plan = plan_seed(seed, SLOTS, self.world, PlanOptions())
            self.assertEqual(set(plan.skull_assignments), set(SKULL_REWARDS))
            for tokens, item in plan.skull_assignments.items():
                self.assertTrue(can_hand_over(item), f"seed {seed}: {item} at {tokens}")
                moved[item != SKULL_REWARDS[tokens]] += 1
        self.assertGreater(moved[True], 0, "skull rewards were never shuffled")

    def test_tight_pool_never_dead_ends(self):
        # Besides progression, only the five vanilla rewards can be handed over; a naive
        # random fill would often strand them in chests.
        for seed in range(40):
            plan = plan_seed(seed, SLOTS, self.world, PlanOptions(max_attempts=1))
            self.assertTrue(all(can_hand_over(i) for i in plan.skull_assignments.values()))

    def test_tokens_stay_fixed(self):
        for seed in range(20):
            plan = plan_seed(seed, SLOTS, self.world, PlanOptions())
            self.assertNotIn(TOKEN_ITEM, [i for _, i in plan.chest_assignments])
            self.assertNotIn(TOKEN_ITEM, plan.skull_assignments.values())
            self.assertFalse(self.world.token_locations & {s.name for s, _ in plan.chest_assignments})

    def test_no_skull_shuffle_keeps_vanilla(self):
        for seed in range(10):
            plan = plan_seed(seed, SLOTS, self.world, PlanOptions(shuffle_skull_rewards=False))
            self.assertEqual(plan.skull_assignments, SKULL_REWARDS)
            self.assertEqual(sorted(i for _, i in plan.chest_assignments), sorted(s.vanilla_item for s in SLOTS))

    def test_one_major_per_dungeon_still_holds(self):
        dungeon_of = self.world.dungeon_locations
        majors = MAJOR_ITEM_ACTORS | set(SONG_SLOTS.values())
        for seed in range(30):
            plan = plan_seed(seed, SLOTS, self.world, PlanOptions(one_major_per_dungeon=True))
            placed = _placed(plan, self.world)
            per_dungeon = Counter(dungeon_of[l] for l, i in placed.items() if l in dungeon_of and i in majors)
            self.assertTrue(all(n <= 1 for n in per_dungeon.values()), per_dungeon)

    def test_without_world(self):
        for seed in range(10):
            plan = plan_seed(seed, SLOTS, None, PlanOptions(shuffle_heart_pieces=False))
            self.assertTrue(all(can_hand_over(i) for i in plan.skull_assignments.values()))


def _rewards_in(data: bytes) -> dict[int, str]:
    from evfl import EventFlow
    from evfl.event import ActionEvent, SubFlowEvent

    flow = EventFlow()
    flow.read(data)
    found: dict[int, str] = {}
    for event in flow.flowchart.events:
        body = event.data
        if not isinstance(body, SubFlowEvent) or not body.params or "TakenRewardActor" not in body.params.data:
            continue
        nxt = body.nxt.v
        if nxt is None or not isinstance(nxt.data, ActionEvent) or not nxt.data.params:
            continue
        flag = nxt.data.params.data.get("GameDataName")
        for tokens in SKULL_REWARDS:
            if flag == f"KakarikoVillage_GatheringTokenGold_GetReward{tokens}":
                found[tokens] = body.params.data["TakenRewardActor"]
    return found


@unittest.skipUnless(RAW_FLOW.exists(), "GatheringTokenGold.bfevfl not available")
class SkullFlowPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = RAW_FLOW.read_bytes()

    def test_vanilla_flow_matches_table(self):
        self.assertEqual(_rewards_in(self.data), SKULL_REWARDS)

    def test_empty_patch_round_trips(self):
        self.assertEqual(patch_skull_rewards(self.data, {}), self.data)

    def test_patch_is_visible_after_reparse(self):
        out = patch_skull_rewards(self.data, {20: "Item_Hookshot", 50: "Item_Range_Bow"})
        expected = dict(SKULL_REWARDS) | {20: "Item_Hookshot", 50: "Item_Range_Bow"}
        self.assertEqual(_rewards_in(out), expected)

    def test_unknown_slot_rejected(self):
        with self.assertRaises(ValueError):
            patch_skull_rewards(self.data, {100: "Item_Hookshot"})


if __name__ == "__main__":
    unittest.main()
