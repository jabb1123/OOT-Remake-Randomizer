import io
import unittest
from pathlib import Path

from evfl import EventFlow
from evfl.event import SwitchEvent

from oot_randomizer.engine import load_default_slots
from oot_randomizer.event_items import EVENT_SLOTS, event_location_name
from oot_randomizer.planner import known_locations
from oot_randomizer.shop_slots import VANILLA_SHOP_LOGIC_ITEMS
from oot_randomizer.skulltula_rewards import SKULL_REWARDS, TOKEN_ITEM, skull_location_name
from oot_randomizer.songs import SONG_SLOTS, song_location_name
from oot_randomizer.stone_gates import STONE_BOOL_ITEMS, STONE_GATE_FLOWS, patch_stone_gates
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

    def test_only_stone_bools_are_mapped_and_water_is_excluded(self):
        self.assertEqual(
            STONE_BOOL_ITEMS,
            {
                "Get_StoneOfForest_IsCompleted_Exp": "Item_Stone_Forest",
                "Get_StoneOfFire_IsCompleted_Exp": "Item_Stone_Fire",
            },
        )
        for bools in STONE_GATE_FLOWS.values():
            self.assertTrue(bools <= set(STONE_BOOL_ITEMS))
            self.assertNotIn(WATER_BOOL, bools)

    def test_unknown_flow_is_a_no_op(self):
        data = b"not a flow"
        self.assertIs(patch_stone_gates(data, "Unrelated.bfevfl.zs"), data)


@unittest.skipUnless(RAW_DOOR.exists() and RAW_GORON.exists(), "raw stone-gate flows not available")
class RawStoneGateFlowTest(unittest.TestCase):
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

    def test_water_bool_is_untouched(self):
        raw = _raw(RAW_DOOR)
        before = [s for s in _switches(_load(raw)) if s[2].get("GameDataName") == WATER_BOOL]
        after = [s for s in _switches(_load(patch_stone_gates(raw, "DoorOfTime.bfevfl.zs")))
                 if s[2].get("GameDataName") == WATER_BOOL]
        self.assertTrue(before)
        self.assertEqual(before, after)

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
    return placed


class TempleStoneLogicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.slots = load_default_slots()
        cls.world = load_world()
        cls.world.check_locations(known_locations(cls.slots))
        cls.placed = _vanilla_placements(cls.slots)
        cls.placed |= {loc: TOKEN_ITEM for loc in cls.world.token_locations}

    def _reached(self, placed: dict[str, str]) -> set[str]:
        res = self.world.explore(placed, {"bombchus_in_logic": True})
        return set().union(*res.regions.values())

    def test_temple_is_reachable_with_both_stones(self):
        self.assertIn("TempleOfTime", self._reached(self.placed))

    def test_temple_needs_kokiris_emerald(self):
        placed = {k: v for k, v in self.placed.items() if k != event_location_name("Dm_Kokiri_0130.bfevfl.zs")}
        self.assertNotIn("TempleOfTime", self._reached(placed))

    def test_temple_needs_goron_ruby(self):
        placed = {k: v for k, v in self.placed.items() if k != event_location_name("Dm_DeathMtTrail_0025.bfevfl.zs")}
        self.assertNotIn("TempleOfTime", self._reached(placed))


if __name__ == "__main__":
    unittest.main()
