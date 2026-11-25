"""Progressive copies at NPC and event grant slots.

A grant slot that the item shuffle fills with a progressive copy gets the same chain a progressive
chest gets (progressive_chests.chain_events). The grant event itself becomes the first question: it
asks the pouch tier by tier and then runs a copy of the same sub-flow call with the lowest unowned
tier. The copies keep the sub-flow, its item parameter and its successor, so the talk and gates
before the grant stay as they are.

Out of scope (copies never land there): the great fairies, whose received bool and vanilla IsGet
flag name the grant's item (patch_fairy_received), the Biggoron Sword, and the shop, skull, heart
and song locations.
"""

from __future__ import annotations

import io

from evfl import EventFlow
from evfl.event import ActionEvent, Event, ForkEvent, SubFlowEvent, SwitchEvent
from evfl.util import make_index, make_rindex

from . import progressive
from .event_items import EVENT_SLOTS, _GRANT_SUBFLOWS, _is_pouch_add, event_location_name
from .npc_grants import (
    FAIRY_FLOWS,
    NPC_SLOTS,
    REROUTED_FLOWS,
    _add_slingshot_bag,
    _fix_progressive_branches,
    _grant_params,
)
from .progressive_chests import chain_events, owner_holder, params_of

_FAIRY_FLOWS: frozenset[str] = frozenset(f.flow for f in FAIRY_FLOWS)


class ProgressiveNpcError(ValueError):
    pass


def progressive_locations() -> frozenset[str]:
    """Location names that may take a progressive copy: the in-scope NPC and event grant slots."""
    npc = (
        loc for loc, slot in NPC_SLOTS.items()
        if progressive.family_of_tier(slot.item) is not None and slot.flow not in _FAIRY_FLOWS
    )
    event = (event_location_name(flow) for flow, item in EVENT_SLOTS.items() if progressive.family_of_tier(item))
    return frozenset([*npc, *event])


def _grant_events(flow: EventFlow) -> list[tuple[Event, dict, str, str]]:
    """(event, item params dict, parameter key, sub-flow entry) for every NPC grant, as npc_grants finds them."""
    out = []
    for params, key, entry in _grant_params(flow):
        event = next(
            e for e in flow.flowchart.events
            if getattr(e.data, "params", None) is not None and e.data.params.data is params
        )
        out.append((event, params, key, entry))
    return out


def _clone_grant(base: Event, key: str, tier: str):
    """A copy of the grant node `base` that hands out `tier` in `key`, with the same successor."""
    params = params_of({**base.data.params.data, key: tier})
    if isinstance(base.data, SubFlowEvent):
        sub = SubFlowEvent()
        sub.nxt = make_index(base.data.nxt.v)
        sub.res_flowchart_name = base.data.res_flowchart_name
        sub.entry_point_name = base.data.entry_point_name
        sub.params = params
        return sub
    act = ActionEvent()
    act.actor = make_rindex(base.data.actor.v)
    act.actor_action = make_rindex(base.data.actor_action.v)
    act.nxt = make_index(base.data.nxt.v)
    act.params = params
    return act


def wrap_grant(flow: EventFlow, event: Event, key: str, family: progressive.Family) -> None:
    """Make the grant `event` hand out the family's lowest unowned tier. `key` is its item parameter.

    `event` is a sub-flow call or a pouch add. The event object stays the same, so every reference to
    it (switch cases, entry points, fork branches) now enters the chain. Each tier's give is a copy of
    the grant with `key` set to that tier, and keeps the grant's successor.
    """
    base = event.data
    if not isinstance(base, (SubFlowEvent, ActionEvent)) or base.params is None or key not in base.params.data:
        raise ProgressiveNpcError(f"{event.name} is not a grant with a {key} parameter")
    fc = flow.flowchart
    actor, holder = owner_holder(flow)
    gives: list[Event] = []
    for i, tier in enumerate(family.tiers):
        give = Event()
        give.name = f"{event.name}_OOTREM_{family.key}_Give{i}"
        give.data = _clone_grant(event, key, tier)
        fc.events.append(give)
        gives.append(give)
    chain_events(fc, family, actor, holder, gives, event, f"{event.name}_OOTREM_{family.key}")


def patch_npc_flow(data: bytes, flow_file: str, changes: dict) -> bytes:
    """patch_npc_grants for a flow that takes progressive copies, in one parse.

    `changes` maps (sub-flow entry, vanilla item) or a plain vanilla item to the new item, as for
    patch_npc_grants. A copy name repoints the grant to the family's lowest tier and wraps it. The
    steps run in the order the flow needs: repoint, branch fix (which needs the kept grant still
    unwrapped), wrap the copies, then the Slingshot bag, which must sit before the wrapped gives.
    """
    flow = EventFlow()
    flow.read(data)
    keyed = {(key if isinstance(key, tuple) else (None, key)): new for key, new in changes.items()}
    hits = []
    for event, params, key, group in _grant_events(flow):
        new = keyed.get((group, params[key]), keyed.get((None, params[key])))
        if new is not None:
            hits.append((event, params, key, new))
    if not hits:
        raise ValueError(f"NPC flow {flow_file} grants none of {sorted({item for _, item in keyed})}")
    wraps = []
    for event, params, key, new in hits:
        family = progressive.family_of_copy(new)
        params[key] = progressive.first_tier(new)
        if family is not None:
            wraps.append((event, key, family))
    if flow_file in REROUTED_FLOWS:
        _fix_progressive_branches(flow, flow_file)
    for event, key, family in wraps:
        wrap_grant(flow, event, key, family)
    _add_slingshot_bag(flow)
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def patch_event_flow(data: bytes, old_item: str, copy_name: str) -> bytes:
    """Wrap the live grants of `old_item` in an event flow, for a progressive copy.

    The grants are the ActorName sub-flow that displays the item and any pouch add of it. A grant is
    live when it is reachable from an entry point; unreachable grants are left as they are. Each
    grant gets its own chain. Both chains ask the same ownership at the same point, so they pick the
    same tier.
    """
    flow = EventFlow()
    flow.read(data)
    reachable = _reachable(flow)
    grants = [
        e for e in flow.flowchart.events
        if (
            isinstance(e.data, SubFlowEvent) and e.data.entry_point_name in _GRANT_SUBFLOWS
            and e.data.params is not None and e.data.params.data.get("ActorName") == old_item
        ) or (
            isinstance(e.data, ActionEvent) and _is_pouch_add(e.data) and e.data.params is not None
            and e.data.params.data.get("Actor") == old_item
        )
    ]
    live = [e for e in grants if id(e) in reachable]
    if not live:
        raise ProgressiveNpcError(f"event flow has no live grant of {old_item!r}")
    family = progressive.family_of_copy(copy_name)
    keyed = [(e, "ActorName" if isinstance(e.data, SubFlowEvent) else "Actor") for e in live]
    for event, key in keyed:
        event.data.params.data[key] = progressive.first_tier(copy_name)
    for event, key in keyed:
        wrap_grant(flow, event, key, family)
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def _targets(event: Event) -> list[Event]:
    data = event.data
    if isinstance(data, SwitchEvent):
        found = [c.v for c in data.cases.values()]
    elif isinstance(data, ForkEvent):
        found = [f.v for f in data.forks] + ([data.join.v] if data.join is not None else [])
    else:
        nxt = getattr(data, "nxt", None)
        found = [nxt.v] if nxt is not None else []
    return [t for t in found if t is not None]


def _reachable(flow: EventFlow) -> set[int]:
    """Ids of the events reachable from the flow's entry points."""
    seen: set[int] = set()
    stack = [e.main_event.v for e in flow.flowchart.entry_points if e.main_event is not None and e.main_event.v]
    while stack:
        event = stack.pop()
        if id(event) not in seen:
            seen.add(id(event))
            stack.extend(_targets(event))
    return seen
