import unittest

from tools.final_audio_provenance_gate import evaluate


FILE_SHA = "a" * 64
CANDIDATE_SHA = "b" * 64
CANDIDATE_FP = "c" * 64
SEGMENT_FP = "d" * 64


def manifest():
    return {
        "published_mix_file_sha256": FILE_SHA,
        "processed_intervals": [
            {
                "interval_id": "P1",
                "start_seconds": 10,
                "end_seconds": 11,
                "reason": "declared equal-power fade",
            }
        ],
        "unchanged_intervals": [
            {"interval_id": "U1", "start_seconds": 2, "end_seconds": 8}
        ],
    }


class FinalAudioProvenanceGateTests(unittest.TestCase):
    def test_passes_declared_processing_and_matching_unchanged_segment(self):
        report = evaluate(
            manifest(),
            FILE_SHA,
            CANDIDATE_SHA,
            CANDIDATE_FP,
            [
                {
                    "interval_id": "U1",
                    "published_mix_fingerprint": SEGMENT_FP,
                    "candidate_fingerprint": SEGMENT_FP,
                }
            ],
        )
        self.assertEqual(report["status"], "PASS")

    def test_rejects_undeclared_processing_or_missing_unchanged_evidence(self):
        payload = manifest()
        payload["processed_intervals"] = []
        report = evaluate(payload, FILE_SHA, CANDIDATE_SHA, CANDIDATE_FP, [])
        self.assertIn("processed_intervals_missing", report["failures"])
        self.assertIn(
            "unchanged_segment_results_missing:U1",
            report["failures"],
        )

    def test_rejects_changed_audio_inside_unchanged_interval(self):
        report = evaluate(
            manifest(),
            FILE_SHA,
            CANDIDATE_SHA,
            CANDIDATE_FP,
            [
                {
                    "interval_id": "U1",
                    "published_mix_fingerprint": SEGMENT_FP,
                    "candidate_fingerprint": "e" * 64,
                }
            ],
        )
        self.assertIn(
            "unchanged_segment_fingerprint_mismatch:U1",
            report["failures"],
        )


if __name__ == "__main__":
    unittest.main()
