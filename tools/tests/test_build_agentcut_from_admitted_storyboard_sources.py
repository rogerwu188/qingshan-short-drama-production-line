import json
import tempfile
import unittest
from pathlib import Path

from tools.build_agentcut_from_admitted_storyboard_sources import build


class AgentCutFromAdmittedSourcesTests(unittest.TestCase):
    def test_silent_visual_reuses_previous_non_silent_audio(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = root / "old.mp4"
            clean = root / "clean.mp4"
            old.write_bytes(b"old")
            clean.write_bytes(b"clean")
            first = root / "first.json"
            first.write_text(json.dumps({"tasks": [{"source_id": "B01-P1", "status": "qa_failed_terminal", "output_path": str(old), "duration": 12, "metadata": {}}]}))
            retry = root / "retry.json"
            retry.write_text(json.dumps({"tasks": [{"source_id": "B01-P1", "status": "qa_pass", "output_path": str(clean), "duration": 12, "metadata": {"silent_visual_replacement": True}}]}))
            review = root / "review.json"
            review.write_text(json.dumps({"passed_items": [{"path": str(clean)}]}))
            project = root / "project.json"
            admission = root / "admission.json"
            build("E99", [first, retry], review, project, admission, root / "out.mp4", 1)
            payload = json.loads(project.read_text())
            self.assertEqual(payload["timeline"]["videoTracks"][0]["clips"][0]["source"], str(clean))
            self.assertEqual(payload["timeline"]["audioTracks"][0]["clips"][0]["source"], str(old))
            self.assertEqual(payload["metadata"]["runtime_seconds"], 12.0)
            self.assertTrue(payload["masterAudioPolicy"]["required"])

    def test_combines_passes_from_failed_only_review(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            one = root / "one.mp4"
            two = root / "two.mp4"
            one.write_bytes(b"one")
            two.write_bytes(b"two")
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps({"tasks": [
                {"source_id": "B01-P1", "status": "qa_pass", "output_path": str(one), "duration": 12},
                {"source_id": "B01-P2", "status": "qa_pass", "output_path": str(two), "duration": 12},
            ]}))
            full = root / "full.json"
            full.write_text(json.dumps({"passed_items": [{"path": str(one)}]}))
            retry = root / "retry.json"
            retry.write_text(json.dumps({"passed_items": [{"path": str(two)}]}))
            project = root / "project.json"
            admission = root / "admission.json"
            result = build("E99", [receipt], [full, retry], project, admission, root / "out.mp4", 2)
            self.assertEqual(result["slots"], 2)

    def test_speaking_visual_replacement_cannot_reuse_old_candidate_audio(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = root / "old.mp4"
            clean = root / "clean.mp4"
            old.write_bytes(b"old")
            clean.write_bytes(b"clean")
            first = root / "first.json"
            first.write_text(json.dumps({"tasks": [{
                "source_id": "B01-P1", "status": "qa_failed_terminal",
                "output_path": str(old), "duration": 4,
                "metadata": {"selected_dialogue": [{"text": "原生台词"}]},
            }]}))
            retry = root / "retry.json"
            retry.write_text(json.dumps({"tasks": [{
                "source_id": "B01-P1", "status": "qa_pass",
                "output_path": str(clean), "duration": 4,
                "metadata": {"silent_visual_replacement": True},
            }]}))
            review = root / "review.json"
            review.write_text(json.dumps({"passed_items": [{"path": str(clean)}]}))
            with self.assertRaisesRegex(ValueError, "cannot reuse dialogue audio"):
                build("E99", [first, retry], review, root / "project.json", root / "admission.json", root / "out.mp4", 1)

    def test_ai_review_pass_can_adjudicate_raw_ocr_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video = root / "candidate.mp4"
            video.write_bytes(b"candidate")
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps({"tasks": [{"source_id": "B01", "status": "qa_failed_terminal", "output_path": str(video), "duration": 12, "metadata": {}}]}))
            review = root / "review.json"
            review.write_text(json.dumps({"passed_items": [{"path": str(video)}]}))
            result = build("E99", [receipt], review, root / "project.json", root / "admission.json", root / "out.mp4", 1)
            self.assertEqual(result["slots"], 1)


if __name__ == "__main__":
    unittest.main()
