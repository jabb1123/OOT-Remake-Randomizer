"""Dampe's Graveyard race: the reward order follows the race, not the pouch.

The race hands out its rewards by ClearCount and the treasure box state. The first race gives the
hookshot slot, the second the heart piece slot, and so on. Before a race starts, the approach talk
asks the pouch whether the Hookshot or Longshot is owned. An owner is sent down the heart-piece
talk branch, which skips the hookshot-first talk, so the randomized hookshot slot is never offered.

Each pouch switch below is pointed at the branch a player without the item takes. The race then
starts from the same talk every time, and the box state decides the reward.
"""

from __future__ import annotations

import io

DAMPE_RACE_FLOW = "MiniGame_DampeRace.bfevfl.zs"

# (switch event, case, vanilla target, new target). The case is the pouch answer that points at the
# owned branch (case 0 = owned). The new target is the not-owned branch.
DAMPE_APPROACH_REROUTES: tuple[tuple[str, int, str, str], ...] = (
    ("Event262", 0, "Event261", "Event260"),  # Near: Longshot owned -> Event261 (heart talk)
    ("Event260", 0, "Event261", "Event14"),  # Near: Hookshot owned -> Event261 (heart talk)
    ("Event18", 0, "Event243", "Event0"),  # Talk: Longshot owned -> Event243 (heart talk)
    ("Event0", 0, "Event243", "Event5"),  # Talk: Hookshot owned -> Event243 (heart talk)
    ("Event61", 0, "Event245", "Event4"),  # Talk choice: Hookshot owned -> Event245 (heart talk)
)


def patch_dampe_race_approach(data: bytes) -> bytes:
    """Point each approach pouch switch at its not-owned branch.

    Returns the input unchanged when already patched. Raises ValueError when the flow does not have
    the expected switches, so a different game build is not patched silently.
    """
    from evfl import EventFlow
    from evfl.event import SwitchEvent

    flow = EventFlow()
    flow.read(data)
    by_name = {event.name: event for event in flow.flowchart.events}
    changed = False
    for source, key, owned_target, new_target in DAMPE_APPROACH_REROUTES:
        switch = by_name.get(source)
        if switch is None or not isinstance(switch.data, SwitchEvent) or key not in switch.data.cases:
            raise ValueError(f"{DAMPE_RACE_FLOW}: {source} has no pouch case {key}")
        target = by_name.get(new_target)
        if target is None:
            raise ValueError(f"{DAMPE_RACE_FLOW}: {new_target} is missing")
        case = switch.data.cases[key]
        if case.v is target:
            continue
        if case.v is not by_name.get(owned_target):
            raise ValueError(f"{DAMPE_RACE_FLOW}: {source} case {key} does not lead to {owned_target}")
        case.v = target
        changed = True
    if not changed:
        return data
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()
