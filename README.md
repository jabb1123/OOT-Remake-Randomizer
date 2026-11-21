# OOT Randomizer (Python Starter)

This project is a Python-based foundation for an Ocarina of Time randomizer pipeline that accepts a `.nup` ROM file and follows the same broad design direction as the original `ootrandomizer.com` experience: random seed generation, item shuffling, dungeon logic, and seed export.

## Goals

- Accept a valid `.nup` file as input
- Validate the ROM before patching
- Model configurable randomizer settings
- Provide a clean CLI entrypoint for future development
- Build a modular foundation for item, dungeon, and logic systems

## Current status

This repository is intentionally a scaffold rather than a full randomizer. The system validates the incoming ROM and exposes a structured config model that can be extended into the full randomization pipeline.

## Planned feature roadmap

1. ROM detection and validation
2. Seed generation and reproducible randomization
3. Item pool shuffling and placement rules
4. Dungeon and overworld logic management
5. Boss key, small key, and major item distribution
6. Entrance randomization and scene transitions
7. Settings UI / CLI options / config file support
8. Patch export and compatibility checks

## Install

```bash
cd oot_randomizer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
```

## Run the CLI

```bash
oot-randomizer --rom "/path/to/The Legend of Zelda Ocarina of Time   U2.0.0.nup" --seed 12345
```

## Loose-file mod export

`--mod-dir DIR` skips writing a full patched ROM. It randomizes a scratch copy, then writes only the changed or new RomFS files to `DIR/<stem>_seed<N>/romfs/`, with the manifest, patch manifest, and spoiler log beside them. To load it in Eden/Lichii, copy that folder into the game's mod folder, `load\0400486024DEC000\`. The loose files override the base game files at the same paths. Paths in the mod are relative to the package RomFS root.

```bash
oot-randomizer --rom "/path/to/The Legend of Zelda Ocarina of Time   U2.0.0.nup" --seed 12345 --mod-dir "/path/to/mods"
```

## World logic

Placement logic lives in `logic/world/`, one TOML file per area:

- `_settings.toml` — `[settings]` only, plus a header documenting the format
- `_helpers.toml` — `[helpers]`: named requirement groups shared by every file, such as `has_strength`, `has_bombs`, `has_explosives`, `has_hookshot`, `can_shoot`, `ranged_weapon` and `can_play(song)` (ocarina plus song). A helper is used like an item name, and `name(param)` helpers take arguments. Helpers can use other helpers, but not in a loop.
- `overworld/<Region>.toml` and `dungeons/<Region>.toml` — each file adds its own `[regions.Root.exits]` entry, then the region's flags, events, locations and Gold Skulltulas

Every `*.toml` is loaded recursively in sorted path order and deep-merged. The same key in two files is an error, `dungeon`/`excluded` flags must agree, `[settings]` may appear only once, and each helper name may be defined only once. `--logic-file` (randomize) and `--file` (`logic check`) accept either this directory or a single TOML file. For example, `oot-randomizer logic template` writes a single-file starter to `logic/world_template.toml`.

## Shopsanity

`--shop-slots N` (0-4, default 2; `RandomizerConfig.shop_slots_per_shop`) turns N random shelf slots of every shop into item locations, each selling a custom `Shop_Rando_<item>` actor for 10-200 rupees (steps of 5). The slot table is in `src/oot_randomizer/shop_slots.py`; only slots whose vanilla item needs no upgrade, bottle or side quest are used (Kokiri Shop, Bazaar, Goron Shop, Zora Shop), and only those listed in the world logic (`KokiriShop`, `Bazaar`, `GoronShop`, `ZoraShop` regions). Prices of 100+ require a wallet per seed (`World.with_requirements`). Each slot adds one rupee filler that only chests accept. New actor packs need TOC room in the NUP (about 28 fit), which the planner checks. The manifest lists every shop placement with its price.

## Intro cutscene

`--skip-intro` (`RandomizerConfig.skip_intro`, off by default) skips the whole opening Introduction cutscene at the start of a new game. In `OpeningEvent.bfevfl`, the `Opening_Introduction` setup event (`Event9`) is redirected to the skip-check's skip branch (`Event24`, the same path the game takes when the player presses skip). The staging, the Meet_DekuTree challenge, and the `Dm_Kokiri_0030` wake-up demo become unreachable. The loading transition (`Dm_Kokiri_0000`, entry point `Opening_LoadingKokiriForest`) is left alone because it gates the scene load. The patch is in `src/oot_randomizer/cutscene_skips.py`.

## Hyrule Field time on the Zelda route

The clock also has to be started. Only the Kaepora flow on first entry to Hyrule Field (`Dm_HrlField_0000`) runs `Event_SetTimeForFlowchart` (a 22-second transition to the target time), so a route that skips it never starts time. The first Kaepora talk in `Goto_HyruleCastle` also sets up the quest log. `add_goto_quest_progress_to_castle_entry` copies those steps into the castle entry flow right after the entry's first action, before the entry's parallel block: set `HyruleField_ArriveEntrance` and `UI_IsFinishChallengeMenuOpenEvent`, add the `Pouch_Amiibo` pouch item, progress the `Goto_HyruleCastle` challenge to `Step02` (with the progress UI ignored, as in `Goto_HyruleCastle`), and show the challenge progress UI. Routes that start at the castle never run `Goto_HyruleCastle`, so without these steps the quest menu never activates. A test checks that each copied step exists verbatim in the retail `Goto_HyruleCastle` flow.

### Hyrule Field Kaepora segment isolation

`src/oot_randomizer/hyrule_field_segments.py` can unlink the Kaepora segments (`Dm_HrlField_0000`, `0005`, `0010`) from the first Kaepora talk in `Goto_HyruleCastle`, so one segment plays at a time. It is disabled in the patcher and kept as a debug tool for finding time triggers. To use it, add a call to `isolate_kaepora_segments` on `KAEPORA_FLOW` in `patcher.py` and set `KAEPORA_SEGMENTS_TO_PLAY`.
