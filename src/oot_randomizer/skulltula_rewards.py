"""Gold Skulltula (House of Skulltula) reward shuffle.

The father in Kakariko's House of Skulltula hands out every reward through one event flow,
GatheringTokenGold.bfevfl. Each reward of 10 to 50 tokens is a `TakenReward_Common_Event`
sub-flow call whose `TakenRewardActor` parameter names the item to give. It is followed by the
action that sets that reward's `GetRewardNN` flag, which is how each slot is identified.
The 100-token reward uses a separate rupee-only sub-flow and is never touched.
"""

from __future__ import annotations

import io

SKULL_FLOW = "GatheringTokenGold.bfevfl.zs"
TOKEN_ITEM = "Item_Token_Gold"
_REWARD_FLAG = "KakarikoVillage_GatheringTokenGold_GetReward{}"
_REWARD_SUBFLOW = "TakenReward_Common_Event"
_REWARD_PARAM = "TakenRewardActor"

# token count -> vanilla reward actor
SKULL_REWARDS: dict[int, str] = {
    10: "Item_Wallet_Medium",
    20: "Item_AgonyStone",
    30: "Item_Wallet_Large",
    40: "Item_BombchuBundle_Large",
    50: "Obj_Heart_Piece",
}


def skull_location_name(tokens: int) -> str:
    return f"House of Skulltula Reward {tokens}"


SKULL_LOCATIONS: dict[str, int] = {skull_location_name(n): n for n in SKULL_REWARDS}


def can_hand_over(item: str) -> bool:
    """Items an NPC can give through the get-item demo.

    Chest-only actors (TBox_*), dungeon-bound items and the scrub placeholder are excluded.
    """
    if item.startswith(("TBox_", "Tbox_", "Item_Dungeon_", "Item_Melody_")):
        return False
    return item != "Item_ScrubBusinessSeed"


def patch_skull_rewards(data: bytes, rewards: dict[int, str]) -> bytes:
    """Set the reward actor for each token count in `rewards` (counts 10-50 only)."""
    from evfl import EventFlow
    from evfl.event import ActionEvent, SubFlowEvent

    unknown = set(rewards) - set(SKULL_REWARDS)
    if unknown:
        raise ValueError(f"no skulltula reward slot for {sorted(unknown)}")
    flow = EventFlow()
    flow.read(data)
    found: set[int] = set()
    for event in flow.flowchart.events:
        body = event.data
        if not isinstance(body, SubFlowEvent) or body.entry_point_name != _REWARD_SUBFLOW:
            continue
        if not body.params or _REWARD_PARAM not in body.params.data:
            continue
        nxt = body.nxt.v
        flag = nxt.data.params.data.get("GameDataName") if nxt is not None and isinstance(nxt.data, ActionEvent) and nxt.data.params else None
        for tokens in SKULL_REWARDS:
            if flag == _REWARD_FLAG.format(tokens):
                found.add(tokens)
                if tokens in rewards:
                    body.params.data[_REWARD_PARAM] = rewards[tokens]
    missing = set(SKULL_REWARDS) - found
    if missing:
        raise ValueError(f"skulltula reward slots not found in event flow: {sorted(missing)}")
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()
