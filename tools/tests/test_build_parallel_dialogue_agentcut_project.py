import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.build_parallel_dialogue_agentcut_project import build_project, media_duration


class MediaDurationTests(unittest.TestCase):
    @patch("tools.build_parallel_dialogue_agentcut_project.subprocess.run")
    def test_uses_shortest_audio_video_stream_duration(self, run):
        run.return_value = SimpleNamespace(
            stdout=json.dumps(
                {
                    "streams": [
                        {"codec_type": "video", "duration": "4.041667"},
                        {"codec_type": "audio", "duration": "4.062993"},
                    ],
                    "format": {"duration": "4.062993"},
                }
            )
        )
        self.assertEqual(media_duration(Path("clip.mp4")), 4.041667)

    @patch("tools.build_parallel_dialogue_agentcut_project.subprocess.run")
    def test_falls_back_to_container_duration_when_stream_duration_missing(self, run):
        run.return_value = SimpleNamespace(
            stdout=json.dumps({"streams": [], "format": {"duration": "5.125"}})
        )
        self.assertEqual(media_duration(Path("clip.mp4")), 5.125)

    @patch("tools.build_parallel_dialogue_agentcut_project.subprocess.run")
    def test_rejects_media_without_any_duration(self, run):
        run.return_value = SimpleNamespace(stdout=json.dumps({"streams": [], "format": {}}))
        with self.assertRaisesRegex(ValueError, "no measurable media duration"):
            media_duration(Path("clip.mp4"))

    @patch("tools.build_parallel_dialogue_agentcut_project.media_duration", return_value=4.0)
    def test_reads_dialogue_contract_from_batch_metadata(self, _duration):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "clip.mp4"
            source.write_bytes(b"media")
            receipt = {
                "episode": "E25",
                "status": "BATCH_COMPLETE",
                "tasks": [{
                    "task_key": "E25-DIA-001-VIDEO",
                    "scene_id": "S1",
                    "status": "qa_pass",
                    "output_path": str(source),
                    "metadata": {
                        "beat_id": "B01",
                        "dia_id": "DIA-001",
                        "speaker": "陈迹",
                        "exact_dialogue": "你不是信使。",
                    },
                }],
            }
            state = {"source_script": "script.json", "scene_state": [{
                "scene_id": "S1", "time_of_day": "day", "weather": "snow", "event_summary": "揭穿假信使"
            }]}
            project = build_project(receipt, state, Path(tmp) / "out.mp4")
            self.assertEqual(project["expectedDialogueIds"], ["DIA-001"])
            clip = project["timeline"]["videoTracks"][0]["clips"][0]
            self.assertEqual(clip["metadata"]["speaker"], "陈迹")
            self.assertEqual(clip["metadata"]["exact_dialogue"], "你不是信使。")


if __name__ == "__main__":
    unittest.main()
