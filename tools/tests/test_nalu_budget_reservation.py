"""K111 reservation path: a paid stage that reserves credits must, at minimum, run.

E12 2026-10-20: the first real paid run that reached the reservation branch died with
``NameError: name 'uuid' is not defined`` — the ``--check --reserve`` path had never been
executed by a test, so a missing stdlib import stayed invisible until money was on the line.
These tests exercise the branch itself on a scratch ledger.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "lines" / "nalu" / "runtime" / "tools" / "nalu_budget_ledger.py"
EPISODE = "E99"
RESERVATIONS = ROOT / "workflow" / "nalu" / EPISODE / "BUDGET_RESERVATION.jsonl"


def _ledger(path: Path, cap: int = 8000) -> None:
    path.write_text(json.dumps({
        "schema": "qingshan.credit_ledger.v1", "cap_credits_per_episode": cap,
        "authority": {}, "money_rules": {}, "entries": [],
        "latest_balance_snapshot": None, "updated_at_utc": "2026-10-20T00:00:00Z",
    }), encoding="utf-8")


class ReservationPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(shutil.rmtree, RESERVATIONS.parent, True)

    def _run(self, *extra: str, cap: int = 8000, planned: str = "66") -> subprocess.CompletedProcess:
        tmp = Path(self.tmp.name)
        ledger = tmp / "ledger.json"
        if not ledger.is_file():
            _ledger(ledger, cap=cap)
        return subprocess.run(
            [sys.executable, "-I", str(TOOL), "--check", "--episode", EPISODE,
             "--planned-credits", planned, "--cap", str(cap), "--ledger", str(ledger),
             "--out", str(tmp / "report.json"), *extra],
            capture_output=True, text=True, cwd=str(ROOT))

    def _report(self) -> dict:
        return json.loads((Path(self.tmp.name) / "report.json").read_text(encoding="utf-8"))

    def test_reserve_returns_a_reservation_id_and_appends_a_row(self) -> None:
        proc = self._run("--reserve")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = self._report()
        self.assertEqual(report["status"], "PASS")
        reservation = report.get("reservation_result") or {}
        self.assertTrue(reservation.get("reserved"), report)
        rid = reservation.get("reservation_id")
        self.assertTrue(rid, "a PASS with --reserve must print the reservation id")
        rows = [json.loads(line) for line in RESERVATIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(rows[-1]["reservation_id"], rid)
        self.assertEqual(rows[-1]["credits"], 66)

    def test_release_clears_the_reservation(self) -> None:
        self.assertEqual(self._run("--reserve").returncode, 0)
        rid = (self._report().get("reservation_result") or {})["reservation_id"]
        proc = self._run("--release-reservation", rid)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["status"], "RELEASED")

    def test_reservation_over_cap_is_refused(self) -> None:
        proc = self._run("--reserve", cap=50)
        self.assertNotEqual(proc.returncode, 0)
        report = self._report()
        self.assertEqual(report["status"], "BLOCKED")
        self.assertTrue(any("RESERVATION_FAILED" in failure or "CAP" in failure
                            for failure in report.get("failures") or []), report.get("failures"))


if __name__ == "__main__":
    unittest.main()
