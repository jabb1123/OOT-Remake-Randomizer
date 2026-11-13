"""Randomized loose overworld heart pieces (Obj_Heart_Piece actors placed in the world).

Each physical piece is a logic location. The planner gives it any item that shops can sell
(`can_pickup`). The patcher clones Obj_Heart_Piece once per distinct item, named
`Obj_HeartRando_<item>`, and points every piece assigned that item at the clone. Pieces keep
their translate and actor index; only the actor's Gyaml changes. Dungeon and chest hearts are
not in this table.

The Gerudo Valley piece is its own class (Obj_GerudoValley_Heart_Piece), but it is a loose
piece too, so it is listed here and its Gyaml is swapped the same way.

The slot table was produced by scripts/scan_loose_hearts.py (see loose_heart_pieces.json).
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from .byml7 import parse_byml7
from .shop_slots import can_sell
from .shops import Shelf, ShopError, apply_shop_items, set_actor_gyaml

# Loose heart classes: a placed actor of one of these with no Dynamic block is a free piece.
HEART_GYAMLS: frozenset[str] = frozenset({"Obj_Heart_Piece", "Obj_GerudoValley_Heart_Piece"})
NAME_PREFIX = "Obj_HeartRando_"

# slot name -> [(scene bcett file, Actors index)]; one entry per scene copy that holds the piece.
_HEART_TARGETS: dict[str, list[tuple[str, int]]] = {
    "DeathMountainCrater Heart Piece 1": [
        ("DeathMountainCrater_Adult_Static.bcett.byml.zs", 10),
        ("DeathMountainCrater_Child_Static.bcett.byml.zs", 10)],
    "DeathMountainCrater Heart Piece 2": [
        ("DeathMountainCrater_Adult_Static.bcett.byml.zs", 9),
        ("DeathMountainCrater_Child_Static.bcett.byml.zs", 9)],
    "DeathMountainTrail Heart Piece 1": [
        ("DeathMountainTrail_Adult_Static.bcett.byml.zs", 34),
        ("DeathMountainTrail_Child_Static.bcett.byml.zs", 34)],
    "DesertColossus Heart Piece 1": [
        ("DesertColossus_Adult_Static.bcett.byml.zs", 67),
        ("DesertColossus_Child_Static.bcett.byml.zs", 67)],
    "GerudoValley Heart Piece 1": [
        ("GerudoValley_Adult_Static.bcett.byml.zs", 24),
        ("GerudoValley_Child_Static.bcett.byml.zs", 18)],
    "Graveyard Heart Piece 1": [
        ("Graveyard_Adult_Static.bcett.byml.zs", 237),
        ("Graveyard_Child_Static.bcett.byml.zs", 237)],
    "HyruleField Heart Piece 1": [
        ("HyruleField_Adult_Static.bcett.byml.zs", 1733)],
    "HyruleField Heart Piece 2": [
        ("HyruleField_Child_Static.bcett.byml.zs", 1495)],
    "KakarikoVillage Heart Piece 1": [
        ("KakarikoVillage_Adult_Alternative_Static.bcett.byml.zs", 41),
        ("KakarikoVillage_Adult_Static.bcett.byml.zs", 41),
        ("KakarikoVillage_Child_Static.bcett.byml.zs", 41)],
    "KakarikoVillage Heart Piece 2": [
        ("KakarikoVillage_Adult_Alternative_Static.bcett.byml.zs", 40),
        ("KakarikoVillage_Adult_Static.bcett.byml.zs", 40),
        ("KakarikoVillage_Child_Static.bcett.byml.zs", 40)],
    "ZoraFountain Heart Piece 1": [
        ("ZoraFountain_Adult_Static.bcett.byml.zs", 128)],
    "ZoraFountain Heart Piece 2": [
        ("ZoraFountain_Adult_Static.bcett.byml.zs", 127)],
    "ZoraRiver Heart Piece 1": [
        ("ZoraRiver_Adult_Static.bcett.byml.zs", 40),
        ("ZoraRiver_Child_Static.bcett.byml.zs", 40)],
    "ZoraRiver Heart Piece 2": [
        ("ZoraRiver_Adult_Static.bcett.byml.zs", 39),
        ("ZoraRiver_Child_Static.bcett.byml.zs", 39)],
}


@dataclass(frozen=True, slots=True)
class HeartSlot:
    name: str
    shelves: tuple[Shelf, ...]


HEART_SLOTS: dict[str, HeartSlot] = {
    name: HeartSlot(name, tuple(Shelf(scene, index) for scene, index in targets))
    for name, targets in _HEART_TARGETS.items()
}
HEART_LOCATIONS: frozenset[str] = frozenset(HEART_SLOTS)


def can_pickup(item: str) -> bool:
    """Items a heart piece can give: the same set shops can sell."""
    return can_sell(item)


def heart_actor_name(item_actor: str) -> str:
    return f"{NAME_PREFIX}{item_actor}"


def set_heart_actor(bcett_bytes: bytes, select: Any, new_gyaml: str, *,
                    allow_multiple: bool = False, changed: list[int] | None = None) -> bytes:
    """Point the loose heart piece at Actors[select] to `new_gyaml`.

    `select` is an exact Actors index. The actor must be a loose heart class (HEART_GYAMLS)
    with no Dynamic block, so a chest or Dynamic heart can never be rewritten by mistake.
    """
    if allow_multiple:
        raise ShopError("heart pieces are addressed by exact actor index; allow_multiple is not supported")
    actors = parse_byml7(bcett_bytes).get("Actors") or []
    if isinstance(select, bool) or not isinstance(select, int) or not 0 <= select < len(actors):
        raise ShopError(f"heart actor index {select!r} is out of range")
    actor = actors[select]
    if actor.get("Gyaml") not in HEART_GYAMLS or "Dynamic" in actor:
        raise ShopError(f"actor {select} is not a loose heart piece (found {actor.get('Gyaml')!r})")
    return set_actor_gyaml(bcett_bytes, [select], new_gyaml, changed=changed)


def heart_items_for(assignments: Iterable[tuple[str, str]]) -> list[tuple[str, int, list[Shelf]]]:
    """apply_shop_items arguments for [(slot name, item)].

    Pieces that give the same item share one clone, so the item's shelves are merged. Unlike
    shops, an item may appear in several heart slots.
    """
    shelves: dict[str, list[Shelf]] = {}
    for name, item in assignments:
        slot = HEART_SLOTS.get(name)
        if slot is None:
            raise ShopError(f"unknown heart pickup slot {name!r}")
        if not can_pickup(item):
            raise ShopError(f"{item} cannot be given by a heart pickup ({name})")
        shelves.setdefault(item, []).extend(slot.shelves)
    return [(item, 0, shelf_list) for item, shelf_list in shelves.items()]


def heart_pack_names(assignments: Iterable[tuple[str, str]]) -> list[str]:
    """Actor names of the clones heart_items_for(assignments) would create."""
    return [heart_actor_name(item) for item, _, _ in heart_items_for(assignments)]


def apply_heart_pickups(nup_path: Any, zsdic_bytes: bytes, assignments: Sequence[tuple[str, str]]):
    """Clone Obj_Heart_Piece for each item and point the planned pieces at it (in place)."""
    items = heart_items_for(assignments)
    if not items:
        return None
    try:
        return apply_shop_items(nup_path, zsdic_bytes, items, template="Obj_Heart_Piece",
                                name_for=heart_actor_name, set_actor=set_heart_actor)
    except KeyError as exc:  # raised while reading, before anything is written
        raise ShopError(f"file missing from the NUP: {exc}") from exc
