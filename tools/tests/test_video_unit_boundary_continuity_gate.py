import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.video_unit_boundary_continuity_gate import (
    REQUIRED_CHECKS,
    transition_sha,
    validate_boundary_decision,
)


class VideoUnitBoundaryContinuityGateTests(unittest.TestCase):
    def test_exact_media_and_transition_bound_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "u1.mp4"
            second = Path(tmp) / "u2.mp4"
            first.write_bytes(b"first-media")
            second.write_bytes(b"second-media")
            transition = {"from_unit_id": "U1", "to_unit_id": "U2", "visual_bridge": "帘缘匹配"}
            previous = {"unit_id": "U1"}
            current = {"unit_id": "U2", "incoming_transition_contract": transition}
            decision = {
                "status": "PASS", "from_unit_id": "U1", "to_unit_id": "U2",
                "from_media_sha256": hashlib.sha256(first.read_bytes()).hexdigest(),
                "to_media_sha256": hashlib.sha256(second.read_bytes()).hexdigest(),
                "transition_contract_sha256": transition_sha(transition),
                "checks": {key: True for key in REQUIRED_CHECKS},
                "reviewer": "VISION-QA-1", "evidence_ref": "qa/pair.jpg",
            }
            result = validate_boundary_decision(
                decision, previous_unit=previous, current_unit=current,
                previous_media=first, current_media=second,
            )
            self.assertEqual(result["status"], "PASS")

    def test_rejects_unreviewed_target_subject(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "u1.mp4"
            second = Path(tmp) / "u2.mp4"
            first.write_bytes(b"first-media")
            second.write_bytes(b"second-media")
            transition = {"from_unit_id": "U1", "to_unit_id": "U2"}
            checks = {key: True for key in REQUIRED_CHECKS}
            checks["target_subject_present_at_required_start"] = False
            decision = {
                "status": "PASS", "from_unit_id": "U1", "to_unit_id": "U2",
                "from_media_sha256": hashlib.sha256(first.read_bytes()).hexdigest(),
                "to_media_sha256": hashlib.sha256(second.read_bytes()).hexdigest(),
                "transition_contract_sha256": transition_sha(transition),
                "checks": checks, "reviewer": "VISION-QA-1", "evidence_ref": "qa/pair.jpg",
            }
            with self.assertRaisesRegex(ValueError, "target_subject_present"):
                validate_boundary_decision(
                    decision, previous_unit={"unit_id": "U1"},
                    current_unit={"unit_id": "U2", "incoming_transition_contract": transition},
                    previous_media=first, current_media=second,
                )


if __name__ == "__main__":
    unittest.main()
