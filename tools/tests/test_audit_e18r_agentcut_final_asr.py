import unittest

from tools.audit_e18r_agentcut_final_asr import (
    choose_source_segments,
    source_range_cuts_sentence,
)


class SourceRangeSentenceTest(unittest.TestCase):
    def test_head_silence_trim_is_not_a_sentence_cut(self) -> None:
        segments = [{"start": 0.66, "end": 4.10, "text": "line"}]
        self.assertFalse(source_range_cuts_sentence(segments, 0.20, 3.86, 4.0635))

    def test_trim_into_first_spoken_segment_blocks(self) -> None:
        segments = [{"start": 0.05, "end": 3.50, "text": "line"}]
        self.assertTrue(source_range_cuts_sentence(segments, 0.20, 3.86, 4.0635))

    def test_tail_truncation_blocks(self) -> None:
        segments = [{"start": 0.50, "end": 4.00, "text": "line"}]
        self.assertTrue(source_range_cuts_sentence(segments, 0.00, 3.80, 4.0635))

    def test_short_chinese_line_uses_no_vad_fallback(self) -> None:
        fallback = [{"start": 0.0, "end": 1.0, "text": "灯"}]
        selected, mode = choose_source_segments([], fallback)
        self.assertEqual(selected, fallback)
        self.assertEqual(mode, "VAD_DISABLED_SHORT_LINE_FALLBACK")

    def test_vad_chinese_line_remains_preferred(self) -> None:
        vad = [{"start": 0.0, "end": 1.0, "text": "他有刀"}]
        selected, mode = choose_source_segments(vad, [{"text": "别的"}])
        self.assertEqual(selected, vad)
        self.assertEqual(mode, "VAD_FILTERED")


if __name__ == "__main__":
    unittest.main()
