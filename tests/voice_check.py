"""One spoken line. Confirms the hidden PowerShell voice process starts."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lol_coach import Speaker

speaker = Speaker(voice=True)
print("mode", speaker.mode)
speaker.say("Macro Goblin voice check. If you can hear this, voice is working.")
time.sleep(4)
alive = speaker.proc is not None and speaker.proc.poll() is None
print("VOICE_PROC", "alive" if alive else "dead")
print("CREATE_NO_WINDOW", "set" if speaker.mode == "win" else "n/a")
if speaker.mode != "win" or not alive:
    raise SystemExit(2)
