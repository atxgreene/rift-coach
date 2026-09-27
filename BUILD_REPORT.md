# Build report

Rift Coach is currently packaged as a local, stdlib-only Python app.

## Current launch surface

```bat
python lol_coach.py --doctor
python lol_coach.py --demo --speed 20 --no-voice
python lol_coach.py --overlay --capture --log
python lol_coach.py --web
```

`run_coach.bat` starts the recommended local mode: voice, overlay, capture, and logging.

## Data sources

- Riot Live Client Data API: `https://127.0.0.1:2999/liveclientdata/allgamedata`
- Riot Data Dragon: `https://ddragon.leagueoflegends.com`
- Optional Claude/Anthropic API only when `--claude` is explicitly passed

## Verification command set

```bat
python tests\test_shop.py
python tests\test_patterns.py
python tests\test_coach.py
python lol_coach.py --doctor
python lol_coach.py --demo --speed 40 --no-voice
```

## Packaging notes

Generated local artifacts are ignored:

- `captures/`
- `logs/`
- `reports/`
- `overlay_layout.json`
- `__pycache__/`

No API keys, captures, logs, reports, or machine-specific paths should be committed.
