import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class RenderAgentCutAudioMasterTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg is required")
    def test_rendered_master_is_48000_hz(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.wav"
            with wave.open(str(source), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(48000)
                wav.writeframes(struct.pack("<h", 1000) * 48000)
            project = {
                "metadata": {
                    "audio_profile_id": "NATIVE_MULTIMODAL_NO_EXTERNAL_BGM",
                    "audio_profile_contract": "configs/audio_postproduction_profiles_v1_20260821.json",
                    "source_audio_policy": "PRESERVE_NATIVE_MULTIMODAL_AUDIO",
                    "sound_design_contract": {
                        "mode": "NATIVE_EMBEDDED",
                        "required_layers": ["DIALOGUE", "FOLEY", "AMBIENCE", "SFX"],
                        "source_track_ids": ["E99_NATIVE_AUDIO"],
                        "external_bgm_allowed": False,
                    },
                },
                "output": {"audioSampleRate": 48000},
                "masterAudioPolicy": {"sampleRateHz": 48000},
                "timeline": {
                    "videoTracks": [{"clips": [{
                        "source": str(source), "start": 0.0, "duration": 1.0,
                        "metadata": {"source_id": "SRC-1"},
                    }]}],
                    "audioTracks": [{"id": "E99_NATIVE_AUDIO", "clips": [{
                        "source": str(source), "start": 0.0, "in": 0.0,
                        "duration": 1.0, "volume": 1.0,
                        "metadata": {"source_id": "SRC-1", "dialogue_classification": "NON_SPEAKING"},
                    }]}],
                },
            }
            project_path = root / "project.json"
            output = root / "master.wav"
            report = root / "report.json"
            project_path.write_text(json.dumps(project), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(ROOT / "tools/render_agentcut_audio_master.py"),
                 str(project_path), str(output), str(report)],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(payload["sample_rate_hz"], 48000)
            self.assertTrue(payload["hard_gates"]["sample_rate_equals_48000_hz"])


if __name__ == "__main__":
    unittest.main()
