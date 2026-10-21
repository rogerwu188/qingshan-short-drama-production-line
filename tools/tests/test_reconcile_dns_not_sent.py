"""A response-lost row whose error proves DNS never resolved is settled as NOT_CHARGED_RETRYABLE."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/reconcile_giggle_image_transactions.py"


class ReconcileDnsNotSentTests(unittest.TestCase):
    def run_tool(self, tx_dir: Path, out: Path, *extra: str) -> subprocess.CompletedProcess:
        reports = tx_dir.parent / "reports"
        reports.mkdir(exist_ok=True)
        return subprocess.run([sys.executable, str(TOOL), "--episode", "E01", "--transactions", str(tx_dir),
                               "--reports-root", str(reports), "--out", str(out), *extra],
                              capture_output=True, text=True, check=True)

    def test_dns_rows_are_settled_and_real_losses_stay_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            tx = Path(tmp) / "tx"
            tx.mkdir()
            dns = {"task_key": "CHAR-A", "state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION",
                   "error": "NETWORK: <urlopen error [Errno -3] Temporary failure in name resolution>",
                   "response_lost_at": "2026-10-21T05:43:51Z"}
            lost = {"task_key": "CHAR-B", "state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION",
                    "error": "NETWORK: The read operation timed out", "response_lost_at": "2026-10-21T05:43:52Z"}
            (tx / "CHAR-A__x.json").write_text(json.dumps(dns), encoding="utf-8")
            (tx / "CHAR-B__y.json").write_text(json.dumps(lost), encoding="utf-8")
            out = Path(tmp) / "report.json"
            dry = json.loads(self.run_tool(tx, out).stdout)
            self.assertEqual([e["task_key"] for e in dry["eligible"]], ["CHAR-A"])
            self.assertFalse(out.exists())  # dry run writes nothing
            self.run_tool(tx, out, "--apply")
            a = json.loads((tx / "CHAR-A__x.json").read_text(encoding="utf-8"))
            b = json.loads((tx / "CHAR-B__y.json").read_text(encoding="utf-8"))
            self.assertEqual(a["state"], "NOT_CHARGED_RETRYABLE")
            self.assertEqual(a["reconciliation_evidence"]["method"], "DNS_RESOLUTION_FAILED_BEFORE_CONNECT")
            self.assertEqual(b["state"], "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION")


if __name__ == "__main__":
    unittest.main()
