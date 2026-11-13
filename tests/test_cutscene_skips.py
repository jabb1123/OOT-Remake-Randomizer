"""Tests for the optional intro-cutscene skip flag."""

import unittest
from pathlib import Path

from evfl import EventFlow
from evfl.event import ActionEvent

from oot_randomizer.cli import build_parser
from oot_randomizer.cutscene_skips import (
    INTRO_DEMO_EVENT,
    INTRO_ENTRY_POINT,
    INTRO_EVENT_FLOW,
    skip_intro_cutscene,
)
from oot_randomizer.config import RandomizerConfig

RAW_DIR = Path(
    r"C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405\files\raw"
)
RAW_OPENING = RAW_DIR / "OpeningEvent.bfevfl"


def _entry_names(data: bytes) -> list[str]:
    flow = EventFlow()
    flow.read(data)
    return [e.name for e in flow.flowchart.entry_points]


def _all_events(data: bytes) -> list[str]:
    flow = EventFlow()
    flow.read(data)
    return [e.name for e in flow.flowchart.events]


def _chain_events(data: bytes, entry_name: str) -> list[str]:
    """Event names reachable from an entry point, following `next` links and switch cases."""
    from evfl.event import SwitchEvent

    flow = EventFlow()
    flow.read(data)
    entry = next(e for e in flow.flowchart.entry_points if e.name == entry_name)
    names: list[str] = []
    stack = [entry.main_event.v]
    seen = set()
    while stack:
        event = stack.pop(0)
        if event is None or id(event) in seen:
            continue
        seen.add(id(event))
        names.append(event.name)
        if isinstance(event.data, ActionEvent):
            stack.append(event.data.nxt.v)
        elif isinstance(event.data, SwitchEvent):
            stack.extend(case.v for case in event.data.cases.values())
    return names



class IntroSkipFlagTests(unittest.TestCase):
    def test_skip_is_off_by_default(self):
        self.assertFalse(RandomizerConfig().skip_intro)

    def test_cli_flag_enables_skip(self):
        args = build_parser().parse_args(["randomize", "--rom", "game.nup", "--skip-intro"])
        self.assertTrue(args.skip_intro)

    def test_cli_skip_is_off_without_flag(self):
        args = build_parser().parse_args(["randomize", "--rom", "game.nup"])
        self.assertFalse(args.skip_intro)

    def test_targets_opening_introduction(self):
        self.assertEqual(INTRO_EVENT_FLOW, "OpeningEvent.bfevfl.zs")
        self.assertEqual(INTRO_ENTRY_POINT, "Opening_Introduction")
        self.assertEqual(INTRO_DEMO_EVENT, "Dm_Kokiri_0030")


@unittest.skipUnless(RAW_OPENING.exists(), "OpeningEvent fixture not extracted")
class IntroSkipCutsceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = RAW_OPENING.read_bytes()
        cls.patched = skip_intro_cutscene(cls.raw)

    def test_intro_chain_reaches_demo_without_patch(self):
        self.assertIn("Event5", _chain_events(self.raw, INTRO_ENTRY_POINT))

    def test_patched_intro_skips_staging_and_demo(self):
        chain = _chain_events(self.patched, INTRO_ENTRY_POINT)
        for skipped in ("Event8", "Event32", "Event27", "Event5", "Event22", "Event16"):
            self.assertNotIn(skipped, chain)
        self.assertEqual(chain[:4], ["Event13", "Event9", "Event24", "Event17"])

    def test_patched_intro_keeps_post_skip_bgm_and_autosave(self):
        chain = _chain_events(self.patched, INTRO_ENTRY_POINT)
        self.assertIn("Event4", chain)
        self.assertIn("Event12", chain)

    def test_loading_entry_point_is_untouched(self):
        self.assertEqual(
            _chain_events(self.patched, "Opening_LoadingKokiriForest"),
            _chain_events(self.raw, "Opening_LoadingKokiriForest"),
        )

    def test_layout_keeps_entry_points_and_events(self):
        self.assertEqual(len(_all_events(self.patched)), len(_all_events(self.raw)))
        self.assertEqual(
            _entry_names(self.patched),
            _entry_names(self.raw),
        )

    def test_patch_is_idempotent(self):
        self.assertEqual(skip_intro_cutscene(self.patched), self.patched)


if __name__ == "__main__":
    unittest.main()

