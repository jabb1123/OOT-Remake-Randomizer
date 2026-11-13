import io
import unittest
from collections import Counter
from pathlib import Path

from oot_randomizer.chest_events import SWORD_EVENT_FLOW
from oot_randomizer.engine import load_default_slots
from oot_randomizer.event_items import EVENT_SLOTS
from oot_randomizer.logic_template import NPC_LOCATIONS
from oot_randomizer.npc_grants import (
    NPC_FLOWS,
    NPC_ITEM_DISPLAY_NAMES,
    NPC_SLOTS,
    _grant_params,
    npc_location_name,
    disable_scrub_biggoron_sale,
    patch_npc_grant,
    patch_npc_grants,
    shuffle_npc_items,
)
from oot_randomizer.planner import PlanOptions, known_locations, plan_seed
from oot_randomizer.skulltula_rewards import SKULL_FLOW
from oot_randomizer.songs import SONG_SLOTS
from oot_randomizer.stone_gates import STONE_GATE_FLOWS
from oot_randomizer.world_logic import DEFAULT_WORLD_PATH, _items_in, load_world

RAW_DIR = Path(
    r"C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405\files\raw"
)
HIT_TARGET = "MiniGame_HitTarget.bfevfl"
FISHING = "MiniGame_Fishing.bfevfl"
DM_LOST_WOOD = "Dm_LostWood_0040.bfevfl"
BIGGORON = "Npc_Goron_Biggoron_Adult.bfevfl"
SCRUB = "Enemy_Scrub_Business_Dream.bfevfl"
SCRUB_SWITCH = "Event42"


def _loc(raw_name: str, item: str) -> str:
    return npc_location_name(f"{raw_name}.zs", item)


def _load(data: bytes):
    from evfl import EventFlow

    flow = EventFlow()
    flow.read(data)
    return flow


def _serialize(flow) -> bytes:
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def _grant_values(data: bytes) -> list[str]:
    return [params[key] for params, key in _grant_params(_load(data))]


def _raw_or_skip(name: str) -> bytes:
    path = RAW_DIR / name
    if not path.exists():
        raise unittest.SkipTest(f"raw flow {name} not available")
    return path.read_bytes()


class SlotTableTest(unittest.TestCase):
    def test_eighteen_locations_one_per_flow_item_pair(self):
        self.assertEqual(len(NPC_SLOTS), 18)
        pairs = [(slot.flow, slot.item) for slot in NPC_SLOTS.values()]
        self.assertEqual(len(set(pairs)), 18)

    def test_flow_names_are_bfevfl_zs(self):
        for slot in NPC_SLOTS.values():
            self.assertTrue(slot.flow.endswith(".bfevfl.zs"), slot.flow)

    def test_every_item_has_a_display_name(self):
        self.assertEqual({slot.item for slot in NPC_SLOTS.values()}, set(NPC_ITEM_DISPLAY_NAMES))

    def test_location_names(self):
        self.assertEqual(
            npc_location_name("MiniGame_HitTarget.bfevfl.zs", "Item_Quiver_Large"),
            "MiniGame_HitTarget: Item_Quiver_Large (npc item)",
        )

    def test_npc_locations_are_known_to_planner(self):
        known = known_locations(load_default_slots())
        self.assertTrue(set(NPC_SLOTS) <= known)

    def test_flows_do_not_overlap_other_modules(self):
        taken = set(EVENT_SLOTS) | set(SONG_SLOTS) | set(STONE_GATE_FLOWS) | {SKULL_FLOW, SWORD_EVENT_FLOW}
        self.assertTrue(NPC_FLOWS.isdisjoint(taken), NPC_FLOWS & taken)

    def test_location_table_matches_slots(self):
        self.assertEqual(set(NPC_LOCATIONS), {(s.flow, s.item) for s in NPC_SLOTS.values()})


class PermutationTest(unittest.TestCase):
    def test_is_a_permutation_of_slot_items(self):
        shuffled = shuffle_npc_items(42)
        self.assertEqual(set(shuffled), set(NPC_SLOTS))
        self.assertEqual(Counter(shuffled.values()), Counter(s.item for s in NPC_SLOTS.values()))

    def test_deterministic_for_a_seed(self):
        self.assertEqual(shuffle_npc_items(9), shuffle_npc_items(9))

    def test_seeds_vary(self):
        self.assertNotEqual(shuffle_npc_items(1), shuffle_npc_items(2))


class PatchTest(unittest.TestCase):
    def test_round_trip_is_byte_equal_for_every_flow(self):
        for flow in sorted(NPC_FLOWS):
            with self.subTest(flow=flow):
                raw = _raw_or_skip(flow.removesuffix(".zs"))
                self.assertEqual(_serialize(_load(raw)), raw)

    def test_old_equals_new_returns_input(self):
        raw = _raw_or_skip(HIT_TARGET)
        self.assertIs(patch_npc_grants(raw, {"Item_Quiver_Large": "Item_Quiver_Large"}), raw)

    def test_repoint_changes_only_the_matching_grant(self):
        raw = _raw_or_skip(HIT_TARGET)
        before = _grant_values(raw)
        after = _grant_values(patch_npc_grant(raw, "Item_Quiver_Large", "Item_BombBag_Large"))
        self.assertEqual(
            after,
            ["Item_BombBag_Large" if v == "Item_Quiver_Large" else v for v in before],
        )

    def test_swap_of_medium_and_large_uses_original_values(self):
        raw = _raw_or_skip(HIT_TARGET)
        swap = {"Item_BulletBag_Medium": "Item_BulletBag_Large", "Item_BulletBag_Large": "Item_BulletBag_Medium"}
        before = _grant_values(raw)
        after = _grant_values(patch_npc_grants(raw, swap))
        self.assertEqual(after, [swap.get(v, v) for v in before])

    def test_fishing_scale_patch_covers_both_nodes(self):
        raw = _raw_or_skip(FISHING)
        before = _grant_values(raw)
        self.assertEqual(before.count("Item_Scale_Gold"), 2)
        after = _grant_values(patch_npc_grant(raw, "Item_Scale_Gold", "Item_BulletBag_Medium"))
        self.assertEqual(after.count("Item_BulletBag_Medium"), 2)
        self.assertNotIn("Item_Scale_Gold", after)

    def test_biggoron_sword_grant_is_a_get_in_event_actor_name(self):
        raw = _raw_or_skip(BIGGORON)
        self.assertEqual(_grant_values(raw), ["Item_Sword_Biggoron"])
        after = _grant_values(patch_npc_grant(raw, "Item_Sword_Biggoron", "Item_Quiver_Medium"))
        self.assertEqual(after, ["Item_Quiver_Medium"])

    def test_scrub_sale_disabled_routes_not_owned_case_past_the_sale(self):
        raw = _raw_or_skip(SCRUB)
        patched = disable_scrub_biggoron_sale(raw)
        self.assertNotEqual(patched, raw)
        flow = _load(patched)
        events = {event.name: event for event in flow.flowchart.events}
        cases = events[SCRUB_SWITCH].data.cases
        self.assertEqual(cases[0].v.name, "Event47")
        self.assertEqual(cases[1].v.name, "Event47")
        self.assertEqual(_serialize(flow), patched)

    def test_scrub_sale_patch_is_idempotent(self):
        once = disable_scrub_biggoron_sale(_raw_or_skip(SCRUB))
        self.assertIs(disable_scrub_biggoron_sale(once), once)

    def test_idempotent(self):
        raw = _raw_or_skip(DM_LOST_WOOD)
        once = patch_npc_grant(raw, "Item_BulletBag_Large", "Item_BombBag_Large")
        self.assertEqual(patch_npc_grant(once, "Item_BulletBag_Large", "Item_BombBag_Large"), once)

    def test_flow_not_granting_old_item_raises(self):
        raw = _raw_or_skip(HIT_TARGET)
        with self.assertRaises(ValueError):
            patch_npc_grant(raw, "Item_Scale_Gold", "Item_Scale_Silver")

    def test_every_flow_grants_its_slot_items(self):
        for flow in sorted(NPC_FLOWS):
            with self.subTest(flow=flow):
                values = set(_grant_values(_raw_or_skip(flow.removesuffix(".zs"))))
                wanted = {s.item for s in NPC_SLOTS.values() if s.flow == flow}
                self.assertTrue(wanted <= values, wanted - values)


class PlannerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.slots = load_default_slots()

    def test_default_plan_assigns_every_npc_location_once(self):
        plan = plan_seed(42, self.slots, None, PlanOptions())
        self.assertEqual(set(plan.npc_assignments), set(NPC_SLOTS))
        self.assertEqual(
            Counter(plan.npc_assignments.values()),
            Counter(s.item for s in NPC_SLOTS.values()),
        )

    def test_disabled_keeps_vanilla_npc_items(self):
        plan = plan_seed(42, self.slots, None, PlanOptions(shuffle_npc_items=False))
        self.assertEqual(plan.npc_assignments, {loc: s.item for loc, s in NPC_SLOTS.items()})

    def test_npc_shuffle_keeps_other_assignments_valid(self):
        on = plan_seed(7, self.slots, None, PlanOptions())
        self.assertEqual(sorted(on.event_assignments.values()), sorted(EVENT_SLOTS.values()))
        self.assertEqual(sorted(on.song_assignments.values()), sorted(SONG_SLOTS.values()))


class ShippedLogicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = load_world(DEFAULT_WORLD_PATH)

    def test_every_npc_location_is_listed_in_its_region(self):
        for (flow, item), (region, _, _) in NPC_LOCATIONS.items():
            with self.subTest(location=npc_location_name(flow, item)):
                self.assertEqual(self.world.location_region[npc_location_name(flow, item)], region)

    def test_world_has_no_errors(self):
        self.assertEqual(self.world.errors, [])

    def test_bag_upgrades_require_their_base_bag(self):
        for raw_name, item, base in [
            (HIT_TARGET, "Item_BulletBag_Large", "Item_BulletBag_Medium"),
            (HIT_TARGET, "Item_Quiver_Large", "Item_Quiver_Medium"),
            (DM_LOST_WOOD, "Item_BulletBag_Large", "Item_BulletBag_Medium"),
        ]:
            name = _loc(raw_name, item)
            region = self.world.regions[self.world.location_region[name]]
            with self.subTest(location=name):
                self.assertIn(base, _items_in(region.locations[name]))


if __name__ == "__main__":
    unittest.main()
