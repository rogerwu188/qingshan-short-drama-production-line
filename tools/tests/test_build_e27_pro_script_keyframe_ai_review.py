import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import build_e27_pro_script_keyframe_ai_review as builder


class BuildE27ProScriptKeyframeAIReviewTest(unittest.TestCase):
    def test_builds_one_six_worker_sha_bound_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = []
            tasks = []
            scenes = []
            for i in range(1, 7):
                path = root / f"s{i}.png"
                path.write_bytes(f"image-{i}".encode())
                digest = builder.sha256(path)
                scene_id = f"S{i}"
                images.append(path)
                tasks.append({"task_key": f"T{i}", "state": "image_pass", "scene_id": scene_id, "scene_no": str(i), "output_path": str(path), "sha256": digest, "prompt_file": "p.txt"})
                scenes.append({"scene_id": scene_id, "location": f"L{i}", "time_of_day": "day" if i == 1 else "night", "weather": "dry", "event_summary": f"A{i}"})
            receipt = root / "receipt.json"
            state = root / "state.json"
            request = root / "request.json"
            config = root / "config.json"
            receipt.write_text(json.dumps({"status": "BATCH_COMPLETE", "tasks": tasks}), encoding="utf-8")
            state.write_text(json.dumps({"scene_state": scenes}), encoding="utf-8")
            with patch.object(builder, "ROOT", root), patch.object(builder, "RECEIPT", receipt), patch.object(builder, "SCENE_STATE", state), patch.object(builder, "QA_DIR", root / "qa"), patch.object(builder, "REQUEST", request), patch.object(builder, "CONFIG", config):
                result = builder.build()
            payload = json.loads(request.read_text(encoding="utf-8"))
            self.assertEqual(result["item_count"], 6)
            self.assertEqual(payload["workers"], 6)
            self.assertEqual(len(payload["items"]), 6)
            self.assertEqual(payload["items"][0]["metadata"]["scene_no"], "1")
            self.assertIn("time of day must read as day", payload["items"][0]["metadata"]["review_focus"])
            self.assertTrue(all(len(item["metadata"]["candidate_sha256"]) == 64 for item in payload["items"]))


if __name__ == "__main__":
    unittest.main()
