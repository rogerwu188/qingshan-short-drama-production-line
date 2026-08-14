import unittest

from tools.container_duration_consistency_gate import evaluate


def clean(**overrides):
    payload = {
        "format_duration_s": 145.259,
        "video_stream_duration_s": 145.231,
        "audio_stream_duration_s": 145.259,
        "decoded_audio_duration_s": 145.259,
        "audio_measurement_method": "decoded_samples",
    }
    payload.update(overrides)
    return payload


class ContainerDurationConsistencyGateTests(unittest.TestCase):
    def test_clean_master_passes(self):
        result = evaluate(clean())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["failures"], [])
        self.assertNotIn("repair_recipe", result)

    def test_e39_regression_is_caught(self):
        # Actual measured E39 released master (CL2X-1015/1016).
        result = evaluate(
            clean(
                format_duration_s=149.479,
                audio_stream_duration_s=149.478,
                decoded_audio_duration_s=145.259,
            )
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["severity"], "BLOCK")
        self.assertTrue(
            any(f.startswith("container_duration_over_declared") for f in result["failures"])
        )
        self.assertTrue(
            any(f.startswith("audio_track_pts_inflated") for f in result["failures"])
        )
        self.assertIn("repair_recipe", result)

    def test_destructive_truncation_recipe_is_caught(self):
        # `-t <video_len>` produced a clean container but lost 4.2s of real audio.
        result = evaluate(
            clean(
                format_duration_s=145.231,
                audio_stream_duration_s=141.013,
                decoded_audio_duration_s=141.013,
            )
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(
            any(f.startswith("audio_tail_lost") for f in result["failures"])
        )

    def test_e37_and_e38r_released_masters_pass(self):
        # Live-probed values, decoded-sample method.
        for fmt, vid, aud in (
            (155.499, 155.499, 155.435),   # E37 release master V14
            (154.834, 154.833, 154.784),   # E38R replacement final (published)
        ):
            with self.subTest(fmt=fmt):
                result = evaluate(
                    clean(
                        format_duration_s=fmt,
                        video_stream_duration_s=vid,
                        audio_stream_duration_s=aud,
                        decoded_audio_duration_s=aud,
                    )
                )
                self.assertEqual(result["status"], "PASS", result["failures"])

    def test_audio_ending_slightly_early_is_advisory_not_fail(self):
        # E38 original FINAL: decoded audio 0.124s shorter than picture.
        # Frame-granularity artefact, not audience-perceptible -> advise, not block.
        result = evaluate(
            clean(
                format_duration_s=155.249,
                video_stream_duration_s=155.249,
                audio_stream_duration_s=155.210,
                decoded_audio_duration_s=155.125,
            )
        )
        self.assertEqual(result["status"], "PASS_WITH_ADVISORY")
        self.assertEqual(result["failures"], [])
        self.assertTrue(
            any(
                a.startswith("audio_ends_early_within_advise_band")
                for a in result["advisories"]
            )
        )

    def test_audio_running_past_picture_blocks(self):
        result = evaluate(
            clean(
                format_duration_s=145.231,
                video_stream_duration_s=145.231,
                audio_stream_duration_s=145.500,
                decoded_audio_duration_s=145.500,
            )
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(
            any(f.startswith("audio_runs_past_picture") for f in result["failures"])
        )

    def test_missing_measurement_fails_not_passes(self):
        payload = clean()
        payload.pop("decoded_audio_duration_s")
        result = evaluate(payload)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn(
            "measurement_missing:decoded_audio_duration_s", result["failures"]
        )

    def test_packet_pts_measurement_is_rejected(self):
        result = evaluate(clean(audio_measurement_method="packet_pts"))
        self.assertEqual(result["status"], "FAIL")
        self.assertIn(
            "untrustworthy_audio_measurement_method:packet_pts", result["failures"]
        )

    def test_ffmpeg_null_muxer_measurement_is_rejected(self):
        result = evaluate(clean(audio_measurement_method="ffmpeg_null_muxer"))
        self.assertEqual(result["status"], "FAIL")

    def test_under_declared_container_also_fails(self):
        result = evaluate(clean(format_duration_s=143.0))
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(
            any(
                f.startswith("container_duration_under_declared")
                for f in result["failures"]
            )
        )

    def test_within_tolerance_is_pass(self):
        result = evaluate(clean(format_duration_s=145.320))
        self.assertEqual(result["status"], "PASS")

    def test_non_object_payload_fails(self):
        result = evaluate(["not", "a", "dict"])
        self.assertEqual(result["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
