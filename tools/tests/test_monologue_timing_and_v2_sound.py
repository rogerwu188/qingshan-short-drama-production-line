"""Owner 2026-11-02 (lab 化神 E01-VU-002): (A) a monologue group's lines run back to back -- the 4 s HopsAPI floor is
the generated unit's, not each line's; (B) a stamped V2 prompt's Sound section quotes no action / dialogue / redo
text, carries no empty "Only for shot :" prefix, and the redo instruction appears once."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for _path in (str(REPO), str(REPO / "tools"), str(REPO / "lines" / "nalu" / "runtime" / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import h3_director_prompt_v2 as v2  # noqa: E402
import speaking_unit_duration as sud  # noqa: E402

PLAN = {"shot_scale": "MEDIUM_CLOSE_UP", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A",
        "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "沈棠胸口以上居中"}


def shot(sid, text, plan=PLAN, who="CHAR-ST"):
    return {"shot_id": sid, "scene_id": "S01", "target_seconds": 4,
            "prompt_spec": {"dialogue": f"沈棠：{text}", "camera_plan": dict(plan),
                            "role_semantic_disambiguation": {"lip_owner_id": who, "dialogue_speaker_id": who},
                            "cast": [{"character_id": who}]}}


class MonologueGroupTimingTests(unittest.TestCase):
    def test_back_to_back_windows_floor_is_the_units(self):
        durations = sud.monologue_group_durations([2.303, 2.779, 2.541])  # lab 化神 E01-VU-002 estimates
        self.assertEqual(durations, [2.8, 3.1, 3.1])
        self.assertEqual(sum(durations), 9.0)  # was 4 + 4 + 4 = 12 with multi-second slack before every line
        self.assertEqual(sum(sud.monologue_group_durations([0.8, 0.7])), float(sud.MIN_SECONDS))
        self.assertTrue(float(sum(sud.monologue_group_durations([1.2, 2.0, 1.1]))).is_integer())

    def test_editorial_groups_only_continuous_action_same_setup(self):
        import build_nalu_preproduction as bnp
        shots = [shot("S1", "谢师弟还有空评价我，"), shot("S2", "看来睡得比我多，明天开始"), shot("S3", "我也睡一个半时辰好了。"),
                 shot("S4", "不练了！")]
        contract = {"shots": shots, "internal_transition_authoring": [
            {"from_shot_id": "S1", "to_shot_id": "S2", "transition_mode": "CONTINUOUS_ACTION"},
            {"from_shot_id": "S2", "to_shot_id": "S3", "transition_mode": "CONTINUOUS_ACTION"},
            {"from_shot_id": "S3", "to_shot_id": "S4", "transition_mode": "MOTIVATED_CUT"}]}
        rows = bnp.monologue_group_durations(contract, {}, "zh")
        self.assertEqual(sorted(rows), ["S1", "S2", "S3"])
        self.assertEqual(rows["S1"]["group_seconds"], 9.0)
        self.assertEqual(rows["S1"]["action"], "MONOLOGUE_GROUP_BACK_TO_BACK")
        moved = dict(PLAN, shot_scale="CLOSE_UP")
        contract["shots"][1] = shot("S2", "看来睡得比我多，明天开始", plan=moved)
        self.assertEqual(sorted(bnp.monologue_group_durations(contract, {}, "zh")), [])

    def test_short_line_is_an_advisory_not_a_padding_request(self):
        row = sud.speaking_duration(4, ["甲：叫您干嘛？"], "zh")
        self.assertEqual((row["duration_seconds"], row["advisory"]), (4.0, sud.SHORT_LINE_ADVISORY))
        self.assertNotIn("warning", row)


LAB_FOLEY = ('Only for shot E01-S01-03 : Close natural contact sounds from "Seated, Shen Tang straightens her back '
             'and calmly answers the offscreen criticism."  through clothing, footsteps and meditation cushion, '
             'recipe booklet')
LAB_ACTION_SOUND = ('Only for shot : Emphasise only  "Seated, Shen Tang straightens her back. The previous take added '
                    'unwanted words. Begin the exact authored line promptly, speak every word once."  one causal '
                    'contact sound ; NO_BGM')


class V2SoundSectionTests(unittest.TestCase):
    def test_sound_rows_are_plain_words(self):
        self.assertEqual(v2.sound_row_v2(LAB_FOLEY),
                         "Close natural contact sounds of clothing, footsteps and meditation cushion, recipe booklet")
        cleaned = v2.scrub(v2.sound_row_v2(LAB_ACTION_SOUND))
        self.assertEqual(cleaned, "Emphasise only one causal contact sound")
        self.assertNotIn('"', cleaned)
        self.assertNotIn("Only for shot", cleaned)

    def test_short_quotes_survive_long_ones_are_unquoted(self):
        self.assertEqual(v2._unquote_long('a "bell" rings'), 'a "bell" rings')
        self.assertEqual(v2._unquote_long('state "Shen Tang sits on the cushion, booklet before her knees."'),
                         "state Shen Tang sits on the cushion, booklet before her knees")

    def test_self_check_flags_a_long_quoted_sentence_outside_dialogue(self):
        text = ('Sound: Emphasise only "Seated, Shen Tang straightens her back and answers." one sound.\n'
                '1. Shentang: <d>[Chinese] "谢师弟还有空评价我 and some more words here too"</d>')
        self.assertEqual(v2.long_quoted_spans(text), ["Seated, Shen Tang straightens her back and answers."])
        findings = v2.director_v2_self_check(text, {}, {}, stamped=True)
        self.assertTrue(any(f.startswith("QUOTED_SENTENCE_IN_PROMPT:") for f in findings))
        self.assertFalse(any(f.startswith("QUOTED_SENTENCE") for f in v2.director_v2_self_check(text, {}, {})))

    def test_renderer_wiring_is_stamped_only(self):
        src = (REPO / "tools" / "h3_director_prompt_v2.py").read_text(encoding="utf-8")
        self.assertIn("scrub(sound_row_v2(value) if stamped else value)", src)
        self.assertIn("if stamped:  # a sentence repeated in every beat", src)
        self.assertIn("if stamped and _BRIDGE_RESTATEMENT.search(bridge)", src)


if __name__ == "__main__":
    unittest.main()
