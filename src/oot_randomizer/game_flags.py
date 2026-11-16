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


POUCH_ACTOR = "PouchSystemActor"
POUCH_ADD_ACTION = "EventTriggerAddOrRemovePouchContent"


def pouch_add_action(flowchart):
    """Return the flow's PouchSystemActor and its add action, adding either if the flow lacks it."""
    from evfl.actor import Actor
    from evfl.common import ActorIdentifier, StringHolder

    actor = next((a for a in flowchart.actors if a.identifier.name == POUCH_ACTOR), None)
    if actor is None:
        actor = Actor()
        actor.identifier = ActorIdentifier(POUCH_ACTOR)
        flowchart.actors.append(actor)
    action = next((a for a in actor.actions if a.v == POUCH_ADD_ACTION), None)
    if action is None:
        action = StringHolder(POUCH_ADD_ACTION)
        actor.actions.append(action)
    return actor, action


def insert_pouch_add_before(flowchart, target, item: str) -> None:
    """Silently add `item` to the pouch immediately before `target` on every path into it."""
    from evfl.container import Container
    from evfl.event import ActionEvent, Event
    from evfl.util import make_index, make_rindex

    actor, action = pouch_add_action(flowchart)
    params = Container()
    params.data.update({
        "Num": 1,
        "IsEquipDIrect": False,
        "IsSetMessageTargetActorName": False,
        "Actor": item,
        "IsGetEvent": False,
    })
    node = ActionEvent()
    node.actor = make_rindex(actor)
    node.actor_action = make_rindex(action)
    node.params = params
    node.nxt = make_index(target)

    new_event = Event()
    new_event.name = f"AutoEvent_Add_{item}_before_{target.name}"
    new_event.data = node
    redirect_references(flowchart, target, new_event)
    flowchart.events.append(new_event)


def insert_action_before(flowchart, target, actor_name: str, action_name: str, params: dict) -> None:
    """Run an existing actor action with `params` immediately before `target` on every path into it.

    The flow must already contain `actor_name` with `action_name`; the helper does not create them.
    """
    actor = next((a for a in flowchart.actors if a.identifier.name == actor_name), None)
    if actor is None:
        raise ValueError(f"flow has no {actor_name} actor")
    action = next((a for a in actor.actions if a.v == action_name), None)
    if action is None:
        raise ValueError(f"{actor_name} has no {action_name} action")
    _insert_action_node(flowchart, target, actor, action, params)


def insert_new_action_before(flowchart, target, actor_name: str, action_name: str, params: dict) -> None:
    """Like `insert_action_before`, but declares the actor action in the flow when it is missing."""
    from evfl.actor import Actor
    from evfl.common import ActorIdentifier, StringHolder

    actor = next((a for a in flowchart.actors if a.identifier.name == actor_name), None)
    if actor is None:
        actor = Actor()
        actor.identifier = ActorIdentifier(actor_name)
        flowchart.actors.append(actor)
    action = next((a for a in actor.actions if a.v == action_name), None)
    if action is None:
        action = StringHolder(action_name)
        actor.actions.append(action)
    _insert_action_node(flowchart, target, actor, action, params)


def _insert_action_node(flowchart, target, actor, action, params: dict) -> None:
    from evfl.container import Container
    from evfl.event import ActionEvent, Event
    from evfl.util import make_index, make_rindex

    node = ActionEvent()
    node.actor = make_rindex(actor)
    node.actor_action = make_rindex(action)
    node.params = Container()
    node.params.data.update(params)
    node.nxt = make_index(target)

    new_event = Event()
    new_event.name = f"AutoEvent_{action.v}_before_{target.name}"
    new_event.data = node
    redirect_references(flowchart, target, new_event)
    flowchart.events.append(new_event)


CHALLENGE_ACTOR = "ChallengeSystemActor"
CHALLENGE_PROGRESS_ACTION = "EventExecuteProgressChallengeStep"


def insert_challenge_progress_before(flowchart, target, challenge: str, step: str) -> None:
    """Progress `challenge` to `step` immediately before `target`, as a vanilla flow would.

    Adds the ChallengeSystemActor and its progress action to the flow when it lacks them.
    """
    from evfl.actor import Actor
    from evfl.common import ActorIdentifier, StringHolder

    actor = next((a for a in flowchart.actors if a.identifier.name == CHALLENGE_ACTOR), None)
    if actor is None:
        actor = Actor()
        actor.identifier = ActorIdentifier(CHALLENGE_ACTOR)
        flowchart.actors.append(actor)
    action = next((a for a in actor.actions if a.v == CHALLENGE_PROGRESS_ACTION), None)
    if action is None:
        action = StringHolder(CHALLENGE_PROGRESS_ACTION)
        actor.actions.append(action)
    _insert_action_node(flowchart, target, actor, action, {
        "ChallengeName": challenge,
        "StepName": step,
        "IsWaitEnd": True,
        "IsIgnoreChallengeProgressUI": False,
        "IsIgnoreCompletedChallenge": False,
    })
