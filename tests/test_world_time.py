"""Tests for the castle quest-log steps (world_time)."""

import io
import unittest
from pathlib import Path

from oot_randomizer.world_time import add_goto_quest_progress_to_castle_entry

RAW_CASTLE_FLOW = Path(
    r"C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405\files\raw\Dm_HrlCastle_0000.bfevfl"
)

RAW_CASTLE_GOTO = Path(
    r"C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405\files\raw\Goto_HyruleCastle.bfevfl"
)
@unittest.skipUnless(RAW_CASTLE_FLOW.exists(), "Dm_HrlCastle_0000.bfevfl not available")
class AddGotoQuestProgressToCastleEntryTest(unittest.TestCase):
    def _patched(self):
        from evfl import EventFlow

        patched = EventFlow()
        patched.read(add_goto_quest_progress_to_castle_entry(RAW_CASTLE_FLOW.read_bytes()))
        return patched

    def _quest_steps(self, flow):
        from evfl.event import ActionEvent

        entry = next(e for e in flow.flowchart.entry_points if e.name == "EntryPoint0").main_event.v
        node = entry.data.nxt.v
        steps = []
        while isinstance(node.data, ActionEvent):
            steps.append(node)
            node = node.data.nxt.v
        return steps, node

    def test_runs_the_kaepora_quest_steps_in_order(self):
        from evfl.event import ForkEvent

        steps, after = self._quest_steps(self._patched())
        self.assertEqual(
            [(s.data.actor.v.identifier.name, s.data.actor_action.v.v) for s in steps],
            [
                ("GameDataActor", "EventTriggerSetGameDataBool"),
                ("GameDataActor", "EventTriggerSetGameDataBool"),
                ("PouchSystemActor", "EventTriggerAddOrRemovePouchContent"),
                ("ChallengeSystemActor", "EventExecuteProgressChallengeStep"),
                ("ChallengeSystemActor", "EventTriggerShowChallengeProgressUI"),
            ],
        )
        self.assertIsInstance(after.data, ForkEvent)

    def test_challenge_step_matches_goto_hyrule_castle(self):
        step = self._quest_steps(self._patched())[0][3]
        self.assertEqual(
            dict(step.data.params.data),
            {"ChallengeName": "Goto_HyruleCastle", "StepName": "Step02", "IsIgnoreCompletedChallenge": False,
             "IsWaitEnd": True, "IsIgnoreChallengeProgressUI": True},
        )

    @unittest.skipUnless(RAW_CASTLE_GOTO.exists(), "Goto_HyruleCastle.bfevfl not available")
    def test_every_copied_step_exists_verbatim_in_goto_hyrule_castle(self):
        from evfl import EventFlow
        from evfl.event import ActionEvent

        goto = EventFlow()
        goto.read(RAW_CASTLE_GOTO.read_bytes())
        goto_actions = [
            (e.data.actor.v.identifier.name, e.data.actor_action.v.v, sorted(e.data.params.data.items()))
            for e in goto.flowchart.events
            if isinstance(e.data, ActionEvent) and e.data.params is not None
        ]
        for step in self._quest_steps(self._patched())[0]:
            key = (
                step.data.actor.v.identifier.name,
                step.data.actor_action.v.v,
                sorted(step.data.params.data.items()),
            )
            self.assertIn(key, goto_actions)

    def test_patched_flow_round_trips(self):
        from evfl import EventFlow

        out = io.BytesIO()
        self._patched().write(out)
        reread = EventFlow()
        reread.read(out.getvalue())
        self.assertEqual(len(reread.flowchart.events), len(self._patched().flowchart.events))

if __name__ == "__main__":
    unittest.main()
