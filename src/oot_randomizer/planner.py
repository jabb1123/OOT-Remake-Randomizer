"""Seed planning with assumed fill.

Progression items (anything the logic file mentions) are placed one at a time. Each item may
only go in a location reachable while assuming every still-unplaced progression item is owned,
which guarantees the final seed is completable. Everything else is placed afterwards.

House of Skulltula rewards share the chest pool, but only accept items an NPC can hand over.
Picked shop slots (shopsanity) share it too, but only accept items a shop can sell, each item
at most once; they are stocked first, still by assumed fill. Every picked slot adds one rupee
filler to the pool, which only chests accept. A slot's price adds a wallet requirement to it
through World.with_requirements. Gold Skulltula locations always keep their token.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

from .engine import UNSHUFFLED_ITEMS, ChestSlot
from .event_items import EVENT_SLOTS, event_location_name
from .item_ids import MAJOR_ITEM_ACTORS
from .npc_grants import NPC_SLOTS
from .shop_slots import (
    DEFAULT_PRICE_RANGE,
    FILLER_ITEMS,
    SHOP_LOCATIONS,
    can_sell,
    combine_requirements,
    item_requirement,
    pick_shop_slots,
    price_choices,
    price_requirement,
)
from .skulltula_rewards import SKULL_LOCATIONS, SKULL_REWARDS, TOKEN_ITEM, can_hand_over, skull_location_name
from .songs import SONG_SLOTS, song_location_name
from .world_logic import World

_SONG_ACTORS = frozenset(SONG_SLOTS.values())
# Songs count as majors for "one major item per dungeon". Event items do not: each sits in its
# dungeon's reward slot, and counting them too leaves the fill with no valid placement.
_MAJORS = MAJOR_ITEM_ACTORS | _SONG_ACTORS


@dataclass
class PlanOptions:
    shuffle_songs: bool = True
    shuffle_event_items: bool = True
    shuffle_npc_items: bool = True
    shuffle_skull_rewards: bool = True
    all_locations_reachable: bool = True
    one_major_per_dungeon: bool = False
    logic_options: dict = field(default_factory=lambda: {"bombchus_in_logic": True})
    max_attempts: int = 200
    # Shopsanity: eligible slots picked per shop (0 = off, max 4) and their price range.
    shop_slots_per_shop: int = 2
    shop_price_range: tuple[int, int] = DEFAULT_PRICE_RANGE
    # Most distinct shop actors the ROM's TOC can take (None = unchecked).
    max_shop_actors: int | None = None


@dataclass
class Plan:
    chest_assignments: list[tuple[ChestSlot, str]]
    song_assignments: dict[str, str]  # flow file -> song actor
    attempts: int
    unreachable: list[str]
    event_assignments: dict[str, str] = field(default_factory=dict)  # flow file -> event item actor
    npc_assignments: dict[str, str] = field(default_factory=dict)  # NPC location -> item actor
    skull_assignments: dict[int, str] = field(default_factory=dict)  # token count -> item
    shop_assignments: list[tuple[str, str, int]] = field(default_factory=list)  # (slot, item, price)
    # Per-seed rules (shop prices) to apply with World.with_requirements when replaying the seed.
    extra_requirements: dict[str, str] = field(default_factory=dict)


class PlanningError(RuntimeError):
    pass


def known_locations(slots: list[ChestSlot]) -> set[str]:
    return ({s.name for s in slots} | {song_location_name(f) for f in SONG_SLOTS}
            | {event_location_name(f) for f in EVENT_SLOTS} | set(NPC_SLOTS)
            | set(SKULL_LOCATIONS) | set(SHOP_LOCATIONS))


def shop_requirements(shop_assignments: list[tuple[str, str, int]]) -> dict[str, str]:
    """{slot: wallet requirement} for the slots whose price needs a bigger wallet."""
    out = {}
    for name, _, price in shop_assignments:
        req = price_requirement(price)
        if req:
            out[name] = req
    return out


def _cap_shop_slots(rng: random.Random, picked: list, pool: list[tuple[str, str]], skull_count: int) -> list:
    """Drop random picks the pool cannot stock (each slot needs a distinct sellable item, and
    shops and skull rewards together need that many hand-over items)."""
    chest_items = [item for item, group in pool if group == "chest"]
    sellable = len({i for i in chest_items if can_sell(i)})
    hand_over = sum(1 for i in chest_items if can_hand_over(i))
    limit = max(0, min(sellable, hand_over - skull_count))
    if len(picked) <= limit:
        return picked
    keep = set(rng.sample(range(len(picked)), limit))
    return [s for i, s in enumerate(picked) if i in keep]


def plan_seed(seed: int, slots: list[ChestSlot], world: World | None, options: PlanOptions) -> Plan:
    rng = random.Random(seed)
    fixed: dict[str, str] = {}
    pool: list[tuple[str, str]] = []  # (item, group)
    open_locations: dict[str, list[str]] = {"chest": [], "song": [], "event": [], "npc": []}
    excluded = world.excluded_locations if world else set()
    for loc in world.token_locations if world else ():
        fixed[loc] = TOKEN_ITEM

    for slot in slots:
        if slot.vanilla_item in UNSHUFFLED_ITEMS or slot.name in excluded:
            fixed[slot.name] = slot.vanilla_item
        else:
            pool.append((slot.vanilla_item, "chest"))
            open_locations["chest"].append(slot.name)
    for flow, song in SONG_SLOTS.items():
        loc = song_location_name(flow)
        if options.shuffle_songs:
            pool.append((song, "song"))
            open_locations["song"].append(loc)
        else:
            fixed[loc] = song
    for flow, item in EVENT_SLOTS.items():
        loc = event_location_name(flow)
        if options.shuffle_event_items:
            pool.append((item, "event"))
            open_locations["event"].append(loc)
        else:
            fixed[loc] = item
    for loc, slot in NPC_SLOTS.items():
        if options.shuffle_npc_items:
            pool.append((slot.item, "npc"))
            open_locations["npc"].append(loc)
        else:
            fixed[loc] = slot.item
    skull_count = 0
    for tokens, item in SKULL_REWARDS.items():
        loc = skull_location_name(tokens)
        if options.shuffle_skull_rewards and loc not in excluded:
            pool.append((item, "chest"))
            open_locations["chest"].append(loc)
            skull_count += 1
        else:
            fixed[loc] = item

    # Shopsanity. With a world, only slots it lists can be used (an unlisted location counts
    # as always reachable, which would skip its wallet requirement).
    try:
        allowed_slots = (set(world.location_region) - excluded) & SHOP_LOCATIONS if world else None
        picked = pick_shop_slots(rng, options.shop_slots_per_shop, allowed_slots)
        prices_allowed = price_choices(options.shop_price_range) if picked else []
    except ValueError as exc:
        raise PlanningError(str(exc)) from exc
    picked = _cap_shop_slots(rng, picked, pool, skull_count)
    if options.max_shop_actors is not None and len(picked) > options.max_shop_actors:
        raise PlanningError(
            f"{len(picked)} shop slots need {len(picked)} new shop actors but the ROM's TOC only has room "
            f"for {options.max_shop_actors}; lower shop_slots_per_shop")
    prices: dict[str, int] = {}
    for slot in picked:
        prices[slot.name] = rng.choice(prices_allowed)
        pool.append((rng.choice(FILLER_ITEMS), "chest"))
        open_locations["chest"].append(slot.name)
    shop_locs = frozenset(prices)
    extra = shop_requirements([(n, "", p) for n, p in prices.items()])
    seed_world = world.with_requirements(extra) if (world is not None and extra) else world

    for attempt in range(1, options.max_attempts + 1):
        placed = _try_fill(rng, seed_world, dict(fixed), pool, open_locations, options, shop_locs)
        if placed is None:
            continue
        # Item rules (Bomb Bag for bombs) are only known once the fill has placed the items.
        item_rules = {slot.name: rule for slot in picked if (rule := item_requirement(placed[slot.name]))}
        requirements = combine_requirements(extra, item_rules)
        check_world = world.with_requirements(requirements) if (world is not None and requirements) else world
        unreachable: list[str] = []
        if check_world is not None:
            result = check_world.explore(placed, options.logic_options)
            if not check_world.goal_met(result, options.logic_options):
                continue
            unreachable = sorted(set(placed) - result.locations)
            if options.all_locations_reachable and unreachable:
                continue
        shop_assignments = [(slot.name, placed[slot.name], prices[slot.name]) for slot in picked]
        actors = {(item, price) for _, item, price in shop_assignments}
        if options.max_shop_actors is not None and len(actors) > options.max_shop_actors:
            raise PlanningError(f"{len(actors)} shop actors do not fit in the ROM's TOC "
                                f"(room for {options.max_shop_actors})")
        return Plan(
            chest_assignments=[(s, placed[s.name]) for s in slots],
            song_assignments={flow: placed[song_location_name(flow)] for flow in SONG_SLOTS},
            event_assignments={flow: placed[event_location_name(flow)] for flow in EVENT_SLOTS},
            npc_assignments={loc: placed[loc] for loc in NPC_SLOTS},
            attempts=attempt,
            unreachable=unreachable,
            skull_assignments={n: placed[skull_location_name(n)] for n in SKULL_REWARDS},
            shop_assignments=shop_assignments,
            extra_requirements=requirements,
        )
    raise PlanningError(
        f"no valid seed after {options.max_attempts} attempts; the logic file may be too strict "
        "(run `oot-randomizer logic check`)"
    )


def _try_fill(
    rng: random.Random,
    world: World | None,
    placed: dict[str, str],
    pool: list[tuple[str, str]],
    open_locations: dict[str, list[str]],
    options: PlanOptions,
    shop_locs: frozenset[str] = frozenset(),
) -> dict[str, str] | None:
    progression_names = world.referenced_items if world else set()
    progression = [e for e in pool if e[0] in progression_names]
    rest = [e for e in pool if e[0] not in progression_names]
    rng.shuffle(progression)
    rng.shuffle(rest)
    # Majors first so the per-dungeon limit still has room for them.
    rest.sort(key=lambda e: e[0] not in _MAJORS)

    dungeon_of = world.dungeon_locations if (world and options.one_major_per_dungeon) else {}
    dungeons_with_major = {dungeon_of[loc] for loc, item in placed.items() if loc in dungeon_of and item in _MAJORS}
    in_shops: set[str] = set()

    def allowed(loc: str, item: str) -> bool:
        if loc in SKULL_LOCATIONS and not can_hand_over(item):
            return False
        if loc in shop_locs and (not can_sell(item) or item in in_shops):
            return False
        return not (item in _MAJORS and loc in dungeon_of and dungeon_of[loc] in dungeons_with_major)

    def place(loc: str, item: str) -> None:
        placed[loc] = item
        if loc in shop_locs:
            in_shops.add(item)
        if item in _MAJORS and loc in dungeon_of:
            dungeons_with_major.add(dungeon_of[loc])

    # Shop slots accept the fewest items, so stock them first from the whole pool. A
    # progression item still needs the slot reachable without it (assumed fill).
    shops = [loc for loc in open_locations["chest"] if loc in shop_locs and loc not in placed]
    rng.shuffle(shops)
    for loc in shops:
        choices = [(progression, i) for i, (item, group) in enumerate(progression)
                   if group == "chest" and allowed(loc, item)]
        choices += [(rest, i) for i, (item, group) in enumerate(rest) if group == "chest" and allowed(loc, item)]
        rng.shuffle(choices)
        for source, i in choices:
            item = source[i][0]
            if source is progression and world is not None:
                assumed = Counter(it for j, (it, _) in enumerate(progression) if j != i)
                if loc not in world.explore(placed, options.logic_options, assumed).locations:
                    continue
            source.pop(i)
            place(loc, item)
            break
        else:
            return None

    while progression:
        item, group = progression.pop()
        assumed = Counter(i for i, _ in progression)
        reachable = world.explore(placed, options.logic_options, assumed).locations
        candidates = [
            loc for loc in open_locations[group]
            if loc not in placed and loc in reachable and allowed(loc, item)
        ]
        if not candidates:
            return None
        place(rng.choice(candidates), item)

    # Skulltula rewards accept few items, so fill them before those items run out.
    for loc in open_locations["chest"]:
        if loc not in SKULL_LOCATIONS or loc in placed:
            continue
        choices = [i for i, (item, group) in enumerate(rest) if group == "chest" and allowed(loc, item)]
        if not choices:
            return None
        item, _ = rest.pop(rng.choice(choices))
        place(loc, item)

    for item, group in rest:
        candidates = [loc for loc in open_locations[group] if loc not in placed and allowed(loc, item)]
        if not candidates:
            return None
        place(rng.choice(candidates), item)
    return placed
