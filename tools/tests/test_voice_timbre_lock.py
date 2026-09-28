"""VOICE_TIMBRE_LOCK (Roger 2026-09-28, E09 声线漂移): prompt binding, writer self-check, post-gen check."""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines" / "nalu" / "runtime" / "tools"))

from tools import voice_timbre_lock as vtl  # noqa: E402
from tools.sd2_provider_prompt_renderer import _beat_line, _delivery_text, _dialogue  # noqa: E402

POLICY = vtl.load_policy()


class VoiceTimbreLockPolicyTests(unittest.TestCase):
    def test_policy_exists_and_is_gated_by_episode(self):
        self.assertTrue(POLICY)
        start = int(POLICY["active_from_episode"])
        self.assertFalse(vtl.active_for(f"E{start - 1:02d}-VU-001"))
        self.assertTrue(vtl.active_for(f"E{start:02d}-VU-001"))
        self.assertFalse(vtl.active_for("UNIT-WITHOUT-EPISODE"))

    def test_longest_term_wins_without_overlap(self):
        found = [row["term"] for row in vtl.terms_in("他屏着气轻声说一句，又压着嗓子问")]
        self.assertEqual(found, ["屏着气", "轻声", "压着嗓子"])
        self.assertEqual(vtl.terms_in("他平静地说一句"), [])


class RendererBindingTests(unittest.TestCase):
    beat = {"dialogue": "秦铭：这不就是金缕玉衣吗？", "primary_action": "秦铭屏着气轻声说一句"}

    def test_without_slots_line_is_unchanged(self):
        text = _dialogue(self.beat)
        self.assertIn("秦铭只说一次：“这不就是金缕玉衣吗？”", text)
        self.assertNotIn("@音频", text)

    def test_slot_is_bound_at_the_line(self):
        text = _dialogue(self.beat, {"秦铭": "@音频1"})
        self.assertIn("秦铭（音色严格同@音频1）说：“这不就是金缕玉衣吗？”", text)

    def test_timbre_terms_are_replaced_not_annotated(self):
        slots = {"秦铭": "@音频1"}
        self.assertEqual(_delivery_text(self.beat, "primary_action", slots),
                         "秦铭音量极低、气息收住、音量低、音色不变地说一句")
        line = _beat_line({**self.beat, "start_seconds": 0, "end_seconds": 2, "entry_state": "坐着",
                           "force_origin": "秦铭", "exit_state": "坐着"}, slots)
        self.assertNotIn("屏着气", line)
        self.assertNotIn("轻声", line)
        # without a bound voice slot the writer's text reaches the provider unchanged
        self.assertEqual(_delivery_text(self.beat, "primary_action", {}), "秦铭屏着气轻声说一句")

    def test_rewrite_keeps_phrases_grammatical(self):
        self.assertEqual(vtl.rewrite_delivery("冯易安压着嗓子一字一顿地问一句"),
                         "冯易安压低音量、语速放慢、音色不变，一字一顿地问一句")
        self.assertEqual(vtl.rewrite_delivery("陆泽激动得声音发颤地说一句"), "陆泽激动得气息不稳、音色不变地说一句")
        self.assertEqual(vtl.rewrite_delivery("杨永青扯着嗓子喊一句"), "杨永青提高音量、拉长呼喊、音色不变地喊一句")
        self.assertEqual(vtl.rewrite_delivery("秦铭平静地说一句"), "秦铭平静地说一句")


class WriterSelfcheckTests(unittest.TestCase):
    contract = {"shots": [
        {"shot_id": "E10-S01-01", "prompt_spec": {"dialogue": "冯易安：谁的口粮？",
                                                  "action": {"primary_action": "冯易安压着嗓子问一句"}}},
        {"shot_id": "E10-S01-02", "prompt_spec": {"dialogue": "",
                                                  "action": {"primary_action": "秦铭压着嗓子喘气"}}},
    ]}

    def test_flags_dialogue_shots_only_and_is_non_blocking_by_default(self):
        import nalu_writer_selfcheck_seq29 as w
        found = w.voice_timbre_findings(self.contract)
        self.assertEqual(found["codes"], ["R10_VOICE_TIMBRE_DIRECTION:E10-S01-01:压着嗓子"])
        self.assertFalse(found["blocking"])
        enforced = w.voice_timbre_findings({**self.contract, "voice_timbre_policy": {"enforced": True}})
        self.assertTrue(enforced["blocking"])


class UnitVoiceConsistencyTests(unittest.TestCase):
    cast = {"characters": {"CHAR-A": {"f0_band_hz": [170.0, 230.0]},
                           "CHAR-B": {"f0_band_hz": [120.0, 160.0]}}}
    names = {"甲": "CHAR-A", "乙": "CHAR-B"}
    policy = {"enabled": True, "band_extra_tolerance_ratio": 0.0, "min_attribution_similarity": 0.5,
              "reason_code": "VOICE_OUT_OF_BAND"}

    def _run(self, segments, expected, f0s):
        import unit_voice_consistency as u
        fake = types.SimpleNamespace(
            load_audio=lambda media: ([0.0], 48000),
            measure_segments=lambda samples, sr, segs: [{"f0_median_hz": f0s[i]} for i, _ in enumerate(segs)])
        original = u.engine_module
        u.engine_module = lambda name: fake
        try:
            return u.check_unit("E10-VU-001", Path("/dev/null"), segments, expected, self.cast, self.names, self.policy)
        finally:
            u.engine_module = original

    def test_single_speaker_out_of_band_fails_with_reason_code(self):
        result = self._run([{"start": 0, "end": 2, "text": "嗓子都快冒烟了"}],
                           [{"shot_id": "S1", "spoken_text": "甲：嗓子都快冒烟了。"}], [118.2])
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["failures"], ["VOICE_OUT_OF_BAND:CHAR-A:118.2"])

    def test_single_speaker_in_band_passes(self):
        result = self._run([{"start": 0, "end": 2, "text": "嗓子都快冒烟了"}],
                           [{"shot_id": "S1", "spoken_text": "甲：嗓子都快冒烟了。"}], [200.0])
        self.assertEqual(result["status"], "PASS")

    def test_multi_speaker_attributes_by_text_and_ambiguous_is_unverified(self):
        expected = [{"shot_id": "S1", "spoken_text": "甲：小叔最厉害了！"},
                    {"shot_id": "S2", "spoken_text": "乙：老许，巡山组的人来了。"}]
        result = self._run([{"start": 0, "end": 2, "text": "小叔最厉害了"},
                            {"start": 2, "end": 5, "text": "老许巡山组的人来了"}], expected, [200.0, 231.4])
        self.assertEqual(result["failures"], ["VOICE_OUT_OF_BAND:CHAR-B:231.4"])
        ambiguous = self._run([{"start": 0, "end": 2, "text": "嗯"}], expected, [200.0])
        self.assertEqual(ambiguous["status"], "UNVERIFIED")
        self.assertTrue(any(v.startswith("SPEAKER_UNATTRIBUTED") for v in ambiguous["unverified"]))

    def test_no_dialogue_is_not_applicable(self):
        self.assertEqual(self._run([], [], [])["status"], "NOT_APPLICABLE")


if __name__ == "__main__":
    unittest.main()
