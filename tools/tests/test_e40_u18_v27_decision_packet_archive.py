import json
import tempfile
import unittest
from pathlib import Path

from tools.e40_u18_v25_final_persistence_preaudit import audit
from tools.e40_u18_v27_decision_packet_archive import ROOT, V25_AUDITOR, V25_RECEIPT, WORK_QUEUE, archive
from tools.tests.test_e40_u18_v25_final_persistence_preaudit import envelope, fail_subject, pass_subject, prepare_root


def setup(root: Path) -> None:
    prepare_root(root)
    for relative, _ in (V25_RECEIPT, V25_AUDITOR):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())


def root_packet(root: Path) -> Path:
    subject, v21 = pass_subject(root)
    packet = audit(subject, envelope(root, subject, v21), root)["decision_packet"]
    path = root / "root_packet.json"
    path.write_text(json.dumps(packet))
    return path


def memory_packet(root: Path) -> Path:
    subject, v21 = fail_subject(root)
    packet = audit(subject, envelope(root, subject, v21), root)["decision_packet"]
    path = root / "memory_packet.json"
    path.write_text(json.dumps(packet))
    return path


class DecisionPacketArchiveTest(unittest.TestCase):
    def test_valid_root_packet_archives_and_waits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            setup(root)
            result = archive(root_packet(root), root)
            self.assertEqual(result["status"], "IMMUTABLE_NO_EXECUTION_ARCHIVE_MANIFEST_READY")
            self.assertEqual(result["archive_manifest"]["wait_trigger"]["trigger_type"], "EXPLICIT_ROOT_DECISION")
            self.assertFalse(result["formal_authorization_created"])
            self.assertFalse(result["admission_permitted"])

    def test_valid_memory_packet_archives_and_waits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            setup(root)
            result = archive(memory_packet(root), root)
            self.assertEqual(result["status"], "IMMUTABLE_NO_EXECUTION_ARCHIVE_MANIFEST_READY")
            self.assertEqual(result["archive_manifest"]["wait_trigger"]["trigger_type"], "EXPLICIT_MEMORY_DECISION")
            self.assertFalse(result["formal_memory_written"])
            self.assertFalse(result["retry_permitted"])

    def test_tampered_packet_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            setup(root)
            packet = root_packet(root)
            value = json.loads(packet.read_text())
            value["assets"][0]["output_sha256"] = "0" * 64
            packet.write_text(json.dumps(value))
            result = archive(packet, root)
            self.assertEqual(result["status"], "TASK_LOCAL_REMOTE_WAIT")
            self.assertTrue(any("TAMPERED" in failure for failure in result["failures"]))

    def test_stale_queue_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            setup(root)
            packet = memory_packet(root)
            (root / WORK_QUEUE[0]).write_text("{}")
            result = archive(packet, root)
            self.assertEqual(result["status"], "TASK_LOCAL_REMOTE_WAIT")
            self.assertIn("WORK_QUEUE_PHYSICAL_SHA_LOCK_FAILED", result["failures"])


if __name__ == "__main__":
    unittest.main()
