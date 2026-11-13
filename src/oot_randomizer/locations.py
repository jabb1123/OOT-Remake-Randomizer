"""OoT location database — logical check definitions independent of ROM format.

Each OOTLocation maps a named check to the scene it lives in, what type of check
it is, what item it normally holds, and what items are needed to reach it. Raw
byte offsets are resolved separately at patch time, once the NUP structure is known.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CheckType = Literal["chest", "npc", "collectable", "grotto", "boss", "song"]


@dataclass(frozen=True, slots=True)
class OOTLocation:
    name: str
    scene: str
    check_type: CheckType
    check_index: int        # actor/chest/NPC index within the scene
    vanilla_item: str
    region: str
    required_items: tuple[str, ...]


# ---------------------------------------------------------------------------
# Location table
# ---------------------------------------------------------------------------
# check_index is the logical index within the scene (chest 0, NPC 1, etc.).
# Actual byte addresses in the .nup are resolved by the patcher at runtime.

LOCATIONS: tuple[OOTLocation, ...] = (
    # --- Kokiri Forest / Overworld ---
    OOTLocation("Kokiri Forest Starting Chest",  "kokiri_forest",   "chest",      0, "Kokiri Sword",       "overworld",  ()),
    OOTLocation("Lost Woods Gift from Saria",    "lost_woods",      "npc",        0, "Fairy Ocarina",      "overworld",  ()),
    OOTLocation("Lost Woods Skull Kid Gift",     "lost_woods",      "npc",        1, "Heart Piece",        "overworld",  ("Deku Sticks",)),

    # --- Deku Tree ---
    OOTLocation("Deku Tree Map Chest",           "deku_tree",       "chest",      0, "Dungeon Map",        "dungeon",    ("Kokiri Sword", "Fairy Slingshot")),
    OOTLocation("Deku Tree Compass Chest",       "deku_tree",       "chest",      1, "Compass",            "dungeon",    ("Kokiri Sword", "Fairy Slingshot")),
    OOTLocation("Deku Tree Slingshot Chest",     "deku_tree",       "chest",      2, "Fairy Slingshot",    "dungeon",    ("Kokiri Sword",)),
    OOTLocation("Deku Tree Boss Key Chest",      "deku_tree",       "chest",      3, "Boss Key",           "dungeon",    ("Kokiri Sword", "Fairy Slingshot")),
    OOTLocation("Queen Gohma Heart Container",   "deku_tree",       "boss",       0, "Heart Container",    "dungeon",    ("Kokiri Sword", "Fairy Slingshot")),
    OOTLocation("Queen Gohma's Gift",            "deku_tree",       "npc",        0, "Kokiri's Emerald",   "dungeon",    ("Kokiri Sword", "Fairy Slingshot")),

    # --- Dodongo's Cavern ---
    OOTLocation("Dodongo's Cavern Map Chest",    "dodongos_cavern", "chest",      0, "Dungeon Map",        "dungeon",    ("Bomb Bag",)),
    OOTLocation("Dodongo's Cavern Compass Chest","dodongos_cavern", "chest",      1, "Compass",            "dungeon",    ("Bomb Bag",)),
    OOTLocation("Dodongo's Cavern Bomb Bag",     "dodongos_cavern", "chest",      2, "Bomb Bag",           "dungeon",    ()),
    OOTLocation("Dodongo's Cavern Boss Key",     "dodongos_cavern", "chest",      3, "Boss Key",           "dungeon",    ("Bomb Bag",)),
    OOTLocation("King Dodongo Heart Container",  "dodongos_cavern", "boss",       0, "Heart Container",    "dungeon",    ("Bomb Bag",)),
    OOTLocation("King Dodongo's Gift",           "dodongos_cavern", "npc",        0, "Goron's Ruby",       "dungeon",    ("Bomb Bag",)),

    # --- Jabu-Jabu's Belly ---
    OOTLocation("Jabu-Jabu Map Chest",           "jabu_jabu",       "chest",      0, "Dungeon Map",        "dungeon",    ("Empty Bottle",)),
    OOTLocation("Jabu-Jabu Compass Chest",       "jabu_jabu",       "chest",      1, "Compass",            "dungeon",    ("Empty Bottle",)),
    OOTLocation("Jabu-Jabu Boomerang Chest",     "jabu_jabu",       "chest",      2, "Boomerang",          "dungeon",    ("Empty Bottle",)),
    OOTLocation("Barinade Heart Container",      "jabu_jabu",       "boss",       0, "Heart Container",    "dungeon",    ("Empty Bottle", "Boomerang")),
    OOTLocation("Barinade's Gift",               "jabu_jabu",       "npc",        0, "Zora's Sapphire",    "dungeon",    ("Empty Bottle", "Boomerang")),

    # --- Forest Temple ---
    OOTLocation("Forest Temple Map Chest",       "forest_temple",   "chest",      0, "Dungeon Map",        "dungeon",    ("Hookshot",)),
    OOTLocation("Forest Temple Compass Chest",   "forest_temple",   "chest",      1, "Compass",            "dungeon",    ("Hookshot",)),
    OOTLocation("Forest Temple Bow Chest",       "forest_temple",   "chest",      2, "Bow",                "dungeon",    ("Hookshot",)),
    OOTLocation("Forest Temple Boss Key Chest",  "forest_temple",   "chest",      3, "Boss Key",           "dungeon",    ("Hookshot", "Bow")),
    OOTLocation("Phantom Ganon Heart Container", "forest_temple",   "boss",       0, "Heart Container",    "dungeon",    ("Hookshot", "Bow")),
    OOTLocation("Forest Medallion",              "forest_temple",   "npc",        0, "Forest Medallion",   "dungeon",    ("Hookshot", "Bow")),

    # --- Fire Temple ---
    OOTLocation("Fire Temple Map Chest",         "fire_temple",     "chest",      0, "Dungeon Map",        "dungeon",    ("Hookshot", "Goron Tunic")),
    OOTLocation("Fire Temple Compass Chest",     "fire_temple",     "chest",      1, "Compass",            "dungeon",    ("Hookshot", "Goron Tunic")),
    OOTLocation("Fire Temple Megaton Hammer",    "fire_temple",     "chest",      2, "Megaton Hammer",     "dungeon",    ("Hookshot", "Goron Tunic")),
    OOTLocation("Fire Temple Boss Key Chest",    "fire_temple",     "chest",      3, "Boss Key",           "dungeon",    ("Hookshot", "Goron Tunic", "Megaton Hammer")),
    OOTLocation("Volvagia Heart Container",      "fire_temple",     "boss",       0, "Heart Container",    "dungeon",    ("Hookshot", "Goron Tunic", "Megaton Hammer")),
    OOTLocation("Fire Medallion",                "fire_temple",     "npc",        0, "Fire Medallion",     "dungeon",    ("Hookshot", "Goron Tunic", "Megaton Hammer")),

    # --- Water Temple ---
    OOTLocation("Water Temple Map Chest",        "water_temple",    "chest",      0, "Dungeon Map",        "dungeon",    ("Hookshot", "Iron Boots", "Zora Tunic")),
    OOTLocation("Water Temple Compass Chest",    "water_temple",    "chest",      1, "Compass",            "dungeon",    ("Hookshot", "Iron Boots", "Zora Tunic")),
    OOTLocation("Water Temple Longshot Chest",   "water_temple",    "chest",      2, "Longshot",           "dungeon",    ("Hookshot", "Iron Boots", "Zora Tunic")),
    OOTLocation("Water Temple Boss Key Chest",   "water_temple",    "chest",      3, "Boss Key",           "dungeon",    ("Longshot", "Iron Boots", "Zora Tunic")),
    OOTLocation("Morpha Heart Container",        "water_temple",    "boss",       0, "Heart Container",    "dungeon",    ("Longshot", "Iron Boots", "Zora Tunic")),
    OOTLocation("Water Medallion",               "water_temple",    "npc",        0, "Water Medallion",    "dungeon",    ("Longshot", "Iron Boots", "Zora Tunic")),

    # --- Shadow Temple ---
    OOTLocation("Shadow Temple Map Chest",       "shadow_temple",   "chest",      0, "Dungeon Map",        "dungeon",    ("Hookshot", "Lens of Truth")),
    OOTLocation("Shadow Temple Compass Chest",   "shadow_temple",   "chest",      1, "Compass",            "dungeon",    ("Hookshot", "Lens of Truth")),
    OOTLocation("Shadow Temple Hover Boots",     "shadow_temple",   "chest",      2, "Hover Boots",        "dungeon",    ("Hookshot", "Lens of Truth")),
    OOTLocation("Shadow Temple Boss Key Chest",  "shadow_temple",   "chest",      3, "Boss Key",           "dungeon",    ("Hookshot", "Lens of Truth", "Hover Boots")),
    OOTLocation("Bongo Bongo Heart Container",   "shadow_temple",   "boss",       0, "Heart Container",    "dungeon",    ("Hookshot", "Lens of Truth", "Hover Boots")),
    OOTLocation("Shadow Medallion",              "shadow_temple",   "npc",        0, "Shadow Medallion",   "dungeon",    ("Hookshot", "Lens of Truth", "Hover Boots")),

    # --- Spirit Temple ---
    OOTLocation("Spirit Temple Map Chest",       "spirit_temple",   "chest",      0, "Dungeon Map",        "dungeon",    ("Magic Bean",)),
    OOTLocation("Spirit Temple Compass Chest",   "spirit_temple",   "chest",      1, "Compass",            "dungeon",    ("Magic Bean", "Hookshot")),
    OOTLocation("Spirit Temple Silver Gauntlets","spirit_temple",   "chest",      2, "Mirror Shield",      "dungeon",    ("Magic Bean", "Hookshot")),
    OOTLocation("Spirit Temple Boss Key Chest",  "spirit_temple",   "chest",      3, "Boss Key",           "dungeon",    ("Magic Bean", "Hookshot", "Light Arrows")),
    OOTLocation("Twinrova Heart Container",      "spirit_temple",   "boss",       0, "Heart Container",    "dungeon",    ("Magic Bean", "Hookshot", "Light Arrows")),
    OOTLocation("Spirit Medallion",              "spirit_temple",   "npc",        0, "Spirit Medallion",   "dungeon",    ("Magic Bean", "Hookshot", "Light Arrows")),

    # --- Ganon's Castle ---
    OOTLocation("Ganon's Tower Boss Key Chest",  "ganons_castle",   "chest",      0, "Boss Key",           "dungeon",    ("Light Arrows", "Master Sword")),
    OOTLocation("Ganondorf Heart Container",     "ganons_castle",   "boss",       0, "Heart Container",    "dungeon",    ("Light Arrows", "Master Sword")),

    # --- Songs ---
    OOTLocation("Song of Time",                  "temple_of_time",  "song",       0, "Ocarina of Time",    "overworld",  ("Master Sword",)),
    OOTLocation("Saria's Song",                  "sacred_forest",   "song",       0, "Fairy Ocarina",      "overworld",  ()),
    OOTLocation("Epona's Song",                  "lon_lon_ranch",   "song",       0, "Fairy Ocarina",      "overworld",  ()),
    OOTLocation("Zelda's Lullaby",               "hyrule_castle",   "song",       0, "Fairy Ocarina",      "overworld",  ()),
    OOTLocation("Sun's Song",                    "royal_tomb",      "song",       0, "Fairy Ocarina",      "overworld",  ()),
    OOTLocation("Song of Storms",                "windmill",        "song",       0, "Fairy Ocarina",      "overworld",  ("Master Sword",)),
    OOTLocation("Minuet of Forest",              "sacred_forest_m", "song",       1, "Fairy Ocarina",      "overworld",  ()),
    OOTLocation("Bolero of Fire",                "death_mountain",  "song",       1, "Fairy Ocarina",      "overworld",  ("Master Sword",)),
    OOTLocation("Serenade of Water",             "lake_hylia",      "song",       1, "Fairy Ocarina",      "overworld",  ("Master Sword",)),
    OOTLocation("Requiem of Spirit",             "desert_colossus", "song",       1, "Fairy Ocarina",      "overworld",  ("Master Sword",)),
    OOTLocation("Nocturne of Shadow",            "kakariko_village","song",       1, "Fairy Ocarina",      "overworld",  ("Master Sword", "Shadow Medallion")),
    OOTLocation("Prelude of Light",              "temple_of_time",  "song",       1, "Fairy Ocarina",      "overworld",  ("Master Sword",)),
)

# Quick lookup by name
LOCATION_BY_NAME: dict[str, OOTLocation] = {loc.name: loc for loc in LOCATIONS}
