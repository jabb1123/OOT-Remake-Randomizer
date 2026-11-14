"""Generate a single-file starter world logic from the real chest and song locations.

The shipped logic lives in logic/world/ (one file per area); a single file like this one
loads the same way and can be passed with --logic-file.
"""

from __future__ import annotations

import json
from collections import defaultdict

from .engine import NOT_IN_GAME_SLOTS, ChestSlot
from .event_items import EVENT_ITEM_DISPLAY_NAMES, EVENT_SLOTS, event_location_name
from .item_ids import ITEM_DISPLAY_NAMES
from .npc_grants import NPC_ITEM_DISPLAY_NAMES, npc_location_name
from .skulltula_rewards import SKULL_REWARDS, skull_location_name
from .songs import SONG_DISPLAY_NAMES, SONG_SLOTS, song_location_name

OVERWORLD = "is_adult or Deku_Tree_Clear"
ALL_MEDALLIONS = (
    "Forest_Temple_Clear and Fire_Temple_Clear and Water_Temple_Clear "
    "and Shadow_Temple_Clear and Spirit_Temple_Clear"
)

# Root exit rule per scene region. Scenes not listed use OVERWORLD.
SCENE_ENTRY: dict[str, str] = {
    "KokiriForest": "true",
    "LostWood": "true",
    "SacredForestMeadow": "true",
    "InsideTheDekuTree": "is_child and Kokiri_Sword",
    "DodongoCavern": (
        "(is_adult or Deku_Tree_Clear) and "
        "(Bomb_Bag or (bombchus_in_logic and Bombchus) or (Zeldas_Lullaby and Sarias_Song))"
    ),
    "ZoraDomain": "(is_adult or Deku_Tree_Clear) and Zeldas_Lullaby",
    "ZoraFountain": "(is_adult or Deku_Tree_Clear) and Zeldas_Lullaby",
    "InsideJabuJabuBelly": "is_child and Deku_Tree_Clear and Zeldas_Lullaby",
    "HyruleCastle": "is_child and Deku_Tree_Clear",
    "BottomOfTheWell": "is_child and Deku_Tree_Clear and Song_of_Storms",
    "IceCavern": "is_adult and Zeldas_Lullaby",
    "ForestTemple": "is_adult and Hookshot",
    "FireTemple": "is_adult",
    "WaterTemple": "is_adult and Zeldas_Lullaby and Iron_Boots and Hookshot",
    "ShadowTemple": "is_adult and Nocturne_of_Shadow and Lens_of_Truth",
    "GerudoFortress": "is_adult and (Longshot or Eponas_Song)",
    "GerudoTrainingGround": "is_adult and (Longshot or Eponas_Song)",
    "HountedWasteland": "is_adult and (Longshot or Eponas_Song)",
    "DesertColossus": "Requiem_of_Spirit or (is_adult and (Longshot or Eponas_Song) and (Longshot or Hover_Boots))",
    "SpiritTemple": "Requiem_of_Spirit or (is_adult and (Longshot or Eponas_Song) and (Longshot or Hover_Boots))",
    "InsideGanonCastle": f"is_adult and {ALL_MEDALLIONS}",
    "BossRushIntervalRoom": "true",
}

DUNGEONS = frozenset(
    {
        "InsideTheDekuTree",
        "DodongoCavern",
        "InsideJabuJabuBelly",
        "ForestTemple",
        "FireTemple",
        "WaterTemple",
        "ShadowTemple",
        "SpiritTemple",
        "BottomOfTheWell",
        "IceCavern",
        "GerudoTrainingGround",
        "InsideGanonCastle",
    }
)
# Unknown remake-only area; chests here keep their vanilla items until confirmed reachable.
EXCLUDED = frozenset({"BossRushIntervalRoom"})

EVENTS: dict[str, dict[str, str]] = {
    "InsideTheDekuTree": {"Deku_Tree_Clear": "is_child and Kokiri_Sword and Slingshot"},
    "DodongoCavern": {
        "Dodongos_Cavern_Clear": "is_child and (Bomb_Bag or (Zeldas_Lullaby and Sarias_Song))"
    },
    "InsideJabuJabuBelly": {"Jabu_Jabu_Clear": "is_child and Boomerang"},
    "TempleOfTime": {
        "Time_Travel": "is_child and Song_of_Time and Deku_Tree_Clear and Dodongos_Cavern_Clear and Jabu_Jabu_Clear",
    },
    "ForestTemple": {"Forest_Temple_Clear": "Bow"},
    "FireTemple": {"Fire_Temple_Clear": "Megaton_Hammer"},
    "WaterTemple": {"Water_Temple_Clear": "Longshot"},
    "ShadowTemple": {"Shadow_Temple_Clear": "Hover_Boots and Bow"},
    "SpiritTemple": {
        "Spirit_Temple_Clear": "is_adult and Silver_Gauntlets and Mirror_Shield and Hookshot"
    },
    "InsideGanonCastle": {"Ganon_Defeated": "Bow"},
    "IceCavern": {"Ice_Cavern_Clear": "is_adult and Zeldas_Lullaby"},
}

# Region holding the House of Skulltula reward locations.
SKULL_REGION = "KakarikoVillage"

# flow file -> (region, requirement, who teaches it in vanilla)
SONG_LOCATIONS: dict[str, tuple[str, str, str]] = {
    "Dm_MelodyGet_Zelda.bfevfl.zs": (
        "HyruleCastle",
        "is_child",
        "Impa, Hyrule Castle courtyard",
    ),
    "Dm_MelodyGet_Saria.bfevfl.zs": (
        "SacredForestMeadow",
        "is_child",
        "Saria, Sacred Forest Meadow",
    ),
    # The remake's Epona flow checks the Fire and Water stones; Water needs Zora's Domain.
    "Dm_MelodyGet_Epona.bfevfl.zs": (
        "LonLonRanch",
        "is_child and Zeldas_Lullaby",
        "Malon, Lon Lon Ranch",
    ),
    "Dm_MelodyGet_Sun_03.bfevfl.zs": (
        "Graveyard",
        "is_child and Zeldas_Lullaby",
        "Royal Tomb",
    ),
    "Dm_MelodyGet_Time.bfevfl.zs": (
        "HyruleField",
        "is_child and Zeldas_Lullaby and Deku_Tree_Clear and Dodongos_Cavern_Clear and Jabu_Jabu_Clear",
        "Zelda at the moat, after all three stones",
    ),
    "Dm_MelodyGet_Storm.bfevfl.zs": ("KakarikoVillage", "is_adult", "Windmill"),
    "Dm_MelodyGet_Forest.bfevfl.zs": (
        "SacredForestMeadow",
        "is_adult",
        "Sheik, Sacred Forest Meadow",
    ),
    "Dm_MelodyGet_Fire.bfevfl.zs": (
        "DeathMountainCrater",
        "is_adult",
        "Sheik, Death Mountain Crater",
    ),
    "Dm_MelodyGet_Water.bfevfl.zs": ("IceCavern", "is_adult", "Sheik, Ice Cavern"),
    "Dm_MelodyGet_Spilit.bfevfl.zs": (
        "DesertColossus",
        "is_adult",
        "Sheik, Desert Colossus",
    ),
    "Dm_MelodyGet_Shadow.bfevfl.zs": (
        "KakarikoVillage",
        "is_adult and Forest_Temple_Clear and Fire_Temple_Clear and Water_Temple_Clear",
        "Sheik, Kakariko",
    ),
    "Dm_MelodyGet_Shine.bfevfl.zs": (
        "TempleOfTime",
        "is_adult and Forest_Temple_Clear",
        "Sheik, Temple of Time",
    ),
}

# flow file -> (region, requirement, where the item is granted in vanilla)
EVENT_LOCATIONS: dict[str, tuple[str, str, str]] = {
    "Dm_Awake_Forest_Get.bfevfl.zs": (
        "ForestTemple",
        "Forest_Temple_Clear",
        "Forest Temple",
    ),
    "Dm_Awake_Fire_Get.bfevfl.zs": ("FireTemple", "Fire_Temple_Clear", "Fire Temple"),
    "Dm_Awake_Water_Get.bfevfl.zs": (
        "WaterTemple",
        "Water_Temple_Clear",
        "Water Temple",
    ),
    "Dm_Awake_Shadow_Get.bfevfl.zs": (
        "ShadowTemple",
        "Shadow_Temple_Clear",
        "Shadow Temple",
    ),
    "Dm_Awake_Spirit_Get.bfevfl.zs": (
        "SpiritTemple",
        "Spirit_Temple_Clear",
        "Spirit Temple",
    ),
    "Dm_Kokiri_0130.bfevfl.zs": ("InsideTheDekuTree", "Deku_Tree_Clear", "Deku Tree"),
    "Dm_DeathMtTrail_0025.bfevfl.zs": (
        "DeathMountainTrail",
        "Dodongos_Cavern_Clear",
        "Darunia",
    ),
    "Dm_ZoraFountain_0030.bfevfl.zs": (
        "ZoraFountain",
        "Jabu_Jabu_Clear",
        "Ruto",
    ),
    "Dm_Kokiri_0155.bfevfl.zs": ("LostWood", "is_child", "Saria, Lost Woods"),
    "Dm_MelodyGet_Time.bfevfl.zs": (
        "HyruleField",
        "is_child and Zeldas_Lullaby and Deku_Tree_Clear and Dodongos_Cavern_Clear and Jabu_Jabu_Clear",
        "Zelda at the moat, after all three stones",
    ),
}

# (flow file, vanilla item) -> (region, requirement, who grants it in vanilla); mirrors npc_grants.py
NPC_LOCATIONS: dict[tuple[str, str, str | None], tuple[str, str, str]] = {
    ("MiniGame_HitTarget.bfevfl.zs", "Item_BulletBag_Large", None): (
        "Market",
        "is_child and Slingshot",
        "Shooting Gallery, Market (2nd bullet bag upgrade)",
    ),
    ("MiniGame_HitTarget.bfevfl.zs", "Item_Quiver_Medium", None): (
        "KakarikoVillage",
        "is_adult and Bow",
        "Shooting Gallery, Kakariko",
    ),
    ("MiniGame_BombchuBowling.bfevfl.zs", "Item_BombBag_Medium", None): (
        "Market",
        "Bomb_Bag",
        "Bombchu Bowling",
    ),
    ("MiniGame_BombchuBowling.bfevfl.zs", "Item_BombBag_Large", None): (
        "Market",
        "Bomb_Bag and Bomb_Bag_Medium",
        "Bombchu Bowling",
    ),
    ("MiniGame_BombchuBowling.bfevfl.zs", "Item_BombchuBundle_Medium", None): (
        "Market",
        "true",
        "Bombchu Bowling",
    ),
    ("MiniGame_Fishing.bfevfl.zs", "Item_Scale_Gold", None): (
        "LakeHylia",
        "true",
        "Fishing Pond",
    ),
    ("MiniGame_Fishing.bfevfl.zs", "Obj_Heart_Piece", None): (
        "LakeHylia",
        "true",
        "Fishing Pond",
    ),
    ("MiniGame_Diving.bfevfl.zs", "Item_Scale_Silver", None): (
        "ZoraDomain",
        "true",
        "Diving Minigame",
    ),
    ("Minigame_HorsebackArchery.bfevfl.zs", "Item_Quiver_Large", None): (
        "GerudoFortress",
        "is_adult and Bow",
        "Horseback Archery",
    ),
    (
        "LostWood_ScrubForestStageElder_SkullMaskFirst.bfevfl.zs",
        "Item_StickBag_Medium",
        None,
    ): ("LostWood", "is_child and Deku_Sticks", "Lost Woods Scrub Elder, Skull Mask"),
    (
        "LostWood_ScrubForestStageElder_SkullMaskFirst.bfevfl.zs",
        "Item_StickBag_Large",
        None,
    ): (
        "LostWood",
        "is_child and Deku_Sticks and Stick_Bag_Medium",
        "Lost Woods Scrub Elder, Skull Mask",
    ),
    (
        "LostWood_ScrubForestStageElder_TrueMaskFirst.bfevfl.zs",
        "Item_NutBag_Medium",
        None,
    ): (
        "LostWood",
        "is_child and Deku_Nuts",
        "Lost Woods Scrub Elder, True Mask",
    ),
    (
        "LostWood_ScrubForestStageElder_TrueMaskFirst.bfevfl.zs",
        "Item_NutBag_Large",
        None,
    ): (
        "LostWood",
        "is_child and Deku_Nuts and Nut_Bag_Medium",
        "Lost Woods Scrub Elder, True Mask",
    ),
    ("Enemy_Scrub_Business_Common.bfevfl.zs", "Item_StickBag_Large", None): (
        "LostWood",
        "is_child and Deku_Sticks",
        "Lost Woods Business Scrub, Deku Stick bag",
    ),
    ("Enemy_Scrub_Business_Common.bfevfl.zs", "Item_NutBag_Large", None): (
        "LostWood",
        "is_child and Deku_Nuts and Bomb_Bag",
        "Lost Woods Business Scrub, Deku Nut bag",
    ),
    ("Dm_LostWood_0040.bfevfl.zs", "Item_BulletBag_Medium", None): (
        "LostWood",
        "is_child and Slingshot",
        "Lost Woods scrub target (1st bullet bag upgrade)",
    ),
    ("Npc_Goron_Biggoron_Adult.bfevfl.zs", "Item_Sword_Biggoron", None): (
        "DeathMountainTrail",
        "is_adult and Ice_Cavern_Clear and (Eponas_Song or Longshot) and (Bomb_Bag or Megaton_Hammer)",
        "Biggoron, Death Mountain Trail",
    ),
    ("SubEvent_FindRichard.bfevfl.zs", "Obj_Heart_Piece", None): (
        "Market",
        "is_child and Alarm_Cucco",
        "Mamamu Yan, after finding Richard",
    ),
    ("Npc_SkullKid_Child_02.bfevfl.zs", "Obj_Heart_Piece", None): (
        "LostWood",
        "is_child and (Fairy_Ocarina or Ocarina_of_Time)",
        "Skullkid, on playing game 3 times",
    ),
    ("Dm_Goron_0030.bfevfl.zs", "Item_Gauntlet_Goron", None): (
        "GoronCity",
        "is_child and Zeldas_Lullaby and Sarias_Song",
        "Darunia, after Goron dance",
    ),
    ("Goto_HyruleCastle.bfevfl.zs", "Item_WeirdEgg", None): (
        "HyruleCastle",
        "is_child",
        "Malon, given as egg",
    ),
    ("Dm_HrlCastle_0050.bfevfl.zs", "Item_ZeldaLetter", None): (
        "HyruleCastle",
        "is_child and Alarm_Cucco",
        "Zelda, after speech",
    ),
    ("Npc_Hylia_001_Adult.bfevfl.zs", "Obj_Heart_Piece", None): (
        "KakarikoVillage",
        "is_adult and has_hookshot",
        "Man on a roof, as an adult",
    ),
    ("Npc_Hylia_045_Child.bfevfl.zs", "Obj_Heart_Piece", None): (
        "KakarikoVillage",
        "is_child",
        "Man on a roof, as a kid",
    ),
    ("MiniGame_FrogTenors.bfevfl.zs", "Obj_Heart_Piece", "song of storms"): (
        "ZoraRiver",
        "is_child and Song_of_Storms",
        "Frog Choir, Song of Storms in the minigame",
    ),
    ("MiniGame_FrogTenors.bfevfl.zs", "Obj_Heart_Piece", "insect repellent"): (
        "ZoraRiver",
        "is_child and Zeldas_Lullaby and Sarias_Song and Eponas_Song and Suns_Song and Song_of_Time",
        "Frog Choir, insect repellent game",
    ),
    ("Dm_FairyFountain_Din.bfevfl.zs", "Item_DinFire", None): (
        "DeathMountainTrail",
        "Bomb_Bag and (Goron_Bracelet or Silver_Gauntlets or Golden_Gauntlets) and can_play(Zeldas_Lullaby)",
        "Great Fairy for 25 rupees",
    ),
    ("Dm_FairyFountain_Frore.bfevfl.zs", "Item_FaroreWind", None): (
        "ZoraFountain",
        "has_explosives and can_play(Zeldas_Lullaby)"
        "Great Fairy for 100 rupees",
    ),
    ("Dm_FairyFountain_Nayru.bfevfl.zs", "Item_NayruLove", None): (
        "DesertColossus",
        "(has_explosives or (Megaton_Hammer and is_adult)) and can_play(Zeldas_Lullaby)"
        "Great Fairy for 300 rupees",
    ), 
    ("Dm_FairyFountain_Power.bfevfl.zs", "Item_FairyBless_MP", None): (
        "HyruleCastle",
        "has_explosives and is_child and can_play(Zeldas_Lullaby)",
        "Great Fairy for 50 rupees",
    ),
    ("Dm_FairyFountain_Wisdom.bfevfl.zs", "Item_FairyBless_MPDouble", None): (
        "DeathMountainCrater",
        "Megaton_Hammer and is_adult and can_play(Zeldas_Lullaby)",
        "Great Fairy for 200 rupees",
    ),
    ("Dm_FairyFountain_Courage.bfevfl.zs", "Item_FairyBless_DefenseDouble", None): (
        "OutsideGanonCastle",
        "Golden_Gauntlets and can_play(Zeldas_Lullaby)",
        "Great Fairy for 500 rupees",
    ),
}

HEADER = """\
# Ocarina of Time remake world logic.
#
# Each region lists:
#   [regions.X.exits]      other regions you can walk to, and what that takes
#   [regions.X.locations]  chests / song spots in the region, and what opening them takes
#   [regions.X.skulltulas] Gold Skulltulas in the region (always hold a token) and what reaching them takes
#   [regions.X.events]     story milestones (boss beaten, door opened) other rules can require
#   dungeon = true         counts for "one major item per dungeon"
#   excluded = true        chests here keep their vanilla item
#
# Requirements use item names joined by `and` / `or` with parentheses, e.g.
#   "Hookshot and (Bow or Slingshot)".  Also available: is_child, is_adult, true, false,
#   event names, `Item:N` for counts, and the option bombchus_in_logic.
# Until skulltulas are listed, every Gold Skulltula token counts as already collected.
# Items accept friendly names (Hookshot, Bow, Zeldas_Lullaby) or actor names (Item_Range_Bow).
#
# Starter rules below are simplified vanilla Ocarina of Time requirements; refine as needed.
# Locations left as "true" only need their region to be reachable.
"""


def _q(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def build_template(slots: list[ChestSlot]) -> str:
    chest_by_region: dict[str, list[ChestSlot]] = defaultdict(list)
    for slot in slots:
        if slot.name not in NOT_IN_GAME_SLOTS:
            chest_by_region[slot.scene].append(slot)
    songs_by_region: dict[str, list[str]] = defaultdict(list)
    for flow, (region, _, _) in SONG_LOCATIONS.items():
        songs_by_region[region].append(flow)
    events_by_region: dict[str, list[str]] = defaultdict(list)
    for flow, (region, _, _) in EVENT_LOCATIONS.items():
        events_by_region[region].append(flow)
    npc_by_region: dict[str, list[tuple[str, str, str | None]]] = defaultdict(list)
    for key, (region, _, _) in NPC_LOCATIONS.items():
        npc_by_region[region].append(key)
    region_names = sorted(
        set(chest_by_region)
        | set(songs_by_region)
        | set(events_by_region)
        | set(EVENTS)
        | set(npc_by_region)
        | {SKULL_REGION}
    )

    lines = [HEADER, "[settings]"]
    lines += [
        'start_age = "child"',
        'child_spawn = "Root"',
        'adult_spawn = "Root"',
        "# Event that unlocks playing as the other age (Door of Time / Master Sword).",
        'time_travel = "Time_Travel"',
        'goal = "Ganon_Defeated"',
        "start_items = []",
        "",
        "[regions.Root.exits]",
    ]
    lines += [
        f"{_q(name)} = {_q(SCENE_ENTRY.get(name, OVERWORLD))}" for name in region_names
    ]

    for name in region_names:
        lines += ["", f"[regions.{_q(name)}]"]
        if name in DUNGEONS:
            lines.append("dungeon = true")
        if name in EXCLUDED:
            lines.append("excluded = true")
        if name in EVENTS:
            lines += ["", f"[regions.{_q(name)}.events]"]
            lines += [f"{_q(ev)} = {_q(req)}" for ev, req in EVENTS[name].items()]
        entries = []
        for flow in songs_by_region.get(name, []):
            _, req, who = SONG_LOCATIONS[flow]
            vanilla = SONG_DISPLAY_NAMES[SONG_SLOTS[flow]]
            entries.append(
                f"{_q(song_location_name(flow))} = {_q(req)}  # song: {vanilla} from {who}"
            )
        for flow in events_by_region.get(name, []):
            _, req, who = EVENT_LOCATIONS[flow]
            vanilla = EVENT_ITEM_DISPLAY_NAMES[EVENT_SLOTS[flow]]
            entries.append(
                f"{_q(event_location_name(flow))} = {_q(req)}  # event item: {vanilla} from {who}"
            )
        for flow, item, label in npc_by_region.get(name, []):
            _, req, who = NPC_LOCATIONS[(flow, item, label)]
            vanilla = NPC_ITEM_DISPLAY_NAMES[item]
            entries.append(
                f"{_q(npc_location_name(flow, item, label))} = {_q(req)}  # npc item: {vanilla} from {who}"
            )
        if name == SKULL_REGION:
            for tokens, item in SKULL_REWARDS.items():
                vanilla = ITEM_DISPLAY_NAMES.get(item, item)
                entries.append(
                    f"{_q(skull_location_name(tokens))} = {_q(f'Gold_Skulltula_Token:{tokens}')}  # vanilla: {vanilla}"
                )
        for slot in sorted(chest_by_region.get(name, []), key=lambda s: s.name):
            ages = slot.ages
            req = (
                "is_adult"
                if ages == {"adult"}
                else "is_child" if ages == {"child"} else "true"
            )
            entries.append(f"{_q(slot.name)} = {_q(req)}")
        if entries:
            lines += ["", f"[regions.{_q(name)}.locations]", *entries]
    return "\n".join(lines) + "\n"
