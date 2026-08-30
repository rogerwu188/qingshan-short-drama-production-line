import unittest

from tools.production_efficiency_contract import (
    evaluate_grouped_manifest,
    generation_cache_key,
    require_e47_efficiency_contract,
)
from tools.release_encoding_profile import select_h264_encoder


def unit(uid, duration, dialogues):
    return {
        "unit_id": uid,
        "model": "MiniMax-H3",
        "duration_seconds": duration,
        "ordered_prompt_specs": [{"dialogue": row} for row in dialogues] or [{"dialogue": ""}],
    }


class ProductionEfficiencyContractTests(unittest.TestCase):
    def test_h3_dialogue_and_silent_profiles_pass(self):
        report = evaluate_grouped_manifest({
            "episode": "E47",
            "units": [unit("D1", 9, ["甲：一句。", "乙：两句。"]), unit("S1", 15, [])],
        })
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["rolling_execution"]["generation_harvest_and_qa_overlap"])

    def test_long_or_dense_h3_dialogue_fails_closed(self):
        report = evaluate_grouped_manifest({
            "episode": "E47",
            "units": [unit("D1", 12, ["甲：一。", "甲：二。", "甲：三。"])],
        })
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("D1:H3_DIALOGUE_UNIT_OVER_10_SECONDS", report["failures"])
        self.assertIn("D1:H3_DIALOGUE_UNIT_OVER_TWO_LINES", report["failures"])

    def test_cache_key_ignores_remote_state(self):
        base = {
            "model": "MiniMax-H3", "duration_seconds": 9, "aspect_ratio": "9:16",
            "resolution": "768p", "prompt_sha256": "p",
            "reference_images": [{"sha256": "i"}], "reference_audios": [],
        }
        self.assertEqual(
            generation_cache_key({**base, "remote_task_id": "one", "status": "running"}),
            generation_cache_key({**base, "remote_task_id": "two", "status": "failed"}),
        )

    def test_videotoolbox_is_preferred(self):
        profile = select_h264_encoder(" V....D h264_videotoolbox VideoToolbox H.264 Encoder")
        self.assertEqual(profile["name"], "h264_videotoolbox")
        self.assertTrue(profile["hardware_accelerated"])

    def test_paid_task_manifest_is_supported_and_e47_is_automatic(self):
        report = require_e47_efficiency_contract({
            "episode": "E47",
            "tasks": [{
                "task_key": "E47-VU-001",
                "model": "MiniMax-H3",
                "duration_seconds": 8,
                "dialogue_lines": ["甲：一句。"],
                "prompt_sha256": "prompt-one",
            }],
        })
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["units"][0]["unit_id"], "E47-VU-001")

    def test_duplicate_exact_requests_fail_closed(self):
        common = {
            "model": "MiniMax-H3", "duration_seconds": 8,
            "aspect_ratio": "9:16", "resolution": "768p", "prompt_sha256": "same",
        }
        report = evaluate_grouped_manifest({
            "episode": "E47",
            "tasks": [
                {**common, "task_key": "A"},
                {**common, "task_key": "B"},
            ],
        })
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("DUPLICATE_EXACT_GENERATION_REQUEST" in row for row in report["failures"]))


if __name__ == "__main__":
    unittest.main()
