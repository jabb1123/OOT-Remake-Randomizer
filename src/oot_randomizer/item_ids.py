"""OoT Remake (Switch 2) item actor name registry.

These are the Drop__DropActor string values used in bcett placement files,
confirmed by scanning all dungeon scene files from the actual game NUP.
Items are identified by actor string name, NOT by numeric byte IDs.
"""

from __future__ import annotations

# All confirmed Drop__DropActor strings found in Obj_TBox chest actors
# across all 160 bcett files in the game.
ITEM_ACTOR_NAMES: frozenset[str] = frozenset([
    # Major items
    "Item_Range_SlingShot",
    "Item_Range_Bow",
    "Item_Boomerang",
    "Item_Hookshot",
    "Item_Longshot",
    "Item_Arrow_Ice",
    "Item_GlassTruth",
    "Item_Hammer",
    "Item_HeavyBoot",
    "Item_HoverBoot",
    "Item_Gauntlet_Silver",
    "Item_Gauntlet_Gold",
    "Item_Shield_Mirror",
    "Item_Sword_Kokiri",
    "Item_BombBag_Small",
    # Dungeon items
    "Item_Dungeon_Map",
    "Item_Dungeon_Compass",
    "Item_Dungeon_SmallKey",
    "Item_Dungeon_BossKey",
    # Collectibles (chest-contained)
    "Obj_Heart_Piece",
    "TBox_Shield_Deku",
    "TBox_Shield_Hylian",
    "TBox_DekuNutBundle",
    "TBox_ArrowBundle_Medium",
    "TBox_ArrowBundle_Large",
    "TBox_Rupee_Green",
    "TBox_Rupee_Blue",
    "TBox_Rupee_Red",
    "TBox_Rupee_Purple",
    "TBox_Rupee_Gold",
    "Tbox_MagicJar_Large",
    "Item_BombBundle_Small",
    "Item_BombchuBundle_Small",
    "Item_DekuStickBundle_Small",
    "Item_ScrubBusinessSeed",
    # House of Skulltula rewards
    "Item_Wallet_Medium",
    "Item_Wallet_Large",
    "Item_AgonyStone",
    "Item_BombchuBundle_Large",
    "Item_Token_Gold",
])

# Human-readable display names for UI / manifests
ITEM_DISPLAY_NAMES: dict[str, str] = {
    "Item_Range_SlingShot":      "Fairy Slingshot",
    "Item_Range_Bow":            "Fairy Bow",
    "Item_Boomerang":            "Boomerang",
    "Item_Hookshot":             "Hookshot",
    "Item_Longshot":             "Longshot",
    "Item_Arrow_Ice":            "Ice Arrows",
    "Item_GlassTruth":           "Lens of Truth",
    "Item_Hammer":               "Megaton Hammer",
    "Item_HeavyBoot":            "Iron Boots",
    "Item_HoverBoot":            "Hover Boots",
    "Item_Gauntlet_Silver":      "Silver Gauntlets",
    "Item_Gauntlet_Gold":        "Golden Gauntlets",
    "Item_Shield_Mirror":        "Mirror Shield",
    "Item_Sword_Kokiri":         "Kokiri Sword",
    "Item_BombBag_Small":        "Bomb Bag",
    "Item_Dungeon_Map":          "Dungeon Map",
    "Item_Dungeon_Compass":      "Compass",
    "Item_Dungeon_SmallKey":     "Small Key",
    "Item_Dungeon_BossKey":      "Boss Key",
    "Obj_Heart_Piece":           "Heart Piece",
    "TBox_Shield_Deku":          "Deku Shield",
    "TBox_Shield_Hylian":        "Hylian Shield",
    "TBox_DekuNutBundle":        "Deku Nuts",
    "TBox_ArrowBundle_Medium":   "Arrows (30)",
    "TBox_ArrowBundle_Large":    "Arrows (50)",
    "TBox_Rupee_Green":          "Green Rupee",
    "TBox_Rupee_Blue":           "Blue Rupee",
    "TBox_Rupee_Red":            "Red Rupee",
    "TBox_Rupee_Purple":         "Purple Rupee",
    "TBox_Rupee_Gold":           "Gold Rupee",
    "Tbox_MagicJar_Large":       "Large Magic Jar",
    "Item_BombBundle_Small":     "Bombs",
    "Item_BombchuBundle_Small":  "Bombchus",
    "Item_DekuStickBundle_Small":"Deku Sticks",
    "Item_ScrubBusinessSeed":    "Business Scrub Item",
    "Item_Wallet_Medium":        "Adult's Wallet",
    "Item_Wallet_Large":         "Giant's Wallet",
    "Item_AgonyStone":           "Stone of Agony",
    "Item_BombchuBundle_Large":  "Bombchus (10)",
    "Item_Token_Gold":           "Gold Skulltula Token",
}

ITEM_ACTOR_BY_DISPLAY: dict[str, str] = {display: actor for actor, display in ITEM_DISPLAY_NAMES.items()}
ITEM_ACTOR_BY_DISPLAY.update({
    "Bow": "Item_Range_Bow",
    "Slingshot": "Item_Range_SlingShot",
    "Gold Skulltula Tokens": "Item_Token_Gold",
})


def resolve_actor_name(item_name: str) -> str:
    """Return the underlying Drop__DropActor string for a logical item label."""
    if item_name.startswith(("Item_", "Obj_", "TBox_", "Tbox_")):
        return item_name
    return ITEM_ACTOR_BY_DISPLAY.get(item_name, item_name)

# Major progression items (not consumables, not keys)
MAJOR_ITEM_ACTORS: frozenset[str] = frozenset([
    "Item_Range_SlingShot",
    "Item_Range_Bow",
    "Item_Boomerang",
    "Item_Hookshot",
    "Item_Longshot",
    "Item_Arrow_Ice",
    "Item_GlassTruth",
    "Item_Hammer",
    "Item_HeavyBoot",
    "Item_HoverBoot",
    "Item_Gauntlet_Silver",
    "Item_Gauntlet_Gold",
    "Item_Shield_Mirror",
    "Item_Sword_Kokiri",
    "Item_BombBag_Small",
])
