# Event item shuffle (phase 1)

## Approach

Event items are granted by cutscene flows (bfevfl files) rather than by actors placed in the scene. Phase 1 shuffles the ten grant flows among the ten event items: five medallions, Kokiri's Emerald, Goron's Ruby, Zora's Sapphire, and the two ocarinas.

Only the grant and display parameters change. These are the `ActorName` / `Actor` values on:

- `GetPouchContentByActorName` and `DisplayGetByActorName` sub-flow calls
- `PouchSystemActor.EventTriggerAddOrRemovePouchContent` actions

Model, LOD, XLink and other ACT references are left alone. The cutscene model may therefore not match the granted item (accepted for phase 1).

Patching uses `evfl` (`EventFlow.read` / `write`), not byte edits. `patch_event_item(data, old, new)` is idempotent and returns the input unchanged when `old == new`.

## Slot list

| Flow | Vanilla item |
| --- | --- |
| Dm_Awake_Forest_Get | Item_Medal_Forest |
| Dm_Awake_Fire_Get | Item_Medal_Fire |
| Dm_Awake_Water_Get | Item_Medal_Water |
| Dm_Awake_Shadow_Get | Item_Medal_Shadow |
| Dm_Awake_Spirit_Get | Item_Medal_Spirit |
| Dm_Kokiri_0130 | Item_Stone_Forest |
| Dm_DeathMtTrail_0025 | Item_Stone_Fire |
| Dm_ZoraFountain_0030 | Item_Stone_Water |
| Dm_Kokiri_0155 | Item_Ocarina_Fairy (two params) |
| Dm_MelodyGet_Time | Item_Ocarina_Time (two params; also a song flow) |

The Zora's Sapphire grant is `Item_Stone_Water` in `Dm_ZoraFountain_0030` (Event158). Its raw flow is in the fixtures used by `test_event_items`.

## Planner and logic

- Event locations use the group `"event"` and are controlled by `PlanOptions.shuffle_event_items` (default `True`, CLI `--no-event-items`).
- Every item is placed uniformly at random among the slots it can legally fill, regardless of group. Event items can land in event, chest, shop, Skulltula, song, and NPC slots; the legality rules are `can_hand_over` and the per-kind checks in `allowed()`.
- Feasibility guard: chest-only items (bundles, dungeon items, and `TBox_*` other than rupees) can only use chest-kind slots. A flexible item may take a chest-kind slot only while enough chest-kind slots remain for them. In the current pool, chest-only items fill most chest-kind slots, so only a small number of flexible placements per seed can land there (about 30 in the 50-seed measurement).
- Event items are not counted as majors for `one_major_per_dungeon`. Counting them made fill infeasible on 9 of 10 seeds.
- Each event location has an entry in the region TOML files under `logic\world\`, keyed `"<flow stem> (event item)"`. The requirements match the vanilla gates.

## Verified

- evfl round trip of all ten raw flows is byte-equal when nothing is changed.
- `patch_event_item` is idempotent and a no-op when old == new.
- Patched flows parse and round-trip; song and event patches compose on `Dm_MelodyGet_Time`.
- `logic check`: 331/331 locations reachable on the vanilla goal.
- Tests: `test_event_items` 23 OK; `test_world_logic` 23 OK; `test_shop_soldout`, `test_gamedata_list`, `test_shopsanity`, `test_skulltula`, `test_chest_events` pass.

## Stone gates

The Temple of Time door and Darunia's Fire-stone branch read `Get_StoneOfFire_IsCompleted_Exp`, a bool set only by the vanilla Goron's Ruby flow. A shuffled Ruby would leave the door locked, so these gates now check pouch possession.

`src\oot_randomizer\stone_gates.py` (`patch_stone_gates`) rewrites the matched query events in these flows when `POUCH_STONE_GATES` is `True`. It is currently `False` for diagnosis, so the vanilla `Get_StoneOf*_IsCompleted_Exp` gates are left in place. The pickup hook is unaffected. The conversion is described below, using the Epona pattern `PouchSystemActor.EventQueryIsExistInPouch {'Actor': 'Obj_Ocarina_Time', 'Num': 1}` with `Item_Stone_Fire`:

- `DoorOfTime` (Event38)
- `Dm_Goron_0028` (Event44)

The patch is idempotent, leaves the file unchanged when the query is absent, and is byte-equal when nothing matches. It runs in `RomPatcher.apply` when at least one event item moved, and it is applied via `replace_file`, so it composes with other patches to the same flow.

Stone pickup trigger: the Door of Time stone count is only rechecked when Zora's Fountain is left (vanilla `Dm_SY_BancChange_EscapeDungeon` Event78). A shuffled stone can be granted from any of the three stone slots, so `add_stone_count_check` inserts a `SUB DoorOfTime DoorOfTime_CheckStoneNum` right after the `GetPouchContentByActorName` grant in `Dm_Kokiri_0130`, `Dm_DeathMtTrail_0025`, and `Dm_ZoraFountain_0030`. The original successor is kept, the insertion is idempotent, and it runs in `RomPatcher.apply` whenever event items are shuffled. The shared `Dm_SY_Get` get-item flow is different. Calling the check right after its `PouchAddItem` sub-flow cut into the get-item presentation, so `add_stone_count_check_at_route_end` instead points each exit of the route after `PouchAddItem` (the small-key switch `Event177`'s false case and the end of `Event183`) at the check. The check runs last and the item's presentation is left alone. It runs after every item on that route, not only stones. The check's own stone gates decide whether progress happens.

Diagnostics: while `STONE_CHECK_DIAGNOSTICS` is True in `stone_gates.py`, `DoorOfTime.bfevfl.zs` writes game-data bools that show which path the check took. `Rando_Diag_StoneCheck_Ran` is set on entry. `Rando_Diag_StoneCheck_Step03`, `Rando_Diag_StoneCheck_Step2_1`, `Rando_Diag_StoneCheck_Step2_2`, and `Rando_Diag_StoneCheck_Both` are set just before the Event37, Event147, Event148, and Event6 branches. Set the constant to False and rebuild to remove them.

The Water bool (`Get_StoneOfWater_IsCompleted_Exp`) is converted in `DoorOfTime.bfevfl.zs` (Event39 and Event56) to a pouch query for `Item_Stone_Water`, the same as Fire. Other Water-bool users are left unchanged: `Dm_SY_BancChange_EscapeDungeon`, `Dm_SY_Ocarina_SariaSong`, `SubEvent_GetEponaSong`, and several `Npc_Zora_*` dialogs. Also left unchanged: `SageOf*_IsCompleted_Exp`; `DoorOfTime_IsAfter_*`; and the Forest and Fire has-stone gates in `Dm_SY_BancChange_EscapeDungeon`, `Dm_SY_BancChangeArrive`, and Kokiri dialog. Those remain bool-based and may still misbehave after a stone moves.

Logic: `logic\world\overworld\TempleOfTime.toml` now requires `(is_adult or Deku_Tree_Clear) and Kokiris_Emerald and Goron_Ruby and Zora_Sapphire`. The logic identifiers are `Kokiris_Emerald`, `Goron_Ruby`, and `Zora_Sapphire`. The DoorOfTime script checks Fire and Water only, so the logic is stricter than the door script for the Emerald.

## Unverified in-game risks

- Cutscene model mismatch (accepted; model and LOD references unchanged).
- The pouch query uses `Num: 1` and the Epona value types; this is not confirmed in-game.
- Forest and Fire has-stone gates that are still bool-based (see Stone gates).
- Nothing has been run in an emulator.
- Boss hearts are not started.
- Zora's Sapphire: the grant flow is decoded. The event location `Dm_ZoraFountain_0030 (event item)` is listed in `ZoraFountain.toml` as `is_child and Jabu_Jabu_Clear`, based on the vanilla warp flow, not in-game. The Water door gate is a pouch check and is untested in-game.
