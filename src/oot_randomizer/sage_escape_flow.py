"""Temple exits no longer move AllSage. AllSage follows the held medal count (medal_progress.py).

Vanilla Dm_SY_BancChange_EscapeDungeon marks a sage Complete when its temple is left, and that stays.
The Forest exit also sets AllSage to Step01_00. That absolute set would move AllSage back when a later
exit runs, so that one node is removed and its edges are pointed at its successor.
"""

from __future__ import annotations

import io

from evfl import EventFlow
from evfl.event import ActionEvent

from .game_flags import redirect_references

ESCAPE_FLOW = "Dm_SY_BancChange_EscapeDungeon.bfevfl.zs"
_PROGRESS_ACTION = "EventExecuteProgressChallengeStep"

# (node name, challenge, step) for each temple-exit step that is removed.
BYPASSED_STEPS: tuple[tuple[str, str, str], ...] = (
    ("Event208", "AllSage", "Step01_00"),
)


def _is_step(event, challenge: str, step: str) -> bool:
    body = event.data
    return (
        isinstance(body, ActionEvent)
        and body.actor_action.v is not None
        and body.actor_action.v.v == _PROGRESS_ACTION
        and body.params is not None
        and body.params.data.get("ChallengeName") == challenge
        and body.params.data.get("StepName") == step
    )


def patch_escape_sage_completes(data: bytes) -> bytes:
    """Remove the temple-exit AllSage Step01_00 set.

    Returns the input unchanged when the node is already gone. Raises ValueError when it is not the
    expected step, so an unknown build is not patched.
    """
    flow = EventFlow()
    flow.read(data)
    chart = flow.flowchart
    by_name = {event.name: event for event in chart.events}
    present = [name for name, _, _ in BYPASSED_STEPS if name in by_name]
    if not present:
        return data
    if len(present) != len(BYPASSED_STEPS):
        raise ValueError(f"{ESCAPE_FLOW}: only some of the temple-exit sage steps are present")
    for name, challenge, step in BYPASSED_STEPS:
        event = by_name[name]
        if not _is_step(event, challenge, step):
            raise ValueError(f"{ESCAPE_FLOW}: {name} is not the {challenge} {step} step")
        successor = event.data.nxt.v
        if successor is None:
            raise ValueError(f"{ESCAPE_FLOW}: {name} has no successor to bypass to")
        redirect_references(chart, event, successor)
        chart.events.remove(event)

    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()
