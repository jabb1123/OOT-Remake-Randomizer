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

from .game_flags import insert_bool_write_before
from .gamedata_list import DIN_FAIRY_RECEIVED_BOOL

_HAND_OVER_SUBFLOW = "NpcCommon_HandOver_NpcToPlayer_NoDisplay"
_HAND_OVER_KEY = "ReveiveItem"
_GET_IN_EVENT_SUBFLOWS = frozenset(
    {
        "GetInEvent_Goron",
        "GetInEvent_GreatFairyCourge",
        "GetInEvent_GreatFairyDin",
        "GetInEvent_Demo_NotLookatObjectEntry",
        "GetInEvent_GreatFairyWisdom",
        "GetInEvent_Zeldaletter",
        "GetInEvent_NotTurn",
        "GetInEvent_NotTurn_PosCamera",
        "GetInEvent_NotLookatObjectTurnOff",
        "GetInEvent_NotTurn_NotNpc",
        "GetInEventItemSwordBiggoron",  # Dm_SY_GetInEvent/GetInEventItemSwordBiggoron (stored without the flow prefix)
        "SimpleShopSub_Scrub_Business_OneTime",  # Enemy_Scrub_Business_Common bag sales (ActorName is the bag)
        "MushiToriGame",  # MiniGame_FrogTenors insect-repellent game (ActorName is the award)
        "GetInEvent",  # Npc_Hylia_001_Adult heart grant; matches only a changed ActorName
    }
)
_GET_IN_EVENT_KEY = "ActorName"


@dataclass(frozen=True)
class NpcSlot:
    flow: str  # flow file that grants the item
    item: str  # vanilla item actor that the grant node gives
    group: str | None = None  # sub-flow entry that makes the grant; None matches any grant of `item`
    label: str | None = None  # tells apart two slots for the same (flow, item)


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
    ("MiniGame_Fishing.bfevfl.zs", "Obj_Heart_Piece"),
    ("MiniGame_Diving.bfevfl.zs", "Item_Scale_Silver"),
    ("Minigame_HorsebackArchery.bfevfl.zs", "Item_Quiver_Large"),
    ("LostWood_ScrubForestStageElder_SkullMaskFirst.bfevfl.zs", "Item_StickBag_Medium"),
    ("LostWood_ScrubForestStageElder_TrueMaskFirst.bfevfl.zs", "Item_NutBag_Medium"),
    ("Enemy_Scrub_Business_Common.bfevfl.zs", "Item_StickBag_Large"),
    ("Enemy_Scrub_Business_Common.bfevfl.zs", "Item_NutBag_Large"),
    ("Dm_LostWood_0040.bfevfl.zs", "Item_BulletBag_Medium"),
    ("Npc_Goron_Biggoron_Adult.bfevfl.zs", "Item_Sword_Biggoron"),
    ("SubEvent_FindRichard.bfevfl.zs", "Obj_Heart_Piece"),
    ("Npc_SkullKid_Child_02.bfevfl.zs", "Obj_Heart_Piece"),
    ("Dm_Goron_0030.bfevfl.zs", "Item_Gauntlet_Goron"),
    ("Goto_HyruleCastle.bfevfl.zs", "Item_WeirdEgg"),
    ("Dm_HrlCastle_0050.bfevfl.zs", "Item_ZeldaLetter"),
    ("Npc_Hylia_001_Adult.bfevfl.zs", "Obj_Heart_Piece"),
    ("Dm_FairyFountain_Din.bfevfl.zs", "Item_DinFire"),
    ("Dm_FairyFountain_Frore.bfevfl.zs", "Item_FaroreWind"),
    ("Dm_FairyFountain_Nayru.bfevfl.zs", "Item_NayruLove"),
    ("Dm_FairyFountain_Power.bfevfl.zs", "Item_FairyBless_MP"),
    ("Dm_FairyFountain_Wisdom.bfevfl.zs", "Item_FairyBless_MPDouble"),
    ("Dm_FairyFountain_Courage.bfevfl.zs", "Item_FairyBless_DefenseDouble"),
)

# Two grants of the same item in one flow, told apart by the sub-flow that makes them. The Song of
# Storms heart is Event384 (GetInEvent_NotTurn_NotNpc); the insect-repellent heart is in the
# MushiToriGame sub-flows (Event161 and Event75). Their Rupee branches are not grants and stay vanilla.
_NPC_GRANT_GROUPS: tuple[NpcSlot, ...] = (
    NpcSlot("MiniGame_FrogTenors.bfevfl.zs", "Obj_Heart_Piece", "GetInEvent_NotTurn_NotNpc", "song of storms"),
    NpcSlot("MiniGame_FrogTenors.bfevfl.zs", "Obj_Heart_Piece", "MushiToriGame", "insect repellent"),
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
    "Item_FaroreWind": "Farore's Wind",
    "Item_NayruLove": "Nayru's Love",
    "Item_FairyBless_MP": "Spin Attack Upgrade",
    "Item_FairyBless_MPDouble": "Magic Meter Upgrade",
    "Item_FairyBless_DefenseDouble": "Half Damage",
    "Item_WeirdEgg": "Alarm_Cucco",
    "Item_ZeldaLetter": "Zeldas_Letter",
    "Obj_Heart_Piece": "Heart Piece",
}


def npc_location_name(flow_file: str, item: str, label: str | None = None) -> str:
    tag = f" ({label})" if label else ""
    return f"{flow_file.removesuffix('.bfevfl.zs')}: {item}{tag} (npc item)"


_PLAIN_NPC_SLOTS = tuple(NpcSlot(flow, item) for flow, item in _NPC_GRANTS)
NPC_SLOTS: dict[str, NpcSlot] = {
    npc_location_name(slot.flow, slot.item, slot.label): slot
    for slot in (*_PLAIN_NPC_SLOTS, *_NPC_GRANT_GROUPS)
}
NPC_FLOWS: frozenset[str] = frozenset(slot.flow for slot in NPC_SLOTS.values())


def shuffle_npc_items(seed: int | random.Random) -> dict[str, str]:
    """Plain permutation of NPC items over NPC locations; logic is enforced by the planner."""
    rng = seed if isinstance(seed, random.Random) else random.Random(seed ^ 0x4E504330)
    items = [slot.item for slot in NPC_SLOTS.values()]
    rng.shuffle(items)
    return dict(zip(NPC_SLOTS, items))


def _grant_params(flow) -> list[tuple[dict, str, str]]:
    """Return (params dict, key, sub-flow entry name) for every hand-over or GetInEvent parameter that names an item."""
    from evfl.event import SubFlowEvent

    found: list[tuple[dict, str, str]] = []
    for event in flow.flowchart.events:
        body = event.data
        if not isinstance(body, SubFlowEvent) or not body.params:
            continue
        if body.entry_point_name == _HAND_OVER_SUBFLOW and _HAND_OVER_KEY in body.params.data:
            found.append((body.params.data, _HAND_OVER_KEY, body.entry_point_name))
        elif body.entry_point_name in _GET_IN_EVENT_SUBFLOWS and _GET_IN_EVENT_KEY in body.params.data:
            found.append((body.params.data, _GET_IN_EVENT_KEY, body.entry_point_name))
    return found


def patch_npc_grants(data: bytes, changes: dict[tuple[str | None, str] | str, str]) -> bytes:
    """Repoint every grant in one flow from its old item to its new item, in a single pass.

    `changes` maps (sub-flow entry, vanilla item) -> new item. A plain item string is the same as
    (None, item), which matches any grant of that item; a named entry matches only the grant made
    by that sub-flow. Matching happens on the original values, so a Medium and Large bag can swap.
    Returns the input unchanged when nothing changes or when the flow already grants the new items
    (an earlier patch). Raises ValueError when the flow grants neither the old nor the new item.
    """
    changes = {
        (key if isinstance(key, tuple) else (None, key)): new
        for key, new in changes.items()
    }
    changes = {key: new for key, new in changes.items() if key[1] != new}
    if not changes:
        return data
    from evfl import EventFlow

    flow = EventFlow()
    flow.read(data)
    params = _grant_params(flow)
    hits = []
    for p, k, group in params:
        new = changes.get((group, p[k]), changes.get((None, p[k])))
        if new is not None:
            hits.append((p, k, new))
    if not hits:
        new_items = set(changes.values())
        if any(p[k] in new_items for p, k, _ in params):
            return data
        olds = sorted({item for _, item in changes})
        raise ValueError(
            f"NPC flow {flow.name} grants neither {olds} nor {sorted(new_items)}"
        )
    for p, k, new in hits:
        p[k] = new
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def patch_npc_grant(data: bytes, old_item: str, new_item: str) -> bytes:
    """Repoint the grant of `old_item` to `new_item` in one NPC flow."""
    return patch_npc_grants(data, {(None, old_item): new_item})


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
    "MiniGame_BombchuBowling.bfevfl.zs": (
        ProgressiveBranch("Event76", "Event306", "Item_BombBag_Large"),
    ),
    "MiniGame_HitTarget.bfevfl.zs": (
        # ProgressiveBranch("original check for the progressive item (win the game)",
        #                   "event that gives the vanilla item (item is given)",
        #                   "vanilla item we're going to overwrite"),
        ProgressiveBranch("Event70", "Event378", "Item_BulletBag_Large"),
        ProgressiveBranch("Event181", "Event381", "Item_Quiver_Medium"),
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


DIN_FAIRY_FLOW = "Dm_FairyFountain_Din.bfevfl.zs"
_DIN_RECEIVED_SWITCH = "Event78"  # SwitchEvent: owned Din's Fire -> skip the 25-rupee offer
_DIN_OLD_FLAG = "IsGet.Item_DinFire"
_DIN_GRANT = "Event212"  # SubFlowEvent GetInEvent_GreatFairyDin, which gives the randomized item


def patch_din_fairy_received(data: bytes) -> bytes:
    """Make the Din's Fire fairy's "already received" check follow the randomized grant.

    The fairy's switch reads IsGet.Item_DinFire, which only reflects the vanilla item. This repoints
    the switch at DIN_FAIRY_RECEIVED_BOOL and sets that bool right before the grant. Returns the
    input unchanged when already patched. Raises ValueError if the flow does not have the expected shape.
    """
    from evfl import EventFlow
    from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent

    flow = EventFlow()
    flow.read(data)
    by_name = {event.name: event for event in flow.flowchart.events}
    switch, grant = by_name.get(_DIN_RECEIVED_SWITCH), by_name.get(_DIN_GRANT)
    if switch is None or not isinstance(switch.data, SwitchEvent) or not switch.data.params:
        raise ValueError(f"Din flow has no {_DIN_RECEIVED_SWITCH} switch")
    if grant is None or not isinstance(grant.data, SubFlowEvent) or grant.data.entry_point_name not in _GET_IN_EVENT_SUBFLOWS:
        raise ValueError(f"Din flow has no {_DIN_GRANT} item grant")
    params = switch.data.params.data
    writers = [
        e for e in flow.flowchart.events
        if isinstance(e.data, ActionEvent)
        and e.data.params is not None
        and e.data.params.data.get("GameDataName") == DIN_FAIRY_RECEIVED_BOOL
        and e.data.nxt is not None
        and e.data.nxt.v is grant
    ]
    if params.get("GameDataName") == DIN_FAIRY_RECEIVED_BOOL:
        if len(writers) == 1:
            return data
        raise ValueError(f"Din flow is partly patched: {len(writers)} writers before {_DIN_GRANT}")
    if params.get("GameDataName") != _DIN_OLD_FLAG:
        raise ValueError(f"Din flow {_DIN_RECEIVED_SWITCH} is not {_DIN_OLD_FLAG}")

    params["GameDataName"] = DIN_FAIRY_RECEIVED_BOOL
    insert_bool_write_before(flow.flowchart, grant, DIN_FAIRY_RECEIVED_BOOL, True)
    # Din's Fire counts as owned once the fairy hands over its item. Setting the vanilla flag too makes
    # every check that reads IsGet.Item_DinFire (the owl, Death Mountain, scrub, Goron) follow the grant.
    received = next(
        e
        for e in flow.flowchart.events
        if e.name == f"AutoEvent_Set_{DIN_FAIRY_RECEIVED_BOOL}"
    )
    insert_bool_write_before(flow.flowchart, received, _DIN_OLD_FLAG, True)
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
