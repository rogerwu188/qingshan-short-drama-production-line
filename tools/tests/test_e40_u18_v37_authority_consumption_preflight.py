import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tools.e40_u18_v35_authority_document_verifier import PINS
from tools.e40_u18_v37_authority_consumption_preflight import verify
from tools.tests.test_e40_u18_v35_authority_document_verifier import fixture as v35_fixture

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root: Path, branch: str = "ROOT") -> tuple[Path, Path, Path, Path, Path]:
    authority_path, bundle_path, ledger_path = v35_fixture(root, branch)
    bundle = json.loads(bundle_path.read_text())
    locks = bundle["locks"]
    proposal_path = Path(locks["v29_proposal_path"])
    decision_path = Path(locks["explicit_decision_path"])
    witness = {
        "schema": "qingshan.e40.u18.v37.local_preflight_witness.v1",
        "scope": "AUTHORITY_CONSUMPTION_PREFLIGHT_ONLY",
        "witness": "second-local-witness-d",
        "witnessed_at": "2026-08-13T11:59:30Z",
        "authority_document_sha256": sha256(authority_path),
        "v31_bundle_file_sha256": sha256(bundle_path),
        "v31_bundle_sha256": bundle["bundle_sha256"],
        "v29_proposal_sha256": sha256(proposal_path),
        "explicit_decision_sha256": sha256(decision_path),
        "nonce_ledger_sha256": sha256(ledger_path),
        "target_path": locks["target_path"],
        "nonce": bundle["nonce"],
        **PINS,
        "nonce_zero_matches": 0,
        "target_absent": True,
        "authority_consumed": False,
        "nonce_registered": False,
        "target_written": False,
    }
    witness_path = root / "witness.json"
    witness_path.write_text(json.dumps(witness))
    return authority_path, bundle_path, witness_path, ledger_path, Path(locks["target_path"])


class AuthorityConsumptionPreflightTest(unittest.TestCase):
    def test_valid_root_and_memory_ready_not_executed(self):
        for branch in ("ROOT", "MEMORY"):
            with self.subTest(branch=branch), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                authority, bundle, witness, ledger, target = fixture(root, branch)
                before = {path: path.read_bytes() for path in (authority, bundle, witness, ledger)}
                value = verify(authority, bundle, witness, root, NOW)
                self.assertEqual(value["status"], "AUTHORITY_CONSUMPTION_PREFLIGHT_READY_NOT_EXECUTED")
                for key in ("authority_consumed", "execution_authorized", "nonce_registered", "nonce_ledger_mutated", "target_written", "formal_authorization_written", "formal_memory_written"):
                    self.assertFalse(value[key])
                self.assertEqual(value["maximum_new_submissions"], 0)
                self.assertFalse(target.exists())
                self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_signer_collisions_rejected(self):
        for source in ("v35", "v29", "human", "authority"):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                authority, bundle, witness, _, _ = fixture(root)
                bundle_value = json.loads(bundle.read_text())
                decision = json.loads(Path(bundle_value["locks"]["explicit_decision_path"]).read_text())
                proposal = json.loads(Path(bundle_value["locks"]["v29_proposal_path"]).read_text())
                archive = json.loads(Path(proposal["archive_manifest_path"]).read_text())
                identities = {
                    "v35": json.loads(authority.read_text())["signer"]["identity"],
                    "v29": decision["signer"],
                    "human": archive["reviewers"]["human"],
                    "authority": archive["reviewers"]["authority"],
                }
                value = json.loads(witness.read_text())
                value["witness"] = identities[source].upper()
                witness.write_text(json.dumps(value))
                self.assertIn("LOCAL_WITNESS_SIGNER_COLLISION", verify(authority, bundle, witness, root, NOW)["failures"])

    def test_target_race_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority, bundle, witness, _, target = fixture(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("racing target")
            value = verify(authority, bundle, witness, root, NOW)
            self.assertIn("TARGET_RACE_DETECTED", value["failures"])
            self.assertFalse(value["target_written"])

    def test_nonce_race_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority, bundle, witness, ledger, _ = fixture(root, "MEMORY")
            nonce = json.loads(authority.read_text())["nonce"]
            ledger.write_text(json.dumps({"schema": "qingshan.e40.u18.v29.readonly_nonce_replay_ledger.v1", "used_nonces": [nonce]}))
            before = ledger.read_bytes()
            value = verify(authority, bundle, witness, root, NOW)
            self.assertIn("NONCE_RACE_DETECTED", value["failures"])
            self.assertEqual(before, ledger.read_bytes())
            self.assertFalse(value["nonce_registered"])

    def test_stale_physical_locks_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority, bundle, witness, _, _ = fixture(root)
            (root / "workflow/work_queue.json").write_text("{}")
            (root / "workflow/claude_writer_agent/GENERATION_PROMPT_FAILURE_MEMORY.json").write_text("{}")
            value = verify(authority, bundle, witness, root, NOW)
            self.assertIn("WORK_QUEUE_PHYSICAL_SHA_LOCK_STALE", value["failures"])
            self.assertIn("FORMAL_MEMORY_PHYSICAL_SHA_LOCK_STALE", value["failures"])

    def test_stale_bound_proposal_and_bundle_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority, bundle, witness, _, _ = fixture(root)
            bundle_value = json.loads(bundle.read_text())
            proposal = Path(bundle_value["locks"]["v29_proposal_path"])
            proposal_value = json.loads(proposal.read_text())
            proposal_value["signed_at"] = "2026-08-13T11:15:01Z"
            proposal.write_text(json.dumps(proposal_value))
            failures = verify(authority, bundle, witness, root, NOW)["failures"]
            self.assertIn("V29_PROPOSAL_SHA_LOCK_STALE", failures)
            bundle_value["rollback_policy"] = "TAMPERED"
            bundle.write_text(json.dumps(bundle_value))
            failures = verify(authority, bundle, witness, root, NOW)["failures"]
            self.assertIn("WITNESS_V31_BUNDLE_FILE_SHA256_LOCK_MISMATCH", failures)

    def test_witness_scope_expansion_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority, bundle, witness, _, _ = fixture(root)
            value = json.loads(witness.read_text())
            value["scope"] = "PREFLIGHT_AND_EXECUTION"
            witness.write_text(json.dumps(value))
            failures = verify(authority, bundle, witness, root, NOW)["failures"]
            self.assertIn("WITNESS_SCOPE_LOCK_MISMATCH", failures)


if __name__ == "__main__":
    unittest.main()
