import unittest

from tools.compile_standard_storyboard_batch import collect_references, dialogue_chunks_for_beat


class StandardStoryboardBatchTests(unittest.TestCase):
    def test_reference_map_keeps_string_path_atomic(self):
        result = collect_references({"beats": {"B01": "working_assets/e25/B01.png"}})
        self.assertEqual(["working_assets/e25/B01.png"], result["B01"])

    def test_reference_map_preserves_path_lists(self):
        result = collect_references({"beats": {"B01": ["a.png", "b.png"]}})
        self.assertEqual(["a.png", "b.png"], result["B01"])

    def test_six_dialogue_lines_split_into_two_three_line_storyboards(self):
        draft = [
            {"beat_id": "B01", "speaker": "A", "text": f"line-{index}"}
            for index in range(6)
        ]

        chunks = dialogue_chunks_for_beat("B01", draft)

        self.assertEqual([3, 3], [len(chunk) for chunk in chunks])
        self.assertEqual("line-5", chunks[1][-1]["text"])


if __name__ == "__main__":
    unittest.main()
