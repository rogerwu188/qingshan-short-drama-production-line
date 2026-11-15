"""S6 final pass applies a recorded line-owner acceptance to a tail-sourced start frame whose clip is on disk.

Device 1101 E10 (2026-11-14): every clip existed, so the wave loop -- the only place the Q1 order overlays
ran -- was skipped.  VU-020's start frame was reviewed FAIL (PERIOD-ANACHRONISM-LOCK), the default
acceptance was recorded twice (seq 195 start-frame gate, seq 196 Q1 gate, both bound to the still's sha),
and the full compile still stopped on INPUT_COMPLETENESS_FAILED:SEMANTIC_ANCHOR_EVIDENCE_INVALID.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "lines/nalu/runtime/tools"
sys.path.insert(0, str(TOOLS))
import nalu_pipeline as npl  # noqa: E402

rga = npl._rga

UID, ITEM, GATE = "E10-VU-020", "E10-S04-05", "PERIOD-ANACHRONISM-LOCK"
FAILURES = [f"evidence_4:{GATE}:registered_gate_not_pass:FAIL_NOT_ADMITTED:P0",
            f"required_registered_gate_not_pass:{GATE}"]


def _order(tmp: Path, sha: str):
    verbatim = "默认条款自动接受：质量问题不阻塞连续生产（短剧工作流）"
    receipt = {"schema": rga.RECEIPT_SCHEMA, "status": "CONFIRMED", "issued_by": "owner",
               "order_seq": 196, "order_id": "SEQ196", "verbatim": verbatim,
               "recorded_at_utc": "2026-11-14T23:30:00Z"}
    path = tmp / "receipt196.json"; path.write_text(json.dumps(receipt))
    return {"seq": 196, "id": "SEQ196", "issued_by": "owner", "status": "active", "order": verbatim,
            "decision": {"kind": "GATE_FAIL_ACCEPTANCE", "episode": "E10", "gate_id": GATE,
                         "detectors": [f"{ITEM}:{GATE}"], "media_sha256_by_item": {ITEM: sha}},
            "source_receipt": {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}


class FinalPassDerivedOrderAcceptanceTests(unittest.TestCase):
    def run_case(self, *, clip=True, with_order=True, reviewed=True):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            kf = tmp / "keyframes" / f"{ITEM}-keyframe-v1.png"; kf.parent.mkdir(parents=True)
            kf.write_bytes(b"previous unit real tail with burned text")
            sha = hashlib.sha256(kf.read_bytes()).hexdigest()
            reports = tmp / "reports"
            ar = reports / "qa/q1" / UID / "admission_result.json"; ar.parent.mkdir(parents=True)
            fail = {"status": "FAIL", "downstream_status": "FAIL_NOT_ADMITTED", "asset_sha256": sha,
                    "failures": FAILURES}
            ar.write_text(json.dumps(fail))
            video = tmp / "video"; video.mkdir()
            if clip:
                (video / f"{UID}.mp4").write_bytes(b"clip")
            ip = reports / "qa/q1/E10_KEYFRAME_Q1_INDEX.json"
            built: list[list] = []

            def fake_qa_run(_ctx, argv, *, name):
                # the builder re-materialises the same reviewed FAIL for the stills in the review
                built.append(list(argv))
                ar.write_text(json.dumps(fail))
                ip.write_text(json.dumps({
                    "unit_count": 1, "admitted_count": 0, "status": "PARTIAL_0_OF_1_ADMITTED",
                    "video_submission_allowed_unit_ids": [], "rejected_unit_ids": [UID],
                    "results": [{"unit_id": UID, "item_id": ITEM, **fail, "admission_result": str(ar)}]}))
                return {"exit_code": 0, "stdout_tail": json.dumps({"out": str(ip)})}

            orders = [_order(tmp, sha)] if with_order else []
            ctx = types.SimpleNamespace(
                episode="E10", p=types.SimpleNamespace(preprod_reports=reports, video_media=video),
                authority_blockers=[],
                authority={"orders_path": tmp / "ORDERS.json", "latest_order_seq": 196, "line_owner_id": "owner"})
            names = ("ENGINE", "continuity_derived_units", "hard_continuation_units", "merge_keyframe_answers",
                     "qa_run")
            saved = (rga._orders, *[getattr(npl, n) for n in names])
            rga._orders = lambda *a, **k: orders
            npl.ENGINE = tmp / "engine"
            npl.continuity_derived_units = lambda _ctx: {UID: {"first_shot_id": ITEM, "keyframe_path": kf}}
            npl.hard_continuation_units = lambda _ctx: {}
            npl.merge_keyframe_answers = lambda _ctx, shots: (
                (tmp / "merged_review.json", list(shots), []) if reviewed else (None, [], list(shots)))
            npl.qa_run = fake_qa_run
            try:
                out = npl.accept_done_derived_start_frames(ctx)
            finally:
                rga._orders = saved[0]
                for n, v in zip(names, saved[1:]):
                    setattr(npl, n, v)
            return out, json.loads(ar.read_text()), built

    def test_order_bound_to_the_still_admits_a_finished_unit(self):
        out, ar, built = self.run_case()
        self.assertEqual(out["status"], "ADMITTED")
        self.assertEqual(out["still_not_admitted"], [])
        self.assertEqual(len(built), 1)
        self.assertEqual(ar["downstream_status"], "ADMITTED_FOR_VIDEO_SUBMIT")
        self.assertEqual(ar["status"], "ADMITTED_BY_LINE_OWNER_ORDER")
        self.assertEqual(ar["engine_failures"], FAILURES)  # the reviewed FAIL stays recorded
        self.assertEqual(ar["line_owner_acceptance"]["order_seq"], 196)

    def test_no_order_stays_rejected(self):
        out, ar, _built = self.run_case(with_order=False)
        self.assertEqual(out["status"], "NOT_ADMITTED")
        self.assertEqual(out["still_not_admitted"], [UID])
        self.assertEqual(ar["downstream_status"], "FAIL_NOT_ADMITTED")

    def test_unit_without_a_clip_is_left_to_the_wave_loop(self):
        out, ar, built = self.run_case(clip=False)
        self.assertEqual(out, {})
        self.assertEqual(built, [])
        self.assertEqual(ar["downstream_status"], "FAIL_NOT_ADMITTED")

    def test_no_valid_review_for_the_bytes_on_disk_builds_nothing(self):
        out, ar, built = self.run_case(reviewed=False)
        self.assertEqual(out["status"], "NO_VALID_REVIEW_FOR_STILL_ON_DISK")
        self.assertEqual(built, [])
        self.assertEqual(ar["downstream_status"], "FAIL_NOT_ADMITTED")

    def test_final_pass_runs_it_before_the_full_compile(self):
        src = inspect.getsource(npl.stage_s6)
        self.assertLess(src.index("accept_done_derived_start_frames(ctx)"),
                        src.index("final_pass=True"))


if __name__ == "__main__":
    unittest.main()
