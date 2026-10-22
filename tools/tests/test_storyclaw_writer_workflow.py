"""Generic private-source -> provenance-bound writer handoff tests."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import storyclaw_project_intake as intake
from tools import storyclaw_writer_workflow as writer
from tools.tests.test_writer_production_field_gate import valid_contract


ROOT = Path(__file__).resolve().parents[2]


def _replace_episode(value, old="E99", new="E01"):
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [_replace_episode(item, old, new) for item in value]
    if isinstance(value, dict):
        return {
            _replace_episode(key, old, new) if isinstance(key, str) else key:
            _replace_episode(item, old, new)
            for key, item in value.items()
        }
    return value


class StoryClawWriterWorkflowTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.base = Path(self._temporary.name).resolve()
        self.projects = self.base / "projects"
        intake.initialize_project(
            self.projects,
            ROOT,
            title="Portable fixture",
            project_id="portable-fixture",
            series_scope_id="PORTABLE_FIXTURE",
            episodes=["E01"],
        )
        self.project = self.projects / "portable-fixture"
        self.private_source = "private source fixture; not a production story"
        intake.intake_pasted_text(self.project, self.private_source)

    def begin(self, *, version=1, model="storyclaw/gpt-6-astra"):
        with patch.dict(os.environ, {"STORYCLAW_MODEL": model}):
            return writer.begin_writer_run(
                self.project,
                "E01",
                version,
                session_or_task_id=f"storyclaw-task-{version}",
            )

    def _write_outputs(self, task):
        outputs = {key: Path(value) for key, value in task["outputs"].items()}
        outputs["narrative_canonical"].write_text(
            "Private narrative fixture.\n", encoding="utf-8"
        )
        outputs["directing_script"].write_text(
            "Private directing fixture.\n", encoding="utf-8"
        )
        contract = _replace_episode(valid_contract())
        contract["schema"] = "qingshan.generation_contract.v3"
        contract["episode"] = "E01"
        contract["writer_selfcheck_seq29"] = {
            "enforced": True,
            "rule8_authorized": False,
        }
        contract["character_entities"] = [{
            "character_id": "CHAR-LEAD",
            "canonical_name": "Lead",
            "aliases": ["Lead alias"],
        }]
        shot = contract["shots"][0]
        shot["prompt_spec"]["cast"][0]["character"] = "Lead"
        shot["prompt_spec"]["cast"][0]["character_id"] = "CHAR-LEAD"
        shot["prompt_spec"]["action"]["subject_id"] = "CHAR-LEAD"
        actor_performance = shot["prompt_spec"]["performance"]["actor_performance"]
        actor_performance["Lead"] = actor_performance.pop("行人")
        role = shot["prompt_spec"]["role_semantic_disambiguation"]
        role["primary_actor"] = "Lead"
        role["primary_actor_id"] = "CHAR-LEAD"
        role["entity_states"] = {"CHAR-LEAD": "moving then stopped"}
        role["entity_presence"] = {"CHAR-LEAD": "VISIBLE_AND_IDENTITY_LOCKED"}
        outputs["generation_contract"].write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        version = task["version"]
        manifest = {
            "episode": "E01",
            "version": f"v{version}",
            "canonical_script": str(outputs["narrative_canonical"]),
            "script_sha256": "0" * 64,
            "supersedes": "none" if version == 1 else f"v{version - 1}",
            "★supersedes_disclosure": "Initial private version for workflow verification."
            if version == 1 else "Private revision with a new immutable writer run.",
            "source_binding": {
                "primary_source_chapter": "private-intake-selection",
                "beat_count": 1,
                "beats_landed": 1,
                "beats_merged": 0,
                "beats_dropped": 0,
            },
            "beat_disposition": [{
                "event_id": "E01-EV-01",
                "disposition": "landed",
                "landed_at": "E01-S01 (one shot)",
                "summary": "Private source beat selected by the writer.",
            }],
            "★authorized_insertions": [],
            "★audience_already_knows": [],
            "structure": [{
                "beat_id": "E01-B01",
                "scene_id": "E01-S01",
                "target_seconds": 4,
                "thread": "A",
                "location_id": "LOC-1",
            }],
            "scene_breakdown_seconds": {"E01-S01": 4},
            "total_seconds": 4,
            "runtime_target_seconds": {"min": 4, "target": 4, "max": 4},
            "key_quote_landing": [],
            "fs1": {},
            "identity_registry": {},
            "new_name_budget": {},
            "distinct_locations": ["LOC-1"],
            "new_locations": ["LOC-1"],
            "episode_global_space_map_id": "EGSM-E01",
            "onscreen_text_shot_level_registry": [],
        }
        outputs["writer_manifest"].write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        outputs["lexicon_draft"].write_text(json.dumps({
            "schema": writer.LEXICON_DRAFT_SCHEMA,
            "world_basis": "Derived only from the current private script setting.",
            "forbidden_terms_basis": "No setting-specific forbidden terms in this fixture.",
            "forbidden_terms": [],
            "address_terms": {"CHAR-LEAD": {"self": "Lead"}},
        }, indent=2) + "\n", encoding="utf-8")
        return outputs

    def finalize(self, task):
        self._write_outputs(task)
        with patch.dict(os.environ, {"STORYCLAW_MODEL": task["model_id"]}):
            return writer.finalize_writer_run(
                self.project,
                "E01",
                task["version"],
                writer_run_id=task["writer_run_id"],
            )

    def test_begin_binds_real_model_private_source_and_exact_output_paths(self):
        task = self.begin()
        self.assertEqual(task["status"], "AUTHORING_REQUIRED")
        self.assertEqual(task["model_id"], "storyclaw/gpt-6-astra")
        bundle_path = Path(task["input_bundle"])
        self.assertTrue(bundle_path.is_relative_to(self.project))
        bundle = json.loads(bundle_path.read_text())
        self.assertEqual(bundle["agent_id"], "ai-drama-factory")
        self.assertEqual(bundle["provider"], "storyclaw")
        self.assertEqual(bundle["source_receipts"][0]["artifacts"][0]["sha256"],
                         intake.sha256_bytes(self.private_source.encode()))
        self.assertNotIn(self.private_source, bundle_path.read_text())
        for output in task["outputs"].values():
            self.assertTrue(Path(output).is_relative_to(self.project))

    def test_finalize_seals_full_provenance_and_derives_project_lexicon(self):
        task = self.begin()
        active = self.finalize(task)
        self.assertEqual(active["status"], "SEALED")
        report = writer.verify_writer_handoff(self.project, "E01")
        self.assertEqual(report["status"], "PASS", report)
        manifest = json.loads(Path(active["layers"]["writer_manifest"]["path"]).read_text())
        provenance = manifest["writer_provenance"]
        self.assertEqual(provenance["agent_id"], "ai-drama-factory")
        self.assertEqual(provenance["provider"], "storyclaw")
        self.assertEqual(provenance["model_id"], "storyclaw/gpt-6-astra")
        lexicon = json.loads(Path(active["project_lexicon"]["path"]).read_text())
        self.assertIn("_PROJECT_LEXICON_v1.json", active["project_lexicon"]["path"])
        self.assertTrue(Path(active["project_lexicon"]["path"]).is_relative_to(self.project))
        self.assertEqual(lexicon["status"], "SCRIPT_DERIVED")
        self.assertEqual(lexicon["world"], "PORTABLE_FIXTURE")
        self.assertEqual(lexicon["canonical_names"], {"Lead": ["Lead alias"]})
        self.assertTrue(lexicon["emotions"])
        self.assertEqual(
            lexicon["derivation"]["writer_manifest_sha256"],
            active["layers"]["writer_manifest"]["sha256"],
        )

    def test_layer_drift_after_seal_is_blocked(self):
        active = self.finalize(self.begin())
        narrative = Path(active["layers"]["narrative_canonical"]["path"])
        narrative.write_text(narrative.read_text() + "drift\n", encoding="utf-8")
        report = writer.verify_writer_handoff(self.project, "E01")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertTrue(any("SHA_MISMATCH" in value for value in report["failures"]))

    def test_source_receipt_drift_after_begin_blocks_finalize(self):
        task = self.begin()
        bundle = json.loads(Path(task["input_bundle"]).read_text())
        receipt_path = Path(bundle["source_receipts"][0]["receipt_path"])
        receipt = json.loads(receipt_path.read_text())
        receipt["post_begin_mutation"] = True
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        self._write_outputs(task)
        with patch.dict(os.environ, {"STORYCLAW_MODEL": task["model_id"]}):
            with self.assertRaisesRegex(
                writer.WriterWorkflowBlocked, "SOURCE_RECEIPT_DRIFT"
            ):
                writer.finalize_writer_run(
                    self.project, "E01", task["version"],
                    writer_run_id=task["writer_run_id"],
                )

    def test_model_switch_after_begin_blocks_finalize(self):
        task = self.begin(model="storyclaw/gpt-6-astra")
        self._write_outputs(task)
        with patch.dict(os.environ, {"STORYCLAW_MODEL": "storyclaw/claude-opus-5"}):
            with self.assertRaisesRegex(
                writer.WriterWorkflowBlocked, "MODEL_CHANGED_DURING_WRITER_RUN"
            ):
                writer.finalize_writer_run(
                    self.project, "E01", task["version"],
                    writer_run_id=task["writer_run_id"],
                )

    def test_new_version_is_selected_without_overwriting_sealed_v1(self):
        first = self.finalize(self.begin(version=1))
        first_manifest = Path(first["layers"]["writer_manifest"]["path"])
        first_bytes = first_manifest.read_bytes()
        first_lexicon = Path(first["project_lexicon"]["path"])
        first_lexicon_bytes = first_lexicon.read_bytes()
        second = self.finalize(self.begin(version=2))
        selected = writer.resolve_active_layers(self.project, "PORTABLE_FIXTURE", "E01")
        self.assertIn("_v2", selected["writer_manifest"].name)
        self.assertIn("_v2", selected["project_lexicon"].name)
        self.assertEqual(first_bytes, first_manifest.read_bytes())
        self.assertEqual(first_lexicon_bytes, first_lexicon.read_bytes())
        self.assertEqual(second["version"], 2)

    def test_lower_version_finalize_cannot_replace_latest_lexicon(self):
        first_task = self.begin(version=1)
        second = self.finalize(self.begin(version=2))
        latest_mirror = self.project / "runtime/series/PORTABLE_FIXTURE/lexicon.json"
        latest_bytes = latest_mirror.read_bytes()
        self._write_outputs(first_task)
        with patch.dict(os.environ, {"STORYCLAW_MODEL": first_task["model_id"]}):
            with self.assertRaisesRegex(
                writer.WriterWorkflowBlocked, "VERSION_NOT_MONOTONIC"
            ):
                writer.finalize_writer_run(
                    self.project, "E01", 1,
                    writer_run_id=first_task["writer_run_id"],
                )
        self.assertEqual(latest_bytes, latest_mirror.read_bytes())
        self.assertEqual(
            writer.resolve_active_layers(
                self.project, "PORTABLE_FIXTURE", "E01"
            )["project_lexicon"],
            Path(second["project_lexicon"]["path"]),
        )

    def test_unapproved_or_missing_host_model_is_rejected(self):
        with self.assertRaisesRegex(writer.WriterWorkflowBlocked, "MODEL_NOT_ALLOWED"):
            self.begin(model="storyclaw/kimi-2.7")
        result = subprocess.run(
            [
                sys.executable, str(ROOT / "tools/storyclaw_writer_workflow.py"),
                "begin", "--project-root", str(self.project), "--episode", "E01",
                "--session-or-task-id", "storyclaw-task-cli",
            ],
            cwd=ROOT,
            env={key: value for key, value in os.environ.items() if key != "STORYCLAW_MODEL"},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("STORYCLAW_MODEL_HOST_EVIDENCE_REQUIRED", result.stderr)


OWNER_RIGHTS_QUOTE = "支持直接从原著改编成短剧剧本并且制作，版权线下已经谈好了，与你无关"


class CodexWriterWorkflowTests(StoryClawWriterWorkflowTests):
    """Line owner 2026-10-22: Codex authors every layer; the agent only dispatches."""

    def setUp(self):
        super().setUp()
        # A real-novel adaptation recorded with the owner's verbatim rights basis.
        intake.intake_pasted_text(self.project, "adapted novel chapter fixture",
                                  rights_statement=OWNER_RIGHTS_QUOTE)

    def _no_storyclaw_env(self, **extra):
        env = {key: value for key, value in os.environ.items()
               if key not in {"STORYCLAW_MODEL", "STORYCLAW_TASK_ID", "WRITER_AUTHOR", "CODEX_MODEL"}}
        env.update(extra)
        return patch.dict(os.environ, env, clear=True)

    def test_codex_round_trip_records_codex_provenance_and_passes_s1_verify(self):
        with self._no_storyclaw_env(CODEX_MODEL="gpt-6.1-sol", STORYCLAW_TASK_ID="sc-task-42"):
            task = writer.begin_writer_run(self.project, "E01", 1, writer="codex")
            self.assertIn("-CODEX-", task["writer_run_id"])
            self.assertEqual(task["provider"], "codex")
            self.assertEqual(task["dispatch_task_id"], "sc-task-42")
            self._write_outputs(task)
            active = writer.finalize_writer_run(
                self.project, "E01", 1, writer_run_id=task["writer_run_id"]
            )
            report = writer.verify_writer_handoff(self.project, "E01")
        self.assertEqual(report["status"], "PASS", report)
        self.assertEqual(active["provider"], "codex")
        self.assertEqual(active["writer_author"], "codex")
        self.assertEqual(active["dispatch_task_id"], "sc-task-42")
        provenance = json.loads(
            Path(active["layers"]["writer_manifest"]["path"]).read_text()
        )["writer_provenance"]
        self.assertEqual(provenance["provider"], "codex")
        self.assertEqual(provenance["model_id"], "gpt-6.1-sol")
        bundle = json.loads(Path(active["input_bundle"]["path"]).read_text())
        statements = {row["receipt_path"]: json.loads(Path(row["receipt_path"]).read_text())
                      .get("rights_statement") for row in bundle["source_receipts"]}
        self.assertIn(OWNER_RIGHTS_QUOTE, statements.values())

    def test_codex_cli_runs_without_any_storyclaw_input(self):
        env = {key: value for key, value in os.environ.items()
               if key not in {"STORYCLAW_MODEL", "STORYCLAW_TASK_ID"}}
        env["CODEX_MODEL"] = "gpt-6.1-sol"
        tool = str(ROOT / "tools/storyclaw_writer_workflow.py")
        begun = subprocess.run(
            [sys.executable, tool, "begin", "--project-root", str(self.project),
             "--episode", "E01", "--writer", "codex"],
            cwd=ROOT, env=env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(begun.returncode, 0, begun.stderr)
        task = json.loads(begun.stdout)
        self._write_outputs(task)
        finished = subprocess.run(
            [sys.executable, tool, "finalize", "--project-root", str(self.project),
             "--episode", "E01", "--version", "1", "--writer-run-id", task["writer_run_id"]],
            cwd=ROOT, env=env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(finished.returncode, 0, finished.stderr)
        self.assertEqual(json.loads(finished.stdout)["verification"]["status"], "PASS")
        self.assertIsNone(task["dispatch_task_id"])

    def test_codex_generic_or_missing_model_is_rejected(self):
        with self._no_storyclaw_env():
            with self.assertRaisesRegex(writer.WriterWorkflowBlocked, "CODEX_WRITER_MODEL"):
                writer.begin_writer_run(self.project, "E01", 1, writer="codex")
            with self.assertRaisesRegex(writer.WriterWorkflowBlocked, "CODEX_WRITER_MODEL"):
                writer.begin_writer_run(self.project, "E01", 1, writer="codex", model_id="auto")

    def test_storyclaw_handoff_still_verifies_after_codex_support(self):
        active = self.finalize(self.begin())
        self.assertEqual(active["provider"], "storyclaw")
        self.assertNotIn("writer_author", active)
        self.assertEqual(writer.verify_writer_handoff(self.project, "E01")["status"], "PASS")


class OwnerRightsQuoteTests(unittest.TestCase):
    def test_intake_source_text_records_owner_quote_verbatim(self):
        with tempfile.TemporaryDirectory() as tmp:
            novel = Path(tmp) / "novel.txt"
            novel.write_text("第1章 开端\n正文一。\n第2章 转折\n正文二。\n", encoding="utf-8")
            out = Path(tmp) / "sources"
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/intake_source_text.py"), "--input", str(novel),
                 "--work", "fixture", "--out", str(out), "--authorization", OWNER_RIGHTS_QUOTE],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            index = json.loads(next(out.rglob("SOURCE_INDEX.json")).read_text(encoding="utf-8"))
            self.assertIn(OWNER_RIGHTS_QUOTE, json.dumps(index, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
