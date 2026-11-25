"""Progressive item families.

A family is a chain of remake actors, one per tier, lowest tier first. Each copy of a family in the
item pool is one grant, named like "Progressive Hookshot". The logic counts copies: with k copies the
player is assumed to hold tiers[0:k]. A chest that holds a copy gives the lowest tier the pouch does
not own yet (progressive_chests), so the pool and the logic agree.

Only families whose every tier is in the pool (exactly once) become progressive. A family with a tier
fixed elsewhere stays as individual items, because its copy count would not match its tiers.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Family:
    key: str  # identifier, e.g. "Hookshot"
    copy: str  # pool name of one copy, e.g. "Progressive Hookshot"
    tiers: tuple[str, ...]  # remake actors, lowest tier first
    owners: tuple[str, ...]  # pouch name checked for each tier (same length as tiers)


def _family(key: str, copy: str, tiers: tuple[str, ...], owners: tuple[str, ...] | None = None) -> Family:
    return Family(key, copy, tiers, owners or tiers)


# Tier order follows the randomizer's progressive items. The owner names differ from the tier actors
# where the pouch stores the item under another name (gauntlets, bow and slingshot).
FAMILIES: tuple[Family, ...] = (
    _family("Hookshot", "Progressive Hookshot", ("Item_Hookshot", "Item_Longshot")),
    _family(
        "Strength", "Progressive Strength Upgrade",
        ("Item_Gauntlet_Goron", "Item_Gauntlet_Silver", "Item_Gauntlet_Gold"),
        ("Armor_Child_Gauntlet_Goron", "Armor_Adult_Gauntlet_Silver", "Armor_Adult_Gauntlet_Gold"),
    ),
    _family("BombBag", "Progressive Bomb Bag", ("Item_BombBag_Small", "Item_BombBag_Medium", "Item_BombBag_Large")),
    _family(
        "Bow", "Progressive Bow", ("Item_Range_Bow", "Item_Quiver_Medium", "Item_Quiver_Large"),
        ("Weapon_Range_Bow", "Item_Quiver_Medium", "Item_Quiver_Large"),
    ),
    _family(
        "Slingshot", "Progressive Slingshot",
        ("Item_Range_SlingShot", "Item_BulletBag_Medium", "Item_BulletBag_Large"),
        ("Weapon_Range_SlingShot", "Item_BulletBag_Medium", "Item_BulletBag_Large"),
    ),
    _family("Wallet", "Progressive Wallet", ("Item_Wallet_Medium", "Item_Wallet_Large")),
    _family("Scale", "Progressive Scale", ("Item_Scale_Silver", "Item_Scale_Gold")),
    _family("NutBag", "Progressive Nut Capacity", ("Item_NutBag_Medium", "Item_NutBag_Large")),
    _family("StickBag", "Progressive Stick Capacity", ("Item_StickBag_Medium", "Item_StickBag_Large")),
    _family("Magic", "Progressive Magic Meter", ("Item_FairyBless_MP", "Item_FairyBless_MPDouble")),
    _family("Ocarina", "Progressive Ocarina", ("Item_Ocarina_Fairy", "Item_Ocarina_Time")),
)

_BY_KEY: dict[str, Family] = {f.key: f for f in FAMILIES}
_BY_COPY: dict[str, Family] = {f.copy: f for f in FAMILIES}
_BY_TIER: dict[str, Family] = {t: f for f in FAMILIES for t in f.tiers}


def family(key: str) -> Family:
    try:
        return _BY_KEY[key]
    except KeyError:
        raise ValueError(f"{key!r} is not a progressive family") from None


def is_copy(item: str) -> bool:
    return item in _BY_COPY


def family_of_copy(item: str) -> Family | None:
    return _BY_COPY.get(item)


def family_of_tier(actor: str) -> Family | None:
    return _BY_TIER.get(actor)


def first_tier(item: str) -> str:
    """The actor a chest drops for a copy: the family's lowest tier. Other items are unchanged."""
    fam = _BY_COPY.get(item)
    return fam.tiers[0] if fam else item


def tier_for_copy(item: str, copies_held: int) -> str | None:
    """The tier the `copies_held`-th copy adds (1-based), or None if `item` is not a copy."""
    fam = _BY_COPY.get(item)
    if fam is None or not 1 <= copies_held <= len(fam.tiers):
        return None
    return fam.tiers[copies_held - 1]


def expand(counts: Mapping[str, int]) -> Counter:
    """Tier actors held for the given copy counts: k copies of a family give tiers[0:k]."""
    out: Counter = Counter()
    for name, n in counts.items():
        fam = _BY_COPY.get(name)
        if fam is None:
            out[name] += n
            continue
        for tier in fam.tiers[: max(0, n)]:
            out[tier] += 1
    return out


def complete_families(pool_items: Iterable[str]) -> list[Family]:
    """Families whose every tier appears exactly once among the pool items."""
    counts = Counter(pool_items)
    return [f for f in FAMILIES if all(counts[t] == 1 for t in f.tiers)]


def convert_pool(pool: list[tuple[str, str]], enabled: bool) -> list[tuple[str, str]]:
    """Replace each tier of every complete family with one copy of that family.

    Pool entries are (item, group). The group is kept, so pool size and group balance do not change.
    """
    if not enabled:
        return pool
    families = {f.key: f for f in complete_families(item for item, _ in pool)}
    copy_of = {tier: f.copy for f in families.values() for tier in f.tiers}
    return [(copy_of.get(item, item), group) for item, group in pool]


def copies_with_any(actors: Iterable[str]) -> set[str]:
    """Copy names of the families that have at least one of `actors` as a tier."""
    wanted = set(actors)
    return {f.copy for f in FAMILIES if wanted.intersection(f.tiers)}
