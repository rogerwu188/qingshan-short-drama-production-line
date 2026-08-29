import tempfile
import unittest
from pathlib import Path

from tools.build_video_unit_anchor_plan import build
from tools.video_unit_anchor_count_gate import evaluate


class BuildVideoUnitAnchorPlanTests(unittest.TestCase):
    def test_adds_references_for_later_visible_identity_and_prop(self):
        grouping = {"episode": "E99", "units": [
            {"unit_id": "U1", "editorial_shot_ids": ["S1", "S1B"]},
            {"unit_id": "U2", "editorial_shot_ids": ["S2"]},
            {"unit_id": "U3", "editorial_shot_ids": ["S3"]},
            {"unit_id": "U4", "editorial_shot_ids": ["S4"]},
        ]}
        editorial = {"shots": [
            {"shot_id": "S1", "prompt_spec": {"dialogue": "line"}},
            {"shot_id": "S1B", "prompt_spec": {"cast": [{"character": "A", "face_visibility": "VISIBLE_PER_FRAME_CONTENT"}], "props": [{"prop": "cup"}]}},
            {"shot_id": "S2", "prompt_spec": {"props": [{"prop": "cup"}]}},
            {"shot_id": "S3", "prompt_spec": {}},
            {"shot_id": "S4", "prompt_spec": {"dialogue": "line"}},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "S1-keyframe-v1.png").touch()
            Path(tmp, "S1B-keyframe-v1.png").touch()
            plan = build(grouping, editorial, Path(tmp))
        self.assertEqual(plan["missing_anchor_shot_ids"], ["S2", "S3", "S4"])
        self.assertEqual(plan["units"][0]["planned_reference_image_count"], 2)
        self.assertEqual(plan["units"][0]["reference_transport_strategy"], "OMNI_MULTI_REFERENCE")
        self.assertEqual(evaluate(plan)["status"], "PASS")
