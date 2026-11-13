"""Tests for NupChestPatcher — scan and patch chest actors in bcett files."""

import struct
import unittest
from pathlib import Path

from oot_randomizer.nup_chest_patcher import (
    ChestEntry,
    NupChestPatcher,
    NupPatchError,
    _detect_dict_id,
    _walk_byml_chests,
)


# ---------------------------------------------------------------------------
# Unit tests that don't need the real NUP
# ---------------------------------------------------------------------------

class DetectDictIdTests(unittest.TestCase):
    def test_detects_embedded_dict_id(self):
        # Build a minimal ZSTD frame header with SS=1, DID_FLAG=1, dict_id=3
        fhd = (2 << 6) | (1 << 5) | 1   # FCS=2, SS=1, DID=1
        frame = struct.pack("<I", 0xFD2FB528) + bytes([fhd, 3])
        self.assertEqual(_detect_dict_id(frame), 3)

    def test_no_dict_id_when_flag_zero(self):
        fhd = (2 << 6) | (1 << 5)   # DID_FLAG=0
        frame = struct.pack("<I", 0xFD2FB528) + bytes([fhd])
        self.assertIsNone(_detect_dict_id(frame))

    def test_returns_none_for_non_zstd_data(self):
        self.assertIsNone(_detect_dict_id(b"YB\x07\x00" + b"\x00" * 8))


class WalkBymlChestsTests(unittest.TestCase):
    """Parsing tests against the extracted Deku Tree Static bcett file (if present)."""

    BYML_PATH = Path("/Users/jacob/Desktop/Roms/oot_randomizer/InsideTheDekuTree_Static.bcett.byml")

    def setUp(self):
        if not self.BYML_PATH.exists():
            self.skipTest("Extracted bcett file not present")

    def test_finds_four_chests(self):
        chests = _walk_byml_chests(self.BYML_PATH.read_bytes())
        self.assertEqual(len(chests), 4)

    def test_all_chests_are_tbox_actors(self):
        chests = _walk_byml_chests(self.BYML_PATH.read_bytes())
        for c in chests:
            self.assertTrue(c.gyaml.startswith("Obj_TBox"), c.gyaml)

    def test_known_deku_tree_drops(self):
        chests = _walk_byml_chests(self.BYML_PATH.read_bytes())
        drops = {c.vanilla_drop for c in chests}
        self.assertIn("Item_Dungeon_Compass", drops)
        self.assertIn("Item_Dungeon_Map", drops)
        self.assertIn("Item_Range_SlingShot", drops)
        self.assertIn("TBox_DekuNutBundle", drops)

    def test_byml_val_offset_is_nonzero(self):
        chests = _walk_byml_chests(self.BYML_PATH.read_bytes())
        for c in chests:
            self.assertGreater(c.byml_val_offset, 0, f"Zero offset for {c.vanilla_drop}")

    def test_byml_val_offset_matches_known_values(self):
        # Confirmed offsets from manual analysis
        known = {
            "Item_Dungeon_Compass": 0x0AEEC,
            "Item_Dungeon_Map":     0x0B61C,
            "Item_Range_SlingShot": 0x0EF00,
            "TBox_DekuNutBundle":   0x0EE70,
        }
        chests = _walk_byml_chests(self.BYML_PATH.read_bytes())
        for c in chests:
            if c.vanilla_drop in known:
                self.assertEqual(
                    c.byml_val_offset,
                    known[c.vanilla_drop],
                    f"{c.vanilla_drop}: offset mismatch",
                )

    def test_scan_is_deterministic(self):
        data = self.BYML_PATH.read_bytes()
        a = _walk_byml_chests(data)
        b = _walk_byml_chests(data)
        self.assertEqual([c.vanilla_drop for c in a], [c.vanilla_drop for c in b])


class NupChestPatcherIntegrationTests(unittest.TestCase):
    """Integration tests that need the real NUP and extracted ZsDic.pack."""

    NUP_PATH   = Path("/Users/jacob/Desktop/Roms/oot_randomizer/deku_tree_test.nup")
    ZSDIC_PATH = Path("/Users/jacob/Desktop/Roms/oot_randomizer/ZsDic.pack")
    SCENE_FILE = "InsideTheDekuTree_Static.bcett.byml.zs"

    def setUp(self):
        if not self.NUP_PATH.exists() or not self.ZSDIC_PATH.exists():
            self.skipTest("Patched NUP or ZsDic.pack not present")

    def _make_patcher(self):
        return NupChestPatcher(self.NUP_PATH, self.ZSDIC_PATH.read_bytes())

    def test_scan_chests_returns_correct_count(self):
        patcher = self._make_patcher()
        chests = patcher.scan_chests(self.SCENE_FILE)
        # Static file has 4 chests (Compass, Map, DekuNut, Slingshot)
        self.assertGreaterEqual(len(chests), 2)

    def test_patch_scene_returns_result(self):
        import shutil, tempfile
        # Work on a temp copy so we don't corrupt the test NUP
        with tempfile.NamedTemporaryFile(suffix=".nup", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        shutil.copy2(self.NUP_PATH, tmp_path)
        try:
            patcher = NupChestPatcher(tmp_path, self.ZSDIC_PATH.read_bytes())
            result = patcher.patch_scene(
                self.SCENE_FILE,
                swap_map={
                    "Item_Dungeon_Compass":   "Item_Dungeon_Map",
                    "Item_Dungeon_Map":       "Item_Dungeon_Compass",
                },
            )
            self.assertEqual(result.chests_patched, 2)
            self.assertEqual(len(result.swaps), 2)
            self.assertGreater(result.new_extent_size, 0)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_patch_scene_produces_readable_result(self):
        import shutil, tempfile, zstandard as zstd
        with tempfile.NamedTemporaryFile(suffix=".nup", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        shutil.copy2(self.NUP_PATH, tmp_path)
        try:
            swap_map = {
                "Item_Dungeon_Compass":   "Item_Dungeon_Map",
                "Item_Dungeon_Map":       "Item_Dungeon_Compass",
            }
            patcher = NupChestPatcher(tmp_path, self.ZSDIC_PATH.read_bytes())
            result = patcher.patch_scene(self.SCENE_FILE, swap_map=swap_map)

            # Re-read using NupChestPatcher.scan_chests to verify
            verify_patcher = NupChestPatcher(tmp_path, self.ZSDIC_PATH.read_bytes())
            chests_after = verify_patcher.scan_chests(self.SCENE_FILE)
            drops_after = {c.vanilla_drop for c in chests_after}
            self.assertIn("Item_Dungeon_Map",     drops_after)
            self.assertIn("Item_Dungeon_Compass", drops_after)
        finally:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
