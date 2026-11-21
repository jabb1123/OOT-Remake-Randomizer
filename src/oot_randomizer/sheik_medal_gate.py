"""Sheik's return-to-child gate, opened by any of the five dungeon medals in the pouch.

When a sage's melody is played, AllSage's MeetSheik_And_Gone entry (Event178) checks the
AllSage_AwakeSage_Fire_Or_Forest flag. Only the vanilla Fire and Forest medal flows set that flag, so a
Fire or Forest medal from another location would leave Sheik in place. This patch keeps the flag check
and adds a chain of pouch queries after it. Any dungeon medal in the pouch sets
AllSage_MeetSheik_And_Gone the same way the flag does.

The Light medal is not in the chain. It comes from the first trip to adulthood, so the player always
has it before a dungeon medal can be held. Requiring a dungeon medal therefore matches the logic's
"two medals including Light".
"""

from __future__ import annotations

from copy import deepcopy
import io

from evfl import EventFlow
from evfl.event import Event, SwitchEvent
from evfl.util import make_rindex

from .stone_gates import _POUCH_QUERY, _pouch_actor, _query

ALLSAGE_FLOW = "AllSage.bfevfl.zs"

_GATE_SWITCH = "Event178"
_FLAG_BOOL = "AllSage_AwakeSage_Fire_Or_Forest"
_AWAKE_EVENT = "Event181"
_CHECK_PREFIX = "MedalCheck_"
MEDAL_ITEMS: tuple[str, ...] = (
    "Item_Medal_Forest",
    "Item_Medal_Fire",
    "Item_Medal_Water",
    "Item_Medal_Shadow",
    "Item_Medal_Spirit",
)


def patch_sheik_medal_gate(data: bytes) -> bytes:
    """Add a pouch check for each dungeon medal after the Fire or Forest flag check.

    Returns the input unchanged when the chain is already present. Raises ValueError when the flow
    does not have the expected gate, so a different game build is not patched silently.
    """
    flow = EventFlow()
    flow.read(data)
    if any(event.name.startswith(_CHECK_PREFIX) for event in flow.flowchart.events):
        return data
    by_name = {event.name: event for event in flow.flowchart.events}
    gate = by_name.get(_GATE_SWITCH)
    awake = by_name.get(_AWAKE_EVENT)
    if (
        gate is None or not isinstance(gate.data, SwitchEvent) or gate.data.params is None
        or gate.data.params.data.get("GameDataName") != _FLAG_BOOL
        or set(gate.data.cases) != {0} or awake is None or gate.data.cases[0].v is not awake
    ):
        raise ValueError(f"{ALLSAGE_FLOW}: {_GATE_SWITCH} is not the Fire or Forest flag gate")

    pouch = _pouch_actor(flow)
    query = _query(pouch, _POUCH_QUERY)
    # Built last to first so each check's false case can point at the check after it.
    following: Event | None = None
    for medal in reversed(MEDAL_ITEMS):
        check = Event()
        check.name = f"{_CHECK_PREFIX}{medal.removeprefix('Item_Medal_')}"
        node = SwitchEvent()
        node.actor = make_rindex(pouch)
        node.actor_query = make_rindex(query)
        node.params = deepcopy(gate.data.params)
        node.params.data = {"Actor": medal, "Num": 1}
        node.cases = {0: make_rindex(awake)}
        if following is not None:
            node.cases[1] = make_rindex(following)
        check.data = node
        flow.flowchart.events.append(check)
        following = check
    gate.data.cases[1] = make_rindex(following)

    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()
