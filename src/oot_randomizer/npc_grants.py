"""NPC and minigame item grants (Stage A).

Bag and quiver upgrades, bombchu bundles and scales are handed over by NPCs and minigames.
A hand-over (`NpcCommon_HandOver_NpcToPlayer_NoDisplay`) names its item in `ReveiveItem`, and a
GetInEvent sub-flow names it in `ActorName`. Like event_items.py, Stage A repoints only those
parameters. Model, LOD and XLink references keep the vanilla actor.

Pouch queries (`PouchSystemActor.EventQueryIsExistInPouch`) and bool gates still name the vanilla
items, so the game's own progress checks are unchanged. docs\\npc_grants.md lists them for Stage B.
"""

from __future__ import annotations

import io
import random
from dataclasses import dataclass

_HAND_OVER_SUBFLOW = "NpcCommon_HandOver_NpcToPlayer_NoDisplay"
_HAND_OVER_KEY = "ReveiveItem"
_GET_IN_EVENT_SUBFLOWS = frozenset({
    "GetInEvent_NotTurn",
    "GetInEvent_NotTurn_PosCamera",
    "GetInEvent_NotLookatObjectTurnOff",
    "GetInEvent_NotTurn_NotNpc",
    "GetInEventItemSwordBiggoron",  # Dm_SY_GetInEvent/GetInEventItemSwordBiggoron (stored without the flow prefix)
})
_GET_IN_EVENT_KEY = "ActorName"


@dataclass(frozen=True)
class NpcSlot:
    flow: str  # flow file that grants the item
    item: str  # vanilla item actor that the grant node gives


# (flow file, vanilla item). A flow can grant several items, so locations are per (flow, item).
_NPC_GRANTS: tuple[tuple[str, str], ...] = (
    ("MiniGame_HitTarget.bfevfl.zs", "Item_BulletBag_Medium"),
    ("MiniGame_HitTarget.bfevfl.zs", "Item_BulletBag_Large"),
    ("MiniGame_HitTarget.bfevfl.zs", "Item_Quiver_Medium"),
    ("MiniGame_HitTarget.bfevfl.zs", "Item_Quiver_Large"),
    ("MiniGame_BombchuBowling.bfevfl.zs", "Item_BombBag_Medium"),
    ("MiniGame_BombchuBowling.bfevfl.zs", "Item_BombBag_Large"),
    ("MiniGame_BombchuBowling.bfevfl.zs", "Item_BombchuBundle_Medium"),
    ("MiniGame_Fishing.bfevfl.zs", "Item_Scale_Gold"),
    ("MiniGame_Diving.bfevfl.zs", "Item_Scale_Silver"),
    ("Minigame_HorsebackArchery.bfevfl.zs", "Item_Quiver_Medium"),
    ("Minigame_HorsebackArchery.bfevfl.zs", "Item_Quiver_Large"),
    ("LostWood_ScrubForestStageElder_SkullMaskFirst.bfevfl.zs", "Item_StickBag_Medium"),
    ("LostWood_ScrubForestStageElder_SkullMaskFirst.bfevfl.zs", "Item_StickBag_Large"),
    ("LostWood_ScrubForestStageElder_TrueMaskFirst.bfevfl.zs", "Item_NutBag_Medium"),
    ("LostWood_ScrubForestStageElder_TrueMaskFirst.bfevfl.zs", "Item_NutBag_Large"),
    ("Dm_LostWood_0040.bfevfl.zs", "Item_BulletBag_Medium"),
    ("Dm_LostWood_0040.bfevfl.zs", "Item_BulletBag_Large"),
    ("Npc_Goron_Biggoron_Adult.bfevfl.zs", "Item_Sword_Biggoron"),
)

# Friendly names usable in logic requirements (the logic uses the Medium/Large forms).
NPC_ITEM_DISPLAY_NAMES: dict[str, str] = {
    "Item_BulletBag_Medium": "Bullet Bag Medium",
    "Item_BulletBag_Large": "Bullet Bag Large",
    "Item_Quiver_Medium": "Quiver Medium",
    "Item_Quiver_Large": "Quiver Large",
    "Item_BombBag_Medium": "Bomb Bag Medium",
    "Item_BombBag_Large": "Bomb Bag Large",
    "Item_BombchuBundle_Medium": "Bombchu Bundle Medium",
    "Item_Scale_Gold": "Golden Scale",
    "Item_Scale_Silver": "Silver Scale",
    "Item_StickBag_Medium": "Stick Bag Medium",
    "Item_StickBag_Large": "Stick Bag Large",
    "Item_NutBag_Medium": "Nut Bag Medium",
    "Item_NutBag_Large": "Nut Bag Large",
    "Item_Sword_Biggoron": "Biggoron Sword",
}


def npc_location_name(flow_file: str, item: str) -> str:
    return f"{flow_file.removesuffix('.bfevfl.zs')}: {item} (npc item)"


NPC_SLOTS: dict[str, NpcSlot] = {
    npc_location_name(flow, item): NpcSlot(flow, item) for flow, item in _NPC_GRANTS
}
NPC_FLOWS: frozenset[str] = frozenset(flow for flow, _ in _NPC_GRANTS)


def shuffle_npc_items(seed: int | random.Random) -> dict[str, str]:
    """Plain permutation of NPC items over NPC locations; logic is enforced by the planner."""
    rng = seed if isinstance(seed, random.Random) else random.Random(seed ^ 0x4E504330)
    items = [slot.item for slot in NPC_SLOTS.values()]
    rng.shuffle(items)
    return dict(zip(NPC_SLOTS, items))


def _grant_params(flow) -> list[tuple[dict, str]]:
    """Return (params dict, key) for every hand-over or GetInEvent parameter that names an item."""
    from evfl.event import SubFlowEvent

    found: list[tuple[dict, str]] = []
    for event in flow.flowchart.events:
        body = event.data
        if not isinstance(body, SubFlowEvent) or not body.params:
            continue
        if body.entry_point_name == _HAND_OVER_SUBFLOW and _HAND_OVER_KEY in body.params.data:
            found.append((body.params.data, _HAND_OVER_KEY))
        elif body.entry_point_name in _GET_IN_EVENT_SUBFLOWS and _GET_IN_EVENT_KEY in body.params.data:
            found.append((body.params.data, _GET_IN_EVENT_KEY))
    return found


def patch_npc_grants(data: bytes, changes: dict[str, str]) -> bytes:
    """Repoint every grant in one flow from its old item to its new item, in a single pass.

    `changes` maps vanilla item -> new item. Matching happens on the original values, so a
    Medium and Large bag can swap. Returns the input unchanged when nothing changes or when the
    flow already grants the new items (an earlier patch). Raises ValueError when the flow grants
    neither the old nor the new item.
    """
    changes = {old: new for old, new in changes.items() if old != new}
    if not changes:
        return data
    from evfl import EventFlow

    flow = EventFlow()
    flow.read(data)
    params = _grant_params(flow)
    hits = [(p, k) for p, k in params if p[k] in changes]
    if not hits:
        if any(p[k] in changes.values() for p, k in params):
            return data
        raise ValueError(f"NPC flow grants neither {sorted(changes)} nor {sorted(changes.values())}")
    for p, k in hits:
        p[k] = changes[p[k]]
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def patch_npc_grant(data: bytes, old_item: str, new_item: str) -> bytes:
    """Repoint the grant of `old_item` to `new_item` in one NPC flow."""
    return patch_npc_grants(data, {old_item: new_item})


SCRUB_BIGGORON_FLOW = "Enemy_Scrub_Business_Dream.bfevfl.zs"
_SCRUB_SALE_SWITCH = "Event42"  # SwitchEvent on GameDataString64 Weapon_Sword_Biggoron
_SCRUB_SALE_FROM = "Event46"  # 1000-rupee Biggoron Sword sale, unreachable after the reroute
_SCRUB_SALE_TO = "Event47"  # the branch the owned case already takes


def disable_scrub_biggoron_sale(data: bytes) -> bytes:
    """Remove the Business Scrub's 1000-rupee Biggoron Sword sale.

    The switch's not-owned case is repointed past the sale, so the sale event is no longer
    reachable. The Biggoron Sword then comes only from its randomized location. Raises ValueError
    if the flow does not have the expected shape. Returns the input unchanged when already patched.
    """
    from evfl import EventFlow

    flow = EventFlow()
    flow.read(data)
    by_name = {event.name: event for event in flow.flowchart.events}
    switch = by_name.get(_SCRUB_SALE_SWITCH)
    if switch is None or not hasattr(switch.data, "cases") or 0 not in switch.data.cases:
        raise ValueError(f"scrub flow has no {_SCRUB_SALE_SWITCH} switch with a not-owned case")
    not_owned = switch.data.cases[0]
    if not_owned.v is by_name[_SCRUB_SALE_TO]:
        return data
    if not_owned.v is not by_name[_SCRUB_SALE_FROM]:
        raise ValueError(f"scrub flow {_SCRUB_SALE_SWITCH} case 0 is not the Biggoron sale")
    not_owned.v = by_name[_SCRUB_SALE_TO]
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()
