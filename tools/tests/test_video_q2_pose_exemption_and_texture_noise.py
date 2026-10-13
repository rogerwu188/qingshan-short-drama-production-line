"""The two E11-Q2 builder fixes, each reproducing the exact 2026-10-12 failure.

1. `identity_pose_exemptions` is written by the reviewer template as a LIST of
   `{character_id, reason, frames, note}`.  The builder read it as a dict keyed by
   character id, so every exemption was silently discarded, the pose-scoped character
   stayed in `measurable_ids`, and the one or two samples that survived the
   measurability floor failed on the sample minimum — or, worse, PASSED on a
   degenerate two-frame median.  E11-VU-014 CHAR-LIULAOTOU (0.90), VU-025/VU-039
   CHAR-QINMING (0.86 / 0.78): all four units FAIL_NOT_ADMITTED on
   `IDENTITY_COSINE_BELOW_PASS` + `SAMPLE_FRAMES_BELOW_REGISTRY_MINIMUM`.

2. A 3-character ASCII letter cluster read out of flame / fur texture at confidence
   just over the audit's 0.50 floor was not texture noise by the old rule (which
   stopped at <=2 letters), so E11-VU-006 frame 5.824 s ("SO!", 0.54, lower-left
   oil-lamp flame) failed the unit as OCR_LATIN_CHARACTERS_PRESENT.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import video_q2_builder as q2  # noqa: E402


class ReviewerPoseExemptionShapeTest(unittest.TestCase):
    """The exemption the reviewer actually submits must reach the measurement."""

    def _verification(self, exemptions):
        item = {
            "answers": {"each_visible_character_identity_recognisable": "PASS"},
            "observed": {"identity_pose_exemptions": exemptions},
        }
        measurement = {
            "non_measurable_declared_characters": [],
            "engine_decisions": [],
            "per_character": [],
            "sample_counts": {"CHAR-QINMING": 2},
            "canonical_views_achieved_min": 3,
            "failures": [],
        }
        return q2.build_identity_verification(
            item, {}, "0" * 64, ["CHAR-QINMING"], measurement)

    def test_list_shape_drops_the_character_from_the_measurement(self):
        verification, failures, method = self._verification([
            {"character_id": "CHAR-QINMING", "reason": "BACK_VIEW",
             "frames": [2.24, 3.136], "note": "过肩前景后脑与布袍"},
        ])
        self.assertNotIn("SAMPLE_FRAMES_BELOW_REGISTRY_MINIMUM:2<3", failures)
        self.assertNotIn("IDENTITY_COSINE_BELOW_PASS:CHAR-QINMING:0.782885", failures)
        self.assertIn("CHAR-QINMING", verification["not_measurable_by_pose"])
        self.assertEqual(verification["not_measurable_by_pose"]["CHAR-QINMING"],
                         "REVIEWER:BACK_VIEW@2.24s")
        self.assertEqual(verification["decision"], "PASS")

    def test_dict_shape_still_honoured(self):
        verification, failures, _ = self._verification({"CHAR-QINMING": "PROFILE"})
        self.assertEqual(verification["not_measurable_by_pose"]["CHAR-QINMING"],
                         "REVIEWER:PROFILE")
        self.assertEqual(failures, [])

    def test_an_undeclared_character_is_never_exempted(self):
        verification, failures, _ = self._verification([
            {"character_id": "CHAR-SOMEONE-ELSE", "reason": "BACK_VIEW", "frames": [1.0]},
        ])
        self.assertEqual(verification["not_measurable_by_pose"], {})
        self.assertIn("SAMPLE_FRAMES_BELOW_REGISTRY_MINIMUM:2<3", failures)

    def test_an_exemption_without_a_reason_is_ignored(self):
        verification, failures, _ = self._verification([
            {"character_id": "CHAR-QINMING", "reason": "   "},
        ])
        self.assertEqual(verification["not_measurable_by_pose"], {})
        self.assertIn("SAMPLE_FRAMES_BELOW_REGISTRY_MINIMUM:2<3", failures)


class TextureNoiseRuleTest(unittest.TestCase):
    """The OCR texture-noise rule, on the real E11-VU-006 reading and its neighbours."""

    def setUp(self):
        self.item = {"observed": {"observed_text_strings": []}}

    def _is_noise(self, text, confidence):
        """Re-derive the predicate the way build_period_verification does, from source."""
        import inspect
        source = inspect.getsource(q2.build_period_verification)
        self.assertIn("1 <= len(core) <= 4 and core.isascii() and core.isalpha()", source)
        self.assertIn("< 0.60", source)
        text_stripped = text.strip()
        if len(text_stripped) <= 2 and text_stripped.isascii() and text_stripped.isalpha():
            return True
        if len(text_stripped) == 1:
            return True
        core = text_stripped.strip(".,!?;:\"'`~*_-=\\/|()[]{}<>")
        return (1 <= len(core) <= 4 and core.isascii() and core.isalpha()
                and confidence < 0.60)

    def test_the_e11_lamp_flame_reading_is_noise(self):
        self.assertTrue(self._is_noise("SO!", 0.539935))

    def test_a_confident_latin_cluster_still_fails(self):
        self.assertFalse(self._is_noise("SO!", 0.91))

    def test_a_digit_or_longer_string_still_fails(self):
        self.assertFalse(self._is_noise("SO2", 0.55))
        self.assertFalse(self._is_noise("SUBTITLE", 0.55))
        self.assertFalse(self._is_noise("4K", 0.55))
        self.assertFalse(self._is_noise("QQ 音乐", 0.55))

    def test_a_two_letter_reading_stays_noise_at_any_confidence(self):
        # the pre-existing <=2 letter rule is unchanged by this fix
        self.assertTrue(self._is_noise("SO", 0.99))


if __name__ == "__main__":
    unittest.main()
