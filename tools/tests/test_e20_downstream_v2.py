import unittest

from tools.build_e20_downstream_v2 import build_contracts


class E20DownstreamV2Tests(unittest.TestCase):
    def test_all_dialogue_gets_sound_a_b_and_request_scope(self):
        rows = [
            {
                "dia_id": f"DIA-{index:03d}",
                "speaker": "陈迹",
                "text": "测试。",
                "beat_id": "B01",
                "function": "确认",
            }
            for index in range(38)
        ]
        beat = {
            "runtime_target_seconds": {"min": 165, "target": 174, "max": 185},
            "structure": [
                {
                    "beat_id": "B01",
                    "target_seconds": 174,
                    "segment_type": "dialogue",
                    "must_show": ["action"],
                    "power_shift": "A to B",
                }
            ],
            "dialogue_draft": rows,
        }
        performance = {
            "beat_sheet_sha256": "sha",
            "lines": [
                {
                    **row,
                    "voice_asset_id": "voice",
                    "voice_gate": None,
                }
                for row in rows
            ],
        }
        sound, coverage, request = build_contracts(beat, performance, "sha")
        self.assertEqual(sum(len(row["dialogue_ids"]) for row in sound["beat_sound_design"]), 38)
        self.assertEqual(len(coverage["dialogue_coverage"]), 38)
        self.assertTrue(coverage["checks"]["every_dialogue_has_a_source"])
        self.assertTrue(coverage["checks"]["every_dialogue_has_b_source"])
        self.assertEqual(sum(len(row["audio_scope"]) for row in request["beat_requests"]), 38)
        self.assertTrue(request["checks"]["all_requests_disabled"])

    def test_rejects_stale_performance_manifest(self):
        with self.assertRaisesRegex(ValueError, "beat_sheet_sha256 mismatch"):
            build_contracts(
                {"runtime_target_seconds": {}, "structure": [], "dialogue_draft": []},
                {"beat_sheet_sha256": "old", "lines": []},
                "new",
            )


if __name__ == "__main__":
    unittest.main()
