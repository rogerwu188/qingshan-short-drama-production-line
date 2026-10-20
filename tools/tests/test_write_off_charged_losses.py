"""K073 write-off: charged images whose task ids were lost are settled, never resent.

E12 2026-10-18: the 09:38 batch lost all eight provider responses to an upstream
``dial tcp ... i/o timeout``.  The credit statement proves seven Pay rows (77 credits)
with no task id to explain them, so the images were bought and unreachable; the two
earlier quarantined transactions have no surviving statement window at all.  K073
(standing line-owner instruction) settles such rows as CHARGED_WRITTEN_OFF_BY_ORDER:
the spend stays in the ledger because the statement file is what counts it, and the
same fingerprint is never resubmitted.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "write_off_charged_losses.py"

STATEMENT = {
    "status": "PASS_BOUNDED",
    "window_start_utc": "2026-10-18T09:38:14.330814Z",
    "window_end_utc": "2026-10-18T09:41:49.284208Z",
    "expected_count": 8,
    "matched_count": 7,
    "charged_credits": 77,
    "unmatched": 0,
    "unmapped_pay_row_count": 7,
    "known_task_id_count": 0,
}

AUTHORITY = {
    "kind": "LINE_OWNER_INSTRUCTION_IN_SESSION",
    "order_id": "ROGER-TEST-WRITE-OFF",
    "issued_by": "Roger",
    "verbatim": "按 K073 核销",
    "recorded_at_utc": "2026-10-20T18:10:00Z",
}


def _tx(key: str, *, state: str = "CHARGE_STATE_UNRESOLVED_BATCH",
        intent: str = "2026-10-18T09:38:25Z") -> dict:
    return {
        "schema": "qingshan.giggle_submit_transaction.v1",
        "task_key": key,
        "state": state,
        "model": "gpt-image-2-pro",
        "intent_recorded_at": intent,
        "provider_response": {"code": 500, "msg": "i/o timeout", "data": None},
        "retry_guard": "DO_NOT_RESUBMIT_RECOVER_TASK_ID_FROM_PROVIDER_HISTORY",
    }


class WriteOffToolTests(unittest.TestCase):
    def _layout(self, root: Path, *, keys=("E99-S01-01-KEYFRAME-V1",),
                states=None, statement=STATEMENT, evidence_rows=None) -> dict:
        (root / "tx").mkdir()
        (root / "reports").mkdir()
        stmt = root / "reports" / "E99_KEYFRAME_SUBMIT_REPORT_credit_statement.json"
        stmt.write_text(json.dumps(statement), encoding="utf-8")
        states = states or {}
        for key in keys:
            (root / "tx" / f"{key}__deadbeef.json").write_text(
                json.dumps(_tx(key, state=states.get(key, "CHARGE_STATE_UNRESOLVED_BATCH"))),
                encoding="utf-8")
        rows = evidence_rows if evidence_rows is not None else [
            {"task_key": key, "charge_evidence": {"statement": str(stmt)}} for key in keys]
        for row in rows:
            ev = row.get("charge_evidence")
            if ev and not ev.get("sha256"):
                import hashlib
                ev["sha256"] = hashlib.sha256(stmt.read_bytes()).hexdigest()
        (root / "evidence.json").write_text(json.dumps(
            {"authority": AUTHORITY, "transactions": rows}), encoding="utf-8")
        return {"stmt": stmt, "evidence": root / "evidence.json"}

    def _run(self, root: Path, paths: dict, *, apply: bool) -> dict:
        out = root / "report.json"
        argv = [sys.executable, "-I", str(TOOL), "--episode", "E99",
                "--transactions", str(root / "tx"), "--evidence", str(paths["evidence"]),
                "--out", str(out)]
        if apply:
            argv.append("--apply")
        proc = subprocess.run(argv, capture_output=True, text=True, cwd=str(ROOT))
        if apply:
            return json.loads(out.read_text(encoding="utf-8"))
        return json.loads(proc.stdout)

    def test_charged_rows_are_written_off_with_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            paths = self._layout(root)
            report = self._run(root, paths, apply=True)
            self.assertEqual(report["eligible_count"], 1)
            tx = json.loads((root / "tx" / "E99-S01-01-KEYFRAME-V1__deadbeef.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(tx["state"], "CHARGED_WRITTEN_OFF_BY_ORDER")
        self.assertEqual(tx["previous_state"], "CHARGE_STATE_UNRESOLVED_BATCH")
        self.assertIsNone(tx["written_off_credits"])
        self.assertEqual(tx["charge_evidence"]["charged_credits"], 77)
        self.assertEqual(tx["charge_evidence"]["unmapped_pay_rows"], 7)
        self.assertEqual(tx["retry_guard"], "DO_NOT_RESUBMIT_THIS_FINGERPRINT")

    def test_statement_sha_mismatch_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            paths = self._layout(root, evidence_rows=[
                {"task_key": "E99-S01-01-KEYFRAME-V1",
                 "charge_evidence": {"statement": "PLACEHOLDER", "sha256": "0" * 64}}])
            # point at the real statement file so the SHA comparison is what refuses it
            rows = json.loads(paths["evidence"].read_text(encoding="utf-8"))
            rows["transactions"][0]["charge_evidence"]["statement"] = str(paths["stmt"])
            paths["evidence"].write_text(json.dumps(rows), encoding="utf-8")
            report = self._run(root, paths, apply=True)
            tx = json.loads((root / "tx" / "E99-S01-01-KEYFRAME-V1__deadbeef.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(report["eligible_count"], 0)
        self.assertEqual(report["refused"][0]["reason"], "STATEMENT_SHA_MISMATCH")
        self.assertEqual(tx["state"], "CHARGE_STATE_UNRESOLVED_BATCH")

    def test_a_settled_transaction_is_never_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            paths = self._layout(root, states={"E99-S01-01-KEYFRAME-V1": "SUBMITTED_TASK_ID_BOUND"})
            report = self._run(root, paths, apply=True)
        self.assertEqual(report["eligible_count"], 0)
        self.assertTrue(report["refused"][0]["reason"].startswith("NOT_UNRESOLVED"))

    def test_no_evidence_requires_an_explicit_reason(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            paths = self._layout(root, evidence_rows=[{"task_key": "E99-S01-01-KEYFRAME-V1"}])
            report = self._run(root, paths, apply=True)
            tx = json.loads((root / "tx" / "E99-S01-01-KEYFRAME-V1__deadbeef.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(report["refused"][0]["reason"], "NO_EVIDENCE_AND_NO_REASON")
        self.assertEqual(tx["state"], "CHARGE_STATE_UNRESOLVED_BATCH")

    def test_a_reasoned_row_without_a_window_settles_at_zero_credits(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            paths = self._layout(root, evidence_rows=[
                {"task_key": "E99-S01-01-KEYFRAME-V1",
                 "reason": "no surviving statement window"}])
            report = self._run(root, paths, apply=True)
            tx = json.loads((root / "tx" / "E99-S01-01-KEYFRAME-V1__deadbeef.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(report["eligible_count"], 1)
        self.assertEqual(tx["written_off_credits"], 0)
        self.assertIsNone(tx["charge_evidence"])
        self.assertEqual(tx["written_off_without_charge_evidence"],
                         "no surviving statement window")

    def test_window_mismatch_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "tx").mkdir()
            (root / "reports").mkdir()
            stmt = root / "reports" / "E99_statement.json"
            stmt.write_text(json.dumps(STATEMENT), encoding="utf-8")
            (root / "tx" / "E99-S01-01-KEYFRAME-V1__deadbeef.json").write_text(
                json.dumps(_tx("E99-S01-01-KEYFRAME-V1", intent="2026-10-18T07:53:13Z")),
                encoding="utf-8")
            import hashlib
            (root / "evidence.json").write_text(json.dumps({
                "authority": AUTHORITY,
                "transactions": [{"task_key": "E99-S01-01-KEYFRAME-V1",
                                  "charge_evidence": {"statement": str(stmt),
                                                      "sha256": hashlib.sha256(
                                                          stmt.read_bytes()).hexdigest()}}]}),
                encoding="utf-8")
            report = self._run(root, {"evidence": root / "evidence.json"}, apply=True)
        self.assertEqual(report["refused"][0]["reason"],
                         "TRANSACTION_OUTSIDE_STATEMENT_WINDOW")

    def test_dry_run_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            paths = self._layout(root)
            report = self._run(root, paths, apply=False)
            tx = json.loads((root / "tx" / "E99-S01-01-KEYFRAME-V1__deadbeef.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(report["mode"], "DRY_RUN")
        self.assertEqual(report["eligible_count"], 1)
        self.assertEqual(tx["state"], "CHARGE_STATE_UNRESOLVED_BATCH")
        self.assertEqual(report["posts"], 0)
        self.assertEqual(report["network_calls"], 0)


if __name__ == "__main__":
    unittest.main()
