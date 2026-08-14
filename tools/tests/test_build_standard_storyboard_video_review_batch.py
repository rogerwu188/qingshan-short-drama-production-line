import json
import tempfile
import unittest
from pathlib import Path

from tools.build_standard_storyboard_video_review_batch import build


class StandardStoryboardVideoReviewBatchTests(unittest.TestCase):
    def test_latest_passing_source_overrides_earlier_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old_video = root / "old.mp4"
            new_video = root / "new.mp4"
            second_video = root / "second.mp4"
            for video in (old_video, new_video, second_video):
                video.write_bytes(video.name.encode())
            first = root / "first.json"
            first.write_text(json.dumps({"tasks": [
                {"source_id": "B01-P1", "status": "qa_pass", "output_path": str(old_video), "scene_id": "S1", "metadata": {}},
                {"source_id": "B01-P2", "status": "qa_pass", "output_path": str(second_video), "scene_id": "S1", "metadata": {}},
            ]}))
            retry = root / "retry.json"
            retry.write_text(json.dumps({"tasks": [
                {"source_id": "B01-P1", "status": "qa_pass", "output_path": str(new_video), "scene_id": "S1", "metadata": {"silent_visual_replacement": True}, "qa": {"ocr": "ocr.json", "frame_cadence": "cadence.json"}},
            ]}))
            request = root / "request.json"
            config = root / "config.json"
            prompt = root / "prompt.txt"
            report = root / "report.json"
            result = build("E99", [first, retry], request, config, prompt, report, 2)
            items = json.loads(request.read_text())["items"]
            self.assertEqual(result["admitted_sources"], 2)
            self.assertEqual(items[0]["path"], str(new_video))
            self.assertTrue(items[0]["metadata"]["silent_visual_replacement"])
            self.assertEqual(items[0]["evidence_inputs"]["ocr"], "ocr.json")
            self.assertEqual(json.loads(config.read_text())["tasks"][0]["tool_type"], "ai_review")

    def test_explicit_failed_item_can_be_sent_for_normalized_adjudication(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video = root / "candidate.mp4"
            video.write_bytes(b"candidate")
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps({"tasks": [{
                "task_key": "B01-R1", "source_id": "B01", "status": "qa_failed_terminal",
                "output_path": str(video), "scene_id": "S1", "metadata": {},
                "qa": {"ocr": "raw_ocr.json", "frame_cadence": "cadence.json"},
            }]}))
            result = build("E99", [receipt], root / "request.json", root / "config.json", root / "prompt.txt", root / "report.json", 1, ["B01-R1"])
            self.assertEqual(result["admitted_sources"], 1)

    def test_prompt_uses_the_admitted_sources_scene_not_first_contract_scene(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video = root / "candidate.mp4"
            video.write_bytes(b"candidate")
            scene_state = root / "scene_state.json"
            scene_state.write_text(json.dumps({"scene_state": [
                {"scene_id": "S1", "time_of_day": "day", "weather": "dry", "location_prompt_tokens": ["clinic"]},
                {"scene_id": "S2", "time_of_day": "night", "weather": "indoors", "location_prompt_tokens": ["royal archive"]},
            ]}))
            source_config = root / "source_config.json"
            source_config.write_text(json.dumps({"scene_contract_ref": str(scene_state)}))
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps({"config": str(source_config), "tasks": [{
                "source_id": "B05-P2", "status": "qa_pass", "output_path": str(video),
                "scene_id": "S2", "metadata": {},
            }]}))
            prompt = root / "prompt.txt"
            build("E99", [receipt], root / "request.json", root / "config.json", prompt, root / "report.json", 1)
            prompt_text = prompt.read_text()
            self.assertIn("royal archive", prompt_text)
            self.assertNotIn("clinic", prompt_text)


if __name__ == "__main__":
    unittest.main()
