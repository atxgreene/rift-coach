# HANDOFF → Kestrel: Rift Coach (League of Legends live voice coach)

**From:** Claude (claude.ai session with Austin)
**To:** Kestrel — Windows heavy-compute agent, this machine
**Date:** 2026-09-25
**Priority:** Personal project, not urgent. Get it working live, then harden it.

---

## 1. Mission

Take ownership of **Rift Coach**. It's a zero-dependency Python script that runs beside League of Legends on this PC and coaches Austin by voice during matches. It reads Riot's official local Live Client Data API.

The code is written and passes a simulated game. It has **never touched a real match**. Your job is to take it from "demo works" to "trusted in ranked." Verify it against real game data, fix whatever reality breaks, and set it up as a one-click tool.

## 2. Files

Austin downloaded two files from claude.ai. Check `%USERPROFILE%\Downloads` first:

| File | Purpose |
|---|---|
| `lol_coach.py` | The whole app (~670 lines, stdlib only, Python 3.8+) |
| `run_coach.bat` | Double-click launcher; passes args through to the script |

**First action:** move both into a permanent project folder. Suggested: `%USERPROFILE%\Projects\rift-coach\`. Use the existing project convention on this machine if one exists. Init a git repo there. If there's no `.gitignore`, add one that excludes `*.log`, `captures/` and any `.env`.

## 3. How it works (so you don't need to reverse-engineer it)

- **Data source:** polls `https://127.0.0.1:2999/liveclientdata/allgamedata` every 1s. The cert is self-signed, so the script uses an unverified SSL context **for localhost only**. The endpoint only responds while a match is loaded. The script waits and retries until it does.
- **Static data:** at startup it pulls item costs and champion AP/AD ratings from Riot's Data Dragon (`ddragon.leagueoflegends.com`). If that fails it degrades gracefully: it falls back to in-game item prices and skips the comp read.
- **Voice:** on Windows it starts one hidden persistent PowerShell process that uses `System.Speech`. Lines are written to its stdin, which avoids the ~1s startup cost of launching per line. Pass `--no-voice` for text only.
- **Structure:**
  - `CONFIG` dict at the top: all timers and thresholds
  - `Speaker`: TTS queue
  - `DataDragon`: static data
  - `ClaudeCoach`: optional LLM tips
  - `Coach`: the brain; `tick()` runs every poll
  - `LiveClient` / `MockGame`: data sources
  - `main()`
- **Callouts:**
  - Objective timers (60s / 30s / up) for dragon, grubs, herald and baron, with respawn tracking from kill events
  - Death review: killer, respawn timer, one reflection question
  - CS/min check-ins every 180s, skipped for `UTILITY`
  - Gold-banked nudges at ≥1300 gold, 120s cooldown
  - Level 6 for Austin and for his lane opponent
  - Enemy legendary item completions
  - Team item-gold diff every 300s, plus swing alerts at ≥1.5k
  - Enemy AD/AP lean at game start
- **Claude mode (`--claude`):** needs env var `ANTHROPIC_API_KEY`. It fires on each death and every 300s. It sends a text snapshot of the scoreboard state to `claude-haiku-4-5-20251001` and speaks back a line of 25 words or fewer. It's async and never blocks the poll loop.

## 4. Verified vs. unverified

**Verified (in a Linux sandbox, simulated game):** the script runs clean end to end. Callouts fire at the right game times. Late-join replay is suppressed. Grammar is fixed. `py_compile` passes.

**NOT verified — treat as assumptions until checked against a real match:**
1. **Field names in the live JSON.**
   - Player identity matching uses `summonerName` / `riotIdGameName` / `riotId`, with the `#TAG` split off. Riot has changed these before.
   - Also check `position` values (`TOP / JUNGLE / MIDDLE / BOTTOM / UTILITY`), `rawChampionName`, `respawnTimer`, `isDead` and `items[].consumable`.
2. **Event names.**
   - The code handles `DragonKill`, `BaronKill`, `HeraldKill`, `HordeKill` (assumed to be void grubs), `ChampionKill`, `Ace`, `InhibKilled` and `GameEnd`.
   - Unknown events are ignored silently. Log every distinct `EventName` you see, especially anything for Atakhan or other newer objectives, so we can add handlers.
3. **`Stolen` field type.** The code compares it to the string `"True"`. Confirm whether the API sends a string or a boolean.
4. **Objective spawn timers.** Current values:
   - Dragon: first spawn 5:00, respawn 5:00
   - Grubs: 8:00
   - Herald: 15:00
   - Baron: first spawn 25:00, respawn 6:00

   These were written from memory and Riot changes them between seasons. **Check them against the current patch notes on the web and update `CONFIG`.**
5. **Voice on this machine.** Confirm the PowerShell TTS process actually speaks, that no console window flashes, and that voice doesn't stutter while League is running.
6. **Performance.** Confirm polling doesn't cause a measurable FPS hit or input lag. It shouldn't, since it's one localhost GET per second, but measure it.

## 5. Tasks, in order

- [ ] **T1 — Environment.** Confirm Python 3.8+ is on PATH (`python --version`). If it's missing, **ask Austin before installing anything.**
- [ ] **T2 — Demo run.** From the project folder, run `python lol_coach.py --demo --speed 20` with voice on. Confirm you hear callouts and the demo ends with "Demo complete."
- [ ] **T3 — Capture harness.** Add a `--capture` flag that writes each poll's raw JSON to `captures/<timestamp>/NNNN.json`. Throttle to every 5s to limit disk use, and always write the tick when a new event appears. This gives us real fixtures without guessing.
- [ ] **T4 — Real-game validation.** After Austin plays one match with `--capture`, diff the real schema against assumptions 1–3. Fix any mismatches. Write a short `SCHEMA_NOTES.md` recording the real field names and every `EventName` seen.
- [ ] **T5 — Replay mode.** Add `--replay captures/<dir>` so a captured game can be fed back through `Coach` at speed. Every future change can then be regression-tested without playing. Prefer this over extending `MockGame`.
- [ ] **T6 — Patch timers.** Look up the current-season objective timers and update `CONFIG`. Add a comment with the patch number and source URL. Handle any new objective the captures revealed.
- [ ] **T7 — In-game overlay (Austin wants this).** Build `overlay.py`, or an `--overlay` flag, with the spec below. Develop it against `--replay` data so you don't need live games to iterate.

  **How (the safe way):**
  - Use stdlib `tkinter`: a borderless window set to `-topmost`, with a `-transparentcolor` key so only the widgets show.
  - Make it **click-through** with `ctypes`: `SetWindowLongW(GWL_EXSTYLE, WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW)`. Mouse clicks pass through to the game, and the window stays out of alt-tab.
  - League must run in **Borderless** window mode, not exclusive Fullscreen, or the OS can't draw anything on top of it. Tell Austin to switch this in League's video settings.
  - Show/hide hotkey (default `Ctrl+Shift+O`) via `ctypes` `RegisterHotKey`. That is a normal Windows API, **not** a keyboard hook. Don't use low-level keyboard hooks or any package that installs one.
  - Threading: tkinter owns the main thread, and the coach poll loop runs in a worker thread. The worker sends UI updates through a `queue.Queue`, and the UI drains it on `after(100)`. Voice keeps working alongside.

  **What it shows (compact, semi-transparent dark panels):**
  1. **Objective timers:** dragon, grubs, herald and baron (plus any new objectives found in T4), each counting down to its next spawn. A timer turns amber under 60s and green when the objective is up.
  2. **Callout ticker:** the last 3 coach lines, fading out after about 12s. These are the same lines that get spoken.
  3. **Gold bar:** a team item-gold diff bar, with + or − and a small trend arrow.
  4. **CS meter:** current CS/min against the target, colored by pace. Hidden for supports.
  5. **Enemy spikes:** a small feed of enemy legendary completions and the lane opponent's level 6.

  **Layout rules:**
  - Nothing covers the minimap, ability bar, scoreboard, item shop area or kill feed.
  - Default is a slim column on the right edge, mid-height.
  - Position, scale and opacity live in `CONFIG`, with a separate block per resolution (1080p / 1440p).
  - Add a `--overlay-edit` mode that turns click-through off so Austin can drag panels. Positions save to `overlay_layout.json`.

  **Scope rule:** the overlay displays only what the voice coach already knows, and nothing hidden from the player.

- [ ] **T8 — Second-screen dashboard (optional, cheap win).** A `--web` flag serves the same panels from `http.server` on `localhost:8765` for a second monitor. Bind it to the LAN address only if Austin asks, so he can glance at it on his phone. It uses the same data queue as the overlay.
- [ ] **T9 — API key.** If Austin wants Claude mode, have him set `ANTHROPIC_API_KEY` himself with `setx`. **Never write the key into the script, the .bat, git, or the vault.**
- [ ] **T10 — Launcher polish.** Optional: add a desktop shortcut to `run_coach.bat` that starts voice and overlay together. A `--log` flag that writes each game's callouts to a file would help T11.
- [ ] **T11 — (Next feature, only after T1–T7 are green) Post-game report.** On `GameEnd`, write a markdown summary into the Obsidian vault under Mnemosyne. Follow existing vault conventions for folder, frontmatter and properties. Include:
  - Champion, role, result, KDA
  - CS/min at 10, 15 and 20 minutes
  - Each death with its timestamp and killer
  - Objectives taken vs. lost
  - Item-gold curve
  - **One** focus item for next game

  Over time this becomes a trend dataset.

## 6. Guardrails — non-negotiable

- **Read-only, sanctioned data only.** Use only the `127.0.0.1:2999` Live Client Data API and Data Dragon. No memory reading, DLL injection, packet sniffing, screen scraping of the game client, or input automation. Anything that looks like it could trip Vanguard is out.
- **Overlays: YES, but only as a separate window.** The overlay is its own process and window, drawn by the OS on top of League. That is the same approach Porofessor, Blitz and Mobalytics take. It **must never** hook DirectX, inject into the League process, or read game memory. That is what gets accounts banned. If a technique needs to touch the League process in any way, it's out.
- **Information scope.** Built-in callouts use only information Austin could already see on the scoreboard, from events, or on screen. Don't add anything that reveals hidden information, such as tracking enemy summoner spell or ultimate cooldowns he didn't personally observe.
- **Claude mode is the gray-area feature** under Riot's third-party policy on real-time directive advice. It stays opt-in, off by default. If this is ever distributed (e.g., via Legacy2Digital), flag Riot's current developer policy for review first.
- Ask Austin before installing packages or system software, or before touching anything outside the project folder and the vault.

## 7. Definition of done (for this handoff)

1. Both files live in a git-tracked project folder.
2. Demo runs with audible voice on this machine.
3. At least one real match is captured, and `SCHEMA_NOTES.md` documents the real fields and events.
4. All assumption mismatches are fixed, and the fix is proven by running `--replay` on the captured game.
5. `CONFIG` timers are verified against the current patch, with the source cited in a comment.
6. The overlay shows timers, the ticker, the gold bar and the CS meter over League in Borderless mode. It is click-through, toggles with the hotkey, and has no measurable FPS impact.
7. Austin can double-click `run_coach.bat` before queueing and get voice plus overlay with no further setup.

## 8. Report back

When done or blocked, give Austin a short status:
- What's green
- What broke in the real-game data and how you fixed it
- The event names discovered
- Anything that needs his decision

Keep it tight — he wants results, not a play-by-play.
