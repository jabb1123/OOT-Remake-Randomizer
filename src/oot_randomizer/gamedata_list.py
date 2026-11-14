"""GameDataList (save-backed game data) edits for shopsanity and randomized NPC grants.

Bool entries are stored in the Bool list of GameDataList.Product.100.byml. Names are
hashed with MurmurHash3 x86_32 (seed 0). Save-layout fields in MetaData are adjusted
for the bytes the new bools add to the progress save (SaveFileIndex 0).
"""

from __future__ import annotations

import math

from .byml7 import U32, dump_byml7, parse_byml7_typed

GAME_DATA_LIST = "GameDataList.Product.100.byml.zs"
SHOP_SOLDOUT_NAMES = tuple(f"KokiriForest_Shop_SoldOut_{i}" for i in range(8))
# Set when the Din's Fire fairy's randomized item has been handed over. The fairy's "already got
# it" check reads this instead of IsGet.Item_DinFire, which is not registered for every item.
DIN_FAIRY_RECEIVED_BOOL = "Rando_Din_FairyGrant_Received"
NPC_GRANT_BOOL_NAMES = (DIN_FAIRY_RECEIVED_BOOL,)
_PROGRESS_SAVE_INDEX = 0
_SOLDOUT_RESET_TYPE = 9  # ResetType for shop sold-out bools (see docs/shopsanity.md)
_NPC_GRANT_RESET_TYPE = 8  # same as the IsGet.* story bools


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


def _append_bools(root: dict, names: tuple[str, ...], reset_type: int) -> list[str]:
    """Append save-backed Bool entries for `names` that are not registered yet; return the added names."""
    bools = root["Data"]["Bool"]
    existing = {int(e["Hash"]) for e in bools}
    new_names = [n for n in names if murmur3_32(n.encode()) not in existing]
    if not new_names:
        return []

    progress_bools = sum(1 for e in bools if int(e["SaveFileIndex"]) == _PROGRESS_SAVE_INDEX)
    for name in new_names:
        bools.append({
            "DefaultValue": False,
            "Hash": U32(murmur3_32(name.encode())),
            "ResetTypeValue": reset_type,
            "SaveFileIndex": _PROGRESS_SAVE_INDEX,
        })

    # Bools are bit-packed, so the progress block grows by ceil(bits / 8) bytes.
    grown_bytes = math.ceil((progress_bools + len(new_names)) / 8) - math.ceil(progress_bools / 8)
    meta = root["MetaData"]
    meta["SaveDataSize"][_PROGRESS_SAVE_INDEX] = U32(int(meta["SaveDataSize"][_PROGRESS_SAVE_INDEX]) + grown_bytes)
    meta["AllDataSaveSize"] = U32(int(meta["AllDataSaveSize"]) + grown_bytes)
    return new_names


def add_shop_soldout_bools(root: dict) -> list[str]:
    """Append the Kokiri Shop sold-out Bool entries to a parsed GameDataList.

    Returns the names that were added; an empty list means they already exist and nothing changed.
    """
    return _append_bools(root, SHOP_SOLDOUT_NAMES, _SOLDOUT_RESET_TYPE)


def add_npc_grant_bools(root: dict) -> list[str]:
    """Append the randomized NPC grant Bool entries (see NPC_GRANT_BOOL_NAMES) to a parsed GameDataList."""
    return _append_bools(root, NPC_GRANT_BOOL_NAMES, _NPC_GRANT_RESET_TYPE)


def patch_gamedata_list(raw: bytes, *, shop: bool = True, npc_grant: bool = False) -> bytes:
    root = parse_byml7_typed(raw)
    added: list[str] = []
    if shop:
        added += add_shop_soldout_bools(root)
    if npc_grant:
        added += add_npc_grant_bools(root)
    if not added:
        return raw
    return dump_byml7(root, big_endian=True, version=7)
