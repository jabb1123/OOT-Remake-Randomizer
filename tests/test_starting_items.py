"""Tests for the starting Small Stick Bag and Small Nut Bag added to the opening event flow."""

import unittest
from pathlib import Path

from evfl import EventFlow
from evfl.event import ActionEvent

from oot_randomizer.cutscene_skips import INTRO_ENTRY_POINT, skip_intro_cutscene
from oot_randomizer.starting_items import (
    POUCH_ACTION,
    POUCH_ACTOR,
    STARTING_BAGS,
    add_starting_bags,
    patch_intro_flow,
)

RAW_DIR = Path(
    r"C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405\files\raw"
)
RAW_OPENING = RAW_DIR / "OpeningEvent.bfevfl"


def _chain(data: bytes, limit: int = 4) -> list[ActionEvent | None]:
    """Return the first `limit` action bodies of the intro entry point's chain."""
    flow = EventFlow()
    flow.read(data)
    entry = next(e for e in flow.flowchart.entry_points if e.name == INTRO_ENTRY_POINT)
    event = entry.main_event.v
    out = []
    while event is not None and len(out) < limit:
        out.append(event.data if isinstance(event.data, ActionEvent) else None)
        event = event.data.nxt.v if isinstance(event.data, ActionEvent) else None
    return out


@unittest.skipUnless(RAW_OPENING.exists(), "OpeningEvent fixture not extracted")
class StartingBagTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = RAW_OPENING.read_bytes()
        cls.patched = add_starting_bags(cls.raw)

    def test_first_actions_are_silent_bag_adds_in_order(self):
        chain = _chain(self.patched, limit=len(STARTING_BAGS) + 1)
        for action, bag in zip(chain, STARTING_BAGS):
            self.assertEqual(str(action.actor.v.identifier.name), POUCH_ACTOR)
            self.assertEqual(str(action.actor_action.v.v), POUCH_ACTION)
            self.assertEqual(action.params.data["Actor"], bag)
            self.assertEqual(action.params.data["Num"], 1)
            self.assertIs(action.params.data["IsGetEvent"], False)

    def test_original_intro_follows_the_bag_adds(self):
        original_first = _chain(self.raw)[0]
        patched_after = _chain(self.patched, limit=len(STARTING_BAGS) + 1)[len(STARTING_BAGS)]
        self.assertEqual(
            str(patched_after.actor_action.v.v), str(original_first.actor_action.v.v),
        )

    def test_skip_path_adds_bags_and_redirects_setup(self):
        combined = patch_intro_flow(self.raw, True)
        self.assertEqual(_chain(combined)[0].params.data["Actor"], STARTING_BAGS[0])
        self.assertEqual(combined, skip_intro_cutscene(self.patched))

    def test_no_skip_only_adds_bags(self):
        self.assertEqual(patch_intro_flow(self.raw, False), self.patched)


if __name__ == "__main__":
    unittest.main()
