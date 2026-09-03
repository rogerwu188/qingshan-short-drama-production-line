import unittest

from tools.visual_culture_contract import (
    DEFAULT_CONTRACT,
    PROFILE_ID,
    prompt_block_en,
    prompt_block_zh,
    validate_visual_culture_contract,
)


class VisualCultureContractTests(unittest.TestCase):
    def test_e54_requires_contract(self):
        report = validate_visual_culture_contract({"episode": "E54"})
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("VISUAL_CULTURE_CONTRACT_MISSING", report["failures"])

    def test_chinese_prompt_contract_passes(self):
        task = {"episode": "E54", "visual_culture_contract": DEFAULT_CONTRACT}
        self.assertEqual(validate_visual_culture_contract(task, prompt_text=prompt_block_zh())["status"], "PASS")

    def test_english_prompt_contract_passes(self):
        task = {"episode": "E54", "visual_culture_contract": DEFAULT_CONTRACT}
        self.assertEqual(validate_visual_culture_contract(task, prompt_text=prompt_block_en())["status"], "PASS")

    def test_full_appearance_reference_requires_culture_admission(self):
        task = {
            "episode": "E54", "visual_culture_contract": DEFAULT_CONTRACT,
            "reference_bindings": [{
                "entity_id": "CHAR-X", "identity_visual_contract": "FULLY_CONCEALED_IDENTITY",
            }],
        }
        report = validate_visual_culture_contract(task, prompt_text=prompt_block_zh())
        self.assertEqual(report["status"], "FAIL")
        task["reference_bindings"][0]["cultural_style_profile_id"] = PROFILE_ID
        self.assertEqual(validate_visual_culture_contract(task, prompt_text=prompt_block_zh())["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
