import unittest

from oot_randomizer.byml7 import U64, dump_byml7, parse_byml7_typed
from oot_randomizer.engine import load_default_slots
from oot_randomizer.heart_pickups import (
    FIRE_ARROW_ITEM,
    FIRE_ARROW_LOCATIONS,
    HEART_LOCATIONS,
    HEART_SLOTS,
    can_pickup,
    heart_actor_name,
    heart_items_for,
    heart_pack_names,
    set_heart_actor,
)
from oot_randomizer.planner import PlanOptions, plan_seed
from oot_randomizer.shops import ShopError

B = dump_byml7


def scene(actors: list[dict]) -> bytes:
    return B({"Actors": actors, "FilePath": "Work/Banc/Forest/Forest_Static.bcett.json"})


def heart(translate=(0.0, 0.0, 0.0)) -> dict:
    return {"Gyaml": "Obj_Heart_Piece", "Hash": U64(7), "Translate": list(translate)}


HEART_ACTORS = [
    {"Gyaml": "Npc_Shopkeeper", "Hash": U64(1), "Translate": [0.0, 0.0, 0.0]},
    heart((1.0, 2.0, 3.0)),
    {**heart((4.0, 5.0, 6.0)), "Dynamic": {"Drop": True}},
    {"Gyaml": "Obj_TBox_A_Heart", "Hash": U64(9), "Translate": [0.0, 0.0, 0.0]},
    {"Gyaml": "Obj_GerudoValley_Heart_Piece", "Hash": U64(10), "Translate": [4.0, 59.0, -78.0]},
]


class SlotTableTests(unittest.TestCase):
    def test_fourteen_slots_each_with_shelves(self):
        self.assertEqual(len(HEART_LOCATIONS), 14)
        self.assertIn("GerudoValley Heart Piece 1", HEART_LOCATIONS)
        self.assertEqual(FIRE_ARROW_LOCATIONS, {"LakeHylia Fire Arrow 1"})
        self.assertFalse(FIRE_ARROW_LOCATIONS & HEART_LOCATIONS)
        for name, slot in HEART_SLOTS.items():
            self.assertEqual(slot.name, name)
            self.assertTrue(slot.shelves, name)

    def test_fire_arrow_slot_points_at_the_sun_reward_actor(self):
        shelves = HEART_SLOTS["LakeHylia Fire Arrow 1"].shelves
        self.assertEqual([(s.scene, s.select) for s in shelves],
                         [("HyruleField_Adult_Static.bcett.byml.zs", 1732)])
        self.assertEqual(FIRE_ARROW_ITEM, "Item_Arrow_Fire")

    def test_pickups_are_the_shop_pickup_set(self):
        self.assertTrue(can_pickup("Item_Hookshot"))
        for item in ("Item_Dungeon_Map", "Item_Melody_Zelda_Lullaby", "Item_Token_Gold", "Obj_Heart_Piece"):
            self.assertFalse(can_pickup(item), item)
        self.assertEqual(heart_actor_name("Item_Hookshot"), "Obj_HeartRando_Item_Hookshot")

    def test_gauntlets_are_heart_pickups(self):
        for item in ("Item_Gauntlet_Silver", "Item_Gauntlet_Gold", "Item_Gauntlet_Goron"):
            self.assertTrue(can_pickup(item), item)


class SetHeartActorTests(unittest.TestCase):
    def setUp(self):
        self.data = scene(HEART_ACTORS)

    def test_changes_only_the_gyaml_of_a_loose_piece(self):
        changed = []
        out = set_heart_actor(self.data, 1, "Obj_HeartRando_Item_Hookshot", changed=changed)
        self.assertEqual(changed, [1])
        before, after = parse_byml7_typed(self.data), parse_byml7_typed(out)
        self.assertEqual(after["Actors"][1]["Gyaml"], "Obj_HeartRando_Item_Hookshot")
        after["Actors"][1]["Gyaml"] = "Obj_Heart_Piece"
        self.assertEqual(after, before)

    def test_rejects_chest_dynamic_and_non_heart_actors(self):
        for index in (0, 2, 3):
            with self.assertRaises(ShopError, msg=f"index {index}"):
                set_heart_actor(self.data, index, "Obj_HeartRando_Item_Hookshot")

    def test_accepts_the_fire_arrow_loose_actor(self):
        arrow = {"Gyaml": "Obj_Arrow_Fire", "Hash": U64(11), "Translate": [0.0, 0.0, 0.0]}
        data = scene([arrow])
        out = set_heart_actor(data, 0, "Obj_HeartRando_Item_Hookshot")
        self.assertEqual(parse_byml7_typed(out)["Actors"][0]["Gyaml"], "Obj_HeartRando_Item_Hookshot")

    def test_accepts_the_gerudo_valley_loose_piece(self):
        out = set_heart_actor(self.data, 4, "Obj_HeartRando_Item_Hookshot")
        self.assertEqual(parse_byml7_typed(out)["Actors"][4]["Gyaml"], "Obj_HeartRando_Item_Hookshot")

    def test_rejects_out_of_range_bool_and_multiple(self):
        for index in (-1, 99, True):
            with self.assertRaises(ShopError, msg=repr(index)):
                set_heart_actor(self.data, index, "Obj_HeartRando_Item_Hookshot")
        with self.assertRaises(ShopError):
            set_heart_actor(self.data, 1, "Obj_HeartRando_Item_Hookshot", allow_multiple=True)


class HeartItemsTests(unittest.TestCase):
    def test_duplicate_items_share_one_clone(self):
        items = heart_items_for([("ZoraRiver Heart Piece 1", "Item_Hookshot"),
                                 ("Graveyard Heart Piece 1", "Item_Hookshot"),
                                 ("ZoraRiver Heart Piece 2", "Item_Bomb")])
        self.assertEqual([item for item, _, _ in items], ["Item_Hookshot", "Item_Bomb"])
        hookshot_shelves = items[0][2]
        self.assertEqual(len(hookshot_shelves), len(HEART_SLOTS["ZoraRiver Heart Piece 1"].shelves)
                         + len(HEART_SLOTS["Graveyard Heart Piece 1"].shelves))
        self.assertEqual(heart_pack_names([("ZoraRiver Heart Piece 1", "Item_Hookshot"),
                                           ("Graveyard Heart Piece 1", "Item_Hookshot")]),
                         ["Obj_HeartRando_Item_Hookshot"])

    def test_rejects_unknown_slot_and_unpickupable_item(self):
        with self.assertRaises(ShopError):
            heart_items_for([("Nowhere Heart Piece 9", "Item_Hookshot")])
        with self.assertRaises(ShopError):
            heart_items_for([("Graveyard Heart Piece 1", "Item_Dungeon_Map")])


class PlannerHeartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.slots = load_default_slots()

    def test_every_heart_slot_gets_a_pickupable_item(self):
        if not self.slots:
            self.skipTest("chest_locations_summary.json not available")
        for seed in range(5):
            plan = plan_seed(seed, self.slots, None, PlanOptions())
            self.assertEqual({name for name, _ in plan.heart_assignments}, HEART_LOCATIONS | FIRE_ARROW_LOCATIONS, seed)
            for name, item in plan.heart_assignments:
                self.assertTrue(can_pickup(item), (seed, name, item))

    def test_hearts_off_leaves_only_the_fire_arrow(self):
        if not self.slots:
            self.skipTest("chest_locations_summary.json not available")
        plan = plan_seed(1, self.slots, None, PlanOptions(shuffle_heart_pieces=False))
        self.assertEqual({name for name, _ in plan.heart_assignments}, FIRE_ARROW_LOCATIONS)
        placed = ({item for _, item in plan.chest_assignments} | {item for _, item in plan.heart_assignments}
                  | {item for _, item, _ in plan.shop_assignments} | set(plan.npc_assignments.values())
                  | set(plan.song_assignments.values()) | set(plan.event_assignments.values())
                  | set(plan.skull_assignments.values()))
        self.assertIn(FIRE_ARROW_ITEM, placed)


if __name__ == "__main__":
    unittest.main()
