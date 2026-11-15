"""Clear Mido's blocker flag when Saria leaves Kokiri Forest for the Sacred Grove.

Mido's blocker flag only clears in the Mido talk path (Npc_Kokiri_Mido_Child). When the player
leaves through Goron City and returns through the Lost Woods, that talk never happens, so Mido
drops his pose while the blocker flag stays set and the Deku Tree stays unreachable. Saria's warp
is the point where the story has moved past Mido, so the flag is cleared there. Saria is warped
out in two flows: Dm_Kokiri_0145 (Saria leaves) and Goto_HyruleCastle (the Zelda trip, which can
run before Mido is ever talked to).
"""

from __future__ import annotations

import io

from .game_flags import insert_bool_write_before

MIDO_BLOCKER_FLOW = "Dm_Kokiri_0145.bfevfl.zs"
GOTO_HYRULE_CASTLE_FLOW = "Goto_HyruleCastle.bfevfl.zs"
MIDO_BLOCKER_FLOWS = (MIDO_BLOCKER_FLOW, GOTO_HYRULE_CASTLE_FLOW)
MIDO_BLOCKER_FLAG = "KokiriForest_Npc_Kokiri_Mido_Child_Blocker"

_SARIA_ACTOR = "Npc_Kokiri_Saria_Child"
_SARIA_WARP_ACTION = "EventWarpToTargetPosAndRot"


def set_flag_before_action(data: bytes, target_actor: str, target_action: str,
                           flag: str, value: bool) -> bytes:
    """Insert a GameDataActor flag write just before the single matching action in the flow.

    Every edge into the target action is rerouted through the new node, so the write runs on
    every path that reaches the target. Raises ValueError unless exactly one action matches.
    """
    from evfl import EventFlow
    from evfl.event import ActionEvent

    flow = EventFlow()
    flow.read(data)
    chart = flow.flowchart

    matches = [
        e for e in chart.events
        if isinstance(e.data, ActionEvent)
        and e.data.actor.v.identifier.name == target_actor
        and e.data.actor_action.v.v == target_action
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one {target_actor}.{target_action} action, found {len(matches)}")
    target = matches[0]

    insert_bool_write_before(chart, target, flag, value)

    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def clear_mido_blocker(data: bytes) -> bytes:
    """Clear the Mido blocker flag right before Saria's warp out of Kokiri Forest in the flow."""
    return set_flag_before_action(data, _SARIA_ACTOR, _SARIA_WARP_ACTION, MIDO_BLOCKER_FLAG, False)
