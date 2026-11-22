"""AllSage progress from the number of dungeon medals held.

AllSage no longer checks each dungeon. Every pickup that adds an item runs a count of the five dungeon
medals in the pouch, then moves AllSage to the step for that count, with the popup when it advances:

    1 medal -> Step01_00, 2 -> Step01_00_01, 3 -> Step01_00_02, 4 -> Step01_00_03, 5 -> Step01_01

The sage quests themselves are not changed. A medal does not set any SageOf<X> step, so each sage's own
flow still finishes it and its dungeon drops are kept. The temple-exit steps are removed by
sage_escape_flow.py.

Each count leaf reads an AllSage_IsAfter_* bool first and skips when the quest is already past its step,
so the count never moves AllSage backwards. Light is not counted. Its medal comes from the first trip to
adulthood, before any dungeon medal can be held.
"""

from __future__ import annotations

import io

from evfl import EventFlow
from evfl.container import Container
from evfl.event import ActionEvent, Event, SwitchEvent
from evfl.util import make_index, make_rindex

from .game_flags import (
    CHALLENGE_ACTOR,
    CHALLENGE_PROGRESS_ACTION,
    _find_or_create_action,
    game_data_actor,
)
from .stone_gates import _GAME_DATA_BOOL_QUERY, _POUCH_QUERY, _pouch_actor, _query

GET_POUCH_CONTENT_FLOW = "GetPouchContent.bfevfl.zs"
GET_IN_EVENT_FLOW = "Dm_SY_GetInEvent.bfevfl.zs"

MEDAL_ITEMS: tuple[str, ...] = (
    "Item_Medal_Forest",
    "Item_Medal_Fire",
    "Item_Medal_Water",
    "Item_Medal_Shadow",
    "Item_Medal_Spirit",
)

_SYNC_PREFIX = "MedalSync_"
_POUCH_ADD_ACTION = "EventTriggerAddOrRemovePouchContent"
_SHOP_PURCHASE_ACTION = "EventTriggerShopItemPutInPouch"

ALLSAGE_CHALLENGE = "AllSage"
# AllSage step reached for each count of held dungeon medals.
COUNT_STEPS: dict[int, str] = {
    1: "Step01_00",
    2: "Step01_00_01",
    3: "Step01_00_02",
    4: "Step01_00_03",
    5: "Step01_01",
}
# The bool that is true once AllSage is past each count's step. Only three AllSage_IsAfter_* bools
# exist in the dumps, so counts 2 and 4 use the nearest later one. Verify these in game.
COUNT_PAST_BOOLS: dict[int, str] = {
    1: "AllSage_IsAfter_Step01_Exp",
    2: "AllSage_IsAfter_Step01_00_02_Exp",
    3: "AllSage_IsAfter_Step01_00_02_Exp",
    4: "AllSage_IsAfter_Step01_01_Exp",
    5: "AllSage_IsAfter_Step01_01_Exp",
}


def _read(data: bytes) -> EventFlow:
    flow = EventFlow()
    flow.read(data)
    return flow


def _write(flow: EventFlow) -> bytes:
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def _progress_node(chart_actor, action, prefix: str, name: str, params: dict, nxt: Event | None) -> Event:
    node = ActionEvent()
    node.actor = make_rindex(chart_actor)
    node.actor_action = make_rindex(action)
    node.params = Container()
    node.params.data.update(params)
    node.nxt = make_index(nxt)
    event = Event()
    event.name = f"{prefix}{name}"
    event.data = node
    return event


def _count_tree(flow: EventFlow, exit_to: Event, prefix: str) -> Event:
    """Build the held-medal count and return its entry. Every path ends at `exit_to`.

    A pouch check for each medal forms a binary tree. A node is keyed by the medal index and the count
    so far, so paths with the same count share their nodes. The leaves are the counts, each going to
    its AllSage step. A count of 0 goes straight to `exit_to`.
    """
    chart = flow.flowchart
    pouch = _pouch_actor(flow)
    pouch_query = _query(pouch, _POUCH_QUERY)
    game_data = game_data_actor(chart)
    bool_query = _query(game_data, _GAME_DATA_BOOL_QUERY)
    challenge_actor, progress_action = _find_or_create_action(chart, CHALLENGE_ACTOR, CHALLENGE_PROGRESS_ACTION)
    steps: dict[int, Event] = {}
    checks: dict[tuple[int, int], Event] = {}

    def step_for(count: int) -> Event:
        if count == 0:
            return exit_to
        if count not in steps:
            # Silent: the step can be set again by a later pickup, and a popup would repeat each time.
            progress = _progress_node(challenge_actor, progress_action, prefix, f"Step_{count}", {
                "ChallengeName": ALLSAGE_CHALLENGE,
                "StepName": COUNT_STEPS[count],
                "IsWaitEnd": True,
                "IsIgnoreChallengeProgressUI": True,
                "IsIgnoreCompletedChallenge": True,
            }, exit_to)
            chart.events.append(progress)

            gate_node = SwitchEvent()
            gate_node.actor = make_rindex(game_data)
            gate_node.actor_query = make_rindex(bool_query)
            gate_node.params = Container()
            gate_node.params.data.update({"GameDataName": COUNT_PAST_BOOLS[count]})
            # EventQueryIsGameDataBoolExp: case 1 = true (already past the step), case 0 = false.
            gate_node.cases = {0: make_rindex(progress), 1: make_rindex(exit_to)}
            gate = Event()
            gate.name = f"{prefix}Gate_{count}"
            gate.data = gate_node
            chart.events.append(gate)
            steps[count] = gate
        return steps[count]

    def check_for(index: int, held: int) -> Event:
        if index == len(MEDAL_ITEMS):
            return step_for(held)
        key = (index, held)
        if key not in checks:
            owned = check_for(index + 1, held + 1)
            missing = check_for(index + 1, held)
            node = SwitchEvent()
            node.actor = make_rindex(pouch)
            node.actor_query = make_rindex(pouch_query)
            node.params = Container()
            node.params.data.update({"Actor": MEDAL_ITEMS[index], "Num": 1})
            # EventQueryIsExistInPouch: case 0 = owned, case 1 = not owned.
            node.cases = {0: make_rindex(owned), 1: make_rindex(missing)}
            check = Event()
            check.name = f"{prefix}Check{index}_Held{held}"
            check.data = node
            chart.events.append(check)
            checks[key] = check
        return checks[key]

    return check_for(0, 0)


def _hook_after(flow: EventFlow, node: Event) -> None:
    """Run the medal count after `node` finishes, before its original successor."""
    body = node.data
    if body.nxt.v is None:
        raise ValueError(f"{node.name} has no successor to hook the medal count in front of")
    first = _count_tree(flow, body.nxt.v, prefix=f"{_SYNC_PREFIX}{node.name}_")
    body.nxt = make_index(first)


def _has_sync(flow: EventFlow) -> bool:
    return any(event.name.startswith(_SYNC_PREFIX) for event in flow.flowchart.events)


def _pouch_add_nodes(flow: EventFlow) -> list[Event]:
    hits = []
    for event in flow.flowchart.events:
        body = event.data
        if not isinstance(body, ActionEvent) or body.actor_action.v is None:
            continue
        if body.actor_action.v.v != _POUCH_ADD_ACTION or body.params is None:
            continue
        if body.params.data.get("Num") == 1:
            hits.append(event)
    return hits


def add_medal_progress_after_pouch_adds(data: bytes) -> bytes:
    """Run the medal progress chain after each pouch add of one item in the flow.

    Used for GetPouchContent, which every chest, event slot, and ByActorName grant runs through,
    and for Dm_SY_GetInEvent, which NPC hand-overs and GetInEvent grants use. Returns the input
    unchanged when the chain is already present. Raises ValueError when no pouch add is found.
    """
    flow = _read(data)
    if _has_sync(flow):
        return data
    adds = _pouch_add_nodes(flow)
    if not adds:
        raise ValueError(f"no {_POUCH_ADD_ACTION} add of one item in the flow")
    for node in adds:
        _hook_after(flow, node)
    return _write(flow)


def add_medal_progress_after_shop_purchase(data: bytes) -> bytes:
    """Run the medal progress chain after each shop purchase's pouch add.

    The purchase node already gives the item, so the chain sees a medal bought in any shop slot.
    Returns the input unchanged when the chain is already present. Raises ValueError when the flow
    has no purchase node.
    """
    flow = _read(data)
    if _has_sync(flow):
        return data
    purchases = [
        event for event in flow.flowchart.events
        if isinstance(event.data, ActionEvent)
        and event.data.actor_action.v is not None
        and event.data.actor_action.v.v == _SHOP_PURCHASE_ACTION
    ]
    if not purchases:
        raise ValueError(f"DisplayShop has no {_SHOP_PURCHASE_ACTION} action")
    for node in purchases:
        _hook_after(flow, node)
    return _write(flow)
