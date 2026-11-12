"""A hard-continuation unit whose bound take opened on an OLDER predecessor tail keeps that image as its opening
reference after the predecessor is redone (fleet device 1101 E04 VU-020, 2026-11-12: the final compile rebound
VU-020 to the redone VU-019's new tail, Q1_ASSET_SHA_MISMATCH, SEMANTIC_ANCHOR_EVIDENCE_INVALID)."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AsSubmittedStartFrameTests(unittest.TestCase):

    def test_finds_the_bound_first_reference_by_sha(self):
        import build_nalu_preproduction as bnp
        with tempfile.TemporaryDirectory() as tmp:
            out, kf, tails = Path(tmp, "pre"), Path(tmp, "kf"), Path(tmp, "tails")
            for d in (out / "reports", kf, tails):
                d.mkdir(parents=True)
            old = kf / "B-keyframe-v1.png"
            old.write_bytes(b"old tail")
            (tails / "U1.png").write_bytes(b"new tail")
            (out / "reports" / "E04_S6_WAVE_STATE.json").write_text(json.dumps({"start_frame_as_submitted": {
                "U2": {"predecessor_tail_submitted": False, "reference_sha256": [_sha(old), "x"],
                       "task_id": "t1"}}}))
            got = bnp.as_submitted_start_frame(out, "E04", "U2", [kf, tails])
            self.assertEqual(got["path"], str(old))
            self.assertEqual(got["sha256"], _sha(old))
            self.assertIsNone(bnp.as_submitted_start_frame(out, "E04", "U9", [kf, tails]))
            old.unlink()
            self.assertIsNone(bnp.as_submitted_start_frame(out, "E04", "U2", [kf, tails]))


class HardContinuationAnchorPlanTests(unittest.TestCase):

    @staticmethod
    def _grouping(withheld: dict) -> tuple[dict, dict]:
        sys.path.insert(0, str(ROOT / "tools" / "tests"))
        from test_e51_pipeline_rectification import E51PipelineRectificationTests as E51
        state = E51._persistent_state()
        space = {"global": "MAP-1", "location": "LOC-ROOM", "subspace": "BED"}
        u1 = {"episode": "E04", "unit_id": "E04-VU-019", "scene_id": "E04-S05", "editorial_shot_ids": ["A"],
              "camera_plan": {"shot_scale": "MEDIUM", "camera_side": "AXIS_A"}, "persistent_state_contract": state,
              "ordered_prompt_specs": [{"space": space, "scene_state": {"time": "当夜亥时"}}],
              "outgoing_transition_contract": {"source_terminal_state": {"space": space}}}
        u2 = {"episode": "E04", "unit_id": "E04-VU-020", "scene_id": "E04-S05", "editorial_shot_ids": ["B"],
              "camera_plan": {"shot_scale": "MEDIUM", "camera_side": "AXIS_A"}, "persistent_state_contract": state,
              "ordered_prompt_specs": [{"space": space, "scene_state": {"time": "当夜亥时"}}],
              "incoming_transition_contract": {"transition_device": "CONTINUOUS_ACTION",
                                               "target_initial_state": {"space": space}},
              "withheld_previous_unit_final_frame": withheld}
        editorial = {"shots": [{"shot_id": "A", "scene_id": "E04-S05", "prompt_spec": {}},
                               {"shot_id": "B", "scene_id": "E04-S05", "prompt_spec": {}}]}
        return {"episode": "E04", "units": [u1, u2]}, editorial

    def _build(self, withheld_extra: dict):
        from tools import build_video_unit_anchor_plan as bva

        def boundary(prev, unit):
            if prev is None:
                return {"status": "PASS", "boundary_class": "NEW_EVENT_ANCHOR", "previous_unit_id": None}
            return {"status": "PASS", "boundary_class": "HARD_CONTINUATION", "previous_unit_id": prev["unit_id"],
                    "same_continuous_event": True}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(bva, "classify_boundary", boundary), \
                mock.patch.object(bva, "compile_internal_shot_boundaries", lambda _u: {"status": "PASS"}), \
                mock.patch.object(bva.unit_action_continuity_contract, "evaluate", lambda *_a: {"status": "PASS"}):
            for name in ("A", "B"):
                Path(tmp, f"{name}-keyframe-v1.png").touch()
            withheld = {"path": f"{tmp}/E04-VU-019.png", "sha256": "new", "previous_unit_id": "E04-VU-019",
                        "reason": "SUBMITTED_WITHOUT_PREDECESSOR_TAIL", **withheld_extra}
            plan = bva.build(*self._grouping(withheld), Path(tmp))
        return plan["units"][1]

    def test_opens_on_the_image_the_take_was_submitted_with(self):
        unit = self._build({"as_submitted_start_frame": {"path": "/kf/B-keyframe-v1.png", "sha256": "old"}})
        self.assertEqual(unit["reference_image_paths"][0], "/kf/B-keyframe-v1.png")
        self.assertNotIn("/E04-VU-019.png", " ".join(unit["reference_image_paths"]))

    def test_without_a_record_the_withheld_tail_still_opens(self):
        unit = self._build({})
        self.assertTrue(unit["reference_image_paths"][0].endswith("/E04-VU-019.png"))


if __name__ == "__main__":
    unittest.main()
