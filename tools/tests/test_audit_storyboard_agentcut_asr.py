import unittest

from tools.audit_storyboard_agentcut_asr import storyboard_audio_clips


class StoryboardAgentCutAsrTests(unittest.TestCase):
    def test_accepts_multi_dialogue_source_metadata(self):
        project = {"timeline": {"audioTracks": [{"clips": [
            {"id": "late", "start": 12, "metadata": {"source_id": "B01-P2", "expected_text": "第二句"}},
            {"id": "early", "start": 0, "metadata": {"source_id": "B01-P1", "expected_text": "第一句和第二句"}},
            {"id": "ambience", "start": 0, "metadata": {}},
        ]}]}}
        clips = storyboard_audio_clips(project)
        self.assertEqual([row["id"] for row in clips], ["early", "late"])


if __name__ == "__main__":
    unittest.main()
