"""Tests for isolating the Hyrule Field segments that play after the first Kaepora talk."""

import unittest
from pathlib import Path

from evfl import EventFlow
from evfl.event import ActionEvent

from oot_randomizer.hyrule_field_segments import (
    KAEPORA_ENTRY_POINT,
    KAEPORA_SEGMENTS,
    KAEPORA_SEGMENTS_TO_PLAY,
    isolate_kaepora_segments,
)

RAW_CASTLE_FLOW = Path(
    r"C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405\files\raw\Goto_HyruleCastle.bfevfl"
)


def _reachable_events(flow: EventFlow, entry_name: str) -> list:
    entry = next(e for e in flow.flowchart.entry_points if e.name == entry_name)
    stack = [entry.main_event.v]
    seen: set[int] = set()
    reached = []
    while stack:
        event = stack.pop()
        if event is None or id(event) in seen:
            continue
        seen.add(id(event))
        reached.append(event)
        data = event.data
        refs = []
        if hasattr(data, "cases"):
            refs.extend(data.cases.values())
        if hasattr(data, "forks"):
            refs.extend(data.forks)
            refs.append(data.join)
        if hasattr(data, "nxt"):
            refs.append(data.nxt)
        stack.extend(r.v for r in refs)
    return reached


def _transitions(data: bytes, entry_name: str) -> set[str]:
    """EventName of every EventTransition reachable from an entry point."""
    flow = EventFlow()
    flow.read(data)
    names = set()
    for event in _reachable_events(flow, entry_name):
        if isinstance(event.data, ActionEvent) and str(event.data.actor_action.v) == "EventTransition":
            names.add(event.data.params.data["EventName"])
    return names


def _event_names(data: bytes, entry_name: str) -> set[str]:
    flow = EventFlow()
    flow.read(data)
    return {e.name for e in _reachable_events(flow, entry_name)}


@unittest.skipUnless(RAW_CASTLE_FLOW.exists(), "Goto_HyruleCastle.bfevfl fixture not extracted")
class KaeporaSegmentIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = RAW_CASTLE_FLOW.read_bytes()

    def test_vanilla_chain_plays_all_three_segments(self):
        self.assertEqual(_transitions(self.raw, KAEPORA_ENTRY_POINT), set(KAEPORA_SEGMENTS))

    def test_default_plays_only_the_configured_segments(self):
        patched = isolate_kaepora_segments(self.raw)
        self.assertEqual(_transitions(patched, KAEPORA_ENTRY_POINT), set(KAEPORA_SEGMENTS_TO_PLAY))

    def test_each_segment_can_be_isolated(self):
        for segment in KAEPORA_SEGMENTS:
            with self.subTest(segment=segment):
                patched = isolate_kaepora_segments(self.raw, frozenset({segment}))
                self.assertEqual(_transitions(patched, KAEPORA_ENTRY_POINT), {segment})

    def test_all_segments_kept_leaves_flow_unchanged(self):
        self.assertIs(isolate_kaepora_segments(self.raw, frozenset(KAEPORA_SEGMENTS)), self.raw)

    def test_unlinking_keeps_every_event_and_entry_point(self):
        patched = isolate_kaepora_segments(self.raw, frozenset({"Dm_HrlField_0005"}))
        before, after = EventFlow(), EventFlow()
        before.read(self.raw)
        after.read(patched)
        self.assertEqual(
            [e.name for e in before.flowchart.events],
            [e.name for e in after.flowchart.events],
        )
        self.assertEqual(
            [e.name for e in before.flowchart.entry_points],
            [e.name for e in after.flowchart.entry_points],
        )

    def test_unlinked_kaepora_chain_still_reaches_the_rest_of_the_talk(self):
        # Dropping the 0005 and 0010 transitions must keep the events that follow them in the chain.
        patched = isolate_kaepora_segments(self.raw, frozenset({"Dm_HrlField_0000"}))
        self.assertIn("Event217", _event_names(patched, KAEPORA_ENTRY_POINT))
        self.assertIn("Event221", _event_names(patched, KAEPORA_ENTRY_POINT))

    def test_other_entry_points_are_untouched(self):
        patched = isolate_kaepora_segments(self.raw)
        self.assertEqual(
            _event_names(patched, "Goto_HyruleCastle_MeetZelda"),
            _event_names(self.raw, "Goto_HyruleCastle_MeetZelda"),
        )


if __name__ == "__main__":
    unittest.main()
