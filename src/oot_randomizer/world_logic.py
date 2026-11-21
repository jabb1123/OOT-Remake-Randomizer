"""World logic: regions, exits, events and locations loaded from TOML.

The logic is either a single TOML file or a directory of them (logic/world/, one file per
area). Directory files are loaded recursively in sorted path order and deep-merged; see
`load_world_data` for the merge rules.

Requirement strings are expressions over item names, events, ages, options and helpers:
    "Hookshot and (Bow or Slingshot)"     "is_adult and Song_of_Time"     "Bombchus:2"
    "has_explosives and can_play(Song_of_Storms)"
`and` binds tighter than `or`. There is no `not`, so reachability only ever grows.

Helpers are named requirements from the top-level `[helpers]` table, e.g.
    has_bombs = "Bomb_Bag and lift_bombs"
    "can_play(song)" = "has_ocarina and song"
and are inlined wherever they are used.
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
# Each dungeon counts its own keys as `Small_Key_<Region>` (e.g. `Small_Key_SpiritTemple:2`) and its
# boss key as `Boss_Key_<Region>`. A generic key actor found in a dungeon's key chest counts toward that dungeon.
KEY_ACTORS = {"Item_Dungeon_SmallKey": "Small_Key_", "Item_Dungeon_BossKey": "Boss_Key_"}
KEY_PREFIXES = tuple(KEY_ACTORS.values())

_RAW_ACTOR = re.compile(r"^(Item|Obj|TBox|Tbox)_\w+$")
_TOKEN = re.compile(r"\s*(?:(\()|(\))|(,)|([A-Za-z_][A-Za-z0-9_]*)(?::(\d+))?)")
_HELPER_KEY = re.compile(r"^\s*([A-Za-z_]\w*)\s*(?:\(\s*([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)?\s*\))?\s*$")
_RESERVED = frozenset({"and", "or", "true", "false", "is_child", "is_adult"})


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
    aliases.update({
        "bombs": "Item_BombBag_Small",
        "hammer": "Item_Hammer",
        "lens": "Item_GlassTruth",
        "sticks": "Item_DekuStickBundle_Small",  # the same Deku Sticks item as Deku_Sticks
    })
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
#            | ("call", helper, [args])  (parsed only; resolving inlines the helper)
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
        elif m.group(3):
            tokens.append((",", "", 0))
        else:
            word = m.group(4)
            if word in ("and", "or") and m.group(5) is None:
                tokens.append((word, "", 0))
            else:
                tokens.append(("name", word, int(m.group(5) or 1)))

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
            if peek() == "(":
                if count != 1:
                    raise LogicError(f"helper call {word!r} cannot take a count in {text!r}")
                i += 1
                args = [parse_or()]
                while peek() == ",":
                    i += 1
                    args.append(parse_or())
                if peek() != ")":
                    raise LogicError(f"missing ')' after arguments to {word!r} in {text!r}")
                i += 1
                return ("call", word, args)
            return ("name", word, count)
        raise LogicError(f"expected a name or '(' in {text!r}")

    if not tokens:
        raise LogicError("empty requirement")
    node = parse_or()
    if i != len(tokens):
        raise LogicError(f"unexpected {tokens[i][0]!r} in {text!r}")
    return node


@dataclass(frozen=True)
class Helper:
    """A named requirement from `[helpers]`; `params` are its argument names."""
    name: str
    params: tuple[str, ...]
    body: Node


def _resolve(node: Node, events: set[str], errors: list[str], where: str,
             helpers: dict[str, Helper] | None = None, env: dict[str, Node] | None = None,
             stack: tuple[str, ...] = ()) -> Node:
    helpers = helpers or {}
    kind = node[0]
    if kind in ("and", "or"):
        return (kind, [_resolve(n, events, errors, where, helpers, env, stack) for n in node[1]])
    if kind == "call":
        _, name, args = node
        helper = helpers.get(name)
        if helper is None:
            errors.append(f"{where}: unknown helper {name!r}")
            return ("const", False)
        if len(args) != len(helper.params):
            errors.append(f"{where}: helper {name!r} takes {len(helper.params)} argument(s), got {len(args)}")
            return ("const", False)
        resolved = [_resolve(a, events, errors, where, helpers, env, stack) for a in args]
        return _expand(helper, resolved, events, errors, where, helpers, stack)
    _, word, count = node
    if env and word in env:
        if count != 1:
            errors.append(f"{where}: helper parameter {word!r} cannot take a count")
        return env[word]
    if word in ("true", "false"):
        return ("const", word == "true")
    if word in ("is_child", "is_adult"):
        return ("age", word[3:])
    if word in KNOWN_OPTIONS:
        return ("option", word)
    if word in events:
        return ("event", word)
    if word in helpers:
        helper = helpers[word]
        if helper.params:
            errors.append(f"{where}: helper {word!r} needs {len(helper.params)} argument(s)")
            return ("const", False)
        if count != 1:
            errors.append(f"{where}: helper {word!r} cannot take a count")
        return _expand(helper, [], events, errors, where, helpers, stack)
    if word.startswith(KEY_PREFIXES):
        return ("item", word, count)  # dungeon key counter; validated in load_world
    actor = resolve_item(word)
    if actor is not None:
        return ("item", actor, count)
    errors.append(f"{where}: unknown name {word!r}")
    return ("const", False)


def _expand(helper: Helper, args: list[Node], events: set[str], errors: list[str], where: str,
            helpers: dict[str, Helper], stack: tuple[str, ...]) -> Node:
    if helper.name in stack:  # only reachable through a cycle, which loading already reports
        return ("const", False)
    # Errors inside the body are reported once, when the helper itself is checked at load time.
    return _resolve(helper.body, events, [], where, helpers, dict(zip(helper.params, args)), (*stack, helper.name))


def _helper_refs(node: Node, helper: Helper, helpers: dict[str, Helper]) -> set[str]:
    if node[0] in ("and", "or"):
        return set().union(*(_helper_refs(n, helper, helpers) for n in node[1]))
    if node[0] == "call":
        found = {node[1]} if node[1] in helpers else set()
        return found.union(*(_helper_refs(a, helper, helpers) for a in node[2]))
    word = node[1]
    return {word} if word in helpers and word not in helper.params else set()


def _helper_cycles(helpers: dict[str, Helper]) -> list[list[str]]:
    refs = {name: _helper_refs(h.body, h, helpers) for name, h in helpers.items()}
    cycles: list[list[str]] = []
    state: dict[str, int] = {}  # 1 = visiting, 2 = done

    def visit(name: str, path: list[str]) -> None:
        state[name] = 1
        for nxt in sorted(refs[name]):
            if state.get(nxt) == 1:
                cycles.append(path[path.index(nxt):] + [nxt])
            elif nxt not in state:
                visit(nxt, path + [nxt])
        state[name] = 2

    for name in helpers:
        if name not in state:
            visit(name, [name])
    return cycles


def _compile_helpers(raw: dict, events: set[str], errors: list[str]) -> dict[str, Helper]:
    helpers: dict[str, Helper] = {}
    for key, text in raw.items():
        where = f"helpers.{key}"
        m = _HELPER_KEY.match(key)
        if not m:
            errors.append(f"{where}: name must look like `name` or `name(param, ...)`")
            continue
        name = m.group(1)
        params = tuple(p.strip() for p in m.group(2).split(",")) if m.group(2) else ()
        if name in helpers:
            errors.append(f"{where}: helper {name!r} is defined twice")
            continue
        if name in _RESERVED or name in KNOWN_OPTIONS or name in events or resolve_item(name) is not None:
            errors.append(f"{where}: {name!r} is already an item, event, option or keyword")
            continue
        if len(set(params)) != len(params):
            errors.append(f"{where}: repeated parameter name")
            continue
        if not isinstance(text, str):
            errors.append(f"{where}: requirement must be a string")
            continue
        try:
            body = parse_requirement(text)
        except LogicError as exc:
            errors.append(f"{where}: {exc}")
            continue
        helpers[name] = Helper(name, params, body)
    cycles = _helper_cycles(helpers)
    for cycle in cycles:
        errors.append(f"helpers.{cycle[0]}: helpers use each other in a loop ({' -> '.join(cycle)})")
    if cycles:
        return {}
    # Check every body once (parameters stand in as `true`).
    for helper in helpers.values():
        env = {p: ("const", True) for p in helper.params}
        _resolve(helper.body, events, errors, f"helpers.{helper.name}", helpers, env, (helper.name,))
    return helpers


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
    dungeon_name: str = ""  # counter name for the dungeon's keys (`dungeon = "Name"` groups rooms under one)
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
    helpers: dict[str, Helper] = field(default_factory=dict)
    # Top-level `[exits]`: targets reachable from any region once their requirement holds.
    global_exits: dict[str, Node] = field(default_factory=dict)
    # Key chests (`... (Item_Dungeon_SmallKey)` / `... (Item_Dungeon_BossKey)`) mapped to their dungeon's
    # counter. Counted even when the planner has not placed them, since keys are not shuffled yet.
    key_locations: dict[str, str] = field(default_factory=dict)

    @property
    def referenced_items(self) -> set[str]:
        found = _items_in(self.goal)
        for region in self.regions.values():
            for req in (*region.exits.values(), *region.locations.values(), *region.events.values()):
                found |= _items_in(req)
        for req in self.global_exits.values():
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
                node = _resolve(parse_requirement(req), events, errors, f"extra requirement for {loc}", self.helpers)
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

    def _item_at(self, loc: str, placements: dict[str, str]) -> str | None:
        """The item a reached location grants. Unplaced key chests grant their own dungeon's key."""
        item = placements.get(loc, self.key_locations.get(loc))
        if item in KEY_ACTORS:
            item = self.key_locations.get(loc, item)
        return item

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
                            item = self._item_at(loc, placements)
                            if item:
                                items[item] += 1
                            changed = True
                    for target, req in (*region.exits.items(), *self.global_exits.items()):
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
            names = ", ".join(sorted(missing))
            self.warnings.append(f"{len(missing)} locations not listed in any region (treated as always reachable): {names}")


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
      * `[helpers]` may be split across files; the same helper name in two files is an error.
      * Top-level `[exits]` (reachable from any region) may be split across files; the same
        target in two files is an error.
      * Per region, the `exits` / `locations` / `events` / `skulltulas` tables are merged;
        the same key in two files is an error naming both files.
      * Scalar region flags (`dungeon`, `excluded`) may repeat but must agree.
    """
    path = Path(path)
    root = path if path.is_dir() else None

    def show(file: Path) -> str:
        return file.relative_to(root).as_posix() if root else str(file)

    merged: dict = {"regions": {}, "helpers": {}, "exits": {}}
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
            elif top == "exits":
                if not isinstance(value, dict):
                    raise LogicError(f"{show(file)}: top-level 'exits' must be a table")
                for target, req in value.items():
                    prev = origin.get(("exits", target))
                    if prev is not None:
                        raise LogicError(f"exits.{target!r} is defined in both {show(prev)} and {show(file)}")
                    origin[("exits", target)] = file
                    merged["exits"][target] = req
            elif top == "helpers":
                if not isinstance(value, dict):
                    raise LogicError(f"{show(file)}: 'helpers' must be a table")
                for key, req in value.items():
                    name = key.split("(", 1)[0].strip()
                    prev = origin.get(("helpers", name))
                    if prev is not None:
                        raise LogicError(f"helper {name!r} is defined in both {show(prev)} and {show(file)}")
                    origin[("helpers", name)] = file
                    merged["helpers"][key] = req
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
    helpers = _compile_helpers(data.get("helpers", {}), event_names, errors)

    def compile_req(text: object, where: str) -> Node:
        if not isinstance(text, str):
            errors.append(f"{where}: requirement must be a string")
            return ("const", False)
        try:
            return _resolve(parse_requirement(text), event_names, errors, where, helpers)
        except LogicError as exc:
            errors.append(f"{where}: {exc}")
            return ("const", False)

    regions: dict[str, Region] = {}
    location_region: dict[str, str] = {}
    token_locations: set[str] = set()
    key_locations: dict[str, str] = {}
    for rname, raw in raw_regions.items():
        raw_dungeon = raw.get("dungeon", False)
        is_dungeon = bool(raw_dungeon)
        dungeon_name = raw_dungeon if isinstance(raw_dungeon, str) else rname
        region = Region(rname, dungeon=is_dungeon, dungeon_name=dungeon_name if is_dungeon else "",
                        excluded=bool(raw.get("excluded", False)))
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
    global_exits: dict[str, Node] = {}
    for target, req in data.get("exits", {}).items():
        if target not in regions:
            errors.append(f"exits: exit to undefined region {target!r}")
        global_exits[target] = compile_req(req, f"exits.{target}")

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

    for rname, region in regions.items():
        for loc in region.locations:
            for actor, prefix in KEY_ACTORS.items():
                if loc.endswith(f"({actor})"):
                    key_locations[loc] = prefix + (region.dungeon_name or rname)

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
        helpers=helpers,
        global_exits=global_exits,
        key_locations=key_locations,
    )

    dungeon_names = {r.dungeon_name for r in regions.values() if r.dungeon}
    for item in sorted(world.referenced_items):
        prefix = next((p for p in KEY_PREFIXES if item.startswith(p)), None)
        if prefix and item[len(prefix):] not in dungeon_names:
            errors.append(f"{item}: dungeon keys are counted per dungeon; {item[len(prefix):]!r} is not a dungeon")

    linked = {spawn for spawn in spawns.values()} | {t for r in regions.values() for t in r.exits} | set(global_exits)
    for rname in regions:
        if rname not in linked:
            warnings.append(f"region {rname!r} has no exit leading to it")
    return world
