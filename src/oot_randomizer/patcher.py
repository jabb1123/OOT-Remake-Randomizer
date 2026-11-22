"""Patch record types and patch application logic.

PatchRecord describes a logical chest change: which scene file, which actor,
and what Drop__DropActor string to place. No numeric byte IDs are used —
the remake identifies items by actor string name.

RomPatcher applies records against an already-copied NUP using NupChestPatcher.
For files where byte offsets are not yet resolved it falls back to manifest-only mode.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .chest_events import SWORD_EVENT_FLOW, SWORD_VANILLA_ITEM, skip_sword_demo
from .cutscene_skips import INTRO_EVENT_FLOW, skip_intro_cutscene
from .starting_items import patch_intro_flow
from .kokiri_blocker import MIDO_BLOCKER_PATCHES
from .world_time import CASTLE_ENTRY_FLOW, add_goto_quest_progress_to_castle_entry
from .event_items import EVENT_SLOTS, patch_event_item
from .dampe_race import DAMPE_RACE_FLOW, patch_dampe_race_approach
from .storm_song_npc import STORM_NPC_FLOW, patch_storm_song_npc
from .sheik_medal_gate import ALLSAGE_FLOW, patch_sheik_medal_gate
from .medal_progress import (
    GET_IN_EVENT_FLOW,
    GET_POUCH_CONTENT_FLOW,
    add_medal_progress_after_pouch_adds,
    add_medal_progress_after_shop_purchase,
)
from .sage_escape_flow import ESCAPE_FLOW, patch_escape_sage_completes
from .npc_grants import (
    FAIRY_FLOWS,
    NPC_SLOTS,
    REROUTED_FLOWS,
    SCRUB_BIGGORON_FLOW,
    SLINGSHOT_ITEM,
    add_slingshot_bag,
    disable_scrub_biggoron_sale,
    fix_progressive_branches,
    patch_fairy_received,
    patch_npc_grants,
)
from .item_ids import resolve_actor_name
from .location_mapper import build_scene_file_index, load_summary_file
from .locations import OOTLocation
from .skulltula_rewards import SKULL_FLOW, SKULL_REWARDS, patch_skull_rewards
from .stone_gates import (
    POUCH_ADD_FLOWS,
    POUCH_ADD_SUBFLOW,
    STONE_CHECK_FLOW_FILE,
    STONE_GATE_FLOWS,
    STONE_SLOT_FLOWS,
    add_shop_stone_count_check,
    add_stone_count_check,
    add_stone_count_check_at_route_end,
    patch_stone_gates,
)
from .songs import OCARINA_LEARN_FLOW, SONG_SLOTS, patch_bfevfl_song, patch_bfevfl_songs


def _legacy_item_id(actor_name: str) -> int:
    """Return a stable 32-bit compatibility ID for an actor name.

    The modern patch pipeline identifies items by their BYML string actor names,
    but older manifests/tests still expect a numeric item id field. The value is
    derived from the actor name so it is deterministic and does not depend on the
    original N64 byte IDs.
    """
    digest = hashlib.sha256(actor_name.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], byteorder="big", signed=False)


@dataclass(frozen=True, slots=True)
class PatchRecord:
    location_name: str
    scene: str
    check_type: str
    check_index: int
    vanilla_item: str       # Drop__DropActor actor name before patching
    replacement_item: str   # Drop__DropActor actor name after patching
    byte_offset: int | None # resolved by BYML walker; None = manifest-only
    item_id: int = 0
    scene_file: str | None = None
    room_index: int | None = None
    chest_order: int | None = None  # position of the chest in the bcett scan order


def make_patch(
    location: OOTLocation,
    replacement_item: str,
    *,
    scene_file: str | None = None,
    room_index: int | None = None,
) -> PatchRecord:
    return PatchRecord(
        location_name=location.name,
        scene=location.scene,
        check_type=location.check_type,
        check_index=location.check_index,
        vanilla_item=resolve_actor_name(location.vanilla_item),
        replacement_item=replacement_item,
        byte_offset=None,
        item_id=_legacy_item_id(replacement_item),
        scene_file=scene_file,
        room_index=room_index,
    )


def _is_nup_container(rom_path: Path) -> bool:
    """True when `rom_path` opens as a NUP container (TOC and packages parse)."""
    try:
        from nup.read import NupReader
        NupReader(str(rom_path)).close()
    except Exception:
        return False
    return True


def sword_chest_moved(patches: list[PatchRecord]) -> bool:
    """True when the Kokiri Forest sword chest no longer holds the Kokiri Sword."""
    return any(
        p.scene == "KokiriForest"
        and p.vanilla_item == SWORD_VANILLA_ITEM
        and p.replacement_item != SWORD_VANILLA_ITEM
        for p in patches
    )


def resolve_scene_files(scene: str) -> list[str]:
    """Resolve a logical scene key to the real filenames present in the generated chest summary."""
    project_root = Path(__file__).resolve().parents[2]
    summary_path = project_root / "chest_locations_summary.json"
    if summary_path.exists():
        summary = load_summary_file(summary_path)
        scene_index = build_scene_file_index(summary)
        files = scene_index.get(scene, [])
        if files:
            return [PurePosixPath(path).name for path in files]
    return [f"{scene}_Static.bcett.byml.zs"]


def build_scene_patch_map(patches: list[PatchRecord]) -> dict[str, list[dict[str, object]]]:
    """Group patch records by scene file and exact chest identity: room + logical chest index."""
    grouped: dict[str, list[dict[str, object]]] = {}
    for patch in patches:
        scene_files = [patch.scene_file] if patch.scene_file else resolve_scene_files(patch.scene)
        for scene_file in scene_files:
            normalized_scene_file = PurePosixPath(scene_file).name if scene_file else None
            if normalized_scene_file is None:
                continue
            grouped.setdefault(normalized_scene_file, []).append(
                {
                    "location_name": patch.location_name,
                    "scene": patch.scene,
                    "check_index": patch.check_index,
                    "room_index": patch.room_index,
                    "chest_order": patch.chest_order,
                    "vanilla_item": patch.vanilla_item,
                    "replacement_item": patch.replacement_item,
                }
            )
    return grouped


class RomPatcher:
    """Applies PatchRecords to a copied NUP via NupChestPatcher.

    Falls back to manifest-only mode when byte_offset is None on any record.
    """

    @staticmethod
    def _resolve_zsdic_path(rom_path: Path) -> Path | None:
        candidates = [
            rom_path.with_name("ZsDic.pack"),
            Path(__file__).resolve().parents[2] / "ZsDic.pack",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def apply(
        self,
        rom_path: Path,
        patches: list[PatchRecord],
        song_assignments: dict[str, str] | None = None,
        skull_assignments: dict[int, str] | None = None,
        shop_assignments: list[tuple[str, str, int]] | None = None,
        event_assignments: dict[str, str] | None = None,
        npc_assignments: dict[str, str] | None = None,
        skip_intro: bool = False,
        heart_assignments: list[tuple[str, str]] | None = None,
    ) -> "PatchResult":
        """Apply chest, song, skull-reward, event-item, NPC-grant, shop and heart changes to a NUP copy, in place.

        Shop items (shop_assignments: [(slot name, item, price)]) and heart pickups
        (heart_assignments: [(heart slot, item)]) are applied first: adding their packs grows
        the TOC and moves the package meta blocks, which is only proven on an otherwise
        untouched NUP (emulator test), and it fails before writing anything when the TOC has
        no room for both. The replace_file based patches that follow re-read the TOC for
        every write, so they work on the grown NUP. Shop and heart errors raise ShopError; the
        other patches keep falling back to manifest-only mode unless new packs were already
        written, in which case their error is raised.
        """
        if not rom_path.exists():
            return PatchResult(
                applied=0,
                skipped=len(patches),
                mode="manifest-only",
                unresolved_locations=[p.location_name for p in patches],
            )

        from .gamedata_list import GAME_DATA_LIST, patch_gamedata_list
        from .nup_chest_patcher import NupChestPatcher, NupPatchError
        from .shop_soldout import DISPLAY_SHOP_FLOW, add_shop_slingshot_bag, patch_kokiri_soldout
        # Group patches by the real scene files and exact chest identity.
        # byte_offset is not required here: the NUP scan resolves the real BYML offsets
        # for each target room/chest when a valid NUP + ZsDic are present.
        by_scene = build_scene_patch_map(patches)

        # Load ZsDic (expected alongside the NUP, but may also live in the project root).
        zsdic_path = self._resolve_zsdic_path(rom_path)
        if zsdic_path is None:
            return PatchResult(
                applied=0,
                skipped=len(patches),
                mode="manifest-only",
                unresolved_locations=["ZsDic.pack not found beside NUP or project root"],
            )

        zsdic = zsdic_path.read_bytes()
        shop_actors: list[str] = []
        heart_actors: list[str] = []
        if shop_assignments or heart_assignments:
            from .heart_pickups import apply_heart_pickups, heart_pack_names
            from .shop_slots import apply_shop_slots, check_toc_names, shop_items_for
            from .shops import shop_actor_name
            # Unknown slots, unsellable items and bad heart items raise ShopError before any write.
            shop_names = [shop_actor_name(item) for item, _, _ in shop_items_for(shop_assignments or [])]
            heart_names = heart_pack_names(heart_assignments or [])
            if _is_nup_container(rom_path):
                check_toc_names(rom_path, shop_names + heart_names)
                if shop_assignments:
                    shop_result = apply_shop_slots(rom_path, zsdic, shop_assignments)
                    shop_actors = [a.name for a in shop_result.actors]
                if heart_assignments:
                    heart_result = apply_heart_pickups(rom_path, zsdic, heart_assignments)
                    heart_actors = [a.name for a in heart_result.actors]

        patcher = NupChestPatcher(rom_path, zsdic)
        applied = len(shop_actors) + len(heart_actors)
        try:
            for scene_file, scene_patches in by_scene.items():
                try:
                    if not scene_patches:
                        continue
                    swap_map: dict[str, str] = {
                        str(p["vanilla_item"]): str(p["replacement_item"]) for p in scene_patches
                    }
                    result = patcher.patch_scene(
                        scene_file,
                        swap_map,
                        target_replacements=scene_patches,
                    )
                    applied += result.chests_patched
                except NupPatchError:
                    pass
            if sword_chest_moved(patches):
                patcher.replace_file(SWORD_EVENT_FLOW, skip_sword_demo)
                applied += 1
            # One transform for the intro: replace_file re-reads the NUP, so a second call on the
            # same file would drop the first edit.
            try:
                patcher.replace_file(
                    INTRO_EVENT_FLOW,
                    lambda data, skip=skip_intro: patch_intro_flow(data, skip),
                )
                applied += 1
            except NupPatchError:
                pass  # flow absent from this NUP (e.g. test fixtures); the retail NUP always has it
            for blocker_flow, blocker_transform in MIDO_BLOCKER_PATCHES:
                try:
                    patcher.replace_file(blocker_flow, blocker_transform)
                    applied += 1
                except NupPatchError:
                    pass  # flow absent from this NUP (e.g. test fixtures); the retail NUP always has it
            try:
                patcher.replace_file(CASTLE_ENTRY_FLOW, add_goto_quest_progress_to_castle_entry)
                applied += 1
            except NupPatchError:
                pass  # flow absent from this NUP (e.g. test fixtures); the retail NUP always has it
            song_changes: dict[str, str] = {}
            for flow_file, new_song in (song_assignments or {}).items():
                old_song = SONG_SLOTS[flow_file]
                if new_song != old_song:
                    patcher.replace_file(
                        flow_file,
                        lambda data, o=old_song, n=new_song: patch_bfevfl_song(data, o, n),
                    )
                    song_changes[old_song] = new_song
                    applied += 1
            if song_changes:
                # The learning branch of the Ocarina flow grants each vanilla song itself, in
                # addition to the per-song flow above. Repoint those grants to the randomized
                # song so the player receives exactly one song per location.
                patcher.replace_file(
                    OCARINA_LEARN_FLOW,
                    lambda data: patch_bfevfl_songs(data, song_changes),
                )
                applied += 1
            changed_skulls = {
                n: item for n, item in (skull_assignments or {}).items() if item != SKULL_REWARDS[n]
            }
            if changed_skulls:
                patcher.replace_file(SKULL_FLOW, lambda data: patch_skull_rewards(data, changed_skulls))
                applied += 1
            for flow_file, new_item in (event_assignments or {}).items():
                old_item = EVENT_SLOTS[flow_file]
                if new_item != old_item:
                    patcher.replace_file(
                        flow_file,
                        lambda data, o=old_item, n=new_item: patch_event_item(data, o, n),
                    )
                    applied += 1
            npc_changes: dict[str, dict[tuple[str | None, str], str]] = {}
            for loc, new_item in (npc_assignments or {}).items():
                slot = NPC_SLOTS[loc]
                if new_item != slot.item:
                    npc_changes.setdefault(slot.flow, {})[(slot.group, slot.item)] = new_item
            for flow_file, changes in npc_changes.items():
                patcher.replace_file(flow_file, lambda data, c=changes: patch_npc_grants(data, c))
                applied += 1
            fairy_randomized = False
            for fairy in FAIRY_FLOWS:
                if fairy.flow in npc_changes:
                    # The fairy's "already received" check must follow the randomized grant, not the vanilla item.
                    patcher.replace_file(fairy.flow, lambda data, f=fairy: patch_fairy_received(data, f))
                    applied += 1
                    fairy_randomized = True
            if npc_assignments:
                # The Biggoron Sword is only obtainable from its randomized location, so the scrub's sale is removed.
                patcher.replace_file(SCRUB_BIGGORON_FLOW, disable_scrub_biggoron_sale)
                applied += 1
                # Progressive bullet bag games always pay out the one slot the logic keeps.
                for flow_file in REROUTED_FLOWS:
                    patcher.replace_file(flow_file, lambda data, f=flow_file: fix_progressive_branches(data, f))
                    applied += 1
                # The bag add goes last: it must sit in front of the grant after the switches are rewired.
                for flow_file, changes in npc_changes.items():
                    if SLINGSHOT_ITEM in changes.values():
                        patcher.replace_file(flow_file, add_slingshot_bag)
                        applied += 1
            # The Dampe race reward follows the race, so an owned hookshot must not skip its talk.
            try:
                patcher.replace_file(DAMPE_RACE_FLOW, patch_dampe_race_approach)
                applied += 1
            except NupPatchError:
                pass
            # The storm song slot is awarded once by this NPC, so the pouch must not skip that award.
            try:
                patcher.replace_file(STORM_NPC_FLOW, patch_storm_song_npc)
                applied += 1
            except NupPatchError:
                pass
            # Sheik's return-to-child gate also opens on any dungeon medal, not only the Fire or Forest flag.
            try:
                patcher.replace_file(ALLSAGE_FLOW, patch_sheik_medal_gate)
                applied += 1
            except NupPatchError:
                pass
            # AllSage follows the number of dungeon medals held. Temple exits no longer finish a sage or set
            # AllSage, so each sage's own quest keeps its drops.
            try:
                patcher.replace_file(ESCAPE_FLOW, patch_escape_sage_completes)
                applied += 1
            except NupPatchError:
                pass
            for flow_file in (GET_POUCH_CONTENT_FLOW, GET_IN_EVENT_FLOW):
                try:
                    patcher.replace_file(flow_file, add_medal_progress_after_pouch_adds)
                    applied += 1
                except NupPatchError:
                    pass
            if event_assignments:
                for flow_file in STONE_GATE_FLOWS:
                    try:
                        patcher.replace_file(
                            flow_file,
                            lambda data, f=flow_file: patch_stone_gates(data, f),
                        )
                        applied += 1
                    except NupPatchError:
                        pass
                # The check is copied into each flow that calls it, so it runs inside that flow. It is read
                # after the gates are patched so the copies include the gate changes.
                door_check = patcher.read_file(STONE_CHECK_FLOW_FILE)
                # A stone can be granted from any stone slot, so each grant rechecks the Door of Time.
                for flow_file in STONE_SLOT_FLOWS:
                    patcher.replace_file(flow_file, lambda data: add_stone_count_check(data, door_check))
                    applied += 1
                # Chests, hearts, and NPC grants pass through the shared pouch add, so a stone from any
                # of them rechecks the Door of Time too.
                for flow_file in POUCH_ADD_FLOWS:
                    patcher.replace_file(
                        flow_file,
                        lambda data: add_stone_count_check_at_route_end(data, door_check, POUCH_ADD_SUBFLOW),
                    )
                    applied += 1
            if shop_actors or fairy_randomized:
                patcher.replace_file(
                    GAME_DATA_LIST,
                    lambda data: patch_gamedata_list(data, shop=bool(shop_actors), npc_grant=fairy_randomized),
                )
            if shop_actors:
                # Combine all DisplayShop edits in one transform. The bag gate reroutes the
                # sold-out gate; the stone recount runs after the purchase and before autosave.
                sells_slingshot = any(item == SLINGSHOT_ITEM for _, item, _ in shop_assignments or [])

                def display_shop(data: bytes, bag: bool = sells_slingshot) -> bytes:
                    data = patch_kokiri_soldout(data)
                    if bag:
                        data = add_shop_slingshot_bag(data)
                    if event_assignments:
                        data = add_shop_stone_count_check(data, door_check)
                    return add_medal_progress_after_shop_purchase(data)

                patcher.replace_file(DISPLAY_SHOP_FLOW, display_shop)
                applied += 1
            patcher.update_resource_size_tables()
        except Exception:
            if shop_actors or heart_actors:
                # The NUP already holds the new packs: "manifest-only" would hide a half-patched ROM.
                raise
            return PatchResult(
                applied=0,
                skipped=len(patches),
                mode="manifest-only",
                unresolved_locations=[p.location_name for p in patches],
            )

        return PatchResult(applied=applied, skipped=0, mode="binary", unresolved_locations=[],
                           shop_actors=shop_actors, heart_actors=heart_actors)

    def write_patch_manifest(self, patches: list[PatchRecord], out_path: Path) -> None:
        payload = [
            {
                "location": p.location_name,
                "scene": p.scene,
                "check_type": p.check_type,
                "check_index": p.check_index,
                "vanilla_item": p.vanilla_item,
                "replacement_item": p.replacement_item,
                "item_id_hex": hex(p.item_id),
            }
            for p in patches
        ]
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def checksum(self, rom_path: Path) -> str:
        h = hashlib.sha256()
        with rom_path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()


@dataclass(slots=True)
class PatchResult:
    applied: int
    skipped: int
    mode: str                       # "binary" or "manifest-only"
    unresolved_locations: list[str]
    shop_actors: list[str] = field(default_factory=list)  # Shop_Rando_* actors added
    heart_actors: list[str] = field(default_factory=list)  # Obj_HeartRando_* actors added
