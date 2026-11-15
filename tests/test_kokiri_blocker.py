import io
import unittest
from pathlib import Path

from oot_randomizer.kokiri_blocker import (
    MIDO_BLOCKER_FLAG,
    MIDO_BLOCKER_FLOW,
    MIDO_BLOCKER_FLOWS,
    clear_mido_blocker,
    set_flag_before_action,
)

RAW_DIR = Path(
    r"C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405\files\raw"
)
RAW_SARIA_FLOW = RAW_DIR / "Dm_Kokiri_0145.bfevfl"
RAW_CASTLE_FLOW = RAW_DIR / "Goto_HyruleCastle.bfevfl"


def _load(data: bytes):
    from evfl import EventFlow

    flow = EventFlow()
    flow.read(data)
    return flow


def _serialize(flow) -> bytes:
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def _saria_warps(flow):
    from evfl.event import ActionEvent

    return [
        e for e in flow.flowchart.events
        if isinstance(e.data, ActionEvent)
        and e.data.actor.v.identifier.name == "Npc_Kokiri_Saria_Child"
        and e.data.actor_action.v.v == "EventWarpToTargetPosAndRot"
    ]


    def test_both_blocker_flows_are_patched(self):
        self.assertEqual(len(MIDO_BLOCKER_FLOWS), 2)
        self.assertIn(MIDO_BLOCKER_FLOW, MIDO_BLOCKER_FLOWS)
        for name in MIDO_BLOCKER_FLOWS:
            self.assertTrue(name.endswith(".bfevfl.zs"))


@unittest.skipUnless(RAW_SARIA_FLOW.exists(), "Dm_Kokiri_0145.bfevfl not available")
class ClearMidoBlockerTest(unittest.TestCase):
    RAW_FLOW = RAW_SARIA_FLOW

    def setUp(self):
        self.raw = self.RAW_FLOW.read_bytes()

    def test_flow_name_is_bfevfl_zs(self):
        self.assertTrue(MIDO_BLOCKER_FLOW.endswith(".bfevfl.zs"))

    def test_clears_flag_before_saria_warp(self):
        from evfl.event import ActionEvent

        before = _load(self.raw)
        warp_before = _saria_warps(before)
        self.assertEqual(len(warp_before), 1)
        before_events = before.flowchart.events
        warp_idx = before_events.index(warp_before[0])
        preds_before = [
            i for i, e in enumerate(before_events)
            if isinstance(e.data, ActionEvent) and e.data.nxt.v is before_events[warp_idx]
        ]
        self.assertTrue(preds_before)

        flow = _load(clear_mido_blocker(self.raw))
        chart = flow.flowchart
        warp = _saria_warps(flow)
        self.assertEqual(len(warp), 1)
        warp = warp[0]

        new = chart.events[-1]
        self.assertIsInstance(new.data, ActionEvent)
        self.assertEqual(new.data.actor.v.identifier.name, "GameDataActor")
        self.assertEqual(new.data.actor_action.v.v, "EventTriggerSetGameDataBool")
        self.assertEqual(new.data.params.data["GameDataName"], MIDO_BLOCKER_FLAG)
        self.assertIs(new.data.params.data["Value"], False)
        self.assertIs(new.data.nxt.v, warp)

        # The write takes over every edge that used to enter Saria's warp.
        preds_after = [
            i for i, e in enumerate(chart.events)
            if isinstance(e.data, ActionEvent) and e.data.nxt.v is new
        ]
        self.assertEqual(preds_after, preds_before)

    def test_output_round_trips_and_keeps_warp_once(self):
        patched = clear_mido_blocker(self.raw)
        again = _serialize(_load(patched))
        self.assertEqual(again, patched)
        self.assertEqual(len(_saria_warps(_load(patched))), 1)

    def test_adds_one_event_and_one_actor_when_missing(self):
        before = _load(self.raw).flowchart
        after = _load(clear_mido_blocker(self.raw)).flowchart
        self.assertEqual(len(after.events), len(before.events) + 1)
        has_game_data = any(a.identifier.name == "GameDataActor" for a in before.actors)
        self.assertEqual(len(after.actors), len(before.actors) + (0 if has_game_data else 1))

    def test_rejects_missing_target_action(self):
        with self.assertRaises(ValueError):
            set_flag_before_action(self.raw, "Npc_Kokiri_Saria_Child", "NoSuchAction", MIDO_BLOCKER_FLAG, False)


@unittest.skipUnless(RAW_CASTLE_FLOW.exists(), "Goto_HyruleCastle.bfevfl not available")
class ClearMidoBlockerCastleTest(ClearMidoBlockerTest):
    RAW_FLOW = RAW_CASTLE_FLOW


if __name__ == "__main__":
    unittest.main()
