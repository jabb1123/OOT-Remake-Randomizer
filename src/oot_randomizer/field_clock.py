"""Start the Hyrule Field clock at the end of the Zelda's Lullaby flow.

The owl route sets the clock in Dm_HrlField_0000 and Dm_HrlField_0010. The Zelda route never sets it,
so time stays frozen after Impa. Dm_MelodyGet_Zelda is the flow that runs the Impa conversation, and
the clock write goes right before its final action so it runs whatever branch reaches the end.
"""

from __future__ import annotations

import io

from .game_flags import insert_new_action_before

ZELDA_MELODY_FLOW = "Dm_MelodyGet_Zelda.bfevfl.zs"
CLOCK_ANCHOR_ACTION = "EventTriggerZeldaNotesSimpleAddNPCTalkCount"
WORLD_MANAGER_ACTOR = "EventWorldManagerController"
SET_TIME_ACTION = "EventTrigger_SetTime"
CLOCK_HOUR = 7
CLOCK_MINUTE = 0


def start_clock_at_zelda_flow_end(data: bytes) -> bytes:
    """Set the clock to 7:00 right before the Zelda's Lullaby flow's final action."""
    from evfl import EventFlow
    from evfl.event import ActionEvent

    flow = EventFlow()
    flow.read(data)
    chart = flow.flowchart
    anchor = next(
        (
            e for e in chart.events
            if isinstance(e.data, ActionEvent) and str(e.data.actor_action.v) == CLOCK_ANCHOR_ACTION
        ),
        None,
    )
    if anchor is None:
        raise ValueError(f"{CLOCK_ANCHOR_ACTION} not found in event flow")

    insert_new_action_before(
        chart,
        anchor,
        WORLD_MANAGER_ACTOR,
        SET_TIME_ACTION,
        {"TimeHour": CLOCK_HOUR, "TimeMin": CLOCK_MINUTE},
    )
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()
