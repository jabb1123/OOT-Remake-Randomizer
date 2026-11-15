# Adding loose heart pieces

Loose heart pieces are the `Obj_Heart_Piece` (and `Obj_GerudoValley_Heart_Piece`) actors placed in the overworld, not in chests or events. Each one becomes a randomizable slot that accepts any pickupable item (the same set shops can sell). See [chest_randomization.md](./chest_randomization.md#loose-heart-pieces) for how the slots are patched and planned.

Use this checklist for every piece you find. The list at the bottom tracks what is done.

## Steps

1. **Find the piece.** Run the scanner on your randomized or vanilla NUP. It lists every heart actor with no `Dynamic` block:

   ```
   python scripts\scan_loose_hearts.py --rom <rom>.nup --zsdic <ZsDic.pack>
   ```

   Add `--write loose_heart_pieces.json` to regenerate the reference list. Note the scene file, the `Actors` index, and the `Gyaml` for both the Child and Adult copies.

2. **Check the actor class.** If the `Gyaml` is not `Obj_Heart_Piece` or `Obj_GerudoValley_Heart_Piece`, add it to `HEART_GYAMLS` in both [heart_pickups.py](../src/oot_randomizer/heart_pickups.py) and [scan_loose_hearts.py](../scripts/scan_loose_hearts.py). Otherwise the scanner will skip it.

3. **Name the slot.** Use `<Region> Heart Piece N`, where `N` continues the count for that region (for example `GerudoValley Heart Piece 1`).

4. **Add the scene targets.** In `_HEART_TARGETS` in [heart_pickups.py](../src/oot_randomizer/heart_pickups.py), list each scene copy that holds the piece as `(scene file, Actors index)`. Child and Adult indexes can differ (GerudoValley is 24 for Adult and 18 for Child), so read each file separately. A piece that exists in only one age gets one entry.

5. **Add the logic line.** In the region TOML under `logic/world/overworld/` (for example [GerudoValley.toml](../logic/world/overworld/GerudoValley.toml)), add the slot under `[regions."<Region>".locations]`:

   ```toml
   "GerudoValley Heart Piece 1" = "true"  # loose Obj_GerudoValley_Heart_Piece, both ages
   ```

   Use `is_child` or `is_adult` for a piece that only one age can reach. Use `true` for a free pickup.

6. **Keep the reference list in sync.** Regenerate `loose_heart_pieces.json` with the scanner (step 1), or edit it by hand to match `_HEART_TARGETS`.

7. **Update the tests.** `tests/test_heart_pickups.py` checks the slot count. Update it when you add a piece.

8. **Verify.**

   ```
   python -m oot_randomizer.cli logic check
   python -m unittest tests.test_heart_pickups tests.test_world_logic tests.test_shopsanity
   ```

   Then build a seed and check in-game that the piece gives the planned item. Pieces with a non-pickupable item (dungeon items, songs, tokens) are never assigned to a heart slot.

## Tracker

Status key: **done** means in `_HEART_TARGETS` and the region TOML. **Open** means still to find or add.

| Slot | Region TOML | Status |
|------|-------------|--------|
| DeathMountainCrater Heart Piece 1 | DeathMountainCrater.toml | done |
| DeathMountainCrater Heart Piece 2 | DeathMountainCrater.toml | done |
| DeathMountainTrail Heart Piece 1 | DeathMountainTrail.toml | done |
| DesertColossus Heart Piece 1 | DesertColossus.toml | done |
| GerudoValley Heart Piece 1 | GerudoValley.toml | done (`Obj_GerudoValley_Heart_Piece`) |
| Graveyard Heart Piece 1 | Graveyard.toml | done |
| LakeHylia Heart Piece 1 | LakeHylia.toml | done (adult copy, stored in `HyruleField_Adult_Static`) |
| LakeHylia Fire Arrow 1 | LakeHylia.toml | done (`Obj_Arrow_Fire`, adult copy, always randomized, not gated by `shuffle_heart_pieces`) |
| LonLonRanch Heart Piece 1 | LonLonRanch.toml | done (child copy, stored in `HyruleField_Child_Static`) |
| KakarikoVillage Heart Piece 1 | KakarikoVillage.toml | done |
| KakarikoVillage Heart Piece 2 | KakarikoVillage.toml | done |
| ZoraFountain Heart Piece 1 | ZoraFountain.toml | done |
| ZoraFountain Heart Piece 2 | ZoraFountain.toml | done |
| ZoraRiver Heart Piece 1 | ZoraRiver.toml | done |
| ZoraRiver Heart Piece 2 | ZoraRiver.toml | done |

### Open

- **HyruleField Static room 0 #0 (Obj_Heart_Piece).** The rule in `HyruleField.toml` is commented out, so the location is not in any region and the planner treats it as always reachable. Decide whether it is a real loose piece, then either add the logic line or confirm it is a duplicate of Heart Piece 1 or 2.
- **Goron large-pot drop** (`EventGoronLargePotDropPrize` in `Dm_Goron_0045`). Not a loose actor. Handled separately.
- **Dodongo's Cavern heart container** (`Actors[585]` in the Dodongo static file). Not a loose actor. Handled separately.
- **Market minigame rewards.** Not included.
