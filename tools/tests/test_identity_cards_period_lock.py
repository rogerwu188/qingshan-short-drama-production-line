"""Identity plates below the qingshan activation episode must not be locked to Northern Song."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import bootstrap_identity_cards as bic  # noqa: E402
from tools.visual_culture_contract import ACTIVE_FROM_EPISODE, PROFILE_ID, validate_visual_culture_contract  # noqa: E402


class IdentityCardsPeriodLockTest(unittest.TestCase):
    def test_nalu_episode_gets_neutral_lock(self) -> None:
        contract, block = bic.culture_lock_for("E01")
        self.assertNotEqual(contract["profile_id"], PROFILE_ID)
        self.assertNotIn("北宋", block)
        self.assertNotIn("北宋", contract["story_world"])
        row = {"episode": "E01", "visual_culture_contract": dict(contract)}
        self.assertEqual(validate_visual_culture_contract(row, prompt_text="晚明江南书生。\n" + block)["status"], "PASS")

    def test_qingshan_episode_keeps_northern_song(self) -> None:
        contract, block = bic.culture_lock_for(f"E{ACTIVE_FROM_EPISODE}")
        self.assertEqual(contract["profile_id"], PROFILE_ID)
        self.assertIn("北宋", block)


if __name__ == "__main__":
    unittest.main()
