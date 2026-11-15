"""Tests for shops.py: custom shop shelf actors, RSDB rows, shelf placement and NUP apply."""

import struct
import sys
import tempfile
import unittest
from pathlib import Path

import zstandard

from oot_randomizer.byml7 import U32, U64, Byml7, dump_byml7, parse_byml7, parse_byml7_typed
from oot_randomizer.nup_chest_patcher import (
    _decompress,
    _detect_dict_id,
    _load_dicts_from_sarc,
    _restbl_entry_offset,
)
from oot_randomizer.sarc import read_sarc, write_sarc
from oot_randomizer.shops import (
    ITEM_LIFT_Y,
    Shelf,
    ShopError,
    add_rsdb_rows,
    apply_shop_items,
    build_rsdb_rows,
    build_shop_actor,
    encode_tag_tables,
    find_shelf_actors,
    needs_lift,
    pack_path_to_work_ref,
    place_shelf_actor,
    ref_closure,
    ref_to_pack_path,
    set_shelf_item,
    shift_actor_y,
    tag_names,
)

SESSION_FILES = Path(r"C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405\files")
SARC_SAMPLES = SESSION_FILES / "sarc_samples"
BYML_SAMPLES = SESSION_FILES / "byml_samples"

AP = ".engine__actor__ActorParam"
B = dump_byml7


# ---------------------------------------------------------------------------
# Synthetic game data
# ---------------------------------------------------------------------------

BASE_AP = f"Actor/Shop_Item_Base{AP}.bgyml"
TPL_FILES = {
    BASE_AP: {"Components": {
        "AIInfoRef": "?AI/AIInfo/Shop_Item_Base.engine__actor__AIInfo.bgyml",
        "PhysicsRef": "?Component/Physics/Shop_Item_Base.engine__component__PhysicsParam.bgyml",
        "ActorPositionCalculatorRef": "?Component/APC/ShopCommon.game__component__APC.bgyml",
        "ModelInfoRef": "?Component/ModelInfo/Dummy.engine__component__ModelInfo.bgyml",
    }},
    "AI/AIInfo/Shop_Item_Base.engine__actor__AIInfo.bgyml": {"RootAIRef": "Work/AI/Root/Shop_Item_Base.root.ain"},
    "AI/Shop_Item_Base.root.ainb": b"AIB \x08\x04\x00\x00" + b"\x01" * 24,
    "Component/Physics/Shop_Item_Base.engine__component__PhysicsParam.bgyml": {
        "$parent": "Work/Component/Physics/ProjectBase.engine__component__PhysicsParam.gyml"},
    "Component/APC/ShopCommon.game__component__APC.bgyml": {"CursorYOffset": 0.0},
    "Component/APC/ShopTpl.game__component__APC.bgyml": {
        "$parent": "Work/Component/APC/ShopCommon.game__component__APC.gyml", "CursorYOffset": 0.25},
    "Component/ASInfo/Item_Shop.engine__component__ASInfo.bgyml": {"AutoPlayASName": ""},
    "Orphan/Unreferenced.bgyml": {"X": 1},
    f"Actor/Shop_Tpl{AP}.bgyml": {
        "$parent": f"Work/Actor/Shop_Item_Base{AP}.gyml",
        "Components": {
            "ASInfoRef": "?Component/ASInfo/Item_Shop.engine__component__ASInfo.bgyml",
            "ASRef": "?AS/Item_Common.root.asb",
            "ActorNameRef": "?ActorSystem/ActorName/Tpl.engine__actor__ActorName.bgyml",
            "ActorPositionCalculatorRef": "?Component/APC/ShopTpl.game__component__APC.bgyml",
            "AnimationRef": "?Component/AnimationParam/Tpl.engine__component__AnimationParam.bgyml",
            "GameParameterTableRef": "?GameParameter/GameParameterTable/Item_Tpl.engine__actor__GameParameterTable.bgyml",
            "ModelInfoRef": "?Component/ModelInfo/Tpl_Shop.engine__component__ModelInfo.bgyml",
            "PouchContentRef": "?Component/PouchContentParam/Shop_Tpl.game__component__PouchContentParam.bgyml",
        }},
    "Component/AnimationParam/Tpl.engine__component__AnimationParam.bgyml": {
        "AnimationResources": [{"ModelProjectName": "Tpl_Animation"}]},
    "Component/ModelInfo/Tpl_Shop.engine__component__ModelInfo.bgyml": {"FmdbName": "Tpl_Shop"},
    "GameParameter/GameParameterTable/Item_Tpl.engine__actor__GameParameterTable.bgyml": {
        "Category": "GameParameterTableDefault", "Components": {
            "PriceParam": "?GameParameter/PriceParam/Item_Tpl.game__pouchcontent__PriceParam.bgyml",
            "Extra": "?GameParameter/Extra/Tpl.game__x__Extra.bgyml"}},
    "GameParameter/PriceParam/Item_Tpl.game__pouchcontent__PriceParam.bgyml": {"BuyingPrice": 0, "SellingPrice": 1},
    "GameParameter/Extra/Tpl.game__x__Extra.bgyml": {"V": 3},
    "Component/PouchContentParam/Shop_Tpl.game__component__PouchContentParam.bgyml": {
        "$parent": "Work/Component/PouchContentParam/TplDefault.game__component__PouchContentParam.gyml",
        "IsNotOpenStockNumDisplay": True, "PouchActor": f"Work/Actor/Item_Tpl{AP}.gyml"},
    "Component/PouchContentParam/TplDefault.game__component__PouchContentParam.bgyml": {
        "$parent": "Work/Component/PouchContentParam/Default.game__component__PouchContentParam.gyml",
        "GetType": U32(5)},
}
TPL_DROPPED = {
    f"Actor/Shop_Tpl{AP}.bgyml",
    "Component/AnimationParam/Tpl.engine__component__AnimationParam.bgyml",
    "Component/ModelInfo/Tpl_Shop.engine__component__ModelInfo.bgyml",
    "GameParameter/GameParameterTable/Item_Tpl.engine__actor__GameParameterTable.bgyml",
    "GameParameter/PriceParam/Item_Tpl.game__pouchcontent__PriceParam.bgyml",
    "GameParameter/Extra/Tpl.game__x__Extra.bgyml",
    "Component/PouchContentParam/Shop_Tpl.game__component__PouchContentParam.bgyml",
    "Component/PouchContentParam/TplDefault.game__component__PouchContentParam.bgyml",
}
ITEM_PC = "Component/PouchContentParam/Item_Thing.game__component__PouchContentParam.bgyml"
ITEM_FILES = {
    f"Actor/Item_Thing{AP}.bgyml": {
        "$parent": f"Work/Actor/Item_EventObject_Base{AP}.gyml",
        "Components": {
            "ASInfoRef": "?Component/ASInfo/Item_GetDemo.engine__component__ASInfo.bgyml",
            "ActorNameRef": "?ActorSystem/ActorName/Item_Thing.engine__actor__ActorName.bgyml",
            "AnimationRef": "?Component/AnimationParam/Item_Thing.engine__component__AnimationParam.bgyml",
            "CaptureRef": "?Component/CaptureParam/Item_Thing.game__component__CaptureParam.bgyml",
            "GameParameterTableRef": "?GameParameter/GameParameterTable/Item_Thing.engine__actor__GameParameterTable.bgyml",
            "ModelInfoRef": "?Component/ModelInfo/Item_Thing.engine__component__ModelInfo.bgyml",
        }},
    f"Actor/Item_EventObject_Base{AP}.bgyml": {"Components": {
        "ModelInfoRef": "?Component/ModelInfo/Dummy.engine__component__ModelInfo.bgyml",
        "PouchContentRef": "?" + ITEM_PC}},
    "Component/ASInfo/Item_GetDemo.engine__component__ASInfo.bgyml": {"AutoPlayASName": ""},
    "Component/AnimationParam/Item_Thing.engine__component__AnimationParam.bgyml": {
        "AnimationResources": [{"ModelProjectName": "Item_Thing_Animation"}]},
    "Component/CaptureParam/Item_Thing.game__component__CaptureParam.bgyml": {"C": 1},
    "Component/ModelInfo/Item_Thing.engine__component__ModelInfo.bgyml": {
        "FmdbName": "Item_Thing_Body", "ModelProjectName": "Item_Thing",
        "ModelVariationAnims": [{"Fmab": "Work/Model/Item/Item_Thing_Animation/output/Pose.fvbb"}]},
    "Component/ModelInfo/Dummy.engine__component__ModelInfo.bgyml": {"FmdbName": ""},
    "GameParameter/GameParameterTable/Item_Thing.engine__actor__GameParameterTable.bgyml": {
        "Category": "GameParameterTableDefault", "Components": {
            "AssignableItemParam": "?GameParameter/AssginableItemParam/Item_Thing.game__actor__AssginableItemParam.bgyml",
            "PriceParam": "?GameParameter/PriceParam/Item_Thing.game__pouchcontent__PriceParam.bgyml"}},
    "GameParameter/AssginableItemParam/Item_Thing.game__actor__AssginableItemParam.bgyml": {"AssignableItem": U32(9)},
    "GameParameter/PriceParam/Item_Thing.game__pouchcontent__PriceParam.bgyml": {"BuyingPrice": 7, "SellingPrice": 7},
    ITEM_PC: {"$parent": "Work/Component/PouchContentParam/Default.game__component__PouchContentParam.gyml",
              "Category": U32(957554845)},
}


def make_pack(files: dict) -> bytes:
    return write_sarc({k: v if isinstance(v, bytes) else B(v) for k, v in files.items()})


def tag_table(entries: list[tuple[str, list[str]]], tags: list[str]) -> bytes:
    entries = sorted(entries, key=lambda e: e[0])
    path_list = [s for name, _ in entries for s in ("Work/Actor/", name, ".engine__actor__ActorParam.gyml")]
    bits, ranks = encode_tag_tables([{tags.index(t) for t in ts} for _, ts in entries], len(tags))
    return B({"BitTable": bits, "PathList": path_list, "RankTable": ranks, "TagList": tags})


def rsdb_tables() -> dict[str, bytes]:
    actor_info = [
        {"ClassName": "GameActor", "InstanceHeapSize": 1000, "__RowId": "Aaa"},
        {"ActorName": "Item_Thing", "AnimationResources": [{"ModelProjectName": "Item_Thing_Animation"}],
         "ClassName": "GameActor", "CoreUsedLevel": U32(0), "FmdbName": "Item_Thing_Body",
         "InstanceHeapSize": 5000, "ModelAabbMax": {"X": 1.0, "Y": 1.0, "Z": 1.0},
         "ModelAabbMin": {"X": -1.0, "Y": -1.0, "Z": -1.0}, "ModelProjectName": "Item_Thing",
         "PreActorRenderInfoHeapSize": 100, "__RowId": "Item_Thing"},
        {"ActorName": "Tpl", "ClassName": "GameActor", "CalcRadius": 40.0, "CoreUsedLevel": U32(0),
         "FmdbName": "Tpl_Shop", "InstanceHeapSize": 3000, "ModelProjectName": "Tpl",
         "ModelVariationFmabName": "Tpl_Color", "PreActorRenderInfoHeapSize": 700, "__RowId": "Shop_Tpl"},
        {"ClassName": "GameActor", "InstanceHeapSize": 10, "__RowId": "Zzz"},
    ]
    game_actor_info = [
        {"ModelVariationAnims": [{"Fmab": "Work/Model/x.fvbb", "Frame": 0.0, "IsPlay": True}], "__RowId": "Item_Thing"},
        {"IsRespawn": True, "MainRigidBodyLayer": "SmallObject", "__RowId": "Shop_Tpl"},
        {"__RowId": "Zzz"},
    ]
    pouch = [
        {"AssignableItem": "Thing", "BundleActorNum": 1, "PouchCategory": "Material", "__RowId": "Item_Thing"},
        {"BundleActorNum": 1, "IsNotOpenStockNumDisplay": True, "SellingPrice": 1, "__RowId": "Shop_Tpl"},
    ]
    return {
        "ActorInfo": B(actor_info), "GameActorInfo": B(game_actor_info), "PouchActorInfo": B(pouch),
        "Tag": tag_table([("Item_Thing", ["A"]), ("Shop_Tpl", ["B", "C"]), ("Zzz", ["A", "C"])],
                         ["A", "B", "C"]),
    }


def train_dicts() -> tuple[bytes, int]:
    """ZsDic.pack-like SARC holding one trained zstd dictionary; returns (sarc, dict id)."""
    samples = [B({f"Key{i % 13}": f"Value{i * 7}", "Components": {f"Ref{j}": f"?Component/X{j}/{i}.bgyml"
                                                                   for j in range(i % 9)}})
               for i in range(600)]
    d = zstandard.train_dictionary(2048, samples, dict_id=0x1234)
    return write_sarc({"pack.zsdic": d.as_bytes()}), 0x1234


def scene(actors: list[dict]) -> bytes:
    return B({"Actors": actors, "FilePath": "Work/Banc/Forest/Forest_Static.bcett.json"})


SHOP_ACTORS = [
    {"Gyaml": "Npc_Shopkeeper", "Hash": U64(1), "Translate": [0.0, 0.0, 0.0]},
    {"Dynamic": {"ShopItemIndex": 1}, "Gyaml": "Shop_Seeds", "Hash": U64(2), "Translate": [1.0, 0.0, 0.0]},
    {"Gyaml": "Shop_Board_Bundle_10", "Hash": U64(3)},
    {"Dynamic": {"ShopItemIndex": 2}, "Gyaml": "Shop_Nuts", "Hash": U64(4), "Translate": [2.0, 0.0, 0.0]},
    {"Dynamic": {"ShopItemIndex": 1}, "Gyaml": "Shop_Seeds", "Hash": U64(5), "Translate": [3.0, 0.0, 0.0],
     "Presence": {"FlagName": "F", "IsNegation": True}},
]


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class RefTests(unittest.TestCase):
    def test_ref_mapping(self):
        self.assertEqual(ref_to_pack_path("?Component/A.bgyml"), "Component/A.bgyml")
        self.assertEqual(ref_to_pack_path("Work/Component/A.x.gyml"), "Component/A.x.bgyml")
        self.assertEqual(ref_to_pack_path("Work/AI/Root/S.root.ain"), "AI/S.root.ainb")
        self.assertEqual(ref_to_pack_path("Work/Logic/N.aidefn"), "Logic/N.aidefn")
        self.assertIsNone(ref_to_pack_path("Material_Stone"))
        self.assertEqual(pack_path_to_work_ref("Component/A.x.bgyml"), "Work/Component/A.x.gyml")
        with self.assertRaises(ShopError):
            pack_path_to_work_ref("AI/S.root.ainb")

    def test_closure_follows_parents_and_ain(self):
        files = {k: v if isinstance(v, bytes) else B(v) for k, v in TPL_FILES.items()}
        got = ref_closure(files, [f"Work/Actor/Shop_Item_Base{AP}.gyml"])
        self.assertIn("AI/Shop_Item_Base.root.ainb", got)
        self.assertIn("Component/APC/ShopCommon.game__component__APC.bgyml", got)
        self.assertNotIn("Orphan/Unreferenced.bgyml", got)


class BuildShopActorTests(unittest.TestCase):
    def setUp(self):
        self.romfs = {
            "Pack/Actor/Shop_Tpl.pack.zs": make_pack(TPL_FILES),
            "Pack/Actor/Item_Thing.pack.zs": make_pack(ITEM_FILES),
        }

    def build(self, **kw):
        return build_shop_actor(self.romfs.__getitem__, "Item_Thing", 10, template="Shop_Tpl",
                                rsdb_tables=rsdb_tables(), **kw)

    def test_pack_contents(self):
        a = self.build()
        self.assertEqual(a.name, "Shop_Rando_Item_Thing")
        self.assertEqual(a.romfs_path, "Pack/Actor/Shop_Rando_Item_Thing.pack.zs")
        files = read_sarc(a.pack)
        self.assertEqual(files, a.files)
        self.assertEqual(a.decompressed_size, len(a.pack))
        self.assertEqual(set(a.dropped), TPL_DROPPED)
        for p in TPL_DROPPED:
            self.assertNotIn(p, files)
        self.assertIn("Orphan/Unreferenced.bgyml", files)  # unknown files are kept
        for p in a.shared:
            self.assertEqual(files[p], make_pack_file(TPL_FILES[p]))
        self.assertEqual(set(a.copied), {
            "Component/AnimationParam/Item_Thing.engine__component__AnimationParam.bgyml",
            "Component/ModelInfo/Item_Thing.engine__component__ModelInfo.bgyml",
            "GameParameter/AssginableItemParam/Item_Thing.game__actor__AssginableItemParam.bgyml",
            ITEM_PC,
        })
        for p in files:
            if p.endswith(".bgyml"):
                parse_byml7_typed(files[p])

        ap = parse_byml7(files[f"Actor/Shop_Rando_Item_Thing{AP}.bgyml"])
        self.assertEqual(ap["$parent"], f"Work/Actor/Shop_Item_Base{AP}.gyml")
        c = ap["Components"]
        tpl_c = TPL_FILES[f"Actor/Shop_Tpl{AP}.bgyml"]["Components"]
        item_c = ITEM_FILES[f"Actor/Item_Thing{AP}.bgyml"]["Components"]
        for k in ("ASInfoRef", "ASRef", "ActorPositionCalculatorRef"):
            self.assertEqual(c[k], tpl_c[k])
        for k in ("ModelInfoRef", "ActorNameRef", "AnimationRef"):
            self.assertEqual(c[k], item_c[k])
        self.assertNotIn("CaptureRef", c)
        pc_path = ref_to_pack_path(c["PouchContentRef"])
        self.assertEqual(parse_byml7(files[pc_path]), {
            "$parent": "Work/" + ITEM_PC[:-6] + ".gyml",
            "IsNotOpenStockNumDisplay": True,
            "PouchActor": f"Work/Actor/Item_Thing{AP}.gyml"})
        gpt = parse_byml7(files[ref_to_pack_path(c["GameParameterTableRef"])])
        self.assertEqual(gpt["Category"], "GameParameterTableDefault")
        self.assertEqual(set(gpt["Components"]), {"AssignableItemParam", "PriceParam"})
        price = parse_byml7_typed(files[ref_to_pack_path(gpt["Components"]["PriceParam"])])
        self.assertEqual(price, {"BuyingPrice": 10, "SellingPrice": 0})
        self.assertIs(type(price["BuyingPrice"]), int)
        # every reference of the new files resolves inside the pack except the external ones
        unresolved = {ref for path in a.created for ref in _refs(files[path])
                      if ref_to_pack_path(ref) not in files}
        self.assertEqual(unresolved, {
            "?AS/Item_Common.root.asb",
            "?ActorSystem/ActorName/Item_Thing.engine__actor__ActorName.bgyml",
            f"Work/Actor/Item_Thing{AP}.gyml",
        })

    def test_rows(self):
        rows = self.build().rows
        ai = rows["ActorInfo"]
        self.assertEqual(ai["__RowId"], "Shop_Rando_Item_Thing")
        self.assertEqual(ai["ActorName"], "Item_Thing")
        self.assertEqual(ai["FmdbName"], "Item_Thing_Body")
        self.assertEqual(ai["CalcRadius"], 40.0)  # template
        self.assertNotIn("ModelVariationFmabName", ai)  # item has none
        self.assertEqual(ai["InstanceHeapSize"], 5000)
        self.assertEqual(ai["PreActorRenderInfoHeapSize"], 700)
        gai = rows["GameActorInfo"]
        self.assertTrue(gai["IsRespawn"])
        self.assertEqual(gai["ModelVariationAnims"][0]["Fmab"], "Work/Model/x.fvbb")
        pai = rows["PouchActorInfo"]
        self.assertEqual((pai["AssignableItem"], pai["BuyingPrice"], pai["IsNotOpenStockNumDisplay"]),
                         ("Thing", 10, True))
        self.assertEqual(rows["Tag"], {"__RowId": "Shop_Rando_Item_Thing", "Tags": ["B", "C"]})

    def test_compression_uses_template_dict(self):
        sarc, did = train_dicts()
        dicts = _load_dicts_from_sarc(sarc)
        raw_tpl = zstandard.ZstdCompressor(dict_data=zstandard.ZstdCompressionDict(dicts[did])).compress(
            self.romfs["Pack/Actor/Shop_Tpl.pack.zs"])
        a = self.build(dicts=dicts, read_raw=lambda p: raw_tpl)
        self.assertEqual(a.dict_id, did)
        self.assertEqual(_detect_dict_id(a.pack_zs), did)
        self.assertEqual(_decompress(a.pack_zs, dicts), a.pack)
        plain = self.build()
        self.assertIsNone(_detect_dict_id(plain.pack_zs))
        self.assertEqual(zstandard.ZstdDecompressor().decompressobj().decompress(plain.pack_zs), plain.pack)

    def test_errors(self):
        with self.assertRaises(ShopError):
            build_shop_actor(self.romfs.__getitem__, "Item_Thing", -1, template="Shop_Tpl")
        with self.assertRaises(KeyError):
            build_shop_actor(self.romfs.__getitem__, "Item_Missing", 1, template="Shop_Tpl")
        tables = rsdb_tables()
        tables["PouchActorInfo"] = B([{"__RowId": "Shop_Tpl"}])
        with self.assertRaises(ShopError):
            build_rsdb_rows(tables, "Shop_Tpl", "Item_Thing", "Shop_Rando_Item_Thing", 1)


def make_pack_file(v):
    return v if isinstance(v, bytes) else B(v)


def _refs(data: bytes):
    from oot_randomizer.shops import iter_refs
    return list(iter_refs(parse_byml7(data)))


class RsdbTests(unittest.TestCase):
    def test_row_insert_sorted_and_replace(self):
        tables = rsdb_tables()
        rows = build_rsdb_rows(tables, "Shop_Tpl", "Item_Thing", "Shop_Rando_Item_Thing", 25)
        out = add_rsdb_rows(tables["ActorInfo"], [rows["ActorInfo"]])
        ids = [r["__RowId"] for r in parse_byml7(out)]
        self.assertEqual(ids, ["Aaa", "Item_Thing", "Shop_Rando_Item_Thing", "Shop_Tpl", "Zzz"])
        before = {r["__RowId"]: r for r in parse_byml7_typed(tables["ActorInfo"])}
        after = {r["__RowId"]: r for r in parse_byml7_typed(out)}
        for k, v in before.items():
            self.assertEqual(after[k], v)
        self.assertIs(type(after["Shop_Rando_Item_Thing"]["CoreUsedLevel"]), U32)
        # idempotent: re-adding replaces instead of duplicating
        again = add_rsdb_rows(out, [dict(rows["ActorInfo"], CalcRadius=99.0)])
        rows2 = [r for r in parse_byml7(again) if r["__RowId"] == "Shop_Rando_Item_Thing"]
        self.assertEqual(len(rows2), 1)
        self.assertEqual(rows2[0]["CalcRadius"], 99.0)
        self.assertEqual(add_rsdb_rows(out, []), out)
        self.assertEqual(add_rsdb_rows(out, [None]), out)

    def test_unsorted_table_appends(self):
        table = B([{"__RowId": "b"}, {"__RowId": "a"}])
        out = add_rsdb_rows(table, [{"__RowId": "c0"}])
        self.assertEqual([r["__RowId"] for r in parse_byml7(out)], ["b", "a", "c0"])

    def test_byml_header_kept(self):
        table = dump_byml7([{"__RowId": "a"}], version=7)
        out = add_rsdb_rows(table, [{"__RowId": "b"}])
        self.assertEqual(out[:4], table[:4])
        self.assertEqual(Byml7(out).version, 7)

    def test_tag_insert_and_rank(self):
        tables = rsdb_tables()
        self.assertEqual(tag_names(tables["Tag"], "Shop_Tpl"), ["B", "C"])
        self.assertEqual(tag_names(tables["Tag"], "Nope"), [])
        out = add_rsdb_rows(tables["Tag"], [{"__RowId": "Shop_Rando_X", "Tags": ["A", "C"]}])
        root = parse_byml7(out)
        names = root["PathList"][1::3]
        self.assertEqual(names, ["Item_Thing", "Shop_Rando_X", "Shop_Tpl", "Zzz"])
        for name, tags in [("Item_Thing", ["A"]), ("Shop_Rando_X", ["A", "C"]), ("Shop_Tpl", ["B", "C"]),
                           ("Zzz", ["A", "C"])]:
            self.assertEqual(tag_names(out, name), tags)
        ranks = struct.unpack("<3I", root["RankTable"])  # 3 tags x 1 block
        self.assertEqual(ranks, (3, 1, 3))
        self.assertEqual(len(root["BitTable"]), (4 * 3 + 7) // 8)
        self.assertEqual(add_rsdb_rows(tables["Tag"], [{"__RowId": "Untagged", "Tags": []}]), tables["Tag"])
        with self.assertRaises(ShopError):
            add_rsdb_rows(tables["Tag"], [{"__RowId": "X", "Tags": ["NotATag"]}])

    def test_encode_tag_tables_blocks(self):
        sets = [{0} if i % 3 == 0 else set() for i in range(70)]
        bits, ranks = encode_tag_tables(sets, 2)
        self.assertEqual(len(bits), (70 * 2 + 7) // 8)
        self.assertEqual(struct.unpack("<6I", ranks), (11, 22, 24, 0, 0, 0))


class ShelfTests(unittest.TestCase):
    def setUp(self):
        self.data = scene(SHOP_ACTORS)

    def test_set_by_index_changes_only_gyaml(self):
        changed = []
        out = set_shelf_item(self.data, 3, "Shop_Rando_Item_Thing", changed=changed)
        self.assertEqual(changed, [3])
        before, after = parse_byml7_typed(self.data), parse_byml7_typed(out)
        self.assertEqual(after["Actors"][3]["Gyaml"], "Shop_Rando_Item_Thing")
        after["Actors"][3]["Gyaml"] = "Shop_Nuts"
        self.assertEqual(after, before)
        # original bytes are untouched apart from the Gyaml slot and the string-table offset;
        # the extended string table is appended
        from oot_randomizer.shops import _actor_gyaml_slots
        slot = _actor_gyaml_slots(self.data)[1][3]
        diff = [i for i in range(len(self.data)) if self.data[i] != out[i]]
        self.assertTrue(diff)
        self.assertTrue(all(8 <= i < 12 or slot <= i < slot + 4 for i in diff), diff)
        self.assertGreater(len(out), len(self.data))

    def test_existing_string_reused(self):
        out = set_shelf_item(self.data, 3, "Shop_Seeds")
        self.assertEqual(len(out), len(self.data))
        self.assertEqual(parse_byml7(out)["Actors"][3]["Gyaml"], "Shop_Seeds")

    def test_match_selector(self):
        sel = {"Gyaml": "Shop_Seeds", "ShopItemIndex": 1}
        self.assertEqual(find_shelf_actors(self.data, sel), [1, 4])
        with self.assertRaises(ShopError):
            set_shelf_item(self.data, sel, "Shop_New")
        changed = []
        out = set_shelf_item(self.data, sel, "Shop_New", allow_multiple=True, changed=changed)
        self.assertEqual(changed, [1, 4])
        gy = [a["Gyaml"] for a in parse_byml7(out)["Actors"]]
        self.assertEqual(gy, ["Npc_Shopkeeper", "Shop_New", "Shop_Board_Bundle_10", "Shop_Nuts", "Shop_New"])
        one = set_shelf_item(self.data, lambda a, i: a.get("Presence") is not None, "Shop_New")
        self.assertEqual([a["Gyaml"] for a in parse_byml7(one)["Actors"]][4], "Shop_New")

    def test_rejects_non_shelf(self):
        with self.assertRaises(ShopError):
            set_shelf_item(self.data, 0, "Shop_New")
        with self.assertRaises(ShopError):
            set_shelf_item(self.data, 2, "Shop_New")  # price board
        with self.assertRaises(ShopError):
            set_shelf_item(self.data, {"Gyaml": "Shop_Board_Bundle_10"}, "Shop_New")
        with self.assertRaises(ShopError):
            set_shelf_item(self.data, 99, "Shop_New")

    def test_needs_lift_skips_regular_shop_stock(self):
        for item in ("Item_DekuStickBundle_Small", "Item_BombBundle_Small", "Item_Bottle_Fairy",
                     "Item_BombchuBundle_Small", "Item_DekuNut", "Item_Arrow_Normal"):
            self.assertFalse(needs_lift(item), item)
        for item in ("Item_Gauntlet_Silver", "Item_HeavyBoot", "Item_Mask_Truth", "Item_Hookshot",
                     "Item_Arrow_Fire", "Item_BulletBag_Large"):
            self.assertTrue(needs_lift(item), item)

    def test_shift_y_changes_only_translate_y(self):
        out = shift_actor_y(self.data, [1], ITEM_LIFT_Y)
        before, after = parse_byml7_typed(self.data), parse_byml7_typed(out)
        self.assertEqual(after["Actors"][1]["Translate"], [1.0, ITEM_LIFT_Y, 0.0])
        after["Actors"][1]["Translate"] = before["Actors"][1]["Translate"]
        self.assertEqual(after, before)

    def test_shift_y_rejects_actor_without_translate(self):
        with self.assertRaises(ShopError):
            shift_actor_y(self.data, [2], ITEM_LIFT_Y)

    def test_shift_y_does_not_move_actors_sharing_a_translate_array(self):
        data = scene([
            {"Gyaml": "Npc_Shopkeeper", "Hash": U64(1), "Translate": [0.0, 0.0, 0.0]},
            {"Dynamic": {"ShopItemIndex": 1}, "Gyaml": "Shop_Seeds", "Hash": U64(2), "Translate": [0.0, 0.0, 0.0]},
        ])
        out = parse_byml7_typed(shift_actor_y(data, [1], ITEM_LIFT_Y))["Actors"]
        self.assertEqual(out[0]["Translate"], [0.0, 0.0, 0.0])
        self.assertEqual(out[1]["Translate"], [0.0, ITEM_LIFT_Y, 0.0])

    def test_place_shelf_actor_lifts_only_when_asked(self):
        shelf = Shelf("KokiriForest_Child_Static.bcett.byml.zs", 1)
        lifted = place_shelf_actor(self.data, shelf, "Shop_New", set_shelf_item, lift=True)
        plain = place_shelf_actor(self.data, shelf, "Shop_New", set_shelf_item, lift=False)
        self.assertEqual(parse_byml7(lifted)["Actors"][1]["Translate"], [1.0, ITEM_LIFT_Y, 0.0])
        self.assertEqual(parse_byml7(plain)["Actors"][1]["Translate"], [1.0, 0.0, 0.0])
        for out in (lifted, plain):
            self.assertEqual(parse_byml7(out)["Actors"][1]["Gyaml"], "Shop_New")
        changed = []
        place_shelf_actor(self.data, shelf, "Shop_New", set_shelf_item, lift=True, changed=changed)
        self.assertEqual(changed, [1])


# ---------------------------------------------------------------------------
# End-to-end on a synthetic NUP
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_nup_files as tnf  # noqa: E402  (module import: its TestCases are not re-collected)


def _restbl(entries: dict[str, int]) -> bytes:
    import zlib
    crcs = sorted((zlib.crc32(p.encode()), s) for p, s in entries.items())
    out = bytearray(b"RESTBL" + struct.pack("<IIII", 1, 160, len(crcs), 0))
    for c, s in crcs:
        out += struct.pack("<II", c, s)
    return bytes(out)


class ApplyShopItemsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.zsdic, self.did = train_dicts()
        self.dicts = _load_dicts_from_sarc(self.zsdic)
        cctx = zstandard.ZstdCompressor(dict_data=zstandard.ZstdCompressionDict(self.dicts[self.did]))
        tables = rsdb_tables()

        def tree(product: str, scene_actors) -> dict[str, bytes]:
            t = {
                "romfs/Pack/Actor/Shop_Tpl.pack.zs": cctx.compress(make_pack(TPL_FILES)),
                "romfs/Pack/Actor/Item_Thing.pack.zs": cctx.compress(make_pack(ITEM_FILES)),
                "romfs/Banc/Forest/Forest_Static.bcett.byml.zs": cctx.compress(scene(scene_actors)),
                "romfs/Banc/Forest/Forest_Adult_Static.bcett.byml.zs": cctx.compress(scene(SHOP_ACTORS[:4])),
                f"romfs/System/Resource/ResourceSizeTable.{product}.rsizetable.zs": zstandard.ZstdCompressor().compress(
                    _restbl({"Banc/Forest/Forest_Static.bcett.byml": 4096,
                             "Banc/Forest/Forest_Adult_Static.bcett.byml": 4096,
                             f"RSDB/ActorInfo.{product}.rstbl.byml": 8192,
                             f"RSDB/GameActorInfo.{product}.rstbl.byml": 8192,
                             f"RSDB/PouchActorInfo.{product}.rstbl.byml": 8192})),
                "exefs/main": b"\x00" * 64,
            }
            for kind, data in tables.items():
                t[f"romfs/RSDB/{kind}.{product}.rstbl.byml.zs"] = cctx.compress(data)
            return t

        src = self.tmp / "src"
        tnf._write_tree(src / "base", tree("Product.100", SHOP_ACTORS))
        tnf._write_tree(src / "updates" / "131072", tree("Product.111", SHOP_ACTORS))
        self.nup = self.tmp / "test.nup"
        tnf.pack(str(self.nup), str(src), names={None: "Synthetic Test Title " * 75})
        tnf.move_meta_before_blob(self.nup, slack=4096)

    def tearDown(self):
        self._tmp.cleanup()

    def read(self, pkg: int, path: str) -> bytes | None:
        with tnf.NupReader(str(self.nup)) as r:
            ref = tnf.resolve_path(r, r.packages[pkg], "romfs/" + path)
            return None if ref is None else _decompress(r.read_file(ref.index), self.dicts)

    def test_apply(self):
        items = [("Item_Thing", 10, [
            Shelf("Forest_Static.bcett.byml.zs", {"Gyaml": "Shop_Seeds", "ShopItemIndex": 1}, True),
            ("Banc/Forest/Forest_Adult_Static.bcett.byml.zs", {"Gyaml": "Shop_Seeds", "ShopItemIndex": 1}),
        ])]
        before = tnf.snapshot(self.nup)
        res = apply_shop_items(self.nup, self.zsdic, items, template="Shop_Tpl")
        ok, problems = tnf.verify(str(self.nup), deep=True)
        self.assertTrue(ok, problems)

        self.assertEqual(res.package_index, 1)
        self.assertEqual(res.added_files, ["Pack/Actor/Shop_Rando_Item_Thing.pack.zs"])
        self.assertIsNone(self.read(0, "Pack/Actor/Shop_Rando_Item_Thing.pack.zs"))
        pack = self.read(1, "Pack/Actor/Shop_Rando_Item_Thing.pack.zs")
        self.assertEqual(pack, res.actors[0].pack)
        self.assertEqual(set(read_sarc(pack)), set(res.actors[0].files))
        with tnf.NupReader(str(self.nup)) as r:
            ref = tnf.resolve_path(r, r.packages[1], "romfs/Pack/Actor/Shop_Rando_Item_Thing.pack.zs")
            self.assertEqual(_detect_dict_id(r.read_file(ref.index)), self.did)

        for pkg, product in [(0, "Product.100"), (1, "Product.111")]:
            for kind in ("ActorInfo", "GameActorInfo", "PouchActorInfo"):
                rows = parse_byml7(self.read(pkg, f"RSDB/{kind}.{product}.rstbl.byml.zs"))
                ids = [x["__RowId"] for x in rows]
                self.assertIn("Shop_Rando_Item_Thing", ids)
                self.assertEqual(ids, sorted(ids))
            self.assertEqual(tag_names(self.read(pkg, f"RSDB/Tag.{product}.rstbl.byml.zs"),
                                       "Shop_Rando_Item_Thing"), ["B", "C"])
            gy = [a["Gyaml"] for a in parse_byml7(self.read(pkg, "Banc/Forest/Forest_Static.bcett.byml.zs"))["Actors"]]
            self.assertEqual(gy[1], "Shop_Rando_Item_Thing")
            self.assertEqual(gy[4], "Shop_Rando_Item_Thing")
            self.assertEqual(gy[3], "Shop_Nuts")
            gy = [a["Gyaml"] for a in parse_byml7(self.read(pkg, "Banc/Forest/Forest_Adult_Static.bcett.byml.zs"))["Actors"]]
            self.assertEqual(gy[1], "Shop_Rando_Item_Thing")

            restbl = zstandard.ZstdDecompressor().decompressobj().decompress(
                tnf.snapshot(self.nup)[(pkg, f"romfs/System/Resource/ResourceSizeTable.{product}.rsizetable.zs")])
            off = _restbl_entry_offset(restbl, "Pack/Actor/Shop_Rando_Item_Thing.pack")
            self.assertEqual(struct.unpack_from("<I", restbl, off)[0], res.actors[0].restbl_size)
            off = _restbl_entry_offset(restbl, f"RSDB/ActorInfo.{product}.rstbl.byml")
            self.assertGreater(struct.unpack_from("<I", restbl, off)[0], 8192)
        # identical base/update copies share one extent (nup.pack dedupes), so one rewrite
        self.assertEqual(res.scenes["Forest_Static.bcett.byml.zs"], [[1, 4]])

        after = tnf.snapshot(self.nup)
        untouched = [k for k in before if "RSDB" not in k[1] and "Banc" not in k[1] and "ResourceSize" not in k[1]]
        for k in untouched:
            self.assertEqual(after[k], before[k], k)

        # re-running replaces the pack and rows instead of failing or duplicating
        res2 = apply_shop_items(self.nup, self.zsdic, [("Item_Thing", 20, [
            ("Forest_Static.bcett.byml.zs", {"Gyaml": "Shop_Nuts"})])], template="Shop_Tpl")
        self.assertEqual(res2.replaced_packs, ["Pack/Actor/Shop_Rando_Item_Thing.pack.zs"])
        ok, problems = tnf.verify(str(self.nup), deep=True)
        self.assertTrue(ok, problems)
        rows = parse_byml7(self.read(1, "RSDB/PouchActorInfo.Product.111.rstbl.byml.zs"))
        hits = [x for x in rows if x["__RowId"] == "Shop_Rando_Item_Thing"]
        self.assertEqual([h["BuyingPrice"] for h in hits], [20])

    def test_validation_happens_before_writing(self):
        size = self.nup.stat().st_size
        with self.assertRaises(ShopError):
            apply_shop_items(self.nup, self.zsdic, [("Item_Thing", 10, [
                ("Forest_Static.bcett.byml.zs", {"Gyaml": "Shop_Seeds"})])], template="Shop_Tpl")
        self.assertEqual(self.nup.stat().st_size, size)


# ---------------------------------------------------------------------------
# Sample-based tests (real game files extracted to the session folder)
# ---------------------------------------------------------------------------

@unittest.skipUnless(SARC_SAMPLES.is_dir() and BYML_SAMPLES.is_dir(), "sample dirs not found")
class SampleTests(unittest.TestCase):
    def rsdb(self, kind: str) -> bytes:
        return (BYML_SAMPLES / f"RSDB__{kind}.Product.100.rstbl.byml").read_bytes()

    def test_keaton_hookshot(self):
        romfs = {f"Pack/Actor/{n}.pack.zs": (SARC_SAMPLES / f"{n}.pack").read_bytes()
                 for n in ("Shop_Mask_Keaton", "Item_Hookshot")}
        tables = {k: self.rsdb(k) for k in ("ActorInfo", "GameActorInfo", "PouchActorInfo", "Tag")}
        a = build_shop_actor(romfs.__getitem__, "Item_Hookshot", 10, rsdb_tables=tables)
        self.assertEqual(set(a.dropped), {
            "Actor/Shop_Mask_Keaton.engine__actor__ActorParam.bgyml",
            "Component/AnimationParam/Item_Mask_Keaton.engine__component__AnimationParam.bgyml",
            "Component/ModelInfo/Item_Mask_Keaton_Shop.engine__component__ModelInfo.bgyml",
            "Component/PouchContentParam/MaskDefault.game__component__PouchContentParam.bgyml",
            "Component/PouchContentParam/Shop_Mask_Keaton.game__component__PouchContentParam.bgyml",
            "GameParameter/GameParameterTable/Item_Mask_Keaton.engine__actor__GameParameterTable.bgyml",
            "GameParameter/InterestEmitterParam/Item_Mask_Keaton.game__perception__InterestEmitterParam.bgyml",
            "GameParameter/PlayerEquipmentActor/Item_Mask_Keaton.game__actor__PlayerEquipmentActor.bgyml",
            "GameParameter/PriceParam/Item_Mask_Keaton.game__pouchcontent__PriceParam.bgyml",
        })
        files = read_sarc(a.pack)
        self.assertIn("AI/Shop_Item_Base.root.ainb", files)
        self.assertIn("Component/ModelInfo/Item_Hookshot.engine__component__ModelInfo.bgyml", files)
        self.assertIn("Component/PouchContentParam/Item_Hookshot.game__component__PouchContentParam.bgyml", files)
        self.assertEqual(write_sarc(files), a.pack)
        self.assertEqual(a.rows["ActorInfo"]["FmdbName"], "Item_Hookshot_Body")
        self.assertEqual(a.rows["ActorInfo"]["ActorName"], "Item_Hookshot")
        self.assertEqual(a.rows["PouchActorInfo"]["BuyingPrice"], 10)
        self.assertIsNone(a.rows["Tag"])  # Shop_Mask_Keaton has no tags

    def test_rsdb_tables_sorted_and_insert(self):
        for kind in ("ActorInfo", "GameActorInfo", "PouchActorInfo"):
            data = self.rsdb(kind)
            out = add_rsdb_rows(data, [{"__RowId": "Shop_Rando_Test"}])
            before, after = parse_byml7_typed(data), parse_byml7_typed(out)
            ids = [r["__RowId"].encode() for r in after]
            self.assertEqual(ids, sorted(ids))
            i = ids.index(b"Shop_Rando_Test")
            self.assertEqual(after[:i] + after[i + 1:], before)

    def test_tag_tables_reencode_identically(self):
        root = parse_byml7_typed(self.rsdb("Tag"))
        from oot_randomizer.shops import _tag_entries
        _, tags, sets = _tag_entries(root)
        bits, ranks = encode_tag_tables(sets, len(tags))
        self.assertEqual(bits, bytes(root["BitTable"]))
        self.assertEqual(ranks, bytes(root["RankTable"]))

    def test_kokiri_shelf(self):
        data = (BYML_SAMPLES / "Banc__KokiriForest__KokiriForest_Child_Static.bcett.byml").read_bytes()
        sel = {"Gyaml": "Shop_DekuSeedBundle_02", "ShopItemIndex": 1}
        self.assertEqual(find_shelf_actors(data, sel), [314, 336])
        out = set_shelf_item(data, 336, "Shop_Rando_Item_Hookshot")
        before, after = parse_byml7(data)["Actors"], parse_byml7(out)["Actors"]
        diff = [i for i, (x, y) in enumerate(zip(before, after)) if x != y]
        self.assertEqual(diff, [336])
        self.assertEqual(after[336]["Gyaml"], "Shop_Rando_Item_Hookshot")


if __name__ == "__main__":
    unittest.main()
