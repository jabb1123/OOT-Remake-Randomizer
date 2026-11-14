"""Write save-backed game-data bools from inside an evfl flow.

A GameDataActor action (`EventTriggerSetGameDataBool`) is inserted as a node that runs just
before an existing event. Every edge that led to that event is rerouted through the new node.
"""

from __future__ import annotations

GAME_DATA_ACTOR = "GameDataActor"
SET_BOOL_ACTION = "EventTriggerSetGameDataBool"
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


def redirect_references(flowchart, old, new) -> None:
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


def game_data_actor(flowchart):
    """Return the flow's GameDataActor, adding one with the standard config if the flow lacks it."""
    from evfl.actor import Actor
    from evfl.common import ActorIdentifier, StringHolder
    from evfl.container import Container

    for actor in flowchart.actors:
        if actor.identifier.name == GAME_DATA_ACTOR:
            return actor
    actor = Actor()
    actor.identifier = ActorIdentifier(GAME_DATA_ACTOR)
    actor.params = Container()
    actor.params.data.update(_GAME_DATA_ACTOR_PARAMS)
    actor.actions = [StringHolder(SET_BOOL_ACTION)]
    actor.queries = [StringHolder(q) for q in _GAME_DATA_QUERIES]
    flowchart.actors.append(actor)
    return actor


def insert_bool_write_before(flowchart, target, flag: str, value: bool) -> None:
    """Run a GameDataActor bool write immediately before `target` on every path into it."""
    from evfl.container import Container
    from evfl.event import ActionEvent, Event
    from evfl.util import make_index, make_rindex

    actor = game_data_actor(flowchart)
    node = ActionEvent()
    node.actor = make_rindex(actor)
    node.actor_action = make_rindex(actor.find_action(SET_BOOL_ACTION))
    node.params = Container()
    node.params.data.update({"Index": -1, "GameDataName": flag, "Value": value})
    node.nxt = make_index(target)

    new_event = Event()
    new_event.name = f"AutoEvent_Set_{flag}"
    new_event.data = node

    redirect_references(flowchart, target, new_event)
    flowchart.events.append(new_event)
