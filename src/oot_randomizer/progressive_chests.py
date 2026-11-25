"""Progressive chests: a chest holding a progressive copy grants the lowest tier the pouch lacks.

Each chest flow (small and big) gets one entry per family, `Success_Prog_<family>`. The entry asks the
pouch, tier by tier from the lowest, whether it owns the tier (GameDataActor.EventQueryCheckIsGet, case
0 = owned), and then calls the flow's own `Success_` entry with the tier actor as ContentName. That is
the same give a chest with that actor drops. The chest's GetEventName selects a row in the RSDB
EventSetting table, which points at the new entry. Those rows are copies of the template row.

Chests are matched by their position among the Obj_TBox actors that have a Drop__DropActor field, the
same order nup_chest_patcher uses for chest_order.
"""

from __future__ import annotations

import copy
import io
from collections.abc import Iterable

from evfl import EventFlow
from evfl.actor import Actor
from evfl.common import ActorIdentifier, StringHolder
from evfl.container import Container
from evfl.entry_point import EntryPoint
from evfl.event import Event, SubFlowEvent, SwitchEvent
from evfl.util import make_index, make_rindex

from . import progressive
from .byml7 import dump_byml7, parse_byml7

SMALL_FLOW = "Dm_SY_TreasureboxSmall.bfevfl.zs"
BIG_FLOW = "Dm_SY_Treasurebox.bfevfl.zs"
SMALL_TEMPLATE = "Dm_SY_TreasureboxSmall"
BIG_TEMPLATE = "Dm_SY_Treasurebox"
SETTING_TABLE = "EventSetting.Product.111.rstbl.byml.zs"
ANALYZED_TABLE = "GameAnalyzedEventInfo.Product.111.rstbl.byml.zs"
ROOT_ENTRY = "Success_"
OWNS_ACTOR = "GameDataActor"
OWNS_QUERY = "EventQueryCheckIsGet"
DROP_KEY = "Drop__DropActor"
EVENT_KEY = "GetEventName"
SIZES = ("Small", "Big")
_FLOW = {"Small": SMALL_FLOW, "Big": BIG_FLOW}
_TEMPLATE = {"Small": SMALL_TEMPLATE, "Big": BIG_TEMPLATE}

# (scene file, chest_order) of chests that already have a GetEventName: vanilla special events (dungeon
# rewards, sages, the Dampe race, the Longshot chest). A progressive copy would replace that event, so
# these chests never take a copy. Found by scanning every bcett file of the retail NUP (226 chests).
NAMED_EVENT_CHESTS: frozenset[tuple[str, int]] = frozenset({
    ("BottomOfTheWell_Dynamic.bcett.byml.zs", 1),
    ("BottomOfTheWell_Static.bcett.byml.zs", 1),
    ("DesertColossus_Adult_Static.bcett.byml.zs", 0),
    ("DesertColossus_Adult_Static.bcett.byml.zs", 1),
    ("DesertColossus_Child_Static.bcett.byml.zs", 0),
    ("DesertColossus_Child_Static.bcett.byml.zs", 1),
    ("DodongoCavern_Dynamic.bcett.byml.zs", 0),
    ("DodongoCavern_Static.bcett.byml.zs", 1),
    ("DodongoCavern_Static.bcett.byml.zs", 2),
    ("FireTemple_Dynamic.bcett.byml.zs", 0),
    ("FireTemple_Static.bcett.byml.zs", 6),
    ("FireTemple_Static.bcett.byml.zs", 7),
    ("FireTemple_Static.bcett.byml.zs", 14),
    ("ForestTemple_Static.bcett.byml.zs", 1),
    ("ForestTemple_Static.bcett.byml.zs", 2),
    ("ForestTemple_Static.bcett.byml.zs", 7),
    ("ForestTemple_Static.bcett.byml.zs", 8),
    ("GerudoTrainingGround_Static.bcett.byml.zs", 12),
    ("Graveyard_Adult_Static.bcett.byml.zs", 1),
    ("Graveyard_Adult_Static.bcett.byml.zs", 2),
    ("Graveyard_Adult_Static.bcett.byml.zs", 3),
    ("Graveyard_Adult_Static.bcett.byml.zs", 4),
    ("IceCavern_Static.bcett.byml.zs", 2),
    ("InsideGanonCastle_Static.bcett.byml.zs", 0),
    ("InsideJabuJabuBelly_Static.bcett.byml.zs", 0),
    ("InsideJabuJabuBelly_Static.bcett.byml.zs", 1),
    ("InsideTheDekuTree_Static.bcett.byml.zs", 0),
    ("InsideTheDekuTree_Static.bcett.byml.zs", 1),
    ("InsideTheDekuTree_Static.bcett.byml.zs", 3),
    ("KokiriForest_Adult_Dynamic.bcett.byml.zs", 1),
    ("KokiriForest_Adult_Dynamic.bcett.byml.zs", 2),
    ("KokiriForest_Adult_Dynamic.bcett.byml.zs", 3),
    ("KokiriForest_Adult_Dynamic.bcett.byml.zs", 4),
    ("KokiriForest_Adult_Dynamic.bcett.byml.zs", 5),
    ("KokiriForest_Child_Dynamic.bcett.byml.zs", 1),
    ("KokiriForest_Child_Dynamic.bcett.byml.zs", 2),
    ("KokiriForest_Child_Dynamic.bcett.byml.zs", 3),
    ("KokiriForest_Child_Dynamic.bcett.byml.zs", 4),
    ("KokiriForest_Child_Dynamic.bcett.byml.zs", 5),
    ("ShadowTemple_Static.bcett.byml.zs", 0),
    ("ShadowTemple_Static.bcett.byml.zs", 1),
    ("ShadowTemple_Static.bcett.byml.zs", 2),
    ("ShadowTemple_Static.bcett.byml.zs", 10),
    ("SpiritTemple_Static.bcett.byml.zs", 5),
    ("SpiritTemple_Static.bcett.byml.zs", 11),
    ("WaterTemple_Static.bcett.byml.zs", 0),
    ("WaterTemple_Static.bcett.byml.zs", 4),
    ("WaterTemple_Static.bcett.byml.zs", 6),
    ("WaterTemple_Static.bcett.byml.zs", 8),
})


class ProgressiveChestError(RuntimeError):
    pass


def size_of(gyaml: str) -> str:
    return "Big" if gyaml.startswith(("Obj_TBox_A_02", "Obj_TBox_A_03")) else "Small"


def event_name(family: str, size: str) -> str:
    return f"OOTREM_Prog_{family}_{size}"


def entry_name(family: str) -> str:
    return f"{ROOT_ENTRY}Prog_{family}"


def ask_chain(tiers: int) -> list[tuple[int, tuple[str, int], tuple[str, int]]]:
    """The questions that pick the lowest unowned tier, as (owner index, if owned, if not owned).

    A target is ("ask", j) for question j or ("give", k) for tier k. The last tier needs no question:
    when every lower tier is owned, it is the one to give.
    """
    steps = []
    for i in range(tiers - 1):
        owned = ("ask", i + 1) if i + 1 < tiers - 1 else ("give", tiers - 1)
        steps.append((i, owned, ("give", i)))
    return steps


def params_of(items: dict) -> Container:
    c = Container()
    c.data = dict(items)
    return c


def owner_holder(flow: EventFlow) -> tuple[Actor, StringHolder]:
    fc = flow.flowchart
    actor = next((a for a in fc.actors if a.identifier.name == OWNS_ACTOR and not a.identifier.sub_name), None)
    if actor is None:
        actor = Actor()
        actor.identifier = ActorIdentifier(OWNS_ACTOR)
        actor.concurrent_clips = 1
        fc.actors.append(actor)
    holder = next((q for q in actor.queries if q.v == OWNS_QUERY), None)
    if holder is None:
        holder = StringHolder(OWNS_QUERY)
        actor.queries.append(holder)
    return actor, holder


def wrap_flow(flow: EventFlow, families: Iterable[str]) -> list[str]:
    """Add the progressive entry of each family to a chest flow. Returns the names it added."""
    fc = flow.flowchart
    if not any(e.name == ROOT_ENTRY for e in fc.entry_points):
        raise ProgressiveChestError(f"the chest flow has no {ROOT_ENTRY} entry")
    actor, holder = owner_holder(flow)
    added: list[str] = []
    for key in families:
        fam = progressive.family(key)
        name = entry_name(key)
        if any(e.name == name for e in fc.entry_points):
            continue
        gives: list[Event] = []
        for i, tier in enumerate(fam.tiers):
            ev = Event()
            ev.name = f"OOTREM_{key}_Give{i}"
            sub = SubFlowEvent()
            sub.res_flowchart_name = ""
            sub.entry_point_name = ROOT_ENTRY
            sub.params = params_of({"ContentName": tier, "IsMiniGame": False})
            ev.data = sub
            fc.events.append(ev)
            gives.append(ev)
        asks = chain_events(fc, fam, actor, holder, gives, None, f"OOTREM_{key}")
        entry = EntryPoint(name)
        entry.main_event = make_index(asks[0])
        fc.entry_points.append(entry)
        added.append(name)
    return added


def chain_events(fc, fam: progressive.Family, actor: Actor, holder: StringHolder, gives: list[Event],
                 first: Event | None, prefix: str) -> list[Event]:
    """Create the questions of a family's chain (ask_chain) and point them at `gives`.

    The root question is `first` when given, so existing references to that event now enter the chain.
    Returns the questions in ask_chain order, root first.
    """
    steps = ask_chain(len(fam.tiers))
    asks: list[Event] = []
    for i in range(len(steps)):
        if i == 0 and first is not None:
            ev = first
        else:
            ev = Event()
            ev.name = f"{prefix}_Ask{i}"
            fc.events.append(ev)
        asks.append(ev)

    def target(t: tuple[str, int]) -> Event:
        return asks[t[1]] if t[0] == "ask" else gives[t[1]]

    for (owner, owned, unowned), ev in zip(steps, asks):
        sw = SwitchEvent()
        sw.actor = make_rindex(actor)
        sw.actor_query = make_rindex(holder)
        sw.params = params_of({"ActorName": fam.owners[owner]})
        sw.cases = {0: make_rindex(target(owned)), 1: make_rindex(target(unowned))}
        ev.data = sw
    return asks


def wrap_flow_bytes(raw: bytes, families: Iterable[str]) -> bytes:
    flow = EventFlow()
    flow.read(raw)
    if not wrap_flow(flow, families):
        return raw
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def add_rows(rows: list, template: str, specs: Iterable[tuple[str, str | None]]) -> int:
    """Add or replace rows named `id`, each a copy of the template row, with EntryPointName when given."""
    base = next((r for r in rows if r.get("__RowId") == template), None)
    if base is None:
        raise ProgressiveChestError(f"the table has no {template} row")
    n = 0
    for row_id, entry in specs:
        row = copy.deepcopy(base)
        row["__RowId"] = row_id
        if entry is not None:
            row["EntryPointName"] = entry
        at = next((i for i, r in enumerate(rows) if r.get("__RowId") == row_id), None)
        if at is None:
            at = next((i for i, r in enumerate(rows) if str(r.get("__RowId", "")) > row_id), len(rows))
            rows.insert(at, row)
        else:
            rows[at] = row
        n += 1
    return n


def chest_actors(root: dict) -> list[dict]:
    """The chest actors in chest_order: Obj_TBox actors with a Dynamic that has a Drop__DropActor."""
    return [
        a for a in root.get("Actors", [])
        if str(a.get("Gyaml", "")).startswith("Obj_TBox")
        and isinstance(a.get("Dynamic"), dict) and DROP_KEY in a["Dynamic"]
    ]


def retarget_chests(raw: bytes, marks: dict[int, str], used: set[tuple[str, str]]) -> bytes:
    """Point each marked chest at its family's event. `marks` maps chest_order to a family key.

    Adds (family, size) to `used` for every chest changed. A chest that already has a GetEventName is
    refused, because its vanilla event would be lost.
    """
    root = parse_byml7(raw)
    chests = chest_actors(root)
    for order, key in sorted(marks.items()):
        if not 0 <= order < len(chests):
            raise ProgressiveChestError(f"chest_order {order} is out of range ({len(chests)} chests)")
        actor = chests[order]
        dyn = copy.deepcopy(actor["Dynamic"])
        if dyn.get(EVENT_KEY):
            raise ProgressiveChestError(f"chest {order} already has GetEventName {dyn[EVENT_KEY]!r}")
        size = size_of(str(actor.get("Gyaml", "")))
        dyn[DROP_KEY] = progressive.family(key).tiers[0]
        dyn[EVENT_KEY] = event_name(key, size)
        actor["Dynamic"] = dyn
        used.add((key, size))
    return dump_byml7(root)


def excluded_slots(slots) -> frozenset[str]:
    """Names of chest slots with a target in NAMED_EVENT_CHESTS. They never take a progressive copy."""
    return frozenset(s.name for s in slots if any((scene, order) in NAMED_EVENT_CHESTS for scene, order in s.targets))


def progressive_targets(assignments) -> list[tuple[str, int, str]]:
    """(scene file, chest_order, family) for every chest slot whose item is a progressive copy."""
    out = []
    for slot, item in assignments:
        fam = progressive.family_of_copy(item)
        if fam is None:
            continue
        for scene, order in slot.targets:
            out.append((scene, order, fam.key))
    return out


def apply_progressive(patcher, targets: list[tuple[str, int, str]]) -> dict[str, int]:
    """Edit the chest flows, the RSDB event tables and the marked bcett files of a NUP copy, in place.

    Run after the chest patches: each replace_file re-reads the NUP. Returns counts for the report.
    """
    if not targets:
        return {}
    by_scene: dict[str, dict[int, str]] = {}
    for scene, order, key in targets:
        by_scene.setdefault(scene, {})[order] = key
    used: set[tuple[str, str]] = set()
    for scene, marks in by_scene.items():
        patcher.replace_file(scene, lambda raw, m=marks: retarget_chests(raw, m, used))
    for size in SIZES:
        families = sorted({f for f, s in used if s == size})
        if families:
            patcher.replace_file(_FLOW[size], lambda raw, fs=families: wrap_flow_bytes(raw, fs))

    def edit_table(with_entry: bool):
        def run(raw: bytes) -> bytes:
            rows = parse_byml7(raw)
            for size in SIZES:
                specs = [(event_name(f, s), entry_name(f) if with_entry else None)
                         for f, s in sorted(used) if s == size]
                if specs:
                    add_rows(rows, _TEMPLATE[size], specs)
            return dump_byml7(rows)
        return run

    patcher.replace_file(SETTING_TABLE, edit_table(True))
    patcher.replace_file(ANALYZED_TABLE, edit_table(False))
    return {"chests": len(targets), "families": len({f for f, _ in used})}
