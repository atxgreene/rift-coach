# Live Client schema notes

Status: **verified against 18 real matches** (captures from 2026-09-26/27, patch 16.19, NA, ranked + bot games).
Anonymized samples live in `tests/fixtures/real/` and replay through the coach in `tests/test_real_games.py`.

## Objective clock (confirmed by real kill times)

| Objective | Config | Evidence (earliest real kill) |
|---|---|---|
| Dragon | first 5:00, respawn 5:00 | 5:54 |
| Dragon soul | first team to 4 dragons | 4 of 9 full games had a 2–2 or 1–3 split at the 4th dragon; soul came later |
| Elder | 6:00 after soul, 6:00 respawn | `DragonType: "Elder"` seen 4 times |
| Void grubs | 8:00, one camp of 3, despawn 14:45 | 8:08; always exactly 3 `HordeKill` events per game |
| Herald | 15:00, despawn 19:45 | 15:35 |
| Baron | 20:00, respawn 6:00 | 21:02 |

No Atakhan events appeared (removed in 26.1).

## `activePlayer`

`summonerName` is now `Name#TAG`. Also `riotId` (`Name#TAG`), `riotIdGameName`, `riotIdTagLine` (capital **L**), `currentGold`, `level`, `championStats` (incl. `moveSpeed`), `abilities`, `fullRunes`, `teamRelativeColors`.

## `allPlayers[]`

`championName`, `rawChampionName` (`game_character_displayname_X`), `position` (`TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY`), `team` (`ORDER/CHAOS`), `riotId`, `riotIdGameName`, `riotIdTagLine`, `summonerName`, `isBot`, `isDead`, `respawnTimer`, `level`, `scores`, `items[]`, `runes`, `summonerSpells`, `skinID`, `skinName`, `rawSkinName`.

`items[]`: `itemID`, `displayName`, `count`, `consumable`, `canUse`, `slot`, `rawDescription`, `rawDisplayName`, `price`.

- **`price` is the combine cost, not the item's value** (Trinity Force = 133). Item gold must come from Data Dragon.
- **Bot lane role quest:** finished boots leave `items[]` (Kai'Sa had Berserker's Greaves in slot 2 at 12:01; gone at 20:03). Boots are tracked as "seen once = owned".
- Gunmetal Greaves (quest upgrade) has **no `Boots` tag** in Data Dragon. Boot detection also checks names.
- Bots: `KillerName`/`VictimName` use the champion name (e.g. `"Miss Fortune"`).

## `events.Events[]`

Cumulative from `EventID 0` for the whole match, even when the coach starts at 34:32. Late join rebuilds history from it.

| Event | Fields seen |
|---|---|
| `GameStart`, `MinionsSpawning` | — |
| `ChampionKill` | `KillerName`, `VictimName`, `Assisters` |
| `FirstBlood` | `Recipient` |
| `Multikill` | `KillerName`, `KillStreak` |
| `DragonKill` | `KillerName`, `Assisters`, `DragonType` (`Fire/Water/Earth/Air/Hextech/Chemtech/Elder`), `Stolen` (**string** `"True"/"False"`) |
| `HordeKill` | one per grub, `KillerName`, `Assisters`, `Stolen` |
| `HeraldKill`, `BaronKill` | `KillerName`, `Assisters`, `Stolen` |
| `TurretKilled`, `FirstBrick` | `TurretKilled` (e.g. `Turret_TChaos_L1_P3_…`), `KillerName` |
| `InhibKilled`, `InhibRespawned` | `InhibKilled` (e.g. `Inhib_TOrder_L1_P1_…` = ORDER's inhibitor) |
| `Ace` | `Acer`, `AcingTeam` |
| `GameEnd` | **`Result`: `"Win"` / `"Lose"`** |

`KillerName` can be a raw ID: `Turret_TOrder_L2_P3_1509986696`, `SRU_*`, minions. The coach reads these as "a tower", "minions", "a jungle camp".

## API behavior

- The endpoint occasionally fails a single poll mid-game (one real game was split into three captures by this). The coach waits `disconnect_grace` (15 s) before calling a game closed, and resumes the same match after longer outages.
- A late-game frame is ~50 KB raw. Captures are now written gzipped (`NNNN.json.gz`, ~7 KB, about 1/7 the disk).
