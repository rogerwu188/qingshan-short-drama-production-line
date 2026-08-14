import json
import tempfile
import unittest
from pathlib import Path

from tools.gate_result_contract import write_gate_result


class GateResultContractTests(unittest.TestCase):
    def test_true_invocation_writes_matrix_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            out = write_gate_result(
                "E32", "G1", invoked=True, status="PASS", runner="runner.py",
                evidence="qa/evidence.json", root=Path(temp),
            )
            payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertTrue(payload["invoked"])
        self.assertEqual(payload["status"], "PASS")

    def test_false_invocation_cannot_be_backfilled(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "invoked=false"):
                write_gate_result(
                    "E32", "G1", invoked=False, status="PASS", runner="runner.py",
                    evidence="none", root=Path(temp),
                )


if __name__ == "__main__":
    unittest.main()
