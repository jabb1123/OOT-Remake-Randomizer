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
from evfl.event import SwitchEvent

STONE_BOOL_ITEMS: dict[str, str] = {
    "Get_StoneOfForest_IsCompleted_Exp": "Item_Stone_Forest",
    "Get_StoneOfFire_IsCompleted_Exp": "Item_Stone_Fire",
}

# flow file name -> stone bools whose gates in that flow are converted
STONE_GATE_FLOWS: dict[str, frozenset[str]] = {
    "DoorOfTime.bfevfl.zs": frozenset({"Get_StoneOfFire_IsCompleted_Exp"}),
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


def patch_stone_gates(data: bytes, flow_name: str) -> bytes:
    bools = STONE_GATE_FLOWS.get(flow_name)
    if not bools:
        return data
    flow = EventFlow()
    flow.read(data)
    switches = _stone_switches(flow, bools)
    if not switches:
        return data
    pouch = _pouch_actor(flow)
    for body in switches:
        stone_bool = body.params.data["GameDataName"]
        body.actor.v = pouch
        body.actor_query.v = _query(pouch, _POUCH_QUERY)
        body.params.data = {"Actor": STONE_BOOL_ITEMS[stone_bool], "Num": 1}
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()
