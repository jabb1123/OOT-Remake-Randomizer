"""Per-slot sold-out state for the Kokiri Shop.

The native sold-out counter is shared by a whole shelf, so a randomized item bought from one
Kokiri slot cannot be tracked by it. DisplayShop.bfevfl is shared by every shop, so this patch
adds two gates that only apply while the Kokiri Shop session is open
(`KokiriForest_Shop_Talking` is set by Root_Buy and cleared by Buy_End):

* SelectItem_CheckAvailable: before the native buy check, a slot whose
  `KokiriForest_Shop_SoldOut_<index>` bool is set routes to the not-available branch.
* ShopItem_Buy_SecondMove: after a purchase, the selected slot's bool is set before the item
  is put in the pouch.

Only the Kokiri child shop NPC is covered. The adult flow is not extracted yet.

`add_shop_slingshot_bag` is applied to the same flow: a Slingshot bought from any shop also gets
the Small Bullet Bag, which the vanilla Slingshot pickup gives but a purchase does not.
"""

from __future__ import annotations

import io

from .game_flags import game_data_actor, pouch_add_action, redirect_references
from .gamedata_list import SHOP_SOLDOUT_NAMES
from .npc_grants import SLINGSHOT_BAG, SLINGSHOT_ITEM

DISPLAY_SHOP_FLOW = "DisplayShop.bfevfl.zs"
KOKIRI_SESSION_BOOL = "KokiriForest_Shop_Talking"

_SELECT_ENTRY = "SelectItem_CheckAvailable"
_SELECT_VANILLA = "Event318"
_NOT_AVAILABLE = "Event312"
_BUY_ENTRY = "ShopItem_Buy_SecondMove"
_BUY_VANILLA = "Event268"

_GAME_DATA_ACTOR = "GameDataActor"
_EVENT_STARTER = "Npc_EventStarter"
_QUERY_BOOL = "EventQueryIsGameDataBool"
_SET_BOOL = "EventTriggerSetGameDataBool"
_QUERY_SLOT = "EventQueryCheckShopSelectItemName"
_SLOT_COUNT = len(SHOP_SOLDOUT_NAMES)


def _actor(flow, name: str):
    for actor in flow.flowchart.actors:
        if actor.identifier.name == name:
            return actor
    raise ValueError(f"actor {name} not found in DisplayShop flow")


def _entry_main_event(flow, entry_name: str):
    for entry in flow.flowchart.entry_points:
        if entry.name == entry_name:
            return entry
    raise ValueError(f"entry point {entry_name} not found in DisplayShop flow")


def _container(params: dict | None):
    from evfl.container import Container

    if not params:
        return None
    container = Container()
    container.data.update(params)
    return container


def _event(flow, name: str, data):
    from evfl.event import Event

    event = Event()
    event.name = name
    event.data = data
    flow.flowchart.events.append(event)
    return event


def _find_event(flow, name: str):
    for event in flow.flowchart.events:
        if event.name == name:
            return event
    raise ValueError(f"event {name} not found in DisplayShop flow")


def _action_event(flow, name: str, actor, action: str, params: dict, nxt):
    from evfl.event import ActionEvent
    from evfl.util import make_index, make_rindex

    data = ActionEvent()
    data.nxt = make_index(nxt)
    data.actor = make_rindex(actor)
    data.actor_action = make_rindex(_string_holder(actor.actions, action))
    data.params = _container(params)
    return _event(flow, name, data)


def _switch_event(flow, name: str, actor, query: str, cases: dict, params: dict | None):
    from evfl.event import SwitchEvent
    from evfl.util import make_rindex

    data = SwitchEvent()
    data.actor = make_rindex(actor)
    data.actor_query = make_rindex(_string_holder(actor.queries, query))
    data.params = _container(params)
    data.cases = {value: make_rindex(target) for value, target in cases.items()}
    return _event(flow, name, data)


def _string_holder(holders: list, name: str):
    for holder in holders:
        if holder.v == name:
            return holder
    raise ValueError(f"{name} is not an action or query of this actor")


def _bool_params(game_data_name: str) -> dict:
    return {"Index": -1, "GameDataName": game_data_name}


def _already_patched(flow) -> bool:
    main = _entry_main_event(flow, _SELECT_ENTRY).main_event.v
    data = main.data
    params = getattr(data, "params", None)
    return bool(params and params.data.get("GameDataName") == KOKIRI_SESSION_BOOL)


def _add_select_gate(flow) -> None:
    vanilla = _find_event(flow, _SELECT_VANILLA)
    not_available = _find_event(flow, _NOT_AVAILABLE)
    game_data = _actor(flow, _GAME_DATA_ACTOR)
    starter = _actor(flow, _EVENT_STARTER)

    checks = {}
    for index, bool_name in enumerate(SHOP_SOLDOUT_NAMES):
        checks[index] = _switch_event(
            flow, f"ShopSoldOut_Check{index}", game_data, _QUERY_BOOL,
            {0: vanilla, 1: not_available}, _bool_params(bool_name),
        )
    slot_switch = _switch_event(
        flow, "ShopSoldOut_SelectSlot", starter, _QUERY_SLOT,
        {**checks, _SLOT_COUNT: vanilla}, None,
    )
    session = _switch_event(
        flow, "ShopSoldOut_SelectSession", game_data, _QUERY_BOOL,
        {0: vanilla, 1: slot_switch}, _bool_params(KOKIRI_SESSION_BOOL),
    )
    _entry_main_event(flow, _SELECT_ENTRY).main_event.v = session


def _add_buy_mark(flow) -> None:
    vanilla = _find_event(flow, _BUY_VANILLA)
    game_data = _actor(flow, _GAME_DATA_ACTOR)
    starter = _actor(flow, _EVENT_STARTER)

    marks = {}
    for index, bool_name in enumerate(SHOP_SOLDOUT_NAMES):
        marks[index] = _action_event(
            flow, f"ShopSoldOut_Mark{index}", game_data, _SET_BOOL,
            {"Index": -1, "GameDataName": bool_name, "Value": True}, vanilla,
        )
    slot_switch = _switch_event(
        flow, "ShopSoldOut_MarkSlot", starter, _QUERY_SLOT,
        {**marks, _SLOT_COUNT: vanilla}, None,
    )
    session = _switch_event(
        flow, "ShopSoldOut_MarkSession", game_data, _QUERY_BOOL,
        {0: vanilla, 1: slot_switch}, _bool_params(KOKIRI_SESSION_BOOL),
    )
    _entry_main_event(flow, _BUY_ENTRY).main_event.v = session


def patch_kokiri_soldout(data: bytes) -> bytes:
    """Add the per-slot sold-out gate and mark to DisplayShop. Applying it twice is a no-op."""
    from evfl import EventFlow

    flow = EventFlow()
    flow.read(data)
    if _already_patched(flow):
        return data
    if _entry_main_event(flow, _SELECT_ENTRY).main_event.v.name != _SELECT_VANILLA:
        raise ValueError(f"{_SELECT_ENTRY} no longer starts at {_SELECT_VANILLA}")
    if _entry_main_event(flow, _BUY_ENTRY).main_event.v.name != _BUY_VANILLA:
        raise ValueError(f"{_BUY_ENTRY} no longer starts at {_BUY_VANILLA}")
    _add_select_gate(flow)
    _add_buy_mark(flow)
    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()


SHOP_PUT_IN_POUCH_ACTION = "EventTriggerShopItemPutInPouch"
SELECTED_ITEM_GAME_DATA = "Shop_SelectItemName"
_STRING_QUERY = "EventQueryIsGameDataString64"
_BAG_EVENT_PREFIX = "AutoEvent_ShopSlingshotBag_"


def add_shop_slingshot_bag(data: bytes) -> bytes:
    """Add the Small Bullet Bag before each shop purchase that can hand over a Slingshot.

    A purchase only puts the item's own pouch content in the pouch. Before every
    EventTriggerShopItemPutInPouch, a GameDataActor check on `Shop_SelectItemName` sends a
    Slingshot purchase through a silent bag add first. Applying it twice is a no-op.
    """
    from evfl import EventFlow
    from evfl.container import Container
    from evfl.event import ActionEvent, Event, SwitchEvent
    from evfl.util import make_index, make_rindex

    flow = EventFlow()
    flow.read(data)
    chart = flow.flowchart
    if any(event.name.startswith(_BAG_EVENT_PREFIX) for event in chart.events):
        return data
    purchases = [
        event for event in chart.events
        if isinstance(event.data, ActionEvent)
        and str(event.data.actor_action.v) == SHOP_PUT_IN_POUCH_ACTION
    ]
    if not purchases:
        raise ValueError(f"DisplayShop has no {SHOP_PUT_IN_POUCH_ACTION} action")

    game_data = game_data_actor(chart)
    query = next((q for q in game_data.queries if q.v == _STRING_QUERY), None)
    if query is None:
        raise ValueError(f"DisplayShop GameDataActor has no {_STRING_QUERY} query")
    pouch_actor, add_action = pouch_add_action(chart)

    for target in purchases:
        bag_params = Container()
        bag_params.data.update({
            "Num": 1,
            "IsEquipDIrect": False,
            "IsSetMessageTargetActorName": False,
            "Actor": SLINGSHOT_BAG,
            "IsGetEvent": False,
        })
        bag_node = ActionEvent()
        bag_node.actor = make_rindex(pouch_actor)
        bag_node.actor_action = make_rindex(add_action)
        bag_node.params = bag_params
        bag_node.nxt = make_index(target)
        bag = Event()
        bag.name = f"{_BAG_EVENT_PREFIX}Add_{target.name}"
        bag.data = bag_node

        check_params = Container()
        check_params.data.update({
            "GameDataName": SELECTED_ITEM_GAME_DATA,
            "Index": -1,
            "Value": SLINGSHOT_ITEM,
        })
        check_node = SwitchEvent()
        check_node.actor = make_rindex(game_data)
        check_node.actor_query = make_rindex(query)
        check_node.params = check_params
        check_node.cases = {0: make_rindex(target), 1: make_rindex(bag)}
        check = Event()
        check.name = f"{_BAG_EVENT_PREFIX}Check_{target.name}"
        check.data = check_node

        # Reroute before the new nodes are added, so their own edges to `target` stay put.
        redirect_references(chart, target, check)
        chart.events.extend([check, bag])

    out = io.BytesIO()
    flow.write(out)
    return out.getvalue()
