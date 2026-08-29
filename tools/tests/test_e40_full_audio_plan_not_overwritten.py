import unittest
from pathlib import Path


class FullAudioPlanProtectionTest(unittest.TestCase):
    def test_video_preproduction_never_writes_complete_audio_plan(self) -> None:
        source = Path("tools/build_e40_full_performance_video_preproduction.py").read_text(encoding="utf-8")
        self.assertNotIn("write(AUDIO_PLAN", source)
        self.assertIn("Complete 20-line audio plan missing", source)


if __name__ == "__main__":
    unittest.main()
