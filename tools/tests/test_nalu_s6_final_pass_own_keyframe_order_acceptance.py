"""S6 final pass applies a recorded line-owner acceptance to a finished unit's OWN start keyframe.

Device 0334 E05 (2026-11-15): all 31 keyframes were re-reviewed after a controlled redo.  VU-024 already had
its clip and starts from its own keyframe S04-01, which the re-review failed on PERIOD-ANACHRONISM-LOCK.  The
default acceptance was recorded for that exact sha (seq 120) and nothing applied it: the final pass re-checked
tail-sourced units only, and S5 reused an ALL_ADMITTED index the final pass had rewritten for two derived
stills.  The full compile stopped on INPUT_COMPLETENESS_FAILED:SEMANTIC_ANCHOR_EVIDENCE_INVALID.
"""
from __future__ import annotations

import hashlib
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

UID, ITEM, GATE = "E05-VU-024", "E05-S04-01", "PERIOD-ANACHRONISM-LOCK"
FAILURES = [f"evidence_4:{GATE}:registered_gate_not_pass:FAIL_NOT_ADMITTED:P0",
            f"required_registered_gate_not_pass:{GATE}"]


def _order(tmp: Path, sha: str):
    verbatim = "默认条款自动接受：质量问题不阻塞连续生产（短剧工作流）"
    receipt = {"schema": rga.RECEIPT_SCHEMA, "status": "CONFIRMED", "issued_by": "owner",
               "order_seq": 120, "order_id": "SEQ120", "verbatim": verbatim,
               "recorded_at_utc": "2026-11-15T11:50:00Z"}
    path = tmp / "receipt120.json"; path.write_text(json.dumps(receipt))
    return {"seq": 120, "id": "SEQ120", "issued_by": "owner", "status": "active", "order": verbatim,
            "decision": {"kind": "GATE_FAIL_ACCEPTANCE", "episode": "E05", "gate_id": GATE,
                         "detectors": [f"{ITEM}:{GATE}"], "media_sha256_by_item": {ITEM: sha}},
            "source_receipt": {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}


class FinalPassOwnKeyframeOrderAcceptanceTests(unittest.TestCase):
    def run_case(self, *, clip=True, with_order=True, judged="same", admitted=False, derived=False):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            preprod = tmp / "preprod"; preprod.mkdir()
            (preprod / "E05_VIDEO_UNIT_GROUPING_PLAN_V1.json").write_text(json.dumps(
                {"units": [{"unit_id": UID, "editorial_shot_ids": [ITEM, "E05-S04-02"]}]}))
            kf = tmp / "keyframes" / f"{ITEM}-keyframe-v1.png"; kf.parent.mkdir(parents=True)
            kf.write_bytes(b"own keyframe with an anachronistic prop")
            sha = hashlib.sha256(kf.read_bytes()).hexdigest()
            reports = tmp / "reports"
            ar = reports / "qa/q1" / UID / "admission_result.json"; ar.parent.mkdir(parents=True)
            fail = {"status": "FAIL", "downstream_status": "FAIL_NOT_ADMITTED",
                    "asset_sha256": sha if judged == "same" else "0" * 64, "failures": FAILURES}
            if admitted:
                fail = {"status": "PASS", "downstream_status": "ADMITTED_FOR_VIDEO_SUBMIT",
                        "asset_sha256": sha, "failures": []}
            if judged != "never":
                ar.write_text(json.dumps(fail))
            video = tmp / "video"; video.mkdir()
            if clip:
                (video / f"{UID}.mp4").write_bytes(b"clip")
            ip = reports / "qa/q1/E05_KEYFRAME_Q1_INDEX.json"
            built: list[list] = []

            def fake_qa_run(_ctx, argv, *, name):
                built.append(list(argv))
                ar.write_text(json.dumps(fail))
                ip.write_text(json.dumps({
                    "unit_count": 1, "admitted_count": 0, "status": "PARTIAL_0_OF_1_ADMITTED",
                    "video_submission_allowed_unit_ids": [], "rejected_unit_ids": [UID],
                    "results": [{"unit_id": UID, "item_id": ITEM, **fail, "admission_result": str(ar)}]}))
                return {"exit_code": 0, "stdout_tail": json.dumps({"out": str(ip)})}

            asked: list[list[str]] = []

            def fake_merge(_ctx, shots):
                asked.append(list(shots))
                return tmp / "merged_review.json", list(shots), []

            orders = [_order(tmp, sha)] if with_order else []
            ctx = types.SimpleNamespace(
                episode="E05",
                p=types.SimpleNamespace(preprod=preprod, preprod_reports=reports, video_media=video,
                                        keyframes=kf.parent),
                authority_blockers=[],
                authority={"orders_path": tmp / "ORDERS.json", "latest_order_seq": 150, "line_owner_id": "owner"})
            names = ("ENGINE", "continuity_derived_units", "hard_continuation_units", "merge_keyframe_answers",
                     "qa_run")
            saved = (rga._orders, *[getattr(npl, n) for n in names])
            rga._orders = lambda *a, **k: orders
            npl.ENGINE = tmp / "engine"
            npl.continuity_derived_units = lambda _ctx: (
                {UID: {"first_shot_id": ITEM, "keyframe_path": kf}} if derived else {})
            npl.hard_continuation_units = lambda _ctx: {}
            npl.merge_keyframe_answers = fake_merge
            npl.qa_run = fake_qa_run
            try:
                pending = npl.own_done_units_q1_rejected(ctx)
                out = npl.accept_done_derived_start_frames(ctx)
            finally:
                rga._orders = saved[0]
                for n, v in zip(names, saved[1:]):
                    setattr(npl, n, v)
            return out, (json.loads(ar.read_text()) if ar.is_file() else None), built, pending, asked

    def test_order_bound_to_the_own_keyframe_admits_a_finished_unit(self):
        out, ar, built, pending, asked = self.run_case()
        self.assertEqual(pending, [(UID, ITEM)])
        self.assertEqual(asked, [[ITEM]])
        self.assertEqual(out["units"], [UID])
        self.assertEqual(out["status"], "ADMITTED")
        self.assertEqual(out["still_not_admitted"], [])
        self.assertEqual(len(built), 1)
        self.assertEqual(ar["downstream_status"], "ADMITTED_FOR_VIDEO_SUBMIT")
        self.assertEqual(ar["status"], "ADMITTED_BY_LINE_OWNER_ORDER")
        self.assertEqual(ar["engine_failures"], FAILURES)  # the reviewed FAIL stays recorded
        self.assertEqual(ar["line_owner_acceptance"]["order_seq"], 120)

    def test_no_order_stays_rejected(self):
        out, ar, _built, _pending, _asked = self.run_case(with_order=False)
        self.assertEqual(out["status"], "NOT_ADMITTED")
        self.assertEqual(out["still_not_admitted"], [UID])
        self.assertEqual(ar["downstream_status"], "FAIL_NOT_ADMITTED")

    def test_unit_without_a_clip_is_left_to_s5(self):
        out, ar, built, pending, _asked = self.run_case(clip=False)
        self.assertEqual((out, built, pending), ({}, [], []))
        self.assertEqual(ar["downstream_status"], "FAIL_NOT_ADMITTED")

    def test_keyframe_q1_never_judged_is_not_touched(self):
        out, ar, built, pending, _asked = self.run_case(judged="never")
        self.assertEqual((out, built, pending, ar), ({}, [], [], None))

    def test_keyframe_changed_since_q1_is_not_touched(self):
        out, ar, built, pending, _asked = self.run_case(judged="other")
        self.assertEqual((out, built, pending), ({}, [], []))
        self.assertEqual(ar["downstream_status"], "FAIL_NOT_ADMITTED")

    def test_admitted_keyframe_builds_nothing(self):
        out, _ar, built, pending, _asked = self.run_case(admitted=True)
        self.assertEqual((out, built, pending), ({}, [], []))

    def test_tail_sourced_unit_is_counted_once_by_the_derived_route(self):
        out, ar, _built, pending, asked = self.run_case(derived=True)
        self.assertEqual(pending, [])
        self.assertEqual(asked, [[ITEM]])
        self.assertEqual(out["units"], [UID])
        self.assertEqual(ar["downstream_status"], "ADMITTED_FOR_VIDEO_SUBMIT")


if __name__ == "__main__":
    unittest.main()
