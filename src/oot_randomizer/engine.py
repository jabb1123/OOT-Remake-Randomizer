from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path

from .location_mapper import build_location_matches, build_runtime_locations, load_summary_file
from .locations import LOCATIONS, OOTLocation
from .patcher import PatchRecord, _legacy_item_id, make_patch

# Keys stay in vanilla chests until key logic exists; moving them can softlock dungeons.
UNSHUFFLED_ITEMS = frozenset({"Item_Dungeon_SmallKey", "Item_Dungeon_BossKey"})
# Scanned chests that are not present in the game (verified in play). Left out of the pool so
# no item is placed where nothing can be picked up.
NOT_IN_GAME_SLOTS = frozenset({"KokiriForest Static room 0 #0 (TBox_Rupee_Green)"})
_ERA_TAG = re.compile(r"_(?:Child|Adult(?:_Alternative)?)(?=_)")
_SUMMARY_PATH = Path(__file__).resolve().parents[2] / "chest_locations_summary.json"


@dataclass(frozen=True, slots=True)
class ChestSlot:
    """One physical chest; may appear in several era variants (Child/Adult) of a scene."""

    name: str
    vanilla_item: str
    room_index: int
    targets: tuple[tuple[str, int], ...]  # (scene_file, chest_order)
    scene: str = ""  # logic region key, e.g. "KokiriForest"

    @property
    def ages(self) -> frozenset[str]:
        """Ages whose scene variant contains this chest; 'both' for age-neutral files."""
        tags = set()
        for scene_file, _ in self.targets:
            tags.add("adult" if "_Adult" in scene_file else "child" if "_Child" in scene_file else "both")
        return frozenset(tags)


def load_chest_slots(summary: list[dict]) -> list[ChestSlot]:
    """Build unique chest slots, merging duplicate summary entries and Child/Adult copies."""
    files: dict[str, list[dict]] = {}
    for entry in summary:
        files.setdefault(Path(entry["scene_file"]).name, entry.get("chests", []))

    slots: dict[tuple[str, int, str, int], list[tuple[str, int]]] = {}
    for scene_file, chests in files.items():
        base = _ERA_TAG.sub("", scene_file)
        occurrence: dict[tuple[int, str], int] = {}
        for order, chest in enumerate(chests):
            room, drop = chest.get("room_index"), chest.get("vanilla_drop")
            if room is None or not drop:
                continue
            k = occurrence.get((room, drop), 0)
            occurrence[(room, drop)] = k + 1
            slots.setdefault((base, room, drop, k), []).append((scene_file, order))

    return [
        ChestSlot(
            name=f"{base.split('_')[0]} {base.split('.')[0].rsplit('_', 1)[-1]} room {room} #{k} ({drop})",
            vanilla_item=drop,
            room_index=room,
            targets=tuple(targets),
            scene=base.split("_")[0],
        )
        for (base, room, drop, k), targets in slots.items()
    ]


def shuffle_chest_items(seed: int | random.Random, slots: list[ChestSlot]) -> list[tuple[ChestSlot, str]]:
    """Permute the vanilla item pool across slots so every item appears exactly as often as vanilla."""
    rng = seed if isinstance(seed, random.Random) else random.Random(seed)
    shuffled = [s for s in slots if s.vanilla_item not in UNSHUFFLED_ITEMS and s.name not in NOT_IN_GAME_SLOTS]
    items = [s.vanilla_item for s in shuffled]
    rng.shuffle(items)
    assignment = dict(zip((id(s) for s in shuffled), items))
    return [(s, assignment.get(id(s), s.vanilla_item)) for s in slots]


def build_shuffle_patches(assignments: list[tuple[ChestSlot, str]]) -> list[PatchRecord]:
    patches: list[PatchRecord] = []
    for slot, item in assignments:
        if item == slot.vanilla_item:
            continue
        for scene_file, order in slot.targets:
            patches.append(
                PatchRecord(
                    location_name=slot.name,
                    scene=scene_file.split("_")[0],
                    check_type="chest",
                    check_index=-1,
                    vanilla_item=slot.vanilla_item,
                    replacement_item=item,
                    byte_offset=None,
                    item_id=_legacy_item_id(item),
                    scene_file=scene_file,
                    room_index=slot.room_index,
                    chest_order=order,
                )
            )
    return patches


def load_default_slots() -> list[ChestSlot]:
    if not _SUMMARY_PATH.exists():
        return []
    return load_chest_slots(load_summary_file(_SUMMARY_PATH))


@dataclass(frozen=True, slots=True)
class ItemPlacement:
    location: str
    region: str
    item: str
    required_items: tuple[str, ...]
    patch: PatchRecord


class SeedEngine:
    """Assigns a shuffled item pool to OoT locations and produces PatchRecords."""

    def __init__(self, logic: str = "glitchedless") -> None:
        self.logic = logic

    def _filtered_locations(self) -> list[OOTLocation]:
        summary_path = Path(__file__).resolve().parents[2] / "chest_locations_summary.json"
        if summary_path.exists():
            try:
                runtime_locations = build_runtime_locations(load_summary_file(summary_path))
                if runtime_locations:
                    return runtime_locations
            except (OSError, ValueError, KeyError, TypeError):
                pass
        return list(LOCATIONS)

    def generate(self, seed: int, item_pool: list[str], locations: list[OOTLocation] | None = None) -> list[ItemPlacement]:
        rng = random.Random(seed)
        ordered = list(locations) if locations is not None else self._filtered_locations()
        rng.shuffle(ordered)

        summary_path = Path(__file__).resolve().parents[2] / "chest_locations_summary.json"
        room_index_lookup: dict[str, tuple[int, str]] = {}
        if summary_path.exists():
            try:
                summary = load_summary_file(summary_path)
                for match in build_location_matches(summary):
                    room_index_lookup[match["location_name"]] = (
                        match["room_index"],
                        Path(match["scene_file"]).name,
                    )
            except (OSError, ValueError, KeyError, TypeError):
                pass

        placements: list[ItemPlacement] = []
        for idx, item in enumerate(item_pool):
            location = ordered[idx % len(ordered)]
            room_index, scene_file = room_index_lookup.get(location.name, (None, None))
            placements.append(
                ItemPlacement(
                    location=location.name,
                    region=location.region,
                    item=item,
                    required_items=location.required_items,
                    patch=make_patch(location, item, scene_file=scene_file, room_index=room_index),
                )
            )
        return placements
