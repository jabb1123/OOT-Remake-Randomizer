"""Event-flow edits that redirect a cutscene so it never plays.

Each helper walks the action chain of one entry point and points the event before a cutscene straight
at the event after it. The rewritten file keeps every event and entry point; only the `next` index of
the redirected event changes. evfl re-lays out the file on write, so the byte size can shift slightly.

`Opening_Introduction` in `OpeningEvent` runs the whole intro: it stops the BGM, fades out, runs the
Meet_DekuTree challenge, pans the camera, plays the wake-up demo (Dm_Kokiri_0030), then reaches a skip
check (Event23). The skip branch (Event24) is the path the game takes when the player presses skip. It
does the Navi warp, restarts the BGM, and autosaves. `skip_intro_cutscene` points the intro setup
straight at that branch, so the staging and demo are never reached.
"""

from __future__ import annotations

import io

INTRO_EVENT_FLOW = "OpeningEvent.bfevfl.zs"
INTRO_ENTRY_POINT = "Opening_Introduction"
# Sets the time to 6 AM and sits right before the intro staging. Its `next` is redirected.
INTRO_SETUP_EVENT = "Event9"
INTRO_SKIP_SWITCH = "Event23"
INTRO_SKIP_QUERY = "EventQueryIsEventSkipedMostRecent"
INTRO_SKIP_CASE = 1
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


def skip_intro_cutscene(data: bytes) -> bytes:
    """Redirect the intro setup past the whole Opening_Introduction cutscene.

    The setup event's `next` is pointed at the skip-check's skip branch. The skipped staging
    events are left in place but unreachable.
    """
    from evfl import EventFlow
    from evfl.event import ActionEvent, SwitchEvent
    from evfl.util import make_index

    flow = EventFlow()
    flow.read(data)
    events = {e.name: e for e in flow.flowchart.events}
    setup = events.get(INTRO_SETUP_EVENT)
    switch = events.get(INTRO_SKIP_SWITCH)
    if setup is None or switch is None:
        raise ValueError(f"{INTRO_SETUP_EVENT} or {INTRO_SKIP_SWITCH} missing from event flow")
    if not isinstance(setup.data, ActionEvent) or not isinstance(switch.data, SwitchEvent):
        raise ValueError("unexpected event types in the intro chain")
    if str(switch.data.actor_query.v) != INTRO_SKIP_QUERY:
        raise ValueError(f"{INTRO_SKIP_SWITCH} is not the skip check")
    target = switch.data.cases[INTRO_SKIP_CASE].v
    setup.data.nxt = make_index(target)
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()
