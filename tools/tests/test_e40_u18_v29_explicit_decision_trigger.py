import json
import tempfile
import unittest
from pathlib import Path

from tools.e40_u18_v29_explicit_decision_trigger import ROOT, V27_RECEIPT, verify
from tools.tests.test_e40_u18_v27_decision_packet_archive import memory_packet, root_packet, setup
from tools.e40_u18_v27_decision_packet_archive import archive


def build(root: Path, branch: str) -> tuple[Path, Path, Path]:
    setup(root)
    receipt = root / V27_RECEIPT[0]
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_bytes((ROOT / V27_RECEIPT[0]).read_bytes())
    packet = root_packet(root) if branch == "ROOT" else memory_packet(root)
    manifest = archive(packet, root)["archive_manifest"]
    archive_path = root / "archive.json"
    archive_path.write_text(json.dumps(manifest))
    decision = {
        "decision_type": "EXPLICIT_ROOT_DECISION" if branch == "ROOT" else "EXPLICIT_MEMORY_DECISION",
        "archive_manifest_sha256": manifest["archive_manifest_sha256"],
        "signer": "independent-root-signer-c",
        "signed_at": "2026-08-13T11:15:00Z",
        "nonce": f"E40-U18-V29-{branch}-nonce-0001",
        "readonly_replay_query_matches": 0,
    }
    decision_path = root / "decision.json"
    decision_path.write_text(json.dumps(decision))
    ledger = {"schema": "qingshan.e40.u18.v29.readonly_nonce_replay_ledger.v1", "used_nonces": []}
    ledger_path = root / "ledger.json"
    ledger_path.write_text(json.dumps(ledger))
    return archive_path, decision_path, ledger_path


class ExplicitDecisionTriggerTest(unittest.TestCase):
    def test_valid_root_proposal_not_written(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path, decision, ledger = build(root, "ROOT")
            result = verify(archive_path, decision, ledger, root)
            self.assertEqual(result["status"], "AUTHORIZATION_PERSISTENCE_PROPOSAL_READY_NOT_WRITTEN")
            self.assertFalse(result["formal_authorization_written"])
            self.assertFalse(result["nonce_registered"])

    def test_valid_memory_proposal_not_written(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path, decision, ledger = build(root, "MEMORY")
            result = verify(archive_path, decision, ledger, root)
            self.assertEqual(result["status"], "FORMAL_MEMORY_PERSISTENCE_PROPOSAL_READY_NOT_WRITTEN")
            self.assertFalse(result["formal_memory_written"])
            self.assertFalse(result["nonce_registered"])

    def test_wrong_branch_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path, decision, ledger = build(root, "ROOT")
            value = json.loads(decision.read_text())
            value["decision_type"] = "EXPLICIT_MEMORY_DECISION"
            decision.write_text(json.dumps(value))
            self.assertIn("WRONG_DECISION_BRANCH", verify(archive_path, decision, ledger, root)["failures"])

    def test_wrong_archive_sha_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path, decision, ledger = build(root, "ROOT")
            value = json.loads(decision.read_text())
            value["archive_manifest_sha256"] = "0" * 64
            decision.write_text(json.dumps(value))
            self.assertIn("ARCHIVE_MANIFEST_SHA_BINDING_MISMATCH", verify(archive_path, decision, ledger, root)["failures"])

    def test_repeated_nonce_rejected_readonly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path, decision, ledger = build(root, "MEMORY")
            nonce = json.loads(decision.read_text())["nonce"]
            ledger.write_text(json.dumps({"schema": "qingshan.e40.u18.v29.readonly_nonce_replay_ledger.v1", "used_nonces": [nonce]}))
            before = ledger.read_bytes()
            result = verify(archive_path, decision, ledger, root)
            self.assertIn("NONCE_REPLAY_OR_NONZERO_QUERY", result["failures"])
            self.assertEqual(ledger.read_bytes(), before)

    def test_stale_canonical_and_queue_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path, decision, ledger = build(root, "ROOT")
            (root / "workflow/work_queue.json").write_text("{}")
            (root / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json").write_text("{}")
            result = verify(archive_path, decision, ledger, root)
            self.assertIn("WORK_QUEUE_PHYSICAL_SHA_LOCK_FAILED", result["failures"])
            self.assertIn("MANIFEST_PHYSICAL_SHA_LOCK_FAILED", result["failures"])


if __name__ == "__main__":
    unittest.main()
