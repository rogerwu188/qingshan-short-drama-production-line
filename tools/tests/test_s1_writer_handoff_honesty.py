"""S1 must not record a PASS for a writer-handoff check that never ran.

Under LEGACY_EPISODE_COMPAT the canonical writer handoff belongs to the StoryClaw
private-project path and is not verified for this line, yet the S1 receipt printed
`gates.canonical_writer_handoff: PASS` for E11-E13 (P0_INVENTORY.md, 附).  Line owner
2026-11-01 authorised fixing the report without changing the stage outcome.
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"


def _load_pipeline():
    tmp = tempfile.mkdtemp(prefix="nalu-s1-honesty-")
    with patch.dict(os.environ, {"NALU_ENGINE_ROOT": str(ROOT),
                                 "NALU_RUNTIME_ROOT": tmp}):
        for name in ("nalu_paths", "nalu_policy_profile", "nalu_pipeline"):
            sys.modules.pop(name, None)
        sys.path.insert(0, str(TOOLS))
        return importlib.import_module("nalu_pipeline")


PIPELINE = _load_pipeline()
SOURCE = (TOOLS / "nalu_pipeline.py").read_text(encoding="utf-8")


class LegacyHandoffStatusTests(unittest.TestCase):
    def test_the_legacy_status_is_not_a_pass(self):
        self.assertNotEqual(PIPELINE.WRITER_HANDOFF_LEGACY_STATUS, "PASS")
        self.assertTrue(PIPELINE.WRITER_HANDOFF_LEGACY_STATUS.startswith("NOT_RUN"))

    def test_a_profile_with_no_verifier_reports_not_run(self):
        status = PIPELINE.writer_handoff_gate_status(
            True, {"status": PIPELINE.WRITER_HANDOFF_LEGACY_STATUS})
        self.assertEqual(status, "NOT_RUN_LEGACY_PROFILE")

    def test_a_verified_handoff_still_reports_pass(self):
        self.assertEqual(PIPELINE.writer_handoff_gate_status(True, {"status": "PASS"}), "PASS")

    def test_a_failed_handoff_still_reports_fail(self):
        self.assertEqual(PIPELINE.writer_handoff_gate_status(False, {"status": "PASS"}), "FAIL")

    def test_an_empty_verdict_is_not_a_pass(self):
        self.assertEqual(PIPELINE.writer_handoff_gate_status(True, {}), "NOT_RUN")

    def test_the_legacy_branch_no_longer_borrows_the_pass(self):
        self.assertNotIn('"canonical_writer_handoff": PASS if writer_handoff_ok else "FAIL"', SOURCE)
        self.assertNotIn('"status": "NOT_APPLICABLE_LEGACY_REPLAY"', SOURCE)
        self.assertIn('WRITER_HANDOFF_LEGACY_STATUS', SOURCE)

    def test_the_stage_outcome_is_unchanged_under_legacy(self):
        # the fix changes what the receipt SAYS, never what S1 decides: the LEGACY
        # branch still admits the step.
        block = SOURCE.split("HONESTY (line owner 2026-11-01)", 1)[1].split("gate10 = ctx.run", 1)[0]
        self.assertIn("writer_handoff_ok = True", block)


class DownstreamConsumerTests(unittest.TestCase):
    """Consumers of the S1 receipt were checked; these assert the check holds."""

    def test_release_validation_only_runs_on_current_portable(self):
        source = (ROOT / "tools/storyclaw_release_validation.py").read_text(encoding="utf-8")
        self.assertIn('"policy_profile": "CURRENT_PORTABLE"', source)
        # and it is that comparison that precedes the gates-map sweep
        before = source.split('"policy_profile": "CURRENT_PORTABLE"', 1)[0]
        self.assertIn("S1_GATE_RECEIPT", before)

    def test_the_asset_plan_gate_reads_the_stage_status_not_the_gate_map(self):
        source = (ROOT / "tools/storyclaw_asset_plan_gate.py").read_text(encoding="utf-8")
        self.assertIn('if _stage_s1_status(s1) != "PASS"', source)
        self.assertNotIn('s1.get("gates")', source)

    def test_no_pipeline_stage_reads_the_handoff_gate_row(self):
        readers = [line for line in SOURCE.splitlines()
                   if "canonical_writer_handoff" in line
                   and "gates" in line and '"canonical_writer_handoff": writer_handoff_gate_status' not in line]
        self.assertEqual(readers, [], readers)


if __name__ == "__main__":
    unittest.main()
