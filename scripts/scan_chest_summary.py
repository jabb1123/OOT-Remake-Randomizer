"""Scan every scene placement file in a NUP for chests, then diff, write, or search.

Examples:
  python scripts/scan_chest_summary.py --nup ROM.nup --zsdic ZsDic.pack
      Diff the fresh scan against chest_locations_summary.json.
  python scripts/scan_chest_summary.py --nup ROM.nup --zsdic ZsDic.pack --write new_summary.json
      Write a fresh summary in the same shape as chest_locations_summary.json.
  python scripts/scan_chest_summary.py --nup ROM.nup --zsdic ZsDic.pack --find Obj_Heart_Piece
      List scene files whose decompressed bytes mention an actor name, and whether they have chests.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from nup.access import iter_children
from nup.read import NupReader

from oot_randomizer.nup_chest_patcher import _decompress, _load_dicts_from_sarc, _walk_byml_chests

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = REPO_ROOT / "chest_locations_summary.json"
SCENE_SUFFIX = ".bcett.byml.zs"
CHEST_FIELDS = ("gyaml", "room_index", "vanilla_drop", "str_table_index")


def iter_scene_files(r: NupReader, dir_index: int, prefix: str = ""):
    """Yield (romfs path, file index) for every scene placement file under dir_index."""
    for ref in iter_children(r, dir_index):
        name = ref.name.decode("utf-8", "replace")
        path = f"{prefix}/{name}" if prefix else name
        if ref.is_dir:
            yield from iter_scene_files(r, ref.index, path)
        elif name.endswith(SCENE_SUFFIX):
            yield path, ref.index


def scan_nup(nup: Path, dicts: dict[int, bytes], pkg_index: int = 0) -> dict[str, dict]:
    """Return {scene_file: {"chests": [...]} | {"error": "..."}} for every scene file in the NUP."""
    results: dict[str, dict] = {}
    r = NupReader(str(nup))
    try:
        pkg = r.packages[pkg_index]
        for path, index in iter_scene_files(r, pkg.romfs_dir):
            try:
                byml = _decompress(r.read_file(index), dicts)
                chests = [
                    {
                        "gyaml": c.gyaml,
                        "room_index": c.room_index,
                        "vanilla_drop": c.vanilla_drop,
                        "str_table_index": c.str_table_index,
                    }
                    for c in _walk_byml_chests(byml)
                ]
                results[path] = {"chests": chests, "raw": byml}
            except Exception as exc:  # reported, not hidden
                results[path] = {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        r.close()
    return results


def build_summary(results: dict[str, dict]) -> list[dict]:
    """Build summary entries in the chest_locations_summary.json shape, skipping scenes without chests."""
    entries = []
    for path, info in results.items():
        chests = info.get("chests")
        if not chests:
            continue
        entries.append({
            "scene_file": path,
            "count": len(chests),
            "chests": [{k: c[k] for k in CHEST_FIELDS} for c in chests],
        })
    return entries


def chest_counter(entry: dict | None) -> Counter:
    if entry is None:
        return Counter()
    return Counter(tuple(c[k] for k in CHEST_FIELDS) for c in entry["chests"])


def diff_summaries(old: list[dict], new: list[dict]) -> list[str]:
    old_map = {e["scene_file"]: e for e in old}
    new_map = {e["scene_file"]: e for e in new}
    lines = []
    for path in sorted(new_map.keys() - old_map.keys()):
        lines.append(f"ADDED scene: {path} ({new_map[path]['count']} chests)")
    for path in sorted(old_map.keys() - new_map.keys()):
        lines.append(f"REMOVED scene: {path} ({old_map[path]['count']} chests)")
    for path in sorted(old_map.keys() & new_map.keys()):
        before, after = chest_counter(old_map[path]), chest_counter(new_map[path])
        if before == after:
            continue
        for key in sorted((before - after).elements()):
            lines.append(f"  - {path}: {key}")
        for key in sorted((after - before).elements()):
            lines.append(f"  + {path}: {key}")
    return lines


def find_objects(results: dict[str, dict], name: str) -> list[str]:
    needle = name.encode()
    lines = []
    for path, info in sorted(results.items()):
        if "raw" not in info or needle not in info["raw"]:
            continue
        chests = info["chests"]
        hits = [c["vanilla_drop"] for c in chests if c["vanilla_drop"] == name]
        tag = f"{len(chests)} chest(s), {len(hits)} with {name} as drop" if chests else "no chests"
        lines.append(f"{path}: {tag}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rom", required=True, type=Path, help="Path to the .nup ROM")
    parser.add_argument("--zsdic", required=True, type=Path, help="Path to ZsDic.pack")
    parser.add_argument("--pkg", type=int, default=0, help="Package index (0 = base)")
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY, help="Summary to diff against")
    parser.add_argument("--write", type=Path, help="Write the fresh summary to this path")
    parser.add_argument("--find", metavar="OBJ_NAME", help="List scene files that mention an actor name")
    args = parser.parse_args()

    dicts = _load_dicts_from_sarc(args.zsdic.read_bytes())
    results = scan_nup(args.rom, dicts, args.pkg)

    errors = {p: i["error"] for p, i in results.items() if "error" in i}
    print(f"scanned {len(results)} scene files, {len(errors)} errors")
    for path, msg in sorted(errors.items()):
        print(f"  ERROR {path}: {msg}")

    if args.find:
        for line in find_objects(results, args.find):
            print(line)
        return 0

    fresh = build_summary(results)
    print(f"{len(fresh)} scene files with chests, {sum(e['count'] for e in fresh)} chests total")

    if args.write:
        args.write.write_text(json.dumps(fresh, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.write}")

    if args.summary.exists():
        old = json.loads(args.summary.read_text(encoding="utf-8"))
        lines = diff_summaries(old, fresh)
        print(f"diff vs {args.summary}: {len(lines)} change line(s)")
        for line in lines:
            print(line)
    else:
        print(f"no existing summary at {args.summary} to diff against")
    return 0


if __name__ == "__main__":
    sys.exit(main())
