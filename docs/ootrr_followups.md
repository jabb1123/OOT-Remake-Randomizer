# ootrr follow-up tasks

Ideas taken from the alternate randomizer `ootrr` (`c:\Users\jabb1123\Desktop\Roms\ootrr`, GPL-3.0-or-later). Reimplement the ideas in our own code. Do not copy ootrr source.

Status: `[ ]` not started, `[~]` in progress, `[x]` done.

## Sage and medal work (next)

- [x] **Kakariko Burning and Forest prelude read medals** (untested in game)
  - ootrr: `randomizer/core/src/medal_gate.rs` (`exps`, `patch_prelude`).
  - Ours: [medal_exp.py](/c:/Users/jabb1123/Desktop/Roms/oot_randomizer/src/oot_randomizer/medal_exp.py). The `SageOfShadow_Kakariko_Burning` formula becomes Forest AND Fire AND Water medals. The `AllSage_IsAfter_Step01_02_Exp` formula becomes the Forest medal, and the Market prelude module (`Market_Adult_Prefab_edc2`) reads that flag instead of `SageOfForest_IsCompleted_Exp`. The sage quest flags are unchanged.
  - Check in game: Kakariko Burning and the Forest prelude follow medals, not sage quests.
- [x] **Light Arrows (LACS) condition** (untested in game)
  - ootrr: `randomizer/core/src/medal_gate.rs` (`patch_lacs`, `patch_banc`, `LACS_EXP`).
  - Ours: [lacs_gate.py](/c:/Users/jabb1123/Desktop/Roms/oot_randomizer/src/oot_randomizer/lacs_gate.py) and the `AllSage_IsAfter_Step02_Exp` formula in [medal_exp.py](/c:/Users/jabb1123/Desktop/Roms/oot_randomizer/src/oot_randomizer/medal_exp.py). The formula is the Shadow and Spirit medals, with `HavePlayedEvent.Dm_TimeTemple_0130` not yet set. The c668 module (`Market_Adult_Prefab_c668`) forces the Light Arrows area on and points the AND gate at the player sensor instead of the Step02 check. The Light Arrows area `Area_a3ca` in `Market_Adult_Static.bcett.byml.zs` gets the presence flag `AllSage_IsAfter_Step02_Exp`.
  - Not ported: the "LACS - Dungeon Rewards" setting and its reward count. The formula is ootrr's default, not the setting-driven one.
  - Check in game: the Light Arrows scene plays once the Shadow and Spirit medals are held, not after the Step02 sage quest.
  - Check: our Ganon's Castle / LACS logic against the shuffled Light Medal.
- [ ] **Dungeon reward credit**
  - ootrr: `randomizer/core/src/dungeon_credit.rs`, `dungeon_grant.rs`.
  - Check: a medal granted from a boss chest or NPC is counted the same way as our `IsGet.Item_Medal_*` count expects.
- [ ] **Starting Stone or Medal**
  - ootrr: `randomizer/core/src/start_reward.rs` (modes Off, Stone, Medal, Any).
  - Requirement: a starting medal must set `IsGet.Item_Medal_*`, or AllSage will miscount.
  - Open question: whether this applies to the first three stones, which are currently not in the medal logic.

## Progressive items (done, untested in game)

- [x] **Progressive item chains** (behind the progressive_items flag, default off)
  - ootrr: `randomizer/core/src/progressive.rs` (`FAMILIES`, `owners`, `wrap`, `chain`, `wrap_grant_as`), with `data/items_coverage.md` (the `tiers` mode).
  - Ours: [progressive.py](/c:/Users/jabb1123/Desktop/Roms/oot_randomizer/src/oot_randomizer/progressive.py) (families and logic expansion), [progressive_chests.py](/c:/Users/jabb1123/Desktop/Roms/oot_randomizer/src/oot_randomizer/progressive_chests.py) (chest and NPC/event chain flows).
  - Covered: chests, 13 NPC grant slots, and 2 Ocarina event grants. Excluded: shop, skull, heart, and song slots (ootrr keeps these fixed), great fairies, Biggoron Sword, and the Bow starter kit.
  - Check in game: the first copy gives tier one, the second gives tier two, and a copy never gives a tier the player already has.

## Logic and start state

- [ ] **Open-start options**
  - ootrr: `randomizer/core/src/start_state.rs`.
  - Options: Kokiri Forest open, Kakariko gate open, Door of Time open, Zora's Fountain open, magic beans planted, Gerudo bridge repaired, Epona race skipped, mask trading skipped.
  - Overlaps with our Door of Time and Goron gate work. Ask before changing any locked flow.

## Shuffle scope (large)

- [ ] **Pots, crates, freestanding items, beehives, scrubs**
  - ootrr: `data/locations.json`, `data/coverage.md`, `randomizer/core/src/pots.rs`, `pot`/`crate` catalog data.
  - Note: ootrr's own coverage report says only about 16% of its catalog is matched to a real object. Treat this as a research project before any code.
- [ ] **Boss heart containers as chests**
  - ootrr: `randomizer/core/src/boss_heart.rs`.
- [ ] **Small keys shuffled**
  - ootrr: `randomizer/core/src/gift_keys.rs`, `key_log.rs`.
  - Note: our `world_logic.py` says keys are not shuffled yet.

## Quality of life (lower priority)

- [ ] **Character hints**
  - ootrr: `randomizer/core/src/npc_hints.rs`.
  - Text-only changes. ootrr marks these untested in the game.
- [ ] **Skip first-pickup text**
  - ootrr: `randomizer/core/src/first_pickups.rs`, `pickup_persist.rs`.
- [ ] **Skip area intros**
  - ootrr: `randomizer/core/src/story_skip.rs`, `area_intros.rs`.
  - Ours: `cutscene_skips.py` covers the opening intro only.
- [ ] **Chest size matches contents**
  - ootrr: `randomizer/core/src/chest_size.rs`. Marked experimental by ootrr.
- [ ] **Difficulty, bunny hood speed, spawn enemies, Navi return**
  - ootrr: `randomizer/core/src/difficulty.rs`. Bunny hood speed, spawn enemies, and Navi return are described in ootrr's README settings section.
  - Optional extras.

## Done

- [x] Medal count uses `IsGet.Item_Medal_*` (ootrr approach). Full suite passed, in-game test pending.
- [x] Skulltula token count is 100 (LLR GS Rain Shed added as a placeholder).
- [x] Skulltula location guide: [skulltulas.md](./skulltulas.md).
