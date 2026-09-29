"""Studio voice: offline neural text-to-speech (Piper) shipped inside the app.

Everything runs on this PC. The app starts one Piper process per session, feeds it a line
of text, and plays the WAV it writes. Lines are cached on disk by text, so repeated calls
("Dragon in 60") are instant after the first time.

Layout (inside the installed app, or the repo after `python tools/fetch_voice.py`):
  voice/piper/piper(.exe) + its DLLs and espeak-ng-data/
  voice/models/<id>.onnx + <id>.onnx.json     bundled voice
  %LOCALAPPDATA%/MacroGoblin/voices/           voices downloaded later from the app

Piper: MIT licence, https://github.com/rhasspy/piper
Voices: public-domain LibriVox recordings, https://huggingface.co/rhasspy/piper-voices
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave

ROOT = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
WINDOWS = sys.platform.startswith("win")
PREFIX = "studio:"

PIPER_RELEASE = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/"
PIPER_BUILDS = {
    "win": ("piper_windows_amd64.zip", "f3c58906402b24f3a96d92145f58acba6d86c9b5db896d207f78dc80811efcea"),
    "linux": ("piper_linux_x86_64.tar.gz", "a50cb45f355b7af1f6d758c1b360717877ba0a398cc8cbe6d2a7a3a26e225992"),
}
VOICE_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/"
# id: (label, description, onnx sha256, json sha256, MB). Both are public domain and trained
# from scratch on LibriVox recordings (see each voice's MODEL_CARD).
VOICES = {
    "en_US-kristin-medium": ("Kristin", "Clear US English, female",
                             "5849957f929cbf720c258f8458692d6103fff2f0e3d3b19c8259474bb06a18d4",
                             "5681426d4aead22195de70531eeeeddb46493cfaffc5764b2ea3db73428b651c", 63),
    "en_US-norman-medium": ("Norman", "Calm US English, male",
                            "b9739443232a80a59c7d18810dd856899bf16a7964725f5ab81ea49b1351cb71",
                            "6c2db7f558a4a8deb9fe822583c1c5105f6c4e834dd0f9de8ad17a888ee9fe1d", 63),
}
BUNDLED = "en_US-kristin-medium"
CACHE_LIMIT = 600  # cached lines kept on disk (about 60 MB at most)


def _data_dir():
    try:
        import lol_coach
        return lol_coach.DATA
    except Exception:
        return ROOT


def piper_exe():
    path = os.path.join(ROOT, "voice", "piper", "piper.exe" if WINDOWS else "piper")
    return path if os.path.isfile(path) else None


def model_dirs():
    return [os.path.join(ROOT, "voice", "models"), os.path.join(_data_dir(), "voices")]


def model_path(voice_id):
    for folder in model_dirs():
        onnx = os.path.join(folder, voice_id + ".onnx")
        if os.path.isfile(onnx) and os.path.isfile(onnx + ".json"):
            return onnx
    return None


def installed():
    """Studio voice ids usable right now (engine present and model on disk), bundled first."""
    if not piper_exe():
        return []
    found = [vid for vid in VOICES if model_path(vid)]
    for folder in model_dirs():
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                vid = name[:-5] if name.endswith(".onnx") else None
                if vid and vid not in found and model_path(vid):
                    found.append(vid)
    return sorted(found, key=lambda vid: (vid != BUNDLED, vid))


def available():
    return bool(installed())


def label(voice_id):
    return VOICES.get(voice_id, (voice_id,))[0]


def is_studio(name):
    return (name or "").startswith(PREFIX)


def resolve(name):
    """Settings voice_name -> studio voice id to use, or None for a Windows voice.

    "" (the default) means the best voice available: the studio voice when it is installed.
    """
    have = installed()
    if not have:
        return None
    if is_studio(name):
        wanted = name[len(PREFIX):]
        return wanted if wanted in have else have[0]
    return have[0] if not name else None


def length_scale(rate):
    """App speed (-10..10, Windows scale) -> Piper length scale (smaller is faster)."""
    return round(max(0.6, min(1.5, 1.0 - 0.05 * int(rate))), 2)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url, dest, sha256, progress=None, opener=urllib.request.urlopen):
    """Download to dest via a temp file; keep it only if the SHA-256 matches."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    digest = hashlib.sha256()
    with opener(urllib.request.Request(url, headers={"User-Agent": "MacroGoblin"}), timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp, "wb") as out:
            while True:
                block = resp.read(1 << 16)
                if not block:
                    break
                out.write(block)
                digest.update(block)
                done += len(block)
                if progress and total:
                    progress(done / float(total))
    if digest.hexdigest() != sha256:
        os.remove(tmp)
        raise ValueError("checksum mismatch for " + os.path.basename(dest))
    os.replace(tmp, dest)
    return dest


def download_voice(voice_id, progress=None, folder=None):
    """Fetch one of the listed voices into the user's data folder (checksum verified)."""
    _label, _desc, onnx_sha, json_sha, _mb = VOICES[voice_id]
    folder = folder or os.path.join(_data_dir(), "voices")
    speaker = voice_id.split("-")[1]
    url = VOICE_BASE + "%s/medium/%s.onnx" % (speaker, voice_id)
    download(url + ".json", os.path.join(folder, voice_id + ".onnx.json"), json_sha)
    download(url, os.path.join(folder, voice_id + ".onnx"), onnx_sha, progress)
    return os.path.join(folder, voice_id + ".onnx")


def scale_volume(data, volume):
    """16-bit PCM bytes scaled to volume percent."""
    if volume >= 100:
        return data
    import array
    samples = array.array("h")
    samples.frombytes(data[: len(data) - len(data) % 2])
    if sys.byteorder == "big":
        samples.byteswap()
    factor = max(0, volume) / 100.0
    samples = array.array("h", (int(s * factor) for s in samples))
    if sys.byteorder == "big":
        samples.byteswap()
    return samples.tobytes()


def wav_seconds(path):
    with wave.open(path, "rb") as handle:
        return handle.getnframes() / float(handle.getframerate() or 22050)


class Player:
    """Plays a WAV file and waits for it, stoppable from another thread."""

    def __init__(self):
        self.proc = None
        self._stop = threading.Event()
        self.command = None
        if not WINDOWS:
            for cmd in (["afplay"], ["paplay"], ["aplay", "-q"]):
                if shutil.which(cmd[0]):
                    self.command = cmd
                    break

    @property
    def ok(self):
        return WINDOWS or self.command is not None

    def play(self, path):
        self._stop.clear()
        seconds = wav_seconds(path)
        if WINDOWS:
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            self._stop.wait(seconds + 0.05)
            if self._stop.is_set():
                winsound.PlaySound(None, 0)
            return
        self.proc = subprocess.Popen(self.command + [path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.proc.wait(timeout=seconds + 5)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def stop(self):
        self._stop.set()
        if WINDOWS:
            try:
                import winsound
                winsound.PlaySound(None, 0)
            except Exception:
                pass
        elif self.proc is not None and self.proc.poll() is None:
            self.proc.kill()


class Studio:
    """One Piper process for the session. synth(text) -> path of a cached WAV."""

    def __init__(self, voice_id, rate=1, volume=100, cache_dir=None, exe=None):
        self.voice_id = voice_id
        self.model = model_path(voice_id)
        self.exe = exe or piper_exe()
        if not self.model or not self.exe:
            raise FileNotFoundError("studio voice not installed")
        self.length = length_scale(rate)
        self.volume = max(0, min(100, int(volume)))
        self.cache = cache_dir or os.path.join(_data_dir(), "cache", "voice")
        os.makedirs(self.cache, exist_ok=True)
        self.work = tempfile.mkdtemp(prefix="mg-voice-")
        self.proc = None
        self.lock = threading.Lock()
        self.player = Player()

    def key(self, text):
        raw = "%s|%s|%s|%s" % (self.voice_id, self.length, self.volume, text)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _start(self):
        if self.proc is not None and self.proc.poll() is None:
            return self.proc
        cmd = [self.exe, "--model", self.model, "--output_dir", self.work,
               "--length_scale", str(self.length), "--sentence_silence", "0.1", "--quiet"]
        kwargs = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                      text=True, encoding="utf-8", cwd=os.path.dirname(self.exe), bufsize=1)
        if WINDOWS:
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        self.proc = subprocess.Popen(cmd, **kwargs)
        return self.proc

    def warm(self):
        """Start Piper and load the model now, so the first real callout is not delayed."""
        with self.lock:
            self._start()

    def synth(self, text, timeout=20):
        text = " ".join((text or "").split())
        if not text:
            return None
        cached = os.path.join(self.cache, self.key(text) + ".wav")
        if os.path.isfile(cached):
            return cached
        with self.lock:
            proc = self._start()
            proc.stdin.write(text + "\n")
            proc.stdin.flush()
            result = {}

            def read():
                result["line"] = proc.stdout.readline()

            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            reader.join(timeout)
            out = (result.get("line") or "").strip()
            if not out or not os.path.isfile(out):
                self.kill()
                raise RuntimeError("studio voice produced no audio")
        self._store(out, cached)
        return cached

    def _store(self, produced, cached):
        if self.volume < 100:
            with wave.open(produced, "rb") as src:
                params, frames = src.getparams(), src.readframes(src.getnframes())
            with wave.open(cached + ".tmp", "wb") as dst:
                dst.setparams(params)
                dst.writeframes(scale_volume(frames, self.volume))
            os.remove(produced)
            os.replace(cached + ".tmp", cached)
        else:
            shutil.move(produced, cached)
        self._trim()

    def _trim(self):
        try:
            files = [os.path.join(self.cache, n) for n in os.listdir(self.cache) if n.endswith(".wav")]
            if len(files) > CACHE_LIMIT:
                files.sort(key=os.path.getmtime)
                for path in files[: len(files) - CACHE_LIMIT]:
                    os.remove(path)
        except OSError:
            pass

    def speak(self, text):
        path = self.synth(text)
        if path:
            try:
                os.utime(path, None)  # keep recently used lines in the cache
            except OSError:
                pass
            self.player.play(path)

    def kill(self):
        if self.proc is not None:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            try:
                self.proc.kill()
                self.proc.wait(5)
            except Exception:
                pass
            for stream in (self.proc.stdout,):
                try:
                    stream.close()
                except Exception:
                    pass
            self.proc = None

    def close(self):
        self.player.stop()
        self.kill()
        shutil.rmtree(self.work, ignore_errors=True)


def self_test(text="Macro Goblin studio voice check.", voice_id=None):
    """Synthesize one line without playing it. Returns (ok, detail). Used by --doctor and CI."""
    voice_id = voice_id or resolve("")
    if not voice_id:
        return False, "studio voice not installed (engine %s)" % ("found" if piper_exe() else "missing")
    started = time.monotonic()
    studio = Studio(voice_id, cache_dir=tempfile.mkdtemp(prefix="mg-voice-test-"))
    try:
        path = studio.synth(text)
        seconds = wav_seconds(path)
    except Exception as exc:
        return False, "%s: %s" % (type(exc).__name__, exc)
    finally:
        studio.close()
        shutil.rmtree(studio.cache, ignore_errors=True)
    return seconds > 0.5, "%s ok: %.1fs of audio in %.1fs" % (label(voice_id), seconds, time.monotonic() - started)
