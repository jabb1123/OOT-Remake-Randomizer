"""Hylia's windmill NPC: the Song of Storms slot is handed out once, by this NPC.

The talk and ocarina gates in Npc_Hylia_009_Adult read the pouch (IsGet.Item_Melody_StormSong). When
the song came from another location, the pouch already holds it, so the gates skip the award and this
NPC's randomized storm song slot is never offered.

The gates below read the NPC's own flag instead. That flag is set only when the award flow finishes
(After_GetStormSong, reached from the end of Dm_MelodyGet_Storm). Until then, the not-yet-awarded
branch runs even when the pouch already has the song.
"""

from __future__ import annotations

import io

STORM_NPC_FLOW = "Npc_Hylia_009_Adult.bfevfl.zs"

_POUCH_BOOL = "IsGet.Item_Melody_StormSong"
# Set on the award path (Event80). Event97 also sets it, but only after the gate below has already
# passed, so it cannot mark the award as done early.
STORM_AWARDED_BOOL = "KakarikoVillage_Npc_Hylia_009_OcarinaStormSong_PlayedFront"

# Talk gate (Event9), ocarina gates on the front (Event17) and back (Event69) paths. Each case map is
# unchanged: true (case 0) is the already-awarded branch, false (case 1) the award branch.
_GATE_SWITCHES = ("Event9", "Event17", "Event69")


def patch_storm_song_npc(data: bytes) -> bytes:
    """Point each storm song gate at the NPC's awarded flag instead of the pouch.

    Returns the input unchanged when already patched. Raises ValueError when the flow does not have
    the expected gates, so a different game build is not patched silently.
    """
    from evfl import EventFlow
    from evfl.event import SwitchEvent

    flow = EventFlow()
    flow.read(data)
    by_name = {event.name: event for event in flow.flowchart.events}
    changed = False
    for name in _GATE_SWITCHES:
        switch = by_name.get(name)
        if switch is None or not isinstance(switch.data, SwitchEvent) or not switch.data.params:
            raise ValueError(f"{STORM_NPC_FLOW}: {name} is not a switch")
        params = switch.data.params.data
        current = params.get("GameDataName")
        if current == STORM_AWARDED_BOOL:
            continue
        if current != _POUCH_BOOL:
            raise ValueError(f"{STORM_NPC_FLOW}: {name} reads {current!r}, not {_POUCH_BOOL}")
        params["GameDataName"] = STORM_AWARDED_BOOL
        changed = True
    if not changed:
        return data
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()
