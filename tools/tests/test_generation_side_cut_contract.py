import unittest

from tools.compile_e19r_agentcut_project import _required_generation_metadata
from tools.insert_agentcut_short_cuts import (
    _insert_semantic_group,
    _required_insert_metadata,
)


class GenerationSideCutContractTest(unittest.TestCase):
    def setUp(self):
        self.continuity = {
            "scene_id": "alley",
            "light_key": "night_lantern",
            "axis_line": "A1",
            "eyeline": "left",
        }

    def test_compiler_requires_reason_and_continuity(self):
        with self.assertRaisesRegex(ValueError, "cut_reason"):
            _required_generation_metadata({"shot_index": 2, **self.continuity})

        with self.assertRaisesRegex(ValueError, "continuity fields"):
            _required_generation_metadata(
                {"shot_index": 2, "cut_reason": "SPEAKER_CHANGE"}
            )

    def test_compiler_rejects_metric_reason_note(self):
        with self.assertRaisesRegex(ValueError, "metric-driven"):
            _required_generation_metadata(
                {
                    "shot_index": 2,
                    "cut_reason": "ACTION_BEAT",
                    "cut_reason_note": "为了把 ASL 压到 3 秒",
                    **self.continuity,
                }
            )

    def test_insert_has_no_default_reason(self):
        with self.assertRaisesRegex(SystemExit, "explicit closed-vocabulary reason"):
            _required_insert_metadata({"id": "I-01", **self.continuity})

    def test_insert_requires_new_information_and_continuity(self):
        with self.assertRaisesRegex(SystemExit, "new_information"):
            _required_insert_metadata(
                {"id": "I-01", "reason": "NEW_INFORMATION", **self.continuity}
            )

    def test_insert_requires_reason_specific_evidence(self):
        with self.assertRaisesRegex(SystemExit, "emotion_delta"):
            _required_insert_metadata(
                {
                    "id": "I-02",
                    "reason": "REACTION_NEW_EMOTION",
                    "new_information": "众人意识到黑猫在示警",
                    **self.continuity,
                }
            )

        with self.assertRaisesRegex(SystemExit, "continuity fields"):
            _required_insert_metadata(
                {
                    "id": "I-01",
                    "reason": "NEW_INFORMATION",
                    "new_information": "巡兵灯火照到墙根",
                }
            )

    def test_valid_insert_carries_contract_into_metadata(self):
        row = {
            "id": "I-01",
            "reason": "NEW_INFORMATION",
            "new_information": "巡兵灯火照到墙根",
            **self.continuity,
        }
        metadata = _required_insert_metadata(row)
        self.assertEqual(metadata["cut_reason"], "NEW_INFORMATION")
        self.assertEqual(metadata["new_information"], "巡兵灯火照到墙根")
        self.assertEqual(metadata["scene_id"], "alley")

    def test_insert_gets_independent_semantic_group(self):
        self.assertEqual(_insert_semantic_group({"id": "I-01"}), "I-01")
        self.assertEqual(
            _insert_semantic_group({"id": "I-01", "semantic_group": "B01-CAT"}),
            "B01-CAT",
        )


if __name__ == "__main__":
    unittest.main()
