import unittest

from tools.final_video_ocr_audit import classify_text, continuous_runs, critical_latin_count


class OCRLexiconPolicyTest(unittest.TestCase):
    def test_allows_only_exact_canonical_sign(self):
        result = classify_text("太平醫館", ["太平醫館"], ["诊所", "診所", "诊局", "医馆"])
        self.assertTrue(result["allowed"])
        self.assertFalse(result["forbidden"])

    def test_allows_right_to_left_canonical_sign(self):
        result = classify_text("館醫平太", ["太平醫館", "館醫平太"], ["诊所", "诊局"])
        self.assertTrue(result["allowed"])
        self.assertFalse(result["unlisted_chinese"])

    def test_rejects_wrong_sign_variant(self):
        result = classify_text("太乘诊局", ["太平醫館"], ["诊所", "診所", "诊局", "医馆"])
        self.assertTrue(result["forbidden"])
        self.assertIn("诊局", result["forbidden_tokens"])

    def test_rejects_latin_text(self):
        result = classify_text("FORENSIC", ["太平醫館"], ["诊所"])
        self.assertEqual(result["latin_chars"], 8)
        self.assertEqual(critical_latin_count(result["latin_chars"]), 8)

    def test_isolated_single_latin_glyph_is_warning_only(self):
        self.assertEqual(critical_latin_count(1), 0)

    def test_marks_unknown_han_and_numbers_as_candidates(self):
        self.assertTrue(classify_text("處检竞摩平太", ["太平醫館"], ["诊所"])["unlisted_chinese"])
        self.assertTrue(classify_text("181881820", ["太平醫館"], ["诊所"])["numeric_string"])

    def test_two_consecutive_samples_are_critical(self):
        critical, warnings = continuous_runs([
            {"time_seconds": 10.5, "text": "處检竞摩平太"},
            {"time_seconds": 12.5, "text": "摩馆医平太"},
        ], 2.0)
        self.assertEqual(len(critical), 1)
        self.assertEqual(warnings, [])

    def test_isolated_sample_is_warning_only(self):
        critical, warnings = continuous_runs([
            {"time_seconds": 10.5, "text": "疑似噪声"},
        ], 2.0)
        self.assertEqual(critical, [])
        self.assertEqual(len(warnings), 1)

    def test_isolated_multi_han_is_critical_in_strict_mode(self):
        critical, warnings = continuous_runs([
            {"time_seconds": 5.5, "text": "欢祥道"},
        ], 0.5, immediate_multi_han=True)
        self.assertEqual(len(critical), 1)
        self.assertEqual(warnings, [])

    def test_isolated_single_han_stays_warning_in_strict_mode(self):
        critical, warnings = continuous_runs([
            {"time_seconds": 5.5, "text": "福"},
        ], 0.5, immediate_multi_han=True)
        self.assertEqual(critical, [])
        self.assertEqual(len(warnings), 1)


if __name__ == "__main__":
    unittest.main()
