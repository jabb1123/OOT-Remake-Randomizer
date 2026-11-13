"""Event item shuffle (phase 1).

Medallions, the Kokiri's Emerald and Goron's Ruby, and the two ocarinas are granted by event
flows. A grant looks the item up by actor name: the `GetPouchContentByActorName` and
`DisplayGetByActorName` sub-flows take `ActorName`, and the pouch add action
`PouchSystemActor.EventTriggerAddOrRemovePouchContent` takes `Actor`. Phase 1 repoints only
those parameters. Model, LOD and XLink references keep the vanilla actor, so cutscenes may
show the vanilla model.
"""

from __future__ import annotations

import io
import random

# flow file name -> vanilla event item granted by that flow
EVENT_SLOTS: dict[str, str] = {
    "Dm_Awake_Forest_Get.bfevfl.zs": "Item_Medal_Forest",
    "Dm_Awake_Fire_Get.bfevfl.zs": "Item_Medal_Fire",
    "Dm_Awake_Water_Get.bfevfl.zs": "Item_Medal_Water",
    "Dm_Awake_Shadow_Get.bfevfl.zs": "Item_Medal_Shadow",
    "Dm_Awake_Spirit_Get.bfevfl.zs": "Item_Medal_Spirit",
    "Dm_Kokiri_0130.bfevfl.zs": "Item_Stone_Forest",
    "Dm_DeathMtTrail_0025.bfevfl.zs": "Item_Stone_Fire",
    "Dm_ZoraFountain_0030.bfevfl.zs": "Item_Stone_Water",
    "Dm_Kokiri_0155.bfevfl.zs": "Item_Ocarina_Fairy",
    "Dm_MelodyGet_Time.bfevfl.zs": "Item_Ocarina_Time",
}

# Friendly names usable in logic requirements.
EVENT_ITEM_DISPLAY_NAMES: dict[str, str] = {
    "Item_Medal_Forest": "Forest Medallion",
    "Item_Medal_Fire": "Fire Medallion",
    "Item_Medal_Water": "Water Medallion",
    "Item_Medal_Shadow": "Shadow Medallion",
    "Item_Medal_Spirit": "Spirit Medallion",
    "Item_Stone_Forest": "Kokiris_Emerald",
    "Item_Stone_Fire": "Goron_Ruby",
    "Item_Stone_Water": "Zora_Sapphire",
    "Item_Ocarina_Fairy": "Fairy Ocarina",
    "Item_Ocarina_Time": "Ocarina of Time",
}

_GRANT_SUBFLOWS = frozenset({"GetPouchContentByActorName", "DisplayGetByActorName"})
_POUCH_ACTOR = "PouchSystemActor"
_POUCH_ADD_ACTION = "EventTriggerAddOrRemovePouchContent"


def event_location_name(flow_file: str) -> str:
    return f"{flow_file.removesuffix('.bfevfl.zs')} (event item)"


def shuffle_event_items(seed: int | random.Random) -> dict[str, str]:
    """Plain permutation of event items over event slots; logic is enforced by the planner."""
    rng = seed if isinstance(seed, random.Random) else random.Random(seed ^ 0x45564E54)
    items = list(EVENT_SLOTS.values())
    rng.shuffle(items)
    return dict(zip(EVENT_SLOTS, items))


def _grant_params(flow) -> list[tuple[dict, str]]:
    """Return (params dict, key) for every grant or display parameter that names an item."""
    from evfl.event import ActionEvent, SubFlowEvent

    found: list[tuple[dict, str]] = []
    for event in flow.flowchart.events:
        body = event.data
        if isinstance(body, SubFlowEvent) and body.entry_point_name in _GRANT_SUBFLOWS:
            if body.params and "ActorName" in body.params.data:
                found.append((body.params.data, "ActorName"))
        elif isinstance(body, ActionEvent) and _is_pouch_add(body):
            if body.params and "Actor" in body.params.data:
                found.append((body.params.data, "Actor"))
    return found


def _is_pouch_add(body) -> bool:
    actor = body.actor.v
    action = body.actor_action.v
    return (
        actor is not None
        and action is not None
        and actor.identifier.name == _POUCH_ACTOR
        and action.v == _POUCH_ADD_ACTION
    )


def patch_event_item(data: bytes, old_item: str, new_item: str) -> bytes:
    """Repoint the grant and display parameters that name `old_item` to `new_item`.

    Returns the input unchanged when old_item == new_item, or when the flow already grants
    new_item (an earlier patch). Raises ValueError when neither item is granted by the flow.
    """
    if old_item == new_item:
        return data
    from evfl import EventFlow

    flow = EventFlow()
    flow.read(data)
    params = _grant_params(flow)
    hits = [(p, k) for p, k in params if p[k] == old_item]
    if not hits:
        if any(p[k] == new_item for p, k in params):
            return data
        raise ValueError(f"event flow grants neither {old_item!r} nor {new_item!r}")
    for p, k in hits:
        p[k] = new_item
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()
