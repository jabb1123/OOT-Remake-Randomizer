"""Stone possession gates.

Some flows test whether the player has a spiritual stone through the `Get_StoneOf*_IsCompleted_Exp`
game-data bools. Only the vanilla stone flows set those bools, so a shuffled stone would leave the
gate locked. The gates converted here ask the pouch for the stone item instead, the same way the
Epona check asks for the ocarina.
"""

from __future__ import annotations

from copy import deepcopy
import io

from evfl import EventFlow
from evfl.actor import Actor
from evfl.common import ActorIdentifier, StringHolder
from evfl.event import ActionEvent, Event, SubFlowEvent, SwitchEvent
from evfl.util import RequiredIndex, make_index, make_rindex

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
# Held-medal checks from medal_progress read IsGet.Item_Medal_* with case 1 = held and no case 0 when the
# count is built for a route, so the route walk must treat their missing case 0 as open.
HELD_MEDAL_BOOL_PREFIX = "IsGet.Item_Medal_"


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
STONE_CHECK_FLOW_FILE = "DoorOfTime.bfevfl.zs"
# Holds the DoorOfTime Step02 progress node that the stone check follows (Event7 in DoorOfTime).
DOOR_OF_TIME_START_FLOW_FILE = "DoorOfTime.bfevfl.zs"
# Prefix on the check's events once copied into a calling flow.
_INLINE_PREFIX = "StoneCheck_"
# Skips the copied check once the Door of Time quest is at Step03 or further, so a stone pickup
# after that point does not progress the quest again.
_STEP_GATE_BOOL = "DoorOfTime_IsAfter_Step03_Exp"
_STEP_GATE_NAME = "IsAfterStep03"


def _read_flow(data: bytes) -> EventFlow:
    flow = EventFlow()
    flow.read(data)
    return flow


def _write_flow(flow: EventFlow) -> bytes:
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def _has_inline_check(flow: EventFlow) -> bool:
    return any(e.name.startswith(_INLINE_PREFIX) for e in flow.flowchart.events)


def _single_grant(flow: EventFlow, grant_subflow: str) -> Event:
    grants = [
        e for e in flow.flowchart.events
        if isinstance(e.data, SubFlowEvent) and e.data.entry_point_name == grant_subflow
    ]
    if len(grants) != 1 or grants[0].data.nxt.v is None:
        raise ValueError(f"flow has {len(grants)} {grant_subflow} grants, expected 1")
    return grants[0]


def _holder(holders: list[StringHolder], name: str) -> StringHolder:
    for holder in holders:
        if holder.v == name:
            return holder
    holder = StringHolder(name)
    holders.append(holder)
    return holder


def _flow_actor(flow: EventFlow, src: Actor) -> Actor:
    """Return the flow's actor for `src`, adding a copy of it when the flow does not have one."""
    for actor in flow.flowchart.actors:
        if actor.identifier.name == src.identifier.name:
            return actor
    actor = Actor()
    actor.identifier = ActorIdentifier(src.identifier.name, src.identifier.sub_name)
    actor.params = deepcopy(src.params)
    actor.concurrent_clips = src.concurrent_clips
    actor.actions = [StringHolder(h.v) for h in src.actions]
    actor.queries = [StringHolder(h.v) for h in src.queries]
    flow.flowchart.actors.append(actor)
    return actor


def _step_gate(flow: EventFlow, check: EventFlow, run: Event, exit_to: Event | None, prefix: str) -> Event:
    """Return a switch that runs `run` only while the Door of Time quest is before Step03.

    The true case (already at Step03 or further) skips to `exit_to`. A missing true case ends the
    branch, which matches a route that ends at None.
    """
    src_actor = next(a for a in check.flowchart.actors if a.identifier.name == _GAME_DATA_ACTOR)
    actor = _flow_actor(flow, src_actor)
    template = next(
        e.data for e in check.flowchart.events
        if isinstance(e.data, SwitchEvent) and e.data.actor.v is not None
        and e.data.actor.v.identifier.name == _GAME_DATA_ACTOR
        and e.data.actor_query.v is not None and e.data.actor_query.v.v == _GAME_DATA_BOOL_QUERY
    )
    gate = SwitchEvent()
    gate.actor = make_rindex(actor)
    gate.actor_query = make_rindex(_holder(actor.queries, _GAME_DATA_BOOL_QUERY))
    gate.params = deepcopy(template.params)
    gate.params.data["GameDataName"] = _STEP_GATE_BOOL
    gate.cases = {1: make_rindex(run)}
    if exit_to is not None:
        gate.cases[0] = make_rindex(exit_to)
    event = Event()
    event.name = f"{prefix}{_STEP_GATE_NAME}"
    event.data = gate
    flow.flowchart.events.append(event)
    return event


def _copy_check_into(
    flow: EventFlow, check: EventFlow, exit_to: Event | None, prefix: str = _INLINE_PREFIX
) -> Event:
    """Copy DoorOfTime_CheckStoneNum from `check` into `flow` and return the entry of the copy.

    The check runs inside the calling flow, so it no longer depends on a cross-file sub-flow. Its
    exits continue to `exit_to`, or end the branch when `exit_to` is None. The returned entry is a
    step gate in front of the copied check.
    """
    entry = next(ep for ep in check.flowchart.entry_points if ep.name == _STONE_CHECK_ENTRY)
    old_events: list[Event] = []
    seen: set[int] = set()
    stack = [entry.main_event.v]
    while stack:
        event = stack.pop()
        if event is None or id(event) in seen:
            continue
        seen.add(id(event))
        old_events.append(event)
        body = event.data
        if isinstance(body, ActionEvent):
            stack.append(body.nxt.v)
        elif isinstance(body, SwitchEvent):
            stack.extend(case.v for case in body.cases.values())
        else:
            raise ValueError(f"unexpected {type(body).__name__} in {_STONE_CHECK_ENTRY}")

    copies: dict[int, Event] = {}
    for old in old_events:
        new = Event()
        new.name = f"{prefix}{old.name}"
        copies[id(old)] = new

    def target(event: Event | None) -> Event | None:
        return exit_to if event is None else copies[id(event)]

    for old in old_events:
        body = old.data
        actor = _flow_actor(flow, body.actor.v)
        if isinstance(body, ActionEvent):
            node = ActionEvent()
            node.actor = make_rindex(actor)
            node.actor_action = make_rindex(_holder(actor.actions, body.actor_action.v.v))
            node.params = deepcopy(body.params)
            node.nxt = make_index(target(body.nxt.v))
        else:
            node = SwitchEvent()
            node.actor = make_rindex(actor)
            node.actor_query = make_rindex(_holder(actor.queries, body.actor_query.v.v))
            node.params = deepcopy(body.params)
            node.cases = {case: make_rindex(copies[id(c.v)]) for case, c in body.cases.items()}
        copies[id(old)].data = node
        flow.flowchart.events.append(copies[id(old)])
    return _step_gate(flow, check, copies[id(entry.main_event.v)], exit_to, prefix)


def add_stone_count_check(data: bytes, check_data: bytes, grant_subflow: str = _STONE_GRANT_SUBFLOW) -> bytes:
    """Run DoorOfTime_CheckStoneNum right after a pouch grant.

    The Door of Time only recounts stones when Zora's Fountain is left, so this call runs after
    each grant instead. The check is copied in after the grant, so the item is already in the
    pouch. The check's own stone gates decide whether any progress happens. `check_data` is the
    DoorOfTime flow to copy from. Returns the input unchanged when the check is already present.
    Raises ValueError unless the flow has exactly one grant.
    """
    flow = _read_flow(data)
    if _has_inline_check(flow):
        return data
    grant = _single_grant(flow, grant_subflow)
    entry = _copy_check_into(flow, _read_flow(check_data), grant.data.nxt.v)
    grant.data.nxt = make_index(entry)
    return _write_flow(flow)


def _open_case(body: SwitchEvent) -> int | None:
    """Return the case that is still open on a route switch, or None when both cases are set.

    A bool switch with only case 0 is open at case 1. A held-medal switch with only case 1 is open at case 0.
    """
    keys = set(body.cases)
    if keys == {0}:
        return 1
    if keys == {1} and body.params is not None:
        if str(body.params.data.get("GameDataName", "")).startswith(HELD_MEDAL_BOOL_PREFIX):
            return 0
    return None


def add_stone_count_check_at_route_end(
    data: bytes, check_data: bytes, grant_subflow: str = POUCH_ADD_SUBFLOW
) -> bytes:
    """Run DoorOfTime_CheckStoneNum after the grant's get-item route has finished.

    Calling the check straight after the grant cuts into the get-item presentation that follows it.
    This instead walks the events after the grant and points each exit of that route at the copied
    check, so the check runs last. `check_data` is the DoorOfTime flow to copy from. Returns the
    input unchanged when the check is already present. Raises ValueError unless the flow has
    exactly one grant and the route after it is simple.

    A switch whose only case is 0 is a bool query, so its missing case 1 is the false exit and
    also ends the route. A held-medal switch whose only case is 1 gets its missing case 0 the same way.
    """
    flow = _read_flow(data)
    if _has_inline_check(flow):
        return data
    grant = _single_grant(flow, grant_subflow)
    check = _copy_check_into(flow, _read_flow(check_data), None)

    exits = 0
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
                body.nxt = make_index(check)
                exits += 1
            else:
                stack.append(body.nxt.v)
        elif isinstance(body, SwitchEvent):
            stack.extend(target.v for target in body.cases.values())
            missing = _open_case(body)
            if missing is not None:
                false_exit = RequiredIndex()
                false_exit.v = check
                body.cases[missing] = false_exit
                exits += 1
        else:
            raise ValueError(f"unexpected {type(body).__name__} after {grant_subflow}")
    if exits == 0:
        raise ValueError(f"no route exit after {grant_subflow}")
    return _write_flow(flow)


_CHALLENGE_PROGRESS_ACTION = "EventExecuteProgressChallengeStep"
_DOOR_OF_TIME_CHALLENGE = "DoorOfTime"
_DOOR_OF_TIME_START_STEP = "Step02"


def add_stone_count_check_after_step01(data: bytes, check_data: bytes) -> bytes:
    """Run DoorOfTime_CheckStoneNum right after the Door of Time quest starts (Step02). This can't follow Step01 or we

    A player who already holds the stones when the quest starts gets the same progress the check
    gives on a later pickup, so the quest does not wait for a stone that was already held. The
    check's own step gates still decide what it does. `check_data` is the DoorOfTime flow to copy
    from. Returns the input unchanged when the check is already present. Raises ValueError unless
    the flow has exactly one Door of Time Step01 progress node with a successor.
    """
    flow = _read_flow(data)
    if _has_inline_check(flow):
        return data
    hits = [
        e
        for e in flow.flowchart.events
        if isinstance(e.data, ActionEvent)
        and e.data.actor_action.v is not None
        and e.data.actor_action.v.v == _CHALLENGE_PROGRESS_ACTION
        and e.data.params is not None
        and e.data.params.data.get("ChallengeName") == _DOOR_OF_TIME_CHALLENGE
        and e.data.params.data.get("StepName") == _DOOR_OF_TIME_START_STEP
    ]
    if len(hits) != 1 or hits[0].data.nxt.v is None:
        raise ValueError(
            f"Flow {DOOR_OF_TIME_START_FLOW_FILE} has {len(hits)} {_DOOR_OF_TIME_START_STEP} progress nodes, expected 1"
        )
    step = hits[0]
    entry = _copy_check_into(flow, _read_flow(check_data), step.data.nxt.v)
    step.data.nxt = make_index(entry)
    return _write_flow(flow)


_SHOP_PURCHASE_EXITS = (
    ("Event268", "Event281", "EventTriggerGetItemAtShop", "Event295"),
    ("Event171", "Event103", "EventTriggerGetBottleItemAtShop", "Event338"),
)


def add_shop_stone_count_check(data: bytes, check_data: bytes) -> bytes:
    """Recount after each shop purchase's item processing and before its autosave."""
    flow = _read_flow(data)
    prefixes = [f"{_INLINE_PREFIX}{grant}_" for grant, _, _, _ in _SHOP_PURCHASE_EXITS]
    present = [any(e.name.startswith(prefix) for e in flow.flowchart.events) for prefix in prefixes]
    if all(present):
        return data
    if any(present):
        raise ValueError("DisplayShop has an incomplete stone-count patch")

    events = {event.name: event for event in flow.flowchart.events}
    check = _read_flow(check_data)
    for (grant, marker_name, action, autosave_name), prefix in zip(_SHOP_PURCHASE_EXITS, prefixes):
        marker = events.get(marker_name)
        purchase = events.get(grant)
        autosave = events.get(autosave_name)
        if (
            marker is None or not isinstance(marker.data, ActionEvent)
            or marker.data.actor_action.v is None or marker.data.actor_action.v.v != action
            or marker.data.nxt.v is not autosave or autosave is None
            or not isinstance(autosave.data, ActionEvent)
            or autosave.data.actor_action.v is None
            or autosave.data.actor_action.v.v != "EventTriggerRequestAutoSave"
            or purchase is None or not isinstance(purchase.data, ActionEvent)
            or purchase.data.actor_action.v is None
            or purchase.data.actor_action.v.v != "EventTriggerShopItemPutInPouch"
        ):
            raise ValueError(f"DisplayShop purchase route {grant} has changed")
        entry = _copy_check_into(flow, check, autosave, prefix)
        marker.data.nxt = make_index(entry)
    return _write_flow(flow)


# Diagnostic bools for the Door of Time stone check. The first is written on entry, and the others
# are written before each progress branch. These names are not registered in GameDataList, so a
# write may stall the item-get flow. False leaves the flow untouched.
STONE_CHECK_DIAGNOSTICS = False
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


# Vanilla shows the Door of Time progress window (Event171) after a step advances. The check only
# advances on Step03 (Event37 -> Event77) and on Step2_1/Step2_2 (both -> Event5), so the window goes
# before those exits. The "both stones" path (Event6) doesn't advance and gets no window.
_PROGRESS_UI_ACTION = "EventTriggerShowChallengeProgressUI"
_PROGRESS_UI_TARGETS = ("Event77", "Event5")


def _add_stone_progress_ui(flow: EventFlow) -> bool:
    from .game_flags import insert_action_before

    events = {e.name: e for e in flow.flowchart.events}
    added = False
    for target in _PROGRESS_UI_TARGETS:
        if f"AutoEvent_{_PROGRESS_UI_ACTION}_before_{target}" in events:
            continue
        insert_action_before(
            flow.flowchart,
            events[target],
            "ChallengeSystemActor",
            _PROGRESS_UI_ACTION,
            {"ChallengeName": _STONE_CHECK_FLOW, "IsFirstStep": False},
        )
        added = True
    return added


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
    if STONE_CHECK_DIAGNOSTICS and flow_name == STONE_CHECK_FLOW_FILE:
        changed = _add_stone_check_diagnostics(flow) or changed
    if flow_name == STONE_CHECK_FLOW_FILE:
        changed = _add_stone_progress_ui(flow) or changed
    if not changed:
        return data
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()
