import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools import storyclaw_asset_plan_gate as gate


class StoryClawAssetPlanGateTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.private = Path(self._temp.name).resolve() / "private"
        self.private.mkdir()
        self.layers_dir = self.private / "writer_layers/TEST/E01"
        self.layers_dir.mkdir(parents=True)
        self.contract = self.layers_dir / "E01_GENERATION_CONTRACT_v1.json"
        self.contract.write_text(json.dumps({
            "schema": "qingshan.generation_contract.v3",
            "episode": "E01",
            "protagonist_ids": ["CHAR-LEAD"],
            "character_entities": [
                {"character_id": "CHAR-LEAD", "canonical_name": "主角", "aliases": []},
                {"character_id": "CHAR-ALLY", "canonical_name": "同伴", "aliases": []},
            ],
            "scene_states": [
                {"scene_id": "SCENE-A", "location_id": "LOC-A"},
                {"scene_id": "SCENE-B", "location_id": "LOC-B"},
            ],
            "shots": [
                {"shot_id": "E01-S01-01", "scene_id": "SCENE-A", "prompt_spec": {
                    "props": [{"prop_id": "PROP-SWORD"}],
                }},
                {"shot_id": "E01-S02-01", "scene_id": "SCENE-B", "prompt_spec": {
                    "props": [{"entity_id": "PROP-BOOK"}, {"prop_id": "PROP-SWORD"}],
                }},
            ],
        }), encoding="utf-8")
        self.layers = {
            "narrative_canonical": self.layers_dir / "E01_NARRATIVE_CANONICAL_v1.md",
            "directing_script": self.layers_dir / "E01_DIRECTING_SCRIPT_v1.md",
            "generation_contract": self.contract,
            "writer_manifest": self.layers_dir / "E01_manifest_v1.json",
        }
        self.layers["narrative_canonical"].write_text("narrative", encoding="utf-8")
        self.layers["directing_script"].write_text("directing", encoding="utf-8")
        self.layers["writer_manifest"].write_text("{}", encoding="utf-8")
        self.s1 = self.private / "pipeline_state/E01.json"
        self.s1.parent.mkdir(parents=True)
        self.s1.write_text(json.dumps({
            "episode": "E01",
            "series_scope": {"scope_id": "TEST"},
            "stages": {"S1": {"status": "PASS"}},
        }), encoding="utf-8")
        self.seq29 = self.private / "pipeline_logs/E01/seq29.json"
        self.seq29.parent.mkdir(parents=True)
        self.seq29.write_text(json.dumps({
            "schema": "nalu.writer_selfcheck_seq29.v1",
            "episode": "E01",
            "enforced": True,
            "status": "PASS",
        }), encoding="utf-8")
        self.s2 = self.private / "pipeline_logs/E01/S2_PREPRODUCTION_RECEIPT.json"
        self.s2.write_text(json.dumps({
            "schema": "nalu.s2_preproduction_receipt.v1",
            "episode": "E01",
            "series_scope_id": "TEST",
            "stage": "S2",
            "status": "PASS",
            "generation_contract_sha256": gate.sha256_file(self.contract),
            "writer_manifest_sha256": gate.sha256_file(self.layers["writer_manifest"]),
            "global_space_map_sha256": "1" * 64,
            "asset_requirements_sha256": "2" * 64,
            "preproduction_report_sha256": "3" * 64,
            "keyframes_included": False,
        }), encoding="utf-8")
        self.assets = self.private / "assets"
        self.assets.mkdir()
        for name in ("lead.jpg", "scene-a.jpg", "sword.jpg"):
            (self.assets / name).write_bytes(("bytes-" + name).encode())
        self.evidence = self._evidence()
        self.plan_path = self.private / "asset_plans/E01_ASSET_MATCH_PLAN.json"
        self.plan_path.parent.mkdir()
        self.plan = self._valid_plan()
        self._write_plan()

    def _evidence(self):
        return gate.build_script_evidence(
            episode="E01",
            series_scope_id="TEST",
            generation_contract_path=self.contract,
            layer_paths=self.layers,
            s1_gate_evidence_path=self.s1,
            s2_gate_evidence_path=self.s2,
            seq29_report_path=self.seq29,
            private_roots=[self.private],
        )

    def _match(self, entity_type, entity_id, filename, **extra):
        path = self.assets / filename
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "source_path": str(path),
            "source_sha256": gate.sha256_file(path),
            "rights_basis": "USER_CONFIRMED_PRIVATE_PROJECT_USE",
            **extra,
        }

    def _valid_plan(self):
        proposals = [
            {"entity_type": "character", "entity_id": "CHAR-ALLY", "model": "gpt-image-2-pro", "prompt": "ally portrait", "estimated_credits": 11, "rights_and_identity_note": "Synthetic character proposal; confirm identity and use rights."},
            {"entity_type": "scene", "entity_id": "SCENE-B", "model": "gpt-image-2-pro", "prompt": "scene B", "estimated_credits": 12.5, "rights_and_identity_note": "Synthetic scene proposal for this private project."},
            {"entity_type": "prop", "entity_id": "PROP-BOOK", "model": "gpt-image-2-pro", "prompt": "book reference", "estimated_credits": "3.5", "rights_and_identity_note": "Synthetic prop proposal for this private project."},
        ]
        return {
            "schema": gate.PLAN_SCHEMA,
            "status": "PROPOSED",
            "episode": "E01",
            "series_scope_id": "TEST",
            "script_evidence": self.evidence,
            "script_evidence_sha256": self.evidence["script_evidence_sha256"],
            "script_summary": "The lead and ally move through two scenes.",
            "assumptions": [],
            "risks": [],
            "rights_and_identity_notes": [
                "Uploaded references require the user's right to use them; AI proposals remain private until separately released."
            ],
            "character_matches": [self._match(
                "character", "CHAR-LEAD", "lead.jpg",
                media_kind="photo", source_kind="USER_UPLOAD",
            )],
            "scene_matches": [self._match("scene", "SCENE-A", "scene-a.jpg")],
            "prop_matches": [self._match("prop", "PROP-SWORD", "sword.jpg")],
            "ai_generation_proposals": proposals,
            "total_estimated_credits": 27,
        }

    def _write_plan(self):
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")

    def _plan_kwargs(self):
        return {
            "episode": "E01",
            "series_scope_id": "TEST",
            "generation_contract_path": self.contract,
            "layer_paths": self.layers,
            "s1_gate_evidence_path": self.s1,
            "s2_gate_evidence_path": self.s2,
            "seq29_report_path": self.seq29,
            "private_roots": [self.private],
            "allowed_models": {"gpt-image-2-pro"},
        }

    def test_complete_plan_passes_and_extracts_all_script_entities(self):
        report = gate.validate_asset_plan(self.plan_path, **self._plan_kwargs())
        self.assertEqual(report["status"], "PASS", report)
        self.assertEqual(report["required_entities"]["character"], ["CHAR-ALLY", "CHAR-LEAD"])
        self.assertEqual(report["required_entities"]["scene"], ["SCENE-A", "SCENE-B"])
        self.assertEqual(report["required_entities"]["prop"], ["PROP-BOOK", "PROP-SWORD"])
        self.assertEqual(report["total_estimated_credits"], "27.0")

    def test_empty_plan_cannot_pass(self):
        self.plan.update({
            "character_matches": [], "scene_matches": [], "prop_matches": [],
            "ai_generation_proposals": [], "total_estimated_credits": 0,
        })
        self._write_plan()
        report = gate.validate_asset_plan(self.plan_path, **self._plan_kwargs())
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("REQUIRED_ENTITY_UNCOVERED:character:CHAR-LEAD", report["failures"])
        self.assertIn("REQUIRED_ENTITY_UNCOVERED:scene:SCENE-A", report["failures"])
        self.assertIn("REQUIRED_ENTITY_UNCOVERED:prop:PROP-SWORD", report["failures"])

    def test_every_match_list_is_required_even_when_ai_covers_items(self):
        self.plan.pop("scene_matches")
        self._write_plan()
        report = gate.validate_asset_plan(self.plan_path, **self._plan_kwargs())
        self.assertIn("MATCH_LIST_MISSING:scene_matches", report["failures"])

    def test_matched_asset_must_be_private_real_and_sha_bound(self):
        outside = Path(self._temp.name) / "outside.jpg"
        outside.write_bytes(b"outside")
        row = self.plan["scene_matches"][0]
        row["source_path"] = str(outside.resolve())
        row["source_sha256"] = "0" * 64
        self._write_plan()
        report = gate.validate_asset_plan(self.plan_path, **self._plan_kwargs())
        self.assertIn("MATCH_SOURCE_NOT_PRIVATE:scene:SCENE-A", report["failures"])
        self.assertIn("MATCH_SOURCE_SHA256_MISMATCH:scene:SCENE-A", report["failures"])

    def test_ai_proposal_requires_allowed_model_prompt_and_numeric_cost(self):
        row = self.plan["ai_generation_proposals"][0]
        row["model"] = "unapproved-model"
        row["prompt"] = ""
        row["estimated_credits"] = True
        self.plan["total_estimated_credits"] = 16
        self._write_plan()
        report = gate.validate_asset_plan(self.plan_path, **self._plan_kwargs())
        self.assertIn("AI_PROPOSAL_MODEL_NOT_ALLOWED:character:CHAR-ALLY", report["failures"])
        self.assertIn("AI_PROPOSAL_PROMPT_MISSING:character:CHAR-ALLY", report["failures"])
        self.assertIn("AI_PROPOSAL_ESTIMATED_CREDITS_INVALID:character:CHAR-ALLY", report["failures"])

    def test_protagonist_needs_user_uploaded_photo_or_explicit_ai_plan(self):
        self.plan["character_matches"][0]["source_kind"] = "LIBRARY_MATCH"
        self._write_plan()
        report = gate.validate_asset_plan(self.plan_path, **self._plan_kwargs())
        self.assertIn("PROTAGONIST_REQUIRES_USER_PHOTO_OR_AI:CHAR-LEAD", report["failures"])

        self.plan["character_matches"] = []
        self.plan["ai_generation_proposals"].append({
            "entity_type": "character", "entity_id": "CHAR-LEAD",
            "model": "gpt-image-2-pro", "prompt": "create lead portrait",
            "estimated_credits": 11,
            "rights_and_identity_note": "Synthetic protagonist; user must approve identity and use rights.",
        })
        self.plan["total_estimated_credits"] = 38
        self._write_plan()
        self.assertEqual(
            gate.validate_asset_plan(self.plan_path, **self._plan_kwargs())["status"],
            "PASS",
        )

    def test_total_cost_must_equal_exact_proposal_sum(self):
        self.plan["total_estimated_credits"] = 26.99
        self._write_plan()
        report = gate.validate_asset_plan(self.plan_path, **self._plan_kwargs())
        self.assertIn("TOTAL_ESTIMATED_CREDITS_MISMATCH", report["failures"])

    def test_duplicate_match_and_ai_proposal_is_ambiguous(self):
        self.plan["ai_generation_proposals"].append({
            "entity_type": "scene", "entity_id": "SCENE-A",
            "model": "gpt-image-2-pro", "prompt": "duplicate", "estimated_credits": 1,
            "rights_and_identity_note": "Synthetic scene proposal.",
        })
        self.plan["total_estimated_credits"] = 28
        self._write_plan()
        report = gate.validate_asset_plan(self.plan_path, **self._plan_kwargs())
        self.assertIn("REQUIRED_ENTITY_AMBIGUOUS:scene:SCENE-A", report["failures"])

    def test_any_writer_layer_change_invalidates_plan(self):
        self.layers["directing_script"].write_text("changed", encoding="utf-8")
        report = gate.validate_asset_plan(self.plan_path, **self._plan_kwargs())
        self.assertIn("SCRIPT_EVIDENCE_BINDING_MISMATCH", report["failures"])
        self.assertIn("SCRIPT_EVIDENCE_SHA256_MISMATCH", report["failures"])

    def test_s1_and_seq29_must_be_real_current_pass_evidence(self):
        s1 = json.loads(self.s1.read_text())
        s1["series_scope"]["scope_id"] = "OTHER"
        self.s1.write_text(json.dumps(s1), encoding="utf-8")
        seq29 = json.loads(self.seq29.read_text())
        seq29["enforced"] = False
        self.seq29.write_text(json.dumps(seq29), encoding="utf-8")
        report = gate.validate_asset_plan(self.plan_path, **self._plan_kwargs())
        self.assertIn("S1_EVIDENCE_SCOPE_MISMATCH", report["failures"])
        self.assertIn("SEQ29_REPORT_NOT_ENFORCED", report["failures"])

    def test_s2_free_preproduction_receipt_is_required_and_script_bound(self):
        s2 = json.loads(self.s2.read_text())
        s2["status"] = "BLOCKED"
        s2["generation_contract_sha256"] = "0" * 64
        self.s2.write_text(json.dumps(s2), encoding="utf-8")
        report = gate.validate_asset_plan(self.plan_path, **self._plan_kwargs())
        self.assertIn("S2_EVIDENCE_NOT_PASS", report["failures"])
        self.assertIn("S2_CONTRACT_SHA256_MISMATCH", report["failures"])

    def _receipt(self):
        report = gate.require_valid_asset_plan(self.plan_path, **self._plan_kwargs())
        return {
            "schema": gate.CONFIRMATION_RECEIPT_SCHEMA,
            "status": "CONFIRMED",
            "episode": "E01",
            "series_scope_id": "TEST",
            "line_owner_id": "owner-1",
            "verbatim": "确认整套素材方案并按预算执行。",
            "message_or_event_id": "storyclaw-message-123",
            "asset_plan_sha256": report["asset_plan_sha256"],
            "script_evidence_sha256": report["script_evidence_sha256"],
            "confirmed_at_utc": "2026-09-20T12:00:00Z",
        }

    def _receipt_kwargs(self, receipt_path, receipt_sha):
        return {
            "receipt_root": self.private / "receipts",
            "expected_receipt_sha256": receipt_sha,
            "expected_line_owner_id": "owner-1",
            "plan_path": self.plan_path,
            **self._plan_kwargs(),
        }

    def test_private_sha_bound_line_owner_receipt_passes(self):
        root = self.private / "receipts"
        root.mkdir()
        receipt = root / "confirm.json"
        receipt.write_text(json.dumps(self._receipt()), encoding="utf-8")
        report = gate.validate_confirmation_receipt(
            receipt, **self._receipt_kwargs(receipt, gate.sha256_file(receipt))
        )
        self.assertEqual(report["status"], "PASS", report)

    def test_receipt_outside_configured_root_and_wrong_sha_are_rejected(self):
        (self.private / "receipts").mkdir()
        receipt = self.private / "elsewhere.json"
        receipt.write_text(json.dumps(self._receipt()), encoding="utf-8")
        report = gate.validate_confirmation_receipt(
            receipt, **self._receipt_kwargs(receipt, "0" * 64)
        )
        self.assertIn("RECEIPT_OUTSIDE_CONFIGURED_ROOT", report["failures"])
        self.assertIn("RECEIPT_SHA256_MISMATCH", report["failures"])

    def test_configured_receipt_root_must_itself_be_private(self):
        outside_root = Path(self._temp.name) / "outside-receipts"
        outside_root.mkdir()
        receipt = outside_root / "confirm.json"
        receipt.write_text(json.dumps(self._receipt()), encoding="utf-8")
        kwargs = self._receipt_kwargs(receipt, gate.sha256_file(receipt))
        kwargs["receipt_root"] = outside_root.resolve()
        report = gate.validate_confirmation_receipt(receipt.resolve(), **kwargs)
        self.assertIn("RECEIPT_ROOT_NOT_PRIVATE", report["failures"])

    def test_arbitrary_confirmation_json_is_rejected(self):
        root = self.private / "receipts"
        root.mkdir()
        receipt = root / "fake.json"
        receipt.write_text(json.dumps({"status": "CONFIRMED"}), encoding="utf-8")
        report = gate.validate_confirmation_receipt(
            receipt, **self._receipt_kwargs(receipt, gate.sha256_file(receipt))
        )
        self.assertIn("RECEIPT_FIELD_MISMATCH:schema", report["failures"])
        self.assertIn("RECEIPT_FIELD_MISMATCH:line_owner_id", report["failures"])
        self.assertIn("RECEIPT_VERBATIM_MISSING", report["failures"])
        self.assertIn("RECEIPT_MESSAGE_OR_EVENT_ID_MISSING", report["failures"])
        self.assertIn("RECEIPT_CONFIRMED_AT_UTC_INVALID", report["failures"])

    def test_script_change_after_confirmation_invalidates_receipt(self):
        root = self.private / "receipts"
        root.mkdir()
        receipt = root / "confirm.json"
        receipt.write_text(json.dumps(self._receipt()), encoding="utf-8")
        receipt_sha = gate.sha256_file(receipt)
        self.layers["narrative_canonical"].write_text("changed", encoding="utf-8")
        report = gate.validate_confirmation_receipt(
            receipt, **self._receipt_kwargs(receipt, receipt_sha)
        )
        self.assertEqual(report["status"], "BLOCKED")
        self.assertTrue(any(
            value.startswith("ASSET_PLAN_NOT_VALID:SCRIPT_EVIDENCE_")
            for value in report["failures"]
        ))


if __name__ == "__main__":
    unittest.main()
