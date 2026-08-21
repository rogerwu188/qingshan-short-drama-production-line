import json
import tempfile
import unittest
from pathlib import Path

from tools.authorize_image_manifest_submission import authorize


class AuthorizeImageManifestSubmissionTest(unittest.TestCase):
    def test_promotes_exactly_budgeted_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            output = root / "authorized.json"
            gate = root / "gate.json"
            source.write_text(json.dumps({
                "machine_gate_reports": [],
                "tasks": [
                    {"task_key": f"T{index}", "status": "READY_FOR_PRECHECK_NO_PROVIDER_POST"}
                    for index in range(7)
                ],
            }), encoding="utf-8")
            manifest, report = authorize(
                source, output, gate,
                authorization_ref="ROGER",
                total_paid_tasks=137,
                observed_paid_rerolls=13,
                fraction=0.15,
            )
            self.assertEqual(report["projected_paid_rerolls"], 20)
            self.assertEqual(report["maximum_paid_rerolls"], 20)
            self.assertTrue(all(task["provider_post_allowed"] for task in manifest["tasks"]))

    def test_rejects_over_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            source.write_text(json.dumps({
                "tasks": [
                    {"task_key": f"T{index}", "status": "READY_FOR_PRECHECK_NO_PROVIDER_POST"}
                    for index in range(8)
                ],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "budget exceeded"):
                authorize(
                    source, root / "authorized.json", root / "gate.json",
                    authorization_ref="ROGER",
                    total_paid_tasks=137,
                    observed_paid_rerolls=13,
                    fraction=0.15,
                )


if __name__ == "__main__":
    unittest.main()
