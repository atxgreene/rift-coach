"""Print the CHANGELOG section for the current version, plus install instructions (release body)."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import lol_coach  # noqa: E402

version = lol_coach.__version__
with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as handle:
    text = handle.read()
section = ""
marker = "## %s" % version
if marker in text:
    section = text.split(marker, 1)[1]
    section = section.split("\n## ", 1)[0]
    section = section.split("\n", 1)[1] if "\n" in section else ""

notes = ("""## Install

**Windows installer (recommended):** download **MacroGoblin-Setup.exe** below and run it. No admin rights needed.

**One command (PowerShell):**
```powershell
irm https://atxgreene.github.io/rift-coach/install.ps1 | iex
```

**Portable:** unzip **MacroGoblin-Portable.zip** anywhere and run `MacroGoblin.exe`.

Windows may show *"Windows protected your PC"* the first time, because the app is new and not code-signed yet. Click **More info > Run anyway**. Checksums are in `SHA256SUMS.txt`.

Set League to **Borderless** (Settings > Video > Window Mode) so the overlay can show.

## What's new in %s
%s""" % (version, section.strip()))
out = sys.argv[1] if len(sys.argv) > 1 else None
if out:
    with open(out, "w", encoding="utf-8") as handle:  # UTF-8 regardless of the console code page
        handle.write(notes)
else:
    sys.stdout.buffer.write(notes.encode("utf-8"))
