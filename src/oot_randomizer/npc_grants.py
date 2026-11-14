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
_GET_IN_EVENT_SUBFLOWS = frozenset(
    {
        "GetInEvent_Goron",
        "GetInEvent_GreatFairyDin",
        "GetInEvent_Zeldaletter",
        "GetInEvent_NotTurn",
        "GetInEvent_NotTurn_PosCamera",
        "GetInEvent_NotLookatObjectTurnOff",
        "GetInEvent_NotTurn_NotNpc",
        "GetInEventItemSwordBiggoron",  # Dm_SY_GetInEvent/GetInEventItemSwordBiggoron (stored without the flow prefix)
        "SimpleShopSub_Scrub_Business_OneTime",  # Enemy_Scrub_Business_Common bag sales (ActorName is the bag)
    }
)
_GET_IN_EVENT_KEY = "ActorName"


@dataclass(frozen=True)
class NpcSlot:
    flow: str  # flow file that grants the item
    item: str  # vanilla item actor that the grant node gives


# (flow file, vanilla item). A flow can grant several items, so locations are per (flow, item).
# The Lost Woods scrub target and the Market shooting gallery are one-time, progressive bullet
# bag grants (Medium if the Medium bag is not owned yet, else Large). Only one branch of each is
# kept (see PROGRESSIVE_BRANCHES): Lost Woods is the 1st upgrade, the Market gallery the 2nd.
_NPC_GRANTS: tuple[tuple[str, str], ...] = (
    ("MiniGame_HitTarget.bfevfl.zs", "Item_BulletBag_Large"),
    ("MiniGame_HitTarget.bfevfl.zs", "Item_Quiver_Medium"),
    ("MiniGame_BombchuBowling.bfevfl.zs", "Item_BombBag_Medium"),
    ("MiniGame_BombchuBowling.bfevfl.zs", "Item_BombBag_Large"),
    ("MiniGame_BombchuBowling.bfevfl.zs", "Item_BombchuBundle_Medium"),
    ("MiniGame_Fishing.bfevfl.zs", "Item_Scale_Gold"),
    ("MiniGame_Diving.bfevfl.zs", "Item_Scale_Silver"),
    ("Minigame_HorsebackArchery.bfevfl.zs", "Item_Quiver_Large"),
    ("LostWood_ScrubForestStageElder_SkullMaskFirst.bfevfl.zs", "Item_StickBag_Medium"),
    ("LostWood_ScrubForestStageElder_SkullMaskFirst.bfevfl.zs", "Item_StickBag_Large"),
    ("LostWood_ScrubForestStageElder_TrueMaskFirst.bfevfl.zs", "Item_NutBag_Medium"),
    ("LostWood_ScrubForestStageElder_TrueMaskFirst.bfevfl.zs", "Item_NutBag_Large"),
    ("Enemy_Scrub_Business_Common.bfevfl.zs", "Item_StickBag_Large"),
    ("Enemy_Scrub_Business_Common.bfevfl.zs", "Item_NutBag_Large"),
    ("Dm_LostWood_0040.bfevfl.zs", "Item_BulletBag_Medium"),
    ("Npc_Goron_Biggoron_Adult.bfevfl.zs", "Item_Sword_Biggoron"),
    ("SubEvent_FindRichard.bfevfl.zs", "Obj_Heart_Piece"),
    ("Npc_SkullKid_Child_02.bfevfl.zs", "Obj_Heart_Piece"),
    ("Dm_Goron_0030.bfevfl.zs", "Item_Gauntlet_Goron"),
    ("Dm_FairyFountain_Din.bfevfl.zs", "Item_DinFire"),
    ("Goto_HyruleCastle.bfevfl.zs", "Item_WeirdEgg"),
    ("Dm_HrlCastle_0050.bfevfl.zs", "Item_ZeldaLetter"),
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
    "Item_Gauntlet_Goron": "Goron_Bracelet",
    "Item_DinFire": "Dins Fire",
    "Item_WeirdEgg": "Alarm_Cucco",
    "Item_ZeldaLetter": "Zeldas_Letter",
    "Obj_Heart_Piece": "Heart Piece",
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


@dataclass(frozen=True)
class ProgressiveBranch:
    switch: str  # SwitchEvent that picks the Medium or Large grant
    keep: str  # grant event every case is pointed at
    keep_item: str  # vanilla item of `keep` (that location's slot)


# Each switch asks "is the Medium bag already owned?"; every case is pointed at `keep`, so the
# grant no longer depends on where the randomized Medium bag was found.
PROGRESSIVE_BRANCHES: dict[str, tuple[ProgressiveBranch, ...]] = {
    "Dm_LostWood_0040.bfevfl.zs": (
        ProgressiveBranch("Event83", "Event30", "Item_BulletBag_Medium"),
    ),
    "MiniGame_HitTarget.bfevfl.zs": (
        ProgressiveBranch("Event70", "Event378", "Item_BulletBag_Large"),
    ),
    "LostWood_ScrubForestStageElder_SkullMaskFirst.bfevfl.zs": (
        ProgressiveBranch("Event30", "Event29", "Item_StickBag_Medium"),
    ),
    "LostWood_ScrubForestStageElder_TrueMaskFirst.bfevfl.zs": (
        ProgressiveBranch("Event30", "Event2", "Item_NutBag_Medium"),
    ),
    # Business Scrub bag sales: the Medium sales are removed, so each switch pins the Large bag.
    "Enemy_Scrub_Business_Common.bfevfl.zs": (
        ProgressiveBranch("Event319", "Event317", "Item_StickBag_Large"),
        ProgressiveBranch("Event323", "Event318", "Item_NutBag_Large"),
    ),
}

# (flow file) -> (source event, case key, old target, new target). Re-points one switch case, for
# gates that lead into a removed grant rather than into a progressive switch.
CASE_REROUTES: dict[str, tuple[tuple[str, int, str, str], ...]] = {
    # IsGet.Item_DekuStick true used to skip the pouch check and sell the Medium stick bag.
    "Enemy_Scrub_Business_Common.bfevfl.zs": (
        ("Event554", 1, "Event555", "Event319"),
    ),
}

# (flow file) -> (source event, old next event or None, new next event). Re-points the `nxt` of an
# event, so the flow skips a pouch switch and continues into the next step.
NEXT_REROUTES: dict[str, tuple[tuple[str, str | None, str], ...]] = {
    # The horseback quiver is always the Large grant (Event319), then the heart piece talk runs
    # (Event349). Event99 is the Medium/Large pouch switch and becomes unreachable.
    "Minigame_HorsebackArchery.bfevfl.zs": (
        ("Event121", "Event99", "Event319"),
        ("Event133", "Event99", "Event319"),
        ("Event319", None, "Event349"),
    ),
}

# Every flow that fix_progressive_branches patches.
REROUTED_FLOWS: tuple[str, ...] = tuple(
    dict.fromkeys((*PROGRESSIVE_BRANCHES, *CASE_REROUTES, *NEXT_REROUTES))
)


def fix_progressive_branches(data: bytes, flow_file: str) -> bytes:
    """Point every case of the flow's progressive bag switches at the kept grant.

    Returns the input unchanged when already patched. Raises ValueError if the switch or the
    kept grant event is missing or is not the expected kind.
    """
    from evfl import EventFlow
    from evfl.event import SubFlowEvent, SwitchEvent
    from evfl.util import make_index

    flow = EventFlow()
    flow.read(data)
    by_name = {event.name: event for event in flow.flowchart.events}
    changed = False
    for branch in PROGRESSIVE_BRANCHES.get(flow_file, ()):
        switch, keep = by_name.get(branch.switch), by_name.get(branch.keep)
        if (
            switch is None
            or not isinstance(switch.data, SwitchEvent)
            or not switch.data.cases
        ):
            raise ValueError(f"{flow_file}: {branch.switch} is not a switch")
        grant_subflows = _GET_IN_EVENT_SUBFLOWS | {_HAND_OVER_SUBFLOW}
        if (
            keep is None
            or not isinstance(keep.data, SubFlowEvent)
            or keep.data.entry_point_name not in grant_subflows
        ):
            raise ValueError(f"{flow_file}: {branch.keep} is not an item grant")
        if not any(case.v is keep for case in switch.data.cases.values()):
            raise ValueError(
                f"{flow_file}: {branch.switch} does not lead to {branch.keep}"
            )
        for case in switch.data.cases.values():
            if case.v is not keep:
                case.v = keep
                changed = True
    for source, key, old_target, new_target in CASE_REROUTES.get(flow_file, ()):
        switch = by_name.get(source)
        if switch is None or not isinstance(switch.data, SwitchEvent) or key not in switch.data.cases:
            raise ValueError(f"{flow_file}: {source} has no case {key}")
        case = switch.data.cases[key]
        if case.v is by_name.get(new_target):
            continue
        if case.v is not by_name.get(old_target):
            raise ValueError(f"{flow_file}: {source} case {key} does not lead to {old_target}")
        case.v = by_name[new_target]
        changed = True
    for source, old_next, new_next in NEXT_REROUTES.get(flow_file, ()):
        event, target = by_name.get(source), by_name.get(new_next)
        if event is None or not hasattr(event.data, "nxt") or target is None:
            raise ValueError(f"{flow_file}: {source} has no next event or {new_next} is missing")
        current = event.data.nxt.v if event.data.nxt is not None else None
        if current is target:
            continue
        if current is not (by_name.get(old_next) if old_next else None):
            raise ValueError(f"{flow_file}: {source} does not lead to {old_next}")
        event.data.nxt = make_index(target)
        changed = True
    if not changed:
        return data
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


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
