"""List overworld heart pieces that sit loose in scene placement files (not chest or event drops).

A loose piece is an ``Obj_Heart_Piece`` or ``Obj_GerudoValley_Heart_Piece`` actor without a
``Dynamic`` block. Its item can be replaced by the heart pickup clones built in
oot_randomizer.heart_pickups.

Examples:
  python scripts/scan_loose_hearts.py --rom ROM.nup --zsdic ZsDic.pack
      Print every loose piece found (scene file, actor index, translate).
  python scripts/scan_loose_hearts.py --rom ROM.nup --zsdic ZsDic.pack --write loose_heart_pieces.json
      Write the list used by the randomizer.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from oot_randomizer.byml7 import parse_byml7
from oot_randomizer.nup_chest_patcher import _load_dicts_from_sarc

from scan_chest_summary import scan_nup

HEART_GYAMLS = frozenset({"Obj_Heart_Piece", "Obj_GerudoValley_Heart_Piece"})
_ERA_TAG = re.compile(r"_(?:Child|Adult(?:_Alternative)?)(?=_)")


def loose_pieces(results: dict[str, dict]) -> list[dict]:
    """Loose heart pieces across scene results, sorted by scene file then actor index."""
    found = []
    for path, info in sorted(results.items()):
        raw = info.get("raw")
        if raw is None:
            continue
        actors = parse_byml7(raw).get("Actors") or []
        for index, actor in enumerate(actors):
            if actor.get("Gyaml") not in HEART_GYAMLS or "Dynamic" in actor:
                continue
            found.append({
                "scene_file": Path(path).name,
                "actor_index": index,
                "translate": [float(v) for v in actor["Translate"]],
            })
    return found


def heart_slots(pieces: list[dict]) -> list[dict]:
    """Merge the Child/Adult copies of each piece into one slot.

    A piece is identified by its scene (era tag removed) and position: the copies of a
    scene file share the same actor data. Slots are numbered per scene in position order.
    """
    groups: dict[tuple[str, tuple[float, ...]], list[dict]] = {}
    for p in pieces:
        base = _ERA_TAG.sub("", p["scene_file"])
        groups.setdefault((base, tuple(p["translate"])), []).append(p)

    slots = []
    counts: dict[str, int] = {}
    for (base, translate), copies in sorted(groups.items()):
        scene = base.split("_")[0]
        counts[scene] = counts.get(scene, 0) + 1
        ages = sorted({"adult" if "_Adult" in c["scene_file"] else "child" for c in copies})
        slots.append({
            "name": f"{scene} Heart Piece {counts[scene]}",
            "scene": scene,
            "ages": ages,
            "translate": list(translate),
            "targets": [{"scene_file": c["scene_file"], "actor_index": c["actor_index"]} for c in copies],
        })
    return slots


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rom", required=True, type=Path, help="Path to the .nup ROM")
    parser.add_argument("--zsdic", required=True, type=Path, help="Path to ZsDic.pack")
    parser.add_argument("--pkg", type=int, default=0, help="Package index (0 = base)")
    parser.add_argument("--write", type=Path, help="Write the slot list as JSON to this path")
    args = parser.parse_args()

    dicts = _load_dicts_from_sarc(args.zsdic.read_bytes())
    results = scan_nup(args.rom, dicts, args.pkg)
    pieces = loose_pieces(results)
    slots = heart_slots(pieces)
    for s in slots:
        targets = ", ".join(f"{t['scene_file']}#{t['actor_index']}" for t in s["targets"])
        print(f"{s['name']}: ages {s['ages']} at {s['translate']} -> {targets}")
    print(f"{len(pieces)} loose heart piece actors, {len(slots)} slots")

    if args.write:
        args.write.write_text(json.dumps(slots, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.write}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
