"""Tests for the product-facing, generic StoryClaw NALU onboarding flow."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools import storyclaw_asset_plan_gate as asset_gate
from tools import storyclaw_guided_onboarding as guide


class StoryClawGuidedOnboardingTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.base = Path(self._temporary.name).resolve()
        self.engine = self.base / "engine"
        (self.engine / "tools").mkdir(parents=True)
        self.projects = self.base / "projects"

    def start(self, **overrides):
        values = {
            "title": "Portable demo",
            "project_id": "portable-demo",
            "series_scope_id": "PORTABLE_DEMO",
        }
        values.update(overrides)
        response = guide.start_project(self.projects, self.engine, **values)
        return self.projects / values["project_id"], response

    def test_empty_project_requests_one_source_and_keeps_safe_defaults(self):
        project, response = self.start()
        self.assertEqual(response["state"], "SOURCE_REQUIRED")
        self.assertEqual(response["human_input"]["request_mode"], "ONE_SOURCE_INPUT")
        self.assertFalse(response["human_input"]["confirmation"])
        self.assertEqual(response["next_action"], {
            "id": "PROVIDE_ONE_SOURCE", "automatic": False,
        })
        self.assertEqual(set(response["message"]), {"zh-CN", "en"})
        self.assertFalse(response["defaults"]["paid_requests_enabled"])
        self.assertFalse(response["defaults"]["automatic_platform_upload_enabled"])
        self.assertEqual(response["safety"]["provider_posts_performed"], 0)
        self.assertTrue(project.is_dir())
        response = guide.add_source(project, source_text="source added after setup")
        self.assertEqual(response["state"], "SCRIPT_READY")
        with self.assertRaisesRegex(guide.OnboardingBlocked, "PRIMARY_SOURCE_ALREADY"):
            guide.add_source(project, source_text="different source")

    def test_title_is_optional_and_safe_default_does_not_block_source_only_start(self):
        response = guide.start_project(
            self.projects,
            self.engine,
            project_id="source-only",
            series_scope_id="SOURCE_ONLY",
            source_text="The user only provided a story source.",
        )
        self.assertEqual(response["state"], "SCRIPT_READY")
        marker = json.loads(
            (self.projects / "source-only/runtime/project.json").read_text()
        )
        self.assertEqual(marker["title"], "Untitled short drama")

    def test_pasted_text_is_ingested_without_echo_then_script_runs_automatically(self):
        source = "Private story text: an ordinary user pastes this into StoryClaw."
        project, response = self.start(source_text=source)
        self.assertEqual(response["state"], "SCRIPT_READY")
        self.assertEqual(response["next_action"]["id"], "RUN_S1_THEN_S2")
        self.assertTrue(response["next_action"]["automatic"])
        self.assertFalse(response["human_input"]["required"])
        self.assertNotIn(source, json.dumps(response))
        receipts = list((project / "runtime/receipts/source_intake").glob("*.json"))
        self.assertEqual(len(receipts), 1)
        receipt = json.loads(receipts[0].read_text())
        self.assertEqual(receipt["intake_kind"], "PASTED_TEXT")
        self.assertEqual(receipt["origin"]["sha256"], hashlib.sha256(source.encode()).hexdigest())

    def test_local_source_and_material_directory_are_copied_and_content_bound(self):
        source = self.base / "source.txt"
        source.write_text("A compact source outline.", encoding="utf-8")
        uploads = self.base / "uploads"
        uploads.mkdir()
        (uploads / "lead.JPG").write_bytes(b"lead-photo")
        (uploads / "room.png").write_bytes(b"room-photo")
        project, response = self.start(source_file=source, materials=[uploads])
        self.assertEqual(response["state"], "SCRIPT_READY")
        self.assertEqual(response["progress"]["material_count"], 2)
        rows = [json.loads(path.read_text()) for path in sorted(
            (project / "runtime/receipts/material_intake").glob("*.json")
        )]
        self.assertEqual(len(rows), 2)
        for row in rows:
            private_path = Path(row["private_path"])
            self.assertTrue(private_path.is_relative_to(project))
            self.assertEqual(guide._sha256_file(private_path), row["sha256"])
            self.assertEqual(row["source_kind"], "USER_UPLOAD")
            self.assertFalse(row["publication_allowed"])
        again = guide.register_materials(project, [uploads])
        self.assertEqual({row["status"] for row in again}, {"EXISTS_UNCHANGED"})

    def test_material_symlinks_and_multiple_source_forms_are_refused(self):
        source = self.base / "source.txt"
        source.write_text("source", encoding="utf-8")
        with self.assertRaisesRegex(guide.OnboardingBlocked, "EXACTLY_ONE_SOURCE"):
            self.start(source_text="text", source_file=source)
        project, _ = self.start(source_text="text")
        material = self.base / "material.png"
        material.write_bytes(b"pixels")
        symlink = self.base / "link.png"
        try:
            symlink.symlink_to(material)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaisesRegex(guide.OnboardingBlocked, "MATERIAL_SYMLINK_REFUSED"):
            guide.register_materials(project, [symlink])

    def _write_passed_script(self, project: Path):
        layer_root = project / "writer_layers/PORTABLE_DEMO/E01"
        layer_root.mkdir(parents=True, exist_ok=True)
        layers = {
            "narrative_canonical": layer_root / "narrative.md",
            "directing_script": layer_root / "directing.md",
            "generation_contract": layer_root / "contract.json",
            "writer_manifest": layer_root / "manifest.json",
        }
        layers["narrative_canonical"].write_text("narrative", encoding="utf-8")
        layers["directing_script"].write_text("directing", encoding="utf-8")
        layers["writer_manifest"].write_text("{}", encoding="utf-8")
        layers["generation_contract"].write_text(json.dumps({
            "schema": "qingshan.generation_contract.v3",
            "episode": "E01",
            "protagonist_ids": ["LEAD"],
            "character_entities": [{"character_id": "LEAD"}],
            "scene_states": [{"scene_id": "ROOM"}],
            "shots": [],
        }), encoding="utf-8")
        seq = project / "runtime/pipeline_logs/E01/seq29.json"
        seq.parent.mkdir(parents=True, exist_ok=True)
        seq.write_text(json.dumps({
            "episode": "E01", "enforced": True, "status": "PASS",
        }), encoding="utf-8")
        s1_receipt = project / "runtime/pipeline_logs/E01/S1_GATE_RECEIPT.json"
        s1_receipt.write_text(json.dumps({
            "schema": "nalu.s1_gate_receipt.v1",
            "episode": "E01",
            "series_scope_id": "PORTABLE_DEMO",
            "stage": "S1",
            "status": "PASS",
        }), encoding="utf-8")
        s2_receipt = project / "runtime/pipeline_logs/E01/S2_PREPRODUCTION_RECEIPT.json"
        s2_receipt.write_text(json.dumps({
            "schema": "nalu.s2_preproduction_receipt.v1",
            "episode": "E01",
            "series_scope_id": "PORTABLE_DEMO",
            "stage": "S2",
            "status": "PASS",
            "generation_contract_sha256": asset_gate.sha256_file(layers["generation_contract"]),
            "writer_manifest_sha256": asset_gate.sha256_file(layers["writer_manifest"]),
            "global_space_map_sha256": "1" * 64,
            "asset_requirements_sha256": "2" * 64,
            "preproduction_report_sha256": "3" * 64,
            "keyframes_included": False,
        }), encoding="utf-8")
        state_path = project / "runtime/pipeline_state/E01.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "episode": "E01",
            "series_scope": {"scope_id": "PORTABLE_DEMO"},
            "layers": {"paths": {key: str(path) for key, path in layers.items()}},
            "stages": {
                "S1": {"status": "PASS", "details": {
                    "writer_selfcheck_seq29": {"report": str(seq)},
                    "s1_gate_receipt": {"path": str(s1_receipt)},
                }},
                "S2": {"status": "PASS", "details": {
                    "s2_preproduction_receipt": {"path": str(s2_receipt)},
                }},
            },
        }
        state_path.write_text(json.dumps(state), encoding="utf-8")
        return state_path, layers, seq, s1_receipt, s2_receipt

    def _write_valid_plan(self, project: Path, layers, seq, s1_receipt, s2_receipt):
        evidence = asset_gate.build_script_evidence(
            episode="E01",
            series_scope_id="PORTABLE_DEMO",
            generation_contract_path=layers["generation_contract"],
            layer_paths=layers,
            s1_gate_evidence_path=s1_receipt,
            s2_gate_evidence_path=s2_receipt,
            seq29_report_path=seq,
            private_roots=[project],
        )
        plan = {
            "schema": asset_gate.PLAN_SCHEMA,
            "status": "PROPOSED",
            "episode": "E01",
            "series_scope_id": "PORTABLE_DEMO",
            "script_evidence": evidence,
            "script_evidence_sha256": evidence["script_evidence_sha256"],
            "script_summary": "The lead enters one room and faces a choice.",
            "assumptions": ["Vertical framing"],
            "character_matches": [],
            "scene_matches": [],
            "prop_matches": [],
            "ai_generation_proposals": [
                {
                    "entity_type": "character", "entity_id": "LEAD",
                    "model": "gpt-image-2-pro", "prompt": "lead portrait",
                    "estimated_credits": 12,
                    "rights_and_identity_note": "Synthetic protagonist proposal for private review.",
                },
                {
                    "entity_type": "scene", "entity_id": "ROOM",
                    "model": "gpt-image-2-pro", "prompt": "room reference",
                    "estimated_credits": 8,
                    "rights_and_identity_note": "Synthetic scene proposal for private review.",
                },
            ],
            "total_estimated_credits": 20,
            "risks": ["AI protagonist appearance requires the user's one-plan approval."],
            "rights_and_identity_notes": [
                "AI identity and uploaded-reference rights are included in the one-plan confirmation."
            ],
        }
        path = (
            project
            / "runtime/asset_plans/PORTABLE_DEMO/E01_ASSET_MATCH_PLAN.json"
        )
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(plan), encoding="utf-8")
        return path, evidence

    def test_only_complete_plan_requests_confirmation_and_receipt_unlocks_production(self):
        project, _ = self.start(source_text="source")
        state_path, layers, seq, s1_receipt, s2_receipt = self._write_passed_script(project)
        response = guide.guided_status(project)
        self.assertEqual(response["state"], "ASSET_PLAN_READY")
        self.assertFalse(response["human_input"]["required"])

        plan_path, evidence = self._write_valid_plan(
            project, layers, seq, s1_receipt, s2_receipt
        )
        plan_without_summary = json.loads(plan_path.read_text())
        plan_without_summary.pop("script_summary")
        plan_path.write_text(json.dumps(plan_without_summary), encoding="utf-8")
        response = guide.guided_status(project)
        self.assertEqual(response["state"], "ASSET_PLAN_BLOCKED")
        self.assertIn("HUMAN_READABLE_SCRIPT_SUMMARY_MISSING", response["failures"])
        plan_without_summary["script_summary"] = (
            "The lead enters one room and faces a choice."
        )
        plan_path.write_text(json.dumps(plan_without_summary), encoding="utf-8")
        response = guide.guided_status(project)
        self.assertEqual(response["state"], "CONFIRMATION_REQUIRED")
        self.assertTrue(response["human_input"]["confirmation"])
        self.assertEqual(
            response["human_input"]["request_mode"],
            "SINGLE_COMPLETE_PLAN_CONFIRMATION",
        )
        self.assertFalse(response["human_input"]["item_by_item_questions_allowed"])
        plan_summary = response["complete_asset_plan"]
        self.assertEqual(plan_summary["total_estimated_credits"], "20")
        self.assertEqual(len(plan_summary["ai_generation_proposals"]), 2)
        self.assertEqual(
            plan_summary["asset_plan_sha256"], asset_gate.sha256_file(plan_path)
        )

        config_path = project / "qingshan.json"
        config = json.loads(config_path.read_text())
        config["authorization"]["line_owner_id"] = "storyclaw-user-123"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        receipt_root = Path(config["authorization"]["confirmation_receipts_root"])
        receipt = receipt_root / "confirm.json"
        receipt.write_text(json.dumps({
            "schema": asset_gate.CONFIRMATION_RECEIPT_SCHEMA,
            "status": "CONFIRMED",
            "episode": "E01",
            "series_scope_id": "PORTABLE_DEMO",
            "line_owner_id": "storyclaw-user-123",
            "asset_plan_sha256": asset_gate.sha256_file(plan_path),
            "script_evidence_sha256": evidence["script_evidence_sha256"],
            "verbatim": "I confirm this complete script and asset plan.",
            "message_or_event_id": "event-123",
            "confirmed_at_utc": "2026-09-20T12:00:00Z",
        }), encoding="utf-8")
        sidecar = (
            project
            / "runtime/asset_plans/PORTABLE_DEMO/E01_ASSET_MATCH_CONFIRMATION.json"
        )
        sidecar.write_text(json.dumps({
            "receipt_path": str(receipt),
            "receipt_sha256": asset_gate.sha256_file(receipt),
        }), encoding="utf-8")
        response = guide.guided_status(project)
        self.assertEqual(response["state"], "PRODUCTION_READY", response)
        self.assertFalse(response["human_input"]["required"])
        self.assertEqual(response["safety"]["provider_posts_performed"], 0)

        # Advancing the mutable pipeline state must not invalidate a plan that
        # binds the dedicated immutable S1 receipt.
        state = json.loads(state_path.read_text())
        state["stages"]["S3"] = {"status": "PASS"}
        state_path.write_text(json.dumps(state), encoding="utf-8")
        response = guide.guided_status(project)
        self.assertEqual(response["state"], "PRODUCTION_IN_PROGRESS", response)

        receipt.write_text(receipt.read_text() + "\n", encoding="utf-8")
        response = guide.guided_status(project)
        self.assertEqual(response["state"], "CONFIRMATION_REQUIRED")
        self.assertIn("RECEIPT_SHA256_MISMATCH", response["failures"])

    def test_wrong_scope_and_corrupt_private_receipts_fail_closed(self):
        project, _ = self.start(source_text="source")
        state_path, _layers, _seq, _s1_receipt, _s2_receipt = self._write_passed_script(project)
        state = json.loads(state_path.read_text())
        state["series_scope"]["scope_id"] = "ANOTHER_PROJECT"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        response = guide.guided_status(project)
        self.assertEqual(response["state"], "PROJECT_BLOCKED")
        self.assertTrue(any("PIPELINE_SCOPE_MISMATCH" in value for value in response["failures"]))

        state_path.unlink()
        receipt = next((project / "runtime/receipts/source_intake").glob("*.json"))
        receipt.write_text("{not-json", encoding="utf-8")
        response = guide.guided_status(project)
        self.assertEqual(response["state"], "PROJECT_BLOCKED")
        self.assertTrue(any("JSON_INVALID" in value for value in response["failures"]))

    def test_cli_accepts_pasted_text_on_stdin_without_argv_leak(self):
        script = Path(guide.__file__)
        private_text = "stdin private source"
        result = subprocess.run(
            [
                sys.executable, str(script), "start",
                "--projects-root", str(self.projects),
                "--engine-root", str(self.engine),
                "--title", "CLI project",
                "--project-id", "cli-project",
                "--scope-id", "CLI_PROJECT",
                "--source-text-file", "-",
            ],
            input=private_text,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response["state"], "SCRIPT_READY")
        self.assertNotIn(private_text, result.stdout)


if __name__ == "__main__":
    unittest.main()
