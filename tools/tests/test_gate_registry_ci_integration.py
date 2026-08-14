import tempfile
import unittest
from pathlib import Path

from tools.run_regression_ci import DEFAULT_GATE_REGISTRY, gate_registry_integrity_stats


class GateRegistryCIIntegrationTests(unittest.TestCase):
    def test_ci_rejects_missing_registry(self):
        with tempfile.TemporaryDirectory() as temp:
            report = gate_registry_integrity_stats(Path(temp) / "missing.json")
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("gate_registry_missing", report["failures"])

    def test_ci_accepts_current_registry(self):
        report = gate_registry_integrity_stats(DEFAULT_GATE_REGISTRY)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["failures"], [])


if __name__ == "__main__":
    unittest.main()
