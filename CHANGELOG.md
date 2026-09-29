# Changelog

## 1.2.0 - 2026-09-29

### New
- **Studio voice.** A natural-sounding neural voice (Piper) now ships inside the app and runs entirely on your PC: no account, no internet, no cost. It is the default, and it keeps the same rules as before (urgent lines first, late lines dropped). Lines are cached, so repeated calls like "Dragon in 60" play instantly. A second studio voice (Norman) is one click away in the voice menu, and your Windows voices are still listed. If the studio voice ever fails, the coach switches to the Windows voice mid-game instead of going silent.
- **Coach style: Beginner, Standard or Pro.**
  - **Beginner** adds a short reason the first couple of times a kind of call comes up ("Dragon in 60 seconds. Push your wave first, then walk over with your team.") and says who you are laning against.
  - **Standard** is the coach you know.
  - **Pro** only speaks calls that change a decision now; about 35% less talking. Everything else stays on the overlay.
- **Choose what gets spoken.** Mute any kind of callout (objectives, deaths, death questions, items and gold, CS, enemy spikes, vision, macro reads). Muted lines still show on the overlay and in your notes.
- **Report card after every game.** Farming, fighting (kill participation), survival, vision and objectives, graded A to D from the scoreboard. The game-over line says your best area and the one to work on. Remakes are not graded.
- **Your trends** in the app: your record over the last 20 games, win streaks, best champions, average grade in each area, and a tip for your weakest one.
- **Quick keys.** `Ctrl+Shift+R` repeats the last callout; `Ctrl+Shift+N` says the next objective and what to buy next. These use the same Windows hotkey call as the overlay (no keyboard hook).
- **New in-game calls:**
  - Back timing: "Dragon in 90. You have 1400 gold. Good time to back and shop."
  - Control ward and vision score reminders, three a game at most.
  - A threat read at the start: "They have 2 assassins, Zed and Kha'Zix. Ward your flanks and stay near your team."
- **Command line:** `--style`, `--mute KIND`, `--voice-name` and `--no-hotkeys`.

### Release engineering
- The Windows build downloads Piper and the voice model with pinned SHA-256 checksums.
- The smoke test fails unless the built app actually synthesizes speech (`--doctor` now checks the studio voice).
- CI runs real Piper synthesis tests on Windows.

## 1.1.0 - 2026-09-29

Macro Goblin is now a Windows app with an installer.

### New
- **The app window.** It starts the coach automatically and shows live status: clock, champion, next objective, dragon race, gold, and the last callout. It also has:
  - Pause/start and **Watch a demo** buttons
  - Switches for voice, overlay, recording, the dashboard and Start with Windows
  - Voice and speed pickers with a **Test** button
  - A list of recent matches that opens each note
  - A welcome card on first run
- **Windows installer.** `MacroGoblin-Setup.exe` installs per user with no admin prompt. It adds Start menu and desktop shortcuts and an optional start with Windows, and it comes with an uninstaller. Your data is kept.
- **One-line install:** `irm https://atxgreene.github.io/rift-coach/install.ps1 | iex`. It downloads the latest release, checks its SHA-256 and installs it silently.
- **Portable zip** for running without installing.
- **Update check.** A banner appears when a new version is out. **Update now** downloads the installer, verifies its checksum against the release's `SHA256SUMS.txt`, and upgrades in place.
- **Settings are saved** in `%LOCALAPPDATA%\MacroGoblin\settings.json`, including voice, speed, volume and CS target. The installed app keeps all its data there.
- **Command line:** `MacroGoblinCLI.exe` ships alongside the app, with every `lol_coach.py` flag.

### Improved
- **Overlay item plan** reads "Yun Tal Wildarrows · 3000g · need 1775" / "later: Infinity Edge", and no longer shows filler like "PLAN adapting". Roles show as Top/Jungle/Mid/Bot/Support.
- **Overlay logo** no longer disappears when the overlay runs inside the app.
- **Launcher window** always fits its content and stays on screen, whatever the fonts or DPI.
- **Offline first run:** a Data Dragon snapshot is bundled, so item data works even before the first download.
- **Windows polish:** only one copy runs at a time (opening it again brings the window forward), crisp text on high-DPI screens, a dark title bar and its own taskbar icon.
- **Crash reports:** crashes are written to `logs\crash-*.txt` instead of vanishing silently.

### Release engineering
- Every build runs on a real Windows runner:
  - tests
  - PyInstaller build
  - smoke test: version, doctor, and a full demo game
  - installer build
  - silent install/uninstall round trip
  - screenshots of the app, overlay and installer
- Tagged builds publish the release with checksums.

## 1.0.0 - 2026-09-28

First ship build, tuned on 18 real matches.

### Fixed (found in real games)
- **One failed API poll ended the game.** It wrote a partial report, reset all history and said "Coach online" mid-match. It now waits 15 s, and resumes the same match after longer outages.
- **Losses were saved as "unknown".** Riot sends `Result: "Lose"`.
- **False dragon soul.** Soul was counted from both teams' dragons, so a 2–2 split announced soul and switched the timer to Elder. It now counts one team reaching 4.
- **"Still no boots" when you had boots.** The bot-lane role quest moves boots out of the item list, some boots cost under 1,100 g, and Gunmetal Greaves has no Boots tag. Boots are now tracked as seen-once-owned, by tag or name.
- **Restarting mid-game** dumped about 7 callouts at once and lost earlier deaths from the report. It now rebuilds history silently, then says one "Coach synced" line.
- **"That lead just vanished"** repeated every minute (44 times across 18 games). It is now called once per collapse, only after the drop holds for two samples, since item gold jumps whenever one team shops.
- **Void grubs** were announced three times per camp. They are now grouped into one line ("We took all 3 void grubs." / "Grubs split. We took 1, they took 2.").
- **Tower deaths** read out raw IDs (`Turret_TOrder_L2_P3_…`). They now say "a tower", "minions" or "a jungle camp".
- **Inhibitor calls** now say which side lost it.
- **Mage item plan** skipped straight to Rabadon's. Mages now get class-aware cores (Malignance/Shadowflame, Rocketbelt for assassins, Liandry's/Riftmaker for battle mages) before defensive picks.
- **Shop callouts** repeated every 90 s. Each suggestion is now spoken once, with one reminder 4 minutes later.
- **Default overlay position** was a second-monitor coordinate. It now auto-places top-right of the main monitor and snaps back if off-screen.
- **The overlay module crashed on import off Windows.** It is now guarded, and the tests run anywhere.

### Improved
- **Voice queue:** urgent lines first, stale lines dropped instead of spoken late, and Windows speech waits for each sentence to finish.
- **Less talk:** 1,113 to 693 spoken lines across the same 18 games (−38%). CS, gold and routine enemy items are overlay-first.
- **Item gold** is spoken every 5 minutes as a 3-sample average instead of reacting to every shopping trip.
- **One match note per game** (`reports/<date>-<champion>-<game id>.md`) with the result, KDA and dragon race. Restarts overwrite the note instead of creating new ones.
- **Data Dragon** is cached per patch, so later starts are instant and work offline.
- **Captures** are gzipped, about 1/7 the disk.
- **`--demo`** replays a real anonymized ranked game. The old fake game is `--demo --synthetic`.
- **Download ZIP** is about 1.2 MB instead of about 35 MB. Brand art and the Pages site stay in the repo but out of the archive.
- **New tools:** `tools/replay_eval.py` and `tools/make_fixture.py`.
- **Tests:** 53 total, including 21 on four real matches, disconnects and the voice queue. CI runs them on Windows and Linux (Python 3.9 and 3.12).

### Hardened (from an independent review)
- **Stopping mid-game now writes the match note** in every case: Ctrl+C, closing the overlay, or the window. Ctrl+C under the overlay stops cleanly instead of being swallowed by Tk.
- **Rejoining after a long outage** re-syncs quietly instead of firing every timer crossed during the gap.
- **Overlay hotkeys** now run on their own thread (still `RegisterHotKey`, no keyboard hook), so Tk's event loop can't swallow presses. One bad draw can no longer freeze the overlay.
- **A file locked by OneDrive or antivirus** skips that capture frame or note instead of closing the app.
- **Voice** recovers from a crashed speech process (up to 3 tries), never lets two voices overlap, and nothing is spoken after "Game over".
