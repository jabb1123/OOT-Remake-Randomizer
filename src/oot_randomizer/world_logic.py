"""World logic: regions, exits, events and locations loaded from TOML.

The logic is either a single TOML file or a directory of them (logic/world/, one file per
area). Directory files are loaded recursively in sorted path order and deep-merged; see
`load_world_data` for the merge rules.

Requirement strings are expressions over item names, events, ages and options:
    "Hookshot and (Bow or Slingshot)"     "is_adult and Song_of_Time"     "Bombchus:2"
`and` binds tighter than `or`. There is no `not`, so reachability only ever grows.
"""

from __future__ import annotations

import re
import tomllib
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

from .event_items import EVENT_ITEM_DISPLAY_NAMES
from .item_ids import ITEM_ACTOR_BY_DISPLAY, ITEM_ACTOR_NAMES
from .npc_grants import NPC_ITEM_DISPLAY_NAMES
from .skulltula_rewards import TOKEN_ITEM
from .songs import SONG_DISPLAY_NAMES

TOTAL_TOKENS = 100
DEFAULT_WORLD_PATH = Path(__file__).resolve().parents[2] / "logic" / "world"
# Where `logic template` writes its single-file starter logic by default.
DEFAULT_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "logic" / "world_template.toml"
REGION_TABLES = ("exits", "locations", "events", "skulltulas")
AGES = ("child", "adult")
# Identifiers that read randomizer settings instead of items.
KNOWN_OPTIONS = frozenset({"bombchus_in_logic"})

_RAW_ACTOR = re.compile(r"^(Item|Obj|TBox|Tbox)_\w+$")
_TOKEN = re.compile(r"\s*(?:(\()|(\))|([A-Za-z_][A-Za-z0-9_]*)(?::(\d+))?)")


class LogicError(ValueError):
    pass


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _build_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for actor in ITEM_ACTOR_NAMES | set(SONG_DISPLAY_NAMES) | set(EVENT_ITEM_DISPLAY_NAMES) | set(NPC_ITEM_DISPLAY_NAMES):
        aliases[_norm(actor)] = actor
    for display, actor in ITEM_ACTOR_BY_DISPLAY.items():
        aliases[_norm(display)] = actor
    for actor, display in SONG_DISPLAY_NAMES.items():
        aliases[_norm(display)] = actor
    for actor, display in EVENT_ITEM_DISPLAY_NAMES.items():
        aliases[_norm(display)] = actor
    for actor, display in NPC_ITEM_DISPLAY_NAMES.items():
        aliases[_norm(display)] = actor
    aliases.update({"bombs": "Item_BombBag_Small", "hammer": "Item_Hammer", "lens": "Item_GlassTruth"})
    return aliases


ITEM_ALIASES = _build_aliases()


def resolve_item(name: str) -> str | None:
    """Map a friendly or actor item name to its actor name."""
    actor = ITEM_ALIASES.get(_norm(name))
    if actor is None and _RAW_ACTOR.match(name):
        return name
    return actor


# ---------------------------------------------------------------------------
# Requirement expressions
# ---------------------------------------------------------------------------

# AST nodes: ("const", bool) | ("name", text, count) | ("item", actor, count) | ("event", name)
#            | ("age", age) | ("option", name) | ("and", [nodes]) | ("or", [nodes])
Node = tuple


def parse_requirement(text: str) -> Node:
    tokens: list[tuple[str, str, int]] = []
    pos = 0
    text = text.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise LogicError(f"unexpected character at {pos} in {text!r}")
        pos = m.end()
        if m.group(1):
            tokens.append(("(", "", 0))
        elif m.group(2):
            tokens.append((")", "", 0))
        else:
            word = m.group(3)
            if word in ("and", "or") and m.group(4) is None:
                tokens.append((word, "", 0))
            else:
                tokens.append(("name", word, int(m.group(4) or 1)))

    i = 0

    def peek() -> str | None:
        return tokens[i][0] if i < len(tokens) else None

    def parse_or() -> Node:
        nonlocal i
        parts = [parse_and()]
        while peek() == "or":
            i += 1
            parts.append(parse_and())
        return parts[0] if len(parts) == 1 else ("or", parts)

    def parse_and() -> Node:
        nonlocal i
        parts = [parse_atom()]
        while peek() == "and":
            i += 1
            parts.append(parse_atom())
        return parts[0] if len(parts) == 1 else ("and", parts)

    def parse_atom() -> Node:
        nonlocal i
        kind = peek()
        if kind == "(":
            i += 1
            node = parse_or()
            if peek() != ")":
                raise LogicError(f"missing ')' in {text!r}")
            i += 1
            return node
        if kind == "name":
            _, word, count = tokens[i]
            i += 1
            return ("name", word, count)
        raise LogicError(f"expected a name or '(' in {text!r}")

    if not tokens:
        raise LogicError("empty requirement")
    node = parse_or()
    if i != len(tokens):
        raise LogicError(f"unexpected {tokens[i][0]!r} in {text!r}")
    return node


def _resolve(node: Node, events: set[str], errors: list[str], where: str) -> Node:
    kind = node[0]
    if kind in ("and", "or"):
        return (kind, [_resolve(n, events, errors, where) for n in node[1]])
    _, word, count = node
    if word in ("true", "false"):
        return ("const", word == "true")
    if word in ("is_child", "is_adult"):
        return ("age", word[3:])
    if word in KNOWN_OPTIONS:
        return ("option", word)
    if word in events:
        return ("event", word)
    actor = resolve_item(word)
    if actor is not None:
        return ("item", actor, count)
    errors.append(f"{where}: unknown name {word!r}")
    return ("const", False)


def _items_in(node: Node) -> set[str]:
    if node[0] == "item":
        return {node[1]}
    if node[0] in ("and", "or"):
        return set().union(*(_items_in(n) for n in node[1]))
    return set()


def evaluate(node: Node, items: Counter, events: set[str], age: str, options: dict) -> bool:
    kind = node[0]
    if kind == "item":
        return items[node[1]] >= node[2]
    if kind == "and":
        return all(evaluate(n, items, events, age, options) for n in node[1])
    if kind == "or":
        return any(evaluate(n, items, events, age, options) for n in node[1])
    if kind == "event":
        return node[1] in events
    if kind == "age":
        return age == node[1]
    if kind == "option":
        return bool(options.get(node[1]))
    return node[1]  # const


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------

@dataclass
class Region:
    name: str
    exits: dict[str, Node] = field(default_factory=dict)
    locations: dict[str, Node] = field(default_factory=dict)
    events: dict[str, Node] = field(default_factory=dict)
    dungeon: bool = False
    excluded: bool = False  # chests here keep their vanilla item


@dataclass
class SearchResult:
    items: Counter
    events: set[str]
    locations: set[str]
    regions: dict[str, set[str]]

    @property
    def ages(self) -> list[str]:
        return [age for age in AGES if self.regions[age]]


@dataclass
class World:
    regions: dict[str, Region]
    spawns: dict[str, str]
    start_age: str
    time_travel: str | None
    goal: Node
    start_items: Counter
    errors: list[str]
    warnings: list[str]
    location_region: dict[str, str] = field(default_factory=dict)
    # Gold Skulltula locations (from `[regions.X.skulltulas]`); each always holds a token.
    token_locations: set[str] = field(default_factory=set)
    # Per-seed requirements AND-ed onto a location's own rule (e.g. a wallet for a shop price).
    extra_requirements: dict[str, Node] = field(default_factory=dict)

    @property
    def referenced_items(self) -> set[str]:
        found = _items_in(self.goal)
        for region in self.regions.values():
            for req in (*region.exits.values(), *region.locations.values(), *region.events.values()):
                found |= _items_in(req)
        for req in self.extra_requirements.values():
            found |= _items_in(req)
        return found

    def with_requirements(self, extra: dict[str, str | Node]) -> World:
        """A copy of this world with `extra` ({location: requirement}) AND-ed onto locations.

        Requirements are strings in the logic syntax or compiled nodes. The world itself is
        not modified, so one loaded world can serve many seeds.
        """
        events = {name for region in self.regions.values() for name in region.events}
        compiled = dict(self.extra_requirements)
        for loc, req in extra.items():
            if loc not in self.location_region:
                raise LogicError(f"cannot add a requirement to {loc!r}: not listed in any region")
            if isinstance(req, str):
                errors: list[str] = []
                node = _resolve(parse_requirement(req), events, errors, f"extra requirement for {loc}")
                if errors:
                    raise LogicError("; ".join(errors))
            else:
                node = req
            compiled[loc] = ("and", [compiled[loc], node]) if loc in compiled else node
        return replace(self, extra_requirements=compiled)

    @property
    def dungeon_locations(self) -> dict[str, str]:
        return {loc: r for loc, r in self.location_region.items() if self.regions[r].dungeon}

    @property
    def excluded_locations(self) -> set[str]:
        return {loc for loc, r in self.location_region.items() if self.regions[r].excluded}

    def explore(self, placements: dict[str, str], options: dict | None = None,
                extra_items: Counter | None = None) -> SearchResult:
        """Collect everything reachable. Locations not listed in the world count as reachable.

        Likewise, a world that lists no Gold Skulltulas counts every token as owned.
        """
        options = options or {}
        items = Counter(self.start_items)
        if extra_items:
            items.update(extra_items)
        if not self.token_locations:
            items[TOKEN_ITEM] += TOTAL_TOKENS
        reached: set[str] = set()
        for loc, item in placements.items():
            if loc not in self.location_region:
                reached.add(loc)
                if item:
                    items[item] += 1
        events: set[str] = set()
        regions: dict[str, set[str]] = {age: set() for age in AGES}
        other_age = "adult" if self.start_age == "child" else "child"

        changed = True
        while changed:
            changed = False
            ages = [self.start_age]
            if self.time_travel and self.time_travel in events:
                ages.append(other_age)
            for age in ages:
                seen = regions[age]
                if not seen:
                    seen.add(self.spawns[age])
                frontier = list(seen)
                while frontier:
                    region = self.regions[frontier.pop()]
                    for name, req in region.events.items():
                        if name not in events and evaluate(req, items, events, age, options):
                            events.add(name)
                            changed = True
                    for loc, req in region.locations.items():
                        extra = self.extra_requirements.get(loc)
                        if loc not in reached and evaluate(req, items, events, age, options) and (
                            extra is None or evaluate(extra, items, events, age, options)
                        ):
                            reached.add(loc)
                            if placements.get(loc):
                                items[placements[loc]] += 1
                            changed = True
                    for target, req in region.exits.items():
                        if target not in seen and evaluate(req, items, events, age, options):
                            seen.add(target)
                            frontier.append(target)
                            changed = True
        return SearchResult(items, events, reached, regions)

    def goal_met(self, result: SearchResult, options: dict | None = None) -> bool:
        return any(evaluate(self.goal, result.items, result.events, age, options or {}) for age in result.ages)

    def check_locations(self, known_locations: set[str]) -> None:
        """Add errors/warnings comparing listed locations against the real ones."""
        for loc in sorted(set(self.location_region) - known_locations - self.token_locations):
            self.errors.append(f"location {loc!r} (in {self.location_region[loc]}) does not exist")
        missing = known_locations - set(self.location_region)
        if missing:
            self.warnings.append(f"{len(missing)} locations not listed in any region (treated as always reachable)")


def logic_files(path: Path) -> list[Path]:
    """The TOML files making up the logic at `path` (a single file or a directory)."""
    path = Path(path)
    if path.is_dir():
        files = sorted(p for p in path.rglob("*.toml") if p.is_file())
        if not files:
            raise LogicError(f"{path}: no .toml files found")
        return files
    return [path]


def load_world_data(path: Path = DEFAULT_WORLD_PATH) -> tuple[dict, list[str]]:
    """Read and deep-merge the raw TOML at `path`. Returns (data, warnings).

    Merge rules for a directory of files:
      * `[settings]` may appear in only one file.
      * Per region, the `exits` / `locations` / `events` / `skulltulas` tables are merged;
        the same key in two files is an error naming both files.
      * Scalar region flags (`dungeon`, `excluded`) may repeat but must agree.
    """
    path = Path(path)
    root = path if path.is_dir() else None

    def show(file: Path) -> str:
        return file.relative_to(root).as_posix() if root else str(file)

    merged: dict = {"regions": {}}
    warnings: list[str] = []
    settings_from: Path | None = None
    origin: dict[tuple, Path] = {}
    for file in logic_files(path):
        try:
            data = tomllib.loads(file.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise LogicError(f"{show(file)}: {exc}") from exc
        for top, value in data.items():
            if top == "settings":
                if settings_from is not None:
                    raise LogicError(f"[settings] is defined in both {show(settings_from)} and {show(file)}")
                settings_from = file
                merged["settings"] = value
            elif top == "regions":
                if not isinstance(value, dict):
                    raise LogicError(f"{show(file)}: 'regions' must be a table")
                for rname, raw in value.items():
                    if not isinstance(raw, dict):
                        raise LogicError(f"{show(file)}: regions.{rname} must be a table")
                    target = merged["regions"].setdefault(rname, {})
                    for key, val in raw.items():
                        if key in REGION_TABLES:
                            if not isinstance(val, dict):
                                raise LogicError(f"{show(file)}: {rname}.{key} must be a table")
                            table = target.setdefault(key, {})
                            for name, req in val.items():
                                prev = origin.get((rname, key, name))
                                if prev is not None:
                                    raise LogicError(
                                        f"{rname}.{key}.{name!r} is defined in both {show(prev)} and {show(file)}"
                                    )
                                origin[(rname, key, name)] = file
                                table[name] = req
                        elif key in target:
                            if target[key] != val:
                                raise LogicError(
                                    f"{rname}.{key} conflicts: {target[key]!r} in {show(origin[(rname, key)])} "
                                    f"but {val!r} in {show(file)}"
                                )
                        else:
                            origin[(rname, key)] = file
                            target[key] = val
            else:
                warnings.append(f"{show(file)}: unknown top-level key {top!r} ignored")
    return merged, warnings


def load_world(path: Path = DEFAULT_WORLD_PATH) -> World:
    """Load the world logic from a single TOML file or a directory of them."""
    data, warnings = load_world_data(path)
    errors: list[str] = []
    settings = data.get("settings", {})
    raw_regions: dict = data.get("regions", {})
    if not raw_regions:
        raise LogicError(f"{path}: no [regions] defined")

    event_names = {name for r in raw_regions.values() for name in r.get("events", {})}
    for name in event_names:
        if resolve_item(name) is not None:
            errors.append(f"event {name!r} has the same name as an item")

    def compile_req(text: object, where: str) -> Node:
        if not isinstance(text, str):
            errors.append(f"{where}: requirement must be a string")
            return ("const", False)
        try:
            return _resolve(parse_requirement(text), event_names, errors, where)
        except LogicError as exc:
            errors.append(f"{where}: {exc}")
            return ("const", False)

    regions: dict[str, Region] = {}
    location_region: dict[str, str] = {}
    token_locations: set[str] = set()
    for rname, raw in raw_regions.items():
        region = Region(rname, dungeon=bool(raw.get("dungeon", False)), excluded=bool(raw.get("excluded", False)))
        for key in ("exits", "locations", "events"):
            table = getattr(region, key)
            for name, req in raw.get(key, {}).items():
                table[name] = compile_req(req, f"{rname}.{key}.{name}")
        for name, req in raw.get("skulltulas", {}).items():
            if name in region.locations:
                errors.append(f"{rname}: {name!r} listed in both locations and skulltulas")
                continue
            region.locations[name] = compile_req(req, f"{rname}.skulltulas.{name}")
            token_locations.add(name)
        for loc in region.locations:
            if loc in location_region:
                errors.append(f"location {loc!r} listed in both {location_region[loc]} and {rname}")
            location_region[loc] = rname
        regions[rname] = region

    for region in regions.values():
        for target in region.exits:
            if target not in regions:
                errors.append(f"{region.name}: exit to undefined region {target!r}")

    start_age = settings.get("start_age", "child")
    if start_age not in AGES:
        errors.append(f"settings.start_age must be one of {AGES}")
        start_age = "child"
    spawns = {"child": settings.get("child_spawn", "Root"), "adult": settings.get("adult_spawn", "Root")}
    for age, spawn in spawns.items():
        if spawn not in regions:
            errors.append(f"settings.{age}_spawn: undefined region {spawn!r}")
    time_travel = settings.get("time_travel")
    if time_travel and time_travel not in event_names:
        errors.append(f"settings.time_travel: undefined event {time_travel!r}")

    start_items: Counter = Counter()
    for name in settings.get("start_items", []):
        actor = resolve_item(name)
        if actor is None:
            errors.append(f"settings.start_items: unknown item {name!r}")
        else:
            start_items[actor] += 1

    world = World(
        regions=regions,
        spawns=spawns,
        start_age=start_age,
        time_travel=time_travel,
        goal=compile_req(settings.get("goal", "true"), "settings.goal"),
        start_items=start_items,
        errors=errors,
        warnings=warnings,
        location_region=location_region,
        token_locations=token_locations,
    )

    linked = {spawn for spawn in spawns.values()} | {t for r in regions.values() for t in r.exits}
    for rname in regions:
        if rname not in linked:
            warnings.append(f"region {rname!r} has no exit leading to it")
    return world
