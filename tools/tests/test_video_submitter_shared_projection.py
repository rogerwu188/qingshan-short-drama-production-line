import unittest

from tools.submit_giggle_video_manifest_v2 import grouped_sequence_unit


class SharedExecutionProjectionTest(unittest.TestCase):
    def test_paid_boundary_projection_keeps_model_transport_identity(self):
        projected = grouped_sequence_unit({
            "task_key": "E50-VU-TEST-VIDEO-A2",
            "unit_id": "E50-VU-TEST",
            "model": "seedance-2.0-pro",
            "resolution": "720p",
            "aspect_ratio": "9:16",
            "duration_seconds": 4,
            "machine_contract": {"ordered_prompt_specs": []},
        })
        self.assertEqual(projected["model"], "seedance-2.0-pro")
        self.assertEqual(projected["resolution"], "720p")
        self.assertEqual(projected["aspect_ratio"], "9:16")


if __name__ == "__main__":
    unittest.main()
