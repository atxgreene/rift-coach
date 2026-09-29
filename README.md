# Macro Goblin

<p align="center">
  <img src="assets/readme-hero.png" alt="Macro Goblin hero" width="900">
</p>

<p align="center"><strong>Tiny goblin. Big macro.</strong></p>

Macro Goblin is a local, read-only League of Legends macro companion. It speaks and displays lightweight reminders for objective timers, item adaptation, CS pace, deaths, and simple pattern reads.

It does **not** need an LLM to run. The default mode is deterministic Python logic.

## What it feels like

A sharp duo partner on your second monitor: quick timers, one useful focus line, clear item plan, and no fake confidence. Funny name, serious safety posture.

## Safety posture

Macro Goblin uses Riot's local Live Client Data API and Riot Data Dragon only.

It does **not**:

- read League process memory
- inject DLLs
- hook DirectX
- sniff packets
- automate mouse/keyboard input
- install low-level keyboard hooks
- upload match data

The overlay hotkeys use Windows `RegisterHotKey`, and the local dashboard binds to `127.0.0.1` only.

See [`docs/SAFETY.md`](docs/SAFETY.md) for details.

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

## Quick start

Before queueing, run the doctor:

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

## Troubleshooting

See [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).
