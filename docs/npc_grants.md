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
| MiniGame_HitTarget (Bullseye) | Bullet Bag Medium / Large | LakeHylia | Slingshot (Large also needs Bullet Bag Medium) |
| MiniGame_HitTarget (Bullseye) | Quiver Medium / Large | LakeHylia | Bow (Large also needs Quiver Medium) |
| MiniGame_BombchuBowling | Bomb Bag Medium / Large | Market | Bomb Bag (Large also needs Bomb Bag Medium) |
| MiniGame_BombchuBowling | Bombchu Bundle Medium | Market | true |
| MiniGame_Fishing | Golden Scale | LakeHylia | true |
| MiniGame_Diving | Silver Scale | ZoraRiver | true |
| Minigame_HorsebackArchery | Quiver Medium / Large | GerudoFortress | adult + Bow (Large also needs Quiver Medium) |
| LostWood_ScrubForestStageElder_SkullMaskFirst | Stick Bag Medium / Large | LostWood | child + Deku Sticks (Large also needs Stick Bag Medium) |
| LostWood_ScrubForestStageElder_TrueMaskFirst | Nut Bag Medium / Large | LostWood | child + Deku Nuts (Large also needs Nut Bag Medium) |
| Dm_LostWood_0040 | Bullet Bag Medium / Large | LostWood | child + Slingshot (Large also needs Bullet Bag Medium) |
| Npc_Goron_Biggoron_Adult | Biggoron Sword | DeathMountainTrail | adult, Ice_Cavern_Clear, (Eponas_Song or Longshot), ((Bomb_Bag and Goron_Bracelet) or Megaton_Hammer) |

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

Talon's milk (`Minigame_FindOutCucco`) is excluded: its grant is a bottle item. The Lake
Hylia child shop flow `Npc_Hylia_019_Shop_Child` is the Bullseye NPC. `Npc_Hylia_067_Shop_Child`
(bowling) is not in the NUP index, so bowling is analyzed from `MiniGame_BombchuBowling` only.

## Biggoron Business Scrub sale (Stage B)

`Enemy_Scrub_Business_Dream` also sells the Biggoron Sword for 1000 rupees, which would
bypass the randomized grant. `disable_scrub_biggoron_sale` repoints Event42's
"not owned" case past that sale (Event46) to Event47, so Event46 is unreachable. The Giant's
Knife sale (Event45, 300 rupees) is kept. The patch is applied only when NPC items are shuffled.

## Gates not converted (for Stage B)

These checks read the game's own state, so Stage A leaves them alone. They need a decision
when the granted item moves.

- `Dm_LostWood_0040`: `Event83` checks `IsGet.Item_BulletBag_Medium`.
- Pouch queries (`PouchSystemActor.EventQueryIsExistInPouch`) for upgrade and base items:
  Bullseye (Event70, Event181), bowling (Event76, Event3), horseback (Event99),
  scrub elder (Event30), Dm_LostWood (Event38).
- Scrub bools: `LostWood_ScrubForestStage_SkullMaskEventLaunched` and
  `LostWood_ScrubForestStage_TrueMaskEventLaunched`. These gate whether the scrub grant replays.

## Options

- Planner pool group `npc`, `PlanOptions.shuffle_npc_items` (default `True`).
- CLI `--no-npc-items` keeps the vanilla NPC items. These locations are not majors for
  `one_major_per_dungeon`, the same as event items.
- Logic check: 18 NPC locations. The vanilla goal is reachable, and 349 of 349 locations are
  reachable. The Kokiri Static rupee is an unlisted known location, so the logic check reports
  348 of 349 listed.

## Unverified in-game

- Biggoron grant. Its flow handles the sword by name at Event632 (`EquipmentUserRequestChangeState`)
  and Event636 (`BigGoronSword_GetAndEquipCheck`), which are name-agnostic. A non-sword item
  granted through `GetInEventItemSwordBiggoron` may equip or behave oddly. Test in-game.
- The scrub sale reroute. Check that the Business Scrub no longer offers the 1000-rupee
  Biggoron Sword, and that the Giant's Knife sale still works.
- Whether the Bullseye NPC grant is `MiniGame_HitTarget` (assumed from "deku bullseye game").
- The region assignments and `true` gates for fishing, diving and bowling.
- The base-item requirements (see above).
- Whether a moved upgrade is handled correctly by the pouch gates and scrub bools above.
- Model and cutscene mismatch, since the actor model stays vanilla.
- Whether a Medium and Large swap in the same flow is handled as the game expects.
