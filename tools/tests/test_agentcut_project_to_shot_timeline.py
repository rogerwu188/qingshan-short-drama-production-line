import unittest

from tools.agentcut_project_to_shot_timeline import build_timeline


class AgentCutProjectToShotTimelineTest(unittest.TestCase):
    def test_converts_and_sorts_track_clips(self):
        project = {
            "timeline": {
                "videoTracks": [{
                    "id": "picture",
                    "clips": [
                        {"id": "b", "start": 2, "duration": 1, "source": "b.mp4", "metadata": {"beat_id": "B02"}},
                        {"id": "a", "start": 0, "duration": 2, "source": "a.mp4", "metadata": {"scene_id": "S01", "beat_id": "B01", "dialogue_id": "DIA-1"}},
                    ],
                }]
            }
        }
        result = build_timeline(project, "picture")
        self.assertEqual([row["shot_id"] for row in result["shots"]], ["a", "b"])
        self.assertEqual(result["shots"][0]["end"], 2.0)
        self.assertEqual(result["shots"][0]["scene_id"], "S01")
        self.assertEqual(result["shots"][1]["scene_id"], "B02")

    def test_missing_track_fails(self):
        with self.assertRaisesRegex(ValueError, "Missing AgentCut video track"):
            build_timeline({"timeline": {"videoTracks": []}}, "picture")


if __name__ == "__main__":
    unittest.main()
