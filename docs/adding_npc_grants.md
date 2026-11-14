# Adding a New NPC or Event Grant

This is the process for making a new item grant randomizable: an NPC hand-over, a minigame reward, or a one-off story item. Follow the steps in order. Each step names the file or tool to use.

## 1. Find the grant node

Decode the flows with the dump tooling in the session `files\recon\` folder (`all_flows_dump.py`, or the walker pattern in `probe_bag_branches.py`). A grant is one of two shapes:

- **Hand-over:** `SUB NpcCommon_HandOver_NpcToPlayer_NoDisplay`, with the item in `ReveiveItem`.
- **GetInEvent:** `SUB Dm_SY_GetInEvent/GetInEvent_*`, with the item in `ActorName`.

Confirm the stored subflow name before using it. Some names are stored without the `Dm_SY_GetInEvent/` prefix, for example `GetInEventItemSwordBiggoron`.

Check that the subflow name is in `_GET_IN_EVENT_SUBFLOWS` in [npc_grants.py](../src/oot_randomizer/npc_grants.py). If it is not, the grant is ignored without an error.

## 2. Map the gates

For each grant, list every `SW` node that reads it:

- `GameDataActor.EventQueryIsGameDataBool` on an `IsGet.*` or progress flag.
- `PouchSystemActor.EventQueryIsExistInPouch` for owning an item.

A gate that reads the vanilla item can send a randomized item down the wrong branch. The fix is the progressive pattern (`PROGRESSIVE_BRANCHES` in `npc_grants.py`). Walk each case to see which grant it reaches before choosing a fix.

## 3. Pick the module

- Repeatable NPC or minigame rewards go in [npc_grants.py](../src/oot_randomizer/npc_grants.py).
- One-off story items (ocarinas, medallions) go in [event_items.py](../src/oot_randomizer/event_items.py), which uses `EVENT_SLOTS` and `patch_event_item`.

## 4. Register the slot in four places

1. `_NPC_GRANTS` (or `EVENT_SLOTS`), and `NPC_ITEM_DISPLAY_NAMES`.
2. `NPC_LOCATIONS` in [logic_template.py](../src/oot_randomizer/logic_template.py), with the region, requirement, and an in-game "who" label.
3. The location in the region's `[locations]` table under `logic\world\`, with the same requirement.
4. Any gate or event the requirement uses, such as `Zeldas_Letter`.

## 5. Wire the patch

[patcher.py](../src/oot_randomizer/patcher.py) groups assignments by flow and calls `replace_file`. [randomizer.py](../src/oot_randomizer/randomizer.py) drops any assignment that equals the vanilla item.

## 6. Update the tests

In [test_npc_grants.py](../tests/test_npc_grants.py):

- Update the count tests (currently 25 NPC locations).
- Add the flow to the round-trip, idempotent, and "every flow grants its slot items" tests.
- Check the region listing test.

## 7. Verify

1. Run `python -m oot_randomizer.cli logic check`. It should pass, with the new location counted.
2. Run the full test suite. Known pre-existing failures: 14 errors in `test_engine`, `test_rom_validation`, and `test_location_mapper` (`/tmp` and macOS paths).
3. Playtest. Confirm the item is given, the NPC does not repeat it, and the model is still vanilla.

## Pitfalls

- A gate on a vanilla item can make a location unreachable or pay the wrong item.
- One item can have several grant nodes (fishing has two). Patch all of them.
- If one flow grants the same item from two sub-flows (the Frog Choir gives two `Obj_Heart_Piece`s), add a second `NpcSlot` with a `group` and a `label`. Give the `NPC_LOCATIONS` key a 3-tuple `(flow, item, label)`, and key `patch_npc_grants` by `(group, item)`.
- An unknown name in logic creates `world.errors`, and that cascades into planner test failures. Fix the first error before reading the rest.

## Candidates

### Zelda's Letter

- Flow: `Dm_HrlCastle_0050`, `Event59`, `GetInEvent_Zeldaletter`, with `ActorName = Item_ZeldaLetter`.
- It is a GetInEvent grant, but `GetInEvent_Zeldaletter` is **not** in `_GET_IN_EVENT_SUBFLOWS`, so the current code would not patch it.
- It is a one-off story item, so the `event_items.py` pattern is the likely fit.
- `Dm_Kakariko_0010` also plays `Item_ZeldaLetter`. That is probably a model or animation, not a grant. Confirm before treating it as a second grant.
- Logic currently places `Zeldas_Letter` in `HyruleCastle`, and Death Mountain Trail depends on it. Moving the item means moving that dependency too.
- The letter's gates are not verified.

### Malon's Cucco Egg

- The egg's slot is `Goto_HyruleCastle: Item_WeirdEgg (npc item)`. The hatch runs in the same flow: Event55 removes the egg from the pouch, Event93 checks for `Item_AlarmCucco`, and Event20 runs `GetInEvent_EggHatche`.
- The planner only lets `Item_WeirdEgg` go to this slot (`_WEIRD_EGG_SLOT` in `planner.py`). A playtest with the egg at a scrub sale never hatched. Only Malon's slot is known to be in the hatch flow.
- Not confirmed in game. If the hatch still fails at Malon's slot, the next step is the Event93 and Event20 branch conditions.

## Open questions

- Whether `Dm_Kokiri_0000` should also be skipped with the intro (loading gate, currently left alone).
- Whether the shop bombchu rule should match the bomb rule (Bracelet not required).
- Whether the Kakariko quiver and Horseback Archery order should be confirmed before the progressive fix covers them.
