import unittest

from oot_randomizer.location_mapper import (
    build_canonical_locations,
    build_location_index,
    build_location_matches,
    load_summary_file,
    normalize_scene_name,
)


class LocationMapperTests(unittest.TestCase):
    def test_normalize_scene_name_matches_known_game_scenes(self):
        self.assertEqual(
            normalize_scene_name("Banc/InsideTheDekuTree/InsideTheDekuTree_Static.bcett.byml.zs"),
            "deku_tree",
        )
        self.assertEqual(
            normalize_scene_name("Banc/DodongoCavern/DodongoCavern_Static.bcett.byml.zs"),
            "dodongos_cavern",
        )
        self.assertEqual(
            normalize_scene_name("Banc/InsideJabuJabuBelly/InsideJabuJabuBelly_Static.bcett.byml.zs"),
            "jabu_jabu",
        )
        self.assertEqual(
            normalize_scene_name("Banc/GerudoValley/GerudoValley_Child_Static.bcett.byml.zs"),
            "gerudo_valley_child",
        )

    def test_build_canonical_locations_from_summary(self):
        summary = [
            {
                "scene_file": "Banc/InsideTheDekuTree/InsideTheDekuTree_Static.bcett.byml.zs",
                "count": 4,
                "chests": [
                    {"gyaml": "Obj_TBox_A_02", "room_index": 3, "vanilla_drop": "Item_Dungeon_Compass"},
                    {"gyaml": "Obj_TBox_A_02", "room_index": 0, "vanilla_drop": "Item_Dungeon_Map"},
                    {"gyaml": "Obj_TBox_A_01", "room_index": 2, "vanilla_drop": "TBox_DekuNutBundle"},
                    {"gyaml": "Obj_TBox_A_02", "room_index": 2, "vanilla_drop": "Item_Range_SlingShot"},
                ],
            }
        ]

        records = build_canonical_locations(summary)
        self.assertEqual(len(records), 4)
        self.assertEqual(records[0]["scene"], "deku_tree")
        self.assertEqual(records[0]["check_index"], 0)
        self.assertEqual(records[0]["vanilla_item"], "Item_Dungeon_Compass")
        self.assertEqual(records[2]["room_index"], 2)
        self.assertEqual(records[2]["vanilla_item"], "TBox_DekuNutBundle")

    def test_build_location_matches_for_known_scene(self):
        summary = [
            {
                "scene_file": "Banc/InsideTheDekuTree/InsideTheDekuTree_Static.bcett.byml.zs",
                "count": 4,
                "chests": [
                    {"gyaml": "Obj_TBox_A_02", "room_index": 0, "vanilla_drop": "Item_Dungeon_Map"},
                    {"gyaml": "Obj_TBox_A_02", "room_index": 1, "vanilla_drop": "Item_Dungeon_Compass"},
                    {"gyaml": "Obj_TBox_A_01", "room_index": 2, "vanilla_drop": "TBox_DekuNutBundle"},
                    {"gyaml": "Obj_TBox_A_02", "room_index": 3, "vanilla_drop": "Item_Range_SlingShot"},
                ],
            }
        ]

        matches = build_location_matches(summary)
        self.assertEqual(matches[0]["location_name"], "Deku Tree Map Chest")
        self.assertEqual(matches[1]["location_name"], "Deku Tree Compass Chest")
        self.assertEqual(matches[2]["scene"], "deku_tree")
        self.assertEqual(matches[3]["location_name"], "Deku Tree Boss Key Chest")

    def test_load_summary_and_build_scene_index(self):
        summary = [
            {
                "scene_file": "Banc/InsideTheDekuTree/InsideTheDekuTree_Static.bcett.byml.zs",
                "count": 4,
                "chests": [
                    {"gyaml": "Obj_TBox_A_02", "room_index": 0, "vanilla_drop": "Item_Dungeon_Map"},
                    {"gyaml": "Obj_TBox_A_02", "room_index": 1, "vanilla_drop": "Item_Dungeon_Compass"},
                    {"gyaml": "Obj_TBox_A_01", "room_index": 2, "vanilla_drop": "TBox_DekuNutBundle"},
                    {"gyaml": "Obj_TBox_A_02", "room_index": 3, "vanilla_drop": "Item_Range_SlingShot"},
                ],
            }
        ]

        index = build_location_index(summary)
        self.assertIn("deku_tree", index)
        self.assertEqual(len(index["deku_tree"]), 4)

        loaded = load_summary_file("/Users/jacob/Desktop/Roms/oot_randomizer/chest_locations_summary.json")
        self.assertTrue(loaded)


if __name__ == "__main__":
    unittest.main()
