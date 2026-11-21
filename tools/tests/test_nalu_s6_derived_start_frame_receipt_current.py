"""S6 derived start frames: the START-FRAME-SEMANTIC-EVIDENCE receipt is keyed on the exact admitted bytes, and a
Q1-rejected derived still with a valid default acceptance never waits for a receipt that only exists after Q1.

Device 1485 (JA-01 anime E03, engine 900bd67, 2026-11-21): four derived start frames were Q1-reviewed FAIL
(PERIOD-ANACHRONISM-LOCK / ACTION-SHOT-DESIGN-AND-STATE-HANDOFF).  S6 stopped on S6.q1_derived:NOT_ADMITTED with
only the start-frame route's refusal (NO_ACCEPTED_START_FRAME_RECEIPT_FOR_THIS_SHA) on screen, although that
receipt is written by S6.sfe_derived only AFTER Q1 admission; and S6 treated any receipt FILE as present, so a
derived frame rewritten after its receipt (#277/#284 tail rewrites, #286 tail rejected -> own keyframe) kept the
receipt of the old bytes for good.
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

UID, ITEM = "E03-VU-012", "E03-S04-02"
PERIOD, ACTION = "PERIOD-ANACHRONISM-LOCK", "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"
FAILURES = [f"evidence_2:{PERIOD}:registered_gate_not_pass:FAIL_NOT_ADMITTED:P0",
            f"evidence_3:{ACTION}:registered_gate_not_pass:FAIL_NOT_ADMITTED:P0",
            f"required_registered_gate_not_pass:{PERIOD}",
            f"required_registered_gate_not_pass:{ACTION}"]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _order(tmp: Path, seq: int, gate: str, detectors: list[str], binding: dict[str, str]) -> dict:
    verbatim = "默认条款自动接受：质量问题不阻塞连续生产（短剧工作流）"
    receipt = {"schema": rga.RECEIPT_SCHEMA, "status": "CONFIRMED", "issued_by": "owner",
               "order_seq": seq, "order_id": f"SEQ{seq:03d}", "verbatim": verbatim,
               "recorded_at_utc": "2026-11-21T07:20:00Z"}
    path = tmp / f"receipt{seq}.json"; path.write_text(json.dumps(receipt))
    return {"seq": seq, "id": f"SEQ{seq:03d}", "issued_by": "owner", "status": "active", "order": verbatim,
            "decision": {"kind": "GATE_FAIL_ACCEPTANCE", "episode": "E03", "gate_id": gate,
                         "detectors": detectors, "media_sha256_by_item": binding},
            "source_receipt": {"path": str(path), "sha256": _sha(path)}}


class _Env:
    """A tmp engine/runtime with one derived unit whose start frame is ``kf``."""

    def __init__(self, tmp: Path, *, own_keyframe: bool = False):
        self.tmp = tmp
        self.kf = tmp / "keyframes" / f"{ITEM}-keyframe-v1.png"; self.kf.parent.mkdir(parents=True)
        self.kf.write_bytes(b"previous unit real tail")
        if not own_keyframe:
            self.kf.with_suffix(".derived.json").write_text("{}")
        self.reviews = tmp / "reviews"; (self.reviews / "E03").mkdir(parents=True)
        self.engine = tmp / "engine"; (self.engine / "reports/start_frame_evidence").mkdir(parents=True)
        self.reports = tmp / "reports"
        self.orders: list[dict] = []
        self.ctx = types.SimpleNamespace(
            episode="E03", run_id="R1", dry=False, say=lambda *_a, **_k: None,
            p=types.SimpleNamespace(preprod_reports=self.reports, preprod=tmp / "preprod",
                                    keyframes=self.kf.parent, video_media=tmp / "video"),
            authority_blockers=[],
            authority={"orders_path": tmp / "ORDERS.json", "latest_order_seq": 999, "line_owner_id": "owner"})
        self.requests: list[list[str]] = []
        self.writes: list[str] = []
        self._saved: list = []

    def receipt(self, sha: str, status: str = "PASS", **extra) -> Path:
        path = self.engine / "reports/start_frame_evidence" / f"{UID}_start_frame_evidence.json"
        path.write_text(json.dumps({"status": status, "reference_sha256": sha, "reference_path": str(self.kf),
                                    "blockers": [] if status == "PASS" else ["VLM_REVIEW_FAIL"], **extra}))
        return path

    def review(self, name: str, sha: str) -> Path:
        path = self.reviews / "E03" / f"{name}_submitted.json"
        path.write_text(json.dumps({
            "kind": "start_frame", "reviewer": npl.REVIEWER_ID, "validation": {"status": "PASS"},
            "items": [{"item_id": UID, "verdict": "PASS", "request_item": {
                "media": [{"role": "START_FRAME_KEYFRAME", "path": str(self.kf), "sha256": sha}]}}]}))
        return path

    def fake_writer(self, _ctx, argv, *, name):
        """start_frame_evidence_writer write: a receipt of the bytes the merged review looked at."""
        review = json.loads(Path(argv[argv.index("--review") + 1]).read_text())
        self.writes.append(name)
        for item in review["items"]:
            self.receipt(item["request_item"]["media"][0]["sha256"])
        return {"exit_code": 0, "stdout_tail": json.dumps({"status": "PASS"})}

    def fake_request(self, _ctx, res, kind, *, sub_stage, note="", items=None, skip_when_empty=False):
        self.requests.append(sorted(items or []))
        res.status = npl.REVIEW_REQUIRED
        return {"kind": kind, "items": len(items or [])}

    def __enter__(self):
        names = ("ENGINE", "REVIEWS_ROOT", "qa_run", "request_review", "continuity_derived_units",
                 "hard_continuation_units")
        self._saved = [rga._orders, *[(n, getattr(npl, n)) for n in names]]
        rga._orders = lambda *a, **k: self.orders
        npl.ENGINE, npl.REVIEWS_ROOT = self.engine, self.reviews
        npl.qa_run, npl.request_review = self.fake_writer, self.fake_request
        npl.continuity_derived_units = lambda _ctx: {UID: {"first_shot_id": ITEM, "keyframe_path": self.kf,
                                                           "previous_unit_id": "E03-VU-011"}}
        npl.hard_continuation_units = lambda _ctx: {}
        return self

    def __exit__(self, *exc):
        rga._orders = self._saved[0]
        for n, v in self._saved[1:]:
            setattr(npl, n, v)


class ReceiptKeyedOnAdmittedBytesTests(unittest.TestCase):
    def test_receipt_states(self):
        with tempfile.TemporaryDirectory() as d, _Env(Path(d)) as env:
            self.assertEqual(npl.start_frame_receipt_state(UID, env.kf), npl.SFE_MISSING)
            env.receipt(_sha(env.kf))
            self.assertEqual(npl.start_frame_receipt_state(UID, env.kf), npl.SFE_CURRENT)
            env.receipt(_sha(env.kf), status="FAIL")
            self.assertEqual(npl.start_frame_receipt_state(UID, env.kf), npl.SFE_CURRENT_FAIL)
            env.receipt(_sha(env.kf), status="ACCEPTED_BY_LINE_OWNER_ORDER",
                        line_owner_acceptance={"media_sha256": _sha(env.kf)})
            self.assertEqual(npl.start_frame_receipt_state(UID, env.kf), npl.SFE_CURRENT)
            env.kf.write_bytes(b"normalised / text-cleaned tail")  # #277 / #284 rewrite after the receipt
            self.assertEqual(npl.start_frame_receipt_state(UID, env.kf), npl.SFE_STALE)

    def test_frame_rewritten_after_evidence_gets_a_new_receipt_for_the_new_bytes(self):
        with tempfile.TemporaryDirectory() as d, _Env(Path(d)) as env:
            old_sha = _sha(env.kf)
            env.receipt(old_sha)
            env.review("E03-start_frame-20261121T0700", old_sha)
            env.kf.write_bytes(b"re-materialised normalised tail")  # receipt + review now describe old bytes
            res = npl.StageResult(npl.REVIEW_REQUIRED)
            # before: the receipt FILE existed, so nothing was asked and the old receipt stayed for good
            self.assertEqual(npl.ensure_derived_start_frame_receipts(env.ctx, res, {UID: env.kf}), "STOP")
            self.assertEqual(env.requests, [[UID]])  # a review of exactly the new bytes
            self.assertEqual(env.writes, [])        # the old review is never used for the new bytes
            # the reviewer answers the new bytes: the engine writes the receipt, keyed on them
            env.review("E03-start_frame-20261121T0730", _sha(env.kf))
            res = npl.StageResult(npl.REVIEW_REQUIRED)
            self.assertEqual(npl.ensure_derived_start_frame_receipts(env.ctx, res, {UID: env.kf}), "WRITTEN")
            self.assertEqual(npl.start_frame_receipt_state(UID, env.kf), npl.SFE_CURRENT)
            self.assertEqual(npl.ensure_derived_start_frame_receipts(env.ctx, npl.StageResult(npl.PASS),
                                                                     {UID: env.kf}), "OK")

    def test_tail_rejected_motivated_cut_on_own_keyframe_gets_a_receipt_for_that_keyframe(self):
        with tempfile.TemporaryDirectory() as d, _Env(Path(d), own_keyframe=True) as env:
            tail_sha = hashlib.sha256(b"rejected predecessor tail").hexdigest()
            env.receipt(tail_sha)  # written for the tail before #286 rejected it
            res = npl.StageResult(npl.REVIEW_REQUIRED)
            self.assertEqual(npl.start_frame_receipt_state(UID, env.kf), npl.SFE_STALE)
            self.assertEqual(npl.ensure_derived_start_frame_receipts(env.ctx, res, {UID: env.kf}), "STOP")
            self.assertEqual(env.requests, [[UID]])
            env.review("E03-start_frame-20261121T0740", _sha(env.kf))
            self.assertEqual(npl.ensure_derived_start_frame_receipts(env.ctx, npl.StageResult(npl.REVIEW_REQUIRED),
                                                                     {UID: env.kf}), "WRITTEN")
            receipt = json.loads(npl.start_frame_receipt_path(UID).read_text())
            self.assertEqual(receipt["reference_sha256"], _sha(env.kf))

    def test_failing_receipt_for_current_bytes_names_the_order_and_is_rewritten(self):
        with tempfile.TemporaryDirectory() as d, _Env(Path(d)) as env:
            env.review("E03-start_frame-20261121T0750", _sha(env.kf))
            env.fake_writer = lambda _c, argv, *, name: (env.writes.append(name),
                                                         env.receipt(_sha(env.kf), status="FAIL"),
                                                         {"exit_code": 2})[-1]
            npl.qa_run = env.fake_writer
            res = npl.StageResult(npl.REVIEW_REQUIRED)
            self.assertEqual(npl.ensure_derived_start_frame_receipts(env.ctx, res, {UID: env.kf}), "STOP")
            self.assertEqual(res.status, npl.BLOCKED)
            need = res.details["start_frame_orders_needed"][0]
            self.assertEqual((need["gate_id"], need["detectors"], need["media_sha256"]),
                             (npl.START_FRAME_GATE_ID, [f"{UID}:VLM_REVIEW_FAIL"], _sha(env.kf)))


def _q1_index(env: _Env) -> tuple[dict, Path, Path]:
    sha = _sha(env.kf)
    ar = env.reports / "qa/q1" / UID / "admission_result.json"; ar.parent.mkdir(parents=True, exist_ok=True)
    ar.write_text(json.dumps({"status": "FAIL", "downstream_status": "FAIL_NOT_ADMITTED", "asset_sha256": sha,
                              "failures": FAILURES}))
    index = {"unit_count": 1, "admitted_count": 0, "status": "PARTIAL_0_OF_1_ADMITTED",
             "video_submission_allowed_unit_ids": [], "rejected_unit_ids": [UID],
             "results": [{"unit_id": UID, "item_id": ITEM, "status": "FAIL", "downstream_status": "FAIL_NOT_ADMITTED",
                          "asset_sha256": sha, "asset_path": str(env.kf), "failures": FAILURES,
                          "admission_result": str(ar)}]}
    ip = env.reports / "qa/q1/E03_KEYFRAME_Q1_INDEX.json"; ip.write_text(json.dumps(index))
    return index, ip, ar


class Q1RejectedDerivedStillTests(unittest.TestCase):
    def test_orders_needed_name_each_failing_gate(self):
        with tempfile.TemporaryDirectory() as d, _Env(Path(d)) as env:
            index, _ip, _ar = _q1_index(env)
            need = npl.q1_orders_needed(env.ctx, index, [UID])[0]
            self.assertEqual(need["media_sha256"], _sha(env.kf))
            self.assertEqual([(o["gate_id"], o["detectors"]) for o in need["orders"]],
                             [(ACTION, [f"{ITEM}:{ACTION}"]), (PERIOD, [f"{ITEM}:{PERIOD}"])])

    def test_per_gate_orders_admit_under_shot_or_unit_binding(self):
        for key in (ITEM, UID):
            with self.subTest(binding=key), tempfile.TemporaryDirectory() as d, _Env(Path(d)) as env:
                index, ip, ar = _q1_index(env)
                sha = _sha(env.kf)
                env.orders[:] = [_order(env.tmp, 301, PERIOD, [f"{key}:{PERIOD}"], {key: sha}),
                                 _order(env.tmp, 302, ACTION, [f"{key}:{ACTION}"], {key: sha})]
                out = npl.apply_line_owner_q1_acceptance(env.ctx, index, ip)
                self.assertEqual(out["accepted_unit_ids"], [UID])
                row = json.loads(ar.read_text())
                self.assertEqual(row["downstream_status"], "ADMITTED_FOR_VIDEO_SUBMIT")
                self.assertEqual(row["engine_failures"], FAILURES)  # the reviewed FAIL stays recorded

    def test_missing_gate_order_or_other_sha_stays_rejected(self):
        with tempfile.TemporaryDirectory() as d, _Env(Path(d)) as env:
            index, ip, ar = _q1_index(env)
            env.orders[:] = [_order(env.tmp, 301, PERIOD, [f"{ITEM}:{PERIOD}"], {ITEM: _sha(env.kf)}),
                             _order(env.tmp, 302, ACTION, [f"{ITEM}:{ACTION}"], {ITEM: "b" * 64})]
            self.assertEqual(npl.apply_line_owner_q1_acceptance(env.ctx, index, ip)["accepted_unit_ids"], [])
            self.assertEqual(npl.apply_derived_start_frame_acceptance(env.ctx, index, ip)["accepted_unit_ids"], [])
            self.assertEqual(json.loads(ar.read_text())["downstream_status"], "FAIL_NOT_ADMITTED")

    def test_start_frame_gate_order_naming_the_q1_gates_admits_without_a_receipt(self):
        with tempfile.TemporaryDirectory() as d, _Env(Path(d)) as env:
            index, ip, ar = _q1_index(env)
            sha = _sha(env.kf)
            env.orders[:] = [_order(env.tmp, 303, npl.START_FRAME_GATE_ID, [f"{UID}:{PERIOD}", f"{UID}:{ACTION}"],
                                    {UID: sha})]
            self.assertFalse(npl.start_frame_receipt_path(UID).is_file())  # the receipt cannot exist yet
            out = npl.apply_derived_start_frame_acceptance(env.ctx, index, ip)
            self.assertEqual(out["accepted_unit_ids"], [UID])
            row = json.loads(ar.read_text())
            self.assertEqual(row["line_owner_acceptance"]["accepted_under"], "START_FRAME_GATE_ORDER_NAMING_Q1_GATES")
            self.assertFalse(npl.start_frame_receipt_path(UID).is_file())  # never forged: the engine writes it later

    def test_start_frame_gate_order_must_name_every_q1_gate(self):
        with tempfile.TemporaryDirectory() as d, _Env(Path(d)) as env:
            index, ip, _ar = _q1_index(env)
            env.orders[:] = [_order(env.tmp, 303, npl.START_FRAME_GATE_ID, [f"{UID}:{PERIOD}"], {UID: _sha(env.kf)})]
            out = npl.apply_derived_start_frame_acceptance(env.ctx, index, ip)
            self.assertEqual(out["accepted_unit_ids"], [])
            self.assertEqual(out["refused"][0]["reason"], "NO_ACCEPTED_START_FRAME_RECEIPT_FOR_THIS_SHA")


class WaveLoopWiringTests(unittest.TestCase):
    def test_wave_loop_keys_receipts_on_bytes_and_names_q1_orders(self):
        import inspect
        src = inspect.getsource(npl.stage_s6)
        self.assertEqual(src.count("ensure_derived_start_frame_receipts(ctx, res, need_sfe"), 2)
        self.assertIn("q1_orders_needed(ctx, _ix", src)
        self.assertNotIn('_start_frame_evidence.json").is_file()]', src)


if __name__ == "__main__":
    unittest.main()
