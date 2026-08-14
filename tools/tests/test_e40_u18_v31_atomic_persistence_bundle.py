import json
import tempfile
import unittest
from pathlib import Path

from tools.e40_u18_v31_atomic_persistence_bundle import FORMAL_MEMORY, ROOT, V29_RECEIPT, compile_bundle
from tools.e40_u18_v29_explicit_decision_trigger import verify
from tools.tests.test_e40_u18_v29_explicit_decision_trigger import build


def setup(root: Path, branch: str) -> tuple[Path, Path]:
    archive_path, decision_path, ledger_path = build(root, branch)
    for relative, _ in (FORMAL_MEMORY, V29_RECEIPT):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    proposal = verify(archive_path, decision_path, ledger_path, root)["persistence_proposal"]
    proposal_path = root / "proposal.json"
    proposal_path.write_text(json.dumps(proposal))
    if branch == "ROOT":
        target = root / "workflow/approvals/E40_U18_TEST_AUTHORIZATION.json"
    else:
        target = root / "workflow/claude_writer_agent/formal_memory_updates/E40_U18_TEST_MEMORY_EVENT.json"
    return proposal_path, target


class AtomicPersistenceBundleTest(unittest.TestCase):
    def test_valid_root_dry_run_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposal, target = setup(root, "ROOT")
            result = compile_bundle(proposal, target, root)
            self.assertEqual(result["status"], "ATOMIC_PERSISTENCE_BUNDLE_READY_DRY_RUN_ONLY")
            self.assertFalse(result["nonce_registered"])
            self.assertFalse(result["target_written"])
            self.assertFalse(target.exists())

    def test_valid_memory_dry_run_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposal, target = setup(root, "MEMORY")
            result = compile_bundle(proposal, target, root)
            self.assertEqual(result["status"], "ATOMIC_PERSISTENCE_BUNDLE_READY_DRY_RUN_ONLY")
            self.assertEqual(result["bundle"]["simulated_cas_order"][1:3], ["REGISTER_NONCE_FIRST", "WRITE_BRANCH_TARGET_SECOND"])
            self.assertFalse(target.exists())

    def test_target_exists_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposal, target = setup(root, "ROOT")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("existing")
            self.assertIn("TARGET_PATH_ALREADY_EXISTS", compile_bundle(proposal, target, root)["failures"])

    def test_nonce_race_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposal, target = setup(root, "MEMORY")
            value = json.loads(proposal.read_text())
            ledger = Path(value["replay_ledger_path"])
            ledger.write_text(json.dumps({"schema": "qingshan.e40.u18.v29.readonly_nonce_replay_ledger.v1", "used_nonces": [value["nonce"]]}))
            value["replay_ledger_sha256"] = __import__("hashlib").sha256(ledger.read_bytes()).hexdigest()
            proposal.write_text(json.dumps(value))
            self.assertIn("NONCE_LEDGER_NOT_ZERO_MATCH", compile_bundle(proposal, target, root)["failures"])

    def test_stale_memory_and_queue_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposal, target = setup(root, "ROOT")
            (root / FORMAL_MEMORY[0]).write_text("{}")
            (root / "workflow/work_queue.json").write_text("{}")
            result = compile_bundle(proposal, target, root)
            self.assertIn("FORMAL_MEMORY_PHYSICAL_SHA_LOCK_FAILED", result["failures"])
            self.assertIn("WORK_QUEUE_PHYSICAL_SHA_LOCK_FAILED", result["failures"])

    def test_simulated_second_step_failure_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposal, target = setup(root, "ROOT")
            result = compile_bundle(proposal, target, root, "AFTER_NONCE_REGISTER")
            self.assertEqual(result["simulation"]["status"], "ROLLBACK_SIMULATED_NO_DISK_WRITE")
            self.assertTrue(result["simulation"]["rollback_complete"])
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
