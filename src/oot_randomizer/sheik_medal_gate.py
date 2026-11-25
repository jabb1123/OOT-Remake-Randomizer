"""Sheik's return-to-child gate, opened by any of the five dungeon medals held.

When a sage's melody is played, AllSage's MeetSheik_And_Gone entry (Event178) checks the
AllSage_AwakeSage_Fire_Or_Forest flag. Only the vanilla Fire and Forest medal flows set that flag, so a
Fire or Forest medal from another location would leave Sheik in place. This patch keeps the flag check
and adds a chain of held-medal checks after it. Any dungeon medal held sets
AllSage_MeetSheik_And_Gone the same way the flag does. The checks read the IsGet.Item_Medal_* bools
(see medal_progress.held_medal_bool).

The Light medal is not in the chain. It is a shuffled item now, so holding it alone must not open Sheik.
Any dungeon medal is looser than the logic's two-medal rule (has_two_medals), so it never blocks progress.
"""

from __future__ import annotations

from copy import deepcopy
import io

from evfl import EventFlow
from evfl.event import Event, SwitchEvent
from evfl.util import make_rindex

from .game_flags import game_data_actor
from .medal_progress import _HELD_QUERY, held_medal_bool
from .stone_gates import _query

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
    """Add a held-medal check for each dungeon medal after the Fire or Forest flag check.

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

    game_data = game_data_actor(flow.flowchart)
    query = _query(game_data, _HELD_QUERY)
    # Built last to first so each check's not-held case can point at the check after it.
    following: Event | None = None
    for medal in reversed(MEDAL_ITEMS):
        check = Event()
        check.name = f"{_CHECK_PREFIX}{medal.removeprefix('Item_Medal_')}"
        node = SwitchEvent()
        node.actor = make_rindex(game_data)
        node.actor_query = make_rindex(query)
        node.params = deepcopy(gate.data.params)
        node.params.data["GameDataName"] = held_medal_bool(medal)
        # EventQueryIsGameDataBool: case 1 = held, case 0 = not held.
        node.cases = {1: make_rindex(awake)}
        if following is not None:
            node.cases[0] = make_rindex(following)
        check.data = node
        flow.flowchart.events.append(check)
        following = check
    gate.data.cases[1] = make_rindex(following)

    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()
