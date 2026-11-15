"""Starting inventory: the Small Stick Bag and Small Nut Bag are added when a new game begins.

The vanilla game gives each Small bag on its first pickup (the first Deku Stick, the first
Deku Nut), and shops give them on purchase. A stick or nut bundle placed in a heart slot goes
through the heart pickup, which does not add the bag, so the player would be stuck at 0/0.
The bags are added here instead, as silent pouch adds at the start of `Opening_Introduction`.
They run whether or not the intro is skipped, because `skip_intro_cutscene` only changes the
event after the entry point's first event.
"""

from __future__ import annotations

import io

from .cutscene_skips import INTRO_ENTRY_POINT, skip_intro_cutscene

STARTING_BAGS = ("Item_StickBag_Small", "Item_NutBag_Small")
POUCH_ACTOR = "PouchSystemActor"
POUCH_ACTION = "EventTriggerAddOrRemovePouchContent"
_EVENT_NAME_PREFIX = "Rando_StartingBag_"


def add_starting_bags(data: bytes) -> bytes:
    """Insert a silent pouch add for each STARTING_BAGS entry at the start of `Opening_Introduction`."""
    from evfl import EventFlow
    from evfl.actor import Actor
    from evfl.common import ActorIdentifier, StringHolder
    from evfl.container import Container
    from evfl.event import ActionEvent, Event
    from evfl.util import make_index, make_rindex

    flow = EventFlow()
    flow.read(data)
    chart = flow.flowchart
    entry = next((e for e in chart.entry_points if e.name == INTRO_ENTRY_POINT), None)
    if entry is None or entry.main_event.v is None:
        raise ValueError(f"entry point {INTRO_ENTRY_POINT!r} not found in event flow")

    actor = next((a for a in chart.actors if a.identifier.name == POUCH_ACTOR), None)
    if actor is None:
        actor = Actor()
        actor.identifier = ActorIdentifier(POUCH_ACTOR)
        chart.actors.append(actor)
    action = next((a for a in actor.actions if a.v == POUCH_ACTION), None)
    if action is None:
        action = StringHolder(POUCH_ACTION)
        actor.actions.append(action)

    # Build the chain back to front so the first bag is the entry point's first action.
    next_event = entry.main_event.v
    for bag in reversed(STARTING_BAGS):
        params = Container()
        params.data.update({
            "Num": 1,
            "IsEquipDIrect": False,
            "IsSetMessageTargetActorName": False,
            "Actor": bag,
            "IsGetEvent": False,
        })

        event = Event()
        event.name = _EVENT_NAME_PREFIX + bag
        event.data = ActionEvent()
        event.data.actor = make_rindex(actor)
        event.data.actor_action = make_rindex(action)
        event.data.params = params
        event.data.nxt = make_index(next_event)
        chart.events.append(event)
        next_event = event
    entry.main_event = make_index(next_event)

    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


def patch_intro_flow(data: bytes, skip_intro: bool) -> bytes:
    """Apply the starting bags, then the intro skip when requested, to OpeningEvent."""
    data = add_starting_bags(data)
    return skip_intro_cutscene(data) if skip_intro else data
