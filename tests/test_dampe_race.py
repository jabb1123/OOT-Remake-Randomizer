import unittest
from pathlib import Path

from evfl import EventFlow
from evfl.event import ActionEvent, SwitchEvent

from oot_randomizer.dampe_race import (
    DAMPE_CLEAR_SWITCH,
    DAMPE_RACE_FLOW,
    DAMPE_RUPEE_SETTER,
    patch_dampe_race_rewards,
)

RAW_DAMPE = Path(__file__).resolve().parents[1] / "tmp" / "Events" / "raw" / f"{DAMPE_RACE_FLOW}.raw"


def _by_name(data: bytes) -> dict:
    flow = EventFlow()
    flow.read(data)
    return {event.name: event for event in flow.flowchart.events}


class DampeRaceRewardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not RAW_DAMPE.exists():
            raise unittest.SkipTest(f"raw flow {RAW_DAMPE} not available")
        cls.raw = RAW_DAMPE.read_bytes()

    def test_not_owned_answer_goes_through_clear(self):
        events = _by_name(patch_dampe_race_rewards(self.raw))
        self.assertIs(events[DAMPE_CLEAR_SWITCH].data.cases[1].v, events["Event379"])

    def test_first_race_gives_vanilla_hookshot_award(self):
        events = _by_name(patch_dampe_race_rewards(self.raw))
        self.assertIs(events["Event275"].data.cases[1].v, events["Event327"])

    def test_second_race_uses_timer_check(self):
        events = _by_name(patch_dampe_race_rewards(self.raw))
        self.assertIs(events["Event275"].data.cases[2].v, events["Event359"])

    def test_third_race_onward_sets_rupee_then_vanilla_rupee_talk(self):
        events = _by_name(patch_dampe_race_rewards(self.raw))
        cases = events["Event275"].data.cases
        setter = events[DAMPE_RUPEE_SETTER]
        later = [key for key in cases if key >= 3]
        self.assertTrue(later)
        for key in later:
            self.assertIs(cases[key].v, setter, f"ClearCount {key}")
        node = setter.data
        self.assertIsInstance(node, ActionEvent)
        self.assertEqual(node.params.data["GameDataName"], "Minigame_DampeRace_TreasureBoxState")
        self.assertEqual(node.params.data["Value"], "AppearRupee")
        self.assertIs(node.nxt.v, events["Event393"])
        self.assertIs(events["Event393"].data.nxt.v, events["Event430"])
        self.assertIs(events["Event430"].data.nxt.v, events["Event404"])

    def test_result_switch_is_still_a_switch_on_clear_count(self):
        events = _by_name(patch_dampe_race_rewards(self.raw))
        self.assertIsInstance(events["Event275"].data, SwitchEvent)

    def test_post_race_heart_branch_is_talk_only(self):
        events = _by_name(patch_dampe_race_rewards(self.raw))
        self.assertIs(events["Event342"].data.cases[1].v, events["Event394"])

    def test_patch_is_idempotent(self):
        once = patch_dampe_race_rewards(self.raw)
        self.assertEqual(patch_dampe_race_rewards(once), once)


if __name__ == "__main__":
    unittest.main()
