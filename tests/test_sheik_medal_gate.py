import io
import unittest
from pathlib import Path

from evfl import EventFlow
from evfl.event import SwitchEvent

from oot_randomizer.sheik_medal_gate import (
    ALLSAGE_FLOW,
    MEDAL_ITEMS,
    patch_sheik_medal_gate,
)

RAW_ALLSAGE = Path(__file__).resolve().parents[1] / "tmp" / "Events" / "raw" / "AllSage.bfevfl.zs.raw"


def _load(data: bytes) -> EventFlow:
    flow = EventFlow()
    flow.read(data)
    return flow


def _serialize(flow: EventFlow) -> bytes:
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


class SheikMedalGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not RAW_ALLSAGE.exists():
            raise unittest.SkipTest(f"raw flow {RAW_ALLSAGE} not available")
        cls.raw = RAW_ALLSAGE.read_bytes()
        cls.patched = patch_sheik_medal_gate(cls.raw)

    def _by_name(self, data: bytes):
        return {event.name: event for event in _load(data).flowchart.events}

    def test_flow_name(self):
        self.assertEqual(ALLSAGE_FLOW, "AllSage.bfevfl.zs")

    def test_gate_keeps_flag_case_and_adds_medal_chain(self):
        events = self._by_name(self.patched)
        gate = events["Event178"].data
        self.assertEqual(gate.params.data["GameDataName"], "AllSage_AwakeSage_Fire_Or_Forest")
        self.assertEqual(gate.cases[0].v.name, "Event181")
        self.assertEqual(gate.cases[1].v.name, "MedalCheck_Forest")

    def test_each_medal_check_points_at_awake_and_the_next_check(self):
        events = self._by_name(self.patched)
        names = [f"MedalCheck_{medal.removeprefix('Item_Medal_')}" for medal in MEDAL_ITEMS]
        for index, name in enumerate(names):
            node = events[name].data
            self.assertIsInstance(node, SwitchEvent)
            self.assertEqual(node.params.data, {"Actor": MEDAL_ITEMS[index], "Num": 1})
            self.assertEqual(node.actor.v.identifier.name, "PouchSystemActor")
            self.assertEqual(node.actor_query.v.v, "EventQueryIsExistInPouch")
            self.assertEqual(node.cases[0].v.name, "Event181")
            if index + 1 < len(names):
                self.assertEqual(node.cases[1].v.name, names[index + 1])
            else:
                self.assertNotIn(1, node.cases)

    def test_chain_is_idempotent(self):
        self.assertEqual(patch_sheik_medal_gate(self.patched), self.patched)

    def test_unexpected_gate_raises(self):
        flow = _load(self.raw)
        gate = next(e for e in flow.flowchart.events if e.name == "Event178")
        gate.data.params.data["GameDataName"] = "SomethingElse"
        with self.assertRaises(ValueError):
            patch_sheik_medal_gate(_serialize(flow))


if __name__ == "__main__":
    unittest.main()
