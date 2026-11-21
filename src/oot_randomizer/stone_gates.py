"""Stone possession gates.

Some flows test whether the player has a spiritual stone through the `Get_StoneOf*_IsCompleted_Exp`
game-data bools. Only the vanilla stone flows set those bools, so a shuffled stone would leave the
gate locked. The gates converted here ask the pouch for the stone item instead, the same way the
Epona check asks for the ocarina.
"""

from __future__ import annotations

import io

from evfl import EventFlow
from evfl.actor import Actor
from evfl.common import ActorIdentifier, StringHolder
from evfl.event import ActionEvent, SwitchEvent

STONE_BOOL_ITEMS: dict[str, str] = {
    "Get_StoneOfForest_IsCompleted_Exp": "Item_Stone_Forest",
    "Get_StoneOfFire_IsCompleted_Exp": "Item_Stone_Fire",
    "Get_StoneOfWater_IsCompleted_Exp": "Item_Stone_Water",
}

# Diagnostic switch. False leaves the original Get_StoneOf*_IsCompleted_Exp gates untouched in the
# flows, so the vanilla bool checks are back in effect. True converts them to pouch queries.
POUCH_STONE_GATES = True

# flow file name -> stone bools whose gates in that flow are converted
STONE_GATE_FLOWS: dict[str, frozenset[str]] = {
    "DoorOfTime.bfevfl.zs": frozenset({"Get_StoneOfFire_IsCompleted_Exp", "Get_StoneOfWater_IsCompleted_Exp"}),
    "Dm_Goron_0028.bfevfl.zs": frozenset({"Get_StoneOfFire_IsCompleted_Exp"}),
}

_GAME_DATA_ACTOR = "GameDataActor"
_GAME_DATA_BOOL_QUERY = "EventQueryIsGameDataBoolExp"
_POUCH_ACTOR = "PouchSystemActor"
_POUCH_QUERY = "EventQueryIsExistInPouch"


def _stone_switches(flow: EventFlow, bools: frozenset[str]) -> list[SwitchEvent]:
    hits = []
    for event in flow.flowchart.events:
        body = event.data
        if not isinstance(body, SwitchEvent) or body.actor.v is None or body.actor_query.v is None:
            continue
        if body.actor.v.identifier.name != _GAME_DATA_ACTOR or body.actor_query.v.v != _GAME_DATA_BOOL_QUERY:
            continue
        if body.params is not None and body.params.data.get("GameDataName") in bools:
            hits.append(body)
    return hits


def _pouch_actor(flow: EventFlow) -> Actor:
    for actor in flow.flowchart.actors:
        if actor.identifier.name == _POUCH_ACTOR:
            return actor
    actor = Actor()
    actor.identifier = ActorIdentifier(_POUCH_ACTOR)
    actor.concurrent_clips = 1
    flow.flowchart.actors.append(actor)
    return actor


def _query(actor: Actor, name: str) -> StringHolder:
    for holder in actor.queries:
        if holder.v == name:
            return holder
    holder = StringHolder(name)
    actor.queries.append(holder)
    return holder


STONE_SLOT_FLOWS: tuple[str, ...] = (
    "Dm_Kokiri_0130.bfevfl.zs",
    "Dm_DeathMtTrail_0025.bfevfl.zs",
    "Dm_ZoraFountain_0030.bfevfl.zs",
)
_STONE_GRANT_SUBFLOW = "GetPouchContentByActorName"
# Shared get-item flow: every chest, heart piece, and NPC grant that uses it adds its item here.
POUCH_ADD_FLOWS: tuple[str, ...] = ("Dm_SY_Get.bfevfl.zs",)
POUCH_ADD_SUBFLOW = "PouchAddItem"
_STONE_CHECK_FLOW = "DoorOfTime"
_STONE_CHECK_ENTRY = "DoorOfTime_CheckStoneNum"
_STONE_CHECK_FLOW_FILE = "DoorOfTime.bfevfl.zs"


def add_stone_count_check(data: bytes, grant_subflow: str = _STONE_GRANT_SUBFLOW) -> bytes:
    """Run DoorOfTime_CheckStoneNum right after a pouch grant sub-flow.

    The Door of Time only recounts stones when Zora's Fountain is left, so this call runs after
    each grant instead. It is inserted after the `grant_subflow` sub-flow, so the item is already
    in the pouch. The check's own stone gates decide whether any progress happens. Returns the
    input unchanged when the call is already present. Raises ValueError unless the flow has
    exactly one grant.
    """
    from evfl.event import Event, SubFlowEvent
    from evfl.util import make_index

    flow = EventFlow()
    flow.read(data)
    events = flow.flowchart.events
    if any(
        isinstance(e.data, SubFlowEvent) and e.data.entry_point_name == _STONE_CHECK_ENTRY
        for e in events
    ):
        return data
    grants = [
        e for e in events
        if isinstance(e.data, SubFlowEvent) and e.data.entry_point_name == grant_subflow
    ]
    if len(grants) != 1 or grants[0].data.nxt.v is None:
        raise ValueError(f"flow has {len(grants)} {grant_subflow} grants, expected 1")
    grant = grants[0]

    node = SubFlowEvent()
    node.res_flowchart_name = _STONE_CHECK_FLOW
    node.entry_point_name = _STONE_CHECK_ENTRY
    node.nxt = make_index(grant.data.nxt.v)
    new_event = Event()
    new_event.name = f"AutoEvent_{_STONE_CHECK_ENTRY}_after_{grant.name}"
    new_event.data = node
    grant.data.nxt = make_index(new_event)
    events.append(new_event)
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def add_stone_count_check_at_route_end(data: bytes, grant_subflow: str = POUCH_ADD_SUBFLOW) -> bytes:
    """Run DoorOfTime_CheckStoneNum after the grant's get-item route has finished.

    Calling the check straight after the grant cuts into the get-item presentation that follows it.
    This instead walks the events after the grant and points each exit of that route at the check,
    so the check runs last. Returns the input unchanged when the call is already present. Raises
    ValueError unless the flow has exactly one grant and the route after it is simple.

    A switch whose only case is 0 is a bool query, so its missing case 1 is the false exit and
    also ends the route.
    """
    from evfl.event import ActionEvent, Event, SubFlowEvent, SwitchEvent
    from evfl.util import RequiredIndex, make_index

    flow = EventFlow()
    flow.read(data)
    events = flow.flowchart.events
    if any(
        isinstance(e.data, SubFlowEvent) and e.data.entry_point_name == _STONE_CHECK_ENTRY
        for e in events
    ):
        return data
    grants = [
        e for e in events
        if isinstance(e.data, SubFlowEvent) and e.data.entry_point_name == grant_subflow
    ]
    if len(grants) != 1 or grants[0].data.nxt.v is None:
        raise ValueError(f"flow has {len(grants)} {grant_subflow} grants, expected 1")

    node = SubFlowEvent()
    node.res_flowchart_name = _STONE_CHECK_FLOW
    node.entry_point_name = _STONE_CHECK_ENTRY
    check = Event()
    check.name = f"AutoEvent_{_STONE_CHECK_ENTRY}_at_end_of_{grants[0].name}"
    check.data = node

    exits = 0
    seen: set[int] = set()
    stack = [grants[0].data.nxt.v]
    while stack:
        event = stack.pop()
        if id(event) in seen:
            continue
        seen.add(id(event))
        body = event.data
        if isinstance(body, (ActionEvent, SubFlowEvent)):
            if body.nxt.v is None:
                body.nxt = make_index(check)
                exits += 1
            else:
                stack.append(body.nxt.v)
        elif isinstance(body, SwitchEvent):
            stack.extend(target.v for target in body.cases.values())
            if set(body.cases) == {0}:
                false_exit = RequiredIndex()
                false_exit.v = check
                body.cases[1] = false_exit
                exits += 1
        else:
            raise ValueError(f"unexpected {type(body).__name__} after {grant_subflow}")
    if exits == 0:
        raise ValueError(f"no route exit after {grant_subflow}")
    events.append(check)
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


# Diagnostic bools for the Door of Time stone check. The first is written on entry, and the others
# are written before each progress branch, so a test ROM shows whether the check ran and which path
# it took. False leaves the flow untouched.
STONE_CHECK_DIAGNOSTICS = True
_DIAG_ENTRY_BOOL = "Rando_Diag_StoneCheck_Ran"
# (event name in DoorOfTime, bool written before it)
_DIAG_BRANCH_BOOLS: tuple[tuple[str, str], ...] = (
    ("Event37", "Rando_Diag_StoneCheck_Step03"),
    ("Event147", "Rando_Diag_StoneCheck_Step2_1"),
    ("Event148", "Rando_Diag_StoneCheck_Step2_2"),
    ("Event6", "Rando_Diag_StoneCheck_Both"),
)


def _add_stone_check_diagnostics(flow: EventFlow) -> bool:
    from .game_flags import insert_bool_write_before

    entry = next(ep for ep in flow.flowchart.entry_points if ep.name == _STONE_CHECK_ENTRY)
    first = entry.main_event.v.data
    if isinstance(first, ActionEvent) and first.params is not None:
        if first.params.data.get("GameDataName") == _DIAG_ENTRY_BOOL:
            return False
    events = {e.name: e for e in flow.flowchart.events}
    insert_bool_write_before(flow.flowchart, entry.main_event.v, _DIAG_ENTRY_BOOL, True)
    for event_name, flag in _DIAG_BRANCH_BOOLS:
        insert_bool_write_before(flow.flowchart, events[event_name], flag, True)
    return True


def patch_stone_gates(data: bytes, flow_name: str) -> bytes:
    bools = STONE_GATE_FLOWS.get(flow_name)
    if not bools:
        return data
    flow = EventFlow()
    flow.read(data)
    changed = False
    if POUCH_STONE_GATES:
        switches = _stone_switches(flow, bools)
        if switches:
            pouch = _pouch_actor(flow)
            for body in switches:
                stone_bool = body.params.data["GameDataName"]
                body.actor.v = pouch
                body.actor_query.v = _query(pouch, _POUCH_QUERY)
                body.params.data = {"Actor": STONE_BOOL_ITEMS[stone_bool], "Num": 1}
            changed = True
    if STONE_CHECK_DIAGNOSTICS and flow_name == _STONE_CHECK_FLOW_FILE:
        changed = _add_stone_check_diagnostics(flow) or changed
    if not changed:
        return data
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()
