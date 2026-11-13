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

## Recommended next implementation phases

- Build a byte-level ROM parser for Ocarina of Time memory layout
- Add a serializer for generated patches
- Separate logic engines by category (items, entrances, overworld)
- Add test coverage for input validation and rules generation
- Add a GUI layer later if desired

This project is best treated as a serious engineering foundation for a future OOT randomizer implementation rather than a one-file script.
