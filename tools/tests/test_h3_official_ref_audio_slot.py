import unittest

from tools.submit_giggle_video_manifest_v2 import _prompt_carries_audio_slot


class OfficialRefAudioSlotTest(unittest.TestCase):
    def test_official_ref_label_counts_as_canonical_slot(self):
        task = {"model": "MiniMax-H3"}
        prompt = "<Subject 1> (S1) uses the voice timbre referenced from <Audio 1> and says, <d>[Chinese]走。</d>"
        self.assertTrue(_prompt_carries_audio_slot(task, "@音频1", prompt))
        self.assertFalse(_prompt_carries_audio_slot(task, "@音频2", prompt))

    def test_director_v2_english_slot_still_accepted(self):
        task = {"model": "minimax-h3"}
        self.assertTrue(_prompt_carries_audio_slot(task, "@音频1", "voice from @Audio1 says"))
        self.assertFalse(_prompt_carries_audio_slot(task, "@音频1", "voice from <Audio 2> says"))

    def test_non_h3_requires_literal_slot(self):
        task = {"model": "seedance-2.0-pro"}
        self.assertTrue(_prompt_carries_audio_slot(task, "@音频1", "用 @音频1 的声音"))
        self.assertFalse(_prompt_carries_audio_slot(task, "@音频1", "uses <Audio 1>"))


if __name__ == "__main__":
    unittest.main()
