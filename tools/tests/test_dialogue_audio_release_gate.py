import unittest

from tools.dialogue_audio_release_gate import evaluate


def fixtures():
    evidence = {
        "status": "PASS",
        "dialogue_audio_claimed": True,
        "expected_dialogue_count": 1,
        "verified_dialogue_count": 1,
        "role_bound_count": 1,
        "final_sha256": "abc",
    }
    audio_manifest = {
        "rows": [
            {
                "dialogue_id": "DIA-001",
                "speaker": "A",
                "text": "line",
                "fitted_file": "/tmp/not-used.wav",
                "fitted_sha256": "0" * 64,
            }
        ]
    }
    asr_report = {
        "status": "PASS",
        "rows": [
            {"dialogue_id": "DIA-001", "speech_present": True, "status": "PASS"}
        ],
    }
    return evidence, audio_manifest, asr_report


class DialogueAudioReleaseGateTests(unittest.TestCase):
    def test_complete_dialogue_audio_passes(self):
        evidence, audio_manifest, asr_report = fixtures()
        result = evaluate(
            evidence,
            audio_manifest,
            asr_report,
            audio_stream_count=1,
            actual_video_sha256="abc",
            verify_audio_files=False,
        )
        self.assertEqual(result["status"], "PASS")

    def test_subtitles_cannot_replace_missing_audio(self):
        evidence, audio_manifest, asr_report = fixtures()
        evidence["dialogue_audio_claimed"] = False
        result = evaluate(
            evidence,
            audio_manifest,
            asr_report,
            audio_stream_count=1,
            actual_video_sha256="abc",
            verify_audio_files=False,
        )
        self.assertIn("dialogue_audio_not_claimed", result["failures"])

    def test_missing_final_audio_stream_fails(self):
        evidence, audio_manifest, asr_report = fixtures()
        result = evaluate(
            evidence,
            audio_manifest,
            asr_report,
            audio_stream_count=0,
            actual_video_sha256="abc",
            verify_audio_files=False,
        )
        self.assertIn("final_video_has_no_audio_stream", result["failures"])

    def test_failed_asr_line_fails(self):
        evidence, audio_manifest, asr_report = fixtures()
        asr_report["rows"][0]["speech_present"] = False
        asr_report["rows"][0]["status"] = "FAIL"
        result = evaluate(
            evidence,
            audio_manifest,
            asr_report,
            audio_stream_count=1,
            actual_video_sha256="abc",
            verify_audio_files=False,
        )
        self.assertIn("dialogue_not_audible:DIA-001", result["failures"])


if __name__ == "__main__":
    unittest.main()
