# Troubleshooting

## Run the doctor first

```bat
python lol_coach.py --doctor
```

Expected when you are **not** in a game:

```text
[WARN] League Live Client ... not reachable; normal unless you are in an active game
```

That warning is fine out of game.

## Overlay does not show

- Make sure League is in **Borderless**, not exclusive Fullscreen.
- Try edit mode and drag the card:

```bat
python lol_coach.py --overlay-edit
```

- Hide/show hotkey: `Ctrl+Shift+O`.
- Move/save hotkey: `Ctrl+Shift+M`, drag the card, then press `Ctrl+Shift+M` again to return to click-through live mode.
- If using multiple monitors, the saved position is local in `overlay_layout.json`. Delete that file to reset layout.
- A saved position that is no longer on any screen snaps back to the top-right of the main monitor automatically.

## No voice

- In the app, press **Test** next to the voice picker. The status line says which voice played ("Studio voice (Kristin)" or "Windows voice").
- Check the Windows volume mixer: the studio voice plays as **Macro Goblin**, the Windows voice as **Windows PowerShell**.
- Run the doctor from the install folder. The **Studio voice** row synthesizes a test line:

```bat
MacroGoblinCLI.exe --doctor
```

- If the studio voice fails, the coach switches to your Windows voice automatically and keeps going. If you prefer the Windows voice, pick it in the voice menu.
- Running from source: `python tools/fetch_voice.py` downloads the studio voice into `voice\`. Without it, source runs use the Windows voice.
- Quiet or muted kinds of calls: check **Spoken callouts** and **Coach style** (Pro keeps routine calls on the overlay only).
- Or run without voice: `python lol_coach.py --overlay --no-voice`. Callouts keep printing either way.

## Coach restarted mid-game / went quiet briefly

The live API sometimes fails a single poll (loading screens, heavy fights). The coach waits 15 seconds before it treats the game as over, and if the same match comes back later it picks up where it left off with the same history and the same match note. If you restart the app mid-game, it rebuilds deaths, dragons and grubs from the game's event history and says one "Coach synced" line.

## Data Dragon warning

Game data is cached per patch in `cache\`, so after one successful run the coach works offline.
If doctor says Riot Data Dragon is not reachable on a fresh install:

- Check internet access.
- Try again later; Data Dragon can be temporarily unavailable.
- The coach can still poll live game data, but item/champion metadata quality is reduced.

## Live Client not reachable in game

- Confirm you are in an active match, not just the client/lobby.
- Wait until loading has completed.
- Test the endpoint in a browser while in-game:

```text
https://127.0.0.1:2999/liveclientdata/allgamedata
```

The endpoint uses a local self-signed certificate, so browsers may show a certificate warning.

## LLM / Claude mode

LLM mode is optional. If you do not pass `--claude`, no LLM calls happen.

If you do pass `--claude`, set:

```bat
setx ANTHROPIC_API_KEY your_key_here
```

Never commit `.env` or API keys.

## "Windows protected your PC"

The app is new and not code-signed yet, so SmartScreen asks the first time. Click **More info**, then **Run anyway**. To check the download yourself, compare `Get-FileHash .\MacroGoblin-Setup.exe` with `SHA256SUMS.txt` on the release page.

## Where are my files?

Settings, match notes (`reports\`), recordings (`captures\`), logs and cached game data are in `%LOCALAPPDATA%\MacroGoblin`. The app's **Data folder** link opens it. Updating or uninstalling keeps it; delete the folder yourself to remove everything.

## The app closed or something looks wrong

- Crash details are saved to `%LOCALAPPDATA%\MacroGoblin\logs\crash-*.txt`, and the app's own log is `logs\app.log`. Attach them to a GitHub issue.
- `MacroGoblinCLI.exe --doctor` (in the install folder) checks voice, overlay support, game data and the live API.

## Uninstall

Windows Settings > Apps > Installed apps > Macro Goblin > Uninstall. Your data folder stays unless you delete it.
