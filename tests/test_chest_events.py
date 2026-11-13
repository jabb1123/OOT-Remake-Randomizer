"""Tests for the sword-chest cutscene fix."""

import unittest

from oot_randomizer.chest_events import SWORD_VANILLA_ITEM
from oot_randomizer.patcher import PatchRecord, sword_chest_moved


def _record(scene: str, vanilla: str, replacement: str) -> PatchRecord:
    return PatchRecord(
        location_name=f"{scene} chest",
        scene=scene,
        check_type="chest",
        check_index=-1,
        vanilla_item=vanilla,
        replacement_item=replacement,
        byte_offset=None,
    )


class SwordChestMovedTests(unittest.TestCase):
    def test_detects_replaced_sword_chest(self):
        self.assertTrue(sword_chest_moved([_record("KokiriForest", SWORD_VANILLA_ITEM, "Item_Gauntlet_Gold")]))

    def test_ignores_sword_left_in_place(self):
        self.assertFalse(sword_chest_moved([_record("KokiriForest", SWORD_VANILLA_ITEM, SWORD_VANILLA_ITEM)]))

    def test_ignores_other_chests(self):
        self.assertFalse(sword_chest_moved([_record("KokiriForest", "TBox_Rupee_Blue", "TBox_Rupee_Red")]))
        self.assertFalse(sword_chest_moved([_record("DekuTree", SWORD_VANILLA_ITEM, "Item_Gauntlet_Gold")]))


if __name__ == "__main__":
    unittest.main()
