import shutil
import struct
import unittest
from pathlib import Path

from oot_randomizer.config import RandomizerConfig
from oot_randomizer.engine import SeedEngine
from oot_randomizer.logic import LogicEngine
from oot_randomizer.nup_parser import NUP_MAGIC
from oot_randomizer.randomizer import OOTRandomizer
from oot_randomizer.rom import RomValidationError, validate_nup_rom


def _make_nup(path: Path, extra: bytes = b"") -> None:
    header = NUP_MAGIC + struct.pack(">III", 0x00000001, len(extra), 0)
    path.write_bytes(header.ljust(64, b"\x00") + extra)


class RomValidationTests(unittest.TestCase):
    def test_accepts_valid_nup_file(self):
        temp_path = Path("tmp/test_valid_rom.nup")
        _make_nup(temp_path)
        self.addCleanup(temp_path.unlink, missing_ok=True)

        info = validate_nup_rom(temp_path)
        self.assertTrue(info.is_nup)

    def test_rejects_wrong_extension(self):
        temp_path = Path("tmp/test_invalid_rom.z64")
        temp_path.write_bytes(b"12345")
        self.addCleanup(temp_path.unlink, missing_ok=True)

        with self.assertRaises(RomValidationError):
            validate_nup_rom(temp_path)

    def test_rejects_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            validate_nup_rom("tmp/does_not_exist.nup")

    def test_randomizer_writes_copy_without_modifying_source(self):
        source_path = Path("tmp/source_copy_test.nup")
        _make_nup(source_path, b"payload")
        output_path = Path("tmp/output_copy_test.nup")
        self.addCleanup(source_path.unlink, missing_ok=True)
        self.addCleanup(output_path.unlink, missing_ok=True)
        self.addCleanup(Path("tmp/output_copy_test.json").unlink, missing_ok=True)
        self.addCleanup(Path("tmp/output_copy_test.patch.json").unlink, missing_ok=True)

        source_before = source_path.read_bytes()
        result = OOTRandomizer(RandomizerConfig(seed=7, output_path=str(output_path))).randomize(str(source_path))

        self.assertEqual(source_path.read_bytes(), source_before)
        self.assertTrue(output_path.exists())
        self.assertEqual(source_before, output_path.read_bytes())
        self.assertTrue(Path(result.manifest_path).exists())
        self.assertEqual(result.status, "randomized-copy-created")

    def test_logic_engine_evaluates_reachable_locations(self):
        logic = LogicEngine("glitchedless")
        item_pool = ["Bomb Bag", "Hookshot", "Fire Arrows", "Light Arrows", "Master Sword"]

        reachable = logic.evaluate(item_pool)
        self.assertIn("Forest Temple", reachable)
        self.assertIn("Fire Temple", reachable)
        self.assertIn("Ganon's Tower", reachable)

    def test_seed_engine_assigns_items_to_locations(self):
        placements = SeedEngine("glitchedless").generate(7, ["Bomb Bag", "Hookshot", "Light Arrows"])

        self.assertEqual(len(placements), 3)
        self.assertEqual(placements[0].item, "Bomb Bag")
        self.assertEqual(placements[1].item, "Hookshot")
        self.assertEqual(placements[2].item, "Light Arrows")
        self.assertTrue(all(placement.location for placement in placements))

    def test_randomizer_handles_unwritable_output_path(self):
        self.skipTest("This does not work on Windows OSes")
        source_path = Path("tmp/unwritable_output_source.nup")
        _make_nup(source_path)
        blocked_dir = Path("/tmp/blocked_oot_output_dir")
        blocked_dir.mkdir(exist_ok=True)
        blocked_dir.chmod(0o500)
        self.addCleanup(lambda: blocked_dir.chmod(0o755) if blocked_dir.exists() else None)
        self.addCleanup(source_path.unlink, missing_ok=True)
        self.addCleanup(shutil.rmtree, blocked_dir, ignore_errors=True)

        with self.assertRaises(RomValidationError):
            OOTRandomizer(RandomizerConfig(output_path=str(blocked_dir / "copy.nup"))).randomize(str(source_path))


if __name__ == "__main__":
    unittest.main()
