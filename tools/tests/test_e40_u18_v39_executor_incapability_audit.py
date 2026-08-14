import builtins
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.e40_u18_v31_atomic_persistence_bundle import compile_bundle
from tools.e40_u18_v35_authority_document_verifier import verify as verify_v35
from tools.e40_u18_v37_authority_consumption_preflight import verify as verify_v37
from tools.e40_u18_v39_executor_incapability_audit import TARGETS, audit
from tools.tests.test_e40_u18_v31_atomic_persistence_bundle import setup as v31_setup
from tools.tests.test_e40_u18_v35_authority_document_verifier import NOW, fixture as v35_fixture
from tools.tests.test_e40_u18_v37_authority_consumption_preflight import fixture as v37_fixture


class WriteDenied(RuntimeError):
    pass


def deny(*args, **kwargs):
    raise WriteDenied("write capability denied by V39 test sandbox")


def guarded_open(real_open):
    def open_only_read(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            raise WriteDenied("non-read open denied")
        return real_open(file, mode, *args, **kwargs)
    return open_only_read


def write_denial_patches():
    return (
        patch("builtins.open", new=guarded_open(builtins.open)),
        patch.object(Path, "write_text", new=deny),
        patch.object(Path, "write_bytes", new=deny),
        patch.object(Path, "touch", new=deny),
        patch.object(Path, "unlink", new=deny),
        patch.object(Path, "rename", new=deny),
        patch.object(Path, "replace", new=deny),
        patch.object(Path, "mkdir", new=deny),
        patch("os.remove", new=deny),
        patch("os.unlink", new=deny),
        patch("os.rename", new=deny),
        patch("os.replace", new=deny),
        patch("os.mkdir", new=deny),
        patch("os.makedirs", new=deny),
    )


class ExecutorIncapabilityAuditTest(unittest.TestCase):
    def test_static_allowlist_passes_real_core_entrypoints(self):
        value = audit()
        self.assertEqual(value["status"], "CAPABILITY_SEPARATION_PASS_NO_EXECUTION")
        self.assertFalse(value["executor_implemented"])
        self.assertFalse(value["network_capability"])

    def test_static_audit_rejects_malicious_network_and_write_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "malicious.py"
            source.write_text("import socket\nfrom pathlib import Path\ndef verify(p):\n Path(p).write_text('owned')\n return socket.socket()\n")
            value = audit({"EVIL": (source, "verify")})
            self.assertEqual(value["status"], "CAPABILITY_SEPARATION_FAIL_CLOSED")
            self.assertIn("EVIL_FORBIDDEN_IMPORT:socket", value["failures"])
            self.assertTrue(any("FORBIDDEN_CALL" in item and "write_text" in item for item in value["failures"]))

    def test_v31_core_succeeds_under_global_write_denial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposal, target = v31_setup(root, "ROOT")
            contexts = write_denial_patches()
            with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4], contexts[5], contexts[6], contexts[7], contexts[8], contexts[9], contexts[10], contexts[11], contexts[12]:
                value = compile_bundle(proposal, target, root)
                self.assertEqual(value["status"], "ATOMIC_PERSISTENCE_BUNDLE_READY_DRY_RUN_ONLY")
                with self.assertRaises(WriteDenied):
                    target.write_text("forbidden")
            self.assertFalse(target.exists())

    def test_v35_core_succeeds_under_global_write_denial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority, bundle, ledger = v35_fixture(root, "MEMORY")
            before = {path: path.read_bytes() for path in (authority, bundle, ledger)}
            contexts = write_denial_patches()
            with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4], contexts[5], contexts[6], contexts[7], contexts[8], contexts[9], contexts[10], contexts[11], contexts[12]:
                value = verify_v35(authority, bundle, ledger, NOW, root)
                self.assertEqual(value["status"], "VALID_AUTHORITY_DOCUMENT_NOT_EXECUTED")
                with self.assertRaises(WriteDenied):
                    ledger.write_text(json.dumps({"used_nonces": ["forbidden"]}))
            self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_v37_core_succeeds_under_global_write_denial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority, bundle, witness, ledger, target = v37_fixture(root, "ROOT")
            protected = (authority, bundle, witness, ledger)
            before = {path: path.read_bytes() for path in protected}
            contexts = write_denial_patches()
            with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4], contexts[5], contexts[6], contexts[7], contexts[8], contexts[9], contexts[10], contexts[11], contexts[12]:
                value = verify_v37(authority, bundle, witness, root, NOW)
                self.assertEqual(value["status"], "AUTHORITY_CONSUMPTION_PREFLIGHT_READY_NOT_EXECUTED")
                for forbidden in (target, ledger, root / "workflow/approvals/forbidden.json", root / "workflow/claude_writer_agent/formal_memory_updates/forbidden.json"):
                    with self.assertRaises(WriteDenied):
                        forbidden.write_text("forbidden")
            self.assertFalse(target.exists())
            self.assertEqual(before, {path: path.read_bytes() for path in before})


if __name__ == "__main__":
    unittest.main()
