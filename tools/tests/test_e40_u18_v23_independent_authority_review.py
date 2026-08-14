import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.e40_u18_v23_independent_authority_review import EXPECTED, HARD_GATES, REQUIREMENTS, ROOT, V21_RECEIPT, json_sha, review


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pass_fixture(root: Path) -> tuple[Path, Path]:
    receipt = root / V21_RECEIPT[0]
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_bytes((ROOT / V21_RECEIPT[0]).read_bytes())
    credit = {"pay": 128, "refund": 0, "net": 128, "status": "PASS"}
    promotion = {
        "schema": "qingshan.e40.u18.v17.output_machine_promotion_manifest.v1",
        "credit_classification": credit,
        "source_snapshot_locks": {"authoritative_credit": {"path": "credit.json", "sha256": "a" * 64}},
    }
    promotion_path = root / "promotion.json"
    promotion_path.write_text(json.dumps(promotion))
    human_assets = []
    proposal_assets = []
    for task_id, fp in EXPECTED.items():
        output_sha = hashlib.sha256(task_id.encode()).hexdigest()
        human_assets.append({"exact_task_id": task_id, "transaction_fingerprint": fp, "output_sha256": output_sha, "provenance": "exact source", "license_or_local_authorship": "licensed fixture"})
        layers = [
            {"name": "ORIGINAL_RESOLUTION", "score": 92, "hard_gate_results": {gate: True for gate in HARD_GATES[task_id]}, "decision": "PASS"},
            {"name": "AUDIENCE_SCALE_720X1280", "score": 90, "hard_gate_results": {gate: True for gate in HARD_GATES[task_id]}, "decision": "PASS"},
        ]
        proposal_assets.append({"exact_task_id": task_id, "transaction_fingerprint": fp, "output_sha256": output_sha, "review_layers": layers})
    human = {
        "schema": "qingshan.e40.u18.v19.human_qa_ready_manifest.v1",
        "input_locks": {"v17_promotion_path": str(promotion_path), "v17_promotion_sha256": sha(promotion_path)},
        "assets": human_assets,
    }
    human_path = root / "human.json"
    human_path.write_text(json.dumps(human))
    proposal = {
        "schema": "qingshan.e40.u18.v21.asset_admission_proposal.v1",
        "status": "PROPOSED_PENDING_INDEPENDENT_AUTHORIZATION",
        "reviewer": "human-reviewer-a",
        "source_locks": {"human_qa_manifest_path": str(human_path), "human_qa_manifest_sha256": sha(human_path)},
        "assets": proposal_assets,
        "output_admission_permitted": False,
        "composite_permitted": False,
        "video_authorization_permitted": False,
    }
    proposal_path = root / "proposal.json"
    proposal_path.write_text(json.dumps(proposal))
    authority = {
        "authority_reviewer": "independent-reviewer-b",
        "authority_reviewed_at": "2026-08-13T10:30:00Z",
        "v21_subject_sha256": sha(proposal_path),
        "v21_receipt_sha256": V21_RECEIPT[1],
        "binding_locks": {
            "v19_human_manifest_sha256": sha(human_path),
            "v17_promotion_sha256": sha(promotion_path),
            "credit_classification_sha256": json_sha(credit),
            "authoritative_credit_snapshot_sha256": "a" * 64,
        },
    }
    authority_path = root / "authority.json"
    authority_path.write_text(json.dumps(authority))
    return proposal_path, authority_path


def fail_fixture(root: Path) -> tuple[Path, Path]:
    receipt = root / V21_RECEIPT[0]
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_bytes((ROOT / V21_RECEIPT[0]).read_bytes())
    draft = {
        "schema": "qingshan.e40.u18.v21.failure_memory_draft.v1",
        "status": "DRAFT_ONLY_NOT_WRITTEN_TO_FORMAL_MEMORY",
        "reviewer": "human-reviewer-a",
        "failures": ["HARD_GATE_FAIL:fixture"],
        "formal_memory_update_permitted": False,
        "retry_authorized": False,
    }
    draft_path = root / "draft.json"
    draft_path.write_text(json.dumps(draft))
    authority = {
        "authority_reviewer": "independent-reviewer-b",
        "authority_reviewed_at": "2026-08-13T10:30:00Z",
        "v21_subject_sha256": sha(draft_path),
        "v21_receipt_sha256": V21_RECEIPT[1],
        "original_fingerprint_quarantine": sorted(EXPECTED.values()),
        "materially_changed_next_attempt_requirements": {key: True for key in REQUIREMENTS},
    }
    authority_path = root / "authority.json"
    authority_path.write_text(json.dumps(authority))
    return draft_path, authority_path


class IndependentAuthorityReviewTest(unittest.TestCase):
    def test_all_pass_independent_review_emits_request_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subject, authority = pass_fixture(root)
            result = review(subject, authority, root)
            self.assertEqual(result["status"], "AUTHORIZATION_REQUEST_READY")
            self.assertFalse(result["authorization_request"]["authorization_granted"])
            self.assertFalse(result["direct_admission_permitted"])

    def test_self_review_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subject, authority = pass_fixture(root)
            row = json.loads(authority.read_text())
            row["authority_reviewer"] = "human-reviewer-a"
            authority.write_text(json.dumps(row))
            result = review(subject, authority, root)
            self.assertEqual(result["status"], "TASK_LOCAL_REMOTE_WAIT")
            self.assertIn("SELF_REVIEW_REJECTED", result["failures"])

    def test_stale_binding_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subject, authority = pass_fixture(root)
            row = json.loads(authority.read_text())
            row["binding_locks"]["credit_classification_sha256"] = "0" * 64
            authority.write_text(json.dumps(row))
            result = review(subject, authority, root)
            self.assertEqual(result["status"], "TASK_LOCAL_REMOTE_WAIT")
            self.assertIn("AUTHORITY_REVIEW_BINDING_LOCKS_STALE_OR_INCOMPLETE", result["failures"])

    def test_failure_draft_emits_formal_memory_proposal_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subject, authority = fail_fixture(root)
            result = review(subject, authority, root)
            self.assertEqual(result["status"], "FORMAL_MEMORY_UPDATE_PROPOSAL_ONLY")
            self.assertFalse(result["formal_memory_write_performed"])
            self.assertFalse(result["formal_memory_update_proposal"]["retry_authorized"])


if __name__ == "__main__":
    unittest.main()
