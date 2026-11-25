from __future__ import annotations

import json
import random
import shutil
import tempfile
from dataclasses import dataclass, asdict, replace as dataclass_replace
from pathlib import Path

from .config import RandomizerConfig
from .engine import SeedEngine, build_shuffle_patches, load_default_slots
from .event_items import EVENT_SLOTS, event_location_name
from .heart_pickups import FIRE_ARROW_ITEM, FIRE_ARROW_LOCATIONS, HEART_SLOTS, heart_actor_name
from .npc_grants import NPC_SLOTS
from .logic import LogicEngine
from .nup_mod_export import export_mod
from .nup_parser import parse_nup_header, NupHeader
from .oot_data import DUNGEON_ITEMS, GOAL_PRESETS, LOGIC_PRESETS, MAJOR_ITEMS
from .patcher import RomPatcher, _legacy_item_id
from .planner import PlanOptions, PlanningError, known_locations, plan_seed
from .progressive import first_tier
from .progressive_chests import excluded_slots as progressive_excluded_slots
from .progressive_chests import progressive_targets as progressive_chest_targets
from .progressive_npc import progressive_locations
from .rom import RomValidationError, validate_nup_rom
from .shop_slots import SHOP_SLOTS, shop_actor_capacity
from .shops import ShopError, shop_actor_name
from .skulltula_rewards import SKULL_REWARDS, skull_location_name
from .songs import SONG_SLOTS, song_location_name
from .world_logic import DEFAULT_WORLD_PATH, LogicError, World, load_world


@dataclass(slots=True)
class RandomizationResult:
    rom_path: str
    output_path: str
    manifest_path: str
    patch_manifest_path: str
    seed: int
    status: str
    target: str
    logic: str
    goal: str
    item_order: list[str]
    dungeon_order: list[str]
    reachable_locations: list[str]
    placements: list[dict[str, object]]
    nup_regions: list[str]
    patch_mode: str


class OOTRandomizer:
    """Seeded OOT randomizer foundation.

    This implementation does not patch game bytes in the original ROM. Instead it
    produces a copy and a JSON manifest describing the generated seed plan.
    """

    def __init__(self, config: RandomizerConfig | None = None) -> None:
        self.config = config or RandomizerConfig()

    def _safe_output_path(self, source_path: Path) -> Path:
        if self.config.output_path:
            output_path = Path(self.config.output_path)
        else:
            suffix = source_path.suffix if source_path.suffix else ".nup"
            output_path = source_path.with_name(f"{source_path.stem}_randomized{suffix}")

        if output_path.resolve() == source_path.resolve():
            raise RomValidationError(
                "Refusing to overwrite the original ROM. Provide a separate output path."
            )
        return output_path

    def _load_world(self, slots) -> World | None:
        if not self.config.use_logic:
            return None
        path = Path(self.config.logic_file) if self.config.logic_file else DEFAULT_WORLD_PATH
        if not path.exists():
            if self.config.logic_file:
                raise RomValidationError(f"Logic file or directory not found: {path}")
            return None
        try:
            world = load_world(path)
        except LogicError as exc:
            raise RomValidationError(str(exc)) from exc
        world.check_locations(known_locations(slots))
        if world.errors:
            raise RomValidationError("Logic file has errors:\n  " + "\n  ".join(world.errors))
        return world

    def _generate_plan(self, seed: int) -> tuple[list[str], list[str]]:
        rng = random.Random(seed)

        item_order = list(MAJOR_ITEMS)
        dungeon_order = list(DUNGEON_ITEMS)

        if self.config.shuffle_items:
            rng.shuffle(item_order)
        if self.config.shuffle_dungeons:
            rng.shuffle(dungeon_order)

        item_limit = max(1, min(self.config.item_pool_limit, len(item_order)))
        dungeon_limit = max(1, min(self.config.dungeon_pool_limit, len(dungeon_order)))

        return item_order[:item_limit], dungeon_order[:dungeon_limit]

    def _write_manifest(
        self,
        source_path: Path,
        output_path: Path,
        seed: int,
        item_order: list[str],
        dungeon_order: list[str],
        placements: list[dict[str, object]],
        logic_report: dict[str, object] | None = None,
    ) -> Path:
        manifest_path = output_path.with_suffix(".json")
        payload = {
            "source_rom": str(source_path),
            "output_rom": str(output_path),
            "seed": seed,
            "logic": self.config.logic,
            "goal": self.config.goal,
            "logic_description": LOGIC_PRESETS.get(self.config.logic, "Custom logic."),
            "goal_description": GOAL_PRESETS.get(self.config.goal, "Custom goal."),
            "items": item_order,
            "dungeons": dungeon_order,
            "placements": placements,
            "shuffle_items": self.config.shuffle_items,
            "shuffle_dungeons": self.config.shuffle_dungeons,
            "shop_slots_per_shop": self.config.shop_slots_per_shop,
            "logic_check": logic_report or {"enabled": False},
        }
        manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._write_spoiler(output_path.with_suffix(".spoiler.txt"), seed, placements)
        return manifest_path

    @staticmethod
    def _write_spoiler(spoiler_path: Path, seed: int, placements: list[dict[str, object]]) -> Path:
        """Plain-text list of every placement, sorted by location, with changed locations marked."""
        lines = [f"Seed {seed}", f"{len(placements)} placements ('*' = item differs from vanilla)", ""]
        for entry in sorted(placements, key=lambda p: str(p["location"])):
            mark = "*" if entry.get("item") != entry.get("vanilla_item") else " "
            lines.append(f"{mark} {entry['location']}: {entry['item']}  (vanilla: {entry['vanilla_item']})")
        spoiler_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return spoiler_path

    def _export_mod(self, source_path: Path) -> RandomizationResult:
        """Randomize a scratch copy, then keep only the changed RomFS files as a mod folder."""
        mod_root = Path(self.config.mod_dir)
        mod_root.mkdir(parents=True, exist_ok=True)
        # The scratch copy sits next to the source ROM so it lands on a disk with room for it.
        with tempfile.TemporaryDirectory(prefix=".rando_tmp_", dir=source_path.parent) as scratch:
            scratch_nup = Path(scratch) / f"{source_path.stem}_randomized{source_path.suffix or '.nup'}"
            inner = dataclass_replace(self.config, mod_dir=None, output_path=str(scratch_nup))
            result = OOTRandomizer(inner).randomize(str(source_path))
            mod_dir = mod_root / f"{source_path.stem}_seed{result.seed}"
            export_mod(source_path, scratch_nup, mod_dir)
            sidecars = [
                Path(result.manifest_path),
                Path(result.patch_manifest_path),
                scratch_nup.with_suffix(".spoiler.txt"),
            ]
            for sidecar in sidecars:
                shutil.copy2(sidecar, mod_dir / sidecar.name)
        return dataclass_replace(
            result,
            output_path=str(mod_dir),
            manifest_path=str(mod_dir / Path(result.manifest_path).name),
            patch_manifest_path=str(mod_dir / Path(result.patch_manifest_path).name),
            status="mod-exported",
        )

    def randomize(self, rom_path: str) -> RandomizationResult:
        info = validate_nup_rom(rom_path)
        if self.config.mod_dir:
            return self._export_mod(Path(info.path))

        if self.config.seed == 0:
            seed = random.SystemRandom().randrange(1, 2**31 - 1)
        else:
            seed = self.config.seed

        if self.config.logic not in LOGIC_PRESETS:
            raise RomValidationError(f"Unsupported logic preset: {self.config.logic}")
        if self.config.goal not in GOAL_PRESETS:
            raise RomValidationError(f"Unsupported goal preset: {self.config.goal}")

        source_path = Path(info.path)
        output_path = self._safe_output_path(source_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source_path, output_path)
            zsdic_candidates = [
                source_path.with_name("ZsDic.pack"),
                Path(__file__).resolve().parents[2] / "ZsDic.pack",
            ]
            for zsdic_source in zsdic_candidates:
                if not zsdic_source.exists():
                    continue
                output_zsdic = output_path.with_name("ZsDic.pack")
                if zsdic_source.resolve() != output_zsdic.resolve():
                    shutil.copy2(zsdic_source, output_zsdic)
                break
        except OSError as exc:
            raise RomValidationError(
                f"Failed to create ROM copy at {output_path}: {exc}. "
                "Choose a destination with enough free space and write permissions."
            ) from exc

        item_order, dungeon_order = self._generate_plan(seed)
        slots = load_default_slots()
        song_assignments: dict[str, str] = {}
        event_assignments: dict[str, str] = {}
        npc_assignments: dict[str, str] = {}
        skull_assignments: dict[int, str] = {}
        shop_assignments: list[tuple[str, str, int]] = []
        heart_assignments: list[tuple[str, str]] = []
        progressive_targets: list[tuple[str, int, str]] = []
        logic_report: dict[str, object] = {"enabled": False}
        if slots:
            world = self._load_world(slots)
            max_shop_actors = None
            if self.config.shop_slots_per_shop:
                try:
                    max_shop_actors = shop_actor_capacity(output_path)
                except Exception:
                    # Not a readable NUP container: the patcher falls back to manifest-only.
                    max_shop_actors = None
            options = PlanOptions(
                shuffle_songs=self.config.shuffle_songs,
                shuffle_event_items=self.config.shuffle_event_items,
                shuffle_npc_items=self.config.shuffle_npc_items,
                shuffle_skull_rewards=self.config.shuffle_skull_rewards,
                all_locations_reachable=self.config.all_locations_reachable,
                one_major_per_dungeon=self.config.one_major_per_dungeon,
                logic_options={"bombchus_in_logic": self.config.bombchus_in_logic},
                shop_slots_per_shop=self.config.shop_slots_per_shop,
                max_shop_actors=max_shop_actors,
                shuffle_heart_pieces=self.config.shuffle_heart_pieces,
                progressive_items=self.config.progressive_items,
                progressive_excluded=(progressive_excluded_slots(slots) if self.config.progressive_items
                                      else frozenset()),
                progressive_npc=progressive_locations() if self.config.progressive_items else frozenset(),
            )
            try:
                plan = plan_seed(seed, slots, world, options)
            except PlanningError as exc:
                raise RomValidationError(str(exc)) from exc
            assignments = plan.chest_assignments
            # A progressive chest is patched with its family's lowest tier; the chest flow gives the rest.
            progressive_targets = progressive_chest_targets(assignments) if self.config.progressive_items else []
            patch_assignments = [(slot, first_tier(item)) for slot, item in assignments]
            song_assignments = {f: s for f, s in plan.song_assignments.items() if s != SONG_SLOTS[f]}
            event_assignments = {f: i for f, i in plan.event_assignments.items() if i != EVENT_SLOTS[f]}
            npc_assignments = {loc: i for loc, i in plan.npc_assignments.items() if i != NPC_SLOTS[loc].item}
            skull_assignments = {n: i for n, i in plan.skull_assignments.items() if i != SKULL_REWARDS[n]}
            shop_assignments = plan.shop_assignments
            heart_assignments = plan.heart_assignments
            if world is not None:
                logic_report = {
                    "enabled": True,
                    "attempts": plan.attempts,
                    "all_locations_reachable": self.config.all_locations_reachable,
                    "unreachable_locations": plan.unreachable,
                    "extra_requirements": plan.extra_requirements,
                    "warnings": world.warnings,
                }
            patch_records = build_shuffle_patches(patch_assignments)
            placements = [
                {
                    "location": slot.name,
                    "vanilla_item": slot.vanilla_item,
                    "item": item,
                    "scene_files": [scene_file for scene_file, _ in slot.targets],
                    "item_id_hex": hex(_legacy_item_id(item)),
                }
                for slot, item in assignments
            ]
            placements += [
                {"location": song_location_name(flow), "vanilla_item": SONG_SLOTS[flow], "item": song}
                for flow, song in plan.song_assignments.items()
            ]
            placements += [
                {"location": event_location_name(flow), "vanilla_item": EVENT_SLOTS[flow], "item": item}
                for flow, item in plan.event_assignments.items()
            ]
            placements += [
                {"location": loc, "vanilla_item": NPC_SLOTS[loc].item, "item": item}
                for loc, item in plan.npc_assignments.items()
            ]
            placements += [
                {"location": skull_location_name(n), "vanilla_item": SKULL_REWARDS[n], "item": item}
                for n, item in plan.skull_assignments.items()
            ]
            placements += [
                {
                    "location": name,
                    "vanilla_item": SHOP_SLOTS[name].vanilla,
                    "item": item,
                    "price": price,
                    "shop_actor": shop_actor_name(item),
                    "scene_files": SHOP_SLOTS[name].scene_files,
                }
                for name, item, price in plan.shop_assignments
            ]
            placements += [
                {
                    "location": name,
                    "vanilla_item": FIRE_ARROW_ITEM if name in FIRE_ARROW_LOCATIONS else "Obj_Heart_Piece",
                    "item": item,
                    "heart_actor": heart_actor_name(item),
                    "scene_files": [shelf.scene for shelf in HEART_SLOTS[name].shelves],
                }
                for name, item in plan.heart_assignments
            ]
        else:
            engine_placements = SeedEngine(self.config.logic).generate(seed, item_order)
            patch_records = [p.patch for p in engine_placements]
            placements = [
                {
                    "location": p.location,
                    "region": p.region,
                    "item": p.item,
                    "required_items": list(p.required_items),
                    "item_id_hex": hex(p.patch.item_id),
                    "byte_offset": p.patch.byte_offset,
                }
                for p in engine_placements
            ]

        patcher = RomPatcher()
        try:
            patch_result = patcher.apply(output_path, patch_records, song_assignments, skull_assignments,
                                         shop_assignments, event_assignments=event_assignments,
                                         npc_assignments=npc_assignments,
                                         skip_intro=self.config.skip_intro,
                                         heart_assignments=heart_assignments,
                                         progressive_chests=progressive_targets)
        except ShopError as exc:
            raise RomValidationError(f"Shop or heart items could not be applied: {exc}") from exc
        except OSError as exc:
            raise RomValidationError(
                f"Patching {output_path} failed: {exc}. Another program (e.g. an emulator scanning "
                "the output folder) may have the file open; the output is incomplete, run again."
            ) from exc
        patch_manifest_path = output_path.with_suffix(".patch.json")
        patcher.write_patch_manifest(patch_records, patch_manifest_path)

        nup_header = parse_nup_header(source_path)
        nup_regions = [r.name for r in nup_header.regions]

        reachable_locations = LogicEngine(self.config.logic).evaluate(item_order)
        manifest_path = self._write_manifest(
            source_path, output_path, seed, item_order, dungeon_order, placements, logic_report
        )

        return RandomizationResult(
            rom_path=str(info.path),
            output_path=str(output_path),
            manifest_path=str(manifest_path),
            patch_manifest_path=str(patch_manifest_path),
            seed=seed,
            status="randomized-copy-created",
            target=info.likely_target,
            logic=self.config.logic,
            goal=self.config.goal,
            item_order=item_order,
            dungeon_order=dungeon_order,
            reachable_locations=reachable_locations,
            placements=placements,
            nup_regions=nup_regions,
            patch_mode=patch_result.mode,
        )
