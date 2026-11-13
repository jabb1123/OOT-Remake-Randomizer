# Key External References

## NUP format

- **Format spec** (authoritative): https://github.com/a55uka/nup/blob/meow/SPEC.md
- **Python reference impl**: https://github.com/a55uka/nup (`tools/nup/` — `pip install ./tools/nup`)
- **NSP-Box 4.0** (independent Python impl, MIT): https://github.com/smarkyie/NSP-Box
- **Eglantine NUP loader** (C++): https://github.com/Djihads80/Eglantine/blob/main/src/core/loader/nup.cpp
- **Eglantine NUP filesystem** (C++): https://github.com/Djihads80/Eglantine/blob/main/src/core/file_sys/nup_container.cpp

## OoT Randomizer reference

- **Original OoT randomizer**: https://ootrandomizer.com
- Covers N64 OoT, not the Switch remake — useful for logic/item pool reference only.

## BYML v7

- No public spec; reverse-engineered from game files in this project.
- `oead` library (PyPI) supports BYML up to v4 only — do not use for v7.
- Summary of v7 format: `mem:byml7_format`

## Compression

- NSP-Box compression doc: https://github.com/smarkyie/NSP-Box/blob/main/NUP.md#compression-and-space
- NUP uses per-file Zstandard compression (codec 1); files > 256 MiB stored raw by default.
- Game `.zs` files use ZSTD with per-type dictionary from `ZsDic.pack.zs` (SARC archive).

## OoT Remake internals

- Actor/scene data files use BYML v7 (`.bcett.byml.zs`, `.bgyml`, etc.)
- Chest actor types: `Obj_TBox_A_01`, `Obj_TBox_A_02`
- Item field on chests: `Dynamic.Drop__DropActor` (string name, not numeric ID)
- Known item string names: `Item_Dungeon_Compass`, `Item_Dungeon_Map`,
  `Item_Range_SlingShot`, `TBox_DekuNutBundle`, `Item_DekuStickBundle_Small`,
  `Item_Dungeon_BossKey`, `Item_Range_Bow`, `Item_Melee_Hammer`, etc.
- GameDataList flag names: `HookShot`, `AppearHookShot`, `DungeonMap`, `FireArrow`,
  `LightArrow`, `GoronGauntlet`, `DekuNut`, `DekuStick`, etc.
