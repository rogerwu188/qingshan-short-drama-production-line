import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
sys.path.insert(0, str(TOOLS))

import video_q2_builder as q2  # noqa: E402


class VideoQ2LineOwnerAcceptanceTest(unittest.TestCase):
    """The Q2 order channel (2026-10-01): admits only on an exact, media-bound line-owner order."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.orders = self.tmp / "private" / "SUPERVISOR_ORDERS.json"
        self.media = self.tmp / "E99-VU-001.mp4"
        self.media.write_bytes(b"synthetic take")
        self.sha = q2.sha256_file(self.media)
        self.result_path = self.tmp / "admission_result.json"
        self.result = {"status": "FAIL", "downstream_status": "FAIL_NOT_ADMITTED", "failures": [
            "evidence_5:DEFECT-TIER-TOLERANCE:registered_gate_not_pass:FAIL_NOT_ADMITTED:P1",
            "required_registered_gate_not_pass:DEFECT-TIER-TOLERANCE",
            "evidence_1:CHARACTER-IDENTITY-ADMISSION:registered_gate_not_pass:FAIL_NOT_ADMITTED:P0",
        ]}
        self.result_path.write_text(json.dumps(self.result))
        self._env = {k: os.environ.get(k) for k in ("NALU_SUPERVISOR_ORDERS_PATH", "NALU_LATEST_ORDER_SEQ",
                                                    "NALU_LINE_OWNER_ID")}

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _record(self, detectors, media=None):
        argv = [sys.executable, str(TOOLS / "record_supervisor_order.py"), "--seq", "1", "--order", "c",
                "--episode", "E99", "--kind", "GATE_FAIL_ACCEPTANCE", "--gate-id", q2.Q2_ACCEPTANCE_GATE_ID,
                "--context", "synthetic", "--orders", str(self.orders)]
        for detector in detectors:
            argv += ["--detector", detector]
        argv += ["--media", f"E99-VU-001={media or self.media}"]
        done = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        os.environ.update({"NALU_SUPERVISOR_ORDERS_PATH": str(self.orders), "NALU_LATEST_ORDER_SEQ": "1",
                           "NALU_LINE_OWNER_ID": "Roger"})

    def test_detectors_are_gate_level(self):
        self.assertEqual(q2._q2_acceptance_detectors("E99-VU-001", self.result["failures"]),
                         ["E99-VU-001:CHARACTER-IDENTITY-ADMISSION", "E99-VU-001:DEFECT-TIER-TOLERANCE"])

    def test_no_order_means_no_admission(self):
        os.environ.pop("NALU_SUPERVISOR_ORDERS_PATH", None)
        self.assertIsNone(q2._line_owner_q2_acceptance("E99", "E99-VU-001", self.sha, self.result,
                                                       self.result_path))

    def test_partial_order_does_not_admit(self):
        self._record(["E99-VU-001:DEFECT-TIER-TOLERANCE"])
        self.assertIsNone(q2._line_owner_q2_acceptance("E99", "E99-VU-001", self.sha, self.result,
                                                       self.result_path))

    def test_other_take_does_not_admit(self):
        other = self.tmp / "other.mp4"
        other.write_bytes(b"a different take")
        self._record(["E99-VU-001:DEFECT-TIER-TOLERANCE", "E99-VU-001:CHARACTER-IDENTITY-ADMISSION"], media=other)
        self.assertIsNone(q2._line_owner_q2_acceptance("E99", "E99-VU-001", self.sha, self.result,
                                                       self.result_path))

    def test_full_media_bound_order_admits_and_keeps_engine_result(self):
        self._record(["E99-VU-001:DEFECT-TIER-TOLERANCE", "E99-VU-001:CHARACTER-IDENTITY-ADMISSION"])
        record = q2._line_owner_q2_acceptance("E99", "E99-VU-001", self.sha, self.result, self.result_path)
        self.assertIsNotNone(record)
        self.assertEqual(record["gate_status_kept"], "FAIL")
        written = json.loads(self.result_path.read_text())
        self.assertEqual(written["downstream_status"], q2.TERMINAL_DOWNSTREAM)
        self.assertEqual(written["engine_failures"], self.result["failures"])
        engine_copy = json.loads(self.result_path.with_suffix(".engine.json").read_text())
        self.assertEqual(engine_copy["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
