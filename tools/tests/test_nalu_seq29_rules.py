"""SUPERVISOR_ORDERS seq=29 (Roger 2026-09-18 memo 九–十四): rule 5 shot length follows the line and no
hold instructions, rule 6 realised speech rate vs the director target, rule 7 performance triad /
emotion lexicon / no three-in-a-row, rule 8 only when authorised; compiler puts performance first
and constraints last."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
sys.path.insert(0, str(TOOLS)); sys.path.insert(0, str(ROOT))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod; spec.loader.exec_module(mod)
    return mod


with patch.dict(os.environ, {
    "NALU_ENGINE_ROOT": str(ROOT),
    "NALU_RUNTIME_ROOT": tempfile.mkdtemp(),
}):
    npr = load("nalu_prompt_rules", TOOLS / "nalu_prompt_rules.py")
    W = load("nalu_writer_selfcheck_seq29", TOOLS / "nalu_writer_selfcheck_seq29.py")
    S = load("speech_rate_check", TOOLS / "speech_rate_check.py")
    C = load("compile_grouped_seedance_manifest", ROOT / "tools/compile_grouped_seedance_manifest.py")


def shot(sid, scene, seconds, dialogue="", emotion=None, body="手指敲桌", delivery="咬字短促", action="他压着火说话", cps=5.0, speaker="CHAR-A", hook=False):
    spec = {"dialogue": dialogue, "action": {"primary_action": action, "start_state": "s", "end_state": "e"},
            "role_semantic_disambiguation": {"dialogue_speaker_id": speaker if dialogue else ""}, "cast": [{"character": "甲", "character_id": speaker}]}
    if emotion is not None:
        spec["action"]["performance"] = {"emotion": emotion, "body_action": body, "delivery": delivery}
    row = {"shot_id": sid, "scene_id": scene, "target_seconds": seconds, "prompt_spec": spec, "pacing_flags": {"hook": hook}}
    if dialogue:
        row["dialogue_delivery"] = {"chinese_characters_per_second": cps}
    return row


class Rule5(unittest.TestCase):
    def test_ten_chars_at_five_cps_is_two_and_a_half_seconds(self):
        self.assertEqual(npr.min_dialogue_seconds("白衣巷不如红衣巷敞亮", 5.0), 2.5)   # 10 chars, speaker prefix stripped by callers
        self.assertEqual(npr.min_dialogue_seconds("十个字十个字十个字十", 5.0), 2.5)
        self.assertEqual(npr.min_dialogue_seconds("十一个字十一个字十一个", 5.0), 3.0)

    def test_template_duration_and_hold_words_fail(self):
        c = {"episode": "E06", "writer_selfcheck_seq29": {"enforced": True}, "character_entities": [],
             "shots": [shot("E06-S01-01", "E06-S01", 5.0, "甲：十个字十个字十个字十", emotion="急"),
                       shot("E06-S01-02", "E06-S01", 2.5, "甲：十个字十个字十个字十", emotion="怒", action="说完后口型闭合、动作保持"),
                       shot("E06-S01-03", "E06-S01", 6.0)]}
        r = W.evaluate(c)
        codes = {f.split(":")[0] for f in r["failures"]}
        self.assertEqual(r["status"], "FAIL"); self.assertTrue(r["enforced"])
        self.assertIn("R5A_DIALOGUE_SHOT_TEMPLATE_DURATION", codes)
        self.assertIn("R5B_ACTION_HOLD_INSTRUCTION", codes)
        self.assertIn("R5C_NO_DIALOGUE_SHOT_OVER_5S", codes)


class Rule7(unittest.TestCase):
    def test_performance_triad_lexicon_and_three_in_a_row(self):
        c = {"episode": "E06", "writer_selfcheck_seq29": {"enforced": True},
             "character_entities": [{"character_id": "CHAR-KID", "apparent_age_range": "5-7"}],
             "shots": [shot("E06-S02-01", "E06-S02", 2.5, "甲：十个字十个字十个字十", emotion="疑", body="点头"),
                       shot("E06-S02-02", "E06-S02", 2.5, "甲：十个字十个字十个字十", emotion="平静"),
                       shot("E06-S02-03", "E06-S02", 2.5, "甲：十个字十个字十个字十", emotion="喜"),
                       shot("E06-S02-04", "E06-S02", 2.5, "甲：十个字十个字十个字十", emotion="喜"),
                       shot("E06-S02-05", "E06-S02", 2.5, "甲：十个字十个字十个字十", emotion="喜"),
                       shot("E06-S02-06", "E06-S02", 3.0, "娃：十个字十个字十个字十", cps=3.5, speaker="CHAR-KID", emotion="怯"),
                       shot("E06-S02-07", "E06-S02", 2.5, "甲：十个字十个字十个字十")]}
        r = W.evaluate(c); codes = [f.split(":")[0] for f in r["failures"]]
        self.assertIn("R5C_DIALOGUE_SHOT_WITHOUT_BODY_ACTION", codes)
        self.assertIn("R7C_EMOTION_NOT_IN_LEXICON", codes)
        self.assertIn("R7C_EMOTION_REPEATED_3_IN_SCENE", codes)
        self.assertIn("R7D_CHILD_SPEECH_RATE_TARGET_LOW", codes)
        self.assertIn("R7B_PERFORMANCE_MISSING", codes)

    def test_clean_contract_passes_and_rule8_is_info_unless_authorised(self):
        good = {"episode": "E06", "writer_selfcheck_seq29": {"enforced": True}, "character_entities": [],
                "shots": [shot("E06-S01-01", "E06-S01", 2.5, "甲：十个字十个字十个字十", emotion="急", hook=True),
                          shot("E06-S01-02", "E06-S01", 3.0)]}
        r = W.evaluate(good)
        self.assertEqual(r["status"], "PASS", r["failures"])
        self.assertTrue(any(w.startswith("RULE8_NOT_AUTHORISED_INFO:R8A") for w in r["warnings"]))
        good["writer_selfcheck_seq29"]["rule8_authorized"] = True
        r = W.evaluate(good); self.assertEqual(r["status"], "FAIL")
        self.assertTrue(any(f.startswith("R8A_PRESSURE_SOURCE_MISSING") for f in r["failures"]))
        legacy = {"episode": "E05", "shots": [shot("E05-S01-01", "E05-S01", 5.0, "甲：十个字十个字十个字十")]}
        r = W.evaluate(legacy); self.assertFalse(r["enforced"]); self.assertEqual(r["status"], "FAIL")


class Rule6(unittest.TestCase):
    def test_tiers(self):
        contract = {"shots": [shot("E06-S01-01", "E06-S01", 2.5, "甲：十个字十个字十个字十", cps=5.0),
                              shot("E06-S01-02", "E06-S01", 2.5, "甲：十个字十个字十个字十", cps=5.0, emotion="怒")]}
        targets = S.shot_targets(contract)
        seg = lambda chars, secs: [{"start": 0.0, "end": secs, "text": "字" * chars}]
        ok = S.measure_unit("U", seg(10, 2.0), [{"shot_id": "E06-S01-01"}], targets)
        self.assertEqual(ok["tier"], "OK"); self.assertEqual(ok["measured_cps"], 5.0)
        minor = S.measure_unit("U", seg(10, 2.6), [{"shot_id": "E06-S01-01"}], targets)
        self.assertEqual(minor["tier"], "MINOR"); self.assertEqual(minor["code"], "SPEECH_RATE_UNDER_TARGET")
        blocker = S.measure_unit("U", seg(10, 3.0), [{"shot_id": "E06-S01-01"}], targets)
        self.assertEqual(blocker["tier"], "BLOCKER"); self.assertIn("PERFORMANCE_INSTRUCTION_CHANGE", blocker["required_reroll_change"])
        conflict = S.measure_unit("U", seg(10, 2.6), [{"shot_id": "E06-S01-02"}], targets)
        self.assertEqual(conflict["tier"], "BLOCKER")   # conflict line: MINOR band becomes BLOCKER
        self.assertEqual(S.measure_unit("U", [], [], targets)["tier"], "NOT_APPLICABLE")
        summary = S.episode_summary([ok, blocker])
        self.assertEqual(summary["blocker"], ["U"]); self.assertLess(summary["mean_measured_cps"], 4.5); self.assertTrue(summary["below_episode_min"])
        self.assertIn("< 4.5", summary["checkpoint_line"])


class CompilerColumns(unittest.TestCase):
    def test_performance_leads_and_constraints_trail(self):
        base = {"action_kind": "DIALOGUE", "start_state": "起", "primary_action": "压着火说话", "completion_state": "说完起身",
                "contact_point": "无", "motion_direction": "前", "physical_causality": "因", "microexpression_design": "微", "physical_action_design": "设"}
        spec = {"dialogue": "甲：你来得，我朋友来不得？", "cast": [{"character": "甲"}], "props": [],
                "action": {**base, "performance": {"emotion": "怒", "body_action": "手指敲桌", "delivery": "咬字短促"}, "constraints": ["不出现字幕", "不出现雪地"]},
                "scene_state": {"time": "夜", "palette": "暖"}, "writer_camera_instruction": "推", "writer_shot_treatment": "近", "writer_expression_arc": "弧",
                "performance": {"psychological_state": "压着火", "emotion": "怒", "emotion_intensity": 3, "expression_arc": "沉→冷", "continuous_micro_action": "手指敲桌",
                                "event_reaction": "对方一句挑衅", "body_sync": "上身前倾"},
                "dialogue_delivery": {"pace": "快", "pause_map": "无", "emphasis_words": ["不配"], "volume_arc": "平→高", "breath_pattern": "短促", "delivery_transition": "无"}}
        timeline = {"start_seconds": 0, "end_seconds": 2.5}
        line = C.compact_beat_line(spec, timeline)
        self.assertLess(line.index("怒，手指敲桌，咬字短促"), line.index("压着火说话"))
        self.assertTrue(line.rstrip().endswith("禁：不出现字幕、不出现雪地。"))
        legacy = C.compact_beat_line({**spec, "action": base}, timeline)
        self.assertNotIn("禁：", legacy); self.assertIn("压着火说话", legacy)


if __name__ == "__main__":
    unittest.main()


class PostureContinuityR9Tests(unittest.TestCase):
    """D-68 (Roger seq=36): inside a scene the next shot's entry posture is the previous exit posture."""

    def setUp(self):
        import nalu_writer_selfcheck_seq29 as sc
        self.sc = sc

    def test_code_chain_and_word_jump(self):
        qm = {"cast": [{"character_id": "CHAR-QM"}]}
        shots = [
            {"shot_id": "S1-01", "scene_id": "S1", "prompt_spec": qm, "completion_state": "秦铭盘坐着闭眼",
             "state_delta_evidence": {"POSTURE": {"entry_code": "STANDING", "exit_code": "SEATED"}}},
            {"shot_id": "S1-02", "scene_id": "S1", "prompt_spec": qm, "entry_state": "秦铭站在磨盘旁",
             "state_delta_evidence": {"POSTURE": {"entry_code": "STANDING", "exit_code": "STANDING"}}},
            # a different character kneeling is NOT a jump for 秦铭
            {"shot_id": "S1-03", "scene_id": "S1", "prompt_spec": {"cast": [{"character_id": "CHAR-ZC"}]}, "entry_state": "周长裕跪在炕前"},
            # posture persists across a shot without posture words: 秦铭 is standing, then "蹲" jumps
            {"shot_id": "S1-04", "scene_id": "S1", "prompt_spec": qm, "entry_state": "秦铭攥紧双拳抬头", "completion_state": "秦铭攥拳"},
            {"shot_id": "S1-05", "scene_id": "S1", "prompt_spec": qm, "entry_state": "秦铭蹲身蓄力"},
        ]
        fails, warns = self.sc.posture_continuity_failures(shots)
        self.assertTrue(any(w.startswith("R9A_POSTURE_CODE_NOT_CONTINUOUS:S1-01->S1-02") for w in warns), warns)
        self.assertEqual([f.split(":")[1] for f in fails], ["S1-01->S1-02", "S1-04->S1-05"], fails)

    def test_continuous_and_scene_change_pass(self):
        shots = [
            {"shot_id": "S1-01", "scene_id": "S1", "prompt_spec": {"cast": [{"character_id": "CHAR-QM"}]}, "completion_state": "秦铭盘坐着闭眼",
             "state_delta_evidence": {"POSTURE": {"entry_code": "STANDING", "exit_code": "SEATED"}}},
            {"shot_id": "S1-02", "scene_id": "S1", "prompt_spec": {"cast": [{"character_id": "CHAR-QM"}]}, "entry_state": "秦铭盘坐着睁开眼睛",
             "state_delta_evidence": {"POSTURE": {"entry_code": "SEATED", "exit_code": "STANDING"}}},
            {"shot_id": "S2-01", "scene_id": "S2", "prompt_spec": {"cast": [{"character_id": "CHAR-QM"}]}, "entry_state": "秦铭站在街上"},
        ]
        self.assertEqual(self.sc.posture_continuity_failures(shots)[0], [])
        self.assertEqual(self.sc.posture_class("秦铭盘坐着"), "SIT")


class SameSubjectBoundaryTests(unittest.TestCase):
    def test_parity_flags_same_size_same_cast_boundary_only_in_scene(self):
        import final_cut_shot_plan_parity as par
        contract = {"shots": [
            {"shot_id": "A1", "shot_size": "中景", "prompt_spec": {"cast": [{"character_id": "CHAR-A"}]}},
            {"shot_id": "B1", "shot_size": "中景", "prompt_spec": {"cast": [{"character_id": "CHAR-A"}]}},
            {"shot_id": "C1", "shot_size": "中景", "prompt_spec": {"cast": [{"character_id": "CHAR-A"}]}},
        ]}
        plan = {"units": [{"unit_id": "U1", "scene_id": "S1", "editorial_shot_ids": ["A1"], "duration_seconds": 4},
                          {"unit_id": "U2", "scene_id": "S1", "editorial_shot_ids": ["B1"], "duration_seconds": 5},
                          {"unit_id": "U3", "scene_id": "S2", "editorial_shot_ids": ["C1"], "duration_seconds": 5}]}
        rows = par.same_subject_boundaries(contract, plan)
        self.assertEqual([(r["from_unit"], r["to_unit"], r["at_seconds"]) for r in rows], [("U1", "U2", 4.0)])
