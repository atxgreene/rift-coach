# Schema notes

Status: **unverified against a live match**. Do not treat these field names as confirmed until a `--capture` folder exists.

Checked 2026-09-26. Port 2999 was not read.

## Timers shipped in CONFIG

| Objective | Value | Source | Confidence |
|---|---|---|---|
| Dragon first / respawn | 5:00 / 5:00 | Dragon pit wiki; patch 26.1 said epic spawns other than Baron were unchanged | High |
| Elder | 6:00 after the 4th dragon kill | Dragon pit wiki | Medium, confirm on capture |
| Void grubs | 8:00, despawn 14:45 if untouched | Voidgrub camp wiki, updated 2026-09-23 | Medium. Baron pit wiki still says 6:00; treated as stale |
| Herald | 15:00, despawn 19:45 if untouched | Baron pit wiki + nerfplz Season 16 guide | Medium |
| Baron | 20:00 first, 6:00 respawn | Patch 26.1 notes (`25m => 20m`). Patch 26.19 notes (2026-09-22) do not change it | High |

Atakhan was removed in patch 26.1. No handler until a capture shows an event name.

## Assumed live JSON fields

These match the public Live Client Data shape and the original script. They are still assumptions.

- Identity: `summonerName`, `riotIdGameName`, `riotId`, `riotIdTagline` / `tagLine`. `#TAG` is stripped. `--me YourName` is the fallback if matching fails.
- Role: `position` of `TOP / JUNGLE / MIDDLE / BOTTOM / UTILITY`. Aliases `MID`, `BOT`, `ADC`, `SUPPORT` are accepted. Support CS checks are skipped only for `UTILITY` after aliasing.
- Champion: `championName`, `rawChampionName`.
- Combat: `isDead`, `respawnTimer`, `level`, `scores.creepScore`.
- Items: `items[].itemID`, `displayName`, `price`, `count`, `consumable`.
- Teams: compared as opaque strings (`ORDER` / `CHAOS` in the demo). Not hardcoded to blue/red.
- Events: `events.Events[]` with `EventID`, `EventName`, `EventTime`. Assumed cumulative for late-join sync. If a capture shows a sliding window, late-join objective state will be wrong until the next kill event.
- `Stolen`: accepted as boolean `true` or string `"True"`.

## Event names the code handles

`DragonKill`, `BaronKill`, `HeraldKill`, `HordeKill`, `VoidGrubKill`, `ChampionKill`, `Ace`, `InhibKilled`, `GameEnd`.

Anything else is printed once as `[event] Name` and otherwise ignored.

## Observed outside a match

On 2026-09-26 the demo and replay runs reached Data Dragon and loaded item/champion data for `16.19.1`. That is the static-data version string. It is not a live-client capture, and it does not by itself prove the in-game objective clock.

## Event names seen in a real match

None yet.

Simulated demo only, not a live client: `GameStart`, `DragonKill`, `ChampionKill`, `HordeKill`, `HeraldKill`, `Ace`, `BaronKill`.
