#!/bin/python3

import argparse
import collections
import os
import sys

# Add the repository's local packages before importing them.
sys.path.insert(0, r"C:\Users\jabb1123\Desktop\Roms\oot_randomizer\src")
sys.path.insert(0, r"C:\Users\jabb1123\Desktop\Roms\oot_randomizer\nup\tools\nup")

import evfl
from evfl.event import (
    ActionEvent,
    ForkEvent,
    JoinEvent,
    ReturnEvent,
    SubFlowEvent,
    SubFlowSwitchEvent,
    SwitchEvent,
)
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

    parser.add_argument(
        "--dot",
        action="store_true",
        help="For flowcharts, also write <e_name>.dot (Graphviz) with entry points and event links",
    )

    return parser


def find_child(r, dir_index, name):
    for c in iter_children(r, dir_index):
        if c.name.decode("utf-8", "surrogateescape") == name:
            return c
    print("No child found...")
    return None

def _name(ref) -> str:
    target = getattr(ref, "v", None)
    return target.name if target is not None else "(end)"


def _link_lines(dd) -> list[str]:
    if isinstance(dd, ForkEvent):
        return [
            "    forks: " + ", ".join(_name(f) for f in dd.forks),
            f"    join: {_name(dd.join)}",
        ]
    if not hasattr(dd, "nxt"):
        return []
    return [f"    next: {_name(dd.nxt)}"]


def _params_of(container) -> str:
    return container.data if container else ""


def _timeline_lines(tl) -> list[str]:
    lines = [
        f"TIMELINE {tl.name} duration={tl.duration} "
        f"actors={[a.identifier.name for a in tl.actors]}",
        f"subtimelines: {[s.name for s in tl.subtimelines]}",
    ]
    for cut in tl.cuts:
        lines.append(f"CUT {cut.name} t={cut.start_time} {_params_of(cut.params)}")
    for clip in sorted(tl.clips, key=lambda c: c.start_time):
        lines.append(
            f"CLIP t={clip.start_time} d={clip.duration} "
            f"{clip.actor.v.identifier.name} {clip.actor_action.v.v} {_params_of(clip.params)}"
        )
    for o in tl.oneshots:
        lines.append(
            f"ONESHOT t={o.time} {o.actor.v.identifier.name} {o.actor_action.v.v} {_params_of(o.params)}"
        )
    for trg in tl.triggers:
        clip = trg.clip.v
        lines.append(
            f"TRIGGER {trg.type.name} t={trg.get_trigger_time()} "
            f"clip={clip.actor_action.v.v}@{clip.start_time}"
        )
    return lines


def _dot_quote(text) -> str:
    escaped = str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _short_params(container, limit: int = 120) -> str:
    data = container.data if container else {}
    text = ", ".join(f"{k}={v}" for k, v in data.items())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _target(ref):
    return getattr(ref, "v", None)


def _dot_event_edges(ev_name: str, dd) -> list[str]:
    """Edges leaving one event: fork branches, switch cases, or the next event."""
    if isinstance(dd, ForkEvent):
        edges = [
            f'  {_dot_quote(ev_name)} -> {_dot_quote(_target(f).name)} [label="fork {i}"];'
            for i, f in enumerate(dd.forks) if _target(f) is not None
        ]
        if _target(dd.join) is not None:
            edges.append(f'  {_dot_quote(ev_name)} -> {_dot_quote(_target(dd.join).name)} [label="join", style=dashed];')
        return edges
    if isinstance(dd, (SwitchEvent, SubFlowSwitchEvent)):
        return [
            f'  {_dot_quote(ev_name)} -> {_dot_quote(_target(ref).name)} [label="case {key}"];'
            for key, ref in sorted(dd.cases.items()) if _target(ref) is not None
        ]
    target = _target(getattr(dd, "nxt", None))
    return [f'  {_dot_quote(ev_name)} -> {_dot_quote(target.name)};'] if target is not None else []


def _flowchart_dot(flow_name: str, fc) -> str:
    """Graphviz DOT for a flowchart: entry points, events, and links to other flows."""
    nodes: list[str] = []
    edges: list[str] = []
    external: set[str] = set()

    def external_flow(flow: str, label: str) -> str:
        node_id = f"flow:{flow}"
        if node_id not in external:
            external.add(node_id)
            nodes.append(
                f"  {_dot_quote(node_id)} [label={_dot_quote(label)}, shape=box3d, style=filled, fillcolor=lightgrey];"
            )
        return node_id

    for entry in fc.entry_points:
        entry_id = f"entry:{entry.name}"
        nodes.append(
            f"  {_dot_quote(entry_id)} [label={_dot_quote(entry.name)}, shape=doublecircle, style=filled, fillcolor=gold];"
        )
        start = _target(entry.main_event)
        if start is not None:
            edges.append(f'  {_dot_quote(entry_id)} -> {_dot_quote(start.name)} [label="start"];')

    for ev in fc.events:
        dd = ev.data
        if isinstance(dd, ActionEvent):
            action = str(dd.actor_action.v)
            label = f"{ev.name}\n{dd.actor.v.identifier.name}.{action}\n{_short_params(dd.params)}"
            fill = "white"
            if action == "EventTransition":
                # Plays another flow or timeline by name, then continues.
                fill = "lightblue"
                event_name = dd.params.data.get("EventName", "") if dd.params else ""
                flow_id = external_flow(event_name, event_name)
                edges.append(f'  {_dot_quote(ev.name)} -> {_dot_quote(flow_id)} [label="transition", style=dashed, color=blue];')
            nodes.append(f"  {_dot_quote(ev.name)} [label={_dot_quote(label)}, shape=box, style=filled, fillcolor={fill}];")
        elif isinstance(dd, SwitchEvent):
            label = f"{ev.name}\nSWITCH {dd.actor.v.identifier.name}\n{dd.actor_query.v}\n{_short_params(dd.params)}"
            nodes.append(f"  {_dot_quote(ev.name)} [label={_dot_quote(label)}, shape=diamond];")
        elif isinstance(dd, (SubFlowEvent, SubFlowSwitchEvent)):
            flow_id = external_flow(dd.res_flowchart_name, f"{dd.res_flowchart_name}\n@{dd.entry_point_name}")
            label = f"{ev.name}\nSUB {dd.res_flowchart_name}\n@{dd.entry_point_name}"
            nodes.append(f"  {_dot_quote(ev.name)} [label={_dot_quote(label)}, shape=component];")
            edges.append(f'  {_dot_quote(ev.name)} -> {_dot_quote(flow_id)} [label="call", style=dashed, color=blue];')
        elif isinstance(dd, ForkEvent):
            label = f"{ev.name}\nFORK"
            nodes.append(f"  {_dot_quote(ev.name)} [label={_dot_quote(label)}, shape=trapezium];")
        elif isinstance(dd, JoinEvent):
            label = f"{ev.name}\nJOIN"
            nodes.append(f"  {_dot_quote(ev.name)} [label={_dot_quote(label)}, shape=invtrapezium];")
        elif isinstance(dd, ReturnEvent):
            label = f"{ev.name}\nRETURN {dd.value}"
            nodes.append(f"  {_dot_quote(ev.name)} [label={_dot_quote(label)}, shape=octagon];")
        else:
            nodes.append(f"  {_dot_quote(ev.name)} [label={_dot_quote(ev.name)}, shape=box, style=dotted];")
        edges.extend(_dot_event_edges(ev.name, dd))

    return "\n".join([
        f"digraph {_dot_quote(flow_name)} {{",
        "  rankdir=LR;",
        '  node [fontname="Consolas", fontsize=10];',
        f"  label={_dot_quote(flow_name)};",
        *nodes,
        *edges,
        "}",
        "",
    ])


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
        for entry in fc.entry_points:
            lines.append(f"ENTRY {entry.name} -> {_name(entry.main_event)}")

        for ev in fc.events:
            dd = ev.data
            if isinstance(dd, ActionEvent):
                params = dd.params.data if dd.params else ""
                lines.append(f"{ev.name} ACT {dd.actor.v.identifier.name} {dd.actor_action.v} {params}")
            elif isinstance(dd, SwitchEvent):
                cases = {k: v.v.name for k, v in dd.cases.items()}
                params = dd.params.data if dd.params else ""
                lines.append(f"{ev.name} SW {dd.actor.v.identifier.name} {dd.actor_query.v} {cases} {params}")
            elif isinstance(dd, SubFlowEvent):
                params = dd.params.data if dd.params else ""
                lines.append(f"{ev.name} SUB {dd.res_flowchart_name} {dd.entry_point_name} {params}")
            elif isinstance(dd, ForkEvent):
                lines.append(f"{ev.name} FORK")
            elif isinstance(dd, JoinEvent):
                lines.append(f"{ev.name} JOIN")
            lines.extend(_link_lines(dd))
        if args.dot:
            dot_path = os.path.join(args.out, args.e_name + ".dot")
            with open(dot_path, "w", encoding="utf-8") as fh:
                fh.write(_flowchart_dot(args.e_name, fc))
            print(f"Wrote DOT graph to {os.path.abspath(dot_path)}")
    elif flow.timeline is not None:
        lines = _timeline_lines(flow.timeline)

for line in lines:
    print(line)

txt_path = os.path.join(args.out, args.e_name + ".txt")
with open(txt_path, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"Wrote {len(lines)} lines to {os.path.abspath(txt_path)}")
