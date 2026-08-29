import unittest

from tools.qa_e40_full_performance_audio_refs import exact_or_known_homophone, majority_exact


class FullPerformanceAudioAsrTest(unittest.TestCase):
    def test_exact_text_passes_without_adjudication(self) -> None:
        self.assertEqual(exact_or_known_homophone("活口一个没留。", "活口一个没留。"), (True, None))

    def test_narrow_ba_homophone_is_adjudicated(self) -> None:
        self.assertEqual(exact_or_known_homophone("带走吧。", "带走罢。"), (True, "罢/吧"))

    def test_tone_distinct_huo_substitution_does_not_pass(self) -> None:
        self.assertEqual(exact_or_known_homophone("火口一个没留。", "活口一个没留。"), (False, None))

    def test_independent_model_vote_requires_two_exact_recognitions(self) -> None:
        self.assertTrue(majority_exact([False, True, True]))
        self.assertFalse(majority_exact([False, True, False]))


if __name__ == "__main__":
    unittest.main()
