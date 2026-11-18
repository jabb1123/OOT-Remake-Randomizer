"""Castle entry changes for the Kaepora quest log.

The first Kaepora talk in Goto_HyruleCastle also sets up the quest log: it sets the challenge menu flag,
adds the Amiibo pouch item, progresses the Goto_HyruleCastle challenge to Step02, and shows its progress UI.
Routes that start at the castle never run Goto_HyruleCastle, so `add_goto_quest_progress_to_castle_entry`
runs those steps in the castle entry flow, right after the entry's first action.
"""

from __future__ import annotations

import io

from evfl.event import ForkEvent

from .game_flags import insert_action_before

CASTLE_ENTRY_FLOW = "Dm_HrlCastle_0000.bfevfl.zs"
CASTLE_ENTRY_POINT = "EntryPoint0"

_GAME_DATA_ACTOR = "GameDataActor"
_POUCH_ACTOR = "PouchSystemActor"
_CHALLENGE_ACTOR = "ChallengeSystemActor"
# Goto_HyruleCastle's quest setup on the first Kaepora talk, in order (Event6, Event205, Event14, Event9).
# The Step02 params match that event, including IsIgnoreChallengeProgressUI.
_KAEPORA_QUEST_STEPS = [
    (_GAME_DATA_ACTOR, "EventTriggerSetGameDataBool", {
            "Index": -1, "GameDataName": "HyruleField_ArriveEntrance", "Value": True,
    }),
    (_GAME_DATA_ACTOR, "EventTriggerSetGameDataBool", {
        "Index": -1, "GameDataName": "UI_IsFinishChallengeMenuOpenEvent", "Value": True,
    }),
    (_POUCH_ACTOR, "EventTriggerAddOrRemovePouchContent", {
        "Actor": "Pouch_Amiibo", "Num": 1, "IsSetMessageTargetActorName": False,
        "IsEquipDIrect": False, "IsGetEvent": False,
    }),
    (_CHALLENGE_ACTOR, "EventExecuteProgressChallengeStep", {
        "ChallengeName": "Goto_HyruleCastle", "StepName": "Step02",
        "IsIgnoreCompletedChallenge": False, "IsWaitEnd": True, "IsIgnoreChallengeProgressUI": True,
    }),
    (_CHALLENGE_ACTOR, "EventTriggerShowChallengeProgressUI", {
        "ChallengeName": "Goto_HyruleCastle", "IsFirstStep": True,
    }),
]

def add_goto_quest_progress_to_castle_entry(data: bytes) -> bytes:
    """Run Goto_HyruleCastle's quest setup in the castle entry flow, before the entry's parallel block.

    The steps go right after the entry's first action, so they run before the rest of the cutscene.
    """
    from evfl import EventFlow

    flow = EventFlow()
    flow.read(data)
    entries = [e for e in flow.flowchart.entry_points if e.name == CASTLE_ENTRY_POINT]
    if len(entries) != 1:
        raise ValueError(f"expected one {CASTLE_ENTRY_POINT} entry point, found {len(entries)}")
    parallel_fork = entries[0].main_event.v.data.nxt.v
    if not isinstance(parallel_fork.data, ForkEvent):
        raise ValueError("expected a fork after the castle entry's first action")

    target = parallel_fork
    for actor_name, action_name, params in reversed(_KAEPORA_QUEST_STEPS):
        target = insert_action_before(flow.flowchart, target, actor_name, action_name, params)

    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()
