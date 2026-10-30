"""record_paid_production_order.py --batch-preauthorization-json writes decision.batch_preauthorization
(提速闭环 3a, Roger 2026-10-30 「自动预授权，不设上限」) and refuses malformed blocks."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "lines/nalu/runtime/tools/record_paid_production_order.py"


def run(tmp: str, extra: list[str]) -> tuple[int, dict]:
    orders = Path(tmp) / "SUPERVISOR_ORDERS.json"
    env = {**os.environ, "NALU_LINE_OWNER_ID": "Roger", "NALU_RUNTIME_ROOT": tmp}
    r = subprocess.run([sys.executable, str(TOOL), "--orders", str(orders), "--owner-id", "Roger",
                        "--order", "自动预授权，不设上限", "--episode", "E99", "--cap", "8000",
                        "--rights-basis", "test", "--video-model", "MiniMax-H3", *extra],
                       capture_output=True, text=True, env=env)
    try:
        out = json.loads(r.stdout) if r.stdout.strip() else {}
    except json.JSONDecodeError:
        out = {"raw": r.stdout[-400:], "stderr": r.stderr[-400:]}
    return r.returncode, out


class RecordPaidOrderPreauthTest(unittest.TestCase):
    def test_block_written_with_null_limits(self):
        block = {"max_credits_per_batch": None, "max_units_per_batch": None,
                 "escalate_on": {"reroll": True, "unit_cost_over_p95": True}}
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = run(tmp, ["--batch-preauthorization-json", json.dumps(block)])
            self.assertEqual(rc, 0, out)
            rows = json.loads(Path(tmp, "SUPERVISOR_ORDERS.json").read_text(encoding="utf-8"))["orders"]
            dec = rows[-1]["decision"]
            self.assertEqual(dec["batch_preauthorization"], block)
            self.assertEqual(dec["budget_cap_credits_per_episode"], 8000)
            self.assertTrue(any(c["id"] == "BATCH_PREAUTHORIZATION" for c in rows[-1]["conditions"]))

    def test_without_option_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = run(tmp, [])
            self.assertEqual(rc, 0, out)
            rows = json.loads(Path(tmp, "SUPERVISOR_ORDERS.json").read_text(encoding="utf-8"))["orders"]
            self.assertNotIn("batch_preauthorization", rows[-1]["decision"])

    def test_malformed_block_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = run(tmp, ["--batch-preauthorization-json", json.dumps({"escalate_on": {}})])
            self.assertEqual(rc, 2)
            self.assertIn("BATCH_PREAUTHORIZATION_KEYS_MISSING", out.get("error", ""))
            self.assertFalse(Path(tmp, "SUPERVISOR_ORDERS.json").exists())


if __name__ == "__main__":
    unittest.main()
