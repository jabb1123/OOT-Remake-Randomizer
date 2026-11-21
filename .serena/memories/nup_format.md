# NUP Format (Nintendo Switch game dump container)

## Sources
- Format spec: https://github.com/a55uka/nup/blob/meow/SPEC.md
- Reference implementation: https://github.com/a55uka/nup (`tools/nup/`)
- NSP-Box 4.0 (independent impl): https://github.com/smarkyie/NSP-Box
- Eglantine loader (C++): https://github.com/Djihads80/Eglantine/blob/main/src/core/loader/nup.cpp

## Superblock (0x80 bytes at offset 0)

| Offset | Size | Field |
|---|---|---|
| 0x00 | 4 | magic `NUP\x01` |
| 0x04 | 2 | header_size (0x80 for v1) |
| 0x06 | 2 | header_version (1) |
| 0x08 | 8 | toc_offset (== header_size in v1) |
| 0x10 | 8 | toc_size |
| 0x18 | 32 | toc_sha256 — SHA-256 over the entire TOC region |
| 0x38 | 8 | blob_offset (16-byte aligned) |
| 0x40 | 8 | file_size |
| 0x48 | 4 | package_count |

## TOC layout (at toc_offset)

```
magic(4) TOC\x01 + package_count(4) + dir_count(8) + file_count(8)
  + string_pool_off(8) + string_pool_size(8) + reserved(8)        [0x30 total header]
  + NupPackage[package_count]  × 0x40 bytes
  + NupDir[dir_count]          × 0x18 bytes
  + NupFile[file_count]        × 0x50 bytes
  + children[] uint32 array
  + string pool
```

## NupFile entry (0x50 bytes)

| Offset | Field |
|---|---|
| 0x00 | name_off (into string pool) |
| 0x04 | name_len |
| 0x08 | size (uncompressed bytes; must == extent_size for raw, or == decompressed size for zstd) |
| 0x10 | extent_offset (absolute file offset, 16-byte aligned) |
| 0x18 | extent_size (compressed bytes in blob) |
| 0x20 | sha256[32] — SHA-256 of UNCOMPRESSED content |
| 0x40 | codec (0=raw, 1=zstd) |

**CRITICAL**: When patching, update BOTH `size` (0x08) AND `extent_size` (0x18), then recompute `toc_sha256` and `file_size` in superblock.

## Codec 1 (zstd)

- One standard ZSTD frame; content size embedded in frame header.
- Game files use ZSTD dictionaries from `ZsDic.pack.zs` (a SARC archive).
- Dictionary IDs 1–4 found in this game's ZsDic.pack.
- Use `ZstdCompressor(level=N, dict_data=d)` to embed dict_id in the frame.
  `ZstdCompressionParameters.from_level()` does NOT embed dict_id — do not use for patching.

## This game's NUP structure (OoT Remake, 23.86 GB)

```
0x000000000  NUP superblock (0x80 bytes)
0x000000080  TOC (36,814,592 bytes) — 1199 dirs, 372,587 files, 2 packages
0x0231CE40   blob region start
  0x231BF80  App metadata (NPDM/ACI0/services)
  0x231CE40  NSO #1 — main game exe (78 MB decompressed, ZBIC-compressed sections)
  0x3F928B0  NSO #2–4 — SDK stubs/libraries
  ...
  0x24DEC000 Encrypted RomFS (AES-CTR — game asset files, NOT accessible without key)
```

**NSO sections** (`.text`, `.rodata`, `.data`) use **ZBIC** compression (NSO flags bit 7).
Each segment starts with `ZBIC`, u16 `0x5880` at +4, decompressed size (LE u32) at +6, and
payload from +10. The payload is a chain of zstd-style 3-byte block headers. Standard zstd and
LZ4 block decoding fails on the first block, and the dictionaries in `ZsDic.pack` don't help.
The executable has not been decoded, so the item-category enum integers are still unknown.

**RomFS game files** are ZSTD-compressed with per-type dictionaries. Files named `*.zs`
use dictionary compression; the dict_id is in the ZSTD frame header.

## ZsDic.pack dictionary IDs (confirmed)

| ID | Usage (confirmed) |
|---|---|
| 1 | Various game data files |
| 2 | Unknown |
| 3 | Dungeon bcett placement files (`InsideTheDekuTree_Static.bcett.byml.zs` → dict 3) |
| 4 | Unknown |

Always auto-detect dict_id from the ZSTD frame header; never hardcode.
