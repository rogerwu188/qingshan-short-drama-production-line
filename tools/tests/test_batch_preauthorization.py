import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))
import batch_preauthorization as bp  # noqa: E402

POLICY = {"batch_preauthorization": {"max_credits_per_batch": 1000, "max_units_per_batch": 10,
                                     "escalate_on": {"reroll": True, "unit_cost_over_p95": True},
                                     "unit_cost_p95_credits": 104}}


def tasks(n, credits=62):
    return [{"task_key": f"E99-VU-{i:03d}", "estimated_credits": credits} for i in range(1, n + 1)]


class BatchPreauthorizationTest(unittest.TestCase):
    def test_not_configured_changes_nothing(self):
        v = bp.evaluate({"kind": "PAID_PRODUCTION_AUTHORIZATION"}, tasks(3), planned_credits=186, tx_dir=None)
        self.assertEqual(v["status"], bp.NOT_CONFIGURED)

    def test_allow_inside_limits(self):
        v = bp.evaluate(POLICY, tasks(5), planned_credits=310, tx_dir=None)
        self.assertEqual(v["status"], bp.ALLOW, v)

    def test_escalates_over_credits_and_units(self):
        v = bp.evaluate(POLICY, tasks(12), planned_credits=1200, tx_dir=None)
        self.assertEqual(v["status"], bp.ESCALATE)
        self.assertTrue(any(r.startswith("BATCH_CREDITS_OVER_LIMIT:1200>1000") for r in v["reasons"]))
        self.assertTrue(any(r.startswith("BATCH_UNITS_OVER_LIMIT:12>10") for r in v["reasons"]))

    def test_escalates_reroll_and_p95(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "E99-VU-001__abc.json").write_text(json.dumps(
                {"task_key": "E99-VU-001", "state": "SUBMITTED_TASK_ID_BOUND", "estimated_credits": 62}), encoding="utf-8")
            rows = tasks(2) + [{"task_key": "E99-VU-009", "estimated_credits": 118}]
            v = bp.evaluate(POLICY, rows, planned_credits=242, tx_dir=Path(tmp))
            self.assertEqual(v["status"], bp.ESCALATE)
            self.assertTrue(any(r.startswith("REROLL:E99-VU-001") for r in v["reasons"]))
            self.assertTrue(any(r.startswith("UNIT_COST_OVER_P95:E99-VU-009:118>104") for r in v["reasons"]))

    def test_measured_p95_from_store_when_order_has_none(self):
        policy = json.loads(json.dumps(POLICY)); del policy["batch_preauthorization"]["unit_cost_p95_credits"]
        with tempfile.TemporaryDirectory() as tmp:
            for i, c in enumerate([62, 62, 76, 76, 90, 90, 104, 104, 104, 118]):
                Path(tmp, f"E99-VU-{i:03d}__x.json").write_text(json.dumps(
                    {"task_key": f"E99-VU-{i:03d}", "state": "SUBMITTED_TASK_ID_BOUND", "estimated_credits": c}), encoding="utf-8")
            v = bp.evaluate(policy, [{"task_key": "E99-VU-900", "estimated_credits": 110}], planned_credits=110, tx_dir=Path(tmp))
            self.assertEqual(v["policy"]["p95_source"], "MEASURED_BOUND_TASKS")
            self.assertEqual(v["policy"]["unit_cost_p95_credits"], 118.0)
            self.assertEqual(v["status"], bp.ALLOW)

    def test_reroll_escalation_can_be_switched_off_only_explicitly(self):
        policy = json.loads(json.dumps(POLICY)); policy["batch_preauthorization"]["escalate_on"]["reroll"] = False
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "E99-VU-001__abc.json").write_text(json.dumps(
                {"task_key": "E99-VU-001", "state": "SUBMITTED_TASK_ID_BOUND", "estimated_credits": 62}), encoding="utf-8")
            v = bp.evaluate(policy, tasks(1), planned_credits=62, tx_dir=Path(tmp))
            self.assertEqual(v["status"], bp.ALLOW)


if __name__ == "__main__":
    unittest.main()
