import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class E40AssemblyRuntimeDiagnosticTest(unittest.TestCase):
    def test_registered_complete_manifest_gate_has_no_runtime_threshold(self) -> None:
        registry = json.loads((ROOT / "configs/GATE_REGISTRY_v3_20260716.json").read_text())
        gate = next(row for row in registry["gates"] if row["gate_id"] == "COMPLETE-VIDEO-PROMPT-MANIFEST")
        self.assertNotIn("canonical_target_seconds", gate["parameters"])
        self.assertNotIn("minimum_runtime_seconds", gate["parameters"])

    def test_assembly_builder_does_not_fail_registered_gate_from_runtime(self) -> None:
        source = (ROOT / "tools/build_e40_current_sequence_v6_all_dialogue_covered.py").read_text()
        self.assertIn('"status": "NOT_EVALUATED_BY_RUNTIME"', source)
        self.assertIn('"class": "DIAGNOSTIC"', source)
        self.assertNotIn('"missing_duration_seconds"', source)


if __name__ == "__main__":
    unittest.main()
