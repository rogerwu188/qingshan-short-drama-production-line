"""Lab-only NALU_VOICE_COPRESENT_RULE=TIMBRE_DISTINCT: the 40 Hz rule stays the default (owner 2026-11-03)."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import build_voice_cast as bvc  # noqa: E402


class TimbreLabRuleTests(unittest.TestCase):
    chars = {"A": {"reference_f0_hz": 120.0, "voice_id": "v1"}, "B": {"reference_f0_hz": 135.0, "voice_id": "v2"}}

    def test_default_is_the_40hz_rule(self):
        self.assertTrue(bvc.copresent_f0_matrix(self.chars, [["A", "B"]])["failures"])

    def test_matrix_function_unchanged_by_env(self):
        with mock.patch.dict(os.environ, {"NALU_VOICE_COPRESENT_RULE": "TIMBRE_DISTINCT"}):
            self.assertTrue(bvc.copresent_f0_matrix(self.chars, [["A", "B"]])["failures"])


if __name__ == "__main__":
    unittest.main()
