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

    def test_authored_world_contract_overrides_episode_number(self) -> None:
        # holmes lab E11 2026-10-31: Victorian London got 自然东方肤色 and 【东方时代视觉锁】 by episode number
        vcc = {"schema": "qingshan.visual_culture_contract.v1", "status": "LOCKED",
               "profile_id": "VICTORIAN-LONDON-1888", "era_lock": "AUTHORED_WORLD",
               "decision_owner": "WRITER_DIRECTOR", "decision_basis": "source", "source_ref": "ch0001.md",
               "story_world": "London, England, March 1888", "production_design": "Victorian London",
               "armor_tradition": "No armor.", "lighting_language": "window light", "image_texture": "photographic",
               "palette_system": {"base": "charcoal", "accent": "amber", "skin": "natural pale English complexions"},
               "forbidden_influences": ["mobile phones", "neon"]}
        for episode in ("E11", f"E{ACTIVE_FROM_EPISODE + 3}"):
            contract, block = bic.culture_lock_for(episode, {"dialogue_language": "en", "visual_culture_contract": vcc})
            self.assertEqual(contract["profile_id"], "VICTORIAN-LONDON-1888")
            self.assertEqual(contract["palette_system"]["skin"], "natural pale English complexions")
            self.assertGreaterEqual(len(contract["forbidden_influences"]), 6)
            self.assertNotRegex(block, "东方|EAST-ASIAN|宋|欧洲|Gothic")
            self.assertIn("VICTORIAN-LONDON-1888", block)
            self.assertNotIn("东方", str(contract))
            row = {"episode": episode, "visual_culture_contract": dict(contract)}
            self.assertEqual(validate_visual_culture_contract(row, prompt_text="Irene Adler.\n" + block)["status"], "PASS")

    def test_english_line_without_era_lock_is_authored_but_chinese_lines_keep_legacy(self) -> None:
        contract, block = bic.culture_lock_for("E01", {"dialogue_language": "en"})
        self.assertNotIn("东方", str(contract) + block)
        legacy = bic.culture_lock_for("E01")
        self.assertEqual(bic.culture_lock_for("E01", {"dialogue_language": "zh", "visual_culture_contract":
                                                      {"profile_id": "YEWUJIANG_X"}}), legacy)
        self.assertEqual(legacy, (bic.NEUTRAL_PERIOD_CONTRACT, bic.NEUTRAL_PERIOD_PROMPT_BLOCK_ZH))
        high = bic.culture_lock_for(f"E{ACTIVE_FROM_EPISODE}", {"dialogue_language": "en"})
        self.assertEqual(high[0]["profile_id"], PROFILE_ID)  # E54+ needs an explicit era_lock
        declared = bic.culture_lock_for("E01", {"dialogue_language": "en",
                                                "visual_culture_contract": {"era_lock": "EAST_ASIAN_PERIOD"}})
        self.assertEqual(declared, legacy)

    def test_authored_lock_replaces_stale_east_asian_lock_and_legacy_prompt_untouched(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "a.txt"
            stale.write_text("Irene.\n" + bic.NEUTRAL_PERIOD_PROMPT_BLOCK_ZH + "\n", encoding="utf-8")
            row = {"prompt_file": str(stale)}
            _, block = bic.culture_lock_for("E11", {"dialogue_language": "en", "visual_culture_contract":
                                                    {"era_lock": "AUTHORED_WORLD", "profile_id": "V"}})
            bic.apply_culture_lock(row, block)
            self.assertEqual(stale.read_text(encoding="utf-8"), "Irene.\n" + block + "\n")
            self.assertEqual(row["prompt_sha256"], bic.sha256_file(stale))
            legacy = Path(tmp) / "b.txt"
            legacy.write_text("晚明书生。\n" + bic.NEUTRAL_PERIOD_PROMPT_BLOCK_ZH + "\n", encoding="utf-8")
            before = legacy.read_bytes()
            legacy_row = {"prompt_file": str(legacy)}
            bic.apply_culture_lock(legacy_row, bic.culture_lock_for("E01")[1])
            self.assertEqual(legacy.read_bytes(), before)
            self.assertNotIn("prompt_sha256", legacy_row)


if __name__ == "__main__":
    unittest.main()
