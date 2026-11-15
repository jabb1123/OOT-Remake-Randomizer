"""Custom shop shelf items: build ``Shop_Rando_<Item>`` actors and put them on shop shelves.

Every shop shelf item is its own actor, placed in a scene bcett with Gyaml ``Shop_<Thing>``
and Dynamic ``{"ShopItemIndex": n}``. Its pack (Pack/Actor/Shop_<Thing>.pack.zs) holds:

* ``Actor/<name>.engine__actor__ActorParam.bgyml`` deriving from Shop_Item_Base, whose
  Components point at the model, animation, pouch content and game parameters;
* a PouchContentParam whose ``PouchActor`` is what the purchase gives;
* a GameParameterTable whose PriceParam holds ``BuyingPrice``/``SellingPrice``;
* the Shop_Item_Base files it needs (AI, physics, blackboard, ...).

``build_shop_actor`` clones a vanilla shop actor (the template) and swaps in another item's
model, animation and pouch content. Besides the pack, a new actor needs one row per RSDB table
(ActorInfo, GameActorInfo, PouchActorInfo, and Tag when the template has tags). RSDB row
tables are lists sorted by ``__RowId`` (plain byte order); the Tag table is a dict of
PathList (prefix, name, suffix triples sorted by full path), TagList, a per-entry tag bit
stream (BitTable) and per-tag cumulative counts per 32 entries (RankTable).

``apply_shop_items`` writes the pack(s), RSDB rows, shelf placements and RESTBL sizes into a NUP.
"""

from __future__ import annotations

import bisect
import copy
import struct
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import zstandard as zstd

from .byml7 import BinaryParam, Byml7, BymlError, dump_byml7, parse_byml7, parse_byml7_typed
from .nup_chest_patcher import (
    NupChestPatcher,
    _decompress,
    _detect_dict_id,
    _extend_string_table,
    _load_dicts_from_sarc,
    _recompress,
)
from .sarc import read_sarc, write_sarc


class ShopError(RuntimeError):
    pass


PACK_DIR = "Pack/Actor/"
ACTOR_PARAM = ".engine__actor__ActorParam"
POUCH_CONTENT = ".game__component__PouchContentParam"
GAME_PARAM_TABLE = ".engine__actor__GameParameterTable"
PRICE_PARAM = ".game__pouchcontent__PriceParam"

DEFAULT_TEMPLATE = "Shop_Mask_Keaton"
NAME_PREFIX = "Shop_Rando_"

# ActorParam components taken from the item's own ActorParam.
ITEM_COMPONENT_REFS = ("ModelInfoRef", "ActorNameRef", "AnimationRef")
# Template components replaced by the item's or by newly written files; every other template
# component (ASInfoRef, ASRef, ActorPositionCalculatorRef, ...) is kept as-is.
REPLACED_COMPONENT_REFS = ITEM_COMPONENT_REFS + ("GameParameterTableRef", "PouchContentRef")

ACTOR_INFO_MODEL_FIELDS = (
    "ActorName", "AnimationResources", "DebugModelScale", "FmdbName", "ModelAabbMax",
    "ModelAabbMin", "ModelProjectName", "ModelVariationFmabFrame", "ModelVariationFmabName",
)
# The item's heaps include its model; using the larger of template/item never under-allocates.
ACTOR_INFO_HEAP_FIELDS = ("InstanceHeapSize", "PreActorRenderInfoHeapSize")
GAME_ACTOR_INFO_MODEL_FIELDS = ("ModelVariationAnims", "HasLightRigBone")

RSDB_KINDS = ("ActorInfo", "GameActorInfo", "PouchActorInfo", "Tag")
TAG_PATH_PREFIX = "Work/Actor/"
TAG_PATH_SUFFIX = ".engine__actor__ActorParam.gyml"
TAG_RANK_BLOCK = 32

# Vanilla RESTBL entries for Pack/Actor/*.pack are align32(decompressed size) + 312.
RESTBL_PACK_OVERHEAD = 312


# ---------------------------------------------------------------------------
# Resource reference helpers
# ---------------------------------------------------------------------------

def shop_actor_name(item_actor: str) -> str:
    return f"{NAME_PREFIX}{item_actor}"


def actor_pack_path(actor: str) -> str:
    return f"{PACK_DIR}{actor}.pack.zs"


def ref_to_pack_path(ref: str) -> str | None:
    """Map a resource reference to the path it has inside a pack / the romfs (without .zs).

    ``?Component/X.bgyml`` -> ``Component/X.bgyml``;
    ``Work/Component/X.gyml`` -> ``Component/X.bgyml``;
    ``Work/AI/Root/X.root.ain`` -> ``AI/X.root.ainb``; other ``Work/`` paths drop the prefix.
    """
    if not isinstance(ref, str):
        return None
    if ref.startswith("?"):
        return ref[1:] or None
    if not ref.startswith("Work/"):
        return None
    rest = ref[len("Work/"):]
    if rest.endswith(".gyml"):
        return rest[:-len(".gyml")] + ".bgyml"
    if rest.endswith(".ain"):
        if rest.startswith("AI/Root/"):
            rest = "AI/" + rest[len("AI/Root/"):]
        return rest + "b"
    return rest


def pack_path_to_work_ref(path: str) -> str:
    """Inverse of ref_to_pack_path for .bgyml files: ``Component/X.bgyml`` -> ``Work/Component/X.gyml``."""
    if not path.endswith(".bgyml"):
        raise ShopError(f"not a .bgyml path: {path!r}")
    return "Work/" + path[:-len(".bgyml")] + ".gyml"


def iter_refs(obj: Any) -> Iterator[str]:
    """Yield every string value that looks like a resource reference (``?...`` or ``Work/...``)."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, str):
            if cur.startswith(("?", "Work/")):
                yield cur
        elif isinstance(cur, Mapping):
            stack.extend(cur.values())
        elif isinstance(cur, (list, tuple)):
            stack.extend(cur)


def _try_parse(data: bytes) -> Any:
    if data[:2] not in (b"YB", b"BY"):
        return None
    try:
        return parse_byml7_typed(data)
    except BymlError:
        return None


def ref_closure(files: Mapping[str, bytes], refs: Iterable[str]) -> set[str]:
    """Pack paths reachable from `refs` through files present in `files`."""
    seen: set[str] = set()
    stack = [p for p in (ref_to_pack_path(r) for r in refs) if p]
    while stack:
        path = stack.pop()
        if path in seen or path not in files:
            continue
        seen.add(path)
        obj = _try_parse(files[path])
        if obj is not None:
            stack.extend(p for p in (ref_to_pack_path(r) for r in iter_refs(obj)) if p)
    return seen


def _actor_component(files: Mapping[str, bytes], ap_path: str, key: str) -> str | None:
    """Component reference of an ActorParam, following $parent within the pack."""
    seen: set[str] = set()
    path: str | None = ap_path
    while path and path in files and path not in seen:
        seen.add(path)
        ap = parse_byml7(files[path])
        value = (ap.get("Components") or {}).get(key)
        if value:
            return value
        path = ref_to_pack_path(ap.get("$parent", ""))
    return None


# ---------------------------------------------------------------------------
# Shop actor pack
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ShopActor:
    name: str
    item_actor: str
    price: int
    template: str
    romfs_path: str                      # Pack/Actor/<name>.pack.zs
    pack: bytes                          # decompressed SARC
    pack_zs: bytes                       # zstd (template's dict id when dicts are given)
    decompressed_size: int
    dict_id: int | None
    files: dict[str, bytes]
    rows: dict[str, dict | None]         # RSDB kind -> row (None: nothing to add)
    shared: list[str] = field(default_factory=list)   # kept from the template
    dropped: list[str] = field(default_factory=list)  # template item-specific files
    copied: list[str] = field(default_factory=list)   # copied from the item pack
    created: list[str] = field(default_factory=list)  # newly written

    @property
    def resource_path(self) -> str:
        """RESTBL path (romfs path without .zs)."""
        return self.romfs_path.removesuffix(".zs")

    @property
    def restbl_size(self) -> int:
        return ((self.decompressed_size + 31) & ~31) + RESTBL_PACK_OVERHEAD


def _check_price(price: int) -> int:
    if isinstance(price, bool) or not isinstance(price, int) or not 0 <= price < (1 << 31):
        raise ShopError(f"invalid price {price!r}")
    return price


def build_shop_actor(read_file: Callable[[str], bytes], item_actor: str, price: int, *,
                     template: str = DEFAULT_TEMPLATE,
                     dicts: Mapping[int, bytes] | None = None,
                     dict_id: int | None = None,
                     read_raw: Callable[[str], bytes] | None = None,
                     rsdb_tables: Mapping[str, bytes] | None = None,
                     rsdb_product: str = "Product.111",
                     name: str | None = None) -> ShopActor:
    """Build the pack and RSDB rows of a shop shelf actor selling `item_actor` for `price`.

    read_file(romfs_path) -> decompressed bytes (e.g. ``Pack/Actor/Item_Hookshot.pack.zs``).
    The pack is compressed with `dicts` (ZsDic.pack dictionaries by id) using `dict_id`, or the
    dict id of the template's compressed pack read via `read_raw`; without `dicts` it is a
    plain zstd frame. RSDB rows come from `rsdb_tables` ({kind: decompressed table}) or from
    ``RSDB/<kind>.<rsdb_product>.rstbl.byml.zs`` via read_file when present.
    """
    _check_price(price)
    name = name or shop_actor_name(item_actor)
    tpl_files = read_sarc(read_file(actor_pack_path(template)))
    item_files = read_sarc(read_file(actor_pack_path(item_actor)))

    tpl_ap_path = f"Actor/{template}{ACTOR_PARAM}.bgyml"
    item_ap_path = f"Actor/{item_actor}{ACTOR_PARAM}.bgyml"
    for files, path, what in ((tpl_files, tpl_ap_path, "template"), (item_files, item_ap_path, "item")):
        if path not in files:
            raise ShopError(f"{what} pack has no {path}")
    tpl_bin = Byml7(tpl_files[tpl_ap_path])
    version, big_endian = tpl_bin.version, not tpl_bin.is_little_endian
    tpl_ap = tpl_bin.parse_typed()
    tpl_parent = tpl_ap.get("$parent")
    base_ap_path = ref_to_pack_path(tpl_parent or "")
    if not base_ap_path or base_ap_path not in tpl_files:
        raise ShopError(f"template {template} ActorParam parent {tpl_parent!r} is not in its pack")
    tpl_comps = dict(tpl_ap.get("Components") or {})

    # --- template: keep the shared files, drop the ones only its item-specific refs reach ---
    kept_refs = [tpl_parent] + [v for k, v in tpl_comps.items() if k not in REPLACED_COMPONENT_REFS]
    specific_refs = [v for k, v in tpl_comps.items() if k in REPLACED_COMPONENT_REFS]
    kept = ref_closure(tpl_files, kept_refs)
    dropped = (ref_closure(tpl_files, specific_refs) - kept) | {tpl_ap_path}
    files = {p: d for p, d in tpl_files.items() if p not in dropped}
    shared = sorted(files)

    # --- item: model / name / animation / pouch content and its game parameters ---
    item_refs: dict[str, str] = {}
    for key in ITEM_COMPONENT_REFS + ("PouchContentRef", "GameParameterTableRef"):
        value = _actor_component(item_files, item_ap_path, key)
        if value:
            item_refs[key] = value
    if "ModelInfoRef" not in item_refs:
        raise ShopError(f"{item_actor} has no ModelInfoRef")
    if "PouchContentRef" not in item_refs:
        raise ShopError(f"{item_actor} has no PouchContentRef")

    item_gpt: dict = {}
    gpt_path = ref_to_pack_path(item_refs.get("GameParameterTableRef", ""))
    if gpt_path and gpt_path in item_files:
        item_gpt = parse_byml7_typed(item_files[gpt_path])
    gpt_components = {k: v for k, v in (item_gpt.get("Components") or {}).items() if k != "PriceParam"}

    copy_refs = [item_refs[k] for k in ITEM_COMPONENT_REFS + ("PouchContentRef",) if k in item_refs]
    copy_refs += list(gpt_components.values())
    if item_gpt.get("$parent"):
        copy_refs.append(item_gpt["$parent"])
    copied = sorted(ref_closure(item_files, copy_refs))
    for path in copied:
        if path in files and files[path] != item_files[path]:
            raise ShopError(f"{path} differs between {template} and {item_actor} packs")
        files[path] = item_files[path]

    # --- new files ---
    pouch_path = f"Component/PouchContentParam/{name}{POUCH_CONTENT}.bgyml"
    gpt_new_path = f"GameParameter/GameParameterTable/{name}{GAME_PARAM_TABLE}.bgyml"
    price_path = f"GameParameter/PriceParam/{name}{PRICE_PARAM}.bgyml"
    ap_path = f"Actor/{name}{ACTOR_PARAM}.bgyml"

    item_pouch_path = ref_to_pack_path(item_refs["PouchContentRef"])
    pouch_parent = (pack_path_to_work_ref(item_pouch_path)
                    if item_pouch_path and item_pouch_path.endswith(".bgyml")
                    else item_refs["PouchContentRef"])
    pouch = {
        "$parent": pouch_parent,
        "IsNotOpenStockNumDisplay": True,
        "PouchActor": f"Work/Actor/{item_actor}{ACTOR_PARAM}.gyml",
    }
    gpt: dict[str, Any] = {}
    if item_gpt.get("$parent"):
        gpt["$parent"] = item_gpt["$parent"]
    gpt["Category"] = item_gpt.get("Category", "GameParameterTableDefault")
    gpt["Components"] = {**gpt_components, "PriceParam": f"?{price_path}"}
    price_param = {"BuyingPrice": int(price), "SellingPrice": 0}

    components = {k: v for k, v in tpl_comps.items() if k not in REPLACED_COMPONENT_REFS}
    for key in ITEM_COMPONENT_REFS:
        if key in item_refs:
            components[key] = item_refs[key]
    components["GameParameterTableRef"] = f"?{gpt_new_path}"
    components["PouchContentRef"] = f"?{pouch_path}"
    actor_param = {"$parent": tpl_parent, "Components": dict(sorted(components.items()))}

    created = {ap_path: actor_param, pouch_path: pouch, gpt_new_path: gpt, price_path: price_param}
    for path, obj in created.items():
        if path in files:
            raise ShopError(f"{path} already exists in the pack")
        files[path] = dump_byml7(obj, big_endian=big_endian, version=version)

    pack = write_sarc(files)
    if dicts is not None:
        if dict_id is None:
            if read_raw is None:
                raise ShopError("need dict_id or read_raw to pick the template's zstd dictionary")
            dict_id = _detect_dict_id(read_raw(actor_pack_path(template)))
        pack_zs = (_recompress(pack, dict(dicts), dict_id) if dict_id is not None
                   else zstd.ZstdCompressor(level=19).compress(pack))
    else:
        dict_id = None
        pack_zs = zstd.ZstdCompressor(level=19).compress(pack)

    if rsdb_tables is None:
        rsdb_tables = {}
        for kind in RSDB_KINDS:
            try:
                rsdb_tables[kind] = read_file(f"RSDB/{kind}.{rsdb_product}.rstbl.byml.zs")
            except (KeyError, FileNotFoundError):
                pass
    rows = build_rsdb_rows(rsdb_tables, template, item_actor, name, price) if rsdb_tables else {}

    return ShopActor(
        name=name, item_actor=item_actor, price=price, template=template,
        romfs_path=actor_pack_path(name), pack=pack, pack_zs=pack_zs,
        decompressed_size=len(pack), dict_id=dict_id, files=files, rows=rows,
        shared=shared, dropped=sorted(dropped), copied=copied, created=sorted(created),
    )


# ---------------------------------------------------------------------------
# RSDB tables
# ---------------------------------------------------------------------------

def _row_ids(rows: Sequence[Mapping]) -> list[bytes]:
    return [str(r.get("__RowId", "")).encode("utf-8") for r in rows]


def find_rsdb_row(table: Any, row_id: str) -> dict | None:
    """Row with `row_id` from a parsed row table (list of dicts)."""
    for row in table:
        if isinstance(row, Mapping) and row.get("__RowId") == row_id:
            return row
    return None


def _is_tag_table(root: Any) -> bool:
    return isinstance(root, Mapping) and {"PathList", "TagList", "BitTable", "RankTable"} <= set(root)


def _tag_entries(root: Mapping) -> tuple[list[tuple[str, str, str]], list[str], list[set[int]]]:
    path_list, tags, bits = list(root["PathList"]), list(root["TagList"]), bytes(root["BitTable"])
    if len(path_list) % 3:
        raise ShopError("Tag PathList length is not a multiple of 3")
    n, t = len(path_list) // 3, len(tags)
    if len(bits) < (n * t + 7) // 8:
        raise ShopError("Tag BitTable too short")
    entries = [tuple(path_list[3 * i:3 * i + 3]) for i in range(n)]
    sets = [{j for j in range(t) if (bits[(i * t + j) >> 3] >> ((i * t + j) & 7)) & 1}
            for i in range(n)]
    return entries, tags, sets


def encode_tag_tables(entry_tags: Sequence[set[int]], tag_count: int) -> tuple[bytes, bytes]:
    """(BitTable, RankTable) for per-entry tag index sets.

    BitTable: tag_count bits per entry, one LSB-first bit stream. RankTable: u32 per
    (tag, 32-entry block), tag-major, counting entries with that tag in [0, end of block).
    """
    n = len(entry_tags)
    bits = bytearray((n * tag_count + 7) // 8)
    for i, tags in enumerate(entry_tags):
        for j in tags:
            k = i * tag_count + j
            bits[k >> 3] |= 1 << (k & 7)
    blocks = (n + TAG_RANK_BLOCK - 1) // TAG_RANK_BLOCK
    ranks = []
    for j in range(tag_count):
        count = 0
        for b in range(blocks):
            count += sum(1 for i in range(b * TAG_RANK_BLOCK, min(n, (b + 1) * TAG_RANK_BLOCK))
                         if j in entry_tags[i])
            ranks.append(count)
    return bytes(bits), struct.pack(f"<{len(ranks)}I", *ranks)


def tag_names(table: Any, actor: str, prefix: str = TAG_PATH_PREFIX,
              suffix: str = TAG_PATH_SUFFIX) -> list[str]:
    """Tags of `actor` in a Tag table (raw bytes or parsed); [] when it has no entry."""
    root = parse_byml7_typed(table) if isinstance(table, (bytes, bytearray)) else table
    entries, tags, sets = _tag_entries(root)
    try:
        i = entries.index((prefix, actor, suffix))
    except ValueError:
        return []
    return [tags[j] for j in sorted(sets[i])]


def _add_tag_rows(root: dict, rows: Iterable[Mapping]) -> None:
    entries, tags, sets = _tag_entries(root)
    tag_index = {t: j for j, t in enumerate(tags)}
    changed = False
    for row in rows:
        name = row["__RowId"]
        key = (row.get("PathPrefix", TAG_PATH_PREFIX), name, row.get("PathSuffix", TAG_PATH_SUFFIX))
        wanted = list(row.get("Tags") or [])
        unknown = [t for t in wanted if t not in tag_index]
        if unknown:
            raise ShopError(f"unknown tags for {name}: {unknown} (TagList/TagDef would need them)")
        new_set = {tag_index[t] for t in wanted}
        if key in entries:
            i = entries.index(key)
            if new_set:
                sets[i] = new_set
            else:
                del entries[i], sets[i]
            changed = True
        elif new_set:
            full = [("".join(e)).encode("utf-8") for e in entries]
            if full != sorted(full):
                raise ShopError("Tag PathList is not sorted; refusing to insert")
            i = bisect.bisect_left(full, "".join(key).encode("utf-8"))
            entries.insert(i, key)
            sets.insert(i, new_set)
            changed = True
    if not changed:
        return
    bit_table, rank_table = encode_tag_tables(sets, len(tags))
    old_bt, old_rt = root["BitTable"], root["RankTable"]
    root["PathList"] = [s for e in entries for s in e]
    root["BitTable"] = BinaryParam(bit_table, old_bt.param) if isinstance(old_bt, BinaryParam) else bit_table
    root["RankTable"] = BinaryParam(rank_table, old_rt.param) if isinstance(old_rt, BinaryParam) else rank_table


def add_rsdb_rows(table_bytes: bytes, rows: Iterable[Mapping | None]) -> bytes:
    """Insert (or replace, by ``__RowId``) rows in an RSDB table, keeping the existing order.

    Row tables (list of dicts sorted by __RowId) get each new row at its sorted position
    (appended if the table is not sorted). Tag tables take rows like
    ``{"__RowId": actor, "Tags": [...]}``; rows without tags add nothing (vanilla omits
    untagged actors). Returns the table unchanged when there is nothing to add.
    """
    rows = [r for r in rows if r is not None]
    if not rows:
        return bytes(table_bytes)
    reader = Byml7(table_bytes)
    root = reader.parse_typed()
    for r in rows:
        if not isinstance(r.get("__RowId"), str) or not r["__RowId"]:
            raise ShopError(f"row without __RowId: {r!r}")
    if _is_tag_table(root):
        before = copy.deepcopy(root)
        _add_tag_rows(root, rows)
        if root == before:
            return bytes(table_bytes)
    elif isinstance(root, list):
        ids = _row_ids(root)
        is_sorted = ids == sorted(ids)
        for r in rows:
            row = copy.deepcopy(dict(r))
            rid = row["__RowId"].encode("utf-8")
            if rid in ids:
                root[ids.index(rid)] = row
                continue
            i = bisect.bisect_left(ids, rid) if is_sorted else len(ids)
            root.insert(i, row)
            ids.insert(i, rid)
    else:
        raise ShopError("unsupported RSDB table layout")
    return dump_byml7(root, big_endian=not reader.is_little_endian, version=reader.version)


def build_rsdb_rows(tables: Mapping[str, bytes | Any], template: str, item_actor: str,
                    name: str, price: int) -> dict[str, dict | None]:
    """RSDB rows for a new shop actor from {kind: table (bytes or parsed)}; kinds may be missing.

    ActorInfo: template row + the item's model fields (and the larger heap sizes);
    GameActorInfo: template row + the item's ModelVariationAnims; PouchActorInfo: item row
    with BuyingPrice=price and IsNotOpenStockNumDisplay; Tag: the template's tags.
    """
    _check_price(price)

    def parsed(kind: str) -> Any:
        t = tables[kind]
        return parse_byml7_typed(t) if isinstance(t, (bytes, bytearray)) else t

    def need(table: Any, kind: str, rid: str) -> dict:
        row = find_rsdb_row(table, rid)
        if row is None:
            raise ShopError(f"{kind} has no row {rid!r}")
        return row

    out: dict[str, dict | None] = {}
    if "ActorInfo" in tables:
        t = parsed("ActorInfo")
        tpl, item = need(t, "ActorInfo", template), need(t, "ActorInfo", item_actor)
        row = copy.deepcopy(dict(tpl))
        for f in ACTOR_INFO_MODEL_FIELDS:
            if f in item:
                row[f] = copy.deepcopy(item[f])
            else:
                row.pop(f, None)
        for f in ACTOR_INFO_HEAP_FIELDS:
            if f in tpl and f in item:
                row[f] = type(tpl[f])(max(int(tpl[f]), int(item[f])))
        row["__RowId"] = name
        out["ActorInfo"] = dict(sorted(row.items()))
    if "GameActorInfo" in tables:
        t = parsed("GameActorInfo")
        tpl, item = need(t, "GameActorInfo", template), need(t, "GameActorInfo", item_actor)
        row = copy.deepcopy(dict(tpl))
        for f in GAME_ACTOR_INFO_MODEL_FIELDS:
            if f in item:
                row[f] = copy.deepcopy(item[f])
            else:
                row.pop(f, None)
        row["__RowId"] = name
        out["GameActorInfo"] = dict(sorted(row.items()))
    if "PouchActorInfo" in tables:
        t = parsed("PouchActorInfo")
        need(t, "PouchActorInfo", template)
        row = copy.deepcopy(dict(need(t, "PouchActorInfo", item_actor)))
        row["BuyingPrice"] = int(price)
        row["IsNotOpenStockNumDisplay"] = True
        row["__RowId"] = name
        out["PouchActorInfo"] = dict(sorted(row.items()))
    if "Tag" in tables:
        tags = tag_names(parsed("Tag"), template)
        out["Tag"] = {"__RowId": name, "Tags": tags} if tags else None
    return out


# ---------------------------------------------------------------------------
# Shelf placements (bcett)
# ---------------------------------------------------------------------------

Selector = int | Mapping[str, Any] | Callable[[Mapping[str, Any], int], bool]


def _bcett_actor_tables(buf: bytes):
    """(value string table, key lookup(hash_off, key) -> (type, value_off) or None,
    per Actors[i] hash offset or None). Walks the BYML in place without re-serializing.
    """
    if buf[:2] != b"YB":
        raise ShopError(f"expected a little-endian BYML (YB), got {bytes(buf[:2])!r}")
    hk_off, st_off, root_off = struct.unpack_from("<III", buf, 4)

    def u24(o: int) -> int:
        return int.from_bytes(buf[o:o + 3], "little")

    def str_table(off: int) -> list[str]:
        if off == 0:
            return []
        out = []
        for i in range(u24(off + 1)):
            start = off + struct.unpack_from("<I", buf, off + 4 + 4 * i)[0]
            out.append(bytes(buf[start:buf.index(b"\x00", start)]).decode("utf-8", "surrogateescape"))
        return out

    keys, strings = str_table(hk_off), str_table(st_off)

    def lookup(hash_off: int, key: str) -> tuple[int, int] | None:
        if key not in keys or buf[hash_off] != 0xC1:
            return None
        want = keys.index(key)
        for i in range(u24(hash_off + 1)):
            e = hash_off + 4 + 8 * i
            if u24(e) == want:
                return buf[e + 3], e + 4
        return None

    found = lookup(root_off, "Actors")
    if found is None or found[0] != 0xC0:
        raise ShopError("bcett has no Actors array")
    arr = struct.unpack_from("<I", buf, found[1])[0]
    count = u24(arr + 1)
    slots_base = (arr + 4 + count + 3) & ~3
    actors: list[int | None] = []
    for i in range(count):
        hash_off = None
        if buf[arr + 4 + i] == 0xC1:
            hash_off = struct.unpack_from("<I", buf, slots_base + 4 * i)[0]
        actors.append(hash_off)
    return strings, lookup, actors


def _actor_gyaml_slots(buf: bytes) -> tuple[list[str], list[int | None]]:
    """(value string table, per Actors[i] byte offset of its Gyaml string index or None)."""
    strings, lookup, actors = _bcett_actor_tables(buf)
    slots: list[int | None] = []
    for hash_off in actors:
        slot = None
        if hash_off is not None:
            g = lookup(hash_off, "Gyaml")
            if g is not None and g[0] == 0xA0:
                slot = g[1]
        slots.append(slot)
    return strings, slots


def _actor_matches(actor: Mapping[str, Any], index: int, selector: Selector) -> bool:
    if callable(selector):
        return bool(selector(actor, index))
    dynamic = actor.get("Dynamic") or {}
    for key, want in selector.items():
        if key in actor:
            have = actor[key]
        elif key in dynamic:
            have = dynamic[key]
        else:
            return False
        if have != want:
            return False
    return True


def find_shelf_actors(bcett_bytes: bytes, selector: Selector) -> list[int]:
    """Indices into Actors of the shop actors matched by `selector`.

    selector: an Actors index; a mapping of field -> value where fields are looked up on
    the actor first and then in its Dynamic (e.g. {"Gyaml": "Shop_DekuSeedBundle_02",
    "ShopItemIndex": 1}); or a callable(actor_dict, index) -> bool. Only actors whose Gyaml
    starts with "Shop_" (and is not a Shop_Board_ price board) can match.
    """
    actors = parse_byml7(bcett_bytes).get("Actors") or []

    def is_shelf(a: Any) -> bool:
        g = a.get("Gyaml", "") if isinstance(a, Mapping) else ""
        return g.startswith("Shop_") and not g.startswith("Shop_Board_")

    if isinstance(selector, int) and not isinstance(selector, bool):
        if not 0 <= selector < len(actors):
            raise ShopError(f"actor index {selector} out of range (0..{len(actors) - 1})")
        if not is_shelf(actors[selector]):
            raise ShopError(f"actor {selector} ({actors[selector].get('Gyaml')!r}) is not a shop shelf item")
        return [selector]
    return [i for i, a in enumerate(actors) if is_shelf(a) and _actor_matches(a, i, selector)]


def set_shelf_item(bcett_bytes: bytes, actor_index_or_match: Selector, new_gyaml: str, *,
                   allow_multiple: bool = False, changed: list[int] | None = None) -> bytes:
    """Change the Gyaml of the shop actor(s) chosen by `actor_index_or_match` to `new_gyaml`.

    Only the actor's Gyaml string index changes; when `new_gyaml` is not yet in the value
    string table, an extended copy of the table is appended (existing indices stay valid).
    Exactly one actor must match unless allow_multiple. Indices of changed actors are
    appended to `changed` when given.
    """
    indices = find_shelf_actors(bcett_bytes, actor_index_or_match)
    if not indices:
        raise ShopError(f"no shop actor matches {actor_index_or_match!r}")
    if len(indices) > 1 and not allow_multiple:
        raise ShopError(f"{len(indices)} shop actors match {actor_index_or_match!r} "
                        f"(indices {indices}); pass allow_multiple=True or an index")
    return set_actor_gyaml(bcett_bytes, indices, new_gyaml, changed=changed)


def set_actor_gyaml(bcett_bytes: bytes, indices: Sequence[int], new_gyaml: str, *,
                    changed: list[int] | None = None) -> bytes:
    """Set the Gyaml of the Actors[i] entries in `indices` to `new_gyaml` (no name checks)."""
    buf = bytearray(bcett_bytes)
    strings, slots = _actor_gyaml_slots(buf)
    if new_gyaml not in strings:
        strings = _extend_string_table(buf, strings, [new_gyaml])
    idx = strings.index(new_gyaml)
    for i in indices:
        if slots[i] is None:
            raise ShopError(f"actor {i} has no Gyaml string")
        struct.pack_into("<I", buf, slots[i], idx)
    if changed is not None:
        changed.extend(indices)
    return bytes(buf)


def _append_f32_array(buf: bytearray, values: Sequence[float]) -> int:
    """Append a float32 BYML array to `buf` (4-byte aligned); returns its offset."""
    buf.extend(b"\x00" * (-len(buf) % 4))
    off = len(buf)
    buf.extend(bytes([0xC0]) + len(values).to_bytes(3, "little"))
    buf.extend(bytes([0xD2]) * len(values))
    buf.extend(b"\x00" * (-len(buf) % 4))
    buf.extend(struct.pack(f"<{len(values)}f", *values))
    return off


def shift_actor_y(bcett_bytes: bytes, indices: Sequence[int], dy: float) -> bytes:
    """Add `dy` to the Y position (Translate[1]) of the Actors[i] entries in `indices`.

    BYML writers share identical containers, so an actor's Translate array may be used by
    other actors too. Each lifted actor therefore gets a fresh copy of its array (appended to
    the buffer) and only its own Translate pointer is repointed.
    """
    buf = bytearray(bcett_bytes)
    _, lookup, actors = _bcett_actor_tables(buf)
    for i in indices:
        if not 0 <= i < len(actors):
            raise ShopError(f"actor index {i} out of range")
        found = lookup(actors[i], "Translate") if actors[i] is not None else None
        if found is None or found[0] != 0xC0:
            raise ShopError(f"actor {i} has no Translate array")
        arr = struct.unpack_from("<I", buf, found[1])[0]
        count = int.from_bytes(buf[arr + 1 : arr + 4], "little")
        if count < 2 or any(buf[arr + 4 + k] != 0xD2 for k in range(count)):
            raise ShopError(f"actor {i} Translate is not a float array")
        base = (arr + 4 + count + 3) & ~3
        values = list(struct.unpack_from(f"<{count}f", buf, base))
        values[1] += dy
        struct.pack_into("<I", buf, found[1], _append_f32_array(buf, values))
    return bytes(buf)


# Shop/heart items that are regular shop stock (vanilla shelves sell these) keep their height.
# Any other item (gauntlets, boots, masks, medals, swords, ...) is lifted by ITEM_LIFT_Y so its
# model sits on the shelf or floor instead of half-sunk into it.
REGULAR_SHOP_ITEMS: frozenset[str] = frozenset(
    {
        "Item_Arrow_Normal",
        "Item_Bomb",
        "Item_BombBundle_Small",
        "Item_Bombchu",
        "Item_BombchuBundle_Small",
        "Item_BombchuBundle_Medium",
        "Item_BombchuBundle_Large",
        "Item_DekuNut",
        "Item_DekuSeed",
        "Item_DekuStick",
        "Item_DekuStickBundle_Small",
    }
)
REGULAR_SHOP_ITEM_PREFIXES: tuple[str, ...] = ("Item_Bottle",)
ITEM_LIFT_Y = 0.3


def needs_lift(item: str) -> bool:
    """True when `item` is placed higher than regular shop stock (see ITEM_LIFT_Y)."""
    return item not in REGULAR_SHOP_ITEMS and not item.startswith(
        REGULAR_SHOP_ITEM_PREFIXES
    )


def place_shelf_actor(
    data: bytes,
    shelf: "Shelf",
    new_name: str,
    set_actor: Callable[..., bytes],
    *,
    lift: bool,
    changed: list[int] | None = None,
) -> bytes:
    """Run `set_actor` for one shelf edit, then lift the placed actors when `lift` is set."""
    placed: list[int] = []
    data = set_actor(
        data,
        shelf.select,
        new_name,
        allow_multiple=shelf.allow_multiple,
        changed=placed,
    )
    if lift and placed:
        data = shift_actor_y(data, placed, ITEM_LIFT_Y)
    if changed is not None:
        changed.extend(placed)
    return data


@dataclass(frozen=True, slots=True)
class Shelf:
    """A shelf placement: bcett file (name or romfs path), selector, allow_multiple."""
    scene: str
    select: Selector
    allow_multiple: bool = False

    @property
    def filename(self) -> str:
        return self.scene.replace("\\", "/").rsplit("/", 1)[-1]


def _as_shelves(sel: Any) -> list[Shelf]:
    if isinstance(sel, Shelf):
        return [sel]
    if isinstance(sel, tuple) and sel and isinstance(sel[0], str):
        return [Shelf(*sel)]
    if isinstance(sel, list):
        return [s for x in sel for s in _as_shelves(x)]
    raise ShopError(f"invalid shelf selector {sel!r}; use Shelf(scene, select[, allow_multiple])")


@dataclass(slots=True)
class ShopApplyResult:
    package_index: int
    package_reason: str
    actors: list[ShopActor]
    added_files: list[str] = field(default_factory=list)
    replaced_packs: list[str] = field(default_factory=list)
    rsdb_tables: dict[str, int] = field(default_factory=dict)      # filename -> extents written
    scenes: dict[str, list[list[int]]] = field(default_factory=dict)  # filename -> changed actors per copy
    restbl_tables_written: int = 0
    restbl_entries_grown: int = 0


def _resolve(r: Any, romfs_dir: int, path: str) -> int | None:
    from nup.access import find_child
    cur = romfs_dir
    ref = None
    for part in path.split("/"):
        ref = find_child(r, cur, part.encode("utf-8"))
        if ref is None:
            return None
        cur = ref.index
    return None if ref is None or ref.is_dir else ref.index


def _resolve_dir(r: Any, romfs_dir: int, path: str) -> int | None:
    from nup.access import find_child
    cur = romfs_dir
    for part in path.split("/"):
        ref = find_child(r, cur, part.encode("utf-8"))
        if ref is None or not ref.is_dir:
            return None
        cur = ref.index
    return cur


def choose_pack_package(r: Any) -> tuple[int, str]:
    """Package to receive new actor packs: the newest update whose romfs has Pack/Actor, else base.

    An update's romfs is the complete game romfs (it holds every Pack/Actor pack and the
    Product.111 RSDB), and the game runs from it when the update is installed, so a pack
    added only to the base romfs would not be found next to the update's RSDB rows.
    """
    from nup import format as F
    candidates = []
    for p in r.packages:
        if p.romfs_dir == F.NO_DIR or _resolve_dir(r, p.romfs_dir, PACK_DIR.rstrip("/")) is None:
            continue
        candidates.append(p)
    updates = [p for p in candidates if p.kind == F.Kind.UPDATE]
    if updates:
        p = max(updates, key=lambda p: p.version)
        return p.index, (f"package {p.index} is the update (v{p.version_str}) and its romfs has "
                         f"{PACK_DIR}; the update romfs is what the game loads")
    bases = [p for p in candidates if p.kind == F.Kind.BASE]
    if bases:
        return bases[0].index, f"no update romfs with {PACK_DIR}; using base package {bases[0].index}"
    raise ShopError(f"no package romfs has a {PACK_DIR} directory")


def _rsdb_files(r: Any, romfs_dir: int) -> dict[str, tuple[str, int]]:
    """{kind: (filename, file index)} for the RSDB tables in one package."""
    from nup.access import iter_children
    d = _resolve_dir(r, romfs_dir, "RSDB")
    out: dict[str, tuple[str, int]] = {}
    if d is None:
        return out
    for ref in iter_children(r, d):
        n = ref.name.decode("utf-8", "replace")
        if ref.is_dir or not n.endswith(".rstbl.byml.zs"):
            continue
        for kind in RSDB_KINDS:
            if n.startswith(f"{kind}.Product."):
                out[kind] = (n, ref.index)
    return out


def _find_by_name(r: Any, romfs_dir: int, filename: str) -> list[int]:
    from nup.access import iter_children
    hits, stack = [], [romfs_dir]
    while stack:
        for ref in iter_children(r, stack.pop()):
            if ref.is_dir:
                stack.append(ref.index)
            elif ref.name.decode("utf-8", "replace") == filename:
                hits.append(ref.index)
    return hits


def apply_shop_items(nup_path: str | Path, zsdic_bytes: bytes,
                     items: Sequence[tuple[str, int, Any]], *,
                     template: str = DEFAULT_TEMPLATE,
                     package_index: int | None = None,
                     name_for: Callable[[str], str] = shop_actor_name,
                     set_actor: Callable[..., bytes] = set_shelf_item) -> ShopApplyResult:
    """Put custom shop items on shelves in a NUP, in place.

    items: [(item_actor, price, shelf_selector)], where shelf_selector is a Shelf, a
    (scene, select[, allow_multiple]) tuple or a list of them; `scene` is the bcett file name
    (e.g. "KokiriForest_Child_Static.bcett.byml.zs") and is patched in every package copy.
    name_for gives each clone's actor name; set_actor(bytes, select, name, allow_multiple=,
    changed=) writes it into a scene (the heart pickups use their own placement check). Shelf
    and heart actors of items that are not regular shop stock are then raised by ITEM_LIFT_Y.

    Everything is read and validated first. Then, in order: (1) new packs are added with
    add_files (it rewrites the whole TOC and may relocate meta blocks, so it runs before
    anything that appends extents or caches TOC positions); (2) RSDB tables of every package
    and (3) the shelf bcetts are rewritten via NupChestPatcher.replace_file; (4) RESTBL sizes
    are inserted for the new packs and (5) grown for the rewritten files.
    """

    from nup.read import NupReader
    from .nup_files import add_files

    nup_path = Path(nup_path)
    dicts = _load_dicts_from_sarc(zsdic_bytes)
    plan = [(item, _check_price(price), _as_shelves(sel)) for item, price, sel in items]
    if not plan:
        raise ShopError("no shop items given")

    with NupReader(str(nup_path)) as r:
        if package_index is None:
            target, reason = choose_pack_package(r)
        else:
            target, reason = package_index, f"package {package_index} requested"
        order = [r.packages[target]] + [p for p in r.packages if p.index != target]

        def read_raw(path: str) -> bytes:
            for p in order:
                fi = _resolve(r, p.romfs_dir, path)
                if fi is not None:
                    return r.read_file(fi)
            raise KeyError(path)

        def read_file(path: str) -> bytes:
            return _decompress(read_raw(path), dicts)

        rsdb = {p.index: _rsdb_files(r, p.romfs_dir) for p in r.packages}
        target_tables = {k: read_file(f"RSDB/{fn}") for k, (fn, _) in rsdb[target].items()}
        actors: list[ShopActor] = []
        for item, price, _ in plan:
            actors.append(build_shop_actor(read_file, item, price, template=template, dicts=dicts,
                                           read_raw=read_raw, rsdb_tables=target_tables,
                                           name=name_for(item)))
        names = [a.name for a in actors]
        if len(set(names)) != len(names):
            raise ShopError(f"duplicate shop items: {names}")
        existing = {a.romfs_path for a in actors
                    if _resolve(r, r.packages[target].romfs_dir, a.romfs_path) is not None}

        # Dry runs on every package copy so nothing is written when a later step would fail.
        for p in r.packages:
            for kind, (fn, fi) in rsdb[p.index].items():
                data = _decompress(r.read_file(fi), dicts)
                for item, price, _ in plan:
                    build_rsdb_rows({kind: data}, template, item, name_for(item), price)
        scene_edits: dict[str, list[tuple[Shelf, str, bool]]] = {}
        for (item, _, shelves), actor in zip(plan, actors):
            for shelf in shelves:
                scene_edits.setdefault(shelf.filename, []).append(
                    (shelf, actor.name, needs_lift(item))
                )
        for filename, edits in scene_edits.items():
            copies = [fi for p in r.packages for fi in _find_by_name(r, p.romfs_dir, filename)]
            if not copies:
                raise ShopError(f"{filename} not found in any package")
            for fi in copies:
                data = _decompress(r.read_file(fi), dicts)
                for shelf, new_name, lift in edits:
                    data = place_shelf_actor(
                        data, shelf, new_name, set_actor, lift=lift
                    )

    result = ShopApplyResult(package_index=target, package_reason=reason, actors=actors)

    # (1) new packs
    new_files = [(a.romfs_path, a.pack_zs) for a in actors if a.romfs_path not in existing]
    if new_files:
        add_files(nup_path, target, new_files, codec="raw")
        result.added_files = [p for p, _ in new_files]

    patcher = NupChestPatcher(nup_path, zsdic_bytes)
    for a in actors:
        if a.romfs_path in existing:
            patcher.replace_file(a.romfs_path.rsplit("/", 1)[-1], lambda _d, pack=a.pack: pack)
            patcher.size_changes.pop(a.resource_path, None)
            result.replaced_packs.append(a.romfs_path)

    # (2) RSDB rows, built from each table copy itself
    def rsdb_transform(kind: str) -> Callable[[bytes], bytes]:
        def transform(data: bytes) -> bytes:
            rows = []
            for item, price, _ in plan:
                rows.append(build_rsdb_rows({kind: data}, template, item, name_for(item), price)[kind])
            return add_rsdb_rows(data, rows)
        return transform

    filenames = {fn: kind for tables in rsdb.values() for kind, (fn, _) in tables.items()}
    for fn, kind in sorted(filenames.items()):
        if kind == "Tag" and all(a.rows.get("Tag") is None for a in actors):
            continue  # template has no tags: nothing to add
        result.rsdb_tables[fn] = patcher.replace_file(fn, rsdb_transform(kind))

    # (3) shelves
    for filename, edits in scene_edits.items():
        per_copy: list[list[int]] = []

        def transform(data: bytes, edits=edits, per_copy=per_copy) -> bytes:
            changed: list[int] = []
            for shelf, new_name, lift in edits:
                data = place_shelf_actor(
                    data, shelf, new_name, set_actor, lift=lift, changed=changed
                )
            per_copy.append(changed)
            return data

        patcher.replace_file(filename, transform)
        result.scenes[filename] = per_copy

    # (4) + (5) resource size table
    result.restbl_tables_written = patcher.add_resource_sizes(
        {a.resource_path: a.restbl_size for a in actors},
        new_paths={a.resource_path for a in actors})
    result.restbl_entries_grown = patcher.update_resource_size_tables()
    return result
