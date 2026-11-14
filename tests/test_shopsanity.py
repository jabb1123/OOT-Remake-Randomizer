"""Tests for shopsanity: the shop slot table, logic/planner integration and the patch path."""

import json
import shutil
import struct
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import zstandard

from oot_randomizer.byml7 import U32, U64, dump_byml7, parse_byml7, parse_byml7_typed
from oot_randomizer.engine import ChestSlot, load_default_slots
from oot_randomizer.event_items import EVENT_SLOTS, event_location_name
from oot_randomizer.gamedata_list import GAME_DATA_LIST, SHOP_SOLDOUT_NAMES, murmur3_32
from oot_randomizer.item_ids import MAJOR_ITEM_ACTORS
from oot_randomizer.npc_grants import NPC_SLOTS
from oot_randomizer.nup_chest_patcher import _decompress, _load_dicts_from_sarc, _restbl_entry_offset
from oot_randomizer.patcher import PatchRecord, RomPatcher
from oot_randomizer.planner import PlanningError, PlanOptions, known_locations, plan_seed, shop_requirements
from oot_randomizer.shop_slots import (
    ALL_SHOP_SLOTS,
    BOMB_RULE,
    FILLER_ITEMS,
    MEDIUM_WALLET_RULE,
    LARGE_WALLET_RULE,
    SHOP_FILLER_ITEMS,
    SHOP_ITEM_PACKS,
    SHOP_LOCATIONS,
    SHOP_SLOTS,
    SHOPS,
    ShelfMatch,
    apply_shop_slots,
    can_sell,
    check_toc_room,
    combine_requirements,
    item_requirement,
    price_choices,
    price_requirement,
    shop_actor_capacity,
    shop_items_for,
)
from oot_randomizer.shops import ShopError, find_shelf_actors, set_shelf_item, tag_names
from oot_randomizer.shop_soldout import patch_kokiri_soldout
from oot_randomizer.skulltula_rewards import SKULL_LOCATIONS, SKULL_REWARDS, TOKEN_ITEM, skull_location_name
from oot_randomizer.songs import SONG_SLOTS, song_location_name
from oot_randomizer.world_logic import LogicError, load_world

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_nup_files as tnf  # noqa: E402  (module imports: their TestCases are not re-collected)
import test_shop_soldout as tso  # noqa: E402
import test_shops as ts  # noqa: E402
import test_skulltula as tsk  # noqa: E402

SHOP_DATA = Path(r"C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405\files\shop_data.json")
WALLETS = ("Item_Wallet_Medium", "Item_Wallet_Large")
MAJORS = MAJOR_ITEM_ACTORS | set(SONG_SLOTS.values())
B = dump_byml7


def _world(text: str):
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "world.toml"
        path.write_text(text, encoding="utf-8")
        return load_world(path)


# ---------------------------------------------------------------------------
# Slot table
# ---------------------------------------------------------------------------

class SlotTableTests(unittest.TestCase):
    def test_eligible_slots(self):
        by_shop = {}
        for slot in SHOP_SLOTS.values():
            by_shop.setdefault(slot.shop, []).append(slot.index)
        self.assertEqual(
            by_shop,
            {
                "Kokiri Shop": list(range(0, 8)),
                "Bazaar": [0, 2, 3, 5, 6, 7],
                "Potion Shop": [0, 1, 2, 3, 5, 6, 7],
                "Goron Shop": list(range(0, 8)),
                "Zora Shop": list(range(0, 8)),
            },
        )
        self.assertEqual(SHOP_LOCATIONS, frozenset(SHOP_SLOTS))
        self.assertEqual(SHOP_SLOTS["Kokiri Shop Slot 2"].vanilla, "Shop_DekuNutBundle_01")

    def test_every_slot_is_listed_once_and_whitelist_decides_eligibility(self):
        self.assertEqual(len(SHOPS), 7)
        self.assertEqual(len(ALL_SHOP_SLOTS), 7 * 8)
        for name, slot in ALL_SHOP_SLOTS.items():
            self.assertEqual(name, f"{slot.shop} Slot {slot.index}")
            excluded_kinds = ("Shop_BombchuBundle", "Shop_Mask", "Shop_MagicJar")
            if slot.vanilla.startswith(excluded_kinds):
                self.assertFalse(slot.eligible, name)

    def test_shelves_cover_every_scene_copy(self):
        kokiri = SHOP_SLOTS["Kokiri Shop Slot 2"]
        self.assertEqual(kokiri.scene_files, ["KokiriForest_Child_Static.bcett.byml.zs",
                                              "KokiriForest_Adult_Static.bcett.byml.zs"])
        self.assertEqual([s.allow_multiple for s in kokiri.shelves], [True, False])
        self.assertEqual(kokiri.copies, 3)
        self.assertEqual(kokiri.ages, ("child", "adult"))
        bazaar = SHOP_SLOTS["Bazaar Slot 6"]
        self.assertEqual(bazaar.scene_files, ["Market_Child_Static.bcett.byml.zs",
                                              "KakarikoVillage_Adult_Static.bcett.byml.zs",
                                              "KakarikoVillage_Adult_Alternative_Static.bcett.byml.zs"])
        self.assertEqual(bazaar.ages, ("child", "adult"))
        zora = SHOP_SLOTS["Zora Shop Slot 3"]
        self.assertEqual(len(zora.shelves), 3)  # adult copies are patched ...
        self.assertEqual(zora.ages, ("child",))  # ... but give no access
        for slot in SHOP_SLOTS.values():
            self.assertTrue(slot.region)
            self.assertTrue(all(isinstance(s.select, ShelfMatch) for s in slot.shelves))
            self.assertTrue(all(s.select == ShelfMatch(slot.vanilla, slot.index) for s in slot.shelves))

    def test_shelf_match_treats_missing_index_as_zero(self):
        m0, m2 = ShelfMatch("Shop_Heart", 0), ShelfMatch("Shop_Heart", 2)
        self.assertTrue(m0({"Gyaml": "Shop_Heart"}, 0))
        self.assertTrue(m0({"Gyaml": "Shop_Heart", "Dynamic": {}}, 0))
        self.assertFalse(m0({"Gyaml": "Shop_Heart", "Dynamic": {"ShopItemIndex": 2}}, 0))
        self.assertTrue(m2({"Gyaml": "Shop_Heart", "Dynamic": {"ShopItemIndex": 2}}, 0))
        self.assertFalse(m2({"Gyaml": "Shop_Nut", "Dynamic": {"ShopItemIndex": 2}}, 0))

    def test_selectors_patch_both_kokiri_shelf_sets(self):
        data = kokiri_child_scene()
        slot = SHOP_SLOTS["Kokiri Shop Slot 0"]
        shelf = slot.shelves[0]
        self.assertEqual(len(find_shelf_actors(data, shelf.select)), 2)
        out = set_shelf_item(data, shelf.select, "Shop_Rando_Item_Hookshot", allow_multiple=shelf.allow_multiple)
        gy = [a["Gyaml"] for a in parse_byml7(out)["Actors"]]
        self.assertEqual(gy.count("Shop_Rando_Item_Hookshot"), 2)
        self.assertEqual(gy.count("Shop_Heart"), 0)

    @unittest.skipUnless(SHOP_DATA.exists(), "shop_data.json not available")
    def test_table_matches_the_rom_scan(self):
        data = json.loads(SHOP_DATA.read_text(encoding="utf-8"))
        placements = data["placements"]
        covered = Counter()
        for slot in ALL_SHOP_SLOTS.values():
            shop = next(s for s in SHOPS if s.name == slot.shop)
            for scene, shelf in zip(shop.scenes, slot.shelves):
                hits = [p for p in placements if f"{p['scene_file']}.bcett.byml.zs" == shelf.filename
                        and shelf.select({"Gyaml": p["Gyaml"], "Dynamic": p["Dynamic"]}, p["actor_index"])]
                self.assertEqual(len(hits), scene.copies, f"{slot.name} in {shelf.filename}")
                for p in hits:
                    self.assertTrue(p["nearest_shop_npc"][0].startswith(shop.npc), (slot.name, p))
                    covered[(p["scene_file"], p["actor_index"])] += 1
        self.assertEqual(len(covered), len(placements))
        self.assertEqual(set(covered.values()), {1})


class SellAndPriceTests(unittest.TestCase):
    def test_can_sell(self):
        for item in ("Item_Hookshot", "Item_Wallet_Medium", "Item_BombBag_Small", "Item_AgonyStone"):
            self.assertTrue(can_sell(item), item)
        for item in ("Item_Dungeon_Map", "Item_Dungeon_SmallKey", "Item_Melody_TimeSong", "Item_ScrubBusinessSeed",
                     "Item_Token_Gold", "Obj_Heart_Piece", "TBox_Rupee_Red", "Item_Hat_FishingPondOwner",
                     "Item_EventObject_Base", "Item_Nonexistent"):
            self.assertFalse(can_sell(item), item)
        self.assertFalse(any(can_sell(f) for f in FILLER_ITEMS))
        self.assertTrue(all(can_sell(f) for f in SHOP_FILLER_ITEMS))

    def test_item_requirement_bombs_need_bomb_bag(self):
        for item in ("Item_Bomb", "Item_BombBundle_Small", "Item_Bombchu", "Item_BombchuBundle_Small"):
            self.assertEqual(item_requirement(item), BOMB_RULE, item)
        for item in ("Item_BombBag_Small", "Item_Hookshot", "Item_DekuNut"):
            self.assertIsNone(item_requirement(item), item)

    def test_combine_requirements_joins_same_slot(self):
        self.assertEqual(combine_requirements({"a": "x"}, {"b": "y"}), {"a": "x", "b": "y"})
        self.assertEqual(combine_requirements({"a": "x"}, {"a": "y"}), {"a": "(x) and (y)"})

    def test_price_requirement(self):
        self.assertIsNone(price_requirement(10))
        self.assertIsNone(price_requirement(99))
        self.assertEqual(price_requirement(100), MEDIUM_WALLET_RULE)
        self.assertEqual(price_requirement(200), MEDIUM_WALLET_RULE)
        self.assertEqual(price_requirement(201), LARGE_WALLET_RULE)
        self.assertEqual(price_requirement(500), LARGE_WALLET_RULE)

    def test_price_choices(self):
        prices = price_choices((10, 200))
        self.assertEqual(prices[0], 10)
        self.assertEqual(prices[-1], 200)
        self.assertTrue(all(p % 5 == 0 for p in prices))
        self.assertEqual(price_choices((12, 24)), [15, 20])
        with self.assertRaises(ValueError):
            price_choices((11, 14))

    def test_shop_items_for_validates(self):
        items = shop_items_for([("Kokiri Shop Slot 2", "Item_Hookshot", 10)])
        self.assertEqual(items[0][:2], ("Item_Hookshot", 10))
        self.assertEqual(items[0][2], list(SHOP_SLOTS["Kokiri Shop Slot 2"].shelves))
        with self.assertRaises(ShopError):
            shop_items_for([("Kokiri Shop Slot 9", "Item_Hookshot", 10)])
        with self.assertRaises(ShopError):
            shop_items_for([("Kokiri Shop Slot 2", "TBox_Rupee_Red", 10)])
        with self.assertRaises(ShopError):
            shop_items_for([("Kokiri Shop Slot 2", "Item_Hookshot", 10), ("Bazaar Slot 0", "Item_Hookshot", 20)])


# ---------------------------------------------------------------------------
# World: per-seed requirements
# ---------------------------------------------------------------------------

WALLET_WORLD = """
[settings]
goal = "Done"
[regions.Root.exits]
Field = "true"
[regions.Field.locations]
"Chest A" = "true"
"Chest B" = "true"
"Kokiri Shop Slot 0" = "true"
[regions.Field.events]
Done = "Hookshot"
"""


class ExtraRequirementTests(unittest.TestCase):
    def setUp(self):
        self.world = _world(WALLET_WORLD)

    def test_requirements_are_anded_per_copy(self):
        seed_world = self.world.with_requirements({"Kokiri Shop Slot 0": MEDIUM_WALLET_RULE})
        self.assertEqual(self.world.extra_requirements, {})
        self.assertIn("Item_Wallet_Medium", seed_world.referenced_items)
        self.assertNotIn("Item_Wallet_Medium", self.world.referenced_items)
        placed = {"Kokiri Shop Slot 0": "Item_Hookshot", "Chest A": "TBox_Rupee_Red", "Chest B": "TBox_Rupee_Red"}
        self.assertTrue(self.world.goal_met(self.world.explore(placed)))
        res = seed_world.explore(placed)
        self.assertNotIn("Kokiri Shop Slot 0", res.locations)
        self.assertFalse(seed_world.goal_met(res))
        res = seed_world.explore(placed | {"Chest A": "Item_Wallet_Large"})
        self.assertTrue(seed_world.goal_met(res))
        both = seed_world.with_requirements({"Kokiri Shop Slot 0": LARGE_WALLET_RULE})
        res = both.explore(placed | {"Chest A": "Item_Wallet_Medium"})
        self.assertNotIn("Kokiri Shop Slot 0", res.locations)

    def test_wallet_behind_its_own_price_is_locked(self):
        seed_world = self.world.with_requirements({"Kokiri Shop Slot 0": MEDIUM_WALLET_RULE})
        placed = {"Kokiri Shop Slot 0": "Item_Wallet_Medium", "Chest A": "Item_Hookshot", "Chest B": "TBox_Rupee_Red"}
        res = seed_world.explore(placed)
        self.assertNotIn("Kokiri Shop Slot 0", res.locations)
        self.assertEqual(res.items["Item_Wallet_Medium"], 0)

    def test_unknown_location_or_name_raises(self):
        with self.assertRaises(LogicError):
            self.world.with_requirements({"Nowhere": "true"})
        with self.assertRaises(LogicError):
            self.world.with_requirements({"Chest A": "Not_An_Item_Or_Event"})


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

def _shop_world_text(*, large_wallet_reachable: bool = True) -> str:
    """Toy world with the Kokiri Shop; optionally the Giant's Wallet reward can never be reached,
    leaving the Adult's Wallet as the only wallet."""
    lines = [
        "[settings]",
        'goal = "Done"',
        "[regions.Root.exits]",
        'Field = "true"',
        'Town = "Hookshot"',
        'Shop = "true"',
        'Locked = "true"',
        "[regions.Field.events]",
        'Dodongos_Cavern_Clear = "true"',
        'Done = "Megaton_Hammer and Item_Wallet_Medium"',
        "[regions.Locked]",
        f"excluded = {'false' if large_wallet_reachable else 'true'}",
        "[regions.Shop.locations]",
    ]
    lines += [f'"{name}" = "true"' for name in SHOP_SLOTS if name.startswith("Kokiri Shop")]
    lines.append("[regions.Field.locations]")
    lines += [f'"{name}" = "true"' for name, (r, _) in CHESTS.items() if r == "Field"]
    lines.append("[regions.Town.locations]")
    lines += [f'"{name}" = "true"' for name, (r, _) in CHESTS.items() if r == "Town"]
    lines += [f'"{skull_location_name(n)}" = "Gold_Skulltula_Token:{n}"' for n in SKULL_REWARDS if n != 30]
    lines.append("[regions.Locked.locations]")
    lines.append(f'"{skull_location_name(30)}" = "{"Gold_Skulltula_Token:30" if large_wallet_reachable else "false"}"')
    lines.append("[regions.Field.skulltulas]")
    lines += [f'"GS Field {i}" = "true"' for i in range(1, 51)]
    return "\n".join(lines) + "\n"


CHESTS = {
    "Field chest 1": ("Field", "Item_Hookshot"),
    "Field chest 2": ("Field", "TBox_Rupee_Red"),
    "Field chest 3": ("Field", "Item_Boomerang"),
    "Field chest 4": ("Field", "TBox_Rupee_Green"),
    "Field chest 5": ("Field", "Item_BombBag_Small"),
    "Town chest 1": ("Town", "Item_Range_Bow"),
    "Town chest 2": ("Town", "TBox_Rupee_Red"),
    "Town chest 3": ("Town", "Item_Hammer"),
    "Town chest 4": ("Town", "Item_HoverBoot"),
}
TOY_SLOTS = [ChestSlot(name, item, 0, ((f"{region}.bcett.byml.zs", i),), region)
             for i, (name, (region, item)) in enumerate(CHESTS.items())]


def _placed(plan, world) -> dict[str, str]:
    placed = {s.name: item for s, item in plan.chest_assignments}
    placed |= {song_location_name(f): s for f, s in plan.song_assignments.items()}
    placed |= {event_location_name(f): item for f, item in plan.event_assignments.items()}
    placed |= plan.npc_assignments
    placed |= {skull_location_name(n): item for n, item in plan.skull_assignments.items()}
    placed |= {loc: TOKEN_ITEM for loc in world.token_locations}
    placed |= {loc: item for loc, item, _ in plan.shop_assignments}
    placed |= dict(plan.heart_assignments)
    return placed


class ToyShopPlanningTests(unittest.TestCase):
    def test_only_wallet_never_behind_a_wallet_price(self):
        world = _world(_shop_world_text(large_wallet_reachable=False))
        self.assertEqual(world.errors, [])
        options = PlanOptions(shop_slots_per_shop=4, shop_price_range=(150, 150), all_locations_reachable=False)
        for seed in range(60):
            plan = plan_seed(seed, TOY_SLOTS, world, options)
            self.assertEqual(len(plan.shop_assignments), 4)
            self.assertEqual(plan.skull_assignments[30], "Item_Wallet_Large")  # excluded: stays vanilla
            for loc, item, price in plan.shop_assignments:
                self.assertEqual(price, 150)
                self.assertNotEqual(item, "Item_Wallet_Medium", f"seed {seed}: only wallet behind {loc}")
            placed = _placed(plan, world)
            seed_world = world.with_requirements(plan.extra_requirements)
            res = seed_world.explore(placed, options.logic_options)
            self.assertTrue(seed_world.goal_met(res), f"seed {seed}")
            self.assertEqual(res.items["Item_Wallet_Medium"], 1, f"seed {seed}")
            self.assertEqual(res.items["Item_Wallet_Large"], 0, f"seed {seed}")
            self.assertTrue({loc for loc, _, _ in plan.shop_assignments} <= res.locations, f"seed {seed}")

    def test_wallet_may_sit_behind_a_price_when_the_other_one_is_reachable(self):
        world = _world(_shop_world_text())
        options = PlanOptions(shop_slots_per_shop=4, shop_price_range=(150, 150))
        wallet_in_shop = 0
        for seed in range(60):
            plan = plan_seed(seed, TOY_SLOTS, world, options)
            placed = _placed(plan, world)
            seed_world = world.with_requirements(plan.extra_requirements)
            res = seed_world.explore(placed, options.logic_options)
            self.assertTrue(seed_world.goal_met(res), f"seed {seed}")
            self.assertEqual(set(placed) - res.locations, set(), f"seed {seed}")
            # without wallets, no 150-rupee slot can be bought
            no_wallets = {k: (None if v in WALLETS else v) for k, v in placed.items()}
            res = seed_world.explore(no_wallets, options.logic_options)
            self.assertFalse({loc for loc, _, _ in plan.shop_assignments} & res.locations, f"seed {seed}")
            wallet_in_shop += any(item in WALLETS for _, item, _ in plan.shop_assignments)
        self.assertGreater(wallet_in_shop, 0, "a wallet was never put in a shop")

    def test_world_without_shop_locations_keeps_shops_off(self):
        world = tsk._world(tsk._world_text())
        plan = plan_seed(1, tsk.SLOTS, world, PlanOptions(shop_slots_per_shop=4))
        self.assertEqual(plan.shop_assignments, [])
        self.assertEqual(plan.extra_requirements, {})

    def test_small_pool_caps_shop_slots(self):
        for seed in range(10):
            # Other non-chest shuffles are off: the toy pool can't cover their slots as well as shops.
            plan = plan_seed(
                seed,
                tsk.SLOTS,
                None,
                PlanOptions(
                    shop_slots_per_shop=4,
                    shuffle_heart_pieces=False,
                    shuffle_npc_items=False,
                    shuffle_event_items=False,
                    shuffle_songs=False,
                ),
            )
            items = [item for _, item, _ in plan.shop_assignments]

            self.assertTrue(all(can_sell(i) for i in items))
            self.assertEqual(len(items), len(set(items)))


@unittest.skipUnless(load_default_slots(), "chest_locations_summary.json not available")
class ShippedShopPlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.slots = load_default_slots()
        cls.world = load_world()
        cls.world.check_locations(known_locations(cls.slots))
        cls.plans = {seed: plan_seed(seed, cls.slots, cls.world, PlanOptions()) for seed in range(25)}

    def test_shop_locations_are_listed_in_the_shipped_logic(self):
        self.assertEqual(self.world.errors, [])
        self.assertEqual(self.world.warnings, [])
        for name, slot in SHOP_SLOTS.items():
            self.assertEqual(self.world.location_region[name], slot.region)

    def test_default_picks_two_slots_per_shop(self):
        for seed, plan in self.plans.items():
            per_shop = Counter(SHOP_SLOTS[n].shop for n, _, _ in plan.shop_assignments)
            self.assertEqual(
                per_shop,
                {
                    "Kokiri Shop": 2,
                    "Bazaar": 2,
                    "Potion Shop": 2,
                    "Goron Shop": 2,
                    "Zora Shop": 2,
                },
                seed,
            )

    def test_shop_slots_only_get_sellable_unique_items_and_valid_prices(self):
        for seed, plan in self.plans.items():
            items = [item for _, item, _ in plan.shop_assignments]
            self.assertTrue(all(can_sell(i) for i in items), (seed, items))
            # Filler bundles may repeat (one shop actor each, so every copy shares its price).
            others = [i for i in items if i not in SHOP_FILLER_ITEMS]
            self.assertEqual(len(others), len(set(others)), seed)
            filler_prices: dict[str, int] = {}
            for _, item, price in plan.shop_assignments:
                if item in SHOP_FILLER_ITEMS:
                    self.assertEqual(filler_prices.setdefault(item, price), price, (seed, item))
            for name, _, price in plan.shop_assignments:
                self.assertTrue(10 <= price <= 200 and price % 5 == 0, (seed, name, price))
            expected = combine_requirements(
                shop_requirements(plan.shop_assignments),
                {name: item_requirement(item) for name, item, _ in plan.shop_assignments if item_requirement(item)}
                | {name: item_requirement(item) for name, item in plan.heart_assignments if item_requirement(item)})
            self.assertEqual(plan.extra_requirements, expected)
            for name, item, price in plan.shop_assignments:
                if price_requirement(price):
                    self.assertIn(price_requirement(price), plan.extra_requirements[name])
                if item_requirement(item):
                    self.assertIn(item_requirement(item), plan.extra_requirements[name])

    def test_fillers_only_in_chests_and_counts_balance(self):
        # Each new shop or heart slot adds one pool entry (SHOP_FILLER_ITEMS); nothing else is added.
        fillers = set(SHOP_FILLER_ITEMS)
        expected = (Counter(s.vanilla_item for s in self.slots) + Counter(SKULL_REWARDS.values())
                    + Counter(SONG_SLOTS.values()) + Counter(EVENT_SLOTS.values())
                    + Counter(s.item for s in NPC_SLOTS.values()))
        for seed, plan in self.plans.items():
            placed = (Counter(i for _, i in plan.chest_assignments) + Counter(plan.skull_assignments.values())
                      + Counter(plan.song_assignments.values()) + Counter(plan.event_assignments.values())
                      + Counter(plan.npc_assignments.values())
                      + Counter(i for _, i, _ in plan.shop_assignments) + Counter(i for _, i in plan.heart_assignments))
            added = placed - expected
            self.assertEqual(sum(added.values()), len(plan.shop_assignments) + len(plan.heart_assignments), seed)
            self.assertTrue(set(added) <= fillers, (seed, added))
            self.assertEqual(expected - placed, Counter(), seed)

    def test_planned_seeds_are_beatable_with_price_rules(self):
        options = PlanOptions()
        for seed, plan in self.plans.items():
            placed = _placed(plan, self.world)
            seed_world = self.world.with_requirements(plan.extra_requirements)
            res = seed_world.explore(placed, options.logic_options)
            self.assertTrue(seed_world.goal_met(res), seed)
            self.assertEqual(set(placed) - res.locations, set(), seed)

    def test_disabled(self):
        expected = (Counter(s.vanilla_item for s in self.slots) + Counter(SKULL_REWARDS.values())
                    + Counter(SONG_SLOTS.values()) + Counter(EVENT_SLOTS.values())
                    + Counter(s.item for s in NPC_SLOTS.values()))
        for seed in range(5):
            plan = plan_seed(seed, self.slots, self.world,
                             PlanOptions(shop_slots_per_shop=0, shuffle_heart_pieces=False))
            self.assertEqual(plan.shop_assignments, [])
            self.assertEqual(plan.extra_requirements, {})
            placed = (Counter([i for _, i in plan.chest_assignments] + list(plan.skull_assignments.values())
                              + list(plan.song_assignments.values()) + list(plan.event_assignments.values())
                              + list(plan.npc_assignments.values())))
            self.assertEqual(placed, expected)

    def test_max_slots_and_one_major_per_dungeon(self):
        dungeon_of = self.world.dungeon_locations
        majors = set(MAJORS)
        for seed in range(8):
            plan = plan_seed(seed, self.slots, self.world, PlanOptions(shop_slots_per_shop=4, one_major_per_dungeon=True))
            per_shop = Counter(SHOP_SLOTS[n].shop for n, _, _ in plan.shop_assignments)
            self.assertEqual(
                per_shop,
                {"Kokiri Shop": 4, "Bazaar": 4, "Goron Shop": 4, "Potion Shop": 4, "Zora Shop": 4},
            )
            placed = _placed(plan, self.world)
            per_dungeon = Counter(dungeon_of[l] for l, i in placed.items() if l in dungeon_of and i in majors)
            self.assertTrue(all(n <= 1 for n in per_dungeon.values()), per_dungeon)
            seed_world = self.world.with_requirements(plan.extra_requirements)
            self.assertTrue(seed_world.goal_met(seed_world.explore(placed, {"bombchus_in_logic": True})))

    def test_bad_options_raise(self):
        for n in (-1, 5):
            with self.assertRaises(PlanningError):
                plan_seed(1, self.slots, self.world, PlanOptions(shop_slots_per_shop=n))
        with self.assertRaises(PlanningError):
            plan_seed(1, self.slots, self.world, PlanOptions(shop_price_range=(11, 14)))
        with self.assertRaisesRegex(PlanningError, "TOC"):
            plan_seed(1, self.slots, self.world, PlanOptions(max_shop_actors=3))
        plan = plan_seed(1, self.slots, self.world, PlanOptions(max_shop_actors=10))
        self.assertEqual(len({(i, p) for _, i, p in plan.shop_assignments}), 10)


# ---------------------------------------------------------------------------
# Patch path on a synthetic NUP
# ---------------------------------------------------------------------------

def _rename(obj, old: str, new: str):
    if isinstance(obj, str):
        return obj.replace(old, new)
    if isinstance(obj, dict):
        return {_rename(k, old, new): _rename(v, old, new) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rename(v, old, new) for v in obj]
    return obj


TEMPLATE = "Shop_Mask_Keaton"
ITEMS = ("Item_Hookshot", "Item_Range_Bow")


def template_pack() -> bytes:
    return ts.make_pack(_rename(ts.TPL_FILES, "Shop_Tpl", TEMPLATE))


def item_pack(item: str) -> bytes:
    return ts.make_pack(_rename(ts.ITEM_FILES, "Item_Thing", item))


def rsdb_tables() -> dict[str, bytes]:
    out = {}
    for kind, data in ts.rsdb_tables().items():
        if kind == "Tag":
            continue
        rows = parse_byml7_typed(data)
        thing = next(r for r in rows if r["__RowId"] == "Item_Thing")
        rows = [_rename(r, "Shop_Tpl", TEMPLATE) for r in rows if r["__RowId"] != "Item_Thing"]
        rows += [_rename(thing, "Item_Thing", item) for item in ITEMS]
        rows.sort(key=lambda r: r["__RowId"].encode())
        out[kind] = B(rows)
    out["Tag"] = ts.tag_table([(i, ["A"]) for i in ITEMS] + [(TEMPLATE, ["B", "C"]), ("Zzz", ["A", "C"])],
                              ["A", "B", "C"])
    return out


def shelf_set(shop, *, flag_negation: bool | None = None, hash_base: int = 100) -> list[dict]:
    actors = []
    for index, gyaml in enumerate(shop.stock):
        a = {"Gyaml": gyaml, "Hash": U64(hash_base + index), "Translate": [float(index), 0.0, 0.0]}
        if index:
            a["Dynamic"] = {"ShopItemIndex": index}
        if flag_negation is not None:
            a["Presence"] = {"FlagName": "Meet_DekuTree_IsAfter_Step02_Exp", "IsNegation": flag_negation}
        actors.append(a)
    return actors


CHEST = {"Gyaml": "Obj_TBox_A_01", "Hash": U64(1),
         "Dynamic": {"DefaultDungeonRoomIndex": 0, "Drop__DropActor": "TBox_Rupee_Green"}}


def _shop(name: str):
    return next(s for s in SHOPS if s.name == name)


def kokiri_child_scene() -> bytes:
    kokiri = _shop("Kokiri Shop")
    actors = ([{"Gyaml": "Npc_Kokiri_001_Shop_Child", "Hash": U64(2)}, dict(CHEST)]
              + shelf_set(kokiri, flag_negation=False) + shelf_set(kokiri, flag_negation=True, hash_base=200))
    return B({"Actors": actors, "FilePath": "Work/Banc/KokiriForest/KokiriForest_Child_Static.bcett.json"})


def simple_scene(shop_names: list[str], path: str) -> bytes:
    actors = []
    for k, name in enumerate(shop_names):
        actors += shelf_set(_shop(name), hash_base=1000 * (k + 1))
    return B({"Actors": actors, "FilePath": path})


def game_data_list() -> bytes:
    return B({
        "Data": {"Bool": [{"DefaultValue": False, "Hash": U32(1), "ResetTypeValue": 9, "SaveFileIndex": 0}]},
        "MetaData": {
            "AllDataSaveOffset": U32(96984), "AllDataSaveSize": U32(781740),
            "SaveDataOffsetPos": [U32(86880), U32(560), U32(672), U32(320)],
            "SaveDataSize": [U32(686828), U32(1004), U32(42356), U32(320)],
        },
    })


SCENES = {
    "KokiriForest/KokiriForest_Child_Static": None,
    "KokiriForest/KokiriForest_Adult_Static": ["Kokiri Shop"],
    "Market/Market_Child_Static": ["Bazaar", "Potion Shop", "Bombchu Shop", "Mask Shop"],
    "KakarikoVillage/KakarikoVillage_Adult_Static": ["Bazaar", "Potion Shop"],
    "KakarikoVillage/KakarikoVillage_Adult_Alternative_Static": ["Bazaar", "Potion Shop"],
}
SHOP_PLAN = [("Kokiri Shop Slot 0", "Item_Hookshot", 150), ("Bazaar Slot 6", "Item_Range_Bow", 35)]


def build_shop_nup(tmp: Path) -> tuple[Path, bytes]:
    zsdic, did = ts.train_dicts()
    dicts = _load_dicts_from_sarc(zsdic)
    cctx = zstandard.ZstdCompressor(dict_data=zstandard.ZstdCompressionDict(dicts[did]))
    tables = rsdb_tables()

    def tree(product: str) -> dict[str, bytes]:
        t = {f"romfs/Pack/Actor/{TEMPLATE}.pack.zs": cctx.compress(template_pack())}
        for item in ITEMS:
            t[f"romfs/Pack/Actor/{item}.pack.zs"] = cctx.compress(item_pack(item))
        sizes = {}
        for scene, shops in SCENES.items():
            data = kokiri_child_scene() if shops is None else simple_scene(shops, f"Work/Banc/{scene}.bcett.json")
            t[f"romfs/Banc/{scene}.bcett.byml.zs"] = cctx.compress(data)
            sizes[f"Banc/{scene}.bcett.byml"] = 8192
        for kind, data in tables.items():
            t[f"romfs/RSDB/{kind}.{product}.rstbl.byml.zs"] = cctx.compress(data)
            sizes[f"RSDB/{kind}.{product}.rstbl.byml"] = 8192
        if tsk.RAW_FLOW.exists():
            t["romfs/Event/EventFlow/GatheringTokenGold.bfevfl.zs"] = cctx.compress(tsk.RAW_FLOW.read_bytes())
            sizes["Event/EventFlow/GatheringTokenGold.bfevfl"] = 65536
        if tso.RAW_FLOW.exists():
            t["romfs/Event/EventFlow/DisplayShop.bfevfl.zs"] = cctx.compress(tso.RAW_FLOW.read_bytes())
            sizes["Event/EventFlow/DisplayShop.bfevfl"] = 262144
        t[f"romfs/System/Resource/ResourceSizeTable.{product}.rsizetable.zs"] = \
            zstandard.ZstdCompressor().compress(ts._restbl(sizes))
        t[f"romfs/GameData/{GAME_DATA_LIST}"] = cctx.compress(game_data_list())
        t["exefs/main"] = b"\x00" * 64
        return t

    src = tmp / "src"
    tnf._write_tree(src / "base", tree("Product.100"))
    tnf._write_tree(src / "updates" / "131072", tree("Product.111"))
    nup = tmp / "shops.nup"
    tnf.pack(str(nup), str(src), names={None: "Synthetic Test Title " * 75})
    tnf.move_meta_before_blob(nup, slack=2048)
    (tmp / "ZsDic.pack").write_bytes(zsdic)
    return nup, zsdic


CHEST_PATCH = PatchRecord(
    location_name="KokiriForest Static room 0 #0 (TBox_Rupee_Green)", scene="KokiriForest", check_type="chest",
    check_index=-1, vanilla_item="TBox_Rupee_Green", replacement_item="Item_Boomerang", byte_offset=None,
    scene_file="KokiriForest_Child_Static.bcett.byml.zs", room_index=0, chest_order=0)


class ShopPatchPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.pristine, cls.zsdic = build_shop_nup(cls.tmp / "pristine")
        cls.dicts = _load_dicts_from_sarc(cls.zsdic)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def copy(self, name: str) -> Path:
        d = self.tmp / name
        d.mkdir()
        shutil.copy(self.pristine, d / "test.nup")
        shutil.copy(self.pristine.with_name("ZsDic.pack"), d / "ZsDic.pack")
        return d / "test.nup"

    def read(self, nup: Path, pkg: int, path: str) -> bytes | None:
        with tnf.NupReader(str(nup)) as r:
            ref = tnf.resolve_path(r, r.packages[pkg], "romfs/" + path)
            return None if ref is None else _decompress(r.read_file(ref.index), self.dicts)

    def restbl_size(self, nup: Path, pkg: int, product: str, path: str) -> int | None:
        raw = tnf.snapshot(nup)[(pkg, f"romfs/System/Resource/ResourceSizeTable.{product}.rsizetable.zs")]
        table = zstandard.ZstdDecompressor().decompressobj().decompress(raw)
        off = _restbl_entry_offset(table, path)
        return None if off is None else struct.unpack_from("<I", table, off)[0]

    def assert_final_state(self, nup: Path, skulls: bool, gamedata: bool = True):
        ok, problems = tnf.verify(str(nup), deep=True)
        self.assertTrue(ok, problems)
        for pkg, product in ((0, "Product.100"), (1, "Product.111")):
            child = parse_byml7(self.read(nup, pkg, "Banc/KokiriForest/KokiriForest_Child_Static.bcett.byml.zs"))["Actors"]
            gy = [a["Gyaml"] for a in child]
            self.assertEqual(gy.count("Shop_Rando_Item_Hookshot"), 2, pkg)  # both Kokiri shelf sets
            self.assertNotIn("Shop_Heart", gy)
            self.assertEqual(gy.count("Shop_DekuNutBundle_01"), 2)  # other slots untouched
            self.assertEqual(child[1]["Dynamic"]["Drop__DropActor"], "Item_Boomerang", pkg)  # chest patch
            adult = [a["Gyaml"] for a in parse_byml7(
                self.read(nup, pkg, "Banc/KokiriForest/KokiriForest_Adult_Static.bcett.byml.zs"))["Actors"]]
            self.assertEqual(adult.count("Shop_Rando_Item_Hookshot"), 1)
            for scene in ("Market/Market_Child_Static", "KakarikoVillage/KakarikoVillage_Adult_Static",
                          "KakarikoVillage/KakarikoVillage_Adult_Alternative_Static"):
                gy = [a["Gyaml"] for a in parse_byml7(self.read(nup, pkg, f"Banc/{scene}.bcett.byml.zs"))["Actors"]]
                self.assertEqual(gy.count("Shop_Rando_Item_Range_Bow"), 1, scene)
                self.assertNotIn("Shop_Weapon_Shield_Hylian", gy)
                self.assertIn("Shop_Bottle_Fish", gy)
            rows = parse_byml7(self.read(nup, pkg, f"RSDB/PouchActorInfo.{product}.rstbl.byml.zs"))
            prices = {r["__RowId"]: r.get("BuyingPrice") for r in rows}
            self.assertEqual(prices["Shop_Rando_Item_Hookshot"], 150)
            self.assertEqual(prices["Shop_Rando_Item_Range_Bow"], 35)
            self.assertEqual(tag_names(self.read(nup, pkg, f"RSDB/Tag.{product}.rstbl.byml.zs"),
                                       "Shop_Rando_Item_Range_Bow"), ["B", "C"])
            for item in ITEMS:
                self.assertIsNotNone(self.restbl_size(nup, pkg, product, f"Pack/Actor/Shop_Rando_{item}.pack"))
            self.assertGreater(self.restbl_size(nup, pkg, product, "Banc/KokiriForest/KokiriForest_Child_Static.bcett.byml"), 8192)
            if skulls:
                self.assertEqual(tsk._rewards_in(self.read(nup, pkg, "Event/EventFlow/GatheringTokenGold.bfevfl.zs"))[20],
                                 "Item_Range_Bow")
            gdl = parse_byml7(self.read(nup, pkg, "GameData/" + GAME_DATA_LIST))
            bool_hashes = [int(e["Hash"]) for e in gdl["Data"]["Bool"]]
            self.assertEqual(len(bool_hashes), len(set(bool_hashes)), pkg)
            for name in SHOP_SOLDOUT_NAMES if gamedata else ():
                self.assertIn(murmur3_32(name.encode()), bool_hashes, (pkg, name))
            if gamedata and tso.RAW_FLOW.exists():
                flow = self.read(nup, pkg, "Event/EventFlow/DisplayShop.bfevfl.zs")
                self.assertEqual(patch_kokiri_soldout(flow), flow, pkg)  # already patched, nothing more to do
            self.assertEqual(gdl["MetaData"]["SaveDataSize"][0], 686829 if gamedata else 686828)
        for item in ITEMS:
            self.assertIsNotNone(self.read(nup, 1, f"Pack/Actor/Shop_Rando_{item}.pack.zs"))
            self.assertIsNone(self.read(nup, 0, f"Pack/Actor/Shop_Rando_{item}.pack.zs"))

    def test_rom_patcher_applies_shops_first(self):
        nup = self.copy("shops_first")
        skulls = {20: "Item_Range_Bow"} if tsk.RAW_FLOW.exists() else None
        res = RomPatcher().apply(nup, [CHEST_PATCH], None, skulls, SHOP_PLAN)
        self.assertEqual(res.mode, "binary")
        self.assertEqual(sorted(res.shop_actors), ["Shop_Rando_Item_Hookshot", "Shop_Rando_Item_Range_Bow"])
        self.assert_final_state(nup, skulls is not None)

    def test_shops_after_replace_file_patches_is_also_valid(self):
        nup = self.copy("shops_last")
        skulls = {20: "Item_Range_Bow"} if tsk.RAW_FLOW.exists() else None
        res = RomPatcher().apply(nup, [CHEST_PATCH], None, skulls)
        self.assertEqual(res.mode, "binary")
        ok, problems = tnf.verify(str(nup), deep=True)
        self.assertTrue(ok, problems)
        apply_shop_slots(nup, self.zsdic, SHOP_PLAN)
        self.assert_final_state(nup, skulls is not None, gamedata=False)

    def test_bad_assignments_fail_before_writing(self):
        nup = self.copy("bad")
        before = nup.read_bytes()
        with self.assertRaises(ShopError):
            RomPatcher().apply(nup, [CHEST_PATCH], None, None, [("Kokiri Shop Slot 9", "Item_Hookshot", 10)])
        with self.assertRaises(ShopError):  # Item_Longshot has no pack in this NUP
            RomPatcher().apply(nup, [], None, None, [("Kokiri Shop Slot 2", "Item_Longshot", 10)])
        self.assertEqual(nup.read_bytes(), before)

    def test_toc_room_check(self):
        nup = self.copy("toc")
        capacity = shop_actor_capacity(nup)
        self.assertGreater(capacity, 2)
        check_toc_room(nup, ["Item_Hookshot", "Item_Range_Bow"])
        many = sorted(i for i in SHOP_ITEM_PACKS if can_sell(i))
        self.assertGreater(len(many), capacity)
        before = nup.read_bytes()
        with self.assertRaisesRegex(ShopError, "TOC"):
            check_toc_room(nup, many)
        plan = [(name, item, 10) for name, item in zip(ALL_SHOP_SLOTS, many)]
        self.assertGreater(len(plan), capacity)
        with self.assertRaisesRegex(ShopError, "TOC"):
            apply_shop_slots(nup, self.zsdic, plan)
        self.assertEqual(nup.read_bytes(), before)

    def test_failure_after_shops_is_raised_not_hidden(self):
        missing_song = {"Dm_MelodyGet_Zelda.bfevfl.zs": "Item_Melody_SariaSong"}  # flow not in this NUP
        nup = self.copy("raise")
        self.assertEqual(RomPatcher().apply(nup, [CHEST_PATCH], missing_song).mode, "manifest-only")
        with self.assertRaises(Exception):
            RomPatcher().apply(nup, [CHEST_PATCH], missing_song, None, SHOP_PLAN)

    def test_non_nup_file_stays_manifest_only(self):
        d = self.tmp / "fake"
        d.mkdir()
        fake = d / "fake.nup"
        fake.write_bytes(b"NUP!" + b"\x00" * 60)
        shutil.copy(self.pristine.with_name("ZsDic.pack"), d / "ZsDic.pack")
        res = RomPatcher().apply(fake, [CHEST_PATCH], None, None, SHOP_PLAN)
        self.assertEqual(res.mode, "manifest-only")
        self.assertEqual(res.shop_actors, [])


if __name__ == "__main__":
    unittest.main()
