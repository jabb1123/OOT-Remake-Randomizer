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

`src\oot_randomizer\stone_gates.py` (`patch_stone_gates`) rewrites the matched query events in these flows, using the Epona pattern `PouchSystemActor.EventQueryIsExistInPouch {'Actor': 'Obj_Ocarina_Time', 'Num': 1}` with `Item_Stone_Fire`:

- `DoorOfTime` (Event38)
- `Dm_Goron_0028` (Event44)

The patch is idempotent, leaves the file unchanged when the query is absent, and is byte-equal when nothing matches. It runs in `RomPatcher.apply` when at least one event item moved, and it is applied via `replace_file`, so it composes with other patches to the same flow.

The Water bool (`Get_StoneOfWater_IsCompleted_Exp`) is converted in `DoorOfTime.bfevfl.zs` (Event39 and Event56) to a pouch query for `Item_Stone_Water`, the same as Fire. Other Water-bool users are left unchanged: `Dm_SY_BancChange_EscapeDungeon`, `Dm_SY_Ocarina_SariaSong`, `SubEvent_GetEponaSong`, and several `Npc_Zora_*` dialogs. Also left unchanged: `SageOf*_IsCompleted_Exp`; `DoorOfTime_IsAfter_*`; and the Forest and Fire has-stone gates in `Dm_SY_BancChange_EscapeDungeon`, `Dm_SY_BancChangeArrive`, and Kokiri dialog. Those remain bool-based and may still misbehave after a stone moves.

Logic: `logic\world\overworld\TempleOfTime.toml` now requires `(is_adult or Deku_Tree_Clear) and Kokiris_Emerald and Goron_Ruby and Zora_Sapphire`. The logic identifiers are `Kokiris_Emerald`, `Goron_Ruby`, and `Zora_Sapphire`. The DoorOfTime script checks Fire and Water only, so the logic is stricter than the door script for the Emerald.

## Unverified in-game risks

- Cutscene model mismatch (accepted; model and LOD references unchanged).
- The pouch query uses `Num: 1` and the Epona value types; this is not confirmed in-game.
- Forest and Fire has-stone gates that are still bool-based (see Stone gates).
- Nothing has been run in an emulator.
- Boss hearts are not started.
- Zora's Sapphire: the grant flow is decoded. The event location `Dm_ZoraFountain_0030 (event item)` is listed in `ZoraFountain.toml` as `is_child and Jabu_Jabu_Clear`, based on the vanilla warp flow, not in-game. The Water door gate is a pouch check and is untested in-game.
