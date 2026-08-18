import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.shot_media_admission_gate import (
    KEYFRAME_REQUIRED_GATES,
    VIDEO_REQUIRED_GATES,
    evaluate,
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ShotMediaAdmissionGateTests(unittest.TestCase):
    def setUp(self):
        self.registry = {"gates": [{"gate_id": value} for value in VIDEO_REQUIRED_GATES]}

    def fixture(self, root: Path, kind="KEYFRAME_VIDEO_SUBMIT"):
        asset = root / "asset.png"
        asset.write_bytes(b"exact-media")
        asset_sha = digest(asset)
        required = KEYFRAME_REQUIRED_GATES if kind == "KEYFRAME_VIDEO_SUBMIT" else VIDEO_REQUIRED_GATES
        evidence = []
        for index, gate_id in enumerate(required):
            report = root / f"evidence-{index}.json"
            report.write_text(json.dumps({"gate_id": gate_id, "status": "PASS"}), encoding="utf-8")
            evidence.append({
                "gate_id": gate_id,
                "status": "PASS",
                "reviewed_asset_sha256": asset_sha,
                "evidence_path": str(report),
                "evidence_sha256": digest(report),
                "original_resolution_review": index == 0,
                "reviewer_type": "HUMAN" if index == 0 else "AI_VISUAL",
            })
        payload = {
            "kind": kind,
            "asset_path": str(asset),
            "asset_sha256": asset_sha,
            "evidence": evidence,
        }
        if kind == "VIDEO_ASSEMBLY":
            payload["technical_qa"] = {
                "status": "TECHNICAL_PASS_CONTENT_UNREVIEWED",
                "reviewed_asset_sha256": asset_sha,
            }
        return payload

    def test_keyframe_requires_exact_sha_registered_content_admission(self):
        with TemporaryDirectory() as directory:
            report = evaluate(self.fixture(Path(directory)), self.registry, Path(directory))
            self.assertEqual(report["status"], "ADMITTED_FOR_VIDEO_SUBMIT", report["failures"])

    def test_advisory_and_unregistered_metric_cannot_admit_or_block(self):
        with TemporaryDirectory() as directory:
            payload = self.fixture(Path(directory))
            payload["evidence"][0]["status"] = "ADVISORY_NOT_A_GATE"
            payload["evidence"].append({"gate_id": "PELVIS-PIXEL-RATIO", "status": "FAIL"})
            report = evaluate(payload, self.registry, Path(directory))
            self.assertEqual(report["status"], "FAIL_NOT_ADMITTED")
            self.assertTrue(any("advisory_not_admission" in row for row in report["diagnostics"]))
            self.assertTrue(any("unregistered_gate_downgraded" in row for row in report["diagnostics"]))
            self.assertFalse(any("PELVIS-PIXEL-RATIO" in row for row in report["failures"]))

    def test_technical_pass_alone_never_admits_video(self):
        with TemporaryDirectory() as directory:
            payload = self.fixture(Path(directory), "VIDEO_ASSEMBLY")
            payload["evidence"] = []
            report = evaluate(payload, self.registry, Path(directory))
            self.assertEqual(report["status"], "FAIL_NOT_ADMITTED")
            self.assertTrue(any("required_registered_gate_not_pass" in row for row in report["failures"]))

    def test_video_requires_honest_technical_status(self):
        with TemporaryDirectory() as directory:
            payload = self.fixture(Path(directory), "VIDEO_ASSEMBLY")
            payload["technical_qa"]["status"] = "PASS_ALL_QA"
            report = evaluate(payload, self.registry, Path(directory))
            self.assertIn("technical_qa_status_missing_or_dishonest", report["failures"])

    def test_unrelated_evidence_payload_cannot_be_wrapped_as_pass(self):
        with TemporaryDirectory() as directory:
            payload = self.fixture(Path(directory))
            evidence = Path(payload["evidence"][0]["evidence_path"])
            evidence.write_text(json.dumps({"gate_id": "OTHER-GATE", "status": "PASS"}), encoding="utf-8")
            payload["evidence"][0]["evidence_sha256"] = digest(evidence)
            report = evaluate(payload, self.registry, Path(directory))
            self.assertTrue(any("evidence_gate_id_mismatch" in value for value in report["failures"]))


if __name__ == "__main__":
    unittest.main()
