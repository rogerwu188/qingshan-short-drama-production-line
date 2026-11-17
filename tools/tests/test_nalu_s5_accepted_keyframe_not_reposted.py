"""S5 applies the line-owner Q1 acceptance orders before deciding which keyframes to POST.

Device ...1101 E15 (2026-11-17): five stills failed Q1 on CHARACTER-IDENTITY-ADMISSION, the default
acceptance orders were recorded for those exact images, and the next S5 entry still planned a paid re-render
of all five because the order overlay only ran after the paid submit.
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

rga = npl._rga  # the module object the pipeline itself calls (another test may have re-imported it)

SHOT, UNIT, TASK = "E06-S02-01", "E06-VU-004", "E06-S02-01-KEYFRAME-V1"


def _fixture(tmp: Path):
    keyframes = tmp / "keyframes"; keyframes.mkdir()
    image = keyframes / f"{SHOT}-keyframe-v1.png"; image.write_bytes(b"the-still-q1-judged")
    sha = hashlib.sha256(image.read_bytes()).hexdigest()
    manifest = tmp / "manifest.json"
    manifest.write_text(json.dumps({"tasks": [
        {"task_key": TASK, "shot_id": SHOT,
         "output_contract": {"expected_output_path": str(image)}}]}))
    q1 = tmp / "reports/qa/q1" / UNIT; q1.mkdir(parents=True)
    ar = q1 / "admission_result.json"
    failures = ["evidence_1:CHARACTER-IDENTITY-ADMISSION:registered_gate_not_pass:FAIL_NOT_ADMITTED:P0",
                "required_registered_gate_not_pass:CHARACTER-IDENTITY-ADMISSION"]
    ar.write_text(json.dumps({"status": "FAIL", "downstream_status": "FAIL_NOT_ADMITTED",
                              "asset_sha256": sha, "failures": failures}))
    ident = tmp / "reports/qa/E06_KEYFRAME_IDENTITY_ADMISSION.json"
    ident.write_text(json.dumps({"objective_verification": {"decisions": [
        {"source_id": f"E06:STILL:{SHOT}", "character_id": "CHAR-QINMING",
         "aggregate_median": 0.288, "decision": "FAIL"}]}}))
    index = {"unit_count": 1, "admitted_count": 0, "status": "PARTIAL_0_OF_1_ADMITTED",
             "video_submission_allowed_unit_ids": [], "rejected_unit_ids": [UNIT],
             "identity_measurement": {"engine_report": str(ident)},
             "results": [{"unit_id": UNIT, "item_id": SHOT, "status": "FAIL",
                          "downstream_status": "FAIL_NOT_ADMITTED", "asset_sha256": sha,
                          "failures": failures, "admission_result": str(ar)}]}
    ip = tmp / "reports/qa/q1/E06_KEYFRAME_Q1_INDEX.json"; ip.write_text(json.dumps(index))
    said: list[str] = []
    ctx = types.SimpleNamespace(
        episode="E06", authority_blockers=[], say=said.append,
        p=types.SimpleNamespace(preprod_reports=tmp / "reports", keyframes=keyframes,
                                keyframe_manifest=manifest),
        authority={"orders_path": tmp / "SUPERVISOR_ORDERS.json",
                   "latest_order_seq": 31, "line_owner_id": "owner-1"})
    return ctx, ip, ar, sha, image


def _order(tmp: Path, sha: str):
    verbatim = "Accept the named identity failure for this exact keyframe."
    receipt = {"schema": rga.RECEIPT_SCHEMA, "status": "CONFIRMED", "issued_by": "owner-1",
               "order_seq": 31, "order_id": "ACCEPT-31", "verbatim": verbatim,
               "recorded_at_utc": "2026-09-20T00:00:00Z"}
    path = tmp / "accept-source.json"; path.write_text(json.dumps(receipt))
    return {"seq": 31, "id": "ACCEPT-31", "issued_by": "owner-1", "status": "active", "order": verbatim,
            "decision": {"kind": "GATE_FAIL_ACCEPTANCE", "episode": "E06",
                         "gate_id": "CHARACTER-IDENTITY-ADMISSION",
                         "detectors": [f"{SHOT}:CHAR-QINMING"],
                         "media_sha256_by_item": {SHOT: sha}},
            "source_receipt": {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}


class S5AcceptedKeyframeTests(unittest.TestCase):
    def _run(self, *, with_order: bool, sha_of_order: str | None = None, replace_image: bool = False):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            ctx, ip, ar, sha, image = _fixture(tmp)
            orders = [_order(tmp, sha_of_order or sha)] if with_order else []
            if replace_image:
                image.write_bytes(b"re-rendered-after-the-review")
            saved = rga._orders
            rga._orders = lambda *args, **kwargs: orders
            try:
                need, done = npl.s5_keyframes_to_post(ctx, ip)
            finally:
                rga._orders = saved
            return need, done, json.loads(ar.read_text()), json.loads(ip.read_text())

    def test_a_rejected_still_with_its_order_is_not_reposted(self):
        need, done, ar, index = self._run(with_order=True)
        self.assertEqual(need, [])
        self.assertEqual(done, [TASK])
        self.assertEqual(ar["downstream_status"], "ADMITTED_FOR_VIDEO_SUBMIT")
        self.assertEqual(ar["engine_downstream_status"], "FAIL_NOT_ADMITTED")
        self.assertEqual(index["status"], "ALL_ADMITTED")

    def test_a_rejected_still_without_an_order_is_still_posted(self):
        need, done, ar, _ = self._run(with_order=False)
        self.assertEqual(need, [TASK])
        self.assertEqual(done, [])
        self.assertEqual(ar["downstream_status"], "FAIL_NOT_ADMITTED")

    def test_an_order_for_another_image_does_not_stop_the_post(self):
        need, _, ar, _ = self._run(with_order=True, sha_of_order="b" * 64)
        self.assertEqual(need, [TASK])
        self.assertEqual(ar["downstream_status"], "FAIL_NOT_ADMITTED")

    def test_an_accepted_still_that_was_replaced_since_is_posted(self):
        need, _, _, _ = self._run(with_order=True, replace_image=True)
        self.assertEqual(need, [TASK])


if __name__ == "__main__":
    unittest.main()
