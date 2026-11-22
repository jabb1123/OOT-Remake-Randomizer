import io
import itertools
import unittest
from pathlib import Path

from evfl import EventFlow
from evfl.event import ActionEvent, ForkEvent, JoinEvent, SubFlowEvent, SubFlowSwitchEvent, SwitchEvent

from oot_randomizer.medal_progress import (
    COUNT_PAST_BOOLS,
    COUNT_STEPS,
    MEDAL_ITEMS,
    add_medal_progress_after_pouch_adds,
    add_medal_progress_after_shop_purchase,
)
from oot_randomizer.sage_escape_flow import BYPASSED_STEPS, ESCAPE_FLOW, patch_escape_sage_completes

RAW_DIR = Path(__file__).resolve().parents[1] / "tmp" / "Events" / "raw"
RAW_POUCH = RAW_DIR / "GetPouchContent.bfevfl.zs.raw"
RAW_IN_EVENT = RAW_DIR / "Dm_SY_GetInEvent.bfevfl.zs.raw"
RAW_SHOP = RAW_DIR / "DisplayShop.bfevfl.zs.raw"
RAW_ESCAPE = RAW_DIR / f"{ESCAPE_FLOW}.raw"
SYNC_PREFIX = "MedalSync_"


def _load(data: bytes) -> EventFlow:
    flow = EventFlow()
    flow.read(data)
    return flow


def _serialize(flow: EventFlow) -> bytes:
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def _by_name(data: bytes) -> dict:
    return {event.name: event for event in _load(data).flowchart.events}


def _targets(flow: EventFlow):
    for event in flow.flowchart.events:
        body = event.data
        if isinstance(body, (ActionEvent, JoinEvent, SubFlowEvent)):
            yield body.nxt.v
        elif isinstance(body, (SwitchEvent, SubFlowSwitchEvent)):
            for case in body.cases.values():
                yield case.v
        elif isinstance(body, ForkEvent):
            yield from (fork.v for fork in body.forks)
            yield body.join.v
    for entry in flow.flowchart.entry_points:
        yield entry.main_event.v


def _walk(events: dict, entry, owned: set, past: set):
    """Run the medal count from `entry` and return (steps reached, name of the exit event)."""
    steps = []
    node = entry
    while node is not None and node.name.startswith(SYNC_PREFIX):
        body = node.data
        if isinstance(body, SwitchEvent):
            query = body.actor_query.v.v
            if query == "EventQueryIsExistInPouch":
                case = 0 if body.params.data["Actor"] in owned else 1
            else:
                case = 1 if body.params.data["GameDataName"] in past else 0
            node = body.cases[case].v
        else:
            if body.actor_action.v.v == "EventExecuteProgressChallengeStep":
                steps.append((body.params.data["ChallengeName"], body.params.data["StepName"]))
            node = body.nxt.v
    return steps, node.name if node is not None else None


class MedalCountTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for path in (RAW_POUCH, RAW_IN_EVENT, RAW_SHOP):
            if not path.exists():
                raise unittest.SkipTest(f"raw flow {path} not available")

    def _check_count(self, data: bytes, hooked: str, exit_name: str, past: set):
        events = _by_name(data)
        entry = events[f"{SYNC_PREFIX}{hooked}_Check0_Held0"]
        for size in range(len(MEDAL_ITEMS) + 1):
            for owned in itertools.combinations(MEDAL_ITEMS, size):
                steps, exit_reached = _walk(events, entry, set(owned), past)
                self.assertEqual(exit_reached, exit_name)
                names = [step for challenge, step in steps if challenge == "AllSage"]
                count = len(owned)
                if count == 0 or COUNT_PAST_BOOLS[count] in past:
                    self.assertEqual(names, [])
                else:
                    self.assertEqual(names, [COUNT_STEPS[count]])
                # The sage quests are never completed by a pickup.
                self.assertFalse(any(challenge.startswith("SageOf") for challenge, _ in steps))

    def test_get_pouch_content_counts_held_medals(self):
        raw = RAW_POUCH.read_bytes()
        original_next = _by_name(raw)["Event0"].data.nxt.v.name
        data = add_medal_progress_after_pouch_adds(raw)
        self._check_count(data, "Event0", original_next, past=set())

    def test_count_does_not_move_allsage_past_its_step(self):
        raw = RAW_POUCH.read_bytes()
        original_next = _by_name(raw)["Event0"].data.nxt.v.name
        data = add_medal_progress_after_pouch_adds(raw)
        for count in COUNT_STEPS:
            self._check_count(data, "Event0", original_next, past={COUNT_PAST_BOOLS[count]})

    def test_get_in_event_hooks_every_single_item_add(self):
        raw = RAW_IN_EVENT.read_bytes()
        adds = [
            e.name for e in _load(raw).flowchart.events
            if isinstance(e.data, ActionEvent)
            and e.data.actor_action.v is not None
            and e.data.actor_action.v.v == "EventTriggerAddOrRemovePouchContent"
            and e.data.params.data.get("Num") == 1
        ]
        self.assertTrue(adds)
        events = _by_name(add_medal_progress_after_pouch_adds(raw))
        for name in adds:
            self.assertTrue(events[name].data.nxt.v.name.startswith(f"{SYNC_PREFIX}{name}_Check0_Held0"))

    def test_patch_is_idempotent(self):
        patched = add_medal_progress_after_pouch_adds(RAW_POUCH.read_bytes())
        self.assertEqual(add_medal_progress_after_pouch_adds(patched), patched)

    def test_patched_flow_round_trips(self):
        patched = add_medal_progress_after_pouch_adds(RAW_POUCH.read_bytes())
        self.assertEqual(_serialize(_load(patched)), patched)

    def test_shop_purchase_hook(self):
        raw = RAW_SHOP.read_bytes()
        patched = add_medal_progress_after_shop_purchase(raw)
        events = _by_name(patched)
        purchases = [
            e.name for e in _load(raw).flowchart.events
            if isinstance(e.data, ActionEvent)
            and e.data.actor_action.v is not None
            and e.data.actor_action.v.v == "EventTriggerShopItemPutInPouch"
        ]
        self.assertTrue(purchases)
        for name in purchases:
            self.assertTrue(events[name].data.nxt.v.name.startswith(f"{SYNC_PREFIX}{name}_Check0_Held0"))
        self.assertEqual(add_medal_progress_after_shop_purchase(patched), patched)


class EscapeSageCompletesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not RAW_ESCAPE.exists():
            raise unittest.SkipTest(f"raw flow {RAW_ESCAPE} not available")

    def test_bypassed_steps_are_removed_and_nothing_points_at_them(self):
        patched = patch_escape_sage_completes(RAW_ESCAPE.read_bytes())
        flow = _load(patched)
        names = {event.name for event in flow.flowchart.events}
        removed = {name for name, _, _ in BYPASSED_STEPS}
        self.assertFalse(removed & names)
        targets = {t.name for t in _targets(flow) if t is not None}
        self.assertFalse(removed & targets)

    def test_sage_complete_steps_are_kept_and_skip_allsage(self):
        patched = patch_escape_sage_completes(RAW_ESCAPE.read_bytes())
        events = {event.name: event for event in _load(patched).flowchart.events}
        for name in ("Event199", "Event40", "Event41", "Event73", "Event141"):
            self.assertIn(name, events)
        self.assertEqual(events["Event199"].data.nxt.v.name, "Event174")

    def test_patch_is_idempotent_and_round_trips(self):
        patched = patch_escape_sage_completes(RAW_ESCAPE.read_bytes())
        self.assertEqual(patch_escape_sage_completes(patched), patched)
        self.assertEqual(_serialize(_load(patched)), patched)


if __name__ == "__main__":
    unittest.main()
