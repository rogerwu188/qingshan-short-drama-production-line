"""Lab E08 2026-10-29: S3 re-entry re-planned an already harvested multi-view sheet and crashed.

* The sheet's reference list grew (base -> base + headshot) once the headshot was harvested, so its
  submission fingerprint drifted; a bound + harvested take of the same row must be reused, never
  planned or POSTed again (mirrors tools/video_live_binding.py).  Only an explicit
  ``supersedes_submission_fingerprints`` entry, or removing the harvested image, lets a POST through.
* A failure before the intent record has no transaction: it is reported with its original error as
  not charged, never read back from a file that was not written.
* ``CHAR-X__*.json`` must never touch the view rows ``CHAR-X__<VIEW>__*.json``.
* nalu_pipeline: planned credits exclude such a row; a stale submit report never turns a failed
  child into PASS.

Mock only: ``_request`` raises if reached, no API key is read, everything lives in a temp dir.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines" / "nalu" / "runtime" / "tools"))
sys.path.insert(0, str(ROOT))

from tools import submit_giggle_character_asset_plan as submitter  # noqa: E402

MODEL, RES = "gpt-image-2-pro", "2K"
SHEET = "CHAR-X__MULTIVIEW_REFERENCE_SHEET"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Fixture:
    def __init__(self, root: Path):
        self.root = root
        self.tx = root / "workflow" / "tasks" / "giggle_submit_transactions" / "E99"
        self.plates = root / "plates"
        self.plates.mkdir(parents=True)
        self.prompt = root / "sheet.txt"
        self.prompt.write_text("turnaround sheet", encoding="utf-8")
        self.base = root / "base.png"
        self.base.write_bytes(b"base")
        self.head = root / "head.png"
        self.head.write_bytes(b"head")

    def row(self, refs: list[Path], row_id: str = SHEET, **extra) -> dict:
        return {"id": row_id, "episode": "E99", "prompt_file": str(self.prompt),
                "prompt_sha256": _sha(self.prompt), "reference_images": [str(p) for p in refs],
                "reference_image_sha256s": [_sha(p) for p in refs], **extra}

    def bind(self, row: dict, task_id: str, *, harvested: bool = True) -> Path:
        fingerprint = submitter.submission_fingerprint(row, MODEL, RES)
        path = submitter.transaction_path(self.tx, row, MODEL, RES)
        submitter.atomic_json(path, {
            "schema": "qingshan.giggle_submit_transaction.v1", "episode": "E99", "task_key": row["id"],
            "submission_fingerprint": fingerprint, "state": "SUBMITTED_TASK_ID_BOUND", "task_id": task_id,
            "receipt": "r.json", "response_recorded_at": "2026-10-29T21:13:36Z"})
        if harvested:
            (self.plates / f"E99_{submitter.safe_name(row['id'])}_{task_id}.png").write_bytes(b"img")
        return path


def _no_post(*_args, **_kwargs):
    raise AssertionError("provider POST attempted")


class HarvestedBindingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.f = Fixture(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_drifted_fingerprint_reuses_harvested_take_without_post_or_mutation(self):
        first = self.f.row([self.f.base])
        old = self.f.bind(first, "task-sheet-1")
        before = old.read_bytes()
        reentry = self.f.row([self.f.base, self.f.head])  # headshot harvested since: references grew
        with mock.patch.object(submitter, "_request", side_effect=_no_post):
            result = submitter.submit(reentry, self.f.root / "rc", self.f.tx, MODEL, RES, self.f.plates)
        self.assertEqual(result["task_id"], "task-sheet-1")
        self.assertTrue(result["recovered_from_transaction"])
        self.assertTrue(result["reused_harvested_binding"])
        self.assertEqual(old.read_bytes(), before, "the bound transaction must not be rewritten")
        self.assertFalse(submitter.transaction_path(self.f.tx, reentry, MODEL, RES).exists())

    def test_superseded_by_marker_without_superseding_transaction_is_ignored(self):
        first = self.f.row([self.f.base])
        old = self.f.bind(first, "task-sheet-1")
        payload = json.loads(old.read_text(encoding="utf-8"))
        payload["superseded_by"] = "f" * 64
        old.write_text(json.dumps(payload), encoding="utf-8")
        with mock.patch.object(submitter, "_request", side_effect=_no_post):
            result = submitter.submit(self.f.row([self.f.base, self.f.head]), self.f.root / "rc",
                                      self.f.tx, MODEL, RES, self.f.plates)
        self.assertEqual(result["task_id"], "task-sheet-1")

    def test_image_not_on_disk_allows_new_post(self):
        self.f.bind(self.f.row([self.f.base]), "task-sheet-1", harvested=False)
        with mock.patch.object(submitter, "_request", return_value={"data": {"task_id": "task-sheet-2"}}) as req:
            result = submitter.submit(self.f.row([self.f.base, self.f.head]), self.f.root / "rc",
                                      self.f.tx, MODEL, RES, self.f.plates)
        self.assertEqual(req.call_count, 1)
        self.assertEqual(result["task_id"], "task-sheet-2")

    def test_explicit_supersede_allows_regeneration(self):
        first = self.f.row([self.f.base])
        self.f.bind(first, "task-sheet-1")
        old_fp = submitter.submission_fingerprint(first, MODEL, RES)
        redo = self.f.row([self.f.base, self.f.head], supersedes_submission_fingerprints=[old_fp])
        with mock.patch.object(submitter, "_request", return_value={"data": {"task_id": "task-sheet-2"}}) as req:
            result = submitter.submit(redo, self.f.root / "rc", self.f.tx, MODEL, RES, self.f.plates)
        self.assertEqual(req.call_count, 1)
        self.assertEqual(result["task_id"], "task-sheet-2")

    def test_base_row_never_touches_view_row_transactions(self):
        view = self.f.bind(self.f.row([self.f.base], row_id="CHAR-X__FRONT_NEUTRAL_HEADSHOT"), "task-head")
        before = view.read_bytes()
        base_row = self.f.row([], row_id="CHAR-X")
        with mock.patch.object(submitter, "_request", return_value={"data": {"task_id": "task-base"}}):
            submitter.submit(base_row, self.f.root / "rc", self.f.tx, MODEL, RES, self.f.plates)
        self.assertEqual(view.read_bytes(), before)
        self.assertEqual(submitter.harvested_binding(base_row, self.f.tx, self.f.plates,
                                                     current_fingerprint="x"), None)


class PreIntentFailureTests(unittest.TestCase):
    def test_submit_wraps_pre_intent_error_and_writes_no_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(Path(tmp))
            row = f.row([f.base], reviewed_request_sha256="0" * 64)
            with mock.patch.object(submitter, "_request", side_effect=_no_post):
                with self.assertRaises(submitter.PreIntentFailure) as raised:
                    submitter.submit(row, f.root / "rc", f.tx, MODEL, RES, f.plates)
            self.assertIn("reviewed_request_sha256 mismatch", str(raised.exception))
            self.assertFalse(submitter.transaction_path(f.tx, row, MODEL, RES).exists())

    def test_post_intent_error_is_not_wrapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(Path(tmp))
            row = f.row([f.base])
            with mock.patch.object(submitter, "_request", side_effect=RuntimeError("socket closed")):
                with self.assertRaises(RuntimeError) as raised:
                    submitter.submit(row, f.root / "rc", f.tx, MODEL, RES, f.plates)
            self.assertNotIsInstance(raised.exception, submitter.PreIntentFailure)
            state = json.loads(submitter.transaction_path(f.tx, row, MODEL, RES).read_text(encoding="utf-8"))
            self.assertEqual(state["state"], "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION")

    def test_main_reports_original_error_as_not_charged(self):
        with tempfile.TemporaryDirectory(dir=submitter.ROOT) as tmp:
            root = Path(tmp)
            prompt = root / "p.txt"
            prompt.write_text("prop", encoding="utf-8")
            gate = root / "gate.json"
            gate.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            plan = root / "plan.json"
            plan.write_text(json.dumps({
                "episode": "E99TEST", "quality": "pro", "machine_gate_reports": [str(gate)],
                "new_asset_groups": [{"id": "PROP-T", "prompt_file": str(prompt), "prompt_sha256": _sha(prompt),
                                      "reference_images": [], "reference_image_sha256s": []}]}), encoding="utf-8")
            out = root / "report.json"

            def fail(*_args, **_kwargs):
                raise submitter.PreIntentFailure(RuntimeError("original cause"))

            argv = ["x", "--plan", str(plan), "--out", str(out)]
            env = dict(os.environ, GIGGLE_API_KEY="dummy-not-a-key")
            with mock.patch.object(sys, "argv", argv), mock.patch.dict(os.environ, env), \
                    mock.patch.object(submitter, "validate_visual_culture_contract", return_value={"status": "PASS"}), \
                    mock.patch.object(submitter, "submit", side_effect=fail), \
                    mock.patch.object(submitter, "fetch_pay_statements", side_effect=_no_post), \
                    mock.patch.object(submitter, "ROOT", root):
                code = submitter.main()
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(code, 2)
            self.assertEqual(report["status"], "FAIL")
            failure = report["failures"][0]
            self.assertEqual(failure["state"], "submit_failed_before_intent")
            self.assertEqual(failure["credit_status"], "NOT_CHARGED_NO_INTENT_RECORDED")
            self.assertIn("original cause", failure["error"])
            self.assertNotIn("transaction", failure)
            self.assertEqual(report["ambiguity_resolution"], "PRE_INTENT_FAILURES_NOT_CHARGED")


class PipelineTests(unittest.TestCase):
    def test_planner_costs_harvested_drifted_row_at_zero(self):
        import nalu_pipeline as npl
        with tempfile.TemporaryDirectory() as tmp:
            engine = Path(tmp)
            f = Fixture(engine)
            f.tx = engine / "workflow" / "tasks" / "giggle_submit_transactions" / "E99"
            f.bind(f.row([f.base]), "task-sheet-1")
            ctx = SimpleNamespace(episode="E99", p=SimpleNamespace(identity_harvest_dir=f.plates))
            reentry = f.row([f.base, f.head])
            with mock.patch.object(npl, "ENGINE", engine):
                self.assertTrue(npl.s3_transaction_bound(ctx, reentry))
                for png in f.plates.glob("*.png"):
                    png.unlink()
                self.assertFalse(npl.s3_transaction_bound(ctx, reentry))

    def test_stale_submit_report_is_ignored(self):
        import nalu_pipeline as npl
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "r.json"
            report.write_text(json.dumps({"status": "PASS", "results": [{"status": "SUBMITTED"}]}), encoding="utf-8")
            old = time.time() - 600
            os.utime(report, (old, old))
            self.assertEqual(npl.s3_fresh_submit_report(report, time.time() - 5), {})
            self.assertEqual(npl.s3_fresh_submit_report(report, old - 5)["status"], "PASS")

    def test_failed_submit_child_is_not_passed_on_old_report(self):
        src = (ROOT / "lines/nalu/runtime/tools/nalu_pipeline.py").read_text(encoding="utf-8")
        self.assertIn("s3_fresh_submit_report(p.identity_submit, submit_started)", src)
        self.assertIn('submit.get("exit_code") == 2', src)
        self.assertIn('"--plates-dir", p.identity_harvest_dir,\n            ]', src)


if __name__ == "__main__":
    unittest.main()
