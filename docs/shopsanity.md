# Shopsanity status

Status: experimental. Logic and placement are in place, but sold-out tracking and price boards are not finished. Revisit for playtesting once the sold-out fix lands.

## Current approach

- **Slots.** Seven shops, each with eight shelves (`ShopItemIndex` 0-7). The table is in `src/oot_randomizer/shop_slots.py` (`SHOPS`, `ShopSlot`).
- **Eligibility.** A shelf is randomizable only if its vanilla item matches `SHOP_ITEM_WHITELIST` (Deku Nut, Deku Stick, Shield, Armor, Heart). Deku Seed shelves are eligible only in the Kokiri Shop. Bottles, masks, arrows, bombchus, magic, and the Bazaar seed shelf are excluded.
- **Cap.** At most `MAX_SHOP_SLOTS_PER_SHOP = 4` randomized slots per shop.
- **Logic.** Shop slots are locations in the region TOML files (for example `logic/world/overworld/KokiriForest.toml`). Only slots listed there can receive randomized items.
  - Kokiri Shop, child: slots 2, 6, and 7 are open from the start. Slots 0, 1, 3, 4, and 5 require `Deku_Tree_Clear`.
- **Item rules.** Bombs and bombchus need `Bomb_Bag` and `Dodongos_Cavern_Clear`, applied by `item_requirement` and merged in `planner.py`.
- **Prices.** Picked from steps of `PRICE_STEP = 5` in `DEFAULT_PRICE_RANGE = (10, 200)`. A price of 100 or more needs a wallet upgrade (Adult's or Giant's). A price of 201 or more needs the Giant's Wallet.
- **Patching.** `src/oot_randomizer/shops.py` rewrites each shelf actor (`ShopItemIndex`, `Gyaml`), the `PriceParam` entry, and the RSDB `BuyingPrice`.
- **Verification.** `logic check` reports all locations reachable. Shop and logic tests pass (`tests/test_shopsanity.py`, `tests/test_shops.py`, `tests/test_world_logic.py`).

## Engine findings

- "Sold out" is tracked per shelf copy. Buying an item in one copy does not mark the other copies sold, and buying from a different shelf does not affect the Deku Shield slot.
- Generic shelves use native events: `EventQueryCheckIsSoldOutSelectItem` checks the state, and `EventTriggerAddShopItemSoldNum` increments it after a purchase.
- The Deku Shield shelf uses a hand-written bool, `KokiriForest_Shop_SelectActor_Shield_Deku` (Bool index 8888 in `GameDataList`). The flow sets it in `Event558`, child only.
- Game-data names are hashed with MurmurHash3 32-bit, seed 0.
- Purchase path (`DisplayShop.bfevfl`): the selection gate is `SelectItem_CheckAvailable`, and the commit is `ShopItem_Buy_SecondMove` (`EventTriggerShopItemPutInPouch`, then `EventTriggerAddShopItemSoldNum`).

## Per-slot sold-out (Kokiri Shop, in progress)

- **Save bools.** `KokiriForest_Shop_SoldOut_0`-`_7` (one per `ShopItemIndex`) are appended to `GameDataList` by `add_shop_soldout_bools` in `src/oot_randomizer/gamedata_list.py` (ResetType 9, SaveFileIndex 0). `RomPatcher.apply` writes this only when shop items are written.
- **Flow patch.** `patch_kokiri_soldout` in `src/oot_randomizer/shop_soldout.py` rewrites `DisplayShop.bfevfl`:
  - Select gate: `SelectItem_CheckAvailable` checks the Kokiri session bool (`KokiriForest_Shop_Talking`), then the selected slot's bool. A sold slot goes to `Event312` (not available).
  - Buy mark: `ShopItem_Buy_SecondMove` checks the session bool, then sets the selected slot's bool to True before `Event268`.
  - Other shops and the native sold-out counter are unchanged. Idempotent.
- **Tests.** `tests/test_shop_soldout.py` checks the rewired entries, all eight gates and marks, the added-event count, and idempotence. `tests/test_shopsanity.py` checks the patched flow in the synthetic NUP.
- **Unverified.**
  - Save layout: `SaveDataSize[0]` and `AllDataSaveSize` grow by one byte if bools are bit-packed (eight bits). Byte-packing would be +8. A new save file is required.
  - Native callers: `SelectItem_CheckAvailable` and `ShopItem_Buy_SecondMove` are assumed to run on every select and buy.
  - The adult Kokiri NPC flow is assumed to use the same session bool. It has not been extracted.
  - The board still shows the native counter, so a sold slot can look in stock while the purchase is blocked.

## Still to do

1. **Sold-out fix, in-game test.** Generate a seed with a fresh save. Buy a randomized Kokiri item, then confirm the slot is blocked, the child and adult copies behave the same, and other shops are unaffected. Then extend the per-slot approach to the other six shops.
2. **Price display and charge.** The shelf shows the old price, and that is what gets charged. Swap in the fixed price boards (3, 5, 8, 10, 15, 20, 30, 50) and confirm the board controls the charge too.
3. **Slot cap.** Decide whether `MAX_SHOP_SLOTS_PER_SHOP` should rise from 4 to 8.
4. **Regenerate and retest.** Build a new seed ROM after the bomb, seed, and price changes. Retest in-game.
5. **Giant's Wallet.** Not yet tested in-game (late game).
6. **Business Scrubs.** The bag sales are done for the stick and nut bags. Both Large bags are randomized and the Medium sales are removed. See `npc_grants.md`. The Biggoron Sword sale is still disabled (it would bypass the randomized Biggoron grant), and the Giant's Knife sale is kept.
7. **Excluded shelves.** Widen the whitelist (bottles, masks, bombchus, arrows, magic) after playtesting.
