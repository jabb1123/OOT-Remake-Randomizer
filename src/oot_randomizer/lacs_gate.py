"""Light Arrows scene gate: the scene waits for the nine-reward formula instead of the AllSage Step02 check.

- The Light Arrows logic module (LACS_MODULE): the Light Arrows area's create input becomes a constant true,
  and every AND gate that read the Step02 check reads the player sensor instead.
- The adult Market static map (LACS_MAP_FILE): the Light Arrows area gets the presence flag LACS_EXP, so it
  appears only once that formula holds (see medal_exp.py).
"""

from __future__ import annotations

from typing import Any

from .ainb import BOOL_KIND, CONST_SRC, Ainb, audit
from .ainb import parse as parse_ainb
from .byml7 import Byml7, dump_byml7, parse_byml7_typed
from .medal_exp import LACS_EXP

LACS_MODULE = "Market_Adult_Prefab_c668.logic.module.ainb"
# The file is Banc/Market/Market_Adult_Static.bcett.byml.zs in the romfs; NUP lookups use the file name.
LACS_MAP_FILE = "Market_Adult_Static.bcett.byml.zs"
LACS_AREA = "Area_a3ca"
LACS_AREA_HASH = 11085071794120779663
ALL_SAGE = "Work/Challenge/AllSage.game__challenge__Challenge.gyml"
LACS_STEP = "Step02"

_AREA = "ActorLogicAreaActor"
_STEP = "HoldChallengeCurrentStepCheckOrder"
_HIT = "HoldActorObserverBySensorHitInfo"
_AND = "OperateAND"
_CREATE = "Logic_Create"
_PRESENCE = {"FlagName": LACS_EXP, "IsCheckLazy": False, "IsNegation": False}


def _one(hits: list[int], what: str) -> int:
    if len(hits) != 1:
        raise ValueError(f"{LACS_MODULE}: expected one {what}, found {len(hits)}, the module is not the unpatched one")
    return hits[0]


def lacs_step(a: Ainb) -> int:
    """Return the element index of the AllSage Step02 check."""
    return _one(
        [i for i in a.find_els(_STEP) if a.in_str(i, "ChallengeName") == ALL_SAGE and a.in_str(i, "ChallengeStepName") == LACS_STEP],
        "AllSage Step02 check",
    )


def reads_of(a: Ainb, src: int) -> int:
    """Count the inputs, plugs and multi-link entries that read element `src`."""
    n = 0
    for i in range(len(a.els)):
        for k in range(6):
            for g in a.input_ids(i, k):
                x = a.input(k, g)
                if x is not None and x.src >= 0 and x.src == src:
                    n += 1
        n += sum(1 for p in a.params[i].plugs if p.a == src)
        rng = a.multi_range(i) if a.el_name(i) == _AND else None
        if rng is not None:
            first, count = rng
            n += sum(1 for j in range(first, first + count) if _points_at(a, j, src))
    return n


def _points_at(a: Ainb, j: int, elem: int) -> bool:
    e = a.multi_entry(j)
    return e is not None and e[0] == elem


def patch_lacs_module(data: bytes) -> bytes:
    """Stop the Light Arrows area waiting for the AllSage Step02 check.

    Returns the input unchanged once it is patched. Raises ValueError on any other layout, or when
    something other than the area still reads the Step02 check after the edit.
    """
    a = parse_ainb(data)
    step = lacs_step(a)
    area = _one([i for i in a.find_els(_AREA) if a.prop_str(i, "InstanceName") == LACS_AREA], "Light Arrows area")
    g = a.find_in(area, BOOL_KIND, _CREATE)
    if g is None:
        raise ValueError(f"{LACS_MODULE}: the Light Arrows area has no create input")
    x = a.input(BOOL_KIND, g)
    if x.src == CONST_SRC and int.from_bytes(x.val, "little") == 1 and reads_of(a, step) == 0:
        return data
    if x.src != step:
        raise ValueError(f"{LACS_MODULE}: the Light Arrows area is not created from the AllSage Step02 check")
    hit = _one(a.find_els(_HIT), "player sensor")
    a.force_bool(area, _CREATE, True)
    for i in a.find_els(_AND):
        rng = a.multi_range(i)
        if rng is None:
            continue
        first, count = rng
        entries = range(first, first + count)
        if not any(_points_at(a, j, step) for j in entries):
            continue
        src = next((j for j in entries if _points_at(a, j, hit)), None)
        if src is None:
            raise ValueError(f"{LACS_MODULE}: the gate that reads the Step02 check does not read the player sensor")
        for j in entries:
            if _points_at(a, j, step):
                a.copy_multi_entry(j, src)
    if reads_of(a, step) != 0:
        raise ValueError(f"{LACS_MODULE}: something still reads the AllSage Step02 check")
    out = a.write()
    back = parse_ainb(out)
    if back.write() != out or audit(back):
        raise ValueError(f"{LACS_MODULE}: the patched module does not read back")
    return out


def patch_lacs_map(data: bytes) -> bytes:
    """Give the Light Arrows area in the adult Market map the presence flag LACS_EXP.

    Returns the input unchanged once the area has that presence. Raises ValueError when the area is missing,
    is not an unpatched Area, or already has a different presence.
    """
    root: Any = parse_byml7_typed(data)
    actors = root.get("Actors") if isinstance(root, dict) else None
    if not isinstance(actors, list):
        raise ValueError(f"{LACS_MAP_FILE}: the map has no actors")
    hits = [a for a in actors if isinstance(a, dict) and a.get("Hash") == LACS_AREA_HASH]
    if len(hits) != 1:
        raise ValueError(f"{LACS_MAP_FILE}: expected one Light Arrows area, found {len(hits)}")
    area = hits[0]
    if area.get("Gyaml") != "Area":
        raise ValueError(f"{LACS_MAP_FILE}: the Light Arrows actor is not an Area")
    if "Presence" in area:
        if area["Presence"] == _PRESENCE:
            return data
        raise ValueError(f"{LACS_MAP_FILE}: the Light Arrows area already has a presence flag")
    area["Presence"] = dict(_PRESENCE)
    reader = Byml7(data)
    out = dump_byml7(root, big_endian=not reader.is_little_endian, version=reader.version)
    if parse_byml7_typed(out) != root:
        raise ValueError(f"{LACS_MAP_FILE}: the patched map does not read back")
    return out
