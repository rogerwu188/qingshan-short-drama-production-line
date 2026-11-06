"""S5 Q1: a sha-bound line-owner default acceptance admits a still whose ONLY failing gate is
ACTION-SHOT-DESIGN-AND-STATE-HANDOFF.

Lab Holmes E11 (2026-10-31): 16 keyframes still failed only the action/state-handoff gate after the
controlled redraw; the owner's default-acceptance orders (seq 211-226) were bound to each exact sha, but
the single-gate route only knew identity/period and the per-gate route required more than one failing
gate, so every still stayed rejected and S5 could not pass.
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

UID, ITEM = "E11-VU-002", "E11-S01-02"
GATE = "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"
FAILURES = [f"evidence_3:{GATE}:registered_gate_not_pass:FAIL_NOT_ADMITTED:P0",
            f"required_registered_gate_not_pass:{GATE}"]


def _order(tmp: Path, sha: str, *, gate=GATE, detectors=(f"{ITEM}:{GATE}",), status="active", item=ITEM):
    verbatim = "默认条款自动接受：质量问题不阻塞连续生产（短剧工作流）"
    receipt = {"schema": rga.RECEIPT_SCHEMA, "status": "CONFIRMED", "issued_by": "owner",
               "order_seq": 211, "order_id": "SEQ211", "verbatim": verbatim,
               "recorded_at_utc": "2026-10-31T09:20:00Z"}
    path = tmp / "receipt211.json"; path.write_text(json.dumps(receipt))
    return {"seq": 211, "id": "SEQ211", "issued_by": "owner", "status": status, "order": verbatim,
            "decision": {"kind": "GATE_FAIL_ACCEPTANCE", "episode": "E11", "gate_id": gate,
                         "detectors": list(detectors), "media_sha256_by_item": {item: sha}},
            "source_receipt": {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}


class SingleActionGateAcceptanceTests(unittest.TestCase):
    def run_case(self, *, order_kw=None, failures=FAILURES, no_order=False, order_sha=None):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            kf = tmp / "keyframes" / f"{ITEM}-keyframe-v1.png"; kf.parent.mkdir(parents=True)
            kf.write_bytes(b"redrawn keyframe")
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
            ip = tmp / "reports/qa/q1/E11_KEYFRAME_Q1_INDEX.json"; ip.write_text(json.dumps(index))
            orders = [] if no_order else [_order(tmp, order_sha or sha, **(order_kw or {}))]
            ctx = types.SimpleNamespace(episode="E11", p=types.SimpleNamespace(preprod_reports=tmp / "reports"),
                                        authority_blockers=[],
                                        authority={"orders_path": tmp / "ORDERS.json", "latest_order_seq": 211,
                                                   "line_owner_id": "owner"})
            saved = (rga._orders, npl.ENGINE)
            rga._orders = lambda *a, **k: orders
            npl.ENGINE = tmp / "engine"
            try:
                out = npl.apply_line_owner_q1_acceptance(ctx, index, ip)
            finally:
                rga._orders, npl.ENGINE = saved
            return out, json.loads(ip.read_text()), json.loads(ar.read_text())

    def test_sha_bound_order_admits_single_action_gate_failure(self):
        out, index, ar = self.run_case()
        self.assertEqual(out["accepted_unit_ids"], [UID])
        self.assertEqual(index["status"], "ALL_ADMITTED")
        self.assertEqual(ar["downstream_status"], "ADMITTED_FOR_VIDEO_SUBMIT")
        rec = ar["line_owner_acceptance"]
        self.assertEqual(rec["gate_ids"], [GATE])
        self.assertEqual(rec["gate_status_kept"], "FAIL")
        self.assertEqual(rec["order_seqs"], [211])
        self.assertEqual(ar["engine_failures"], FAILURES)  # the review's FAIL stays recorded

    def test_single_scene_gate_failure_also_routes(self):
        scene = "SCENE-AUTHORITY-LOCK"
        out, _, _ = self.run_case(
            failures=[f"evidence_2:{scene}:registered_gate_not_pass:FAIL_NOT_ADMITTED:P1",
                      f"required_registered_gate_not_pass:{scene}"],
            order_kw={"gate": scene, "detectors": (f"{ITEM}:{scene}",)})
        self.assertEqual(out["accepted_unit_ids"], [UID])

    def test_refusals_stay_rejected(self):
        cases = ({"no_order": True}, {"order_sha": "b" * 64}, {"order_kw": {"status": "done"}},
                 {"order_kw": {"gate": "SCENE-AUTHORITY-LOCK"}},
                 {"order_kw": {"detectors": (f"{ITEM}:SOMETHING-ELSE",)}},
                 {"order_kw": {"item": "E11-S01-03"}},
                 {"failures": ["required_registered_gate_not_pass:KEYFRAME-INTEGRITY"],
                  "order_kw": {"gate": "KEYFRAME-INTEGRITY", "detectors": (f"{ITEM}:KEYFRAME-INTEGRITY",)}},
                 {"failures": FAILURES + ["something_unattributed"]})
        for kw in cases:
            with self.subTest(kw=kw):
                out, index, ar = self.run_case(**kw)
                self.assertEqual(out["accepted_unit_ids"], [])
                self.assertEqual(ar["downstream_status"], "FAIL_NOT_ADMITTED")
                self.assertEqual(out["still_rejected_unit_ids"], [UID])


if __name__ == "__main__":
    unittest.main()
