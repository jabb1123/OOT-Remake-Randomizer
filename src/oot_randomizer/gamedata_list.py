"""GameDataList (save-backed game data) edits for shopsanity.

Bool entries are stored in the Bool list of GameDataList.Product.100.byml. Names are
hashed with MurmurHash3 x86_32 (seed 0). Save-layout fields in MetaData are adjusted
for the bytes the new bools add to the progress save (SaveFileIndex 0).
"""

from __future__ import annotations

import math

from .byml7 import U32, dump_byml7, parse_byml7_typed

GAME_DATA_LIST = "GameDataList.Product.100.byml.zs"
SHOP_SOLDOUT_NAMES = tuple(f"KokiriForest_Shop_SoldOut_{i}" for i in range(8))
_PROGRESS_SAVE_INDEX = 0
_SOLDOUT_RESET_TYPE = 9  # same as KokiriForest_Shop_SelectActor_Shield_Deku (Bool 8888)


def murmur3_32(data: bytes, seed: int = 0) -> int:
    c1, c2 = 0xCC9E2D51, 0x1B873593
    h = seed & 0xFFFFFFFF
    n = len(data)
    nblocks = n // 4
    for i in range(nblocks):
        k = int.from_bytes(data[4 * i:4 * i + 4], "little")
        k = (k * c1) & 0xFFFFFFFF
        k = ((k << 15) | (k >> 17)) & 0xFFFFFFFF
        k = (k * c2) & 0xFFFFFFFF
        h ^= k
        h = ((h << 13) | (h >> 19)) & 0xFFFFFFFF
        h = (h * 5 + 0xE6546B64) & 0xFFFFFFFF
    tail = data[nblocks * 4:]
    if tail:
        k = 0
        if len(tail) >= 3:
            k ^= tail[2] << 16
        if len(tail) >= 2:
            k ^= tail[1] << 8
        k ^= tail[0]
        k = (k * c1) & 0xFFFFFFFF
        k = ((k << 15) | (k >> 17)) & 0xFFFFFFFF
        k = (k * c2) & 0xFFFFFFFF
        h ^= k
    h ^= n
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & 0xFFFFFFFF
    h ^= h >> 16
    return h


def add_shop_soldout_bools(root: dict) -> list[str]:
    """Append the Kokiri Shop sold-out Bool entries to a parsed GameDataList.

    Returns the names that were added; an empty list means they already exist and nothing changed.
    """
    bools = root["Data"]["Bool"]
    existing = {int(e["Hash"]) for e in bools}
    new_names = [n for n in SHOP_SOLDOUT_NAMES if murmur3_32(n.encode()) not in existing]
    if not new_names:
        return []

    progress_bools = sum(1 for e in bools if int(e["SaveFileIndex"]) == _PROGRESS_SAVE_INDEX)
    for name in new_names:
        bools.append({
            "DefaultValue": False,
            "Hash": U32(murmur3_32(name.encode())),
            "ResetTypeValue": _SOLDOUT_RESET_TYPE,
            "SaveFileIndex": _PROGRESS_SAVE_INDEX,
        })

    # Bools are bit-packed, so the progress block grows by ceil(bits / 8) bytes.
    grown_bytes = math.ceil((progress_bools + len(new_names)) / 8) - math.ceil(progress_bools / 8)
    meta = root["MetaData"]
    meta["SaveDataSize"][_PROGRESS_SAVE_INDEX] = U32(int(meta["SaveDataSize"][_PROGRESS_SAVE_INDEX]) + grown_bytes)
    meta["AllDataSaveSize"] = U32(int(meta["AllDataSaveSize"]) + grown_bytes)
    return new_names


def patch_gamedata_list(raw: bytes) -> bytes:
    root = parse_byml7_typed(raw)
    if not add_shop_soldout_bools(root):
        return raw
    return dump_byml7(root, big_endian=True, version=7)
