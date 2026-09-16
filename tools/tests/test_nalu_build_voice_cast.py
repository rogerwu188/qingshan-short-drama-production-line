"""build_voice_cast: measured reference bands + co-presence precheck (no provider calls)."""
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("build_voice_cast", ROOT / "lines/nalu/runtime/tools/build_voice_cast.py")
mod = importlib.util.module_from_spec(SPEC)
sys.modules["build_voice_cast"] = mod
SPEC.loader.exec_module(mod)

CONTRACT = {"episode": "EXX",
            "character_entities": [{"character_id": "CHAR-A"}, {"character_id": "CHAR-B"}, {"character_id": "CHAR-SILENT"}],
            "audio_contract": {"dialogue_units": [{"shot_id": "EXX-S01-01", "speaker_id": "CHAR-A"},
                                                  {"shot_id": "EXX-S01-01", "speaker_id": "CHAR-B"}]},
            "shots": [{"shot_id": "EXX-S01-01", "scene_id": "EXX-S01",
                       "prompt_spec": {"cast": [{"character_id": "CHAR-A"}, {"character_id": "CHAR-B"}]}}]}


def sawtooth_wav(path: Path, f0: float, seconds: float = 1.5, sr: int = 48000):
    import numpy as np
    import soundfile as sf
    t = np.arange(int(seconds * sr)) / sr
    y = 0.5 * (2 * ((t * f0) % 1.0) - 1.0)
    sf.write(str(path), y.astype("float32"), sr)


class VoiceCast(unittest.TestCase):
    def test_copresence(self):
        self.assertEqual(mod.scene_copresence(CONTRACT), [["CHAR-A", "CHAR-B"]])

    @unittest.skipIf(shutil.which("ffmpeg") is None or importlib.util.find_spec("numpy") is None
                     or importlib.util.find_spec("soundfile") is None, "ffmpeg + numpy + soundfile needed")
    def test_measured_bands_and_precheck(self):
        tmp = Path(tempfile.mkdtemp())
        sawtooth_wav(tmp / "a.wav", 120.0)
        sawtooth_wav(tmp / "b.wav", 125.0)          # nearly the same pitch → bands overlap → REQUIRES_HUMAN
        registry = {"major_roles": [
            {"character_id": "CHAR-A", "status": "LOCKED_PRODUCTION_READY", "generation_voice_id": "v1", "local_reference": str(tmp / "a.wav")},
            {"character_id": "CHAR-B", "status": "LOCKED_PRODUCTION_READY", "generation_voice_id": "v2", "local_reference": str(tmp / "b.wav")}]}
        (tmp / "contract.json").write_text(json.dumps(CONTRACT)); (tmp / "registry.json").write_text(json.dumps(registry))
        report = mod.build("EXX", tmp / "contract.json", tmp / "registry.json", tmp / "cast.json", tmp / "report.json")
        cast = json.loads((tmp / "cast.json").read_text())
        self.assertNotIn("CHAR-SILENT", cast["characters"])            # silent characters need no voice
        f0 = cast["characters"]["CHAR-A"]["reference_f0_hz"]
        self.assertTrue(f0 and abs(f0 - 120.0) / 120.0 < 0.05)
        self.assertEqual(report["status"], "REQUIRES_HUMAN")
        self.assertTrue(any(r.startswith("F0_BAND_OVERLAP_REQUIRES_HUMAN") for r in report["requires_human"]))
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
