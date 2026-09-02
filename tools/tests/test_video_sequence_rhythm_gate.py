import unittest

from tools.video_sequence_rhythm_gate import validate_combat_sequence_rhythm


def _combat(duration: float, index: int, *, override: bool = False) -> dict:
    row = {
        "unit_id": f"VU-{index}",
        "scene_id": "S-COMBAT",
        "duration_seconds": duration,
        "action_classification": "COMBAT",
        "ordered_prompt_specs": [],
    }
    if override:
        row["combat_rhythm_override"] = {
            "status": "APPROVED",
            "reason": "Deliberate metronomic montage established by the director",
            "approved_by": "DIRECTOR",
        }
    return row


class VideoSequenceRhythmGateTest(unittest.TestCase):
    def test_five_identical_short_combat_units_fail(self) -> None:
        report = validate_combat_sequence_rhythm([_combat(4, index) for index in range(5)])
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("DURATION_VARIETY_MISSING" in row for row in report["failures"]))
        self.assertTrue(any("EXCHANGE_MISSING" in row for row in report["failures"]))
        self.assertTrue(any("IDENTICAL_DURATION_RUN" in row for row in report["failures"]))

    def test_contrast_and_exchange_pass(self) -> None:
        report = validate_combat_sequence_rhythm([
            _combat(duration, index) for index, duration in enumerate((4, 4, 4, 4, 8), 1)
        ])
        self.assertEqual(report["status"], "PASS", report["failures"])
        sequence = report["sequences"][0]
        self.assertEqual(sequence["duration_distribution"], {4.0: 4, 8.0: 1})
        self.assertIn("camera_signature_distribution", sequence)
        self.assertEqual(
            sequence["camera_distribution_policy"],
            "PRE_SUBMISSION_OBSERVABILITY_ONLY_NO_AUTOMATIC_SHOT_TYPE_MUTATION",
        )

    def test_named_director_override_is_auditable(self) -> None:
        report = validate_combat_sequence_rhythm([
            _combat(4, index, override=True) for index in range(5)
        ])
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["sequences"][0]["approved_override"])


if __name__ == "__main__":
    unittest.main()
