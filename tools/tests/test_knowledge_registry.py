import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from tools.knowledge_registry import ROOT, REGISTRY, validate, export_context


class KnowledgeRegistryTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / REGISTRY).read_text())

    def test_complete_catalog(self):
        self.assertEqual(52, len(validate(self.data, ROOT)["rules"]))

    NALU_S7_SYNC_E03_IDS = tuple(f"K{n:03d}" for n in range(23, 35))
    NALU_S7_SYNC_E04_IDS = tuple(f"K{n:03d}" for n in range(35, 42))
    E04_REVIEW_FAILURE_MEMORY_IDS = tuple(f"K{n:03d}" for n in range(42, 53))

    def test_e04_review_failure_memory_rows_and_jsonl_export(self):
        from tools.knowledge_registry import export_failure_memory
        by_id = {row["id"]: row for row in self.data["rules"]}
        codes = []
        for key in self.E04_REVIEW_FAILURE_MEMORY_IDS:
            row = by_id[key]
            self.assertIn(row["stage"], ("pipeline", "prompt"))          # the report's own stage values
            for field in ("failure_code", "do_not_repeat", "scope"):
                self.assertTrue(row.get(field))
            codes.append(row["failure_code"])
        self.assertEqual(sorted(codes), sorted(["HOOK_MISSING", "ACTION_NO_OUTCOME", "ANTAGONIST_NO_MOTIVE",
            "PROP_NO_SOURCE", "DEAD_THEN_ALIVE", "MASCOT_IN_STORY", "CREATURE_FORM_DRIFT", "VOICE_COLLISION",
            "FLAT_EMOTION", "MODERN_LEXICON", "DIALOGUE_STARVATION"]))
        prompt_rows = export_failure_memory(self.data, "prompt")
        self.assertEqual({r["failure_code"] for r in prompt_rows},
                         {"ACTION_NO_OUTCOME", "ANTAGONIST_NO_MOTIVE", "PROP_NO_SOURCE", "CREATURE_FORM_DRIFT"})
        # the committed jsonl must equal the registry export (CI keeps them in sync)
        exported = [json.dumps(r, ensure_ascii=False) for r in export_failure_memory(self.data)]
        committed = (ROOT / "knowledge/failure_memory.jsonl").read_text().splitlines()
        self.assertEqual(exported, committed)

    def test_every_rule_has_a_markdown_section(self):
        markdown = (ROOT / "docs/knowledge/ENGINEERING_KNOWLEDGE_BASE.md").read_text()
        for row in self.data["rules"]:
            self.assertIn(f"### {row['id']} — {row['stage']}", markdown)

    def test_nalu_s7_sync_e03_entries_exist_in_registry_and_markdown(self):
        markdown = (ROOT / "docs/knowledge/ENGINEERING_KNOWLEDGE_BASE.md").read_text()
        by_id = {row["id"]: row for row in self.data["rules"]}
        for key in self.NALU_S7_SYNC_E03_IDS + self.NALU_S7_SYNC_E04_IDS:
            self.assertIn(key, by_id)
            self.assertIn(f"### {key} — {by_id[key]['stage']}", markdown)
            # Evidence is a runbook decision id, never a path, credential or live identifier.
            self.assertRegex(by_id[key]["evidence"], r"^nalu PIPELINE_RUNBOOK D-\d+(/D-\d+)*$")
            self.assertIn("- 证据：" + by_id[key]["evidence"], markdown)
        for key in ("K035", "K036", "K037", "K040"):
            self.assertEqual("REFERENCE_IMPLEMENTATION", by_id[key]["status"])
            for path in by_id[key]["implementation"]:
                self.assertTrue((ROOT / path).is_file(), path)
        for key in ("K030", "K032", "K034"):
            expected = "REFERENCE_IMPLEMENTATION" if key == "K032" else "INTEGRATION_PENDING"  # K032: gate accepts the window label since e23 (owner decision 2026-09-15)
            self.assertEqual(expected, by_id[key]["status"])

    def test_knowledge_docs_are_in_deployment_inventory_scope(self):
        from tools.deployment_code_integrity import included
        for name in ("docs/knowledge/ENGINEERING_KNOWLEDGE_BASE.md",
                     "docs/decisions/DECISION_RECORDS.md",
                     "examples/handoff/HANDOFF_TEMPLATE.md"):
            self.assertTrue(included(name))

    def test_never_authorizes_or_claims_media_qa(self):
        result = export_context(self.data)
        self.assertIs(result["production_authorization"], False)
        self.assertIs(result["media_qa_pass"], False)
        self.assertIn("K004", result["integration_pending"])

    def test_stage_filter(self):
        self.assertEqual(["K009"], [x["id"] for x in export_context(self.data, "ACTION")["rules"]])
        with self.assertRaisesRegex(ValueError, "STAGE_UNKNOWN"):
            export_context(self.data, "typo")

    def test_duplicate_rejected(self):
        self.data["rules"].append(copy.deepcopy(self.data["rules"][0]))
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            validate(self.data, ROOT)

    def test_missing_source_rejected(self):
        self.data["rules"][0]["implementation"] = ["tools/does_not_exist.py"]
        with self.assertRaisesRegex(ValueError, "LINK_NOT_FOUND"):
            validate(self.data, ROOT)

    def test_path_escape_rejected(self):
        for name in ("../outside", "/outside", "tools\\outside"):
            data = copy.deepcopy(self.data)
            data["rules"][0]["implementation"] = [name]
            with self.assertRaisesRegex(ValueError, "PATH_UNSAFE"):
                validate(data, ROOT)

    def test_no_silent_promotion(self):
        self.data["rules"][0]["runtime_gate_added"] = True
        with self.assertRaisesRegex(ValueError, "FALSE_GATE"):
            validate(self.data, ROOT)

    def test_evidence_required(self):
        self.data["rules"][0]["implementation"] = []
        with self.assertRaisesRegex(ValueError, "EVIDENCE_MISSING"):
            validate(self.data, ROOT)

    def test_help_and_validate_outside_repository(self):
        for arg in ("--help", "--validate"):
            result = subprocess.run([sys.executable, str(ROOT / "tools/knowledge_registry.py"), arg],
                                    cwd=ROOT.parent, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)

    def test_no_personal_paths_or_live_task_identifiers(self):
        text = (ROOT / REGISTRY).read_text()
        for token in ("/Users/", "/var/folders/", "Bearer ", "task_id", "remote_task_id"):
            self.assertNotIn(token, text)

    def test_original_causal_chain_regression(self):
        # Exercise an existing production consumer, not a new media judge.
        from tools.sd2_motion_density_gate import validate_combat_causal_chain
        base = dict(interaction_mode="CONTACT", force_origin="right shoulder",
                    primary_feedback="opponent steps back", secondary_feedback=[],
                    contact_point="chest", primary_action="strike", exit_state="separated",
                    state_delta_dimensions=["CONTACT"])
        self.assertEqual([], validate_combat_causal_chain(base, source_id="fixture"))
        base["contact_point"] = "尚未接触"
        self.assertTrue(any("AMBIGUOUS_CONTACT_TYPE" in x
                            for x in validate_combat_causal_chain(base, source_id="fixture")))


if __name__ == "__main__":
    unittest.main()
