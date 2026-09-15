from tools.submit_giggle_image_manifest import validate_positive_single_subject_provider_scope
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.submit_giggle_image_manifest import (
    submit_all,
    submit_one,
    validate_anchor_count_gate_requirement,
    validate_mask_transport,
    validate_submission_authority,
)


class SubmitGiggleImageManifestTest(unittest.TestCase):
    def test_paid_submit_rejects_precheck_only_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "provider_post_allowed"):
                validate_submission_authority(
                    {"provider_post_allowed": False},
                    [{"task_key": "T1"}],
                    [],
                    path,
                )

    def test_paid_submit_requires_exact_budget_gate_manifest_sha(self):
        manifest = {
            "provider_post_allowed": True,
            "maximum_new_submissions": 1,
            "authorization_ref": "ROGER",
        }
        task = {
            "task_key": "T1",
            "status": "READY_TO_SUBMIT",
            "provider_post_allowed": True,
            "maximum_new_submissions": 1,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exact submission manifest SHA"):
                validate_submission_authority(
                    manifest,
                    [task],
                    [{"gate_id": "GIGGLE-REROLL-COST-GUARD", "reviewed_manifest_sha256": "wrong"}],
                    path,
                )

    def test_submit_one_rechecks_input_anchors_before_transaction_or_post(self):
        task = {
            "task_key": "MISSING-PROP",
            "prompt_file": "unused.txt",
            "canonical_props": ["PROP-REQUIRED"],
            "reference_images": [],
            "reference_bindings": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "tools.submit_giggle_image_manifest._request"
        ) as request:
            root = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "PROP-REQUIRED"):
                submit_one(task, root / "receipts", root / "transactions")
            request.assert_not_called()
            self.assertEqual(list((root / "transactions").glob("*.json")), [])

    def test_image_without_edit_mask_does_not_require_mask_transport(self):
        validate_mask_transport({"task_key": "PLAIN", "reference_bindings": []})

    def test_edit_mask_reference_cannot_claim_exact_mask_semantics(self):
        task = {
            "task_key": "MASKED",
            "reference_bindings": [{"role": "edit_mask"}],
        }
        with self.assertRaisesRegex(ValueError, "reference-only"):
            validate_mask_transport(task)

    def test_provider_native_mask_claim_fails_until_payload_support_exists(self):
        task = {
            "task_key": "MASKED",
            "reference_bindings": [{"role": "edit_mask"}],
            "mask_transport": {"mode": "provider_native"},
        }
        with self.assertRaisesRegex(ValueError, "not implemented"):
            validate_mask_transport(task)

    def test_video_unit_batch_requires_variable_anchor_gate(self):
        manifest = {"tasks": [{"video_unit_id": "E99-CW-U01"}]}
        with self.assertRaisesRegex(ValueError, "previous-final-frame-chain"):
            validate_anchor_count_gate_requirement(
                manifest,
                [{"schema": "qingshan.some_other_gate.v1", "status": "PASS"}],
            )

    def test_video_unit_batch_accepts_variable_anchor_gate(self):
        manifest = {"tasks": [{"video_unit_id": "E99-CW-U01"}]}
        validate_anchor_count_gate_requirement(
            manifest,
            [{"schema": "qingshan.video_unit_anchor_count_gate.v2_previous_final_frame_chain", "status": "PASS"}],
        )

    def test_partial_anchor_batch_requires_tracked_dependencies(self):
        gates = [{"schema": "qingshan.video_unit_anchor_count_gate.v2_previous_final_frame_chain", "status": "PASS"}]
        manifest = {
            "consumer_contract": {"planned_anchor_count": 2},
            "tasks": [{"task_key": "U01-A1", "video_unit_id": "U01"}],
            "blocked_tasks": ["U01-A2"],
        }
        with self.assertRaisesRegex(ValueError, "declare every dependent anchor"):
            validate_anchor_count_gate_requirement(manifest, gates)

        manifest["dependent_anchor_specs"] = [
            {"task_key": "U01-A2", "depends_on_task_key": "U01-A1"}
        ]
        validate_anchor_count_gate_requirement(manifest, gates)

    def test_client_system_exit_is_isolated_pending_ledger_reconciliation(self):
        tasks = [
            {"task_key": "OK", "beat_id": "B1"},
            {"task_key": "TIMEOUT", "beat_id": "B2"},
        ]

        def fake_submit(task, receipt_dir, transaction_dir):
            if task["task_key"] == "TIMEOUT":
                raise SystemExit("network timeout")
            return {"task_key": "OK", "task_id": "task-1", "status": "submitted"}

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "tools.submit_giggle_image_manifest.submit_one", side_effect=fake_submit
        ):
            root = Path(temp_dir)
            results, failures = submit_all(
                tasks,
                root / "receipts",
                root / "transactions",
                concurrency=2,
            )

        self.assertEqual([row["task_key"] for row in results], ["OK"])
        self.assertEqual(failures[0]["task_key"], "TIMEOUT")
        self.assertIsNone(failures[0]["credit"])
        self.assertEqual(failures[0]["credit_status"], "PENDING_LEDGER_RECONCILIATION")

    def test_positive_single_subject_scope_keeps_hidden_listener_machine_only(self):
        role = {
            "schema": "qingshan.role_semantic_disambiguation.v1",
            "status": "PASS",
            "shot_id": "E56-S01-01",
            "forbidden_role_swaps": True,
            "primary_actor": "陈迹",
            "primary_actor_id": "CHAR-CHENJI",
            "primary_actor_kind": "CHARACTER",
            "dialogue_speaker": "陈迹",
            "dialogue_speaker_id": "CHAR-CHENJI",
            "dialogue_listener": "姚老头",
            "dialogue_listener_id": "CHAR-YAO",
            "action_patient": "",
            "entity_states": {"CHAR-CHENJI": "speaking", "CHAR-YAO": "listening"},
            "entity_presence": {
                "CHAR-CHENJI": "VISIBLE_AND_IDENTITY_LOCKED",
                "CHAR-YAO": "OFFSCREEN_VOICE_ONLY",
            },
        }
        task = {
            "episode": "E56",
            "role_semantic_disambiguation": role,
            "provider_scope_projection": {
                "visible_character_ids": ["CHAR-CHENJI"],
                "exclusive_visible_living_entity_set": True,
                "visible_living_entity_instance_total": 1,
                "background_population_count": 0,
            },
            "prompt_contract": {"visible_character_names": ["陈迹"]},
        }
        prompt = "陈迹单人中景，盘坐在院墙前，抬头开口。"
        self.assertEqual(validate_positive_single_subject_provider_scope(task, prompt), [])

    def test_positive_single_subject_scope_rejects_hidden_role_name_leak(self):
        role = {
            "schema": "qingshan.role_semantic_disambiguation.v1",
            "status": "PASS",
            "shot_id": "E56-S01-01",
            "forbidden_role_swaps": True,
            "primary_actor": "陈迹",
            "primary_actor_id": "CHAR-CHENJI",
            "primary_actor_kind": "CHARACTER",
            "dialogue_speaker": "陈迹",
            "dialogue_speaker_id": "CHAR-CHENJI",
            "dialogue_listener": "姚老头",
            "dialogue_listener_id": "CHAR-YAO",
            "action_patient": "",
            "entity_states": {"CHAR-CHENJI": "speaking", "CHAR-YAO": "listening"},
            "entity_presence": {
                "CHAR-CHENJI": "VISIBLE_AND_IDENTITY_LOCKED",
                "CHAR-YAO": "OFFSCREEN_VOICE_ONLY",
            },
        }
        task = {
            "episode": "E56",
            "role_semantic_disambiguation": role,
            "provider_scope_projection": {
                "visible_character_ids": ["CHAR-CHENJI"],
                "exclusive_visible_living_entity_set": True,
                "visible_living_entity_instance_total": 1,
                "background_population_count": 0,
            },
            "prompt_contract": {"visible_character_names": ["陈迹"]},
        }
        prompt = "陈迹单人中景，姚老头在画外。"
        failures = validate_positive_single_subject_provider_scope(task, prompt)
        self.assertIn(
            "POSITIVE_SINGLE_SUBJECT_HIDDEN_ROLE_LEAK:dialogue_listener:姚老头",
            failures,
        )


if __name__ == "__main__":
    unittest.main()
