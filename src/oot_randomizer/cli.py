from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import RandomizerConfig
from .nup_parser import scan_nup_structure
from .randomizer import OOTRandomizer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ocarina of Time randomizer prototype")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # --- randomize sub-command (default behaviour) ---
    rand = sub.add_parser("randomize", help="Generate a randomized ROM copy")
    rand.add_argument("--rom", required=True, help="Path to a .nup ROM file")
    rand.add_argument("--seed", type=int, default=0, help="Random seed; 0 = generate")
    rand.add_argument("--goal", default="ganon", help="Winning condition")
    rand.add_argument("--logic", default="glitchedless", help="Logic preset")
    rand.add_argument("--no-item-shuffle", action="store_true")
    rand.add_argument("--no-dungeon-shuffle", action="store_true")
    rand.add_argument("--no-song-shuffle", action="store_true")
    rand.add_argument("--no-event-items", action="store_true",
                      help="Keep the vanilla medallions, stones and ocarinas in their grant flows")
    rand.add_argument("--no-npc-items", action="store_true",
                      help="Keep the vanilla bag, quiver and scale upgrades in their NPC and minigame grants")
    rand.add_argument("--no-skull-shuffle", action="store_true",
                      help="Keep the vanilla House of Skulltula rewards")
    rand.add_argument("--output", default=None, help="Output ROM copy path; original is never modified")
    rand.add_argument("--logic-file", default=None,
                      help="World logic: a TOML file or a directory of them (default: logic/world/)")
    rand.add_argument("--no-logic", action="store_true", help="Skip the completability check")
    rand.add_argument("--goal-only", action="store_true",
                      help="Only require the goal to be reachable, not every location")
    rand.add_argument("--no-bombchus-in-logic", action="store_true")
    rand.add_argument("--one-major-per-dungeon", action="store_true")
    rand.add_argument("--shop-slots", type=int, default=2, choices=range(0, 5), metavar="N",
                      help="Shop shelf slots per shop that hold randomized items (0-4, 0 = off; default 2)")
    rand.add_argument("--skip-intro", action="store_true",
                      help="Skip the opening Introduction cutscene (Kokiri Forest wake-up) at the start of a new game")
    rand.add_argument("--no-heart-shuffle", action="store_true",
                      help="Keep the loose overworld heart pieces as vanilla hearts (they are randomized by default)")

    # --- logic sub-command ---
    lg = sub.add_parser("logic", help="Create or check the world logic file")
    lg_sub = lg.add_subparsers(dest="logic_command", metavar="ACTION", required=True)
    tpl = lg_sub.add_parser("template", help="Write a single-file starter logic listing every location")
    tpl.add_argument("--out", default=None, help="Output path (default: logic/world_template.toml)")
    tpl.add_argument("--force", action="store_true", help="Overwrite an existing file")
    chk = lg_sub.add_parser("check", help="Validate the logic and test it against the vanilla game")
    chk.add_argument("--file", default=None, help="Logic file or directory (default: logic/world/)")

    # --- scan sub-command ---
    sc = sub.add_parser("scan", help="Scan a .nup file and report its internal structure")
    sc.add_argument("--rom", required=True, help="Path to the .nup file to scan")
    sc.add_argument("--max-mb", type=int, default=256, help="Maximum megabytes to scan (default 256)")
    sc.add_argument("--chunk-mb", type=int, default=4, help="Chunk size in megabytes (default 4)")
    sc.add_argument("--json-out", default=None, help="Write full JSON report to this file")

    return parser


def _cmd_randomize(args: argparse.Namespace) -> None:
    config = RandomizerConfig(
        seed=args.seed,
        goal=args.goal,
        logic=args.logic,
        shuffle_items=not args.no_item_shuffle,
        shuffle_dungeons=not args.no_dungeon_shuffle,
        shuffle_songs=not args.no_song_shuffle,
        shuffle_event_items=not args.no_event_items,
        shuffle_npc_items=not args.no_npc_items,
        shuffle_skull_rewards=not args.no_skull_shuffle,
        output_path=args.output,
        use_logic=not args.no_logic,
        logic_file=args.logic_file,
        all_locations_reachable=not args.goal_only,
        bombchus_in_logic=not args.no_bombchus_in_logic,
        one_major_per_dungeon=args.one_major_per_dungeon,
        shop_slots_per_shop=args.shop_slots,
        shuffle_heart_pieces=not args.no_heart_shuffle,
        skip_intro=args.skip_intro,
    )
    result = OOTRandomizer(config).randomize(args.rom)
    print(json.dumps({
        "rom_path": result.rom_path,
        "output_path": result.output_path,
        "manifest_path": result.manifest_path,
        "patch_manifest_path": result.patch_manifest_path,
        "seed": result.seed,
        "status": result.status,
        "target": result.target,
        "logic": config.logic,
        "goal": config.goal,
        "patch_mode": result.patch_mode,
        "nup_regions": result.nup_regions,
        "item_order": result.item_order,
        "dungeon_order": result.dungeon_order,
        "reachable_locations": result.reachable_locations,
        "placements": result.placements,
    }, indent=2))


def _cmd_logic(args: argparse.Namespace) -> int:
    from .engine import load_default_slots
    from .event_items import EVENT_SLOTS, event_location_name
    from .heart_pickups import FIRE_ARROW_ITEM, FIRE_ARROW_LOCATIONS, HEART_LOCATIONS
    from .logic_template import build_template
    from .npc_grants import NPC_SLOTS
    from .planner import known_locations
    from .shop_slots import SHOP_SLOTS, VANILLA_SHOP_LOGIC_ITEMS
    from .skulltula_rewards import SKULL_REWARDS, TOKEN_ITEM, skull_location_name
    from .songs import SONG_SLOTS, song_location_name
    from .world_logic import DEFAULT_TEMPLATE_PATH, DEFAULT_WORLD_PATH, LogicError, load_world

    slots = load_default_slots()
    if not slots:
        print("chest_locations_summary.json not found; cannot list locations", file=sys.stderr)
        return 1

    if args.logic_command == "template":
        out = Path(args.out) if args.out else DEFAULT_TEMPLATE_PATH
        if out.exists() and not args.force:
            print(f"{out} already exists; use --force to overwrite", file=sys.stderr)
            return 1
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(build_template(slots), encoding="utf-8")
        print(f"Wrote {out} ({len(slots)} chests, {len(SONG_SLOTS)} song locations)")
        return 0

    path = Path(args.file) if args.file else DEFAULT_WORLD_PATH
    try:
        world = load_world(path)
    except (LogicError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    world.check_locations(known_locations(slots))
    for warning in world.warnings:
        print(f"warning: {warning}")
    for error in world.errors:
        print(f"error: {error}")
    if world.errors:
        return 1

    obtainable = {s.vanilla_item for s in slots} | set(SONG_SLOTS.values()) | set(world.start_items)
    obtainable |= set(SKULL_REWARDS.values()) | {TOKEN_ITEM} | set(EVENT_SLOTS.values())
    obtainable |= {slot.item for slot in NPC_SLOTS.values()} | {FIRE_ARROW_ITEM}
    counters = set(world.key_locations.values())  # dungeon key counters are obtained through their chests
    for item in sorted(world.referenced_items - obtainable - counters):
        print(f"warning: {item} is required somewhere but no location holds it")

    # The unmodified game must satisfy the rules, otherwise they are too strict.
    vanilla = {s.name: s.vanilla_item for s in slots}
    vanilla |= {song_location_name(f): song for f, song in SONG_SLOTS.items()}
    vanilla |= {skull_location_name(n): item for n, item in SKULL_REWARDS.items()}
    vanilla |= {event_location_name(f): item for f, item in EVENT_SLOTS.items()}
    vanilla |= {loc: slot.item for loc, slot in NPC_SLOTS.items()}
    vanilla |= {loc: TOKEN_ITEM for loc in world.token_locations}
    # Shop slots keep their vanilla shelf item, which is not an item actor in the logic.
    vanilla |= {loc: None for loc in SHOP_SLOTS}
    vanilla |= {loc: None for loc in HEART_LOCATIONS}  # loose heart pieces hold no logic item
    vanilla |= {loc: FIRE_ARROW_ITEM for loc in FIRE_ARROW_LOCATIONS}  # the sun reward is the only copy
    vanilla |= VANILLA_SHOP_LOGIC_ITEMS
    options = {"bombchus_in_logic": True}
    result = world.explore(vanilla, options)
    unreached = sorted(set(vanilla) - result.locations)
    print(f"Regions: {len(world.regions)}  Locations listed: {len(world.location_region)}/{len(vanilla)}")
    print(f"Vanilla game: goal {'reachable' if world.goal_met(result, options) else 'NOT reachable'}, "
          f"{len(result.locations)}/{len(vanilla)} locations reachable, "
          f"events: {', '.join(sorted(result.events)) or 'none'}")
    for loc in unreached:
        print(f"  unreachable in vanilla: {loc}")
    return 0 if world.goal_met(result, options) and not unreached else 1


def _cmd_scan(args: argparse.Namespace) -> None:
    max_bytes = args.max_mb * 1024 * 1024
    chunk_bytes = args.chunk_mb * 1024 * 1024

    scanned_mb = [0]
    file_gb = [None]

    def _progress(done: int, total: int) -> None:
        file_gb[0] = total / (1024 ** 3)
        done_mb = done / (1024 ** 2)
        pct = 100.0 * done / total
        print(f"\r  Scanning... {done_mb:.0f} MB / {args.max_mb} MB  ({pct:.1f}%)  ", end="", flush=True)
        scanned_mb[0] = done_mb

    print(f"Scanning {args.rom}")
    print(f"  Max scan depth : {args.max_mb} MB")
    print(f"  Chunk size     : {args.chunk_mb} MB")
    print()

    report = scan_nup_structure(
        args.rom,
        max_bytes=max_bytes,
        chunk_size=chunk_bytes,
        progress=_progress,
    )
    print()  # newline after progress line
    # print(report.summary())

    if args.json_out:
        Path(args.json_out).write_text(report.to_json(), encoding="utf-8")
        print(f"\nFull JSON report written to: {args.json_out}")


def main() -> None:
    parser = build_parser()

    # Legacy flat-flag form: oot-randomizer --rom ... (no subcommand)
    # Detect by checking for --rom before any subcommand token.
    argv = sys.argv[1:]
    if argv and not argv[0].startswith("-") and argv[0] not in ("randomize", "scan", "logic"):
        argv = ["randomize"] + argv
    elif argv and argv[0].startswith("-"):
        argv = ["randomize"] + argv

    args = parser.parse_args(argv)

    if args.command == "scan":
        _cmd_scan(args)
    elif args.command == "logic":
        sys.exit(_cmd_logic(args))
    else:
        _cmd_randomize(args)


if __name__ == "__main__":
    main()
