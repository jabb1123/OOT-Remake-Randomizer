# BYML v7 Binary Format

## Magic / endianness

| Magic | Endian | Used in |
|---|---|---|
| `BY` | Big-endian | `GameDataList.Product.100.byml` and similar |
| `YB` | Little-endian | bcett placement files, GameBancParam, etc. |

## Header (16 bytes)

```
magic[2]  version(u16 LE or BE)  hash_key_table_offset(u32)
string_table_offset(u32)  root_node_offset(u32)
```

## Node type codes (v7 — DIFFERENT from v2-4)

| Code | Type | Storage |
|---|---|---|
| 0xC0 | **Array** | `type_per_element[count]` (padded to 4B) + `u32 value[count]` |
| 0xC1 | **Hash/Map** | 8B entries: `key_idx(3B LE) + type(1B) + value(4B)` |
| 0xC2 | String array | offset table + null-terminated strings |
| 0xA0 | String ref | `u32` index into string table |
| 0xD0 | Bool | `u32` (0 or 1) |
| 0xD1 | Int32 | `i32` |
| 0xD2 | Float32 | `f32` |
| 0xD3 | UInt32 | `u32` |
| 0xFF | Null | — |

**CRITICAL NOTE**: In v7, 0xC0=Array and 0xC1=Hash. This is REVERSED from v2-4 where
0xC0=Hash and 0xC1=Array. `oead` only supports up to v4 — do not use it for v7 files.

## Container vs scalar value slot

- **Scalar** (0xA0, 0xD0–0xD3, 0xFF): 4-byte inline value.
- **Container** (0xC0, 0xC1): 4-byte value is an **absolute file offset** to the child node.

## String array layout (0xC2)

```
type(1B) + count(3B LE/BE) + offset_table[count × 4B] + string_data
```
Each offset is relative to the start of the string array node.

## bcett file structure

Root node is a 0xC1 Hash with keys: `Actors`, `AiGroups`, `FarDeleteGroups`,
`FilePath`, `PhiveHeader`, `PlgGdTable`, `SimultaneousGroups`.

`Actors` → 0xC0 Array of 0xC1 Hash actor nodes.
Each actor has at minimum: `Gyaml` (string ref), `SRTHash` (u32).
Chest actors additionally have: `Dynamic` → hash with `Drop__DropActor` (string ref),
`DefaultDungeonRoomIndex` (int), optionally `GetEventName` (string ref).

## GameDataList structure

Top-level: 0xC1 Array with 2 string refs (file format descriptors).
Contains sections keyed: `Bool`, `BoolArray`, `S32`, `F32`, `U32`, `String16`,
`AllDataSaveOffset`, `AllDataSaveSize`, etc.
Flag names like `HookShot`, `AppearHookShot`, `DungeonMap`, `FireArrow`, `LightArrow`
are stored as string table entries.
