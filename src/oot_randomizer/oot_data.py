"""Static OoT Remake (Switch 2) data — actor names confirmed from the game NUP."""

from __future__ import annotations

from .item_ids import ITEM_ACTOR_NAMES, MAJOR_ITEM_ACTORS

# Major progression items available for randomization (confirmed actor names)
MAJOR_ITEMS: list[str] = sorted(MAJOR_ITEM_ACTORS)

# Dungeon order pool (scene identifiers matching bcett file naming)
DUNGEON_ITEMS: list[str] = [
    "InsideTheDekuTree",
    "DodongoCavern",
    "InsideJabuJabuBelly",
    "ForestTemple",
    "FireTemple",
    "WaterTemple",
    "ShadowTemple",
    "SpiritTemple",
    "GanonCastle",
]

LOGIC_PRESETS = {
    "glitchedless": "No major glitches required.",
    "casual": "Light logic with a few convenience assumptions.",
    "all_locations": "All item locations are considered reachable.",
}

GOAL_PRESETS = {
    "ganon": "Defeat Ganon.",
    "triforce_hunt": "Collect the Triforce pieces.",
}
