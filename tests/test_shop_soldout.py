import unittest
from pathlib import Path

from oot_randomizer.gamedata_list import SHOP_SOLDOUT_NAMES
from oot_randomizer.npc_grants import SLINGSHOT_BAG, SLINGSHOT_ITEM
from oot_randomizer.shop_soldout import (
    KOKIRI_SESSION_BOOL,
    add_shop_slingshot_bag,
    patch_kokiri_soldout,
)

RAW_FLOW = Path(
    r"C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405\files\raw\DisplayShop.bfevfl"
)


def _load(data: bytes):
    from evfl import EventFlow

    flow = EventFlow()
    flow.read(data)
    return flow


def _events(flow) -> dict:
    return {e.name: e.data for e in flow.flowchart.events}


def _entry(flow, name: str) -> str:
    for entry in flow.flowchart.entry_points:
        if entry.name == name:
            return entry.main_event.v.name
    raise AssertionError(f"no entry {name}")


@unittest.skipUnless(RAW_FLOW.exists(), "DisplayShop.bfevfl not available")
class KokiriSoldOutFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = RAW_FLOW.read_bytes()
        cls.patched = patch_kokiri_soldout(cls.raw)
        cls.flow = _load(cls.patched)
        cls.events = _events(cls.flow)

    def test_entries_route_through_session_gate(self):
        self.assertEqual(_entry(self.flow, "SelectItem_CheckAvailable"), "ShopSoldOut_SelectSession")
        self.assertEqual(_entry(self.flow, "ShopItem_Buy_SecondMove"), "ShopSoldOut_MarkSession")

    def test_session_gate_only_fires_for_kokiri_session(self):
        for name in ("ShopSoldOut_SelectSession", "ShopSoldOut_MarkSession"):
            data = self.events[name]
            self.assertEqual(data.params.data["GameDataName"], KOKIRI_SESSION_BOOL)
            self.assertEqual(data.cases[0].v.name, "Event318" if "Select" in name else "Event268")

    def test_select_gate_routes_sold_slots_to_not_available(self):
        slots = self.events["ShopSoldOut_SelectSlot"].cases
        for index, bool_name in enumerate(SHOP_SOLDOUT_NAMES):
            check = self.events[f"ShopSoldOut_Check{index}"]
            self.assertEqual(slots[index].v.name, f"ShopSoldOut_Check{index}")
            self.assertEqual(check.params.data["GameDataName"], bool_name)
            self.assertEqual(check.cases[0].v.name, "Event318")
            self.assertEqual(check.cases[1].v.name, "Event312")
        self.assertEqual(slots[8].v.name, "Event318")

    def test_buy_marks_set_the_selected_slot_bool(self):
        slots = self.events["ShopSoldOut_MarkSlot"].cases
        for index, bool_name in enumerate(SHOP_SOLDOUT_NAMES):
            mark = self.events[f"ShopSoldOut_Mark{index}"]
            self.assertEqual(slots[index].v.name, f"ShopSoldOut_Mark{index}")
            self.assertEqual(mark.params.data, {"Index": -1, "GameDataName": bool_name, "Value": True})
            self.assertEqual(mark.nxt.v.name, "Event268")
        self.assertEqual(slots[8].v.name, "Event268")

    def test_only_new_events_are_added(self):
        # 10 select-gate nodes and 10 buy-mark nodes (8 slots + slot switch + session switch each)
        self.assertEqual(len(self.flow.flowchart.events) - len(_load(self.raw).flowchart.events), 20)

    def test_applying_twice_is_a_no_op(self):
        self.assertEqual(patch_kokiri_soldout(self.patched), self.patched)

    def test_vanilla_flow_is_still_reachable(self):
        self.assertEqual(self.events["Event318"].actor.v.identifier.name, "Npc_EventStarter")
        self.assertEqual(self.events["Event268"].nxt.v.name, "Event219")


@unittest.skipUnless(RAW_FLOW.exists(), "DisplayShop.bfevfl not available")
class ShopSlingshotBagFlowTest(unittest.TestCase):
    CHECK = "AutoEvent_ShopSlingshotBag_Check_"
    ADD = "AutoEvent_ShopSlingshotBag_Add_"

    @classmethod
    def setUpClass(cls):
        cls.raw = RAW_FLOW.read_bytes()
        cls.patched = add_shop_slingshot_bag(cls.raw)
        cls.flow = _load(cls.patched)
        cls.events = _events(cls.flow)

    def test_each_purchase_is_gated_on_the_selected_slingshot(self):
        for target in ("Event268", "Event171"):
            check = self.events[self.CHECK + target]
            self.assertEqual(check.params.data, {
                "GameDataName": "Shop_SelectItemName", "Index": -1, "Value": SLINGSHOT_ITEM,
            })
            self.assertEqual(check.cases[0].v.name, target)
            self.assertEqual(check.cases[1].v.name, self.ADD + target)

    def test_bag_add_runs_before_the_purchase(self):
        for target in ("Event268", "Event171"):
            add = self.events[self.ADD + target]
            self.assertEqual(add.params.data["Actor"], SLINGSHOT_BAG)
            self.assertEqual(add.params.data["Num"], 1)
            self.assertEqual(add.nxt.v.name, target)

    def test_applying_twice_is_a_no_op(self):
        self.assertEqual(add_shop_slingshot_bag(self.patched), self.patched)

    def test_kokiri_sold_out_gate_is_rerouted_to_the_bag_gate(self):
        combined = add_shop_slingshot_bag(patch_kokiri_soldout(self.raw))
        events = _events(_load(combined))
        self.assertEqual(events["ShopSoldOut_MarkSession"].cases[0].v.name, self.CHECK + "Event268")
        self.assertEqual(events["ShopSoldOut_SelectSession"].cases[0].v.name, "Event318")


if __name__ == "__main__":
    unittest.main()
