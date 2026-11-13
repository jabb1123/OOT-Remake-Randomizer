# Chest Item Patching Pipeline

## Actor type for chests

`Gyaml` field values: `Obj_TBox_A_01` (small chest), `Obj_TBox_A_02` (large chest).
Found in both `_Static.bcett.byml.zs` and `_Dynamic.bcett.byml.zs` for each scene.

## Item field

Path: `actor["Dynamic"]["Drop__DropActor"]` — a BYML string ref (0xA0 node type).
The 4-byte value at the hash entry's value slot is a u32 index into the file's string table.

## In-place swap method (confirmed working)

1. Find `Drop__DropActor` hash entry for each chest actor by walking the BYML binary.
2. Record the **absolute byte offset of the u32 string-index value** for each chest.
3. Write the new string-index values directly with `struct.pack_into("<I", ...)`.
4. Recompress with `ZstdCompressor(level=22, dict_data=d)` using the SAME dict_id
   (auto-detected from original frame header). Level 22 gives best ratio.
5. Append recompressed extent to end of NUP copy (original extent stays; NUP allows this).
6. Update NupFile TOC entry: `size` (0x08), `extent_offset` (0x10), `extent_size` (0x18),
   `sha256` (0x20–0x40) — sha256 is of the UNCOMPRESSED patched bytes.
7. Recompute `toc_sha256` (SHA-256 of full TOC bytes) and write to superblock at 0x18.
8. Update superblock `file_size` at 0x40.

## Deku Tree confirmed chest data (InsideTheDekuTree_Static.bcett.byml)

| Gyaml | Room | Drop__DropActor | str_idx | BYML val offset |
|---|---|---|---|---|
| Obj_TBox_A_02 | 3 | Item_Dungeon_Compass | 284 | 0x0AEEC |
| Obj_TBox_A_02 | 0 | Item_Dungeon_Map | 285 | 0x0B61C |
| Obj_TBox_A_01 | 2 | TBox_DekuNutBundle | 480 | 0x0EE70 |
| Obj_TBox_A_02 | 2 | Item_Range_SlingShot | 286 | 0x0EF00 |

(Dynamic file has 2 more chests: TBox_DekuNutBundle and Item_DekuStickBundle_Small)

**Extent info** (InsideTheDekuTree_Static.bcett.byml.zs in base package):
- NUP file index: 14111
- NupFile entry in TOC: absolute offset 0x11AB48
- Original extent: @0x6F766B50, size 35706 bytes, dict_id=3

## Important: re-compression always produces larger frames with our tools

Original was likely compressed with Nintendo's internal tooling at high efficiency.
Our level-22 output with dict_id embedded is ~34KB vs original 35KB — fits in extent size
at level 22 (`ZstdCompressor(level=22, dict_data=d)` with embedded dict).

## Verified swap

Compass ↔ Slingshot swap verified in `deku_tree_test.nup` using `nup.read_file()` +
decompression + byte offset check.
