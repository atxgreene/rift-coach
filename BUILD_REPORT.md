# Build report

Version 1.0.0. See `CHANGELOG.md` for what changed and why.

## Release checklist

```bat
python -m unittest discover -s tests -p "test_*.py"
python tools\replay_eval.py tests\fixtures\real\*.jsonl.gz --summary
python lol_coach.py --doctor
python lol_coach.py --demo --speed 40 --no-voice
python tests\voice_check.py        :: Windows: hear one line
python tests\smoke_overlay.py      :: Windows: click-through + hotkey
```

Voice budget: the real fixtures should stay under about 3 spoken lines per minute (`test_voice_budget`).

## Data sources

- Riot Live Client Data API: `https://127.0.0.1:2999/liveclientdata/allgamedata`
- Riot Data Dragon: `https://ddragon.leagueoflegends.com` (cached in `cache/`)
- Anthropic API only when `--claude` is passed

## Never committed

`captures/`, `logs/`, `reports/`, `cache/`, `overlay_layout.json`, `.env`. Real captures contain other players' Riot IDs. Only commit fixtures made with `tools/make_fixture.py`.
