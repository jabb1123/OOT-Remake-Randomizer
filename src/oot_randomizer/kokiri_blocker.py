"""Clear Mido's blocker flag when Saria leaves Kokiri Forest for the Sacred Grove.

Mido's blocker flag only clears in the Mido talk path (Npc_Kokiri_Mido_Child). When the player
leaves through Goron City and returns through the Lost Woods, that talk never happens, so Mido
drops his pose while the blocker flag stays set and the Deku Tree stays unreachable. Saria's warp
in Dm_Kokiri_0145 is the point where the story has moved past Mido, so the flag is cleared there.
"""

from __future__ import annotations

import io

MIDO_BLOCKER_FLOW = "Dm_Kokiri_0145.bfevfl.zs"
MIDO_BLOCKER_FLAG = "KokiriForest_Npc_Kokiri_Mido_Child_Blocker"

_SARIA_ACTOR = "Npc_Kokiri_Saria_Child"
_SARIA_WARP_ACTION = "EventWarpToTargetPosAndRot"
_GAME_DATA_ACTOR = "GameDataActor"
_SET_FLAG_ACTION = "EventTriggerSetGameDataBool"
_GAME_DATA_QUERIES = (
    "EventQueryIsGameDataBoolExp",
    "EventQueryIsGameDataBool",
    "EventQueryCheckIsGet",
)
_GAME_DATA_ACTOR_PARAMS = {
    "EventMemberCreateMethod": 0,
    "IsBindNearestActor": False,
    "IsGrounding": False,
    "IsWorld": False,
    "UseEventModelAnime": "使用しない",
    "UseEventAS": "使用しない",
}


def _redirect_references(flowchart, old, new) -> None:
    """Point every edge that targets `old` at `new` instead."""
    from evfl.event import ActionEvent, ForkEvent, JoinEvent, SubFlowEvent, SubFlowSwitchEvent, SwitchEvent

    for entry in flowchart.entry_points:
        if entry.main_event.v is old:
            entry.main_event.v = new
    for event in flowchart.events:
        data = event.data
        if isinstance(data, (ActionEvent, JoinEvent, SubFlowEvent)):
            if data.nxt.v is old:
                data.nxt.v = new
        elif isinstance(data, (SwitchEvent, SubFlowSwitchEvent)):
            for case in data.cases.values():
                if case.v is old:
                    case.v = new
        elif isinstance(data, ForkEvent):
            for fork in data.forks:
                if fork.v is old:
                    fork.v = new
            if data.join.v is old:
                data.join.v = new


def _game_data_actor(flowchart):
    """Return the flow's GameDataActor, adding one with the standard config if the flow lacks it."""
    from evfl.actor import Actor
    from evfl.common import ActorIdentifier, StringHolder
    from evfl.container import Container

    for actor in flowchart.actors:
        if actor.identifier.name == _GAME_DATA_ACTOR:
            return actor
    actor = Actor()
    actor.identifier = ActorIdentifier(_GAME_DATA_ACTOR)
    actor.params = Container()
    actor.params.data.update(_GAME_DATA_ACTOR_PARAMS)
    actor.actions = [StringHolder(_SET_FLAG_ACTION)]
    actor.queries = [StringHolder(q) for q in _GAME_DATA_QUERIES]
    flowchart.actors.append(actor)
    return actor


def set_flag_before_action(data: bytes, target_actor: str, target_action: str,
                           flag: str, value: bool) -> bytes:
    """Insert a GameDataActor flag write just before the single matching action in the flow.

    Every edge into the target action is rerouted through the new node, so the write runs on
    every path that reaches the target. Raises ValueError unless exactly one action matches.
    """
    from evfl import EventFlow
    from evfl.container import Container
    from evfl.event import ActionEvent, Event
    from evfl.util import make_index, make_rindex

    flow = EventFlow()
    flow.read(data)
    chart = flow.flowchart

    matches = [
        e for e in chart.events
        if isinstance(e.data, ActionEvent)
        and e.data.actor.v.identifier.name == target_actor
        and e.data.actor_action.v.v == target_action
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one {target_actor}.{target_action} action, found {len(matches)}")
    target = matches[0]

    actor = _game_data_actor(chart)
    node = ActionEvent()
    node.actor = make_rindex(actor)
    node.actor_action = make_rindex(actor.find_action(_SET_FLAG_ACTION))
    node.params = Container()
    node.params.data.update({"Index": -1, "GameDataName": flag, "Value": value})
    node.nxt = make_index(target)

    new_event = Event()
    new_event.name = f"AutoEvent_Set_{flag}"
    new_event.data = node

    _redirect_references(chart, target, new_event)
    chart.events.append(new_event)

    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def clear_mido_blocker(data: bytes) -> bytes:
    """Clear the Mido blocker flag right before Saria's warp to the Sacred Grove in Dm_Kokiri_0145."""
    return set_flag_before_action(data, _SARIA_ACTOR, _SARIA_WARP_ACTION, MIDO_BLOCKER_FLAG, False)
