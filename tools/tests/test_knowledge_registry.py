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
        self.assertEqual(22, len(validate(self.data, ROOT)["rules"]))

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
