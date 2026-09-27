# Safety

Macro Goblin is designed as a read-only, local-first companion.

## Data sources

1. **League Live Client Data API**
   - URL: `https://127.0.0.1:2999/liveclientdata/allgamedata`
   - Available only while in an active League match.
   - Exposes information visible to the local player through the client/scoreboard/events.

2. **Riot Data Dragon**
   - URL: `https://ddragon.leagueoflegends.com`
   - Used for static item/champion metadata such as item names, prices, tags, and champion info.

3. **Optional Anthropic API**
   - Used only when `--claude` is passed and `ANTHROPIC_API_KEY` is set.
   - Not required for normal operation.

## What the app does not do

Macro Goblin does not:

- read or scan game process memory
- inject into the League client
- hook DirectX or render inside the game process
- sniff network packets
- automate gameplay input
- send clicks or keystrokes to League
- upload captures/logs/reports by default

## Overlay behavior

The overlay is a separate topmost Windows/Tkinter window. It uses Windows window styles for click-through behavior. League should run in **Borderless** mode; exclusive fullscreen will usually cover the overlay.

The hide/show hotkey uses Windows `RegisterHotKey`, not a low-level keyboard hook.

## Web dashboard behavior

The dashboard binds only to `127.0.0.1`. The code refuses non-localhost dashboard hosts.

## Local files

`captures/`, `logs/`, and `reports/` are local debugging artifacts. They can contain summoner names and match details. They are ignored by git and should not be shared unless intentionally anonymized.
