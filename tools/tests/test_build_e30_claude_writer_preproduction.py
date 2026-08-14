import unittest

from tools.build_e30_claude_writer_preproduction import build_subtitle_contract, sha256, SCRIPT


class E30SubtitleContractTest(unittest.TestCase):
    def test_scene_cast_lists_are_not_dialogue(self):
        scenes = {
            "3-1": "S01",
            "3-2": "S02",
            "3-3": "S03",
            "3-4": "S04",
            "3-5": "S05",
        }
        contract = build_subtitle_contract(sha256(SCRIPT), scenes)
        speakers = [row["speaker"] for row in contract["dialogue"]]

        self.assertEqual(contract["dialogue_line_count"], 20)
        self.assertNotIn("人物", speakers)
        self.assertTrue(all(row["spoken_text"] for row in contract["dialogue"]))


if __name__ == "__main__":
    unittest.main()
