import json
import tempfile
import unittest
from pathlib import Path

from tools.build_standard_storyboard_agentcut_qa_batch import build


class StandardStoryboardAgentCutQaBatchTests(unittest.TestCase):
    def test_builds_five_concurrent_gates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video = root / "cut.mp4"
            video.write_bytes(b"video")
            project = root / "project.json"
            beat_sheet = root / "beats.json"
            scene_state = root / "scene.json"
            for path in (project, beat_sheet):
                path.write_text("{}")
            scene_state.write_text(json.dumps({"scene_state": [{
                "scene_id": "E99-S01",
                "location": "clinic",
                "time_of_day": "night",
                "weather": "dry",
                "event_summary": "test",
                "location_prompt_tokens": ["clinic"],
            }]}))
            config = root / "batch.json"
            result = build("E99", video, project, beat_sheet, scene_state, root / "qa", config)
            payload = json.loads(config.read_text())
            self.assertEqual(result["tasks"], 5)
            self.assertEqual(payload["concurrency"], 5)
            self.assertEqual(len({task["task_key"] for task in payload["tasks"]}), 5)
            self.assertEqual(payload["scene_authority_mode"], "MULTI_SCENE_POST_RENDER_QA")
            self.assertIn("scene_contract_ref", payload)
            self.assertTrue(Path(payload["scene_contract_ref"]).is_file())


if __name__ == "__main__":
    unittest.main()
