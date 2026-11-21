# NPC and minigame item grants (Stages A and B)

Stage A shuffles the bag, quiver, scale and bombchu-bundle items that NPCs and minigames hand
over. Stage B adds the Biggoron Sword reward. It follows the same pattern as `event_items.py`:
the planner picks an item for each location, and `npc_grants.py` repoints the item-name
parameter inside the evfl event flow.

## Mechanisms

| Mechanism | Flow node | Parameter |
| --- | --- | --- |
| Hand-over | `NpcCommon_HandOver_NpcToPlayer_NoDisplay` sub-flow | `ReveiveItem` (sic) |
| GetInEvent | `GetInEvent_NotTurn`, `_NotTurn_PosCamera`, `_NotLookatObjectTurnOff`, `_NotTurn_NotNpc` | `ActorName` |

Only these parameters change. Model, LOD and XLink references keep the vanilla actor.

## Locations

| Flow | Vanilla item | Logic region | Logic (summary) |
| --- | --- | --- | --- |
| MiniGame_HitTarget (Shooting Gallery, child) | Bullet Bag Large (2nd upgrade) | Market | child + Slingshot (flow forced to this slot, see below) |
| MiniGame_HitTarget (Shooting Gallery, adult) | Quiver Medium | KakarikoVillage | adult + Bow |
| MiniGame_BombchuBowling | Bomb Bag Large | Market | Bomb Bag and Bomb Bag Medium (Medium comes from the Goron child slot) |
| MiniGame_BombchuBowling | Bombchu Bundle Medium | Market | true |
| MiniGame_Fishing | Golden Scale / Heart Piece | LakeHylia | true |
| MiniGame_Diving | Silver Scale | ZoraRiver | true |
| Minigame_HorsebackArchery | Quiver Large | GerudoFortress | adult + Bow. Every win gives Large, then the heart piece (Event349). The Medium grant is removed from this minigame. |
| LostWood_ScrubForestStageElder_SkullMaskFirst | Stick Bag Medium | LostWood | child + Deku Sticks |
| LostWood_ScrubForestStageElder_TrueMaskFirst | Nut Bag Medium | LostWood | child + Deku Nuts |
| Enemy_Scrub_Business_Common (Business Scrub bag sales) | Stick Bag Large / Nut Bag Large | LostWood | child + Deku Sticks (stick), child + Deku Nuts + Bomb Bag (nut) |
| Dm_LostWood_0040 (Lost Woods scrub target) | Bullet Bag Medium (1st upgrade) | LostWood | child + Slingshot (flow forced to this slot, see below) |
| Npc_Goron_Biggoron_Adult | Biggoron Sword | DeathMountainTrail | adult, Ice_Cavern_Clear, (can_play(Eponas_Song) or Longshot), (has_bombs or Megaton_Hammer) |
| MiniGame_FrogTenors (Frog Choir, Song of Storms) | Heart Piece | ZoraRiver | child, Zelda's Lullaby, Sarias, Epona's, Sun's, Song of Time (the Frog Choir requirement) |
| MiniGame_FrogTenors (Frog Choir, insect repellent game) | Heart Piece | ZoraRiver | same as the Song of Storms heart |

The Biggoron row is the final reward of the Biggoron chain. The chain itself stays fixed (Option A).
Only the item handed over at the end is randomized. Its logic is the union of the chain gates:
Kokiri and Kakariko are adult, Gerudo Valley needs Epona or Longshot, Lake Hylia is adult,
Zora's Domain needs the Ice Cavern (`Ice_Cavern_Clear`), and Death Mountain Trail needs a
bomb bag or hammer. `Ice_Cavern_Clear` is a new event in `IceCavern.toml`, set to
`is_adult and Zeldas_Lullaby`. It is entry-only: the Blue Fire clause is dropped because
Blue Fire and bottles do not resolve in logic.

Each upgrade is its own logic identifier. The base bag or quiver is required wherever the
upgrade needs it. The small-bag identifier is never reused for an upgrade.

The base requirements (child/adult, Bow, Slingshot, Deku Sticks/Nuts) are design choices
for Stage A, not values read from the game. The region assignments come from memory of the
game's layout; no repo data confirms them. The repo has no scene mapping for these flows.

Talon's milk (`Minigame_FindOutCucco`) is excluded: its grant is a bottle item.
`MiniGame_HitTarget` is the shooting gallery: its flags are `MiniGame_HitTarget_HrlCity_*`
(Market, child) and `MiniGame_HitTarget_Kakariko_*` (Kakariko, adult). `Npc_Hylia_067_Shop_Child`
(bowling) is not in the NUP index, so bowling is analyzed from `MiniGame_BombchuBowling` only.

## Progressive bullet bag games

The Lost Woods scrub target and the Market shooting gallery each pay out once (flags
`LostWood_HitTargetOfDekuScrub_FirstClear` and `MiniGame_HitTarget_HrlCity_Get_BulletBag`).
Which prize they give depends on whether the Medium bullet bag is already owned. In these
bool and pouch switches, case 0 is "true":

| Flow | Switch | Case 0 (Medium owned) | Case 1 (not owned) | Kept |
| --- | --- | --- | --- | --- |
| Dm_LostWood_0040 | Event83 `IsGet.Item_BulletBag_Medium` | Event17, Large | Event30, Medium | Event30 |
| MiniGame_HitTarget | Event70 pouch `Item_BulletBag_Medium` | Event378, Large | Event241, Medium | Event378 |

With randomized items, the branch taken would depend on where the real Medium bag was found,
so one of each game's two slots would never pay out. `fix_progressive_branches` points both
cases of each switch at the kept grant (`PROGRESSIVE_BRANCHES` in `npc_grants.py`), so Lost
Woods is always the 1st upgrade slot and the Market gallery always the 2nd. The kept grant only
has to be reachable from the switch, so the Goron child's switch (Event14) skips its Small bag
checks and talk (Event12/13/21/54) and goes straight to the Medium grant (Event58). The other
two slots are not locations, and their grant events become unreachable. The patch runs whenever
NPC items are shuffled. `Dm_LostWood_0040` Event38 (which bag model to show) is cosmetic and is
left alone.

## Business Scrub bag sales

`Enemy_Scrub_Business_Common` sells the stick and nut bags for 40 rupees each. Each sale is a
`SimpleShopSub_Scrub_Business_OneTime` node whose `ActorName` is the bag granted. The Medium
bag sales were removed. Each bag switch now pins the Large sale:

| Switch | Case 0 (Medium owned) | Case 1 (not owned) | Kept |
| --- | --- | --- | --- |
| Event319 `PouchSystemActor.EventQueryIsExistInPouch` Stick Bag Medium | Event317, Stick Bag Large | Event322, Stick Bag Medium | Event317 |
| Event323 `PouchSystemActor.EventQueryIsExistInPouch` Nut Bag Medium | Event318, Nut Bag Large | Event326, Nut Bag Medium | Event318 |

`Event554` (`IsGet.Item_DekuStick`) used to send a player who already has the Deku Stick
straight to the Medium stick sale (Event555). Its true case is now re-pointed to Event319, so
both paths go through the pinned switch (`CASE_REROUTES` in `npc_grants.py`). Event322, Event326
and Event555 become unreachable.

Both Large bags are randomized locations in `LostWood`. The stick bag needs child and Deku
Sticks. The nut bag needs child, Deku Nuts and Bomb Bag. The Large bags no longer need a
Medium bag, because the Medium sale is gone from the scrub. The Lost Woods scrub's own
Medium and Large bags stay as they were. The Lost Woods scrub's Large bags are not randomized: see
the Lost Woods section below.

The scrub's flow is shared by every Business Scrub instance that loads
`Enemy_Scrub_Business_Common`. The randomized bags therefore show up in every such scrub, not only
the Lost Woods one. Confirm in-game whether the other scrubs also sell bags.

The shelf still shows the vanilla bag names and models, and the `Scrub_Business_TempItemName_00`
string checks (Event314 to Event316) still compare against the vanilla Medium names. Test in-game.

## Biggoron Business Scrub sale (Stage B)

`Enemy_Scrub_Business_Dream` also sells the Biggoron Sword for 1000 rupees, which would
bypass the randomized grant. `disable_scrub_biggoron_sale` repoints Event42's
"not owned" case past that sale (Event46) to Event47, so Event46 is unreachable. The Giant's
Knife sale (Event45, 300 rupees) is kept. The patch is applied only when NPC items are shuffled.

## Din's Fire fairy (already-received check)

The Great Fairy in `Dm_FairyFountain_Din` asks for 25 rupees to grant Din's Fire. Event78 gated
the offer on `IsGet.Item_DinFire`, which is only set for the vanilla item. After a randomized
grant, the fairy asked again on every visit.

`patch_din_fairy_received` in `npc_grants.py` fixes this:

- Event78 reads a custom bool, `Rando_Din_FairyGrant_Received` (`DIN_FAIRY_RECEIVED_BOOL`),
  registered in GameDataList by `add_npc_grant_bools`.
- A set-True write to that bool is inserted before the grant (Event212) by
  `insert_bool_write_before` in `game_flags.py`.
- A second set-True write sets the vanilla `IsGet.Item_DinFire` flag, inserted between the first
  write and the grant. Every other flow that reads `IsGet.Item_DinFire` (the owl, Death Mountain,
  scrubs, Goron, Gerudo, TriForce) therefore sees Din's Fire as owned once the fairy has handed
  over its randomized item, with no per-flow edits.

The bool is registered only when the Din's Fire fairy slot is randomized. The fairy's own check
stays on the custom bool, so a Din's Fire elsewhere (for example in a chest) does not hide the
fairy's offer.

The 25-rupee offer lives only on the first-meeting path (`FirstTime`, reached through Event32's
MeetFirst switch). Once the fairy has been met, Event78's not-received case used to go to
RecoverSequence, which never offers the item, so the randomized item could be unreachable. The
patch repoints that case at the `FirstTime` subflow (Event334) so the offer is shown again until the
item is handed over.

## Slingshot hand-over

The vanilla Slingshot pickup gives the Small Bullet Bag with the weapon. A hand-over or GetInEvent
grant gives only the weapon, so a randomized Slingshot would arrive without its bag. `add_slingshot_bag`
inserts a silent `PouchSystemActor` add of `Item_BulletBag_Small` before each Slingshot grant. It runs
after `fix_progressive_branches`, so every switch path into the grant goes through the add.

## Gates not converted (for Stage B)

These checks read the game's own state and are left alone. They need a decision when the
granted item moves. `Dm_LostWood_0040` Event83 and the shooting gallery's Event70 are handled
by the progressive bullet bag fix above.

- Owns-Din's-Fire checks on `IsGet.Item_DinFire` in other flows (Dm_DeathMtTrail_0025 Event113,
  Dm_SY_BancChange_EscapeDungeon, Enemy_Scrub_Business_Common Event407 and Event435,
  Enemy_Scrub_Business_Seed Event147, Npc_Gerudo_012 Event37, Npc_Goron_008_Child Event57,
  Npc_Kaepora_DeathMountainTrail Event4, TriForcePoint Event8 and Event137) now follow the fairy's
  grant too, because of the flag write above. Their logic gates in the TOMLs should be checked to
  match, since they open after the fairy visit, not after Din's Fire is found elsewhere.

- Pouch queries (`PouchSystemActor.EventQueryIsExistInPouch`) for upgrade and base items:
  shooting gallery quivers (Event181: Medium owned picks the Large grant, the same
  progressive pattern as the bullet bags), bowling (Event76, Event3), scrub elder (Event30),
  Dm_LostWood (Event38, cosmetic). Horseback (Event99) is bypassed by `NEXT_REROUTES`, which
  routes Event121 and Event133 straight to the Large grant.
- Scrub bools: `LostWood_ScrubForestStage_SkullMaskEventLaunched` and
  `LostWood_ScrubForestStage_TrueMaskEventLaunched`. These gate whether the scrub grant replays.

## Frog Choir hearts (two grants in one flow)

`MiniGame_FrogTenors` pays two Heart Pieces, and both are `Obj_Heart_Piece`. They come from two
different sub-flows of the same file, so a flow-and-item key cannot tell them apart:

| Heart | Sub-flow | Event |
| --- | --- | --- |
| Song of Storms (minigame) | `GetInEvent_NotTurn_NotNpc` | Event384 |
| Insect repellent (game) | `MushiToriGame` | Event161, Event75 |

`_NPC_GRANT_GROUPS` in `npc_grants.py` lists both as `NpcSlot`s with a `group` set to the
sub-flow name. `patch_npc_grants` accepts `(group, item)` keys. A `(None, item)` key matches any
grant of that item, and a group key matches only that sub-flow. Both hearts share the Frog Choir
requirement, and they appear as separate locations in logic. The Event162/Event76 `Obj_Rupee_Blue`
grants in `MushiToriGame` are not randomized.

## Lost Woods scrub Large bags (not randomized)

The Elder scrub's Large bags (`Event32` in SkullMaskFirst, `Event31` in TrueMaskFirst) are only
reachable through the pinned `Event30` switch in the first-visit flows. `PROGRESSIVE_BRANCHES`
points every case of that switch at the Medium grant, so the Large grant is never reached. Its
logic rows were removed with the slot. Two things are still unverified in game: whether the
first-visit flow replays on a later talk (the Medium grant would then repeat, because the
randomized Medium item never enters the pouch), and whether the Large bag can be given there at all.

## Dampe's Graveyard race (approach talk)

`MiniGame_DampeRace.bfevfl.zs` (`dampe_race.py`) normally takes a different talk path when the
player already owns the Hookshot or Longshot. That path skips the first-race reward, so the
randomized Hookshot slot could never be collected. `patch_dampe_race_approach` repoints the
approach-talk pouch switches (`Event262`, `Event260`, `Event18`, `Event0`, `Event61`) at their
not-owned branch. Every player then takes the first-race talk path.

The reward order comes from the race itself: `MiniGame_DampeRace_ClearCount` 0 gives the
Hookshot slot (the randomized static room item), 1 gives the heart piece, and 2 or more give
rupees. The post-race pouch switches (`Event442`, `Event443`, `Event444`) are left vanilla.
Forcing them could skip the ClearCount increment or change the retry dialogue.

Unverified in game: the approach talk on a player with the Hookshot already, and the heart piece
on the second race.

## Windmill Song of Storms (Npc_Hylia_009_Adult)

`Npc_Hylia_009_Adult.bfevfl.zs` (`storm_song_npc.py`) awards the storm song slot through
`Dm_MelodyGet_Storm`. Its talk gate (`Event9`) and ocarina gates (`Event17`, `Event69`) read the pouch
(`IsGet.Item_Melody_StormSong`). If the song came from another location, the pouch already has it,
so the award never runs. The patch points those three gates at
`KakarikoVillage_Npc_Hylia_009_OcarinaStormSong_PlayedFront` instead. The award flow sets that flag
at its end (`After_GetStormSong` → `Event80`), so the award runs once. Case mapping is unchanged.

`Event31` (the balloon text) still reads the pouch. Only its wording is affected.

## Sheik return to child (AllSage)

`AllSage.bfevfl.zs` (`sheik_medal_gate.py`) gates Sheik's return to child on the
`AllSage_AwakeSage_Fire_Or_Forest` flag through the `MeetSheik_And_Gone` entry (`Event178`). The
vanilla flag is set only by the Fire and Forest medal flows. If either medal was randomized elsewhere,
the flag is never set and Sheik blocks a return to child that the logic allows.

The patch keeps that flag check (case 0 still goes to `Event181`). On false it runs a chain of five
pouch queries (`PouchSystemActor.EventQueryIsExistInPouch`) for `Item_Medal_Forest`, `Fire`, `Water`,
`Shadow`, and `Spirit`, in that order. Any held medal goes to `Event181`, which sets
`AllSage_MeetSheik_And_Gone`. The Light medal is not checked, because the first trip to adulthood
always gives it. The check mirrors the logic `Time_Travel_Back` (`is_adult and (has_two_medals or
Forest_Temple_Clear or Fire_Temple_Clear)`). The new check events are named `MedalCheck_<Medal>`.

Unverified in game: the chain's timing on the sage melody flows, and that the held medal is in the
pouch when `Event178` runs.

## Options

- Planner pool group `npc`, `PlanOptions.shuffle_npc_items` (default `True`).
- CLI `--no-npc-items` keeps the vanilla NPC items. These locations are not majors for
  `one_major_per_dungeon`, the same as event items.
- Logic check: 25 NPC slots (23 plain, plus the two Frog Choir hearts). The vanilla goal is reachable, and 347 of 347 locations are
  listed and reachable.

## Unverified in-game

- Biggoron grant. Its flow handles the sword by name at Event632 (`EquipmentUserRequestChangeState`)
  and Event636 (`BigGoronSword_GetAndEquipCheck`), which are name-agnostic. A non-sword item
  granted through `GetInEventItemSwordBiggoron` may equip or behave oddly. Test in-game.
- The scrub sale reroute. Check that the Business Scrub no longer offers the 1000-rupee
  Biggoron Sword, and that the Giant's Knife sale still works.
- The progressive bullet bag fix: Lost Woods should always give its slot item, and the Market
  gallery its slot item, whether or not the real Medium bullet bag is owned.
- The region assignments and `true` gates for fishing, diving and bowling.
- The base-item requirements (see above).
- Whether a moved upgrade is handled correctly by the pouch gates and scrub bools above.
- Model and cutscene mismatch, since the actor model stays vanilla.
- Whether a Medium and Large swap in the same flow is handled as the game expects.
