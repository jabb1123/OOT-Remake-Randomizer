"""Event-flow fixes for chests whose opening triggers a hardcoded cutscene.

The Kokiri Forest sword chest is opened through the `Get_StoneOfForest_GetSword` event
(Get_StoneOfForest.bfevfl, entry point `GetSword`): the normal treasure-box demo runs first
(which gives whatever the chest holds), then the `Dm_Kokiri_0063` demo creates and equips a
Kokiri Sword on Link regardless of the chest contents. When the sword is moved elsewhere,
that second transition is unlinked so the chest only gives its real item.
"""

from __future__ import annotations

from .cutscene_skips import unlink_transition

SWORD_EVENT_FLOW = "Get_StoneOfForest.bfevfl.zs"
SWORD_ENTRY_POINT = "GetSword"
SWORD_DEMO_EVENT = "Dm_Kokiri_0063"
SWORD_VANILLA_ITEM = "Item_Sword_Kokiri"


def skip_sword_demo(data: bytes) -> bytes:
    """Unlink the Dm_Kokiri_0063 transition from the GetSword entry point of a BFEVFL."""
    return unlink_transition(data, SWORD_ENTRY_POINT, SWORD_DEMO_EVENT)
