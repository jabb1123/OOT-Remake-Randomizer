"""Dampe's Graveyard race: approach dialogue and reward order.

Approach: the Dampe talk checks whether the pouch holds the Hookshot or Longshot. Owners go down the
heart-piece talk branch, so each approach switch is repointed so a player without the item takes the
not-owned talk.

Rewards: every finished race adds one to MiniGame_DampeRace_ClearCount, including for a player without
the Hookshot. The Result switch (Event275) reads that count. Race 1 gives the hookshot slot, race 2
gives the heart piece when under a minute (rupee-low when over), and race 3 and later give a rupee.
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

# Post-race pouch switch. The not-owned answer (case 1) skipped Event379, so the race never counted.
DAMPE_CLEAR_SWITCH = "Event442"
DAMPE_CLEAR_CASE = 1
DAMPE_CLEAR_VANILLA = "Event33"
DAMPE_CLEAR_TARGET = "Event379"  # MiniGame_DampeRace_Clear: ClearCount +1, then Event33

# Result entry: switches on MiniGame_DampeRace_ClearCount and picks the reward for the race.
DAMPE_RESULT_SWITCH = "Event275"
DAMPE_FIRST_RACE_CASE = 1  # ClearCount 1: hookshot slot
DAMPE_SECOND_RACE_CASE = 2  # ClearCount 2: timer check, heart piece under a minute, rupee-low over
DAMPE_RUPEE_FROM_CASE = 3  # ClearCount 3 and up: rupee
DAMPE_TIMER_CHECK = "Event359"
# Vanilla hookshot award: Talk_55, then Event353 flags the box, Event355 sets AppearHookShot and
# Event167 shows the box.
DAMPE_HOOKSHOT_TALK = "Event327"
# Vanilla rupee box: Talk_28, then Event430 -> Event404 (RupeeHigh box SUB). The SUB only flags the box
# when the state is already AppearRupee, so DAMPE_RUPEE_SETTER sets that before the talk.
DAMPE_RUPEE_TALK = "Event393"
DAMPE_RUPEE_CHAIN = ("Event430", "Event404")

# Post-race auto path (Event33 -> Event342). Its heart branch is cut so the Result switch alone
# hands out rewards.
DAMPE_HEART_RESULT_SWITCH = "Event342"
DAMPE_HEART_RESULT_CASE = 1
DAMPE_HEART_RESULT_TIMER = "Event448"
DAMPE_HEART_RESULT_TALK = "Event394"  # Same talk as HeartGeted false

DAMPE_RUPEE_SETTER = "DampeRace_RupeeFromThird"
_SET_ENUM_ACTION = "EventTriggerSetGameDataEnum"
_BOX_STATE = "Minigame_DampeRace_TreasureBoxState"
_RUPEE_BOX_STATE = "AppearRupee"


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


def _switch_cases(by_name, switch_name):
    from evfl.event import SwitchEvent

    switch = by_name.get(switch_name)
    if switch is None or not isinstance(switch.data, SwitchEvent):
        raise ValueError(f"{DAMPE_RACE_FLOW}: {switch_name} is not a switch")
    return switch.data.cases


def patch_dampe_race_rewards(data: bytes) -> bytes:
    """Hand out the hookshot slot, then the heart piece, then rupees, by ClearCount.

    The Result switch gets: case 1 -> the vanilla hookshot award talk, case 2 -> the timer check (heart
    piece under a minute, rupee-low over), case 3 and up -> a rupee setter that feeds the vanilla rupee
    talk and box. The post-race heart branch on Event342 is set to talk only, so a race never hands out
    a heart piece twice.

    Returns the input unchanged when already patched. Raises ValueError when the flow does not have
    the expected nodes, so a different game build is not patched silently.
    """
    from evfl import EventFlow
    from evfl.container import Container
    from evfl.event import ActionEvent, Event
    from evfl.util import make_index, make_rindex

    from .game_flags import GAME_DATA_ACTOR, _find_or_create_action, game_data_actor

    flow = EventFlow()
    flow.read(data)
    chart = flow.flowchart
    by_name = {event.name: event for event in chart.events}
    if DAMPE_RUPEE_SETTER in by_name:
        return data
    for name in (
        DAMPE_CLEAR_SWITCH,
        DAMPE_CLEAR_TARGET,
        DAMPE_CLEAR_VANILLA,
        DAMPE_RESULT_SWITCH,
        DAMPE_TIMER_CHECK,
        DAMPE_HOOKSHOT_TALK,
        DAMPE_RUPEE_TALK,
        *DAMPE_RUPEE_CHAIN,
        DAMPE_HEART_RESULT_SWITCH,
        DAMPE_HEART_RESULT_TIMER,
        DAMPE_HEART_RESULT_TALK,
    ):
        if name not in by_name:
            raise ValueError(f"{DAMPE_RACE_FLOW}: {name} is missing")

    clear_case = _switch_cases(by_name, DAMPE_CLEAR_SWITCH).get(DAMPE_CLEAR_CASE)
    if clear_case is None:
        raise ValueError(f"{DAMPE_RACE_FLOW}: {DAMPE_CLEAR_SWITCH} has no not-owned case")
    if clear_case.v is by_name[DAMPE_CLEAR_VANILLA]:
        clear_case.v = by_name[DAMPE_CLEAR_TARGET]
    elif clear_case.v is not by_name[DAMPE_CLEAR_TARGET]:
        raise ValueError(f"{DAMPE_RACE_FLOW}: {DAMPE_CLEAR_SWITCH} case {DAMPE_CLEAR_CASE} is not vanilla")

    result_cases = _switch_cases(by_name, DAMPE_RESULT_SWITCH)
    timer = by_name[DAMPE_TIMER_CHECK]
    first = result_cases.get(DAMPE_FIRST_RACE_CASE)
    if first is None or first.v is not timer:
        raise ValueError(f"{DAMPE_RACE_FLOW}: {DAMPE_RESULT_SWITCH} case {DAMPE_FIRST_RACE_CASE} is not {DAMPE_TIMER_CHECK}")
    if DAMPE_SECOND_RACE_CASE not in result_cases or DAMPE_RUPEE_FROM_CASE not in result_cases:
        raise ValueError(f"{DAMPE_RACE_FLOW}: {DAMPE_RESULT_SWITCH} has no second or later race case")

    heart_case = _switch_cases(by_name, DAMPE_HEART_RESULT_SWITCH).get(DAMPE_HEART_RESULT_CASE)
    if heart_case is None or heart_case.v is not by_name[DAMPE_HEART_RESULT_TIMER]:
        raise ValueError(
            f"{DAMPE_RACE_FLOW}: {DAMPE_HEART_RESULT_SWITCH} case {DAMPE_HEART_RESULT_CASE} is not {DAMPE_HEART_RESULT_TIMER}"
        )

    game_data = game_data_actor(chart)
    _, set_action = _find_or_create_action(chart, GAME_DATA_ACTOR, _SET_ENUM_ACTION)
    set_node = ActionEvent()
    set_node.actor = make_rindex(game_data)
    set_node.actor_action = make_rindex(set_action)
    set_node.params = Container()
    set_node.params.data.update({"Index": -1, "GameDataName": _BOX_STATE, "Value": _RUPEE_BOX_STATE})
    set_node.nxt = make_index(by_name[DAMPE_RUPEE_TALK])
    setter = Event()
    setter.name = DAMPE_RUPEE_SETTER
    setter.data = set_node
    chart.events.append(setter)

    result_cases[DAMPE_FIRST_RACE_CASE].v = by_name[DAMPE_HOOKSHOT_TALK]
    result_cases[DAMPE_SECOND_RACE_CASE].v = timer
    for key in result_cases:
        if key >= DAMPE_RUPEE_FROM_CASE:
            result_cases[key].v = setter
    heart_case.v = by_name[DAMPE_HEART_RESULT_TALK]

    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()