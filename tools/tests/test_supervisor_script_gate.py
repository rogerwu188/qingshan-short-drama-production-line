import hashlib
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.supervisor_script_gate import PREGATE_SCHEMA, SCHEMA, verify_supervisor_script_gate


class SupervisorScriptGateTest(unittest.TestCase):
    def _fixture(self, root: Path):
        generated = root / "generated.json"
        compiled = root / "compiled.json"
        generated.write_text(json.dumps({
            "episode": 28,
            "locked_script": {
                "scenes": [{"shots": [{"id": "E28-N01"}, {"id": "E28-N02"}]}],
            },
        }), encoding="utf-8")
        compiled.write_text(json.dumps({"episode": 28}), encoding="utf-8")
        report = root / "review.json"
        report.write_text(json.dumps({
            "schema": SCHEMA,
            "episode": "E28",
            "reviewer_role": "LOCAL_CLAUDE_SUPERVISOR",
            "status": "PASS",
            "generation_allowed": True,
            "script_bindings": {
                "generated_script_sha256": hashlib.sha256(generated.read_bytes()).hexdigest(),
                "compiled_script_sha256": hashlib.sha256(compiled.read_bytes()).hexdigest(),
            },
            "shot_reviews": [
                {"shot_id": shot_id, "status": "PASS", "source_basis": "PASS", "script_alignment": "PASS", "treatment_alignment": "PASS"}
                for shot_id in ("E28-N01", "E28-N02")
            ],
        }), encoding="utf-8")
        return generated, compiled, report

    def test_exact_sha_complete_per_shot_pass_allows_generation(self):
        with TemporaryDirectory() as tmp:
            generated, compiled, report = self._fixture(Path(tmp))
            result = verify_supervisor_script_gate("E28", generated, compiled, report)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["generation_allowed"])
        self.assertEqual(result["reviewed_shot_count"], 2)

    def test_missing_review_blocks_generation(self):
        with TemporaryDirectory() as tmp:
            generated, compiled, _report = self._fixture(Path(tmp))
            result = verify_supervisor_script_gate("E28", generated, compiled, Path(tmp) / "missing.json")
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["generation_allowed"])

    def test_sha_mismatch_blocks_generation(self):
        with TemporaryDirectory() as tmp:
            generated, compiled, report = self._fixture(Path(tmp))
            compiled.write_text(json.dumps({"episode": 28, "changed": True}), encoding="utf-8")
            result = verify_supervisor_script_gate("E28", generated, compiled, report)
        self.assertTrue(any(row["check"] == "compiled_script_sha256_binding" for row in result["failures"]))

    def test_missing_one_shot_review_blocks_generation(self):
        with TemporaryDirectory() as tmp:
            generated, compiled, report = self._fixture(Path(tmp))
            payload = json.loads(report.read_text(encoding="utf-8"))
            payload["shot_reviews"].pop()
            report.write_text(json.dumps(payload), encoding="utf-8")
            result = verify_supervisor_script_gate("E28", generated, compiled, report)
        self.assertTrue(any(row["check"] == "shot_review_coverage" for row in result["failures"]))

    def test_pass_with_reason_is_accepted(self):
        with TemporaryDirectory() as tmp:
            generated, compiled, report = self._fixture(Path(tmp))
            payload = json.loads(report.read_text(encoding="utf-8"))
            payload["shot_reviews"][0]["source_basis"] = "PASS — exact source fact and reason"
            report.write_text(json.dumps(payload), encoding="utf-8")
            result = verify_supervisor_script_gate("E28", generated, compiled, report)
        self.assertEqual(result["status"], "PASS")

    def test_conditional_pass_is_rejected(self):
        with TemporaryDirectory() as tmp:
            generated, compiled, report = self._fixture(Path(tmp))
            payload = json.loads(report.read_text(encoding="utf-8"))
            payload["shot_reviews"][0]["source_basis"] = "PASS_CONDITIONAL"
            report.write_text(json.dumps(payload), encoding="utf-8")
            result = verify_supervisor_script_gate("E28", generated, compiled, report)
        self.assertEqual(result["status"], "FAIL")

    def test_sha_bound_cl2x499_pregate_pass_is_accepted(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated = root / "directing.md"
            compiled = root / "contract.json"
            generated.write_text("# E41 directing\n", encoding="utf-8")
            compiled.write_text(json.dumps({"episode": "E41", "units": [1, 2]}), encoding="utf-8")
            report = root / "pregate.json"
            report.write_text(json.dumps({
                "schema": PREGATE_SCHEMA,
                "gate_ref": "CL2X-499",
                "episode": "E41",
                "verdict": "PASS",
                "ruled_by": "Claude 本地监制/制片",
                "registered_gates": {"count": 9, "pass": 9, "fail": 0, "failures_total": 0},
                "sha_recompute": {
                    "directing_script": {"path": str(generated), "sha256": hashlib.sha256(generated.read_bytes()).hexdigest()},
                    "generation_contract": {"path": str(compiled), "sha256": hashlib.sha256(compiled.read_bytes()).hexdigest()},
                },
                "structure_cross_check": {
                    "path_a_manifest": {"shots": 110},
                    "path_b_contract_recompute": {"units": 110},
                    "consistent": True,
                },
            }), encoding="utf-8")
            result = verify_supervisor_script_gate("E41", generated, compiled, report)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["generation_allowed"])
        self.assertEqual(result["reviewed_shot_count"], 110)

    def test_pregate_sha_mismatch_blocks_generation(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated = root / "directing.md"
            compiled = root / "contract.json"
            generated.write_text("# E41 directing\n", encoding="utf-8")
            compiled.write_text(json.dumps({"episode": "E41"}), encoding="utf-8")
            report = root / "pregate.json"
            report.write_text(json.dumps({
                "schema": PREGATE_SCHEMA,
                "gate_ref": "CL2X-499",
                "episode": "E41",
                "verdict": "PASS",
                "ruled_by": "Claude 本地监制/制片",
                "registered_gates": {"count": 9, "pass": 9, "fail": 0, "failures_total": 0},
                "sha_recompute": {
                    "directing_script": {"path": str(generated), "sha256": "bad"},
                    "generation_contract": {"path": str(compiled), "sha256": hashlib.sha256(compiled.read_bytes()).hexdigest()},
                },
                "structure_cross_check": {
                    "path_a_manifest": {"shots": 110},
                    "path_b_contract_recompute": {"units": 110},
                    "consistent": True,
                },
            }), encoding="utf-8")
            result = verify_supervisor_script_gate("E41", generated, compiled, report)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any(row["check"] == "generated_script_sha256_binding" for row in result["failures"]))


if __name__ == "__main__":
    unittest.main()
