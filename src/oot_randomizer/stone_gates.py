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
    "Get_StoneOfWater_IsCompleted_Exp": "Item_Stone_Water",
}

# Diagnostic switch. False leaves the original Get_StoneOf*_IsCompleted_Exp gates untouched in the
# flows, so the vanilla bool checks are back in effect. True converts them to pouch queries.
POUCH_STONE_GATES = False

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


def patch_stone_gates(data: bytes, flow_name: str) -> bytes:
    if not POUCH_STONE_GATES:
        return data
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
