"""A hard-continuation unit's real tail goes through the same S6 Q1 route as a continuity-derived one
(2026-11-11, fleet devices 1101 E04 VU-012/020/023 and 1284 E06 VU-006).

PREVIOUS_UNIT_REAL_FINAL_FRAME units were left out of continuity_derived_units, so the tail was never
materialised as the first shot's keyframe, no Q1 request was issued, and the video admission gate failed
SEMANTIC_ANCHOR_EVIDENCE_INVALID (Q1_ASSET_SHA_MISMATCH, source_q1_ref null) on every resume."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines" / "nalu" / "runtime" / "tools"))
sys.path.insert(0, str(ROOT))

import nalu_pipeline as npl  # noqa: E402

STAMPED = {"episode": "E04", "camera_grammar_policy": "CAMERA_GRAMMAR_V1"}


def _fixture(tmp: Path):
    preprod = tmp / "preproduction"
    for sub in ("keyframes", "real_final_frames", "reports", "prompts/keyframes"):
        (preprod / sub).mkdir(parents=True, exist_ok=True)
    (tmp / "video").mkdir()
    (tmp / "contract.json").write_text(json.dumps(STAMPED))
    (preprod / "E04_VIDEO_UNIT_GROUPING_PLAN_V1.json").write_text(json.dumps({"units": [
        {"unit_id": "E04-VU-011", "editorial_shot_ids": ["E04-S03-03"]},
        {"unit_id": "E04-VU-012", "editorial_shot_ids": ["E04-S03-04"]},
        {"unit_id": "E04-VU-013", "editorial_shot_ids": ["E04-S03-05"]}]}))
    (preprod / "E04_VIDEO_UNIT_ANCHOR_PLAN_V1.json").write_text(json.dumps({"units": [
        {"unit_id": "E04-VU-011", "opening_anchor_contract": {"source": "NEW_EVENT_GENERATED_KEYFRAME"}},
        {"unit_id": "E04-VU-012", "opening_anchor_contract": {"source": "PREVIOUS_UNIT_REAL_FINAL_FRAME",
                                                              "previous_unit_id": "E04-VU-011"}},
        {"unit_id": "E04-VU-013", "opening_anchor_contract": {"source": "CONTINUITY_DERIVED_KEYFRAME",
                                                              "previous_unit_id": "E04-VU-012"}}]}))
    (preprod / "real_final_frames" / "E04-VU-011.png").write_bytes(b"real tail of VU-011")
    ctx = SimpleNamespace(
        episode="E04", dry=False, run_id="RUN1", say=lambda *_a, **_k: None,
        p=SimpleNamespace(preprod=preprod, preprod_reports=preprod / "reports", contract=tmp / "contract.json",
                          video_media=tmp / "video", keyframes=preprod / "keyframes",
                          q2_dir=preprod / "reports" / "qa" / "q2"))
    return ctx, preprod / "keyframes" / "E04-S03-04-keyframe-v1.png"


class HardContinuationTailQ1Test(unittest.TestCase):
    def test_both_tail_sources_are_tail_sourced(self):
        with tempfile.TemporaryDirectory() as d:
            ctx, _ = _fixture(Path(d))
            self.assertEqual(set(npl.continuity_derived_units(ctx)), {"E04-VU-013"})
            self.assertEqual(set(npl.hard_continuation_units(ctx)), {"E04-VU-012"})
            self.assertEqual(set(npl.tail_sourced_units(ctx)), {"E04-VU-012", "E04-VU-013"})

    def test_hard_continuation_tail_is_materialised_and_needs_q1(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(npl, "ENGINE", Path(d) / "engine"):
            ctx, kf = _fixture(Path(d))
            with mock.patch.object(npl, "check_tail_start_frame",
                                   side_effect=AssertionError("a hard continuation never switches frames")):
                rows = {r["unit_id"]: r for r in npl.materialise_derived_keyframes(ctx)}
            self.assertEqual(rows["E04-VU-012"]["status"], "MATERIALISED")
            self.assertEqual(rows["E04-VU-013"]["status"], "TAIL_NOT_YET_EXTRACTED")
            self.assertEqual(kf.read_bytes(), b"real tail of VU-011")
            self.assertEqual(npl.derived_units_pending_q1(ctx), [("E04-VU-012", "E04-S03-04")])
            q1 = ctx.p.preprod_reports / "qa" / "q1" / "E04-VU-012" / "admission_result.json"
            q1.parent.mkdir(parents=True)
            q1.write_text(json.dumps({"downstream_status": "ADMITTED_FOR_VIDEO_SUBMIT",
                                      "asset_sha256": npl.sha256_file(kf)}))
            self.assertEqual(npl.derived_units_pending_q1(ctx), [])
            self.assertEqual(npl.own_keyframes_needed(ctx), [])

    def test_hard_continuation_waiting_on_tail_needs_no_own_keyframe(self):
        # 1101 E05 2026-11-12: the predecessor video is not submitted yet and S5 left an unused prompt.
        with tempfile.TemporaryDirectory() as d, mock.patch.object(npl, "ENGINE", Path(d) / "engine"):
            ctx, kf = _fixture(Path(d))
            (ctx.p.preprod / "real_final_frames" / "E04-VU-011.png").unlink()
            (ctx.p.preprod / "prompts" / "keyframes" / "E04-S03-04-KEYFRAME-V1.txt").write_text("unused")
            self.assertFalse(kf.is_file())
            self.assertEqual(npl.own_keyframes_needed(ctx), [])


if __name__ == "__main__":
    unittest.main()
