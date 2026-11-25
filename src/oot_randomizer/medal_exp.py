"""Medal formulas for the Kakariko Burning, Forest prelude and Light Arrows flags.

Three computed flags change so the story reads medals instead of sage quests:

- SageOfShadow_Kakariko_Burning is true once the Forest, Fire, and Water medals are all held.
- AllSage_IsAfter_Step01_02_Exp is true once the Forest medal is held. The Market prelude module reads it
  instead of SageOfForest_IsCompleted_Exp (see patch_prelude_module).
- AllSage_IsAfter_Step02_Exp is true once the Shadow and Spirit medals are held and the Light Arrows scene has
  not played yet. The Light Arrows module and its Temple of Time area read it (see lacs_gate.py).

The sage quest flags themselves are not changed. Only these formulas and the reads of them move to medals, so
the sage flows keep their own completion checks.
"""

from __future__ import annotations

from typing import Any

from .ainb import parse as parse_ainb
from .byml7 import U64, dump_byml7, parse_byml7_typed
from .gamedata_list import murmur3_32

PRELUDE_MODULE = "Market_Adult_Prefab_edc2.logic.module.ainb"

KAKARIKO_EXP = "SageOfShadow_Kakariko_Burning"
PRELUDE_EXP = "AllSage_IsAfter_Step01_02_Exp"
LACS_EXP = "AllSage_IsAfter_Step02_Exp"
LACS_PLAYED = "HavePlayedEvent.Dm_TimeTemple_0130"
PRELUDE_READ_EXP = "SageOfForest_IsCompleted_Exp"
_PRELUDE_READ_ELEMENT = "HoldGameDataGetBoolExpSimple"
_PRELUDE_READ_INPUT = "GameDataNameBoolExp"

_REF = 0
_AND = 3
_NOT = 5

MEDAL_FLAG_PREFIX = "IsGet.Item_Medal_"


def medal_flag(medal: str) -> str:
    return f"{MEDAL_FLAG_PREFIX}{medal}"


def _formulas() -> dict[str, list[tuple[int, str | None]]]:
    kakariko = [
        (_REF, medal_flag("Forest")),
        (_REF, medal_flag("Fire")),
        (_REF, medal_flag("Water")),
        (_AND, None),
        (_AND, None),
    ]
    prelude = [(_REF, medal_flag("Forest"))]
    lacs = [
        (_REF, medal_flag("Shadow")),
        (_REF, medal_flag("Spirit")),
        (_AND, None),
        (_REF, LACS_PLAYED),
        (_NOT, None),
        (_AND, None),
    ]
    return {KAKARIKO_EXP: kakariko, PRELUDE_EXP: prelude, LACS_EXP: lacs}


def _row(root: dict[str, Any], name: str) -> dict[str, Any]:
    hash_ = murmur3_32(name.encode())
    rows = [r for r in root["Data"]["BoolExp"] if int(r["Hash"]) == hash_]
    if len(rows) != 1:
        raise ValueError(f"GameDataList: expected one BoolExp row for {name}, found {len(rows)}")
    return rows[0]


def _set_formula(root: dict[str, Any], name: str, terms: list[tuple[int, str | None]]) -> bool:
    """Replace a computed flag's formula with `terms` (opcode, flag or None). Returns True if it changed.

    The existing rows are all U64 nodes, so the new terms are too.
    """
    row = _row(root, name)
    if not all(isinstance(x, U64) for term in row["Values"] for x in term):
        raise ValueError(f"GameDataList: the formula of {name} has an unexpected term layout")
    bools = {int(r["Hash"]) for r in root["Data"]["Bool"]}

    new_values = []
    for op, flag in terms:
        if flag is None:
            new_values.append([U64(op)])
            continue
        if murmur3_32(flag.encode()) not in bools:
            raise ValueError(f"GameDataList: the formula of {name} reads {flag}, which is not a registered bool")
        new_values.append([U64(op), U64(murmur3_32(flag.encode()))])

    if row["Values"] == new_values:
        return False
    row["Values"] = new_values
    return True


def patch_gamedata_medal_exps(raw: bytes) -> bytes:
    """Set the medal formulas on a GameDataList. Returns the input unchanged when they already match."""
    root = parse_byml7_typed(raw)
    changed = False
    for name, terms in _formulas().items():
        changed = _set_formula(root, name, terms) or changed
    if not changed:
        return raw
    return dump_byml7(root, big_endian=True, version=7)


def patch_prelude_module(data: bytes) -> bytes:
    """Point the Market prelude's Forest sage read at PRELUDE_EXP instead of SageOfForest_IsCompleted_Exp.

    Returns the input unchanged when it already reads PRELUDE_EXP. Raises ValueError unless exactly one
    SageOfForest_IsCompleted_Exp read is found, so a different build is not patched silently.
    """
    ainb = parse_ainb(data)
    reads = [i for i in ainb.find_els(_PRELUDE_READ_ELEMENT) if ainb.in_str(i, _PRELUDE_READ_INPUT) is not None]
    if any(ainb.in_str(i, _PRELUDE_READ_INPUT) == PRELUDE_EXP for i in reads):
        return data
    hits = [i for i in reads if ainb.in_str(i, _PRELUDE_READ_INPUT) == PRELUDE_READ_EXP]
    if len(hits) != 1:
        raise ValueError(f"{PRELUDE_MODULE}: expected one {PRELUDE_READ_EXP} read, found {len(hits)}")
    ainb.set_str_input(hits[0], _PRELUDE_READ_INPUT, PRELUDE_EXP)
    return ainb.write()
