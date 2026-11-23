"""Measured edit on every NALU episode (deep review 1485 E09, 2026-11-23).

The nalu gate "active_from_episode 11" dates from the single-series era (E01-E10 already delivered).  On the fleet
every series starts at E01, so the first ten episodes of every device's series were cut without the measured edit
(no SENTENCE_TAIL after the last word; JA E09 had six lines running across cuts)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import measured_edit_policy as mep  # noqa: E402


class MeasuredEditEverySeriesTests(unittest.TestCase):
    def test_first_episodes_of_a_series_are_covered(self):
        for ep in ("E01", "E09", "E10", "E11", "E24"):
            self.assertTrue(mep.active_for(ep, line="nalu"), ep)
        self.assertEqual(mep.get_policy_params("E09", line="nalu")["trail_seconds"], 0.4)

    def test_qingshan_line_gate_unchanged(self):
        self.assertFalse(mep.active_for("E64", line="qingshan"))
        self.assertTrue(mep.active_for("E65", line="qingshan"))


if __name__ == "__main__":
    unittest.main()
