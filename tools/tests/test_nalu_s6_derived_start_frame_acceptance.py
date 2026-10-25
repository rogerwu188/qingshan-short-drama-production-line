"""S6.q1_derived honours a START-FRAME-SEMANTIC-EVIDENCE default acceptance bound to the exact still.

Lab Holmes E03 (2026-10-24): the derived stills of VU-002/005/008 were reviewed FAIL, a controlled redo
was spent, and the line owner's default acceptance was recorded for the start-frame gate (receipt
ACCEPTED_BY_LINE_OWNER_ORDER).  The Q1 overlay only looked for orders keyed by the failing Q1 gates, so S6
re-ran admission and rejected the same stills forever.
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

# the module object nalu_pipeline really calls (another test may have re-imported roger_gate_acceptance)
rga = npl._rga

UID, ITEM = "E03-VU-002", "E03-S01-02"
DETECTORS = ["E03-VU-002:CAMERA_START_FRAMING_NOT_VERIFIED", "E03-VU-002:VLM_REVIEW_REJECT"]
FAILURES = ["evidence_1:CHARACTER-IDENTITY-ADMISSION:registered_gate_not_pass:FAIL_NOT_ADMITTED:P0",
            "evidence_3:ACTION-SHOT-DESIGN-AND-STATE-HANDOFF:registered_gate_not_pass:FAIL_NOT_ADMITTED:P0",
            "required_registered_gate_not_pass:CHARACTER-IDENTITY-ADMISSION",
            "required_registered_gate_not_pass:ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"]


def _order(tmp: Path, sha: str, *, gate="START-FRAME-SEMANTIC-EVIDENCE", detectors=DETECTORS, status="active"):
    verbatim = "默认条款自动接受：质量问题不阻塞连续生产（短剧工作流）"
    receipt = {"schema": rga.RECEIPT_SCHEMA, "status": "CONFIRMED", "issued_by": "owner",
               "order_seq": 69, "order_id": "SEQ069", "verbatim": verbatim,
               "recorded_at_utc": "2026-10-24T21:37:41Z"}
    path = tmp / "receipt69.json"; path.write_text(json.dumps(receipt))
    return {"seq": 69, "id": "SEQ069", "issued_by": "owner", "status": status, "order": verbatim,
            "decision": {"kind": "GATE_FAIL_ACCEPTANCE", "episode": "E03", "gate_id": gate,
                         "detectors": list(detectors), "media_sha256_by_item": {UID: sha}},
            "source_receipt": {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}


class DerivedStartFrameAcceptanceTests(unittest.TestCase):
    def run_case(self, *, order_kw=None, receipt_status="ACCEPTED_BY_LINE_OWNER_ORDER", receipt_sha=None,
                 failures=FAILURES, derived=True, no_order=False):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            kf = tmp / "keyframes" / f"{ITEM}-keyframe-v1.png"; kf.parent.mkdir(parents=True)
            kf.write_bytes(b"derived tail frame")
            sha = hashlib.sha256(kf.read_bytes()).hexdigest()
            q1 = tmp / "reports/qa/q1" / UID; q1.mkdir(parents=True)
            ar = q1 / "admission_result.json"
            ar.write_text(json.dumps({"status": "FAIL", "downstream_status": "FAIL_NOT_ADMITTED",
                                      "asset_sha256": sha, "failures": failures}))
            index = {"unit_count": 1, "admitted_count": 0, "status": "PARTIAL_0_OF_1_ADMITTED",
                     "video_submission_allowed_unit_ids": [], "rejected_unit_ids": [UID],
                     "results": [{"unit_id": UID, "item_id": ITEM, "status": "FAIL",
                                  "downstream_status": "FAIL_NOT_ADMITTED", "asset_sha256": sha,
                                  "failures": failures, "admission_result": str(ar)}]}
            ip = tmp / "reports/qa/q1/E03_KEYFRAME_Q1_INDEX.json"; ip.write_text(json.dumps(index))
            sfe = tmp / "engine/reports/start_frame_evidence"; sfe.mkdir(parents=True)
            rs = receipt_sha or sha
            (sfe / f"{UID}_start_frame_evidence.json").write_text(json.dumps({
                "status": receipt_status, "reference_sha256": rs,
                "line_owner_acceptance": {"accepted_detectors": DETECTORS, "media_sha256": rs}}))
            orders = [] if no_order else [_order(tmp, sha, **(order_kw or {}))]
            ctx = types.SimpleNamespace(episode="E03", p=types.SimpleNamespace(preprod_reports=tmp / "reports"),
                                        authority_blockers=[],
                                        authority={"orders_path": tmp / "ORDERS.json", "latest_order_seq": 69,
                                                   "line_owner_id": "owner"})
            saved = (rga._orders, npl.ENGINE, npl.continuity_derived_units)
            rga._orders = lambda *a, **k: orders
            npl.ENGINE = tmp / "engine"  # order source receipts live outside the engine
            npl.continuity_derived_units = lambda _ctx: (
                {UID: {"first_shot_id": ITEM, "keyframe_path": kf}} if derived else {})
            try:
                out = npl.apply_derived_start_frame_acceptance(ctx, index, ip)
            finally:
                rga._orders, npl.ENGINE, npl.continuity_derived_units = saved
            return out, json.loads(ip.read_text()), json.loads(ar.read_text())

    def test_sha_bound_start_frame_default_acceptance_admits(self):
        out, index, ar = self.run_case()
        self.assertEqual(out["accepted_unit_ids"], [UID])
        self.assertEqual(index["status"], "ALL_ADMITTED")
        self.assertEqual(ar["downstream_status"], "ADMITTED_FOR_VIDEO_SUBMIT")
        rec = ar["line_owner_acceptance"]
        self.assertEqual(rec["acceptance_status"], "ACCEPTED_BY_DEFAULT_ORDER")
        self.assertEqual(rec["gate_status_kept"], "FAIL")
        self.assertEqual(rec["order_seq"], 69)
        self.assertEqual(ar["engine_failures"], FAILURES)  # the review's FAIL stays recorded

    def test_refusals_stay_rejected(self):
        cases = ({"no_order": True}, {"receipt_status": "FAIL"}, {"receipt_sha": "b" * 64},
                 {"order_kw": {"status": "done"}}, {"order_kw": {"gate": "SOME-OTHER-GATE"}},
                 {"order_kw": {"detectors": DETECTORS[:1]}}, {"derived": False},
                 {"failures": FAILURES + ["required_registered_gate_not_pass:KEYFRAME-INTEGRITY"]},
                 {"failures": FAILURES + ["something_unattributed"]})
        for kw in cases:
            with self.subTest(kw=kw):
                out, index, ar = self.run_case(**kw)
                self.assertEqual(out["accepted_unit_ids"], [])
                self.assertEqual(ar["downstream_status"], "FAIL_NOT_ADMITTED")
                self.assertEqual(index["rejected_unit_ids"], [UID])


if __name__ == "__main__":
    unittest.main()
