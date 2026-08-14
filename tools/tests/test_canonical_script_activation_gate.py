import hashlib
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.canonical_script_activation_gate import (
    REQUIRED_CHECKS,
    SUPERVISION_SCHEMA,
    verify_canonical_script_activation,
)


class CanonicalScriptActivationGateTest(unittest.TestCase):
    def _fixture(self, root: Path):
        baseline = root / "v1.md"
        revised = root / "v2.md"
        changes = root / "changes.md"
        report = root / "review.json"
        baseline.write_text("baseline\n", encoding="utf-8")
        revised.write_text("revised\n", encoding="utf-8")
        changes.write_text("dialogue shortened\n", encoding="utf-8")
        revised_sha = hashlib.sha256(revised.read_bytes()).hexdigest()
        report.write_text(json.dumps({
            "schema": SUPERVISION_SCHEMA,
            "episode": "E32",
            "reviewer_role": "LOCAL_CLAUDE_SUPERVISOR",
            "status": "PASS",
            "canonical_activation_allowed": True,
            "script_sha256": revised_sha,
            "required_checks": {name: True for name in REQUIRED_CHECKS},
        }), encoding="utf-8")
        return baseline, revised, changes, report, revised_sha

    def test_exact_sha_local_supervision_passes(self):
        with TemporaryDirectory() as tmp:
            args = self._fixture(Path(tmp))
            result = verify_canonical_script_activation("E32", *args[:4], args[4])
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["canonical_activation_allowed"])

    def test_missing_revision_blocks(self):
        with TemporaryDirectory() as tmp:
            baseline, _revised, changes, report, _sha = self._fixture(Path(tmp))
            result = verify_canonical_script_activation("E32", baseline, Path(tmp) / "missing.md", changes, report)
        self.assertEqual(result["status"], "BLOCKED_CANONICAL_SCRIPT_ACTIVATION")

    def test_supervision_sha_mismatch_blocks(self):
        with TemporaryDirectory() as tmp:
            baseline, revised, changes, report, revised_sha = self._fixture(Path(tmp))
            payload = json.loads(report.read_text(encoding="utf-8"))
            payload["script_sha256"] = "0" * 64
            report.write_text(json.dumps(payload), encoding="utf-8")
            result = verify_canonical_script_activation("E32", baseline, revised, changes, report, revised_sha)
        self.assertTrue(any(row["check"] == "supervision_script_sha256" for row in result["failures"]))

    def test_missing_required_check_blocks(self):
        with TemporaryDirectory() as tmp:
            baseline, revised, changes, report, revised_sha = self._fixture(Path(tmp))
            payload = json.loads(report.read_text(encoding="utf-8"))
            payload["required_checks"]["shot_treatment"] = False
            report.write_text(json.dumps(payload), encoding="utf-8")
            result = verify_canonical_script_activation("E32", baseline, revised, changes, report, revised_sha)
        self.assertTrue(any(row["check"] == "required_check_shot_treatment" for row in result["failures"]))


if __name__ == "__main__":
    unittest.main()
