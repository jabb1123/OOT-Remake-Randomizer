#!/bin/python3

import argparse
import collections
import os
import sys

# Add the repository's local packages before importing them.
sys.path.insert(0, r"C:\Users\jabb1123\Desktop\Roms\oot_randomizer\src")
sys.path.insert(0, r"C:\Users\jabb1123\Desktop\Roms\oot_randomizer\nup\tools\nup")

import evfl
from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent
from nup.access import iter_children
from nup.read import NupReader

from oot_randomizer.byml7 import parse_byml7
from oot_randomizer.nup_chest_patcher import _decompress, _load_dicts_from_sarc


def _byml_lines(obj, path: str = "") -> list[str]:
    """Flatten a parsed BYML tree into one 'Path.To[0].Key = value' line per leaf."""
    if isinstance(obj, dict):
        out: list[str] = []
        for key, value in obj.items():
            out += _byml_lines(value, f"{path}.{key}" if path else str(key))
        return out
    if isinstance(obj, list):
        out = []
        for i, value in enumerate(obj):
            out += _byml_lines(value, f"{path}[{i}]")
        return out
    return [f"{path} = {obj!r}"]

# ROM = r"C:\Users\jabb1123\Desktop\Roms\The Legend of Zelda Ocarina of Time + U2\The Legend of Zelda Ocarina of Time   U2.0.0.nup"
# ZSDIC = r"C:\Users\jabb1123\Desktop\Roms\oot_randomizer\ZsDic.pack"
# NAME = "Dm_ZoraFountain_0030_Npc_Zora_ZU_Ruto_Child.anim.baev.zs"

def build_parser() -> argparse.ArgumentParser:
    """
    """
    parser = argparse.ArgumentParser(description="Ocarina of Time Decomp script")

    parser.add_argument("--rom", required=True, help="Path to a .nup ROM file")
    parser.add_argument("--zsdic", required=True, help="Path to the .ZcDic file")
    parser.add_argument("--e_name", required=True, help="File name to decompress and parse")
    parser.add_argument(
        "--dir",
        default="Event/EventFlow",
        help="romfs directory containing the file, e.g. AnimationEvent/Animation",
    )
    parser.add_argument(
        "--out",
        default=".",
        help="Folder for output: <e_name>.raw (decompressed bytes) and <e_name>.txt (event listing)",
    )

    return parser


def find_child(r, dir_index, name):
    for c in iter_children(r, dir_index):
        if c.name.decode("utf-8", "surrogateescape") == name:
            return c
    print("No child found...")
    return None

parser = build_parser()
argv = sys.argv[1:]
args = parser.parse_args(argv)


dicts = _load_dicts_from_sarc(open(args.zsdic, "rb").read())
r = NupReader(args.rom)
d = r.packages[0].romfs_dir  # 0 = base package
path_parts = [p for p in args.dir.split("/") if p] + [args.e_name]
file_node = None
for part in path_parts:
    node = find_child(r, d, part)
    if node is None:
        r.close()
        sys.exit(f"Not found in romfs: {'/'.join(path_parts)} (missing '{part}')")
    file_node = node
    d = node.index
if file_node.is_dir:
    r.close()
    sys.exit(f"'{args.e_name}' is a directory, not a file")
raw = _decompress(r.read_file(file_node.index), dicts)  # ZSTD + dictionary
r.close()

os.makedirs(os.path.join(args.out, "raw"), exist_ok=True)
raw_path = os.path.join(args.out, "raw/",  args.e_name + ".raw")
with open(raw_path, "wb") as fh:
    fh.write(raw)

lines: list[str] = []
if raw[:2] in (b"YB", b"BY"):
    # Scene placement files (*.bcett.byml): one line per BYML leaf.
    lines = _byml_lines(parse_byml7(raw))
elif raw[:8] != b"BFEVFL\x00\x00":
    sys.exit(
        f"Not an event flow or BYML (magic {raw[:4]!r}). "
        f"Decompressed bytes saved to {os.path.abspath(raw_path)}"
    )
else:
    flow = evfl.EventFlow()
    flow.read(raw)  # bytes, not a BytesIO
    fc = flow.flowchart

    if fc:
        counts = dict(collections.Counter(type(e.data).__name__ for e in fc.events))
        lines.append(f"events: {len(fc.events)} {counts}")

        for ev in fc.events:
            dd = ev.data
            if isinstance(dd, ActionEvent):
                params = dd.params.data if dd.params else ""
                lines.append(f"{ev.name} ACT {dd.actor.v.identifier.name} {dd.actor_action.v} {params}")
            elif isinstance(dd, SwitchEvent):
                cases = {k: v.v.name for k, v in dd.cases.items()}
                lines.append(f"{ev.name} SW {dd.actor.v.identifier.name} {dd.actor_query.v} {cases}")
            elif isinstance(dd, SubFlowEvent):
                params = dd.params.data if dd.params else ""
                lines.append(f"{ev.name} SUB {dd.res_flowchart_name} {dd.entry_point_name} {params}")

for line in lines:
    print(line)

txt_path = os.path.join(args.out, args.e_name + ".txt")
with open(txt_path, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"Wrote {len(lines)} lines to {os.path.abspath(txt_path)}")
