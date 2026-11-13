# OoT Randomizer — Project Core

Python CLI tool that patches the OoT Remake `.nup` ROM file to randomize chest item assignments.
Never modifies the original; always works on a copy.

## Source map

```
src/oot_randomizer/
  cli.py          — CLI entrypoint; subcommands: randomize, scan
  randomizer.py   — OOTRandomizer: orchestrates copy → patch → manifest
  engine.py       — SeedEngine: assigns items to locations, produces PatchRecords
  patcher.py      — RomPatcher + PatchRecord; binary or manifest-only mode
  byml7.py        — BYML v7 parser (LE 'YB' and BE 'BY' variants)
  game_data.py    — NUP file access + ZSTD dict decompression pipeline
  nup_parser.py   — NUP structure scanner + KNOWN_LAYOUT constants
  locations.py    — OOTLocation table: scene, check_type, required_items
  item_ids.py     — Game-level item byte IDs (not N64-specific)
  logic.py        — LogicEngine: evaluates reachable locations for a given item pool
  config.py       — RandomizerConfig dataclass
  oot_data.py     — Static item/dungeon pools and preset tables
  rom.py          — NUP file validation (validate_nup_rom)
tests/
  test_engine.py           — NUP parser, item IDs, locations, patcher, engine
  test_rom_validation.py   — ROM validation, safe-copy, logic engine
```

## Project invariants

- Original `.nup` is NEVER modified; all changes go to a copy.
- Patcher enters `manifest-only` mode when `byte_offset=None` on a PatchRecord.
- All tests must pass before any change is complete (30 tests, ~0.01s).

## Key domain memories

- NUP format and file structure: `mem:nup_format`
- BYML v7 binary format details: `mem:byml7_format`
- Chest item patching pipeline: `mem:chest_patching`
- Useful references and repos: `mem:references`
