"""Tests for progressive copies at NPC and event grant slots (progressive_npc)."""

import io
import unittest
from collections import Counter
from pathlib import Path

from evfl import EventFlow
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, Event, SubFlowEvent, SwitchEvent
from evfl.flowchart import Flowchart
from evfl.util import make_index

from oot_randomizer import progressive, progressive_npc as pn
from oot_randomizer.engine import load_default_slots
from oot_randomizer.event_items import EVENT_SLOTS, event_location_name
from oot_randomizer.heart_pickups import HEART_LOCATIONS
from oot_randomizer.npc_grants import NPC_SLOTS, fix_progressive_branches, patch_npc_grants
from oot_randomizer.planner import PlanOptions, plan_seed
from oot_randomizer.progressive_chests import params_of
from oot_randomizer.shop_slots import SHOP_LOCATIONS
from oot_randomizer.skulltula_rewards import SKULL_LOCATIONS
from oot_randomizer.songs import SONG_SLOTS, song_location_name
from oot_randomizer.world_logic import DEFAULT_WORLD_PATH, load_world

REPO = Path(__file__).resolve().parents[1]
NUP = REPO.parent / "The Legend of Zelda Ocarina of Time + U2" / "The Legend of Zelda Ocarina of Time   U2.0.0.nup"
ZSDIC = REPO / "ZsDic.pack"

HAND_OVER = "NpcCommon_HandOver_NpcToPlayer_NoDisplay"
DISPLAY_GET = "DisplayGetByActorName"

EXPECTED_NPC_SCOPE = {
    "MiniGame_HitTarget: Item_BulletBag_Large (npc item)",
    "MiniGame_HitTarget: Item_Quiver_Medium (npc item)",
    "Npc_Goron_006_Child: Item_BombBag_Medium (npc item)",
    "MiniGame_BombchuBowling: Item_BombBag_Large (npc item)",
    "MiniGame_Fishing: Item_Scale_Gold (npc item)",
    "MiniGame_Diving: Item_Scale_Silver (npc item)",
    "Minigame_HorsebackArchery: Item_Quiver_Large (npc item)",
    "LostWood_ScrubForestStageElder_SkullMaskFirst: Item_StickBag_Medium (npc item)",
    "LostWood_ScrubForestStageElder_TrueMaskFirst: Item_NutBag_Medium (npc item)",
    "Enemy_Scrub_Business_Common: Item_StickBag_Large (npc item)",
    "Enemy_Scrub_Business_Common: Item_NutBag_Large (npc item)",
    "Dm_LostWood_0040: Item_BulletBag_Medium (npc item)",
    "Dm_Goron_0030: Item_Gauntlet_Goron (npc item)",
}
EXPECTED_EVENT_SCOPE = {
    event_location_name("Dm_Kokiri_0155.bfevfl.zs"),
    event_location_name("Dm_MelodyGet_Time.bfevfl.zs"),
}


def _empty_flow() -> EventFlow:
    flow = EventFlow()
    flow.name = "Synthetic"
    flow.flowchart = Flowchart()
    flow.flowchart.name = "Synthetic"
    return flow


def _synthetic_grant_flow() -> EventFlow:
    """A flow whose only event is a hand-over of Item_Scale_Silver, reached from one entry point."""
    flow = _empty_flow()
    grant = Event()
    grant.name = "Grant"
    sub = SubFlowEvent()
    sub.res_flowchart_name = "NpcCommon"
    sub.entry_point_name = HAND_OVER
    sub.params = params_of({"ReveiveItem": "Item_Scale_Silver", "NpcActorName": "Npc"})
    grant.data = sub
    flow.flowchart.events.append(grant)
    entry = EntryPoint("Main")
    entry.main_event = make_index(grant)
    flow.flowchart.entry_points.append(entry)
    return flow


def _reload(flow: EventFlow) -> EventFlow:
    out = io.BytesIO()
    flow.write(out)
    again = EventFlow()
    again.read(out.getvalue())
    return again


def _by_name(flow: EventFlow) -> dict:
    return {e.name: e for e in flow.flowchart.events}


def _chain_gives(root: Event, entry: str) -> list[Event]:
    """The grant events of `entry` that a chain reaches from `root`.

    Follows switch cases, and the single successor of other nodes (a pouch add that Slingshot bags
    put in front of a give), but not past a grant.
    """
    out, seen, stack = [], set(), [root]
    while stack:
        ev = stack.pop()
        if id(ev) in seen:
            continue
        seen.add(id(ev))
        if isinstance(ev.data, SubFlowEvent):
            if ev.data.entry_point_name == entry:
                out.append(ev)
        elif isinstance(ev.data, SwitchEvent):
            stack.extend(c.v for c in ev.data.cases.values() if c.v is not None)
        elif getattr(ev.data, "nxt", None) is not None and ev.data.nxt.v is not None:
            stack.append(ev.data.nxt.v)
    return out


def _chain_leaves(root: Event) -> list[Event]:
    """The non-question nodes of a chain (its gives), following switch cases."""
    out, seen, stack = [], set(), [root]
    while stack:
        ev = stack.pop()
        if id(ev) in seen:
            continue
        seen.add(id(ev))
        if isinstance(ev.data, SwitchEvent):
            stack.extend(c.v for c in ev.data.cases.values() if c.v is not None)
        else:
            out.append(ev)
    return out


def _pouch_tiers(root: Event) -> list[str] | None:
    """The tiers that a chain's leaves add to the pouch, or None when a leaf is not a pouch add."""
    leaves = _chain_leaves(root)
    if not all(isinstance(g.data, ActionEvent) and g.data.params is not None and "Actor" in g.data.params.data
               for g in leaves):
        return None
    return sorted(g.data.params.data["Actor"] for g in leaves)


def _item_of(ev: Event) -> str:
    params = ev.data.params.data
    return params["ReveiveItem"] if "ReveiveItem" in params else params["ActorName"]


def _entry_of(flow: EventFlow, event_name: str) -> str:
    return _by_name(flow)[event_name].data.entry_point_name


class ScopeTests(unittest.TestCase):
    def test_in_scope_slots_are_exactly_the_family_grants_outside_the_fairies(self):
        self.assertEqual(pn.progressive_locations(), frozenset(EXPECTED_NPC_SCOPE | EXPECTED_EVENT_SCOPE))

    def test_shop_skull_heart_and_song_locations_are_never_in_scope(self):
        scope = pn.progressive_locations()
        self.assertFalse(scope & set(SKULL_LOCATIONS))
        self.assertFalse(scope & set(SHOP_LOCATIONS))
        self.assertFalse(scope & set(HEART_LOCATIONS))
        self.assertFalse(scope & {song_location_name(f) for f in SONG_SLOTS})

    def test_fairy_and_biggoron_grants_stay_out(self):
        scope = pn.progressive_locations()
        for loc, slot in NPC_SLOTS.items():
            if slot.item in ("Item_FairyBless_MP", "Item_FairyBless_MPDouble", "Item_Sword_Biggoron"):
                self.assertNotIn(loc, scope, loc)

    def test_every_in_scope_site_is_a_tier_of_a_family(self):
        event_items = {event_location_name(f): i for f, i in EVENT_SLOTS.items()}
        for loc in pn.progressive_locations():
            item = NPC_SLOTS[loc].item if loc in NPC_SLOTS else event_items[loc]
            with self.subTest(location=loc):
                self.assertIsNotNone(progressive.family_of_tier(item))


class SyntheticChainTests(unittest.TestCase):
    def test_grant_becomes_a_pouch_chain_with_one_give_per_tier(self):
        flow = _synthetic_grant_flow()
        grant = _by_name(flow)["Grant"]
        pn.wrap_grant(flow, grant, "ReveiveItem", progressive.family("Scale"))
        self.assertIsInstance(grant.data, SwitchEvent)
        self.assertEqual(grant.data.params.data, {"ActorName": "Item_Scale_Silver"})
        self.assertEqual(grant.data.actor.v.identifier.name, "GameDataActor")
        self.assertEqual(grant.data.actor_query.v.v, "EventQueryCheckIsGet")
        # Owned Silver (case 0) gives Gold; not owned (case 1) gives Silver.
        self.assertEqual(grant.data.cases[0].v.name, "Grant_OOTREM_Scale_Give1")
        self.assertEqual(grant.data.cases[1].v.name, "Grant_OOTREM_Scale_Give0")
        gives = [e for e in flow.flowchart.events if "_Give" in e.name]
        self.assertEqual(sorted(_item_of(e) for e in gives), ["Item_Scale_Gold", "Item_Scale_Silver"])
        for ev in gives:
            self.assertEqual(ev.data.entry_point_name, HAND_OVER)
            self.assertEqual(ev.data.params.data["NpcActorName"], "Npc")
            self.assertIsNone(ev.data.nxt.v)

    def test_entry_point_enters_the_chain_and_the_flow_round_trips(self):
        flow = _synthetic_grant_flow()
        pn.wrap_grant(flow, _by_name(flow)["Grant"], "ReveiveItem", progressive.family("Scale"))
        again = _reload(flow)
        root = next(e for e in again.flowchart.entry_points if e.name == "Main").main_event.v
        self.assertIsInstance(root.data, SwitchEvent)
        self.assertEqual(sorted(_item_of(g) for g in _chain_gives(root, HAND_OVER)),
                         ["Item_Scale_Gold", "Item_Scale_Silver"])

    def test_every_give_keeps_the_successor_of_the_grant(self):
        flow = _synthetic_grant_flow()
        end = Event()
        end.name = "End"
        end.data = SubFlowEvent()
        end.data.entry_point_name = "Ending"
        flow.flowchart.events.append(end)
        grant = _by_name(flow)["Grant"]
        grant.data.nxt = make_index(end)
        pn.wrap_grant(flow, grant, "ReveiveItem", progressive.family("Scale"))
        gives = [e for e in flow.flowchart.events if "_Give" in e.name]
        self.assertTrue(all(g.data.nxt.v is end for g in gives))

    def test_a_grant_without_its_parameter_is_refused(self):
        flow = _synthetic_grant_flow()
        with self.assertRaises(pn.ProgressiveNpcError):
            pn.wrap_grant(flow, _by_name(flow)["Grant"], "ActorName", progressive.family("Scale"))


@unittest.skipUnless(NUP.exists() and ZSDIC.exists(), "retail NUP or ZsDic.pack not present")
class NupGrantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from oot_randomizer.nup_chest_patcher import NupChestPatcher

        cls.patcher = NupChestPatcher(NUP, ZSDIC.read_bytes())

    def _read(self, name: str) -> bytes:
        return self.patcher.read_file(name)

    def test_every_in_scope_npc_site_wraps_into_a_chain_of_its_family(self):
        for loc in sorted(EXPECTED_NPC_SCOPE):
            slot = NPC_SLOTS[loc]
            fam = progressive.family_of_tier(slot.item)
            with self.subTest(location=loc):
                raw = self._read(slot.flow)
                vanilla = EventFlow()
                vanilla.read(raw)
                grants = [(e, g) for e, p, k, g in pn._grant_events(vanilla) if p[k] == slot.item]
                self.assertTrue(grants)
                out = pn.patch_npc_flow(raw, slot.flow, {(slot.group, slot.item): fam.copy})
                patched = EventFlow()
                patched.read(out)
                events = _by_name(patched)
                for vanilla_event, entry in grants:
                    root = events[vanilla_event.name]
                    self.assertIsInstance(root.data, SwitchEvent)
                    self.assertEqual(sorted(_item_of(g) for g in _chain_gives(root, entry)), sorted(fam.tiers))

    def test_wrapped_gives_keep_the_successor_of_their_grant(self):
        cases = {
            "Dm_LostWood_0040: Item_BulletBag_Medium (npc item)": ("Event30", "Event106"),
            "Dm_Goron_0030: Item_Gauntlet_Goron (npc item)": ("Event127", None),
            "LostWood_ScrubForestStageElder_TrueMaskFirst: Item_NutBag_Medium (npc item)": ("Event2", "Event25"),
        }
        for loc, (grant, expected_next) in cases.items():
            slot = NPC_SLOTS[loc]
            with self.subTest(location=loc):
                raw = self._read(slot.flow)
                vanilla = EventFlow()
                vanilla.read(raw)
                entry = _entry_of(vanilla, grant)
                out = pn.patch_npc_flow(raw, slot.flow, {(slot.group, slot.item): progressive.family_of_tier(slot.item).copy})
                flow = EventFlow()
                flow.read(out)
                gives = _chain_gives(_by_name(flow)[grant], entry)
                nexts = {g.data.nxt.v.name if g.data.nxt.v is not None else None for g in gives}
                self.assertEqual(nexts, {expected_next})

    def test_bow_quiver_site_gives_the_bow_and_quiver_tiers(self):
        slot = NPC_SLOTS["MiniGame_HitTarget: Item_Quiver_Medium (npc item)"]
        out = pn.patch_npc_flow(self._read(slot.flow), slot.flow, {(None, slot.item): "Progressive Bow"})
        flow = EventFlow()
        flow.read(out)
        root = _by_name(flow)["Event381"]
        self.assertIsInstance(root.data, SwitchEvent)
        self.assertEqual(root.data.params.data, {"ActorName": "Weapon_Range_Bow"})
        self.assertEqual(sorted(_item_of(g) for g in _chain_gives(root, HAND_OVER)),
                         sorted(progressive.family("Bow").tiers))

    def test_the_lost_woods_bag_switch_reaches_the_wrapped_grant(self):
        slot = NPC_SLOTS["Dm_LostWood_0040: Item_BulletBag_Medium (npc item)"]
        out = pn.patch_npc_flow(self._read(slot.flow), slot.flow, {(None, slot.item): "Progressive Slingshot"})
        flow = EventFlow()
        flow.read(out)
        events = _by_name(flow)
        self.assertIsInstance(events["Event30"].data, SwitchEvent)
        self.assertEqual({c.v.name for c in events["Event83"].data.cases.values()}, {"Event30"})

    def test_slingshot_tier_gets_the_small_bag_before_each_give(self):
        slot = NPC_SLOTS["Dm_LostWood_0040: Item_BulletBag_Medium (npc item)"]
        out = pn.patch_npc_flow(self._read(slot.flow), slot.flow, {(None, slot.item): "Progressive Slingshot"})
        flow = EventFlow()
        flow.read(out)
        events = _by_name(flow)
        gives = [e for e in flow.flowchart.events
                 if isinstance(e.data, SubFlowEvent) and e.data.params is not None
                 and e.data.params.data.get("ActorName") == "Item_Range_SlingShot"]
        self.assertTrue(gives)
        for give in gives:
            self.assertIn(f"AutoEvent_Add_Item_BulletBag_Small_before_{give.name}", events)

    def test_a_plain_repoint_gives_the_same_bytes_as_the_separate_steps(self):
        slot = NPC_SLOTS["MiniGame_HitTarget: Item_Quiver_Medium (npc item)"]
        raw = self._read(slot.flow)
        combined = pn.patch_npc_flow(raw, slot.flow, {(None, slot.item): "Item_Quiver_Large"})
        separate = fix_progressive_branches(patch_npc_grants(raw, {(None, slot.item): "Item_Quiver_Large"}), slot.flow)
        self.assertEqual(combined, separate)

    def test_a_flow_that_does_not_grant_the_slot_is_refused(self):
        slot = NPC_SLOTS["Dm_LostWood_0040: Item_BulletBag_Medium (npc item)"]
        with self.assertRaises(ValueError):
            pn.patch_npc_flow(self._read(slot.flow), slot.flow, {(None, "Item_Quiver_Large"): "Progressive Bow"})

    def test_ocarina_event_sites_wrap_into_the_two_tiers(self):
        for flow_file, vanilla in [("Dm_Kokiri_0155.bfevfl.zs", "Item_Ocarina_Fairy"),
                                   ("Dm_MelodyGet_Time.bfevfl.zs", "Item_Ocarina_Time")]:
            with self.subTest(flow=flow_file):
                out = pn.patch_event_flow(self._read(flow_file), vanilla, "Progressive Ocarina")
                flow = EventFlow()
                flow.read(out)
                tiers = sorted(progressive.family("Ocarina").tiers)
                displays = [e for e in flow.flowchart.events if isinstance(e.data, SwitchEvent)
                            and sorted(_item_of(g) for g in _chain_gives(e, DISPLAY_GET)) == tiers]
                pouch_adds = [e for e in flow.flowchart.events if isinstance(e.data, SwitchEvent)
                              and _pouch_tiers(e) == tiers]
                self.assertEqual(len(displays), 1)
                self.assertEqual(len(pouch_adds), 1)

    def test_an_event_flow_without_the_item_is_refused(self):
        with self.assertRaises(pn.ProgressiveNpcError):
            pn.patch_event_flow(self._read("Dm_Kokiri_0155.bfevfl.zs"), "Item_Ocarina_Time", "Progressive Ocarina")


class PlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.slots = load_default_slots()
        cls.scope = pn.progressive_locations()

    def _plan(self, seed, enabled, world=None):
        options = PlanOptions(progressive_items=enabled,
                              progressive_npc=self.scope if enabled else frozenset())
        return plan_seed(seed, self.slots, world, options)

    def test_copies_land_only_in_chests_and_in_scope_npc_or_event_slots(self):
        for seed in range(1, 7):
            plan = self._plan(seed, True)
            for loc, item in plan.npc_assignments.items():
                if progressive.is_copy(item):
                    self.assertIn(loc, self.scope)
            for flow, item in plan.event_assignments.items():
                if progressive.is_copy(item):
                    self.assertIn(event_location_name(flow), self.scope)
            self.assertFalse(any(progressive.is_copy(i) for i in plan.skull_assignments.values()))
            self.assertFalse(any(progressive.is_copy(i) for _, i, _ in plan.shop_assignments))
            self.assertFalse(any(progressive.is_copy(i) for _, i in plan.heart_assignments))
            self.assertFalse(any(progressive.is_copy(i) for i in plan.song_assignments.values()))

    def test_npc_and_event_slots_receive_copies_across_seeds(self):
        placed = 0
        for seed in range(1, 9):
            plan = self._plan(seed, True)
            placed += sum(progressive.is_copy(i) for i in plan.npc_assignments.values())
            placed += sum(progressive.is_copy(i) for i in plan.event_assignments.values())
        self.assertGreater(placed, 0)

    def test_every_copy_places_and_nothing_is_unreachable_with_the_shipped_logic(self):
        world = load_world(DEFAULT_WORLD_PATH)
        for seed in (1, 2):
            with self.subTest(seed=seed):
                plan = self._plan(seed, True, world=world)
                items = [i for _, i in plan.chest_assignments]
                items += plan.npc_assignments.values()
                items += plan.event_assignments.values()
                copies = Counter(i for i in items if progressive.is_copy(i))
                self.assertEqual(sum(copies.values()), sum(len(f.tiers) for f in progressive.FAMILIES))
                self.assertEqual(plan.unreachable, [])

    def test_flag_off_ignores_the_npc_scope(self):
        for seed in (1, 2, 3):
            off = plan_seed(seed, self.slots, None, PlanOptions(progressive_items=False))
            scoped = plan_seed(seed, self.slots, None,
                               PlanOptions(progressive_items=False, progressive_npc=self.scope))
            self.assertEqual(off.npc_assignments, scoped.npc_assignments)
            self.assertEqual(off.event_assignments, scoped.event_assignments)
            self.assertEqual([(s.name, i) for s, i in off.chest_assignments],
                             [(s.name, i) for s, i in scoped.chest_assignments])


if __name__ == "__main__":
    unittest.main()
