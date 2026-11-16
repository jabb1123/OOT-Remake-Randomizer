"""Clear Mido's blocker flag when the story moves past Mido.

Mido's blocker flag only clears in the Mido talk path (Npc_Kokiri_Mido_Child). Two other paths
move the story past Mido without that talk, so the flag is cleared on each:

- Saria's warp out of Kokiri Forest (Dm_Kokiri_0145, and Goto_HyruleCastle's Lost Woods entry).
  Players who leave through Goron City and return through the Lost Woods never talk to Mido.
- The start of the Zelda visit (Goto_HyruleCastle's MeetZelda entry). That route never warps
  Saria, so the Saria clear does not run on it, and Mido's barrier stayed up.

Each clear also progresses the Meet_DekuTree challenge to Step02, as Mido's talk does, so the
Kokiri shop restocks the same way it does when Mido leaves.
"""

from __future__ import annotations

import io

from .game_flags import insert_bool_write_before, insert_challenge_progress_before

MIDO_BLOCKER_FLOW = "Dm_Kokiri_0145.bfevfl.zs"
GOTO_HYRULE_CASTLE_FLOW = "Goto_HyruleCastle.bfevfl.zs"
MIDO_BLOCKER_FLOWS = (MIDO_BLOCKER_FLOW, GOTO_HYRULE_CASTLE_FLOW)
MIDO_BLOCKER_FLAG = "KokiriForest_Npc_Kokiri_Mido_Child_Blocker"
GOTO_MEET_ZELDA_ENTRY = "Goto_HyruleCastle_MeetZelda"
# Mido's talk progresses this challenge before clearing his blocker. The Kokiri shop's second
# shelf set (Meet_DekuTree_IsAfter_Step02_Exp) is derived from it, so the barrier removal must
# progress it too or the shop keeps its pre-Mido stock.
MEET_DEKU_TREE_CHALLENGE = "Meet_DekuTree"
MEET_DEKU_TREE_STEP = "Step02"

_SARIA_ACTOR = "Npc_Kokiri_Saria_Child"
_SARIA_WARP_ACTION = "EventWarpToTargetPosAndRot"


def _find_action(target_actor: str, target_action: str):
    def find(chart):
        from evfl.event import ActionEvent

        matches = [
            e for e in chart.events
            if isinstance(e.data, ActionEvent)
            and e.data.actor.v.identifier.name == target_actor
            and e.data.actor_action.v.v == target_action
        ]
        if len(matches) != 1:
            raise ValueError(f"expected one {target_actor}.{target_action} action, found {len(matches)}")
        return matches[0]

    return find


def _find_entry(entry_name: str):
    def find(chart):
        matches = [e for e in chart.entry_points if e.name == entry_name]
        if len(matches) != 1:
            raise ValueError(f"expected one {entry_name} entry point, found {len(matches)}")
        return matches[0].main_event.v

    return find


def _write_flag_before(data: bytes, find_target, flag: str, value: bool) -> bytes:
    """Insert a flag write before the event that `find_target(chart)` returns, and serialize."""
    from evfl import EventFlow

    flow = EventFlow()
    flow.read(data)
    insert_bool_write_before(flow.flowchart, find_target(flow.flowchart), flag, value)

    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def set_flag_before_action(data: bytes, target_actor: str, target_action: str,
                           flag: str, value: bool) -> bytes:
    """Insert a GameDataActor flag write just before the single matching action in the flow.

    Every edge into the target action is rerouted through the new node, so the write runs on
    every path that reaches the target. Raises ValueError unless exactly one action matches.
    """
    return _write_flag_before(data, _find_action(target_actor, target_action), flag, value)


def _release_mido_before(data: bytes, find_target) -> bytes:
    """Progress Meet_DekuTree to Step02, then clear Mido's blocker, right before the target event.

    Mido's talk runs the progression before the flag write, so the order matches vanilla.
    """
    from evfl import EventFlow

    flow = EventFlow()
    flow.read(data)
    target = find_target(flow.flowchart)
    insert_challenge_progress_before(flow.flowchart, target, MEET_DEKU_TREE_CHALLENGE, MEET_DEKU_TREE_STEP)
    insert_bool_write_before(flow.flowchart, target, MIDO_BLOCKER_FLAG, False)

    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def clear_mido_blocker(data: bytes) -> bytes:
    """Clear the Mido blocker flag right before Saria's warp out of Kokiri Forest in the flow."""
    return _release_mido_before(data, _find_action(_SARIA_ACTOR, _SARIA_WARP_ACTION))


def clear_mido_blocker_on_zelda_visit(data: bytes) -> bytes:
    """Clear the Mido blocker flag at the start of the Zelda visit, before any other event runs."""
    return _release_mido_before(data, _find_entry(GOTO_MEET_ZELDA_ENTRY))


# (flow, transform) pairs applied in order. Goto_HyruleCastle takes two transforms, and each
# re-reads the NUP, so they chain.
MIDO_BLOCKER_PATCHES = (
    (MIDO_BLOCKER_FLOW, clear_mido_blocker),
    (GOTO_HYRULE_CASTLE_FLOW, clear_mido_blocker),
    (GOTO_HYRULE_CASTLE_FLOW, clear_mido_blocker_on_zelda_visit),
)
