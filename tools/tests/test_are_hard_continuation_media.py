"""S6 action-role review never carries a tail-sourced unit without media (E04 S6, 2026-11-11).

Fleet device 1101: VU-012/020/023 open on the previous unit's real final frame.  The anchor plan
the action-role request read was built before those tails existed, so the request carried
``media_path: null``, and the start-frame contract bound them to the episode's first shot (S01-01)
because their first reference key names the previous unit, not a shot.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import build_nalu_preproduction as bnp  # noqa: E402
import nalu_qa_common as qc  # noqa: E402


def _shot(shot_id: str, start: str) -> dict:
    return {"shot_id": shot_id, "prompt_spec": {
        "cast": [], "props": [], "space": {"location": "L", "subspace": "S"},
        "action": {"start_state": start},
        "visual_design": {"still_prompt_contract": "entry only"}}}


class StartFrameContractFirstShotTest(unittest.TestCase):
    def test_hard_continuation_binds_own_first_shot(self):
        editorial = {"shots": [_shot("E04-S01-01", "water edge"), _shot("E04-S05-02", "charred stump")]}
        anchor_plan = {"units": [{"unit_id": "E04-VU-020",
                                  "reference_image_task_keys": ["E04-VU-019:REAL_FINAL_FRAME"],
                                  "reference_image_paths": [""]}]}
        grouping = {"units": [{"unit_id": "E04-VU-020", "editorial_shot_ids": ["E04-S05-02"]}]}
        with tempfile.TemporaryDirectory() as tmp:
            rows = bnp.build_start_frame_contracts(anchor_plan, editorial, Path(tmp), grouping)
        self.assertEqual(rows[0]["derived_from"]["shot_id"], "E04-S05-02")
        self.assertEqual(rows[0]["derived_from"]["entry_state"], "charred stump")

    def test_shot_key_after_tail_key_wins(self):
        editorial = {"shots": [_shot("E04-S01-01", "a"), _shot("E04-S03-04", "b")]}
        anchor_plan = {"units": [{"unit_id": "E04-VU-012",
                                  "reference_image_task_keys": ["E04-VU-011:REAL_FINAL_FRAME", "E04-S03-04:KEYFRAME"],
                                  "reference_image_paths": ["", ""]}]}
        with tempfile.TemporaryDirectory() as tmp:
            rows = bnp.build_start_frame_contracts(anchor_plan, editorial, Path(tmp))
        self.assertEqual(rows[0]["derived_from"]["shot_id"], "E04-S03-04")


class ActionRoleItemsMediaTest(unittest.TestCase):
    def test_unit_without_media_is_not_an_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "k.png"
            img.write_bytes(b"x")
            exp = qc.Expectations.__new__(qc.Expectations)
            exp.contract = {}
            exp.shots = {"E04-S01-01": {"scene_id": "S01", "prompt_spec": {}}}
            exp.units = {}
            exp.wardrobe_by_id = {}
            exp.start_frame_units = {
                "E04-VU-001": {"reference_path": str(img), "derived_from": {"shot_id": "E04-S01-01"}},
                "E04-VU-012": {"reference_path": None, "derived_from": {"shot_id": "E04-S03-04"}},
            }
            rows = exp.action_role_items()
        self.assertEqual([r["unit_id"] for r in rows], ["E04-VU-001"])
        self.assertEqual(exp.action_role_items_skipped_media_missing, ["E04-VU-012"])


class PipelineUnboundMediaTest(unittest.TestCase):
    def test_units_without_bound_media_are_listed(self):
        import nalu_pipeline as np_
        with tempfile.TemporaryDirectory() as tmp:
            preprod = Path(tmp)
            img = preprod / "tail.png"
            img.write_bytes(b"x")
            (preprod / "E04_VIDEO_UNIT_ANCHOR_PLAN_V1.json").write_text(json.dumps({"units": [
                {"unit_id": "E04-VU-011", "start_frame_semantic_contract": {"reference_path": str(img)}},
                {"unit_id": "E04-VU-012", "start_frame_semantic_contract": {"reference_path": None}},
            ]}), encoding="utf-8")
            ctx = SimpleNamespace(episode="E04", p=SimpleNamespace(preprod=preprod))
            self.assertEqual(np_.are_units_without_start_frame_media(ctx, ["E04-VU-011", "E04-VU-012"]),
                             ["E04-VU-012"])


if __name__ == "__main__":
    unittest.main()
