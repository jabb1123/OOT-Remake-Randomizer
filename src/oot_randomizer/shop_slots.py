"""Shopsanity: shop shelf slots as item locations.

A shop slot is one (shop, ShopItemIndex) pair. Every shop shelf item is its own actor in a
scene bcett (Gyaml ``Shop_<Thing>``, Dynamic ``ShopItemIndex``; index 0 omits the key), and
the same slot appears in every scene/age variant of the shop and, for the Kokiri Shop, twice
in KokiriForest_Child (one shelf set before meeting the Deku Tree, one after). A slot's
`shelves` select every one of those copies so they are all patched together.

The table below was built from a scan of every Banc/*.bcett in both packages of the retail
ROM: shelf actors were grouped by their nearest ``Npc_*Shop*`` actor and ShopItemIndex. Both
packages hold identical shelf placements. There are no shelves in Market_Adult (the ruined
adult Market); the adult Bazaar and Potion Shop live in KakarikoVillage_Adult(_Alternative).

Only slots whose vanilla shelf item is buyable without prerequisites are used (see
SHOP_ITEM_WHITELIST); `ShopSlot.eligible` tells which. A picked slot sells a custom
``Shop_Rando_<item>`` actor built by shops.build_shop_actor.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .shops import Shelf, ShopError, actor_pack_path, apply_shop_items, shop_actor_name

# Vanilla shelf actors (prefixes) whose slots may be randomized.
SHOP_ITEM_WHITELIST: tuple[str, ...] = (
    "Shop_DekuNutBundle_",
    "Shop_DekuSeedBundle_",
    "Shop_DekuStick",
    "Shop_Weapon_Shield_",
    "Shop_Armor_",
    "Shop_Heart",
)
# Per-shop additions to SHOP_ITEM_WHITELIST. The Goron Shop's bottle and bomb-bundle shelves are
# randomizable: their location access is already gated by the Goron Shop region, and the planner
# adds the bomb-bag rule to any bomb item placed there.
SHOP_EXTRA_ELIGIBLE: dict[str, tuple[str, ...]] = {
    "Goron Shop": ("Shop_Bottle_RedPotion", "Shop_Bottle_Bug", "Shop_BombBundle_"),
}
# Excluded slots (vanilla gates them behind an upgrade, a bottle or a side quest, or they need
# magic); widen SHOP_ITEM_WHITELIST after in-game testing:
#   Bazaar       1 Shop_MagicJar_Small (magic), 2 Shop_DekuSeedBundle_02 (seeds),
#                3 Shop_ArrowBundle_01 (arrows: bow), 4 Shop_BombBundle_01 (bombs: bomb bag)
#   Potion Shop  0 Shop_Bottle_RedPotion, 1 Shop_Bottle_GreenPotion, 2 Shop_Bottle_HalfMilk,
#                3 Shop_Bottle_Fairy, 4 Shop_Bottle_BlueFire, 5 Shop_Bottle_Poe,
#                6 Shop_Bottle_Bug, 7 Shop_Bottle_Fish                               (bottle)
#   Bombchu Shop 0-7 Shop_BombchuBundle_01..08                                       (bombchus)
#   Mask Shop    0-7 Shop_Mask_*                                                     (mask quest)
#   Zora Shop    0 Shop_Bottle_RedPotion, 1 Shop_Bottle_GreenPotion, 2 Shop_Bottle_Bug,
#                6 Shop_Bottle_Fish (bottle), 4/5/7 Shop_ArrowBundle_01..03 (arrows: bow)

MAX_SHOP_SLOTS_PER_SHOP = 4
PRICE_STEP = 5
DEFAULT_PRICE_RANGE = (10, 200)
FILLER_ITEMS = ("TBox_Rupee_Blue", "TBox_Rupee_Red")
# Pool entries added for each new shop or heart slot. They must be sellable so they can stock those
# slots; the pool would otherwise have fewer sellable items than shop + heart slots.
SHOP_FILLER_ITEMS = ("Item_BombBundle_Small", "Item_DekuStickBundle_Small")

# Wallet capacity is 99 / 200 / 500 rupees.
MEDIUM_WALLET_PRICE = 100
LARGE_WALLET_PRICE = 201
MEDIUM_WALLET_RULE = "Item_Wallet_Medium or Item_Wallet_Large"
LARGE_WALLET_RULE = "Item_Wallet_Large"
BOMB_RULE = "Bomb_Bag and Dodongos_Cavern_Clear"

# Item_* actors with a Pack/Actor/<item>.pack.zs in the ROM (both packages) for which
# build_shop_actor succeeds against the retail packs and RSDB tables. Not buildable, so left
# out: Item_Hat_FishingPondOwner (no PouchActorInfo row), Item_*_ImportantMenu,
# Item_Ocarina_*_Holder and Item_OrnamentalBottle_Milk (no PouchContentRef);
# Item_EventObject_Base is a base actor, not an item.
SHOP_ITEM_PACKS: frozenset[str] = frozenset("""
Item_AgonyStone Item_AlarmCucco Item_Arrow_Fire Item_Arrow_Ice Item_Arrow_Light Item_Arrow_Normal
Item_Bomb Item_BombBag_Large Item_BombBag_Medium Item_BombBag_Small Item_BombBundle_Small
Item_Bombchu Item_BombchuBundle_Large Item_BombchuBundle_Medium Item_BombchuBundle_Small
Item_Boomerang Item_Bottle Item_Bottle_BigPoe Item_Bottle_BlueFire Item_Bottle_BluePotion
Item_Bottle_Bug Item_Bottle_Fairy Item_Bottle_Fish Item_Bottle_GreenPotion Item_Bottle_HalfMilk
Item_Bottle_Letter Item_Bottle_Milk Item_Bottle_Poe Item_Bottle_RedPotion Item_BrokenSword
Item_BulletBag_Large Item_BulletBag_Medium Item_BulletBag_Small Item_ClaimCheck Item_CojiroCucco
Item_DekuNut Item_DekuSeed Item_DekuStick Item_DekuStickBundle_Small Item_DinFire
Item_Dungeon_BossKey Item_Dungeon_Compass Item_Dungeon_Map Item_Dungeon_SmallKey Item_EyeDrop
Item_EyeballFrog Item_FairyBless_DefenseDouble Item_FairyBless_MP Item_FairyBless_MPDouble
Item_FaroreWind Item_FishingRod Item_Gauntlet_Gold Item_Gauntlet_Goron Item_Gauntlet_Silver
Item_GlassTruth Item_Hammer Item_HeavyBoot Item_Hookshot Item_HoverBoot Item_Longshot
Item_MagicBean Item_Mask_Bunny Item_Mask_Gerudo Item_Mask_Goron Item_Mask_Keaton Item_Mask_Skull
Item_Mask_Spooky Item_Mask_Truth Item_Mask_Zora Item_Medal_Fire Item_Medal_Forest Item_Medal_Light
Item_Medal_Shadow Item_Medal_Spirit Item_Medal_Water Item_Melody_EponaSong Item_Melody_FireBolero
Item_Melody_ForestMinuet Item_Melody_LightPrelude Item_Melody_SariaSong Item_Melody_ScarecrowSong
Item_Melody_ShadowNocturne Item_Melody_SpiritRequiem Item_Melody_StormSong Item_Melody_SunSong
Item_Melody_TimeSong Item_Melody_WaterSerenade Item_Melody_ZeldaLullaby Item_NayruLove
Item_NutBag_Large Item_NutBag_Medium Item_NutBag_Small Item_Ocarina_Fairy Item_Ocarina_Time
Item_OddMushroom Item_OddPowder Item_PoacherSaw Item_PocketCucco Item_PocketEgg Item_Prescription
Item_Quiver_Large Item_Quiver_Medium Item_Quiver_Small Item_Range_Bow Item_Range_SlingShot
Item_Scale_Gold Item_Scale_Silver Item_ScrubBusinessSeed Item_Shield_Mirror Item_StickBag_Large
Item_StickBag_Medium Item_StickBag_Small Item_Stone_Fire Item_Stone_Forest Item_Stone_Water
Item_Sword_Biggoron Item_Sword_BrokenGiant Item_Sword_Giant Item_Sword_Kokiri Item_Token_Gerudo
Item_Token_Gold Item_Wallet_Large Item_Wallet_Medium Item_WeirdEgg Item_ZeldaLetter
""".split())

_NOT_SELLABLE_PREFIXES = ("Item_Dungeon_", "Item_Melody_")
_NOT_SELLABLE = frozenset({"Item_ScrubBusinessSeed", "Item_Token_Gold"})


def can_sell(item: str) -> bool:
    """Items a Shop_Rando_<item> shelf actor can sell.

    Only Item_* actors with a pack in the ROM; dungeon items, songs, the scrub placeholder and
    tokens are excluded. Obj_Heart_Piece (not an Item_* actor) is excluded for now.
    """
    return (item in SHOP_ITEM_PACKS and not item.startswith(_NOT_SELLABLE_PREFIXES)
            and item not in _NOT_SELLABLE)


def price_requirement(price: int) -> str | None:
    """Logic requirement for affording `price` rupees, or None when the starting wallet does."""
    if price >= LARGE_WALLET_PRICE:
        return LARGE_WALLET_RULE
    if price >= MEDIUM_WALLET_PRICE:
        return MEDIUM_WALLET_RULE
    return None


def item_requirement(item: str) -> str | None:
    """Logic requirement to receive `item` from a shop slot, or None.

    Bombs and bombchus need the Bomb Bag and Dodongo's Cavern cleared (the Bomb Bag itself does not).
    """
    if item.startswith("Item_Bomb") and not item.startswith("Item_BombBag"):
        return BOMB_RULE
    return None


def combine_requirements(*maps: Mapping[str, str]) -> dict[str, str]:
    """Merge {slot: rule} maps, joining rules that name the same slot with `and`."""
    out: dict[str, str] = {}
    for m in maps:
        for slot, rule in m.items():
            out[slot] = f"({out[slot]}) and ({rule})" if slot in out else rule
    return out


def price_choices(price_range: Sequence[int]) -> list[int]:
    lo, hi = price_range
    lo = -(-int(lo) // PRICE_STEP) * PRICE_STEP
    prices = list(range(max(lo, 0), int(hi) + 1, PRICE_STEP))
    if not prices:
        raise ValueError(f"shop price range {tuple(price_range)} has no multiple of {PRICE_STEP}")
    return prices


# ---------------------------------------------------------------------------
# Slot table
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ShelfMatch:
    """Shelf selector: the actor with this vanilla Gyaml and ShopItemIndex (absent = 0)."""
    gyaml: str
    index: int

    def __call__(self, actor: Mapping[str, Any], _i: int) -> bool:
        dynamic = actor.get("Dynamic") or {}
        return actor.get("Gyaml") == self.gyaml and dynamic.get("ShopItemIndex", 0) == self.index


@dataclass(frozen=True, slots=True)
class ShopScene:
    """One scene variant holding a shop's shelves."""
    scene: str           # bcett stem, e.g. "KokiriForest_Child_Static"
    age: str             # "child" / "adult"
    copies: int = 1      # shelf sets in this file
    reachable: bool = True  # False: patched, but logic gives no access through this copy

    @property
    def filename(self) -> str:
        return f"{self.scene}.bcett.byml.zs"


@dataclass(frozen=True, slots=True)
class Shop:
    name: str
    npc: str                     # shopkeeper Gyaml prefix (age/stock variants share it)
    region: str | None           # logic region holding the slots; None when no slot is eligible
    scenes: tuple[ShopScene, ...]
    stock: tuple[str, ...]       # vanilla shelf Gyaml by ShopItemIndex


@dataclass(frozen=True, slots=True)
class ShopSlot:
    shop: str
    index: int                   # ShopItemIndex
    vanilla: str                 # vanilla shelf Gyaml
    region: str | None
    ages: tuple[str, ...]        # ages that reach the slot through a reachable scene copy
    shelves: tuple[Shelf, ...]   # one selector per scene file, covering every copy
    copies: int                  # total shelf actors patched

    @property
    def name(self) -> str:
        return shop_slot_name(self.shop, self.index)

    @property
    def eligible(self) -> bool:
        # Seed shelves are only randomized in the Kokiri Shop (the Bazaar seed slot is not in logic).
        if self.vanilla.startswith("Shop_DekuSeedBundle_") and self.shop != "Kokiri Shop":
            return False
        return self.vanilla.startswith(SHOP_ITEM_WHITELIST + SHOP_EXTRA_ELIGIBLE.get(self.shop, ()))

    @property
    def scene_files(self) -> list[str]:
        return [s.filename for s in self.shelves]


def shop_slot_name(shop: str, index: int) -> str:
    return f"{shop} Slot {index}"


SHOPS: tuple[Shop, ...] = (
    Shop("Kokiri Shop", "Npc_Kokiri_001_Shop", "KokiriShop",
         (ShopScene("KokiriForest_Child_Static", "child", copies=2),  # before / after the Deku Tree
          ShopScene("KokiriForest_Adult_Static", "adult")),
         ("Shop_Heart", "Shop_DekuSeedBundle_02", "Shop_DekuNutBundle_01", "Shop_DekuNutBundle_02",
          "Shop_DekuSeedBundle_01", "Shop_DekuStickBundle_Medium", "Shop_Weapon_Shield_Deku",
          "Shop_DekuStick")),
    Shop("Bazaar", "Npc_Hylia_018_Shop", "Bazaar",
         (ShopScene("Market_Child_Static", "child"),
          ShopScene("KakarikoVillage_Adult_Static", "adult"),
          ShopScene("KakarikoVillage_Adult_Alternative_Static", "adult")),
         ("Shop_Heart", "Shop_MagicJar_Small", "Shop_DekuSeedBundle_02", "Shop_ArrowBundle_01",
          "Shop_BombBundle_01", "Shop_DekuNutBundle_01", "Shop_Weapon_Shield_Hylian", "Shop_DekuStick")),
    Shop("Potion Shop", "Npc_Hylia_020_Shop", None,
         (ShopScene("Market_Child_Static", "child"),
          ShopScene("KakarikoVillage_Adult_Static", "adult"),
          ShopScene("KakarikoVillage_Adult_Alternative_Static", "adult")),
         ("Shop_Bottle_RedPotion", "Shop_Bottle_GreenPotion", "Shop_Bottle_HalfMilk", "Shop_Bottle_Fairy",
          "Shop_Bottle_BlueFire", "Shop_Bottle_Poe", "Shop_Bottle_Bug", "Shop_Bottle_Fish")),
    Shop("Bombchu Shop", "Npc_Hylia_021_Shop", None,
         (ShopScene("Market_Child_Static", "child"),),
         ("Shop_BombchuBundle_03", "Shop_BombchuBundle_04", "Shop_BombchuBundle_05", "Shop_BombchuBundle_06",
          "Shop_BombchuBundle_01", "Shop_BombchuBundle_07", "Shop_BombchuBundle_02", "Shop_BombchuBundle_08")),
    Shop("Mask Shop", "Npc_Hylia_023_Shop", None,
         (ShopScene("Market_Child_Static", "child"),),
         ("Shop_Mask_Spooky", "Shop_Mask_Keaton", "Shop_Mask_Bunny", "Shop_Mask_Skull",
          "Shop_Mask_Zora", "Shop_Mask_Goron", "Shop_Mask_Gerudo", "Shop_Mask_Truth")),
    Shop("Goron Shop", "Npc_Goron_011_Shop", "GoronShop",
         (ShopScene("GoronCity_Child_Static", "child"),
          ShopScene("GoronCity_Adult_Static", "adult")),
         ("Shop_Heart", "Shop_Bottle_RedPotion", "Shop_Bottle_Bug", "Shop_Armor_Goron",
          "Shop_BombBundle_01", "Shop_BombBundle_02", "Shop_BombBundle_03", "Shop_BombBundle_04")),
    # The adult shopkeeper is frozen until King Zora is thawed (blue fire), which the logic
    # does not model, so the adult copies are patched but give no access.
    Shop("Zora Shop", "Npc_Zora_011_Shop", "ZoraShop",
         (ShopScene("ZoraDomain_Child_Static", "child"),
          ShopScene("ZoraDomain_Adult_Static", "adult", reachable=False),
          ShopScene("ZoraDomain_Adult_Alternative_Static", "adult", reachable=False)),
         ("Shop_Bottle_RedPotion", "Shop_Bottle_GreenPotion", "Shop_Bottle_Bug", "Shop_Armor_Zora",
          "Shop_ArrowBundle_01", "Shop_ArrowBundle_02", "Shop_Bottle_Fish", "Shop_ArrowBundle_03")),
)


def _build_slots() -> dict[str, ShopSlot]:
    slots: dict[str, ShopSlot] = {}
    for shop in SHOPS:
        ages = tuple(a for a in ("child", "adult") if any(s.age == a and s.reachable for s in shop.scenes))
        for index, gyaml in enumerate(shop.stock):
            match = ShelfMatch(gyaml, index)
            shelves = tuple(Shelf(s.filename, match, allow_multiple=s.copies > 1) for s in shop.scenes)
            slot = ShopSlot(shop.name, index, gyaml, shop.region, ages, shelves,
                            sum(s.copies for s in shop.scenes))
            slots[slot.name] = slot
    return slots


# Every slot, eligible or not, by location name.
ALL_SHOP_SLOTS: dict[str, ShopSlot] = _build_slots()
# Slots that can become locations.
SHOP_SLOTS: dict[str, ShopSlot] = {n: s for n, s in ALL_SHOP_SLOTS.items() if s.eligible}
SHOP_LOCATIONS: frozenset[str] = frozenset(SHOP_SLOTS)
# Vanilla contents of shop slots that the logic needs in the unmodified game. The shelf
# item itself is not an item actor, so these map the slot to the chest actor with the same item.
VANILLA_SHOP_LOGIC_ITEMS: dict[str, str] = {"Kokiri Shop Slot 6": "TBox_Shield_Deku"}  # Deku Shield


def slots_by_shop(slots: Iterable[ShopSlot] | None = None) -> dict[str, list[ShopSlot]]:
    out: dict[str, list[ShopSlot]] = {}
    for slot in (SHOP_SLOTS.values() if slots is None else slots):
        out.setdefault(slot.shop, []).append(slot)
    return out


def pick_shop_slots(rng: random.Random, per_shop: int,
                    allowed: set[str] | frozenset[str] | None = None) -> list[ShopSlot]:
    """Pick `per_shop` eligible slots of every shop at random (fewer when a shop has fewer).

    `allowed` limits the candidates (e.g. to slots listed in the world logic).
    """
    if isinstance(per_shop, bool) or not isinstance(per_shop, int) or not 0 <= per_shop <= MAX_SHOP_SLOTS_PER_SHOP:
        raise ValueError(f"shop_slots_per_shop must be 0..{MAX_SHOP_SLOTS_PER_SHOP}, got {per_shop!r}")
    if per_shop == 0:
        return []
    picked: list[ShopSlot] = []
    for shop in SHOPS:
        candidates = [s for s in SHOP_SLOTS.values()
                      if s.shop == shop.name and (allowed is None or s.name in allowed)]
        if candidates:
            picked += sorted(rng.sample(candidates, min(per_shop, len(candidates))), key=lambda s: s.index)
    return picked


# ---------------------------------------------------------------------------
# ROM side
# ---------------------------------------------------------------------------

def _toc_name_bytes(actor_name: str) -> int:
    from nup import format as F
    filename = actor_pack_path(actor_name).rsplit("/", 1)[-1]
    # file record + child index + name in the string pool (an upper bound: names may be reused)
    return F.FILE_SIZE + 4 + len(filename.encode("utf-8"))


def _toc_entry_bytes(item_actor: str) -> int:
    return _toc_name_bytes(shop_actor_name(item_actor))


_MAX_ITEM_NAME = max(SHOP_ITEM_PACKS, key=len)


def shop_actor_capacity(nup_path: str | Path) -> int:
    """How many new shop actor packs surely fit in the TOC without relocating extents."""
    from .nup_files import toc_space
    free = toc_space(nup_path)["free_bytes_after_meta_move"]
    return max(0, (free - 15) // _toc_entry_bytes(_MAX_ITEM_NAME))


def check_toc_names(nup_path: str | Path, actor_names: Iterable[str]) -> None:
    """Raise ShopError when the new packs named `actor_names` may not fit in the TOC."""
    from .nup_files import toc_space
    names = sorted(set(actor_names))
    need = sum(_toc_name_bytes(n) for n in names)
    need = (need + 15) & ~15
    free = toc_space(nup_path)["free_bytes_after_meta_move"]
    if need > free:
        raise ShopError(
            f"{len(names)} new actors need up to {need} TOC bytes but only {free} are free before "
            f"the blob region; use fewer shop slots or heart pickups")


def check_toc_room(nup_path: str | Path, item_actors: Iterable[str]) -> None:
    """Raise ShopError when the shop packs for `item_actors` may not fit in the TOC."""
    try:
        check_toc_names(nup_path, [shop_actor_name(i) for i in item_actors])
    except ShopError as exc:
        raise ShopError(
            f"{exc}; lower shop_slots_per_shop (about {shop_actor_capacity(nup_path)} actors fit)") from None


def shop_items_for(assignments: Iterable[tuple[str, str, int]]) -> list[tuple[str, int, list[Shelf]]]:
    """apply_shop_items arguments for [(slot name, item, price)]."""
    items: list[tuple[str, int, list[Shelf]]] = []
    seen: dict[str, int] = {}
    for name, item, price in assignments:
        slot = ALL_SHOP_SLOTS.get(name)
        if slot is None:
            raise ShopError(f"unknown shop slot {name!r}")
        if not can_sell(item):
            raise ShopError(f"{item} cannot be sold in a shop ({name})")
        if item in seen:
            raise ShopError(f"{item} is assigned to two shop slots; each item may be sold once per seed")
        seen[item] = price
        items.append((item, price, list(slot.shelves)))
    return items


def apply_shop_slots(nup_path: str | Path, zsdic_bytes: bytes,
                     assignments: Sequence[tuple[str, str, int]]):
    """Put the planned shop items on their shelves in a NUP (see shops.apply_shop_items)."""
    items = shop_items_for(assignments)
    check_toc_room(nup_path, [item for item, _, _ in items])
    try:
        return apply_shop_items(nup_path, zsdic_bytes, items)
    except KeyError as exc:  # raised while reading, before anything is written
        raise ShopError(f"file missing from the NUP: {exc}") from exc
