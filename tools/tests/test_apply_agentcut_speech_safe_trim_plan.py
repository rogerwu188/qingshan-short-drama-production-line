import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "apply_agentcut_speech_safe_trim_plan.py"


class SpeechSafeTrimPlanTest(unittest.TestCase):
    def test_ripple_trim_preserves_protected_dialogue_and_adds_stable_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            self.run_ripple_trim_case(Path(temporary_directory))

    def run_ripple_trim_case(self, tmp_path: Path) -> None:
        project = {
            "version": "1.0",
            "output": {"path": str(tmp_path / "old.mp4")},
            "timeline": {
                "videoTracks": [
                    {
                        "id": "ordered_dialogue_picture",
                        "clips": [
                            {"source": "/x/DIA-001_muted.mp4", "start": 0, "in": 0, "duration": 4},
                            {"source": "/x/DIA-002_muted.mp4", "start": 4, "in": 0, "duration": 4},
                        ],
                    }
                ],
                "audioTracks": [
                    {
                        "id": "ordered_dialogue",
                        "clips": [
                            {"source": "/x/DIA-001.wav", "start": 0, "in": 0, "duration": 4},
                            {"source": "/x/DIA-002.wav", "start": 4, "in": 0, "duration": 4},
                        ],
                    }
                ],
            },
            "qingshanAudit": {
                "dialogue_order": ["DIA-001", "DIA-002"],
                "beat_windows": [
                    {"beat_id": "B01", "start_seconds": 0, "end_seconds": 8, "actual_seconds": 8}
                ],
            },
        }
        plan = {
            "status": "PASS",
            "projected_runtime_seconds": 7.8,
            "total_trim_seconds": 0.2,
            "trimmed_dialogue_count": 1,
            "items": [
                {"dialogue_id": "DIA-001", "beat_id": "B01", "eligible": True, "source_head_trim_seconds": 0.2},
                {"dialogue_id": "DIA-002", "beat_id": "B01", "eligible": False, "source_head_trim_seconds": 0.0},
            ],
        }
        project_path = tmp_path / "project.json"
        plan_path = tmp_path / "plan.json"
        out_path = tmp_path / "out.json"
        project_path.write_text(json.dumps(project), encoding="utf-8")
        plan_path.write_text(json.dumps(plan), encoding="utf-8")

        subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "--project",
                str(project_path),
                "--trim-plan",
                str(plan_path),
                "--out",
                str(out_path),
                "--output-video",
                str(tmp_path / "new.mp4"),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(out_path.read_text(encoding="utf-8"))
        audio = result["timeline"]["audioTracks"][0]["clips"]
        video = result["timeline"]["videoTracks"][0]["clips"]
        self.assertEqual(audio[0]["in"], 0.2)
        self.assertEqual(audio[0]["duration"], 3.8)
        self.assertEqual(audio[1]["start"], 3.8)
        self.assertEqual(video[0]["in"], 0.18)
        self.assertEqual(video[0]["duration"], 3.82)
        self.assertEqual(video[1]["start"], 3.8)
        self.assertEqual(audio[0]["id"], "audio-01-DIA-001")
        self.assertEqual(result["qingshanAudit"]["compiled_runtime_seconds"], 7.8)
        self.assertIs(result["qingshanAudit"]["final_lock"], False)


if __name__ == "__main__":
    unittest.main()
