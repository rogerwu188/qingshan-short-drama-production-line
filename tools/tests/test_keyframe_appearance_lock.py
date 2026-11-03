"""Keyframe 【外貌锁】: contract appearance_anchor_en reaches the image prompt (E12 2026-10-31)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import build_keyframe_manifest as bkm  # noqa: E402

CONTRACT = {"character_entities": [
    {"character_id": "CHAR-A", "canonical_name": "甲", "appearance_anchor_en": "man in his forties, short beard."},
    {"character_id": "CHAR-B", "canonical_name": "乙"},
]}


class AppearanceLockTests(unittest.TestCase):
    def test_active_from_e13_and_for_listed_e12_redo_shots_only(self):
        self.assertTrue(bkm.appearance_lock_active("E13", "E13-S01-01"))
        self.assertTrue(bkm.appearance_lock_active("E12", "E12-S04-01"))
        self.assertFalse(bkm.appearance_lock_active("E12", "E12-S04-02"))
        self.assertFalse(bkm.appearance_lock_active("E11", "E11-S04-01"))

    def test_lines_follow_cast_order_and_skip_characters_without_an_anchor(self):
        self.assertEqual(bkm.appearance_lock_lines(CONTRACT, ["CHAR-B", "CHAR-A"]),
                         ["- 甲（CHAR-A）：man in his forties, short beard"])
        self.assertEqual(bkm.appearance_lock_lines(CONTRACT, []), [])


if __name__ == "__main__":
    unittest.main()
