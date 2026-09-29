"""Download the studio voice (Piper engine + bundled voice model) into ./voice/.

    python tools/fetch_voice.py              # engine for this OS + bundled voice
    python tools/fetch_voice.py --all-voices # also the optional voices

Every file is pinned by SHA-256 (see voice.py). The release build runs this before
PyInstaller; nothing here is committed to git.
"""

import argparse
import os
import shutil
import sys
import tarfile
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import voice  # noqa: E402

SKIP = ("pkgconfig", "libtashkeel_model.ort")  # Arabic-only diacritizer; not needed for English voices


def fetch_engine(platform, dest):
    name, sha = voice.PIPER_BUILDS[platform]
    exe = os.path.join(dest, "piper", "piper.exe" if platform == "win" else "piper")
    if os.path.isfile(exe):
        print("engine already present:", exe)
        return
    tmp = tempfile.mkdtemp()
    archive = voice.download(voice.PIPER_RELEASE + name, os.path.join(tmp, name), sha)
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest)
    for skip in SKIP:
        path = os.path.join(dest, "piper", skip)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)
    shutil.rmtree(tmp, ignore_errors=True)
    print("engine:", exe)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=sorted(voice.PIPER_BUILDS),
                        default="win" if sys.platform.startswith("win") else "linux")
    parser.add_argument("--all-voices", action="store_true")
    args = parser.parse_args()
    dest = os.path.join(ROOT, "voice")
    fetch_engine(args.platform, dest)
    wanted = list(voice.VOICES) if args.all_voices else [voice.BUNDLED]
    for vid in wanted:
        target = os.path.join(dest, "models", vid + ".onnx")
        if os.path.isfile(target) and voice._sha256(target) == voice.VOICES[vid][2]:
            print("voice already present:", vid)
            continue
        voice.download_voice(vid, folder=os.path.join(dest, "models"))
        print("voice:", vid)
    with open(os.path.join(dest, "NOTICE.txt"), "w", encoding="utf-8") as handle:
        handle.write(
            "Studio voice\n\n"
            "Piper text-to-speech 2023.11.14-2, MIT licence, (c) Michael Hansen\n"
            "  https://github.com/rhasspy/piper\n"
            "  includes espeak-ng (GPL-3.0, https://github.com/espeak-ng/espeak-ng)\n"
            "  and ONNX Runtime (MIT, https://github.com/microsoft/onnxruntime)\n\n"
            "Voice models from https://huggingface.co/rhasspy/piper-voices (v1.0.0):\n"
            + "".join("  %s (%s): public domain LibriVox recordings\n" % (v, voice.VOICES[v][0]) for v in voice.VOICES)
        )


if __name__ == "__main__":
    main()
