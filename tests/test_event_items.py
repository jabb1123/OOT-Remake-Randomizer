import io
import unittest
from collections import Counter
from pathlib import Path

from oot_randomizer.engine import load_default_slots
from oot_randomizer.event_items import (
    EVENT_ITEM_DISPLAY_NAMES,
    EVENT_SLOTS,
    _grant_params,
    event_location_name,
    patch_event_item,
    shuffle_event_items,
)
from oot_randomizer.item_ids import CANNOT_NAME_GRANT
from oot_randomizer.npc_grants import NPC_SLOTS
from oot_randomizer.heart_pickups import FIRE_ARROW_ITEM
from oot_randomizer.planner import PlanOptions, known_locations, plan_seed
from oot_randomizer.skulltula_rewards import SKULL_REWARDS
from oot_randomizer.songs import SONG_SLOTS, patch_bfevfl_song

RAW_DIR = Path(
    r"C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405\files\raw"
)
RAW_FORCE = RAW_DIR / "Dm_Awake_Forest_Get.bfevfl"
RAW_TIME = RAW_DIR / "Dm_MelodyGet_Time.bfevfl"
RAW_FAIRY = RAW_DIR / "Dm_Kokiri_0155.bfevfl"


def _load(data: bytes):
    from evfl import EventFlow

    flow = EventFlow()
    flow.read(data)
    return flow


def _serialize(flow) -> bytes:
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def _grant_values(flow) -> list[str]:
    return [params[key] for params, key in _grant_params(flow)]


def _raw(name: str) -> bytes:
    return (RAW_DIR / name).read_bytes()


class SlotTableTest(unittest.TestCase):
    def test_ten_flows_with_unique_vanilla_items(self):
        self.assertEqual(len(EVENT_SLOTS), 10)
        self.assertEqual(len(set(EVENT_SLOTS.values())), 10)

    def test_flow_names_are_bfevfl_zs(self):
        for flow in EVENT_SLOTS:
            self.assertTrue(flow.endswith(".bfevfl.zs"), flow)

    def test_every_item_has_a_display_name(self):
        self.assertEqual(set(EVENT_SLOTS.values()), set(EVENT_ITEM_DISPLAY_NAMES))

    def test_location_names(self):
        self.assertEqual(
            event_location_name("Dm_Awake_Forest_Get.bfevfl.zs"),
            "Dm_Awake_Forest_Get (event item)",
        )

    def test_event_locations_are_known_to_planner(self):
        known = known_locations(load_default_slots())
        for flow in EVENT_SLOTS:
            self.assertIn(event_location_name(flow), known)

    def test_no_collision_with_song_locations(self):
        self.assertFalse(
            {event_location_name(f) for f in EVENT_SLOTS} & {f.removesuffix(".bfevfl.zs") for f in SONG_SLOTS}
        )


class ShuffleTest(unittest.TestCase):
    def test_is_a_permutation(self):
        mapping = shuffle_event_items(1234)
        self.assertEqual(set(mapping), set(EVENT_SLOTS))
        self.assertEqual(sorted(mapping.values()), sorted(EVENT_SLOTS.values()))

    def test_deterministic_for_a_seed(self):
        self.assertEqual(shuffle_event_items(99), shuffle_event_items(99))

    def test_seeds_vary(self):
        results = {tuple(shuffle_event_items(s).items()) for s in range(20)}
        self.assertGreater(len(results), 1)

    def test_accepts_random_instance(self):
        import random

        mapping = shuffle_event_items(random.Random(5))
        self.assertEqual(sorted(mapping.values()), sorted(EVENT_SLOTS.values()))


@unittest.skipUnless(RAW_FORCE.exists(), "raw event flows not available")
class RawFlowTest(unittest.TestCase):
    def test_round_trip_is_byte_equal_for_every_flow(self):
        for flow_file in EVENT_SLOTS:
            raw = _raw(flow_file.removesuffix(".zs"))
            with self.subTest(flow=flow_file):
                self.assertEqual(_serialize(_load(raw)), raw)

    def test_old_equals_new_returns_input(self):
        raw = _raw("Dm_Awake_Forest_Get.bfevfl")
        self.assertIs(patch_event_item(raw, "Item_Medal_Forest", "Item_Medal_Forest"), raw)

    def test_medal_grant_and_display_repointed(self):
        raw = _raw("Dm_Awake_Forest_Get.bfevfl")
        patched = _load(patch_event_item(raw, "Item_Medal_Forest", "Item_Medal_Fire"))
        self.assertEqual(_grant_values(patched), ["Item_Medal_Fire"])

    def test_repoint_changes_only_the_item_param(self):
        raw = _raw("Dm_Awake_Forest_Get.bfevfl")
        before = _load(raw)
        after = _load(patch_event_item(raw, "Item_Medal_Forest", "Item_Medal_Fire"))
        before_events = {e.name: e.data for e in before.flowchart.events}
        after_events = {e.name: e.data for e in after.flowchart.events}
        self.assertEqual(before_events.keys(), after_events.keys())
        changed = []
        for name in before_events:
            b = before_events[name]
            a = after_events[name]
            if getattr(b, "params", None) is not None and getattr(a, "params", None) is not None:
                if b.params.data != a.params.data:
                    changed.append(name)
        self.assertTrue(changed)
        self.assertEqual(len(_grant_values(before)), len(_grant_values(after)))

    def test_idempotent(self):
        raw = _raw("Dm_Awake_Forest_Get.bfevfl")
        once = patch_event_item(raw, "Item_Medal_Forest", "Item_Medal_Fire")
        self.assertEqual(patch_event_item(once, "Item_Medal_Forest", "Item_Medal_Fire"), once)

    def test_already_granted_new_item_is_noop(self):
        raw = _raw("Dm_Awake_Forest_Get.bfevfl")
        once = patch_event_item(raw, "Item_Medal_Forest", "Item_Medal_Water")
        self.assertEqual(patch_event_item(once, "Item_Medal_Forest", "Item_Medal_Water"), once)

    def test_flow_not_granting_old_item_raises(self):
        raw = _raw("Dm_Awake_Forest_Get.bfevfl")
        with self.assertRaises(ValueError):
            patch_event_item(raw, "Item_Medal_Fire", "Item_Medal_Water")

    @unittest.skipUnless(RAW_FAIRY.exists(), "Dm_Kokiri_0155 not available")
    def test_fairy_ocarina_both_params_repointed(self):
        raw = _raw("Dm_Kokiri_0155.bfevfl")
        before = _grant_values(_load(raw))
        self.assertEqual(before.count("Item_Ocarina_Fairy"), len(before))
        self.assertGreaterEqual(len(before), 2)
        patched = _load(patch_event_item(raw, "Item_Ocarina_Fairy", "Item_Stone_Forest"))
        after = _grant_values(patched)
        self.assertEqual(after, ["Item_Stone_Forest"] * len(before))

    @unittest.skipUnless(RAW_TIME.exists(), "Dm_MelodyGet_Time not available")
    def test_ocarina_of_time_both_params_repointed(self):
        raw = _raw("Dm_MelodyGet_Time.bfevfl")
        before = _grant_values(_load(raw))
        self.assertGreaterEqual(before.count("Item_Ocarina_Time"), 2)
        patched = _load(patch_event_item(raw, "Item_Ocarina_Time", "Item_Medal_Shadow"))
        after = _grant_values(patched)
        self.assertNotIn("Item_Ocarina_Time", after)
        self.assertEqual(after.count("Item_Medal_Shadow"), before.count("Item_Ocarina_Time"))

    @unittest.skipUnless(RAW_TIME.exists(), "Dm_MelodyGet_Time not available")
    def test_song_patch_then_event_patch_parse(self):
        raw = _raw("Dm_MelodyGet_Time.bfevfl")
        songed = patch_bfevfl_song(raw, "Item_Melody_TimeSong", "Item_Melody_ZeldaLullaby")
        patched = patch_event_item(songed, "Item_Ocarina_Time", "Item_Medal_Shadow")
        values = _grant_values(_load(patched))
        self.assertNotIn("Item_Ocarina_Time", values)
        self.assertEqual(values.count("Item_Medal_Shadow"), 2)
        self.assertEqual(values.count("Item_Melody_ZeldaLullaby"), 1)
        self.assertEqual(_serialize(_load(patched)), patched)


class PlannerEventTest(unittest.TestCase):
    def setUp(self):
        self.slots = load_default_slots()

    def test_default_plan_places_every_item_once(self):
        plan = plan_seed(42, self.slots, None, PlanOptions(shop_slots_per_shop=0, shuffle_heart_pieces=False))
        self.assertEqual(set(plan.event_assignments), set(EVENT_SLOTS))
        placed = Counter([i for _, i in plan.chest_assignments] + list(plan.skull_assignments.values())
                         + list(plan.song_assignments.values()) + list(plan.event_assignments.values())
                         + list(plan.npc_assignments.values()) + [i for _, i in plan.heart_assignments])
        expected = Counter(s.vanilla_item for s in self.slots) + Counter(SKULL_REWARDS.values())
        expected += Counter(SONG_SLOTS.values()) + Counter(EVENT_SLOTS.values())
        expected += Counter(s.item for s in NPC_SLOTS.values()) + Counter([FIRE_ARROW_ITEM])
        self.assertEqual(placed, expected)

    def test_disabled_keeps_vanilla_event_items(self):
        plan = plan_seed(42, self.slots, None, PlanOptions(shuffle_event_items=False))
        self.assertEqual(plan.event_assignments, EVENT_SLOTS)

    def test_event_shuffle_does_not_change_song_assignments(self):
        on = plan_seed(7, self.slots, None, PlanOptions(shuffle_songs=False))
        off = plan_seed(7, self.slots, None, PlanOptions(shuffle_songs=False, shuffle_event_items=False))
        self.assertEqual(on.song_assignments, off.song_assignments)

    def test_bundles_never_land_in_name_granted_locations(self):
        bundles_in_chests = 0
        for seed in range(10):
            plan = plan_seed(seed, self.slots, None, PlanOptions(shop_slots_per_shop=0, shuffle_heart_pieces=False))
            name_granted = (list(plan.song_assignments.values()) + list(plan.event_assignments.values())
                            + list(plan.npc_assignments.values()))
            self.assertFalse(CANNOT_NAME_GRANT & set(name_granted), f"seed {seed}")
            bundles_in_chests += sum(1 for _, item in plan.chest_assignments if item in CANNOT_NAME_GRANT)
        self.assertGreater(bundles_in_chests, 0)


if __name__ == "__main__":
    unittest.main()
