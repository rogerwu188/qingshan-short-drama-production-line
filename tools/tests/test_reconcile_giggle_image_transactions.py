"""Regression for tools/reconcile_giggle_image_transactions.py (K106).

nalu E12 2026-10-18: a keyframe batch of 10 lost every provider response (upstream
``dial tcp ... i/o timeout``), the credit window showed 10 Pay rows and 0 bound task ids,
and the submitter quarantined all 10 as CHARGE_STATE_UNRESOLVED_BATCH — correctly.  The
offline reconciler then matched the embedded (known=0, pay_rows=10, unmapped=10) tuple
against the archived statement, treated "same batch" as "closed batch", and rewrote all 10
to NOT_CHARGED_RETRYABLE with unmapped=0.  The next two paid runs re-POSTed the same 8
prompts (88 + 77 credits) into the same outage.  A Pay row that no task id explains is a
bought image, never a free retry.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "reconcile_giggle_image_transactions.py"


def _statement(*, known: int, matched: int, unmapped: int, expected: int, ambiguous: int,
               charged: int) -> dict:
    rows = [
        {"event_description": "SingleGenerateImage", "event_type": "Pay", "credit": "-11",
         "created_at": f"2026-10-18 07:5{i}:00", "model": "gpt-image-2-fast"}
        for i in range(matched)
    ]
    return {
        "status": "PASS_BOUNDED",
        "window_start_utc": "2026-10-18T07:53:00Z",
        "window_end_utc": "2026-10-18T07:58:00Z",
        "expected_count": expected,
        "matched_count": matched,
        "charged_credits": charged,
        "statement_rows": rows,
        "known_task_id_count": known,
        "ambiguous_response_count": ambiguous,
        "unmapped_pay_row_count": unmapped,
    }


def _transaction(task_key: str, *, known: int, pay_rows: int, unmapped: int) -> dict:
    return {
        "schema": "qingshan.giggle_submit_transaction.v1",
        "task_key": task_key,
        "state": "CHARGE_STATE_UNRESOLVED_BATCH",
        "model": "gpt-image-2-fast",
        "intent_recorded_at": "2026-10-18T07:53:14Z",
        "response_lost_at": "2026-10-18T07:54:26Z",
        "error": "Submit response missing data.task_id",
        "provider_response": {"code": 500, "msg": "img2img failed: ... i/o timeout", "data": None},
        "batch_known_task_ids": known,
        "batch_ledger_pay_rows": pay_rows,
        "batch_unmapped_pay_rows": unmapped,
        "retry_guard": "DO_NOT_RESUBMIT_RECOVER_TASK_ID_FROM_PROVIDER_HISTORY",
    }


def _run(root: Path, *, apply: bool) -> dict:
    out = root / "report.json"
    argv = [sys.executable, "-I", str(TOOL), "--episode", "E99",
            "--transactions", str(root / "tx"), "--reports-root", str(root / "reports"),
            "--out", str(out)]
    if apply:
        argv.append("--apply")
    proc = subprocess.run(argv, capture_output=True, text=True, cwd=str(root), check=True)
    if apply:
        return json.loads(out.read_text(encoding="utf-8"))
    return json.loads(proc.stdout)


class ReconcileEmbeddedBatchTests(unittest.TestCase):
    def _layout(self, root: Path, *, n: int, known: int, matched: int, unmapped: int,
                charged: int) -> list[Path]:
        (root / "tx").mkdir()
        (root / "reports").mkdir()
        (root / "reports" / "E99_KEYFRAME_SUBMIT_REPORT_credit_statement.json").write_text(
            json.dumps(_statement(known=known, matched=matched, unmapped=unmapped,
                                  expected=known + n, ambiguous=n, charged=charged)),
            encoding="utf-8")
        paths = []
        for i in range(n):
            p = root / "tx" / f"E99-S{i:02d}-01-KEYFRAME-V1__{i:016x}.json"
            p.write_text(json.dumps(_transaction(f"E99-S{i:02d}-01-KEYFRAME-V1", known=known,
                                                 pay_rows=matched, unmapped=unmapped)),
                         encoding="utf-8")
            paths.append(p)
        return paths

    def test_unmapped_pay_rows_stay_quarantined(self) -> None:
        """E12 shape: 10 lost responses, 10 Pay rows, 0 bound ids → nothing is retryable."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            paths = self._layout(root, n=10, known=0, matched=10, unmapped=10, charged=110)
            report = _run(root, apply=True)
            self.assertEqual(report["eligible_count"], 0)
            self.assertEqual(report["skipped_count"], 10)
            self.assertTrue(all(s["reason"] == "EMBEDDED_BATCH_HAS_UNMAPPED_PAY_ROWS"
                                for s in report["skipped"]))
            for p in paths:
                tx = json.loads(p.read_text(encoding="utf-8"))
                self.assertEqual(tx["state"], "CHARGE_STATE_UNRESOLVED_BATCH")
                self.assertEqual(tx["batch_unmapped_pay_rows"], 10)
                self.assertEqual(tx["retry_guard"],
                                 "DO_NOT_RESUBMIT_RECOVER_TASK_ID_FROM_PROVIDER_HISTORY")

    def test_closed_zero_charge_batch_is_retryable(self) -> None:
        """Provider declined, window empty: (known=0, pay_rows=0, unmapped=0) may retry."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            paths = self._layout(root, n=3, known=0, matched=0, unmapped=0, charged=0)
            report = _run(root, apply=True)
            self.assertEqual(report["eligible_count"], 3)
            for p in paths:
                tx = json.loads(p.read_text(encoding="utf-8"))
                self.assertEqual(tx["state"], "NOT_CHARGED_RETRYABLE")
                self.assertEqual(tx["batch_unmapped_pay_rows"], 0)
                self.assertEqual(tx["retry_guard"], "RETRY_ALLOWED_NEW_ATTEMPT")

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            paths = self._layout(root, n=2, known=0, matched=2, unmapped=2, charged=22)
            report = _run(root, apply=False)
            self.assertEqual(report["mode"], "DRY_RUN")
            self.assertEqual(report["eligible_count"], 0)
            for p in paths:
                self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["state"],
                                 "CHARGE_STATE_UNRESOLVED_BATCH")


if __name__ == "__main__":
    unittest.main()
