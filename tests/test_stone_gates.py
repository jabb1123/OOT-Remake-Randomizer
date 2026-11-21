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

    def _check_events(self, flow: EventFlow):
        return [
            e for e in flow.flowchart.events
            if isinstance(e.data, SubFlowEvent) and e.data.entry_point_name == self.CHECK
        ]

    def test_every_stone_slot_calls_the_check_after_its_grant(self):
        for flow_name in STONE_SLOT_FLOWS:
            path = RAW_DIR / flow_name.removesuffix(".zs")
            if not path.exists():
                self.skipTest(f"{path.name} not available")
            raw = _raw(path)
            grant = next(
                e for e in _load(raw).flowchart.events
                if isinstance(e.data, SubFlowEvent) and e.data.entry_point_name == "GetPouchContentByActorName"
            )
            original_next = grant.data.nxt.v.name
            patched = _load(add_stone_count_check(raw))
            checks = self._check_events(patched)
            self.assertEqual(len(checks), 1, flow_name)
            check = checks[0]
            self.assertEqual(check.data.res_flowchart_name, "DoorOfTime", flow_name)
            after_grant = next(
                e for e in patched.flowchart.events
                if e.name == grant.name
            )
            self.assertIs(after_grant.data.nxt.v, check, flow_name)
            self.assertEqual(check.data.nxt.v.name, original_next, flow_name)

    def test_check_is_idempotent(self):
        for flow_name in STONE_SLOT_FLOWS:
            path = RAW_DIR / flow_name.removesuffix(".zs")
            if not path.exists():
                self.skipTest(f"{path.name} not available")
            once = add_stone_count_check(_raw(path))
            self.assertIs(add_stone_count_check(once), once, flow_name)

    def test_check_survives_a_repointed_stone_grant(self):
        path = RAW_DIR / "Dm_DeathMtTrail_0025.bfevfl"
        if not path.exists():
            self.skipTest("Dm_DeathMtTrail_0025 not available")
        moved = patch_event_item(_raw(path), "Item_Stone_Fire", "Item_Stone_Water")
        patched = add_stone_count_check(moved)
        self.assertEqual(len(self._check_events(_load(patched))), 1)
        grants = [
            e.data.params.data["ActorName"]
            for e in _load(patched).flowchart.events
            if isinstance(e.data, SubFlowEvent) and e.data.entry_point_name == "GetPouchContentByActorName"
        ]
        self.assertEqual(grants, ["Item_Stone_Water"])

    def test_pouch_add_check_runs_at_the_end_of_the_get_route(self):
        path = RAW_DIR / "Dm_SY_Get.bfevfl"
        if not path.exists():
            self.skipTest("Dm_SY_Get not available")
        raw = _raw(path)
        add = next(
            e for e in _load(raw).flowchart.events
            if isinstance(e.data, SubFlowEvent) and e.data.entry_point_name == POUCH_ADD_SUBFLOW
        )
        original_next = add.data.nxt.v.name
        patched = _load(add_stone_count_check_at_route_end(raw, POUCH_ADD_SUBFLOW))
        checks = self._check_events(patched)
        self.assertEqual(len(checks), 1)
        after_add = next(e for e in patched.flowchart.events if e.name == add.name)
        self.assertEqual(after_add.data.nxt.v.name, original_next)
        self.assertIsNone(checks[0].data.nxt.v)
        exits = {
            e.name for e in patched.flowchart.events
            if isinstance(e.data, (ActionEvent, SubFlowEvent)) and e.data.nxt.v is checks[0]
        } | {
            e.name for e in patched.flowchart.events
            if isinstance(e.data, SwitchEvent) and any(c.v is checks[0] for c in e.data.cases.values())
        }
        self.assertEqual(exits, {"Event183", "Event177"})
        once = add_stone_count_check_at_route_end(raw, POUCH_ADD_SUBFLOW)
        self.assertIs(add_stone_count_check_at_route_end(once, POUCH_ADD_SUBFLOW), once)


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
                stone_gates, "POUCH_STONE_GATES", pouch_gates
            ):
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
            self.assertIs(patch_stone_gates(raw, "DoorOfTime.bfevfl.zs"), raw)


if __name__ == "__main__":
    unittest.main()
