import unittest

from tools.grand_cinematic_prompt_compiler import compile_prompts
from tools.tests.test_grand_cinematic_visual_contract_gate import valid_payload


class GrandCinematicPromptCompilerTest(unittest.TestCase):
    def test_compiles_still_and_video_from_same_locked_contract(self):
        result = compile_prompts(valid_payload())
        self.assertTrue(result["script_state_locked"])
        self.assertEqual(result["shot_count"], 1)
        self.assertIn("剧本硬锁", result["shots"][0]["still_prompt"])
        self.assertIn("生成9秒真实连续视频", result["shots"][0]["video_prompt"])
        self.assertIn("尺度锚点", result["shots"][0]["video_prompt"])

    def test_refuses_invalid_contract(self):
        payload = valid_payload()
        payload["shots"][0]["duration_seconds"] = 20
        with self.assertRaisesRegex(ValueError, "visual contract failed"):
            compile_prompts(payload)


if __name__ == "__main__":
    unittest.main()
