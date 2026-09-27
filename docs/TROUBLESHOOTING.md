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
- If using multiple monitors, the saved position is local in `overlay_layout.json`. Delete that file to reset layout.

## No voice

- Run:

```bat
python tests\voice_check.py
```

- Or run without voice:

```bat
python lol_coach.py --overlay --no-voice
```

On Windows, voice uses PowerShell/System.Speech. If that fails, the app keeps printing callouts.

## Data Dragon warning

If doctor says Riot Data Dragon is not reachable:

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
