"""Normalize raw chest scan data from the main NUP into canonical randomizer locations."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from .locations import LOCATION_BY_NAME, LOCATIONS, OOTLocation


def normalize_scene_name(scene_file: str) -> str:
    """Convert a raw banc path like 'Banc/InsideTheDekuTree/...' to the logical scene key."""
    name = PurePosixPath(scene_file).name
    stem = name.rsplit(".bcett.byml.zs", 1)[0]
    variant = ""

    if stem.endswith("_Dynamic"):
        stem = stem[:-8]
    if stem.endswith("_Static"):
        stem = stem[:-7]
    if stem.endswith("_Alternative"):
        stem = stem[:-12]

    if stem.endswith("_Adult"):
        variant = "_adult"
        stem = stem[:-6]
    elif stem.endswith("_Child"):
        variant = "_child"
        stem = stem[:-6]

    # Match the logical scene naming convention used in the project.
    replacements = {
        "InsideTheDekuTree": "deku_tree",
        "DodongoCavern": "dodongos_cavern",
        "InsideJabuJabuBelly": "jabu_jabu",
        "ForestTemple": "forest_temple",
        "FireTemple": "fire_temple",
        "WaterTemple": "water_temple",
        "ShadowTemple": "shadow_temple",
        "SpiritTemple": "spirit_temple",
        "BottomOfTheWell": "bottom_of_the_well",
        "GerudoFortress": "gerudo_fortress",
        "GerudoValley": "gerudo_valley",
        "GoronCity": "goron_city",
        "KakarikoVillage": "kakariko_village",
        "KokiriForest": "kokiri_forest",
        "LostWood": "lost_woods",
        "Market": "market",
        "SacredForestMeadow": "sacred_forest_meadow",
        "HyruleCastle": "hyrule_castle",
        "HyruleField": "hyrule_field",
        "Graveyard": "graveyard",
        "HountedWasteland": "hounted_wasteland",
        "IceCavern": "ice_cavern",
        "InsideGanonCastle": "inside_ganon_castle",
        "GanonCastle": "ganons_castle",
        "DeathMountainCrater": "death_mountain_crater",
        "DeathMountainTrail": "death_mountain_trail",
        "DesertColossus": "desert_colossus",
        "ZoraDomain": "zora_domain",
        "ZoraFountain": "zora_fountain",
        "ZoraRiver": "zora_river",
        "SageRoom": "sage_room",
    }

    for source, target in replacements.items():
        if stem.startswith(source):
            return f"{target}{variant}"

    if "FinalBattleField" in stem:
        return f"ganons_castle{variant}"
    if "Crumbling" in stem:
        return f"ganons_castle{variant}"
    if stem.startswith("Demo_"):
        return f"kokiri_forest{variant}"

    return f"{stem.lower().replace(' ', '_')}{variant}"


def build_canonical_locations(summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn raw scan output into canonical chest records.

    Each record has:
      - scene: canonical scene key
      - room_index: room index from byml
      - check_index: index within the scene's treasure list
      - vanilla_item: item string name
      - scene_file: original path
      - gyaml: chest actor type
    """
    records: list[dict[str, Any]] = []
    for entry in summary:
        scene_file = entry.get("scene_file", "")
        scene = normalize_scene_name(scene_file)
        for idx, chest in enumerate(entry.get("chests", [])):
            records.append(
                {
                    "scene": scene,
                    "scene_file": scene_file,
                    "room_index": chest.get("room_index", 0),
                    "check_index": idx,
                    "vanilla_item": chest.get("vanilla_drop", ""),
                    "gyaml": chest.get("gyaml", ""),
                    "str_table_index": chest.get("str_table_index", -1),
                }
            )

    return records


def build_location_matches(
    summary: list[dict[str, Any]],
    locations: list[OOTLocation] | None = None,
) -> list[dict[str, Any]]:
    """Link each raw chest record to its logical OOTLocation by scene and room ordering."""
    location_list = list(locations) if locations is not None else list(LOCATIONS)
    scene_lookup: dict[str, list[OOTLocation]] = {}
    for location in location_list:
        scene_lookup.setdefault(location.scene, []).append(location)

    matches: list[dict[str, Any]] = []
    for entry in summary:
        scene_file = entry.get("scene_file", "")
        scene = normalize_scene_name(scene_file)
        scene_locations = [loc for loc in scene_lookup.get(scene, []) if loc.check_type == "chest"]
        chest_rows = sorted(
            entry.get("chests", []),
            key=lambda row: (row.get("room_index", 0), row.get("str_table_index", -1), row.get("vanilla_drop", "")),
        )
        limit = min(len(scene_locations), len(chest_rows))
        for index in range(limit):
            row = chest_rows[index]
            location = scene_locations[index]
            matches.append(
                {
                    "scene": scene,
                    "location_name": location.name,
                    "scene_file": scene_file,
                    "check_type": location.check_type,
                    "check_index": location.check_index,
                    "room_index": row.get("room_index", 0),
                    "gyaml": row.get("gyaml", ""),
                    "raw_item": row.get("vanilla_drop", ""),
                    "expected_item": location.vanilla_item,
                    "region": location.region,
                }
            )

    return matches


def load_summary_file(path: str | Path) -> list[dict[str, Any]]:
    """Load a chest scan summary exported from the main NUP archive."""
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("Chest summary JSON must be a list of scene entries.")
    return data


def build_location_index(
    summary: list[dict[str, Any]],
    locations: list[OOTLocation] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Group matched location records by canonical scene name for downstream patch generation."""
    matches = build_location_matches(summary, locations)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in matches:
        grouped.setdefault(item["scene"], []).append(item)
    return grouped


def build_runtime_locations(summary: list[dict[str, Any]]) -> list[OOTLocation]:
    """Resolve the actual chest summary into canonical OOTLocation objects in room-scan order."""
    runtime: list[OOTLocation] = []
    seen: set[str] = set()
    for match in build_location_matches(summary):
        location_name = match["location_name"]
        if location_name in seen:
            continue
        location = LOCATION_BY_NAME.get(location_name)
        if location is None:
            continue
        runtime.append(location)
        seen.add(location_name)
    return runtime


def build_scene_file_index(summary: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Map each logical scene key to the real scene file names seen in the main NUP summary."""
    grouped: dict[str, list[str]] = {}
    for entry in summary:
        scene_file = entry.get("scene_file", "")
        if not scene_file:
            continue
        scene = normalize_scene_name(scene_file)
        grouped.setdefault(scene, []).append(scene_file)
    return {scene: list(dict.fromkeys(paths)) for scene, paths in grouped.items()}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Normalize raw chest summaries into canonical scene-location records.")
    parser.add_argument("summary", type=str, help="Path to a chest_locations_summary.json file")
    args = parser.parse_args()

    summary = load_summary_file(args.summary)
    matches = build_location_matches(summary)
    print(f"matched {len(matches)} chest records")
    for scene, rows in build_location_index(summary).items():
        print(f"{scene}: {len(rows)}")
