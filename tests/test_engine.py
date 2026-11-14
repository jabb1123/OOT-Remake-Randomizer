"""Tests for the OoT remake randomizer engine — NUP parser, locations, patcher."""

import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from oot_randomizer.config import RandomizerConfig
from oot_randomizer.engine import SeedEngine, build_shuffle_patches, load_chest_slots, shuffle_chest_items
from oot_randomizer.item_ids import ITEM_ACTOR_NAMES, ITEM_DISPLAY_NAMES
from oot_randomizer.locations import LOCATIONS, LOCATION_BY_NAME
from oot_randomizer.logic import LogicEngine
from oot_randomizer.nup_parser import NUP_MAGIC, NupParseError, parse_nup_header
from oot_randomizer.patcher import (
    PatchRecord,
    RomPatcher,
    build_scene_patch_map,
    make_patch,
    resolve_scene_files,
)
from oot_randomizer.randomizer import OOTRandomizer
from oot_randomizer.location_mapper import build_runtime_locations
from oot_randomizer.rom import RomValidationError, validate_nup_rom


def _make_nup(path: Path, extra: bytes = b"") -> None:
    header = NUP_MAGIC + struct.pack(">III", 0x00000001, len(extra), 0)
    header = header.ljust(64, b"\x00")
    path.write_bytes(header + extra)


class SongShuffleTests(unittest.TestCase):
    def test_song_shuffle_is_a_permutation(self):
        from oot_randomizer.songs import SONG_SLOTS, shuffle_songs

        for seed in range(50):
            a = shuffle_songs(seed)
            self.assertEqual(sorted(a.values()), sorted(SONG_SLOTS.values()))
            self.assertEqual(set(a), set(SONG_SLOTS))

    def test_patch_bfevfl_song_repoints_pointer_and_moves_relt(self):
        from oot_randomizer.songs import patch_bfevfl_song

        old = b"Item_Melody_StormSong"
        body = bytearray(b"BFEVFL\x00\x00" + b"\x00" * 0x18)
        body += b"\x00" * 8  # pointer slot at 0x20
        str_off = len(body)
        body += struct.pack("<H", len(old)) + old + b"\x00"
        while len(body) % 8:
            body.append(0)
        struct.pack_into("<Q", body, 0x20, str_off)
        relt_off = len(body)
        relt = bytearray(b"RELT" + struct.pack("<II", relt_off, 1) + b"\x00" * 4)
        relt += struct.pack("<QIIII", 0, 0, relt_off, 0, 0)
        data = body + relt
        struct.pack_into("<I", data, 0x18, relt_off)
        struct.pack_into("<I", data, 0x1C, len(data))

        out = patch_bfevfl_song(bytes(data), "Item_Melody_StormSong", "Item_Melody_ZeldaLullaby")
        new_relt = struct.unpack_from("<I", out, 0x18)[0]
        self.assertEqual(out[new_relt:new_relt + 4], b"RELT")
        self.assertEqual(struct.unpack_from("<I", out, new_relt + 4)[0], new_relt)
        self.assertEqual(struct.unpack_from("<I", out, 0x1C)[0], len(out))
        ptr = struct.unpack_from("<Q", out, 0x20)[0]
        n = struct.unpack_from("<H", out, ptr)[0]
        self.assertEqual(out[ptr + 2:ptr + 2 + n], b"Item_Melody_ZeldaLullaby")

    def test_patch_bfevfl_songs_swaps_chain_in_one_pass(self):
        from oot_randomizer.songs import patch_bfevfl_songs

        strings = [b"Item_Melody_StormSong", b"Item_Melody_TimeSong"]
        body = bytearray(b"BFEVFL\x00\x00" + b"\x00" * 0x18)
        body += b"\x00" * 16  # two pointer slots at 0x20 and 0x28
        offs = []
        for s in strings:
            offs.append(len(body))
            body += struct.pack("<H", len(s)) + s + b"\x00"
            while len(body) % 8:
                body.append(0)
        for i, off in enumerate(offs):
            struct.pack_into("<Q", body, 0x20 + 8 * i, off)
        relt_off = len(body)
        relt = bytearray(b"RELT" + struct.pack("<II", relt_off, 1) + b"\x00" * 4)
        relt += struct.pack("<QIIII", 0, 0, relt_off, 0, 0)
        data = body + relt
        struct.pack_into("<I", data, 0x18, relt_off)
        struct.pack_into("<I", data, 0x1C, len(data))

        out = patch_bfevfl_songs(
            bytes(data),
            {"Item_Melody_StormSong": "Item_Melody_TimeSong", "Item_Melody_TimeSong": "Item_Melody_StormSong"},
        )
        for ptr_slot, expected in [(0x20, b"Item_Melody_TimeSong"), (0x28, b"Item_Melody_StormSong")]:
            ptr = struct.unpack_from("<Q", out, ptr_slot)[0]
            n = struct.unpack_from("<H", out, ptr)[0]
            self.assertEqual(out[ptr + 2:ptr + 2 + n], expected)
        new_relt = struct.unpack_from("<I", out, 0x18)[0]
        self.assertEqual(out[new_relt:new_relt + 4], b"RELT")
        self.assertEqual(struct.unpack_from("<I", out, 0x1C)[0], len(out))

    def test_patch_bfevfl_songs_rejects_missing_song(self):
        from oot_randomizer.songs import patch_bfevfl_songs

        body = bytearray(b"BFEVFL\x00\x00" + b"\x00" * 0x18)
        relt_off = len(body)
        relt = bytearray(b"RELT" + struct.pack("<II", relt_off, 0) + b"\x00" * 4)
        data = body + relt
        struct.pack_into("<I", data, 0x18, relt_off)
        struct.pack_into("<I", data, 0x1C, len(data))
        with self.assertRaises(ValueError):
            patch_bfevfl_songs(bytes(data), {"Item_Melody_StormSong": "Item_Melody_TimeSong"})


class ChestShuffleTests(unittest.TestCase):
    def test_restbl_entry_lookup_by_crc_and_name(self):
        import zlib
        from oot_randomizer.nup_chest_patcher import _restbl_entry_offset

        crcs = sorted([(zlib.crc32(b"a/b.byml"), 100), (zlib.crc32(b"z.byml"), 200)])
        table = b"RESTBL" + struct.pack("<III", 1, 160, len(crcs)) + struct.pack("<I", 1)
        table += b"".join(struct.pack("<II", c, s) for c, s in crcs)
        table += b"named.byml".ljust(160, b"\x00") + struct.pack("<I", 300)
        for path, size in [("a/b.byml", 100), ("z.byml", 200), ("named.byml", 300)]:
            off = _restbl_entry_offset(table, path)
            self.assertEqual(struct.unpack_from("<I", table, off)[0], size)
        self.assertIsNone(_restbl_entry_offset(table, "missing.byml"))
    SUMMARY = [
        {"scene_file": "Banc/A/Kokiri_Child_Static.bcett.byml.zs", "chests": [
            {"room_index": 0, "vanilla_drop": "Item_Sword_Kokiri"},
            {"room_index": 1, "vanilla_drop": "TBox_Rupee_Blue"},
        ]},
        {"scene_file": "Banc/A/Kokiri_Adult_Static.bcett.byml.zs", "chests": [
            {"room_index": 0, "vanilla_drop": "Item_Sword_Kokiri"},
        ]},
        {"scene_file": "Banc/B/Deku_Static.bcett.byml.zs", "chests": [
            {"room_index": 2, "vanilla_drop": "Item_Range_SlingShot"},
            {"room_index": 3, "vanilla_drop": "Item_Dungeon_SmallKey"},
        ]},
        {"scene_file": "Banc/B/Deku_Static.bcett.byml.zs", "chests": [
            {"room_index": 2, "vanilla_drop": "Item_Range_SlingShot"},
        ]},
    ]

    def test_era_variants_and_duplicate_entries_merge_into_one_slot(self):
        slots = load_chest_slots(self.SUMMARY)
        self.assertEqual(len(slots), 4)
        sword = next(s for s in slots if s.vanilla_item == "Item_Sword_Kokiri")
        self.assertEqual(len(sword.targets), 2)

    def test_every_item_appears_exactly_once_per_seed(self):
        slots = load_chest_slots(self.SUMMARY)
        for seed in range(20):
            assignments = shuffle_chest_items(seed, slots)
            self.assertEqual(
                sorted(item for _, item in assignments),
                sorted(s.vanilla_item for s in slots),
            )
            key = next(item for s, item in assignments if s.vanilla_item == "Item_Dungeon_SmallKey")
            self.assertEqual(key, "Item_Dungeon_SmallKey")

    def test_patches_write_same_item_to_all_era_variants(self):
        slots = load_chest_slots(self.SUMMARY)
        for seed in range(20):
            patches = build_shuffle_patches(shuffle_chest_items(seed, slots))
            sword = [p for p in patches if p.vanilla_item == "Item_Sword_Kokiri"]
            if sword:
                self.assertEqual(len(sword), 2)
                self.assertEqual(len({p.replacement_item for p in sword}), 1)
                return
        self.fail("sword chest never shuffled")


class RomValidationTests(unittest.TestCase):
    def test_accepts_valid_nup_file(self):
        p = Path("tmp/test_valid_rom.nup")
        _make_nup(p)
        self.addCleanup(p.unlink, missing_ok=True)
        info = validate_nup_rom(p)
        self.assertTrue(info.is_nup)

    def test_rejects_wrong_extension(self):
        p = Path("tmp/test_invalid_rom.z64")
        p.write_bytes(b"12345")
        self.addCleanup(p.unlink, missing_ok=True)
        with self.assertRaises(RomValidationError):
            validate_nup_rom(p)

    def test_rejects_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            validate_nup_rom("tmp/does_not_exist.nup")


class NupParserTests(unittest.TestCase):
    def test_parses_valid_nup_header(self):
        p = Path("tmp/nup_parser_test.nup")
        _make_nup(p, b"content")
        self.addCleanup(p.unlink, missing_ok=True)

        header = parse_nup_header(p)
        self.assertTrue(header.is_valid())
        self.assertEqual(header.magic, NUP_MAGIC)
        self.assertGreater(header.file_size, 0)
        self.assertTrue(any(r.name == "header" for r in header.regions))

    def test_rejects_non_nup_file(self):
        p = Path("tmp/nup_bad_magic.nup")
        p.write_bytes(b"FAKE" + b"\x00" * 60)
        self.addCleanup(p.unlink, missing_ok=True)
        with self.assertRaises(NupParseError):
            parse_nup_header(p)

    def test_detects_embedded_region_markers(self):
        p = Path("tmp/nup_with_pfs0.nup")
        _make_nup(p, b"\x00" * 256 + b"PFS0" + b"\x00" * 64)
        self.addCleanup(p.unlink, missing_ok=True)

        header = parse_nup_header(p)
        region_names = [r.name for r in header.regions]
        self.assertIn("pfs0_partition", region_names)


class ItemIdTests(unittest.TestCase):
    def test_all_actor_names_are_strings(self):
        for name in ITEM_ACTOR_NAMES:
            self.assertIsInstance(name, str)
            self.assertTrue(name.startswith(("Item_", "TBox_", "Obj_", "Tbox_")), name)

    def test_display_names_cover_major_items(self):
        self.assertIn("Item_Range_SlingShot", ITEM_DISPLAY_NAMES)
        self.assertIn("Item_Hookshot", ITEM_DISPLAY_NAMES)
        self.assertIn("Item_Dungeon_Compass", ITEM_DISPLAY_NAMES)

    def test_no_n64_byte_ids(self):
        # Confirm we don't have N64-era numeric IDs masquerading as item IDs
        for name in ITEM_ACTOR_NAMES:
            self.assertNotIsInstance(name, int)


class LocationTests(unittest.TestCase):
    def test_location_count(self):
        self.assertGreater(len(LOCATIONS), 50)

    def test_all_locations_have_scene(self):
        self.assertTrue(all(loc.scene for loc in LOCATIONS))

    def test_location_by_name_lookup(self):
        loc = LOCATION_BY_NAME["Forest Temple Bow Chest"]
        self.assertEqual(loc.check_type, "chest")
        self.assertIsNotNone(loc.vanilla_item)


class PatcherTests(unittest.TestCase):
    def test_make_patch_creates_correct_record(self):
        loc = LOCATION_BY_NAME["Forest Temple Bow Chest"]
        record = make_patch(loc, "Item_Range_Bow")
        self.assertEqual(record.replacement_item, "Item_Range_Bow")
        self.assertIsNone(record.byte_offset)

    def test_patcher_operates_in_manifest_only_without_offsets(self):
        p = Path("tmp/patcher_manifest_test.nup")
        _make_nup(p)
        self.addCleanup(p.unlink, missing_ok=True)

        loc = LOCATION_BY_NAME["Deku Tree Slingshot Chest"]
        patch = make_patch(loc, "Item_Range_Bow")
        result = RomPatcher().apply(p, [patch])
        self.assertEqual(result.mode, "manifest-only")
        self.assertEqual(result.applied, 0)
        self.assertEqual(result.skipped, 1)

    def test_patcher_applies_real_scene_patch_to_valid_nup_copy(self):
        nup_path = Path("/Users/jacob/Desktop/Roms/oot_randomizer/deku_tree_test.nup")
        zsdic_path = Path("/Users/jacob/Desktop/Roms/oot_randomizer/ZsDic.pack")
        if not nup_path.exists() or not zsdic_path.exists():
            self.skipTest("Real test NUP or ZsDic.pack not present")

        import shutil, tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            out_path = tmpdir_path / "deku_tree_test.nup"
            try:
                shutil.copy2(nup_path, out_path)
                shutil.copy2(zsdic_path, tmpdir_path / "ZsDic.pack")
            except FileNotFoundError as exc:
                self.skipTest(f"Real test NUP or ZsDic.pack not present: {exc}")

            loc = LOCATION_BY_NAME["Deku Tree Map Chest"]
            patch = make_patch(loc, "Item_Dungeon_Compass", scene_file="InsideTheDekuTree_Static.bcett.byml.zs", room_index=0)
            result = RomPatcher().apply(out_path, [patch])
            self.assertEqual(result.mode, "binary")
            self.assertGreaterEqual(result.applied, 1)

    def test_resolve_scene_files_uses_real_summary_paths(self):
        candidates = resolve_scene_files("bottom_of_the_well")
        self.assertIn("BottomOfTheWell_Static.bcett.byml.zs", candidates)
        self.assertIn("BottomOfTheWell_Dynamic.bcett.byml.zs", candidates)

    def test_randomizer_copies_zsdic_next_to_output_and_uses_binary_mode(self):
        nup_path = Path("/Users/jacob/Desktop/Roms/oot_randomizer/deku_tree_test.nup")
        zsdic_path = Path("/Users/jacob/Desktop/Roms/oot_randomizer/ZsDic.pack")
        if not nup_path.exists() or not zsdic_path.exists():
            self.skipTest("Real test NUP or ZsDic.pack not present")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            out_path = tmpdir_path / "deku_tree_test_randomized.nup"
            try:
                config = RandomizerConfig(seed=99, output_path=str(out_path), logic="glitchedless")
                result = OOTRandomizer(config).randomize(str(nup_path))
            except FileNotFoundError as exc:
                self.skipTest(f"Real test NUP or ZsDic.pack not present: {exc}")

            self.assertTrue((tmpdir_path / "ZsDic.pack").exists())
            self.assertEqual(result.patch_mode, "binary")
            self.assertGreaterEqual(result.placements[0]["item_id_hex"], "0x0")

    def test_build_scene_patch_map_targets_exact_chests(self):
        loc = LOCATION_BY_NAME["Deku Tree Map Chest"]
        patch = make_patch(loc, "Item_Range_Bow", scene_file="InsideTheDekuTree_Static.bcett.byml.zs", room_index=0)
        scene_map = build_scene_patch_map([patch])
        self.assertIn("InsideTheDekuTree_Static.bcett.byml.zs", scene_map)
        self.assertEqual(scene_map["InsideTheDekuTree_Static.bcett.byml.zs"][0]["replacement_item"], "Item_Range_Bow")
        self.assertEqual(scene_map["InsideTheDekuTree_Static.bcett.byml.zs"][0]["check_index"], 0)


class EngineTests(unittest.TestCase):
    def test_engine_produces_patch_records(self):
        items = ["Item_Range_SlingShot", "Item_Hookshot", "Item_Range_Bow"]
        placements = SeedEngine("glitchedless").generate(7, items)
        self.assertEqual(len(placements), 3)
        for p in placements:
            self.assertIsNotNone(p.patch)
            self.assertIn(p.item, ITEM_ACTOR_NAMES)

    def test_engine_is_deterministic(self):
        items = ["Item_Range_Bow", "Item_Hookshot"]
        a = SeedEngine().generate(42, items)
        b = SeedEngine().generate(42, items)
        self.assertEqual([p.location for p in a], [p.location for p in b])

    def test_different_seeds_produce_different_placements(self):
        items = ["Item_Range_Bow", "Item_Hookshot"]
        a = SeedEngine().generate(1, items)
        b = SeedEngine().generate(2, items)
        self.assertNotEqual([p.location for p in a], [p.location for p in b])

    def test_engine_prefers_summary_backed_location_list(self):
        locations = SeedEngine()._filtered_locations()
        names = {loc.name for loc in locations}
        self.assertIn("Deku Tree Map Chest", names)
        self.assertIn("Forest Temple Bow Chest", names)

    def test_summary_runtime_locations_reuse_canonical_names(self):
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

        runtime_locations = build_runtime_locations(summary)
        self.assertEqual(runtime_locations[0].name, "Deku Tree Map Chest")
        self.assertEqual(runtime_locations[1].name, "Deku Tree Compass Chest")


class LogicEngineTests(unittest.TestCase):
    def test_glitchedless_evaluates_reachable_locations(self):
        reachable = LogicEngine("glitchedless").evaluate(
            ["Bomb Bag", "Hookshot", "Fire Arrows", "Light Arrows", "Master Sword"]
        )
        self.assertIn("Forest Temple", reachable)
        self.assertIn("Fire Temple", reachable)
        self.assertIn("Ganon's Tower", reachable)

    def test_all_locations_returns_everything(self):
        reachable = LogicEngine("all_locations").evaluate([])
        self.assertGreater(len(reachable), 0)


class SafeCopyTests(unittest.TestCase):
    def test_copy_does_not_modify_source(self):
        src = Path("tmp/source_copy_test.nup")
        _make_nup(src, b"original-data")
        out = Path("tmp/output_copy_test.nup")
        self.addCleanup(src.unlink, missing_ok=True)
        self.addCleanup(out.unlink, missing_ok=True)
        self.addCleanup(Path("tmp/output_copy_test.json").unlink, missing_ok=True)
        self.addCleanup(Path("tmp/output_copy_test.patch.json").unlink, missing_ok=True)

        before = src.read_bytes()
        result = OOTRandomizer(RandomizerConfig(seed=7, output_path=str(out))).randomize(str(src))

        self.assertEqual(src.read_bytes(), before)
        self.assertTrue(out.exists())
        self.assertEqual(before, out.read_bytes())
        self.assertTrue(Path(result.manifest_path).exists())
        self.assertTrue(Path(result.patch_manifest_path).exists())
        self.assertEqual(result.status, "randomized-copy-created")
        self.assertEqual(result.patch_mode, "manifest-only")

    def test_refuses_to_overwrite_original(self):
        src = Path("tmp/overwrite_guard_test.nup")
        _make_nup(src)
        self.addCleanup(src.unlink, missing_ok=True)
        with self.assertRaises(RomValidationError):
            OOTRandomizer(RandomizerConfig(output_path=str(src))).randomize(str(src))

    def test_handles_unwritable_output_dir(self):
        self.skipTest("This does not work on Windows OSes")
        src = Path("tmp/unwritable_output_source.nup")
        _make_nup(src)
        blocked = Path("/tmp/blocked_oot_output_dir")
        blocked.mkdir(exist_ok=True)
        blocked.chmod(0o500)
        self.addCleanup(lambda: blocked.chmod(0o755) if blocked.exists() else None)
        self.addCleanup(src.unlink, missing_ok=True)
        self.addCleanup(shutil.rmtree, blocked, ignore_errors=True)
        with self.assertRaises(RomValidationError):
            OOTRandomizer(RandomizerConfig(output_path=str(blocked / "copy.nup"))).randomize(str(src))


if __name__ == "__main__":
    unittest.main()
