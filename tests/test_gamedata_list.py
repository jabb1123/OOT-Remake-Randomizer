"""Tests for the Kokiri Shop sold-out Bool entries in GameDataList."""

import unittest
from pathlib import Path

from oot_randomizer.byml7 import U32, dump_byml7, parse_byml7_typed
from oot_randomizer.gamedata_list import (
    SHOP_SOLDOUT_NAMES,
    add_shop_soldout_bools,
    murmur3_32,
    patch_gamedata_list,
)

SAMPLE = Path(
    r"C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405\files\byml_samples"
    r"\GameData__GameDataList.Product.100.byml"
)

EXPECTED_HASHES = {
    "KokiriForest_Shop_SoldOut_0": 520717719,
    "KokiriForest_Shop_SoldOut_1": 3284184693,
    "KokiriForest_Shop_SoldOut_2": 3257748438,
    "KokiriForest_Shop_SoldOut_3": 4024991567,
    "KokiriForest_Shop_SoldOut_4": 3454931238,
    "KokiriForest_Shop_SoldOut_5": 2936240294,
    "KokiriForest_Shop_SoldOut_6": 100485119,
    "KokiriForest_Shop_SoldOut_7": 2260209522,
}


def _make_root(progress_bools: int, progress_size: int = 686828, all_size: int = 781740) -> dict:
    bools = [
        {"DefaultValue": False, "Hash": U32(1000 + i), "ResetTypeValue": 8, "SaveFileIndex": 0}
        for i in range(progress_bools)
    ]
    return {
        "Data": {"Bool": bools},
        "MetaData": {
            "AllDataSaveOffset": U32(96984),
            "AllDataSaveSize": U32(all_size),
            "SaveDataOffsetPos": [U32(86880), U32(560), U32(672), U32(320)],
            "SaveDataSize": [U32(progress_size), U32(1004), U32(42356), U32(320)],
        },
    }


class MurmurHashTests(unittest.TestCase):
    def test_known_hash(self):
        self.assertEqual(murmur3_32(b"KokiriForest_Shop_SelectActor_Shield_Deku"), 936576842)

    def test_soldout_name_hashes(self):
        self.assertEqual(tuple(SHOP_SOLDOUT_NAMES), tuple(EXPECTED_HASHES))
        for name, expected in EXPECTED_HASHES.items():
            with self.subTest(name=name):
                self.assertEqual(murmur3_32(name.encode()), expected)


class AddShopSoldoutBoolsTests(unittest.TestCase):
    def test_appends_eight_save_backed_bools(self):
        root = _make_root(progress_bools=9363)
        added = add_shop_soldout_bools(root)
        self.assertEqual(added, list(SHOP_SOLDOUT_NAMES))
        new = root["Data"]["Bool"][9363:]
        self.assertEqual(len(new), 8)
        for name, entry in zip(SHOP_SOLDOUT_NAMES, new):
            self.assertEqual(int(entry["Hash"]), EXPECTED_HASHES[name])
            self.assertEqual(entry["DefaultValue"], False)
            self.assertEqual(entry["ResetTypeValue"], 9)
            self.assertEqual(entry["SaveFileIndex"], 0)

    def test_idempotent(self):
        root = _make_root(progress_bools=10)
        add_shop_soldout_bools(root)
        before = (len(root["Data"]["Bool"]), list(root["MetaData"]["SaveDataSize"]),
                  int(root["MetaData"]["AllDataSaveSize"]))
        self.assertEqual(add_shop_soldout_bools(root), [])
        after = (len(root["Data"]["Bool"]), list(root["MetaData"]["SaveDataSize"]),
                 int(root["MetaData"]["AllDataSaveSize"]))
        self.assertEqual(before, after)

    def test_layout_grows_progress_block_by_one_byte(self):
        root = _make_root(progress_bools=9363, progress_size=686828, all_size=781740)
        add_shop_soldout_bools(root)
        meta = root["MetaData"]
        self.assertEqual(int(meta["SaveDataSize"][0]), 686829)
        self.assertEqual(int(meta["AllDataSaveSize"]), 781741)
        self.assertEqual([int(v) for v in meta["SaveDataSize"][1:]], [1004, 42356, 320])
        self.assertEqual([int(v) for v in meta["SaveDataOffsetPos"]], [86880, 560, 672, 320])
        self.assertEqual(int(meta["AllDataSaveOffset"]), 96984)

    def test_existing_names_are_not_added_twice(self):
        root = _make_root(progress_bools=0)
        root["Data"]["Bool"].append({
            "DefaultValue": False, "Hash": U32(EXPECTED_HASHES["KokiriForest_Shop_SoldOut_3"]),
            "ResetTypeValue": 9, "SaveFileIndex": 0,
        })
        added = add_shop_soldout_bools(root)
        self.assertNotIn("KokiriForest_Shop_SoldOut_3", added)
        self.assertEqual(len(added), 7)
        hashes = [int(e["Hash"]) for e in root["Data"]["Bool"]]
        self.assertEqual(len(hashes), len(set(hashes)))


class PatchGameDataListTests(unittest.TestCase):
    def test_bytes_round_trip_and_idempotent(self):
        raw = dump_byml7(_make_root(progress_bools=9363), big_endian=True, version=7)
        patched = patch_gamedata_list(raw)
        self.assertNotEqual(patched, raw)
        root = parse_byml7_typed(patched)
        self.assertEqual(len(root["Data"]["Bool"]), 9371)
        self.assertEqual(int(root["MetaData"]["SaveDataSize"][0]), 686829)
        self.assertEqual(patch_gamedata_list(patched), patched)

    @unittest.skipUnless(SAMPLE.exists(), "GameDataList sample not present")
    def test_real_gamedata_list_sample(self):
        raw = SAMPLE.read_bytes()
        root = parse_byml7_typed(raw)
        bools = root["Data"]["Bool"]
        self.assertEqual(len(bools), 10411)
        self.assertEqual(int(bools[8888]["Hash"]), 936576842)
        progress_before = sum(1 for e in bools if int(e["SaveFileIndex"]) == 0)
        size_before = int(root["MetaData"]["SaveDataSize"][0])
        all_before = int(root["MetaData"]["AllDataSaveSize"])

        patched = parse_byml7_typed(patch_gamedata_list(raw))
        bools = patched["Data"]["Bool"]
        self.assertEqual(len(bools), 10419)
        hashes = [int(e["Hash"]) for e in bools]
        self.assertEqual(len(hashes), len(set(hashes)))
        for name in SHOP_SOLDOUT_NAMES:
            self.assertIn(murmur3_32(name.encode()), hashes)
        grown = (progress_before + 8 + 7) // 8 - (progress_before + 7) // 8
        self.assertEqual(int(patched["MetaData"]["SaveDataSize"][0]), size_before + grown)
        self.assertEqual(int(patched["MetaData"]["AllDataSaveSize"]), all_before + grown)
        self.assertEqual(patch_gamedata_list(dump_byml7(patched, big_endian=True, version=7)),
                         dump_byml7(patched, big_endian=True, version=7))


if __name__ == "__main__":
    unittest.main()
