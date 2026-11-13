"""Song reward shuffle.

Each song is taught by one event flow (Event/EventFlow/<flow>.bfevfl.zs) that grants the
song through a length-prefixed `Item_Melody_*` string referenced by a single pointer.
Shuffling repoints that string to another song's name.
"""

from __future__ import annotations

import random
import re
import struct

# flow file name -> vanilla song item granted by that flow
SONG_SLOTS: dict[str, str] = {
    "Dm_MelodyGet_Zelda.bfevfl.zs": "Item_Melody_ZeldaLullaby",
    "Dm_MelodyGet_Epona.bfevfl.zs": "Item_Melody_EponaSong",
    "Dm_MelodyGet_Saria.bfevfl.zs": "Item_Melody_SariaSong",
    "Dm_MelodyGet_Sun_03.bfevfl.zs": "Item_Melody_SunSong",
    "Dm_MelodyGet_Time.bfevfl.zs": "Item_Melody_TimeSong",
    "Dm_MelodyGet_Storm.bfevfl.zs": "Item_Melody_StormSong",
    "Dm_MelodyGet_Forest.bfevfl.zs": "Item_Melody_ForestMinuet",
    "Dm_MelodyGet_Fire.bfevfl.zs": "Item_Melody_FireBolero",
    "Dm_MelodyGet_Water.bfevfl.zs": "Item_Melody_WaterSerenade",
    "Dm_MelodyGet_Spilit.bfevfl.zs": "Item_Melody_SpiritRequiem",
    "Dm_MelodyGet_Shadow.bfevfl.zs": "Item_Melody_ShadowNocturne",
    "Dm_MelodyGet_Shine.bfevfl.zs": "Item_Melody_LightPrelude",
}

# Friendly names usable in logic requirements.
SONG_DISPLAY_NAMES: dict[str, str] = {
    "Item_Melody_ZeldaLullaby": "Zelda's Lullaby",
    "Item_Melody_EponaSong": "Epona's Song",
    "Item_Melody_SariaSong": "Saria's Song",
    "Item_Melody_SunSong": "Sun's Song",
    "Item_Melody_TimeSong": "Song of Time",
    "Item_Melody_StormSong": "Song of Storms",
    "Item_Melody_ForestMinuet": "Minuet of Forest",
    "Item_Melody_FireBolero": "Bolero of Fire",
    "Item_Melody_WaterSerenade": "Serenade of Water",
    "Item_Melody_SpiritRequiem": "Requiem of Spirit",
    "Item_Melody_ShadowNocturne": "Nocturne of Shadow",
    "Item_Melody_LightPrelude": "Prelude of Light",
}


def song_location_name(flow_file: str) -> str:
    return flow_file.removesuffix(".bfevfl.zs")


def shuffle_songs(seed: int | random.Random) -> dict[str, str]:
    """Plain permutation of songs over song slots; logic is enforced by the planner."""
    rng = seed if isinstance(seed, random.Random) else random.Random(seed ^ 0x50465)
    songs = list(SONG_SLOTS.values())
    rng.shuffle(songs)
    return dict(zip(SONG_SLOTS, songs))


def patch_bfevfl_song(data: bytes, old_song: str, new_song: str) -> bytes:
    """Repoint every `[prefix.]old_song` string in a BFEVFL to `[prefix.]new_song`.

    New strings are appended just before the RELT block; only the single pointer to each old
    string is rewritten, so no other offsets move except RELT itself.
    """
    if old_song == new_song:
        return data
    buf = bytearray(data)
    relt_off = struct.unpack_from("<I", buf, 0x18)[0]
    if buf[relt_off:relt_off + 4] != b"RELT":
        raise ValueError("BFEVFL RELT block not found")
    head, relt = buf[:relt_off], buf[relt_off:]

    pattern = re.compile(rb"(?:[A-Za-z]+\.)?" + re.escape(old_song.encode()) + rb"\x00")
    repoints: list[tuple[int, bytes]] = []
    for m in pattern.finditer(bytes(head)):
        text = m.group()[:-1]
        len_off = m.start() - 2
        if len_off < 0 or struct.unpack_from("<H", head, len_off)[0] != len(text):
            continue
        ptrs = [p.start() for p in re.finditer(re.escape(struct.pack("<Q", len_off)), bytes(head))
                if p.start() % 8 == 0]
        if len(ptrs) != 1:
            raise ValueError(f"expected one pointer to {text!r}, found {len(ptrs)}")
        repoints.append((ptrs[0], text.replace(old_song.encode(), new_song.encode())))
    if not repoints:
        raise ValueError(f"{old_song} not found in event flow")

    for ptr_off, text in repoints:
        while len(head) % 2:
            head.append(0)
        struct.pack_into("<Q", head, ptr_off, len(head))
        head += struct.pack("<H", len(text)) + text + b"\x00"
    while len(head) % 8:
        head.append(0)

    new_relt_off = len(head)
    struct.pack_into("<I", relt, 4, new_relt_off)
    section_count = struct.unpack_from("<I", relt, 8)[0]
    for i in range(section_count):
        sec = 0x10 + i * 0x18
        # Section entry: u64 ptr, u32 offset, u32 size covering the data ahead of RELT, ...
        if struct.unpack_from("<I", relt, sec + 0x0C)[0] == relt_off:
            struct.pack_into("<I", relt, sec + 0x0C, new_relt_off)
    out = head + relt
    struct.pack_into("<I", out, 0x18, new_relt_off)
    struct.pack_into("<I", out, 0x1C, len(out))
    return bytes(out)
