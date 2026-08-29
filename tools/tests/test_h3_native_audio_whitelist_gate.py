import unittest

from tools.h3_native_audio_whitelist_gate import evaluate_transcript


class H3NativeAudioWhitelistGateTest(unittest.TestCase):
    def test_canonical_dialogue_with_homophone_is_advisory_pass(self):
        report = evaluate_transcript("土硝，三斗。", "土销三斗")
        self.assertEqual(report["status"], "PASS", report["failures"])

    def test_e45_vu006_prompt_narration_is_blocked(self):
        report = evaluate_transcript(
            "您要这么多，做什么用？昨日还有。",
            "手掌一直保持为本镜头结果您要这么多做什么用昨日还有",
        )
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(row.startswith("NON_WHITELIST_SPEECH") for row in report["failures"]))
        self.assertTrue(any(row.startswith("PROMPT_TEXT_NARRATION") for row in report["failures"]))

    def test_silent_unit_rejects_any_speech(self):
        report = evaluate_transcript("", "摄影机慢慢向前移动")
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("UNAUTHORED_SPEECH_IN_SILENT_UNIT", report["failures"])

    def test_media_tail_speech_is_blocked(self):
        report = evaluate_transcript(
            "昨日还有。", "昨日还有", final_speech_end=6.0, media_duration=6.02
        )
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("SPEECH_REACHES_MEDIA_TAIL_HARD_CUT_RISK", report["failures"])


if __name__ == "__main__":
    unittest.main()
