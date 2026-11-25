# Chest Randomization

This is the process for finding chests in the NUP, turning them into randomizable slots, and patching the shuffled items back in. Chests are the base case for item randomization; NPC grants and event items follow the same pattern with different patch targets (see [adding_npc_grants.md](./adding_npc_grants.md)).

## Pipeline

### 1. Scan the scene files

Each placement file (`*.bcett.byml`, with Child and Adult variants) is decompressed and walked by `_walk_byml_chests` in [nup_chest_patcher.py](../src/oot_randomizer/nup_chest_patcher.py). It finds every `Obj_TBox_A_01` and `Obj_TBox_A_02` actor and records:

- the room index,
- the vanilla `Drop__DropActor` item,
- the byte offset of the item's string-table index.

The results go into `chest_locations_summary.json` at the project root. The `scan` command reports NUP structure but does not write this summary. The script that generates the summary has not been confirmed; check before regenerating it.

### 2. Merge into slots

`load_chest_slots` in [engine.py](../src/oot_randomizer/engine.py) combines the Child and Adult copies of a chest into one `ChestSlot`:

- `targets` lists each `(scene_file, chest_order)` pair that the slot patches.
- `ages` reports whether the chest is child-only, adult-only, or both, based on the file name.
- `scene` is the logic region key (the scene prefix, e.g. `KokiriForest`).

Slots listed in `NOT_IN_GAME_SLOTS` (in [engine.py](../src/oot_randomizer/engine.py)) are dropped from shuffling and from the planner. They have no chest in game, even though the scan finds them. `KokiriForest Static room 0 #0 (TBox_Rupee_Green)` is the current entry. Do not use the `NoBake` name alone to detect these. Many real chests also have `NoBake`.

### 3. Add logic

`logic template` generates a starter file from the slots, with one `[regions.X.locations]` entry per chest. Set each chest's requirement by hand under `logic\world\`. Chests in the unknown-area region keep their vanilla items until confirmed reachable.

### 4. Shuffle

`shuffle_chest_items` assigns items to reachable slots. `build_shuffle_patches` turns each assignment into a `PatchRecord` carrying the `chest_order`. The plan is exposed as `plan.chest_assignments` in [randomizer.py](../src/oot_randomizer/randomizer.py).

### 5. Patch

[patcher.py](../src/oot_randomizer/patcher.py) groups patches by scene file and chest identity (room plus order). `NupChestPatcher` then:

1. Rewrites the `Drop__DropActor` string index in the BYML.
2. Recompresses the file.
3. Appends a new extent to the NUP copy.
4. Updates the TOC entry, the RESTBL sizes, and the superblock.

The Kokiri Forest sword chest is a special case: [chest_events.py](../src/oot_randomizer/chest_events.py) handles its demo.

### 6. Verify

1. `python -m oot_randomizer.cli logic check`
2. Chest-related tests: `test_location_mapper` and `test_world_logic`.
3. Playtest. Confirm the chest gives the right item and that Child and Adult versions match.

## Progressive items (opt-in)

`--progressive-items` (`RandomizerConfig.progressive_items`, default off) turns each complete item family into copies in the pool: Hookshot, Strength, Bomb Bag, Bow, Slingshot, Wallet, Scale, Nut and Stick Capacity, Magic, Ocarina. The family list and tier order are in [progressive.py](../src/oot_randomizer/progressive.py).

- **Pool and logic.** Each tier actor in the pool becomes one copy (`Progressive Hookshot`). The logic counts k copies as the first k tiers, so `Item_Longshot` needs two Hookshot copies. The logic TOML is unchanged.
- **Placement.** Copies go to plain chests and to the in-scope NPC and event grant slots (see below). Skull rewards, shop slots, heart pieces and song locations never take one, and neither do the 49 chests that already have a `GetEventName` (their vanilla event must stay). The planner keeps the same pool size.
- **Chest flows.** A copy's chest drops its family's lowest tier and gets a `GetEventName` (`OOTREM_Prog_<family>_<Small|Big>`). The matching row in the RSDB `EventSetting` and `GameAnalyzedEventInfo` tables points at a new entry, `Success_Prog_<family>`, in `Dm_SY_TreasureboxSmall` or `Dm_SY_Treasurebox`. That entry asks the pouch tier by tier (`GameDataActor.EventQueryCheckIsGet`) and gives the lowest tier it does not own, by calling the flow's own `Success_` entry.
- **NPC and event grants.** A copy placed at an in-scope grant slot (`progressive_npc.py`) wraps that grant in place. The grant node becomes the same ask chain, and each tier's give is a copy of the grant with the tier as its item, keeping the grant's successor. The in-scope slots are the bag, quiver, scale and Goron gauntlet grants in `npc_grants.py` (13 NPC slots) and the two Ocarina grants in `event_items.py`. Out of scope: the great fairies (their received bool and IsGet flag name the grant's item), the Biggoron Sword (no family in ootrr either), and the shop, skull, heart and song locations.

The structure was checked against the NUP dumps and by a full randomize on the retail NUP. Whether the pouch ownership checks, the per-chest events and the Ocarina chest grant behave in game is not verified. The NPC and event chains are not verified in game either.

## Loose heart pieces

The loose overworld `Obj_Heart_Piece` pickups (not chests) are randomized as pickupable items, the same set shops can sell. They are handled by [heart_pickups.py](../src/oot_randomizer/heart_pickups.py).

- **Slots:** 14 physical pieces, listed in `_HEART_TARGETS`. Each has a `Heart Piece N` logic location in its region TOML. Child and Adult copies are merged into one slot. [scan_loose_hearts.py](../scripts/scan_loose_hearts.py) produces the reference list in `loose_heart_pieces.json`. To add a piece, follow [adding_heart_pieces.md](./adding_heart_pieces.md).
- **Patching:** each distinct item gets a clone actor, `Obj_HeartRando_<item>`, built from the `Obj_Heart_Piece` template with the item's model and pouch content. Only the Gyaml string index in the scene changes. Actor positions are kept. The clones are added through the same path as shopsanity (`apply_shop_items`).
- **Planning:** the planner draws heart items after shop items. Each heart slot adds one filler (`SHOP_FILLER_ITEMS`, bombs or sticks) to the pool. Heart slots only accept pickupable items.
- **Stick and nut bundles:** a heart pickup does not give the Small Stick Bag or Small Nut Bag that the first Deku Stick and Deku Nut pickups and shop purchases give. Every seed grants both bags at the start of a new game instead (see the README's "Starting Small Stick Bag and Small Nut Bag").
- **Logic:** the rules are placeholders. Adjust them in the region TOMLs.
- **Disable:** `--no-heart-shuffle` on the CLI, or `shuffle_heart_pieces = false` in the config.
- **Not included:** the Goron large-pot drop (`EventGoronLargePotDropPrize`), dungeon heart containers, and the Market minigame rewards.

## Where items can go

The planner in [planner.py](../src/oot_randomizer/planner.py) fills every randomized location. Each kind of location accepts:

- **Chests:** any item from the chest pool, including songs, medallions, ocarinas, bags, and rupees.
- **Song, event, and NPC locations:** any item an NPC can hand over (`can_hand_over`). Songs and dungeon items are not hand-over items, so they cannot go to event or NPC slots. Rupees (`TBox_Rupee_*`) are hand-over items, because vanilla grants `TBox_Rupee_Green` by name. Consumable bundles (`CANNOT_NAME_GRANT` in `item_ids.py`) are never placed in these locations, because their name-based grant gives the Bomb Bag.
- **Skulltula rewards:** hand-over items only.
- **Shop and loose heart slots:** sellable or pickupable items only (`can_sell`, `can_pickup`). Each shop or heart slot also adds one filler to the pool (`SHOP_FILLER_ITEMS`).
- **Dungeon items, bundles, and other `TBox_*` actors:** chests only. Rupees are the exception above.

Progression items prefer their own group's locations and fall back to chests. Chest-only items are placed before songs, and hand-over items go last.

## Pitfalls

- **Slot identity depends on scan order.** The `#k` in a slot name counts duplicate room and drop pairs in scan order. Regenerating the summary with a different order can renumber slots, and existing logic entries would then point at the wrong chest.
- **Child and Adult copies must change together.** A slot has several targets for this reason.
- **The patch changes file size.** New drop strings go into the BYML string table, so the RESTBL sizes and TOC must be updated, not just the bytes at one offset.
- **Dynamic nodes can be shared.** `dynamic_offset` may be shared between actors, so do not edit it per chest. A swapped chest gets its own copy of the Dynamic hash (`_dynamic_hash_for_swap`).
- **Owned-item substitutes.** Some shield chests (`Obj_TBox_A_06`, e.g. Graveyard's Hylian Shield) carry `Drop__CheckActor` and `Drop__DropActor_Substitute` in their Dynamic node. If the player already owns the check item, the game gives the substitute (a rupee) instead of the drop. The swapped copy drops both keys, so the randomized item is always given.
- **Unknown drops are skipped.** Chests with no room index or no drop name are ignored by `load_chest_slots`.
