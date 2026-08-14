import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.release_dependent_image_anchors import build_release_manifest


class ReleaseDependentImageAnchorsTest(unittest.TestCase):
    def test_releases_only_completed_dependency_and_binds_a1_first(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "a1.png"
            image.write_bytes(b"image")
            digest = hashlib.sha256(b"image").hexdigest()
            base = {
                "task_key": "U04-A1",
                "reference_bindings": [{"role": "scene", "entity_id": "S1", "path": "scene.png", "sha256": "x", "qa_status": "PASS"}],
                "prompt_contract": {"schema": "qingshan.image_prompt_contract.v2", "visible_characters": [], "status": "PASS"},
            }
            source = {
                "episode": "E32",
                "tasks": [base],
                "dependent_anchor_specs": [
                    {"task_key": "U04-A2", "video_unit_id": "U04", "depends_on_task_key": "U04-A1", "state_index": 2, "state_count": 2, "state_role": "terminal", "terminal_description": "终态", "source_action": "动作链"},
                    {"task_key": "U10-A2", "video_unit_id": "U10", "depends_on_task_key": "U10-A1", "state_index": 2, "state_count": 2, "state_role": "terminal", "terminal_description": "终态", "source_action": "动作链"},
                ],
            }
            harvest = {"results": [{"task_key": "U04-A1", "remote_status": "completed", "output_path": str(image), "sha256": digest}]}
            result = build_release_manifest(source, harvest, root / "prompts")
            self.assertEqual(result["status"], "READY_TO_SUBMIT_CONCURRENTLY")
            self.assertEqual([row["task_key"] for row in result["tasks"]], ["U04-A2"])
            self.assertEqual(result["blocked_tasks"], ["U10-A2"])
            self.assertEqual(result["tasks"][0]["reference_bindings"][0]["role"], "continuity_anchor")
            self.assertTrue(result["tasks"][0]["prompt_contract"]["continuity_anchor_is_first_real_reference"])


if __name__ == "__main__":
    unittest.main()
