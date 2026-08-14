#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "tools/pipeline_environment_baseline.py"
SPEC = importlib.util.spec_from_file_location("pipeline_environment_baseline", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PipelineEnvironmentBaselineTests(unittest.TestCase):
    def test_builds_complete_mixed_file_and_state_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            contract.write_text('{"role":"pipeline"}', encoding="utf-8")
            files = {"role_contract": str(contract)}
            states = {
                name: f"live:{name}"
                for name in MODULE.REQUIRED
                if name not in files
            }
            baseline = MODULE.build_baseline(
                "2.1.0-pipeline-production-parity",
                "https://storyclaw.com/agent/pipeline",
                files,
                states,
            )
        self.assertEqual(baseline["status"], "PASS")
        self.assertEqual(
            {item["name"] for item in baseline["protected_components"]},
            MODULE.REQUIRED,
        )
        self.assertFalse(baseline["protocol_mutation_allowed"])

    def test_missing_component_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing protected components"):
            MODULE.build_baseline(
                "version",
                "https://storyclaw.com/agent/pipeline",
                {},
                {"queue_cron": "live:q"},
            )


if __name__ == "__main__":
    unittest.main()
