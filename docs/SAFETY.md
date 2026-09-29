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

3. **League's own settings file (read-only)**
   - `Config\PersistedSettings.json` / `game.cfg` in the League install folder.
   - Only the minimap size and side are read, so the compact HUD strip can sit just above the minimap. The file is never written.

4. **Optional Anthropic API**
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

The overlay hotkeys (Ctrl+Shift+O cycles compact strip / full card / off, Ctrl+Shift+M moves it) and the coach quick keys (Ctrl+Shift+R, Ctrl+Shift+N, held only during a match) use Windows `RegisterHotKey`, not a low-level keyboard hook.

## Web dashboard behavior

The dashboard binds only to `127.0.0.1`. The code refuses non-localhost dashboard hosts.

## Local files

`captures/`, `logs/`, `reports/` and `cache/` are local files. They can contain summoner names and match details. They are ignored by git and should not be shared unless intentionally anonymized.

## Installer and updates

- The installer (`MacroGoblin-Setup.exe`) installs for your Windows account only, into `%LOCALAPPDATA%\Programs\Macro Goblin`. It needs no admin rights and does not touch the League client or any system folder.
- It adds a Start menu shortcut, an optional desktop shortcut, an optional "start with Windows" entry (`HKCU\...\Run\MacroGoblin`), and an uninstaller in Apps & features.
- The update check reads `https://api.github.com/repos/atxgreene/rift-coach/releases/latest`. Nothing is sent about you, your PC or your matches.
- "Update now" downloads the new installer from GitHub Releases and checks its SHA-256 against the release's `SHA256SUMS.txt`. If they don't match, nothing is installed. The one-line PowerShell installer does the same check.
- Releases are built from this repository by GitHub Actions (`.github/workflows/release.yml`) on a clean Windows runner, and are not built on anyone's personal PC.
- The executables are not code-signed yet, so Windows SmartScreen may ask once.
