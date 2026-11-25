"""AllSage progress from the number of dungeon medals held.

AllSage no longer checks each dungeon. Every pickup that adds an item runs a count of the five dungeon
medals held, then moves AllSage to the step for that count, with the popup when it advances:

    1 medal -> Step01_00, 2 -> Step01_00_01, 3 -> Step01_00_02, 4 -> Step01_00_03, 5 -> Step01_01

The sage quests themselves are not changed. A medal does not set any SageOf<X> step, so each sage's own
flow still finishes it and its dungeon drops are kept. The temple-exit steps are removed by
sage_escape_flow.py. Kakariko Burning and the Forest prelude read medals directly (medal_exp.py).

Each count leaf reads an AllSage_IsAfter_* bool first and skips when the quest is already past its step,
so the count never moves AllSage backwards. Light is not counted. It is a shuffled item that belongs to no
dungeon, so it does not move any sage's step. Its logic is in has_two_medals (Sheik return to child).
"""

from __future__ import annotations

import io

from evfl import EventFlow
from evfl.container import Container
from evfl.event import ActionEvent, Event, SubFlowEvent, SwitchEvent
from evfl.util import make_index, make_rindex

from .game_flags import (
    CHALLENGE_ACTOR,
    CHALLENGE_PROGRESS_ACTION,
    _find_or_create_action,
    game_data_actor,
)
from .stone_gates import (
    _GAME_DATA_BOOL_QUERY,
    HELD_MEDAL_BOOL_PREFIX,
    POUCH_ADD_SUBFLOW,
    _query,
    _single_grant,
)

GET_POUCH_CONTENT_FLOW = "GetPouchContent.bfevfl.zs"
GET_IN_EVENT_FLOW = "Dm_SY_GetInEvent.bfevfl.zs"

MEDAL_ITEMS: tuple[str, ...] = (
    "Item_Medal_Forest",
    "Item_Medal_Fire",
    "Item_Medal_Water",
    "Item_Medal_Shadow",
    "Item_Medal_Spirit",
)


# The held check reads the IsGet.Item_Medal_* game bool, which is set when the medal is obtained.
# A pouch check would miss a medal that is no longer in the pouch.
_HELD_QUERY = "EventQueryIsGameDataBool"


def held_medal_bool(medal: str) -> str:
    return f"{HELD_MEDAL_BOOL_PREFIX}{medal.removeprefix('Item_Medal_')}"


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


def _count_tree(flow: EventFlow, exit_to: Event | None, prefix: str) -> Event | None:
    """Build the held-medal count and return its entry. Every path ends at `exit_to`.

    A held check for each medal forms a binary tree. A node is keyed by the medal index and the count
    so far, so paths with the same count share their nodes. The leaves are the counts, each going to
    its AllSage step. A count of 0 goes straight to `exit_to`. A None `exit_to` ends the branch, so
    switch cases that would go there are left out.
    """
    chart = flow.flowchart
    game_data = game_data_actor(chart)
    bool_query = _query(game_data, _GAME_DATA_BOOL_QUERY)
    held_query = _query(game_data, _HELD_QUERY)
    challenge_actor, progress_action = _find_or_create_action(chart, CHALLENGE_ACTOR, CHALLENGE_PROGRESS_ACTION)
    steps: dict[int, Event] = {}
    checks: dict[tuple[int, int], Event] = {}

    def step_for(count: int) -> Event | None:
        if count == 0:
            return exit_to
        if count not in steps:
            # Popup on: this is a test build, so each sub-step advance shows its progress window.
            progress = _progress_node(challenge_actor, progress_action, prefix, f"Step_{count}", {
                "ChallengeName": ALLSAGE_CHALLENGE,
                "StepName": COUNT_STEPS[count],
                "IsWaitEnd": True,
                "IsIgnoreChallengeProgressUI": False,
                "IsIgnoreCompletedChallenge": True,
            }, exit_to)
            chart.events.append(progress)

            gate_node = SwitchEvent()
            gate_node.actor = make_rindex(game_data)
            gate_node.actor_query = make_rindex(bool_query)
            gate_node.params = Container()
            gate_node.params.data.update({"GameDataName": COUNT_PAST_BOOLS[count]})
            # EventQueryIsGameDataBoolExp: case 1 = true (already past the step), case 0 = false.
            gate_node.cases = {0: make_rindex(progress)}
            if exit_to is not None:
                gate_node.cases[1] = make_rindex(exit_to)
            gate = Event()
            gate.name = f"{prefix}Gate_{count}"
            gate.data = gate_node
            chart.events.append(gate)
            steps[count] = gate
        return steps[count]

    def check_for(index: int, held: int) -> Event | None:
        if index == len(MEDAL_ITEMS):
            return step_for(held)
        key = (index, held)
        if key not in checks:
            owned = check_for(index + 1, held + 1)
            missing = check_for(index + 1, held)
            node = SwitchEvent()
            node.actor = make_rindex(game_data)
            node.actor_query = make_rindex(held_query)
            node.params = Container()
            node.params.data.update({"GameDataName": held_medal_bool(MEDAL_ITEMS[index])})
            # EventQueryIsGameDataBool: case 1 = held, case 0 = not held. A None `missing` ends that branch.
            node.cases = {1: make_rindex(owned)}
            if missing is not None:
                node.cases[0] = make_rindex(missing)
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


def add_medal_progress_at_route_end(data: bytes, grant_subflow: str = POUCH_ADD_SUBFLOW) -> bytes:
    """Run the medal count after the grant's get-item route has finished.

    Chests, hearts, and NPC grants all pass through the shared pouch add in Dm_SY_Get, and a medal from
    those does not reach the pouch add hooks in GetPouchContent. This walks the route after the grant
    and points each open exit at the count, so it runs after the item is in the pouch and after the
    presentation, the same placement the stone check uses. Every exit is collected before the count is
    built, so the count's own events are not walked. Returns the input unchanged when the count is
    already present. Raises ValueError unless the flow has exactly one grant and the route is simple.
    """
    flow = _read(data)
    if _has_sync(flow):
        return data
    grant = _single_grant(flow, grant_subflow)

    open_nxt: list[ActionEvent | SubFlowEvent] = []
    open_cases: list[SwitchEvent] = []
    seen: set[int] = set()
    stack = [grant.data.nxt.v]
    while stack:
        event = stack.pop()
        if id(event) in seen:
            continue
        seen.add(id(event))
        body = event.data
        if isinstance(body, (ActionEvent, SubFlowEvent)):
            if body.nxt.v is None:
                open_nxt.append(body)
            else:
                stack.append(body.nxt.v)
        elif isinstance(body, SwitchEvent):
            stack.extend(target.v for target in body.cases.values())
            # A switch whose only case is 0 is a bool query, so its missing case 1 is the false exit.
            if set(body.cases) == {0}:
                open_cases.append(body)
        else:
            raise ValueError(f"unexpected {type(body).__name__} after {grant_subflow}")
    if not open_nxt and not open_cases:
        raise ValueError(f"no route exit after {grant_subflow}")

    entry = _count_tree(flow, None, prefix=f"{_SYNC_PREFIX}Route_")
    for body in open_nxt:
        body.nxt = make_index(entry)
    for body in open_cases:
        body.cases[1] = make_rindex(entry)
    return _write(flow)


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


def add_medal_progress_after_allsage_step01(data: bytes) -> bytes:
    """Run the medal count right after AllSage's Step01, the step the sages start from.

    A player who already holds medals when AllSage reaches Step01 moves on to the step for that
    count, the same as a medal picked up later. Returns the input unchanged when the chain is already
    present. Raises ValueError unless the flow has exactly one AllSage Step01 progress node.
    """
    flow = _read(data)
    if _has_sync(flow):
        return data
    nodes = [
        event
        for event in flow.flowchart.events
        if isinstance(event.data, ActionEvent)
        and event.data.actor_action.v is not None
        and event.data.actor_action.v.v == CHALLENGE_PROGRESS_ACTION
        and event.data.params is not None
        and event.data.params.data.get("ChallengeName") == ALLSAGE_CHALLENGE
        and event.data.params.data.get("StepName") == "Step01"
    ]
    if len(nodes) != 1:
        raise ValueError(
            f"flow has {len(nodes)} AllSage Step01 progress nodes, expected 1"
        )
    _hook_after(flow, nodes[0])
    return _write(flow)
