"""Tests for nup_mod_export: loose-file RomFS mods built from a patched synthetic NUP."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from oot_randomizer.config import RandomizerConfig
from oot_randomizer.nup_chest_patcher import NupChestPatcher
from oot_randomizer.nup_files import add_files
from oot_randomizer.nup_mod_export import changed_romfs_files, export_mod
from oot_randomizer.randomizer import OOTRandomizer, RandomizationResult
from oot_randomizer.sarc import write_sarc

from test_nup_files import build_nup


class NupModExportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.source = build_nup(self.tmp)
        self.patched = self.tmp / "patched.nup"
        shutil.copy2(self.source, self.patched)

    def tearDown(self):
        self._tmp.cleanup()

    def test_unchanged_nup_exports_nothing(self):
        self.assertEqual(changed_romfs_files(self.source, self.patched), {})

    def test_replaced_file_is_the_only_change(self):
        NupChestPatcher(self.patched, write_sarc({})).replace_file("zeta.txt", lambda d: b"changed!")
        self.assertEqual(changed_romfs_files(self.source, self.patched), {"a/b/zeta.txt": b"changed!"})

    def test_added_file_is_exported(self):
        add_files(self.patched, 0, [("a/new.txt", b"new")])
        self.assertEqual(changed_romfs_files(self.source, self.patched), {"a/new.txt": b"new"})

    def test_export_writes_only_changed_files_under_romfs(self):
        NupChestPatcher(self.patched, write_sarc({})).replace_file("zeta.txt", lambda d: b"changed!")
        add_files(self.patched, 0, [("a/new.txt", b"new")])
        mod = self.tmp / "mod"
        self.assertEqual(export_mod(self.source, self.patched, mod), 2)
        written = sorted(p.relative_to(mod).as_posix() for p in mod.rglob("*") if p.is_file())
        self.assertEqual(written, ["romfs/a/b/zeta.txt", "romfs/a/new.txt"])
        self.assertEqual((mod / "romfs/a/b/zeta.txt").read_bytes(), b"changed!")

    def test_export_replaces_a_stale_romfs_folder(self):
        mod = self.tmp / "mod"
        stale = mod / "romfs" / "old.txt"
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b"stale")
        export_mod(self.source, self.patched, mod)
        self.assertFalse(stale.exists())

    def test_export_writes_seed_mod_folder_and_removes_scratch_copy(self):
        source = build_nup(self.tmp, name="game.nup")
        source_before = source.read_bytes()
        mods = self.tmp / "mods"

        real_randomize = OOTRandomizer.randomize

        def fake_randomize(self, rom_path):
            if self.config.mod_dir is not None:
                return real_randomize(self, rom_path)
            # Stand-in for the full pipeline, which needs a game-shaped NUP the synthetic one is not.
            out = Path(self.config.output_path)
            shutil.copy2(rom_path, out)
            add_files(out, 0, [("a/new.txt", b"new")])
            out.with_suffix(".json").write_text("{}")
            out.with_suffix(".patch.json").write_text("[]")
            out.with_suffix(".spoiler.txt").write_text("spoiler")
            return RandomizationResult(
                rom_path=str(rom_path), output_path=str(out),
                manifest_path=str(out.with_suffix(".json")),
                patch_manifest_path=str(out.with_suffix(".patch.json")),
                seed=self.config.seed, status="randomized-copy-created", target="", logic="", goal="",
                item_order=[], dungeon_order=[], reachable_locations=[], placements=[],
                nup_regions=[], patch_mode="",
            )

        with mock.patch.object(OOTRandomizer, "randomize", fake_randomize):
            result = OOTRandomizer(RandomizerConfig(seed=7, mod_dir=str(mods))).randomize(str(source))

        mod = Path(result.output_path)
        self.assertEqual(result.status, "mod-exported")
        self.assertEqual(mod, mods / "game_seed7")
        self.assertEqual((mod / "romfs/a/new.txt").read_bytes(), b"new")
        self.assertTrue(Path(result.manifest_path).exists())
        self.assertTrue(Path(result.patch_manifest_path).exists())
        self.assertTrue((mod / "game_randomized.spoiler.txt").exists())
        self.assertEqual(source.read_bytes(), source_before)
        self.assertEqual([p.name for p in self.tmp.iterdir() if p.name.startswith(".rando_tmp_")], [])


if __name__ == "__main__":
    unittest.main()
