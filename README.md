# Macro Goblin

<p align="center">
  <img src="assets/readme-hero.png" alt="Macro Goblin hero" width="900">
</p>

<p align="center"><strong>Tiny goblin. Big macro.</strong></p>

Macro Goblin is a live macro coach for League of Legends. It talks in your ear and shows a small card over the game: objective timers, the dragon race, item counters, CS pace and death patterns, called at the moment they matter.

It is read-only: it uses Riot's official local game API and never touches the League client.

## Download

**[Download for Windows](https://github.com/atxgreene/rift-coach/releases/latest/download/MacroGoblin-Setup.exe)** (Windows 10/11, 12 MB, no admin rights needed)

Or install with one command in PowerShell:

```powershell
irm https://atxgreene.github.io/rift-coach/install.ps1 | iex
```

Or grab the [portable zip](https://github.com/atxgreene/rift-coach/releases/latest/download/MacroGoblin-Portable.zip) and run `MacroGoblin.exe` from anywhere.

Then set League to **Borderless** (Settings > Video > Window Mode) and play. The coach connects by itself when your match loads.

> **"Windows protected your PC"?** The app is new and not code-signed yet, so SmartScreen asks once. Click **More info > Run anyway**. Every release lists SHA-256 checksums in `SHA256SUMS.txt`, and the one-line installer checks them for you.

### The app

- Starts the coach automatically and waits for your match. The status card shows the clock, your champion, the next objective and the last callout.
- Switches for voice, the overlay, match recording, the second-screen dashboard and Start with Windows. Choose a voice and speed, and use **Test** to hear it.
- Recent matches list your last games with result, KDA and the one thing to fix. Click one to open the full note.
- **Watch a demo** plays a real (anonymized) ranked game through the coach, so you can see and hear it without queueing.
- Tells you when a new version is out. **Update now** downloads it, checks its checksum and installs it in place.

Your settings, match notes and recordings live in `%LOCALAPPDATA%\MacroGoblin` and are kept when you update or uninstall.

## What it says in game

- **Objective timers:** dragon, grubs, Herald, Baron and Elder at 60s, 30s and up, with respawn times after each kill.
- **Dragon race:** "We took Fire dragon. Dragons 2 to 1." Soul and Elder calls are based on one team reaching 4, not the total.
- **Deaths:** who got you (champion, tower or minions), your timer, and a reflection question every other death. A repeat killer or a death spiral gets called out by name.
- **Your lane:** level 6 for you and your lane opponent, CS pace when you are behind, gold banked.
- **Their spikes:** finished items from your lane opponent and their fed carry (the rest go on the overlay only).
- **Item plan:** counters for healing, armor, MR and shields, with class-aware cores for ADCs and mages.
- **After the game:** a match note in `reports\` with deaths, CS at 10/15/20, objectives, gold curve and one focus for next game.

Voice is rationed: urgent lines (timers, deaths) come first, routine lines are spoken at most every 20 seconds, and any line that is more than a few seconds late is dropped instead of spoken. Everything still shows on the overlay.

## Requirements

- Windows recommended for the overlay and built-in voice path
- Python 3.9+
- League of Legends in **Borderless** mode for the overlay
- Internet on first run for Riot Data Dragon (cached per patch after that, so later starts work offline)

No required pip packages are currently needed; the runtime is stdlib-only.

## Running from source

Python 3.9+, no pip packages needed.

```bat
python app.py                 :: the app window
```

Before queueing, you can run the doctor:

```bat
python lol_coach.py --doctor
```

Then watch the demo. It replays a real, anonymized ranked game (Kai'Sa bot lane) through the coach:

```bat
python lol_coach.py --demo --speed 20
```

To run for a real game:

```bat
run_coach.bat
```

or manually:

```bat
python lol_coach.py --overlay --capture --log
```

Start it before you queue. It will wait until the League Live Client endpoint appears in-game.

## Common commands

```bat
python lol_coach.py --doctor
python lol_coach.py --demo --speed 20 --no-voice
python lol_coach.py --demo --synthetic      # old scripted fake game
python lol_coach.py --overlay
python lol_coach.py --overlay-edit
python lol_coach.py --capture
python lol_coach.py --replay captures\<timestamp> --speed 20 --no-voice
python lol_coach.py --web
python lol_coach.py --log
python lol_coach.py --me YourSummonerName
```

`--web` binds to `127.0.0.1:8765` only. It does not listen on the LAN.

Show/hide overlay: `Ctrl+Shift+O`.
The overlay starts top-right of your main monitor. If a saved position is off every screen (unplugged monitor), it snaps back.
Move/save overlay while running: `Ctrl+Shift+M`, drag the card, then press `Ctrl+Shift+M` again to return to click-through live mode.

## Optional LLM mode

Claude mode is optional and off by default.

```bat
setx ANTHROPIC_API_KEY your_key_here
python lol_coach.py --claude
```

If `--claude` is not passed, no LLM/API call is made.

## Generated local files

These are ignored by git:

- `captures/` raw local snapshots for replay/debugging (gzipped)
- `cache/` Data Dragon item/champion data, one file per patch
- `logs/` callout logs
- `reports/` match notes
- `overlay_layout.json` local overlay position
- `__pycache__/`, `*.pyc`
- `.env`

Do not commit personal captures/logs/reports when sharing the repo.

## Verification

```bat
python -m unittest discover -s tests -p "test_*.py"
python lol_coach.py --doctor
python lol_coach.py --demo --speed 40 --no-voice
```

`tests\test_real_games.py` replays four real, anonymized matches and checks every bug found in real play (results, dragon soul, boots, grub spam, late join, disconnects, voice budget).

## Tools for tuning

```bat
python tools\replay_eval.py captures\<timestamp>          :: what the coach would say, offline
python tools\replay_eval.py captures\* --summary          :: voice lines per game, before/after a change
python tools\make_fixture.py captures\<timestamp> tests\fixtures\real\<name>.jsonl.gz
```

`make_fixture.py` replaces every Riot ID with Player1..10 and refuses to write if a real name survives.

Optional manual checks:

```bat
python tests\smoke_overlay.py
python tests\voice_check.py
```

## Brand

See [`docs/BRAND.md`](docs/BRAND.md). Generated assets live in `assets/` and are mirrored under `docs/assets/` for GitHub Pages.

## Building the Windows release

Every push to a `release/**` branch builds on a Windows runner: tests, PyInstaller app (`MacroGoblin.exe` + `MacroGoblinCLI.exe`), a smoke test (version, doctor, full demo game), the Inno Setup installer, a silent install/uninstall round trip, and screenshots. Pushing a `v*` tag that matches `lol_coach.__version__` also publishes the GitHub release with the installer, portable zip and checksums. See `.github/workflows/release.yml` and `packaging/`.

## Troubleshooting

See [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

## Legal

Macro Goblin isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc.
