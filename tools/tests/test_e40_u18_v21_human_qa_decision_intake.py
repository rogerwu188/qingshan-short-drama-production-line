import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.e40_u18_v21_human_qa_decision_intake import EXPECTED, HARD_GATES, ROOT, V19_RECEIPT, V7_HUMAN, intake_decisions


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root: Path) -> tuple[Path, Path]:
    for relative, _ in (V7_HUMAN, V19_RECEIPT):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    assets = []
    decisions = []
    for task_id, fingerprint in EXPECTED.items():
        assets.append({
            "review_asset_id": "fixture",
            "exact_task_id": task_id,
            "transaction_fingerprint": fingerprint,
            "output_path": f"outputs/{task_id}.png",
            "output_sha256": hashlib.sha256(task_id.encode()).hexdigest(),
            "source_dimensions": {"width": 1024, "height": 1024},
            "provenance": "fixture",
            "license_or_local_authorship": "fixture",
        })
        decisions.append({
            "exact_task_id": task_id,
            "transaction_fingerprint": fingerprint,
            "output_sha256": hashlib.sha256(task_id.encode()).hexdigest(),
            "review_layers": [
                {"name": "ORIGINAL_RESOLUTION", "score": 92, "hard_gate_results": {gate: True for gate in HARD_GATES[task_id]}, "decision": "PASS"},
                {"name": "AUDIENCE_SCALE_720X1280", "score": 90, "hard_gate_results": {gate: True for gate in HARD_GATES[task_id]}, "decision": "PASS"},
            ],
        })
    manifest = {
        "schema": "qingshan.e40.u18.v19.human_qa_ready_manifest.v1",
        "status": "READY_FOR_ORIGINAL_AND_720X1280_HUMAN_QA_NO_ADMISSION",
        "assets": assets,
        "output_admission_permitted": False,
        "composite_permitted": False,
        "video_authorization_permitted": False,
    }
    manifest_path = root / "human_manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    payload = {
        "human_qa_manifest_sha256": sha(manifest_path),
        "v7_human_sha256": V7_HUMAN[1],
        "v19_receipt_sha256": V19_RECEIPT[1],
        "reviewer": "synthetic-human-reviewer",
        "reviewed_at": "2026-08-13T10:20:00Z",
        "assets": decisions,
    }
    decisions_path = root / "decisions.json"
    decisions_path.write_text(json.dumps(payload))
    return manifest_path, decisions_path


class DecisionIntakeTest(unittest.TestCase):
    def test_all_pass_emits_proposal_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, decisions = fixture(root)
            result = intake_decisions(manifest, decisions, root)
            self.assertEqual(result["status"], "ASSET_ADMISSION_PROPOSAL_READY_PENDING_INDEPENDENT_AUTHORIZATION")
            self.assertIsNone(result["failure_memory_draft"])
            self.assertFalse(result["output_admission_permitted"])
            self.assertFalse(result["composite_permitted"])
            self.assertFalse(result["video_authorization_permitted"])

    def test_mixed_pass_fail_emits_draft_and_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, decisions = fixture(root)
            row = json.loads(decisions.read_text())
            row["assets"][1]["review_layers"][1]["hard_gate_results"]["AUDIENCE_READABLE"] = False
            row["assets"][1]["review_layers"][1]["decision"] = "FAIL"
            decisions.write_text(json.dumps(row))
            result = intake_decisions(manifest, decisions, root)
            self.assertEqual(result["status"], "TASK_LOCAL_REMOTE_WAIT")
            self.assertEqual(result["failure_memory_draft"]["status"], "DRAFT_ONLY_NOT_WRITTEN_TO_FORMAL_MEMORY")
            self.assertFalse(result["formal_failure_memory_write_performed"])

    def test_missing_scale_emits_draft_and_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, decisions = fixture(root)
            row = json.loads(decisions.read_text())
            row["assets"][0]["review_layers"].pop()
            decisions.write_text(json.dumps(row))
            result = intake_decisions(manifest, decisions, root)
            self.assertEqual(result["status"], "TASK_LOCAL_REMOTE_WAIT")
            self.assertTrue(any("MISSING_OR_DUPLICATE_REVIEW_SCALE" in failure for failure in result["failures"]))

    def test_stale_manifest_sha_emits_draft_and_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, decisions = fixture(root)
            row = json.loads(decisions.read_text())
            row["human_qa_manifest_sha256"] = "0" * 64
            decisions.write_text(json.dumps(row))
            result = intake_decisions(manifest, decisions, root)
            self.assertEqual(result["status"], "TASK_LOCAL_REMOTE_WAIT")
            self.assertIn("STALE_OR_WRONG_V19_HUMAN_QA_MANIFEST_SHA", result["failures"])


if __name__ == "__main__":
    unittest.main()
