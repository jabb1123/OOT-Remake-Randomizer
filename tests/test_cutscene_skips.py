"""Tests for the optional intro-cutscene skip flag."""

import unittest

from oot_randomizer.cli import build_parser
from oot_randomizer.cutscene_skips import INTRO_DEMO_EVENT, INTRO_ENTRY_POINT, INTRO_EVENT_FLOW
from oot_randomizer.config import RandomizerConfig


class IntroSkipFlagTests(unittest.TestCase):
    def test_skip_is_off_by_default(self):
        self.assertFalse(RandomizerConfig().skip_intro)

    def test_cli_flag_enables_skip(self):
        args = build_parser().parse_args(["randomize", "--rom", "game.nup", "--skip-intro"])
        self.assertTrue(args.skip_intro)

    def test_cli_skip_is_off_without_flag(self):
        args = build_parser().parse_args(["randomize", "--rom", "game.nup"])
        self.assertFalse(args.skip_intro)

    def test_targets_opening_introduction_wake_up(self):
        self.assertEqual(INTRO_EVENT_FLOW, "OpeningEvent.bfevfl.zs")
        self.assertEqual(INTRO_ENTRY_POINT, "Opening_Introduction")
        self.assertEqual(INTRO_DEMO_EVENT, "Dm_Kokiri_0030")


if __name__ == "__main__":
    unittest.main()
