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
| MiniGame_BombchuBowling | Bomb Bag Medium / Large | Market | Bomb Bag (Large also needs Bomb Bag Medium) |
| MiniGame_BombchuBowling | Bombchu Bundle Medium | Market | true |
| MiniGame_Fishing | Golden Scale | LakeHylia | true |
| MiniGame_Diving | Silver Scale | ZoraRiver | true |
| Minigame_HorsebackArchery | Quiver Large | GerudoFortress | adult + Bow + Quiver Medium. Every win gives Large, then the heart piece (Event349). The Medium grant is removed from this minigame. |
| LostWood_ScrubForestStageElder_SkullMaskFirst | Stick Bag Medium / Large | LostWood | child + Deku Sticks (Large also needs Stick Bag Medium) |
| LostWood_ScrubForestStageElder_TrueMaskFirst | Nut Bag Medium / Large | LostWood | child + Deku Nuts (Large also needs Nut Bag Medium) |
| Enemy_Scrub_Business_Common (Business Scrub bag sales) | Stick Bag Large / Nut Bag Large | LostWood | child + Deku Sticks (stick), child + Deku Nuts + Bomb Bag (nut) |
| Dm_LostWood_0040 (Lost Woods scrub target) | Bullet Bag Medium (1st upgrade) | LostWood | child + Slingshot (flow forced to this slot, see below) |
| Npc_Goron_Biggoron_Adult | Biggoron Sword | DeathMountainTrail | adult, Ice_Cavern_Clear, (can_play(Eponas_Song) or Longshot), (has_bombs or Megaton_Hammer) |

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
Woods is always the 1st upgrade slot and the Market gallery always the 2nd. The other two
slots are not locations, and their grant events become unreachable. The patch runs whenever
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
Medium and Large bags stay as they were.

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

## Gates not converted (for Stage B)

These checks read the game's own state and are left alone. They need a decision when the
granted item moves. `Dm_LostWood_0040` Event83 and the shooting gallery's Event70 are handled
by the progressive bullet bag fix above.

- Pouch queries (`PouchSystemActor.EventQueryIsExistInPouch`) for upgrade and base items:
  shooting gallery quivers (Event181: Medium owned picks the Large grant, the same
  progressive pattern as the bullet bags), bowling (Event76, Event3), scrub elder (Event30),
  Dm_LostWood (Event38, cosmetic). Horseback (Event99) is bypassed by `NEXT_REROUTES`, which
  routes Event121 and Event133 straight to the Large grant.
- Scrub bools: `LostWood_ScrubForestStage_SkullMaskEventLaunched` and
  `LostWood_ScrubForestStage_TrueMaskEventLaunched`. These gate whether the scrub grant replays.

## Options

- Planner pool group `npc`, `PlanOptions.shuffle_npc_items` (default `True`).
- CLI `--no-npc-items` keeps the vanilla NPC items. These locations are not majors for
  `one_major_per_dungeon`, the same as event items.
- Logic check: 22 NPC locations. The vanilla goal is reachable, and 347 of 347 locations are
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
