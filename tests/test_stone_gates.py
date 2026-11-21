import io
import unittest
from pathlib import Path
from unittest import mock

from evfl import EventFlow
from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent

from oot_randomizer import stone_gates
from oot_randomizer.engine import load_default_slots
from oot_randomizer.event_items import EVENT_SLOTS, event_location_name, patch_event_item
from oot_randomizer.npc_grants import NPC_SLOTS
from oot_randomizer.planner import known_locations
from oot_randomizer.shop_slots import VANILLA_SHOP_LOGIC_ITEMS
from oot_randomizer.shop_soldout import add_shop_slingshot_bag, patch_kokiri_soldout
from oot_randomizer.skulltula_rewards import SKULL_REWARDS, TOKEN_ITEM, skull_location_name
from oot_randomizer.songs import SONG_SLOTS, song_location_name
from oot_randomizer.stone_gates import (
    POUCH_ADD_SUBFLOW,
    STONE_BOOL_ITEMS,
    STONE_GATE_FLOWS,
    STONE_SLOT_FLOWS,
    add_stone_count_check,
    add_stone_count_check_at_route_end,
    patch_stone_gates,
)
from oot_randomizer.world_logic import load_world

RAW_DIR = Path(
    r"C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405\files\raw"
)
RAW_DOOR = RAW_DIR / "DoorOfTime.bfevfl"
RAW_GORON = RAW_DIR / "Dm_Goron_0028.bfevfl"
FIRE_BOOL = "Get_StoneOfFire_IsCompleted_Exp"
WATER_BOOL = "Get_StoneOfWater_IsCompleted_Exp"


def _load(data: bytes) -> EventFlow:
    flow = EventFlow()
    flow.read(data)
    return flow


def _serialize(flow: EventFlow) -> bytes:
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def _raw(path: Path) -> bytes:
    return path.read_bytes()


def _switches(flow: EventFlow) -> list[tuple[str, str, dict]]:
    found = []
    for event in flow.flowchart.events:
        body = event.data
        if isinstance(body, SwitchEvent) and body.actor.v is not None and body.actor_query.v is not None:
            params = dict(body.params.data) if body.params is not None else {}
            found.append((body.actor.v.identifier.name, body.actor_query.v.v, params))
    return found


class StoneGateTableTest(unittest.TestCase):
    def test_flow_names_are_bfevfl_zs(self):
        for flow in STONE_GATE_FLOWS:
            self.assertTrue(flow.endswith(".bfevfl.zs"), flow)

    def test_only_stone_bools_are_mapped(self):
        self.assertEqual(
            STONE_BOOL_ITEMS,
            {
                "Get_StoneOfForest_IsCompleted_Exp": "Item_Stone_Forest",
                "Get_StoneOfFire_IsCompleted_Exp": "Item_Stone_Fire",
                "Get_StoneOfWater_IsCompleted_Exp": "Item_Stone_Water",
            },
        )
        for bools in STONE_GATE_FLOWS.values():
            self.assertTrue(bools <= set(STONE_BOOL_ITEMS))

    def test_unknown_flow_is_a_no_op(self):
        data = b"not a flow"
        self.assertIs(patch_stone_gates(data, "Unrelated.bfevfl.zs"), data)


@unittest.skipUnless(RAW_DOOR.exists() and RAW_GORON.exists(), "raw stone-gate flows not available")
class RawStoneGateFlowTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(stone_gates, "POUCH_STONE_GATES", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_switch_off_leaves_the_vanilla_bool_gates(self):
        with mock.patch.object(stone_gates, "POUCH_STONE_GATES", False):
            raw = _raw(RAW_DOOR)
            patched = _switches(_load(patch_stone_gates(raw, "DoorOfTime.bfevfl.zs")))
            self.assertIn(FIRE_BOOL, [p.get("GameDataName") for _, _, p in patched])
            self.assertNotIn("Item_Stone_Fire", [p.get("Actor") for _, _, p in patched])

    def test_round_trip_is_byte_equal(self):
        for path in (RAW_DOOR, RAW_GORON):
            raw = _raw(path)
            self.assertEqual(_serialize(_load(raw)), raw, path.name)

    def test_door_of_time_fire_gate_becomes_pouch_query(self):
        raw = _raw(RAW_DOOR)
        self.assertIn(FIRE_BOOL, [p.get("GameDataName") for _, _, p in _switches(_load(raw))])
        patched = _switches(_load(patch_stone_gates(raw, "DoorOfTime.bfevfl.zs")))
        self.assertNotIn(FIRE_BOOL, [p.get("GameDataName") for _, _, p in patched])
        self.assertIn(("PouchSystemActor", "EventQueryIsExistInPouch",
                       {"Actor": "Item_Stone_Fire", "Num": 1}), patched)

    def test_door_of_time_water_gates_become_pouch_queries(self):
        raw = _raw(RAW_DOOR)
        self.assertIn(WATER_BOOL, [p.get("GameDataName") for _, _, p in _switches(_load(raw))])
        patched = _switches(_load(patch_stone_gates(raw, "DoorOfTime.bfevfl.zs")))
        self.assertNotIn(WATER_BOOL, [p.get("GameDataName") for _, _, p in patched])
        self.assertIn(("PouchSystemActor", "EventQueryIsExistInPouch",
                       {"Actor": "Item_Stone_Water", "Num": 1}), patched)

    def test_goron_fire_gate_becomes_pouch_query(self):
        raw = _raw(RAW_GORON)
        patched = _switches(_load(patch_stone_gates(raw, "Dm_Goron_0028.bfevfl.zs")))
        self.assertNotIn(FIRE_BOOL, [p.get("GameDataName") for _, _, p in patched])
        self.assertIn(("PouchSystemActor", "EventQueryIsExistInPouch",
                       {"Actor": "Item_Stone_Fire", "Num": 1}), patched)

    def test_patch_is_idempotent(self):
        for path, flow in ((RAW_DOOR, "DoorOfTime.bfevfl.zs"), (RAW_GORON, "Dm_Goron_0028.bfevfl.zs")):
            once = patch_stone_gates(_raw(path), flow)
            self.assertNotEqual(once, _raw(path), path.name)
            self.assertEqual(patch_stone_gates(once, flow), once, path.name)

    def test_absent_query_leaves_file_unchanged(self):
        raw = _raw(RAW_DOOR)
        patched = patch_stone_gates(raw, "DoorOfTime.bfevfl.zs")
        self.assertIs(patch_stone_gates(patched, "DoorOfTime.bfevfl.zs"), patched)
        self.assertIs(patch_stone_gates(raw, "Dm_Kokiri_0130.bfevfl.zs"), raw)


def _vanilla_placements(slots) -> dict[str, str]:
    placed = {s.name: s.vanilla_item for s in slots}
    placed |= {song_location_name(f): s for f, s in SONG_SLOTS.items()}
    placed |= {event_location_name(f): item for f, item in EVENT_SLOTS.items()}
    placed |= {skull_location_name(n): i for n, i in SKULL_REWARDS.items()}
    placed |= VANILLA_SHOP_LOGIC_ITEMS
    placed |= {loc: slot.item for loc, slot in NPC_SLOTS.items()}
    return placed


class TempleStoneLogicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.slots = load_default_slots()
        cls.world = load_world()
        cls.world.check_locations(known_locations(cls.slots))
        cls.placed = _vanilla_placements(cls.slots)
        cls.placed |= {loc: TOKEN_ITEM for loc in cls.world.token_locations}

    def _events(self, placed: dict[str, str]) -> set[str]:
        res = self.world.explore(placed, {"bombchus_in_logic": True})
        return set(res.events)

    def test_time_travel_is_reachable_with_both_stones(self):
        self.assertIn("Time_Travel", self._events(self.placed))

    def test_time_travel_needs_kokiris_emerald(self):
        placed = {k: v for k, v in self.placed.items() if k != event_location_name("Dm_Kokiri_0130.bfevfl.zs")}
        self.assertNotIn("Time_Travel", self._events(placed))

    def test_time_travel_needs_goron_ruby(self):
        placed = {k: v for k, v in self.placed.items() if k != event_location_name("Dm_DeathMtTrail_0025.bfevfl.zs")}
        self.assertNotIn("Time_Travel", self._events(placed))

    def test_time_travel_needs_zora_sapphire(self):
        placed = {
            k: v
            for k, v in self.placed.items()
            if k != event_location_name("Dm_ZoraFountain_0030.bfevfl.zs")
        }
        self.assertNotIn("Time_Travel", self._events(placed))


class StoneCountCheckTest(unittest.TestCase):
    CHECK = "DoorOfTime_CheckStoneNum"
    PREFIX = "StoneCheck_"
    GATE = "IsAfterStep03"

    def _check_raw(self) -> bytes:
        path = RAW_DIR / "DoorOfTime.bfevfl"
        if not path.exists():
            self.skipTest("DoorOfTime not available")
        return _raw(path)

    def _source_entry_name(self, check_raw: bytes) -> str:
        flow = _load(check_raw)
        entry = next(ep for ep in flow.flowchart.entry_points if ep.name == self.CHECK)
        return entry.main_event.v.name

    def _calls_door_of_time(self, flow: EventFlow) -> bool:
        return any(
            isinstance(e.data, SubFlowEvent) and e.data.entry_point_name == self.CHECK
            for e in flow.flowchart.events
        )

    def _inline_events(self, flow: EventFlow):
        return [e for e in flow.flowchart.events if e.name.startswith(self.PREFIX)]

    def _inline_exits(self, flow: EventFlow) -> set[str | None]:
        """Names of the events outside the copied check that its exits continue to. None means the branch ends."""
        exits: set[str | None] = set()
        for e in self._inline_events(flow):
            if isinstance(e.data, ActionEvent):
                targets = [e.data.nxt.v]
            elif isinstance(e.data, SwitchEvent):
                targets = [c.v for c in e.data.cases.values()]
            else:
                continue
            for target in targets:
                if target is None:
                    exits.add(None)
                elif not target.name.startswith(self.PREFIX):
                    exits.add(target.name)
        return exits

    def _grant(self, flow: EventFlow, subflow: str):
        return next(
            e for e in flow.flowchart.events
            if isinstance(e.data, SubFlowEvent) and e.data.entry_point_name == subflow
        )

    def test_every_stone_slot_runs_the_check_after_its_grant(self):
        check_raw = self._check_raw()
        gate_name = self.PREFIX + self.GATE
        for flow_name in STONE_SLOT_FLOWS:
            path = RAW_DIR / flow_name.removesuffix(".zs")
            if not path.exists():
                self.skipTest(f"{path.name} not available")
            raw = _raw(path)
            grant = self._grant(_load(raw), "GetPouchContentByActorName")
            grant_name, original_next = grant.name, grant.data.nxt.v.name
            patched = _load(add_stone_count_check(raw, check_raw))
            self.assertFalse(self._calls_door_of_time(patched), flow_name)
            after_grant = next(e for e in patched.flowchart.events if e.name == grant_name)
            self.assertEqual(after_grant.data.nxt.v.name, gate_name, flow_name)
            self.assertEqual(self._inline_exits(patched), {original_next}, flow_name)

    def test_step_gate_skips_the_check_from_step03_onward(self):
        path = RAW_DIR / "Dm_SY_Get.bfevfl"
        if not path.exists():
            self.skipTest("Dm_SY_Get not available")
        check_raw = self._check_raw()
        source_entry = self._source_entry_name(check_raw)
        patched = _load(add_stone_count_check_at_route_end(_raw(path), check_raw))
        gate = next(e for e in patched.flowchart.events if e.name == self.PREFIX + self.GATE)
        self.assertIsInstance(gate.data, SwitchEvent)
        self.assertEqual(gate.data.params.data["GameDataName"], "DoorOfTime_IsAfter_Step03_Exp")
        self.assertEqual(gate.data.cases[1].v.name, self.PREFIX + source_entry)
        self.assertNotIn(0, gate.data.cases)

    def test_inlined_check_copies_each_source_event_it_reaches(self):
        check_raw = self._check_raw()
        source = {e.name: e for e in _load(check_raw).flowchart.events}
        raw = _raw(RAW_DIR / "Dm_SY_Get.bfevfl")
        patched = _load(add_stone_count_check_at_route_end(raw, check_raw))
        copies = [e for e in self._inline_events(patched) if e.name != self.PREFIX + self.GATE]
        self.assertTrue(copies)
        for copy in copies:
            original = source[copy.name[len(self.PREFIX):]]
            if isinstance(original.data, ActionEvent):
                self.assertIsInstance(copy.data, ActionEvent, copy.name)
                self.assertEqual(copy.data.actor.v.identifier.name, original.data.actor.v.identifier.name)
                self.assertEqual(copy.data.actor_action.v.v, original.data.actor_action.v.v)
            else:
                self.assertIsInstance(copy.data, SwitchEvent, copy.name)
                self.assertEqual(copy.data.actor.v.identifier.name, original.data.actor.v.identifier.name)
                self.assertEqual(copy.data.actor_query.v.v, original.data.actor_query.v.v)
            copied_params = copy.data.params.data if copy.data.params is not None else None
            source_params = original.data.params.data if original.data.params is not None else None
            self.assertEqual(copied_params, source_params, copy.name)

    def test_check_is_idempotent(self):
        check_raw = self._check_raw()
        for flow_name in STONE_SLOT_FLOWS:
            path = RAW_DIR / flow_name.removesuffix(".zs")
            if not path.exists():
                self.skipTest(f"{path.name} not available")
            once = add_stone_count_check(_raw(path), check_raw)
            self.assertIs(add_stone_count_check(once, check_raw), once, flow_name)

    def test_check_survives_a_repointed_stone_grant(self):
        path = RAW_DIR / "Dm_DeathMtTrail_0025.bfevfl"
        if not path.exists():
            self.skipTest("Dm_DeathMtTrail_0025 not available")
        check_raw = self._check_raw()
        moved = patch_event_item(_raw(path), "Item_Stone_Fire", "Item_Stone_Water")
        patched = _load(add_stone_count_check(moved, check_raw))
        entry_name = self.PREFIX + self.GATE
        self.assertEqual(sum(e.name == entry_name for e in patched.flowchart.events), 1)
        self.assertFalse(self._calls_door_of_time(patched))
        grants = [
            e.data.params.data["ActorName"]
            for e in patched.flowchart.events
            if isinstance(e.data, SubFlowEvent) and e.data.entry_point_name == "GetPouchContentByActorName"
        ]
        self.assertEqual(grants, ["Item_Stone_Water"])

    def test_pouch_add_check_runs_at_the_end_of_the_get_route(self):
        path = RAW_DIR / "Dm_SY_Get.bfevfl"
        if not path.exists():
            self.skipTest("Dm_SY_Get not available")
        check_raw = self._check_raw()
        raw = _raw(path)
        add = self._grant(_load(raw), POUCH_ADD_SUBFLOW)
        add_name, original_next = add.name, add.data.nxt.v.name
        entry_name = self.PREFIX + self.GATE
        patched = _load(add_stone_count_check_at_route_end(raw, check_raw))
        self.assertFalse(self._calls_door_of_time(patched))
        self.assertEqual(sum(e.name == entry_name for e in patched.flowchart.events), 1)
        after_add = next(e for e in patched.flowchart.events if e.name == add_name)
        self.assertEqual(after_add.data.nxt.v.name, original_next)
        self.assertEqual(self._inline_exits(patched), {None})
        entry = next(e for e in patched.flowchart.events if e.name == entry_name)
        exits = {
            e.name for e in patched.flowchart.events
            if isinstance(e.data, (ActionEvent, SubFlowEvent)) and e.data.nxt.v is entry
        } | {
            e.name for e in patched.flowchart.events
            if isinstance(e.data, SwitchEvent) and any(c.v is entry for c in e.data.cases.values())
        }
        self.assertEqual(exits, {"Event183", "Event177"})
        once = add_stone_count_check_at_route_end(raw, check_raw)
        self.assertIs(add_stone_count_check_at_route_end(once, check_raw), once)

    def test_shop_purchases_recount_before_autosave_and_preserve_other_patches(self):
        path = RAW_DIR / "DisplayShop.bfevfl"
        if not path.exists():
            self.skipTest("DisplayShop not available")
        check_raw = patch_stone_gates(self._check_raw(), "DoorOfTime.bfevfl.zs")
        shop = add_shop_slingshot_bag(patch_kokiri_soldout(_raw(path)))
        patched = stone_gates.add_shop_stone_count_check(shop, check_raw)
        flow = _load(patched)
        events = {event.name: event for event in flow.flowchart.events}
        source_entry = self._source_entry_name(check_raw)
        for grant, fork, join, sold, marker, autosave in (
            ("Event268", "Event219", "Event220", "Event217", "Event281", "Event295"),
            ("Event171", "Event232", "Event233", "Event231", "Event103", "Event338"),
        ):
            entry_name = f"StoneCheck_{grant}_{self.GATE}"
            self.assertEqual(events[entry_name].data.cases[1].v.name, f"StoneCheck_{grant}_{source_entry}")
            self.assertEqual(events[grant].data.nxt.v.name, fork)
            self.assertEqual(events[fork].data.join.v.name, join)
            self.assertEqual(events[join].data.nxt.v.name, sold)
            self.assertEqual(events[sold].data.nxt.v.name, marker)
            self.assertEqual(events[marker].data.nxt.v.name, entry_name)
            copies = [event for event in flow.flowchart.events if event.name.startswith(f"StoneCheck_{grant}_")]
            self.assertTrue(copies)
            copied_switches = [
                (event.data.actor.v.identifier.name, event.data.actor_query.v.v, event.data.params.data)
                for event in copies if isinstance(event.data, SwitchEvent)
            ]
            for item in ("Item_Stone_Fire", "Item_Stone_Water"):
                self.assertIn(("PouchSystemActor", "EventQueryIsExistInPouch",
                               {"Actor": item, "Num": 1}), copied_switches)
            self.assertTrue(any(
                isinstance(event.data, ActionEvent)
                and event.data.actor_action.v.v == "EventTriggerShowChallengeProgressUI"
                for event in copies
            ))
            exits = {
                event.data.nxt.v.name
                for event in copies
                if isinstance(event.data, ActionEvent)
                and event.data.nxt.v is not None
                and not event.data.nxt.v.name.startswith(f"StoneCheck_{grant}_")
            }
            self.assertEqual(exits, {autosave})
            self.assertEqual(events[autosave].data.actor_action.v.v, "EventTriggerRequestAutoSave")
            self.assertIn(f"AutoEvent_ShopSlingshotBag_Check_{grant}", events)
        self.assertIn("ShopSoldOut_MarkSession", events)
        self.assertIs(stone_gates.add_shop_stone_count_check(patched, check_raw), patched)

    def test_shop_check_rejects_changed_purchase_route(self):
        path = RAW_DIR / "DisplayShop.bfevfl"
        if not path.exists():
            self.skipTest("DisplayShop not available")
        flow = _load(_raw(path))
        marker = next(event for event in flow.flowchart.events if event.name == "Event281")
        marker.data.nxt.v = None
        with self.assertRaisesRegex(ValueError, "purchase route Event268 has changed"):
            stone_gates.add_shop_stone_count_check(_serialize(flow), self._check_raw())


class StoneCheckDiagnosticsTest(unittest.TestCase):
    def _diag_writes(self, flow: EventFlow) -> dict[str, ActionEvent]:
        writes = {}
        for event in flow.flowchart.events:
            body = event.data
            if isinstance(body, ActionEvent) and body.params is not None:
                flag = body.params.data.get("GameDataName")
                if isinstance(flag, str) and flag.startswith("Rando_Diag_StoneCheck_"):
                    writes[flag] = body
        return writes

    def test_diagnostic_bools_precede_the_entry_and_each_branch(self):
        if not RAW_DOOR.exists():
            self.skipTest("raw Door of Time dump not present")
        expected = {stone_gates._DIAG_ENTRY_BOOL} | {flag for _, flag in stone_gates._DIAG_BRANCH_BOOLS}
        for pouch_gates in (True, False):
            with self.subTest(pouch_gates=pouch_gates), mock.patch.object(
                stone_gates, "STONE_CHECK_DIAGNOSTICS", True
            ), mock.patch.object(stone_gates, "POUCH_STONE_GATES", pouch_gates):
                patched = _load(patch_stone_gates(_raw(RAW_DOOR), "DoorOfTime.bfevfl.zs"))
                writes = self._diag_writes(patched)
                self.assertEqual(set(writes), expected)
                for flag, body in writes.items():
                    self.assertIs(body.params.data["Value"], True)
                entry = next(ep for ep in patched.flowchart.entry_points
                             if ep.name == stone_gates._STONE_CHECK_ENTRY)
                self.assertEqual(entry.main_event.v.data.params.data["GameDataName"],
                                 stone_gates._DIAG_ENTRY_BOOL)
                for event_name, flag in stone_gates._DIAG_BRANCH_BOOLS:
                    self.assertEqual(writes[flag].nxt.v.name, event_name)

    def test_diagnostics_off_leaves_the_flow_untouched(self):
        if not RAW_DOOR.exists():
            self.skipTest("raw Door of Time dump not present")
        raw = _raw(RAW_DOOR)
        with mock.patch.object(stone_gates, "STONE_CHECK_DIAGNOSTICS", False), mock.patch.object(
            stone_gates, "POUCH_STONE_GATES", False
        ):
            patched = _load(patch_stone_gates(raw, "DoorOfTime.bfevfl.zs"))
            self.assertEqual(self._diag_writes(patched), {})
            names = {e.name for e in patched.flowchart.events}
            self.assertIn("AutoEvent_EventTriggerShowChallengeProgressUI_before_Event5", names)

    def test_progress_window_precedes_the_step_exits(self):
        if not RAW_DOOR.exists():
            self.skipTest("raw Door of Time dump not present")
        patched = _load(patch_stone_gates(_raw(RAW_DOOR), "DoorOfTime.bfevfl.zs"))
        by_name = {e.name: e for e in patched.flowchart.events}
        for target in ("Event77", "Event5"):
            node = by_name[f"AutoEvent_EventTriggerShowChallengeProgressUI_before_{target}"]
            body = node.data
            self.assertIsInstance(body, ActionEvent)
            self.assertEqual(body.actor.v.identifier.name, "ChallengeSystemActor")
            self.assertEqual(body.actor_action.v.v, "EventTriggerShowChallengeProgressUI")
            self.assertEqual(body.params.data, {"ChallengeName": "DoorOfTime", "IsFirstStep": False})
            self.assertEqual(body.nxt.v.name, target)
        once = patch_stone_gates(_raw(RAW_DOOR), "DoorOfTime.bfevfl.zs")
        self.assertIs(patch_stone_gates(once, "DoorOfTime.bfevfl.zs"), once)


if __name__ == "__main__":
    unittest.main()
