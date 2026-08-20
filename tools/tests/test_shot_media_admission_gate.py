import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.shot_media_admission_gate import (
    KEYFRAME_REQUIRED_GATES,
    VIDEO_REQUIRED_GATES,
    aggregate_template_defects,
    compute_input_template_id,
    evaluate,
    precheck_submission_inputs,
    validate_retry_change,
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
            self.assertEqual(report["status"], "ADMITTED", report["failures"])
            self.assertEqual(report["downstream_status"], "ADMITTED_FOR_VIDEO_SUBMIT")

    def test_advisory_and_unregistered_metric_cannot_admit_or_block(self):
        with TemporaryDirectory() as directory:
            payload = self.fixture(Path(directory))
            payload["evidence"][0]["status"] = "ADVISORY_NOT_A_GATE"
            payload["evidence"].append({"gate_id": "PELVIS-PIXEL-RATIO", "status": "FAIL"})
            report = evaluate(payload, self.registry, Path(directory))
            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(any("advisory_not_admission" in row for row in report["diagnostics"]))
            self.assertTrue(any("unregistered_gate_downgraded" in row for row in report["diagnostics"]))
            self.assertFalse(any("PELVIS-PIXEL-RATIO" in row for row in report["failures"]))

    def test_technical_pass_alone_never_admits_video(self):
        with TemporaryDirectory() as directory:
            payload = self.fixture(Path(directory), "VIDEO_ASSEMBLY")
            payload["evidence"] = []
            report = evaluate(payload, self.registry, Path(directory))
            self.assertEqual(report["status"], "FAIL")
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

    def test_precheck_blocks_missing_canonical_anchor(self):
        task = {
            "canonical_characters": ["CHAR-A", "CHAR-B"],
            "canonical_props": ["PROP-X"],
            "reference_image_sequence": [
                {"role": "character", "entity_id": "CHAR-A", "path": "a.png"},
                {"role": "prop", "entity_id": "PROP-X", "path": "x.png"},
            ],
        }
        report = precheck_submission_inputs(task)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["failure_code"], "MISSING_ANCHOR_FOR_CANONICAL_ENTITY")
        self.assertEqual(report["missing_characters"], ["CHAR-B"])

    def test_precheck_accepts_every_canonical_anchor(self):
        task = {
            "canonical_characters": ["CHAR-A"],
            "canonical_props": ["PROP-X"],
            "reference_image_sequence": [
                {"role": "character", "entity_id": "CHAR-A", "path": "a.png"},
                {"role": "prop", "entity_id": "PROP-X", "path": "x.png"},
            ],
        }
        self.assertEqual(precheck_submission_inputs(task)["status"], "PASS")

    def test_p2_within_budget_is_conditionally_admitted(self):
        with TemporaryDirectory() as directory:
            payload = self.fixture(Path(directory))
            payload["evidence"][0].update({
                "status": "FAIL_P2",
                "defect_tier": "P2",
                "p2_within_budget": True,
                "defect": "minor edge softness",
            })
            report = evaluate(payload, self.registry, Path(directory))
            self.assertEqual(report["status"], "ADMITTED_WITH_P2", report["failures"])
            self.assertEqual(len(report["p2_defect_ledger"]), 1)

    def test_retry_must_change_attributed_variable(self):
        report = validate_retry_change({
            "failure_attribution": "MISSING_REFERENCE_ANCHOR",
            "changed_variables": ["PROMPT"],
        })
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("RETRY_CHANGED_WRONG_VARIABLE", report["failures"])

    def test_same_attribution_twice_requires_switch_coverage(self):
        report = validate_retry_change({
            "failure_attribution": "PROMPT_SEMANTICS",
            "changed_variables": ["PROMPT"],
            "same_attribution_consecutive_count": 2,
        })
        self.assertIn("SWITCH_COVERAGE_REQUIRED", report["failures"])

    def test_model_stochastic_retry_keeps_input_unchanged(self):
        self.assertEqual(validate_retry_change({
            "failure_attribution": "MODEL_STOCHASTIC",
            "changed_variables": [],
        })["status"], "PASS")
        report = validate_retry_change({
            "failure_attribution": "MODEL_STOCHASTIC",
            "changed_variables": ["PROMPT"],
        })
        self.assertIn("RETRY_CHANGED_WRONG_VARIABLE", report["failures"])

    def test_canonical_mismatch_never_resubmits_media(self):
        report = validate_retry_change({
            "failure_attribution": "CANONICAL_MISMATCH",
            "changed_variables": ["QA_TARGET"],
        })
        self.assertIn("CANONICAL_MISMATCH_MEDIA_RETRY_FORBIDDEN", report["failures"])

    def test_template_defect_ignores_success_with_stale_attribution(self):
        base = {
            "global_space_map_id": "GSM-1",
            "canonical_characters": ["CHAR-A"],
            "reference_image_sequence": [
                {"role": "character", "entity_id": "CHAR-A", "path": "a.png"}
            ],
            "failure_attribution": "PROMPT_SEMANTICS",
        }
        report = aggregate_template_defects([
            {**base, "task_key": "U1", "state": "qa_pass"},
            {**base, "task_key": "U2", "state": "qa_pass"},
        ])
        self.assertEqual(report["status"], "PASS_NO_TEMPLATE_DEFECT")

    def test_template_defect_aggregates_without_serial_wait(self):
        base = {
            "global_space_map_id": "GSM-1",
            "canonical_characters": ["CHAR-A"],
            "reference_image_sequence": [
                {"role": "character", "entity_id": "CHAR-A", "path": "a.png"}
            ],
            "failure_attribution": "MISSING_REFERENCE_ANCHOR",
        }
        template_id = compute_input_template_id(base)
        report = aggregate_template_defects([
            {**base, "task_key": "U1", "input_template_id": template_id},
            {**base, "task_key": "U2", "input_template_id": template_id},
        ])
        self.assertEqual(report["status"], "TEMPLATE_DEFECT")
        self.assertFalse(report["serial_wait_introduced"])


if __name__ == "__main__":
    unittest.main()
