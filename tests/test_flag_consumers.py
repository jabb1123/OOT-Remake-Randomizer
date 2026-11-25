import tempfile
import unittest
from pathlib import Path
from unittest import mock

import zstandard as zstd

from oot_randomizer import flag_consumers
from oot_randomizer.flag_consumers import DEFAULT_ROOT, find_consumers, format_result

RAW_MEDAL_FILE = "Dm_Awake_Forest_Get.bfevfl.zs.raw"


class FindConsumersTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name: str, data: bytes) -> None:
        (self.root / name).write_bytes(data)

    def test_finds_only_files_that_name_the_token(self):
        self._write("A.bfevfl.zs.raw", b"\x00Item_Medal_Forest\x00")
        self._write("B.bfevfl.zs.raw", b"\x00Item_Medal_Fire\x00")

        result = find_consumers(self.root, "Item_Medal_Forest")

        self.assertEqual([h.path for h in result.hits], ["A.bfevfl.zs.raw"])
        self.assertEqual(result.scanned, 2)

    def test_matches_whole_names_only(self):
        self._write("long.raw", b"AllSage_IsAfter_Step02_Exp\x00")
        self._write("exact.raw", b"AllSage_IsAfter_Step02\x00")

        result = find_consumers(self.root, "AllSage_IsAfter_Step02")

        self.assertEqual([h.path for h in result.hits], ["exact.raw"])

    def test_skips_zstd_compressed_files(self):
        packed = zstd.ZstdCompressor().compress(b"Item_Medal_Forest")
        self._write("packed.bfevfl.zs", packed)
        self._write("plain.bfevfl.zs.raw", b"Item_Medal_Forest")

        result = find_consumers(self.root, "Item_Medal_Forest")

        self.assertEqual(result.skipped_compressed, ["packed.bfevfl.zs"])
        self.assertEqual([h.path for h in result.hits], ["plain.bfevfl.zs.raw"])

    def test_suffix_filter_limits_the_search(self):
        self._write("a.raw", b"Item_Medal_Forest")
        self._write("a.txt", b"Item_Medal_Forest")

        result = find_consumers(self.root, "Item_Medal_Forest", suffixes=("raw",))

        self.assertEqual([h.path for h in result.hits], ["a.raw"])

    def test_kind_follows_the_file_name(self):
        self._write("Dm_X.bfevfl.zs.raw", b"Item_Medal_Forest")
        self._write("Logic.ainb", b"Item_Medal_Forest")
        self._write("Setting.gyml", b"Item_Medal_Forest")
        self._write("notes.txt", b"Item_Medal_Forest")

        kinds = {h.path: h.kind for h in find_consumers(self.root, "Item_Medal_Forest").hits}

        self.assertEqual(kinds, {
            "Dm_X.bfevfl.zs.raw": "event flow",
            "Logic.ainb": "logic module",
            "Setting.gyml": "data",
            "notes.txt": "other",
        })

    def test_reviewed_entries_are_reported(self):
        self._write("Dm_X.bfevfl.zs.raw", b"Item_Medal_Forest")
        reviewed = {("Item_Medal_Forest", "Dm_X"): ("gating", "test note")}

        with mock.patch.dict(flag_consumers.REVIEWED, reviewed, clear=True):
            hit = find_consumers(self.root, "Item_Medal_Forest").hits[0]

        self.assertEqual((hit.review, hit.note), ("gating", "test note"))

    def test_unreviewed_by_default(self):
        self._write("Dm_X.bfevfl.zs.raw", b"Item_Medal_Forest")

        with mock.patch.dict(flag_consumers.REVIEWED, {}, clear=True):
            hit = find_consumers(self.root, "Item_Medal_Forest").hits[0]

        self.assertEqual(hit.review, "unreviewed")

    def test_rejects_a_token_that_is_not_a_name(self):
        with self.assertRaises(ValueError):
            find_consumers(self.root, "Item Medal")

    def test_format_reports_hits_and_skips(self):
        self._write("a.raw", b"Item_Medal_Forest")
        self._write("b.zs", zstd.ZstdCompressor().compress(b"x"))

        text = format_result("Item_Medal_Forest", self.root, find_consumers(self.root, "Item_Medal_Forest"))

        self.assertIn("[other] a.raw (unreviewed)", text)
        self.assertIn("1 hit(s) in 1 scanned file(s)", text)
        self.assertIn("1 zstd-compressed file(s) skipped", text)


@unittest.skipUnless(DEFAULT_ROOT.is_dir(), "tmp/Events/raw dumps are not present")
class RealDumpTest(unittest.TestCase):
    def test_medal_name_is_found_in_the_forest_medal_flow(self):
        result = find_consumers(DEFAULT_ROOT, "Item_Medal_Forest", suffixes=("raw",))

        self.assertIn(RAW_MEDAL_FILE, [h.path for h in result.hits])


if __name__ == "__main__":
    unittest.main()
