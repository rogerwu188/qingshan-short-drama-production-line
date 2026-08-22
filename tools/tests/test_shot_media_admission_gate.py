import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.shot_media_admission_gate import (
    KEYFRAME_REQUIRED_GATES,
    P0_OBJECTIVE_GATES,
    P0_OBJECTIVE_METHODS,
    NO_CHARACTER_IDENTITY_METHOD,
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
        self.registry = {"gates": [
            {"gate_id": value, "parameters": {
                "canonical_views_min": 3,
                "sample_frames_per_source_min": 3,
                "embedding_cosine_pass_threshold": 0.45,
            } if value == "CHARACTER-IDENTITY-ADMISSION" else {}}
            for value in VIDEO_REQUIRED_GATES
        ]}

    def fixture(self, root: Path, kind="KEYFRAME_VIDEO_SUBMIT"):
        asset = root / "asset.png"
        asset.write_bytes(b"exact-media")
        asset_sha = digest(asset)
        required = KEYFRAME_REQUIRED_GATES if kind == "KEYFRAME_VIDEO_SUBMIT" else VIDEO_REQUIRED_GATES
        evidence = []
        for index, gate_id in enumerate(required):
            report = root / f"evidence-{index}.json"
            report_payload = {"gate_id": gate_id, "status": "PASS"}
            if gate_id in P0_OBJECTIVE_GATES:
                verification = {
                    "method": P0_OBJECTIVE_METHODS[gate_id],
                    "decision": "PASS",
                    "checks": [{"question": "closed", "answer": "PASS"}],
                }
                if gate_id == "CHARACTER-IDENTITY-ADMISSION":
                    verification.update({
                        "pass_threshold": 0.45,
                        "canonical_views_min": 3,
                        "sample_frames_per_source_min": 3,
                        "decisions": [{"character_id": "CHAR-A", "decision": "PASS"}],
                    })
                report_payload["objective_verification"] = verification
            report.write_text(json.dumps(report_payload), encoding="utf-8")
            evidence.append({
                "gate_id": gate_id,
                "status": "PASS",
                "reviewed_asset_sha256": asset_sha,
                "evidence_path": str(report),
                "evidence_sha256": digest(report),
                "original_resolution_review": index == 0,
                "reviewer_type": "HUMAN_AND_AI" if gate_id in P0_OBJECTIVE_GATES else "AI_VISUAL",
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

    def test_semantic_keyframe_policy_rejects_label_only_contact_sheet(self):
        task = {
            "media_stage": "KEYFRAME",
            "require_semantic_anchor_evidence": True,
            "canonical_characters": ["CHAR-A"],
            "reference_image_sequence": [
                {"role": "character", "entity_id": "CHAR-A", "path": "contact-sheet.png"}
            ],
        }
        report = precheck_submission_inputs(task)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("SEMANTIC_ANCHOR_EVIDENCE_MISSING", report["failures"])

    def test_semantic_keyframe_policy_accepts_exact_source_and_qa(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "native.png"
            qa = root / "qa.json"
            source.write_bytes(b"native")
            qa.write_text("{}", encoding="utf-8")
            task = {
                "media_stage": "KEYFRAME",
                "require_semantic_anchor_evidence": True,
                "canonical_props": ["PROP-X"],
                "reference_image_sequence": [{
                    "role": "prop", "entity_id": "PROP-X", "path": str(source),
                    "sha256": digest(source), "qa_report": str(qa),
                    "asset_origin": "CANONICAL_PROP_REGISTRY",
                }],
            }
            self.assertEqual(precheck_submission_inputs(task, root=root)["status"], "PASS")

    def test_semantic_video_policy_requires_q1_exact_sha(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            frame = root / "frame.png"
            frame.write_bytes(b"frame")
            frame_sha = digest(frame)
            q1 = root / "q1.json"
            q1.write_text(json.dumps({
                "status": "ADMITTED", "downstream_status": "ADMITTED_FOR_VIDEO_SUBMIT",
                "asset_sha256": frame_sha,
            }), encoding="utf-8")
            task = {
                "media_stage": "VIDEO", "require_semantic_anchor_evidence": True,
                "canonical_characters": ["CHAR-A"], "exact_first_frame_sha256": frame_sha,
                "start_frame_admission_ref": str(q1),
                "reference_image_sequence": [
                    {"role": "character", "entity_id": "CHAR-A", "path": str(frame)}
                ],
            }
            self.assertEqual(precheck_submission_inputs(task, root=root)["status"], "PASS")

    def test_video_missing_semantic_policy_declaration_fails_loudly(self):
        task = {
            "media_stage": "VIDEO",
            "canonical_characters": ["CHAR-A"],
            "reference_image_sequence": [
                {"role": "character", "entity_id": "CHAR-A", "path": "frame.png"}
            ],
        }
        report = precheck_submission_inputs(task)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("SEMANTIC_ANCHOR_POLICY_NOT_DECLARED", report["failures"])
        self.assertTrue(report["semantic_anchor_policy_enforced"])

    def test_every_p0_gate_accepts_only_structured_objective_ai_evidence(self):
        for gate_id in P0_OBJECTIVE_GATES:
            with self.subTest(gate_id=gate_id), TemporaryDirectory() as directory:
                payload = self.fixture(Path(directory))
                evidence = next(row for row in payload["evidence"] if row["gate_id"] == gate_id)
                evidence["reviewer_type"] = "AI_VISUAL"
                evidence_path = Path(evidence["evidence_path"])
                verification = {
                    "method": P0_OBJECTIVE_METHODS[gate_id],
                    "decision": "PASS",
                    "checks": [{"question": "closed", "answer": "PASS"}],
                }
                if gate_id == "CHARACTER-IDENTITY-ADMISSION":
                    verification.update({
                        "pass_threshold": 0.45,
                        "canonical_views_min": 3,
                        "sample_frames_per_source_min": 3,
                        "decisions": [{"character_id": "CHAR-A", "decision": "PASS"}],
                    })
                evidence_path.write_text(json.dumps({
                    "gate_id": gate_id, "status": "PASS",
                    "objective_verification": verification,
                }), encoding="utf-8")
                evidence["evidence_sha256"] = digest(evidence_path)
                report = evaluate(payload, self.registry, Path(directory))
                self.assertEqual(report["status"], "ADMITTED", report["failures"])

    def test_p0_ai_visual_cannot_self_assert_unstructured_pass(self):
        with TemporaryDirectory() as directory:
            payload = self.fixture(Path(directory))
            evidence = next(row for row in payload["evidence"] if row["gate_id"] == "CHARACTER-IDENTITY-ADMISSION")
            evidence["reviewer_type"] = "AI_VISUAL"
            evidence_path = Path(evidence["evidence_path"])
            evidence_path.write_text(json.dumps({
                "gate_id": "CHARACTER-IDENTITY-ADMISSION",
                "status": "PASS",
            }), encoding="utf-8")
            evidence["evidence_sha256"] = digest(evidence_path)
            report = evaluate(payload, self.registry, Path(directory))
            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(any("p0_objective_method_invalid" in row for row in report["failures"]))

    def test_p0_human_and_ai_label_cannot_bypass_objective_identity_evidence(self):
        with TemporaryDirectory() as directory:
            payload = self.fixture(Path(directory))
            evidence = next(
                row for row in payload["evidence"]
                if row["gate_id"] == "CHARACTER-IDENTITY-ADMISSION"
            )
            evidence_path = Path(evidence["evidence_path"])
            evidence_path.write_text(json.dumps({
                "gate_id": "CHARACTER-IDENTITY-ADMISSION",
                "status": "PASS",
            }), encoding="utf-8")
            evidence["evidence_sha256"] = digest(evidence_path)
            report = evaluate(payload, self.registry, Path(directory))
            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(any(
                "p0_objective_method_invalid" in row for row in report["failures"]
            ))

    def test_character_free_insert_can_objectively_pass_identity_scope(self):
        with TemporaryDirectory() as directory:
            payload = self.fixture(Path(directory))
            evidence = next(
                row for row in payload["evidence"]
                if row["gate_id"] == "CHARACTER-IDENTITY-ADMISSION"
            )
            evidence["reviewer_type"] = "AI_VISUAL"
            evidence_path = Path(evidence["evidence_path"])
            evidence_path.write_text(json.dumps({
                "gate_id": "CHARACTER-IDENTITY-ADMISSION",
                "status": "PASS",
                "objective_verification": {
                    "method": NO_CHARACTER_IDENTITY_METHOD,
                    "decision": "PASS",
                    "canonical_characters": [],
                    "checks": [
                        {"question": "No human or animal character is visible", "answer": "PASS"},
                        {"question": "No extra character was generated", "answer": "PASS"},
                    ],
                },
            }), encoding="utf-8")
            evidence["evidence_sha256"] = digest(evidence_path)
            report = evaluate(payload, self.registry, Path(directory))
            self.assertEqual(report["status"], "ADMITTED", report["failures"])

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
