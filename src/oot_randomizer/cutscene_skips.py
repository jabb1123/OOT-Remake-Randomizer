"""Event-flow edits that unlink a cutscene transition so it never plays.

Each helper walks the action chain of one entry point and removes the `EventTransition` to a
given demo by pointing the event before it straight at the event after it. The rewritten file keeps
its exact size and layout; only one event's `next` index changes.

The intro wake-up demo (Dm_Kokiri_0030) is a timeline-only cutscene. `OpeningEvent` plays it, then
continues through the same skip check the game uses when the player presses skip, so unlinking it
returns to the normal post-cutscene path with the cutscene removed.
"""

from __future__ import annotations

import io

INTRO_EVENT_FLOW = "OpeningEvent.bfevfl.zs"
INTRO_ENTRY_POINT = "Opening_Introduction"
INTRO_DEMO_EVENT = "Dm_Kokiri_0030"


def unlink_transition(data: bytes, entry_point_name: str, demo_event: str) -> bytes:
    """Unlink the EventTransition to `demo_event` from the chain of `entry_point_name`.

    Returns `data` unchanged when the transition is not in the chain.
    """
    from evfl import EventFlow
    from evfl.event import ActionEvent
    from evfl.util import make_index

    flow = EventFlow()
    flow.read(data)
    chart = flow.flowchart
    entry = next((e for e in chart.entry_points if e.name == entry_point_name), None)
    if entry is None or entry.main_event.v is None:
        raise ValueError(f"entry point {entry_point_name!r} not found in event flow")

    prev = None
    event = entry.main_event.v
    seen: set[int] = set()
    while event is not None and id(event) not in seen:
        seen.add(id(event))
        body = event.data
        if not isinstance(body, ActionEvent):
            break
        params = body.params.data if body.params else {}
        if str(body.actor_action.v) == "EventTransition" and params.get("EventName") == demo_event:
            if prev is None:
                raise ValueError(f"{demo_event} is the first event of {entry_point_name!r}")
            prev.data.nxt = make_index(body.nxt.v)
            out = io.BytesIO()
            flow.write(out)
            return out.getvalue()
        prev, event = event, body.nxt.v
    return data


def skip_intro_demo(data: bytes) -> bytes:
    """Unlink the Dm_Kokiri_0030 wake-up transition from the Opening_Introduction entry point."""
    return unlink_transition(data, INTRO_ENTRY_POINT, INTRO_DEMO_EVENT)
