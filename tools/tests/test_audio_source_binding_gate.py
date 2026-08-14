import unittest

from tools.audio_source_binding_gate import evaluate


FILE_SHA = "a" * 64
AUDIO_FP = "b" * 64


def plan():
    return {
        "audio_binding": {
            "published_mix_file_sha256": FILE_SHA,
            "published_mix_audio_fingerprint": AUDIO_FP,
        },
        "audio_tracks": [
            {
                "track_id": "published_mix_main",
                "source_type": "published_mix",
                "source_file_sha256": FILE_SHA,
                "source_audio_fingerprint": AUDIO_FP,
            }
        ],
        "repair_segments": [
            {"segment_id": "R1", "candidate_audio_discarded": True}
        ],
    }


class AudioSourceBindingGateTests(unittest.TestCase):
    def test_passes_bound_published_mix(self):
        self.assertEqual(evaluate(plan(), FILE_SHA, AUDIO_FP)["status"], "PASS")

    def test_rejects_candidate_audio_or_wrong_track(self):
        payload = plan()
        payload["audio_tracks"][0]["source_type"] = "candidate_aac"
        payload["repair_segments"][0]["candidate_audio_discarded"] = False
        report = evaluate(payload, FILE_SHA, AUDIO_FP)
        self.assertIn(
            "audio_track_not_published_mix:published_mix_main",
            report["failures"],
        )
        self.assertIn("candidate_audio_not_discarded:R1", report["failures"])


if __name__ == "__main__":
    unittest.main()
