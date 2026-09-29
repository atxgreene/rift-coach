import io
import os
import shutil
import sys
import tempfile
import threading
import unittest
import wave
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lol_coach  # noqa: E402
import voice  # noqa: E402


class FakeResp(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class VoiceChoiceTests(unittest.TestCase):
    def test_resolve_prefers_studio_by_default(self):
        with mock.patch.object(voice, "installed", return_value=["en_US-kristin-medium", "en_US-norman-medium"]):
            self.assertEqual(voice.resolve(""), "en_US-kristin-medium")
            self.assertEqual(voice.resolve("studio:en_US-norman-medium"), "en_US-norman-medium")
            self.assertEqual(voice.resolve("studio:gone"), "en_US-kristin-medium")
            self.assertIsNone(voice.resolve("Microsoft Zira Desktop"))  # a chosen Windows voice stays chosen

    def test_resolve_without_engine(self):
        with mock.patch.object(voice, "installed", return_value=[]):
            self.assertIsNone(voice.resolve(""))
            self.assertIsNone(voice.resolve("studio:en_US-kristin-medium"))

    def test_speed_maps_to_length_scale(self):
        self.assertEqual(voice.length_scale(0), 1.0)
        self.assertLess(voice.length_scale(3), voice.length_scale(1))
        self.assertEqual(voice.length_scale(99), 0.6)
        self.assertEqual(voice.length_scale(-99), 1.5)

    def test_volume_scaling(self):
        import array
        data = array.array("h", [1000, -1000, 32767]).tobytes()
        self.assertEqual(voice.scale_volume(data, 100), data)
        half = array.array("h")
        half.frombytes(voice.scale_volume(data, 50))
        self.assertEqual(list(half), [500, -500, 16383])

    def test_download_rejects_bad_checksum(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        dest = os.path.join(folder, "v.onnx")
        with self.assertRaises(ValueError):
            voice.download("https://example.invalid/v", dest, "0" * 64, opener=lambda *a, **k: FakeResp(b"abc"))
        self.assertFalse(os.path.exists(dest))
        self.assertFalse(os.path.exists(dest + ".part"))
        import hashlib
        good = hashlib.sha256(b"abc").hexdigest()
        seen = []
        voice.download("https://example.invalid/v", dest, good, progress=seen.append,
                       opener=lambda *a, **k: FakeResp(b"abc"))
        self.assertTrue(os.path.exists(dest))
        self.assertEqual(seen[-1], 1.0)

    def test_every_listed_voice_is_pinned(self):
        self.assertIn(voice.BUNDLED, voice.VOICES)
        for vid, row in voice.VOICES.items():
            self.assertEqual(len(row[2]), 64, vid)
            self.assertEqual(len(row[3]), 64, vid)


class SpeakerFallbackTests(unittest.TestCase):
    def test_broken_studio_voice_falls_back_and_keeps_the_line(self):
        speaker = lol_coach.Speaker(voice=False)
        spoken = []

        class Broken:
            voice_id = "en_US-kristin-medium"

            def speak(self, text):
                raise RuntimeError("no audio")

            def close(self):
                pass

        speaker.studio = Broken()
        speaker.mode = "studio"
        done = threading.Event()

        def fake_win(text):
            spoken.append(text)
            done.set()

        speaker._speak_win = fake_win
        with mock.patch.object(lol_coach.Speaker, "_detect", staticmethod(lambda: "win")):
            with mock.patch("builtins.print"):
                threading.Thread(target=speaker._run, daemon=True).start()
                speaker.say("first line", lol_coach.P_URGENT)   # studio fails once: skipped, retried next line
                speaker.say("second line", lol_coach.P_NORMAL)  # fails again -> Windows voice says it
                self.assertTrue(done.wait(5))
        self.assertEqual(speaker.mode, "win")
        self.assertIsNone(speaker.studio)
        self.assertEqual(spoken, ["second line"])
        self.assertEqual(speaker.engine, "Windows voice")
        speaker.close()


@unittest.skipUnless(voice.available(), "studio voice not fetched (python tools/fetch_voice.py)")
class RealSynthesisTests(unittest.TestCase):
    def test_synthesizes_and_caches(self):
        cache = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cache, True)
        studio = voice.Studio(voice.resolve(""), rate=1, volume=80, cache_dir=cache)
        self.addCleanup(studio.close)
        first = studio.synth("Dragon in sixty seconds.")
        self.assertGreater(voice.wav_seconds(first), 0.5)
        with wave.open(first, "rb") as handle:
            self.assertEqual(handle.getsampwidth(), 2)
        again = studio.synth("Dragon  in sixty seconds.")
        self.assertEqual(first, again)
        self.assertEqual(len(os.listdir(cache)), 1)

    def test_self_test(self):
        ok, detail = voice.self_test()
        self.assertTrue(ok, detail)


if __name__ == "__main__":
    unittest.main()
