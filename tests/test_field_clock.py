import io
import unittest
from pathlib import Path

from oot_randomizer.field_clock import (
    CLOCK_HOUR,
    CLOCK_MINUTE,
    CLOCK_ANCHOR_ACTION,
    SET_TIME_ACTION,
    WORLD_MANAGER_ACTOR,
    start_clock_at_zelda_flow_end,
)

RAW_DIR = Path(
    r"C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405\files\raw"
)
RAW_MELODY_ZELDA = RAW_DIR / "Dm_MelodyGet_Zelda.bfevfl"
RAW_DOOR_OF_TIME = RAW_DIR / "DoorOfTime.bfevfl"


def _load(data: bytes):
    from evfl import EventFlow

    flow = EventFlow()
    flow.read(data)
    return flow


def _serialize(flow) -> bytes:
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def _action_name(event) -> str:
    return str(event.data.actor_action.v)


def _action_events(flow):
    from evfl.event import ActionEvent

    return [e for e in flow.flowchart.events if isinstance(e.data, ActionEvent)]


def _clock_writes(flow):
    return [e for e in _action_events(flow) if _action_name(e) == SET_TIME_ACTION]


@unittest.skipUnless(RAW_MELODY_ZELDA.exists(), "Dm_MelodyGet_Zelda.bfevfl not available")
class StartClockAtZeldaFlowEndTest(unittest.TestCase):
    def setUp(self):
        self.raw = RAW_MELODY_ZELDA.read_bytes()

    def test_clock_write_sits_before_final_action(self):
        patched = _load(start_clock_at_zelda_flow_end(self.raw))
        clocks = _clock_writes(patched)
        self.assertEqual(len(clocks), 1)
        clock = clocks[0]
        self.assertEqual(clock.data.actor.v.identifier.name, WORLD_MANAGER_ACTOR)
        self.assertEqual(clock.data.params.data, {"TimeHour": CLOCK_HOUR, "TimeMin": CLOCK_MINUTE})
        self.assertEqual(_action_name(clock.data.nxt.v), CLOCK_ANCHOR_ACTION)

    def test_adds_exactly_one_clock_write(self):
        before = len(_clock_writes(_load(self.raw)))
        after = len(_clock_writes(_load(start_clock_at_zelda_flow_end(self.raw))))
        self.assertEqual(after, before + 1)

    def test_patched_flow_round_trips(self):
        patched = start_clock_at_zelda_flow_end(self.raw)
        self.assertEqual(_serialize(_load(patched)), patched)


@unittest.skipUnless(RAW_DOOR_OF_TIME.exists(), "DoorOfTime.bfevfl not available")
class MissingAnchorTest(unittest.TestCase):
    def test_rejects_flow_without_anchor(self):
        with self.assertRaises(ValueError):
            start_clock_at_zelda_flow_end(RAW_DOOR_OF_TIME.read_bytes())


if __name__ == "__main__":
    unittest.main()
