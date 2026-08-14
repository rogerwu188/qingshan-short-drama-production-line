import json
import tempfile
import unittest
from pathlib import Path

from tools.e40_u18_v23_independent_authority_review import review
from tools.e40_u18_v25_final_persistence_preaudit import CANONICAL, ROOT, V23_RECEIPT, WORK_QUEUE, ZERO_KEYS, audit, sha256
from tools.tests.test_e40_u18_v23_independent_authority_review import fail_fixture, pass_fixture


def prepare_root(root: Path) -> None:
    for relative, _ in [*CANONICAL.values(), WORK_QUEUE, V23_RECEIPT]:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())


def envelope(root: Path, subject_path: Path, v21_path: Path) -> Path:
    value = {
        "v23_subject_sha256": sha256(subject_path),
        "v21_subject_path": str(v21_path),
        "physical_locks": {
            "script_sha256": CANONICAL["script"][1],
            "manifest_sha256": CANONICAL["manifest"][1],
            "work_queue_sha256": WORK_QUEUE[1],
            "v23_receipt_sha256": V23_RECEIPT[1],
        },
        "side_effects": {key: 0 for key in ZERO_KEYS},
    }
    path = root / "preaudit_envelope.json"
    path.write_text(json.dumps(value))
    return path


def pass_subject(root: Path) -> tuple[Path, Path]:
    v21, authority = pass_fixture(root)
    value = review(v21, authority, root)["authorization_request"]
    path = root / "v23_authorization_request.json"
    path.write_text(json.dumps(value))
    return path, v21


def fail_subject(root: Path) -> tuple[Path, Path]:
    v21, authority = fail_fixture(root)
    value = review(v21, authority, root)["formal_memory_update_proposal"]
    path = root / "v23_memory_proposal.json"
    path.write_text(json.dumps(value))
    return path, v21


class FinalPersistencePreauditTest(unittest.TestCase):
    def test_all_valid_pass_branch_emits_root_packet_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_root(root)
            subject, v21 = pass_subject(root)
            result = audit(subject, envelope(root, subject, v21), root)
            self.assertEqual(result["status"], "ROOT_DECISION_PACKET_READY_NOT_EXECUTED")
            self.assertFalse(result["formal_authorization_created"])
            self.assertFalse(result["admission_permitted"])
            self.assertFalse(result["retry_permitted"])

    def test_all_valid_fail_branch_emits_memory_packet_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_root(root)
            subject, v21 = fail_subject(root)
            result = audit(subject, envelope(root, subject, v21), root)
            self.assertEqual(result["status"], "MEMORY_DECISION_PACKET_READY_NOT_WRITTEN")
            self.assertFalse(result["formal_memory_written"])
            self.assertFalse(result["retry_permitted"])

    def test_stale_work_queue_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_root(root)
            (root / WORK_QUEUE[0]).write_text("{}")
            subject, v21 = fail_subject(root)
            result = audit(subject, envelope(root, subject, v21), root)
            self.assertEqual(result["status"], "TASK_LOCAL_REMOTE_WAIT")
            self.assertIn("WORK_QUEUE_PHYSICAL_SHA_LOCK_FAILED", result["failures"])

    def test_stale_canonical_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_root(root)
            (root / CANONICAL["manifest"][0]).write_bytes(b"drift")
            subject, v21 = fail_subject(root)
            result = audit(subject, envelope(root, subject, v21), root)
            self.assertEqual(result["status"], "TASK_LOCAL_REMOTE_WAIT")
            self.assertIn("MANIFEST_PHYSICAL_SHA_LOCK_FAILED", result["failures"])

    def test_forged_reviewer_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_root(root)
            subject, v21 = pass_subject(root)
            subject_row = json.loads(subject.read_text())
            v21_row = json.loads(v21.read_text())
            subject_row["authority_reviewer"] = v21_row["reviewer"].upper()
            subject.write_text(json.dumps(subject_row))
            result = audit(subject, envelope(root, subject, v21), root)
            self.assertEqual(result["status"], "TASK_LOCAL_REMOTE_WAIT")
            self.assertIn("FORGED_OR_NONINDEPENDENT_REVIEWER", result["failures"])


if __name__ == "__main__":
    unittest.main()
