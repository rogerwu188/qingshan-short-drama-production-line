"""E27 prompt / director round (device 1101, 2026-11-25): zero credits, no new blocking gate.

Covers: the vertical shot grammar of the BILI_V1 director pass on compiler-scaled shots (MCU single default, hardest
line tightest, DP9 floor and ceiling kept, no run of 3 identical framings, writer-authored scales untouched); the
per-unit micro-performance timeline (trigger word, per-character emotion curve, softened jumps, disfluency by
psychology on the hardest word, grief formula) compiled into the contract and rendered time-coded into the H3 prompt
(V1 and V2, no Chinese outside the dialogue, LEGACY untouched); the script-doctor advisories (warnings only); the
BILI_V1 writer section carrying the opening formula and the four script-doctor questions.  Offline, no paid call."""
from __future__ import annotations

import copy
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import bili_adaptation_check as bac  # noqa: E402
import director_pass as dp  # noqa: E402
import nalu_craft_standard as craft  # noqa: E402
import performance_timeline as ptl  # noqa: E402
import screenplay_compile as spc  # noqa: E402
from tools import direction_policy_gate as dpg  # noqa: E402
from tools.h3_provider_prompt_renderer import render_h3_prompt  # noqa: E402
from tools.tests.test_h3_director_prompt_v2 import A, B, fixture  # noqa: E402

FIXTURE = ROOT / "tools" / "tests" / "fixtures" / "screenplay_e25"
DP9 = {"cu_mcu_max_episode_ratio": 0.8, "min_group_shots_per_multi_character_scene": 2}
CJK = re.compile(r"[㐀-鿿]")


def compiled() -> dict:
    return spc.compile_files(FIXTURE, "E25")


# --------------------------------------------------------------------------- shot grammar
def line_shot(sid: str, scene: str, speaker: str, listener: str, line: str, *, role: str = "LINE",
              push: bool = False, named: bool = False) -> dict:
    plan = {"shot_scale": "MEDIUM", "scale_source": "screenplay_compile", "motion_family": "DOLLY" if push else "LOCKED",
            "motion_direction": "PUSH_IN" if push else "NONE",
            "start_framing": f"{speaker}在殿内，{listener}的后脑与肩在前景虚化，冷光", "end_framing": "x"}
    return {"shot_id": sid, "scene_id": scene, "shot_size": "MEDIUM", "target_seconds": 4.0,
            "camera": f"MEDIUM，固定机位，过肩{listener}",
            "prompt_spec": {"dialogue": f"{speaker}：{line}", "beat_role": role, "camera_plan": plan,
                            "cast": [{"character": speaker, "character_id": speaker,
                                      "face_visibility": "FRONT_FACE_VISIBLE"},
                                     {"character": listener, "character_id": listener,
                                      "face_visibility": "BACK_AND_SHOULDERS_ONLY"}],
                            "action": {"primary_action": f"{speaker}按住桌沿" + (f"，{listener}站在对面" if named else ""),
                                       "field_sources": {"primary_action": "screenplay"}},
                            "role_semantic_disambiguation": {
                                "dialogue_speaker_id": speaker, "dialogue_listener_id": listener,
                                "entity_presence": {speaker: "VISIBLE_AND_IDENTITY_LOCKED",
                                                    listener: "VISIBLE_AND_IDENTITY_LOCKED"}}}}


def scene_contract(n: int = 6) -> dict:
    shots = []
    for i in range(1, n + 1):
        who, other = (A, B) if i % 2 else (B, A)
        shots.append(line_shot(f"E09-S01-{i:02d}", "E09-S01", who, other, f"第{i}句台词。",
                               role="TURN" if i == n - 1 else "LINE", push=i == n - 1))
    return {"episode": "E09", "craft_profile": "BILI_V1", "shots": shots,
            "character_entities": [{"character_id": A, "canonical_name": A}, {"character_id": B, "canonical_name": B}]}


def kinds(contract: dict) -> list[tuple[str, str]]:
    return [(dp._scale(s), dp._frame_kind(s)) for s in contract["shots"]]


class ShotGrammarTest(unittest.TestCase):
    def test_singles_by_default_hardest_tightest_floor_kept(self):
        out, report = dp.direct(scene_contract(), force=True)
        rows = kinds(out)
        self.assertEqual(rows[4], ("CLOSE_UP", "SINGLE"))                       # the #转折 line
        self.assertGreaterEqual(sum(1 for _, k in rows if k != "SINGLE"), 2)    # DP9 floor
        self.assertGreaterEqual(sum(1 for r in rows if r == ("MEDIUM_CLOSE_UP", "SINGLE")), 1)
        for a, b, c in zip(rows, rows[1:], rows[2:]):
            self.assertFalse(a == b == c, rows)
        self.assertEqual(dpg._dp9_coverage_floor(out["shots"], DP9)[0], [])
        self.assertTrue(any(a.startswith("SHOT_GRAMMAR:") for a in report["applied"]))
        hard = out["shots"][4]
        self.assertEqual(hard["shot_size"], "CLOSE_UP")
        self.assertNotIn("过肩", hard["camera"])
        self.assertNotIn("后脑与肩", hard["prompt_spec"]["camera_plan"]["start_framing"])
        self.assertNotIn(B if hard["prompt_spec"]["role_semantic_disambiguation"]["dialogue_speaker_id"] == A else A,
                         dp.visible_cast(hard))
        self.assertEqual(hard["prompt_spec"]["director"]["shot_grammar"]["scale"], "CLOSE_UP")

    def test_named_listener_is_never_removed(self):
        c = scene_contract(3)
        for shot in c["shots"]:
            shot.update(line_shot(shot["shot_id"], shot["scene_id"],
                                  shot["prompt_spec"]["role_semantic_disambiguation"]["dialogue_speaker_id"],
                                  shot["prompt_spec"]["role_semantic_disambiguation"]["dialogue_listener_id"],
                                  "台词。", named=True))
        out, _ = dp.direct(c, force=True)
        for shot in out["shots"]:
            self.assertEqual(len(dp.visible_cast(shot)), 2)

    def test_dp9_ceiling_is_kept(self):
        c = scene_contract(10)
        out, _ = dp.direct(c, force=True)
        ratio = sum(1 for s in out["shots"] if dp._scale(s) in dp._CU_MCU) / len(out["shots"])
        self.assertLessEqual(ratio, 0.8)

    def test_writer_authored_scales_are_untouched(self):
        c = scene_contract()
        for shot in c["shots"]:
            shot["prompt_spec"]["camera_plan"].pop("scale_source")
        out, report = dp.direct(c, force=True)
        self.assertEqual({dp._scale(s) for s in out["shots"]}, {"MEDIUM"})
        self.assertFalse(any(a.startswith("SHOT_GRAMMAR") for a in report["applied"]))

    def test_compiled_e25_mixes_sizes_and_passes_dp9(self):
        out = compiled()
        contract = out["contract"]
        self.assertTrue(all(s["prompt_spec"]["camera_plan"].get("scale_source") == "screenplay_compile"
                            for s in contract["shots"]))
        directed, report = dp.direct(contract, force=True)
        self.assertEqual(report["integrity_failures"], [])
        self.assertEqual(dpg._dp9_coverage_floor(directed["shots"], DP9)[0], [])
        rows = kinds(directed)
        self.assertGreater(sum(1 for s, _ in rows if s == "MEDIUM_CLOSE_UP"), sum(1 for s, _ in rows if s == "MEDIUM"))
        for a, b, c in zip(rows, rows[1:], rows[2:]):
            self.assertFalse(a == b == c and a[0] in ("MEDIUM_CLOSE_UP", "CLOSE_UP"), rows)


# --------------------------------------------------------------------------- micro-performance
class TimelineTest(unittest.TestCase):
    def test_every_lexicon_emotion_has_a_row(self):
        for word in spc.emotion_lexicon()["emotions"]:
            self.assertTrue(ptl.emotion_row(word).get("change_en"), word)

    def test_trigger_word_prefers_a_name_then_hard_words(self):
        self.assertEqual(ptl.trigger_word("你还说他偷？", ["阿夜"])[0], "偷")
        self.assertEqual(ptl.trigger_word("阿夜，你还说他偷？", ["阿夜"]), ("阿夜", 0))

    def test_three_beats_and_the_curve_carries_exit_into_entry(self):
        curve = ptl.EmotionCurve()
        first = ptl.build(who=A, emotion="怒", emotion_en="angry", line="东西认得主人。你还说他偷？",
                          listener_name="掌门", curve=curve)
        self.assertEqual([b["kind"] for b in first["beats"]], ["ENTRY", "CHANGE", "EXIT"])
        self.assertEqual(first["beats"][0]["from"], 0.0)
        self.assertEqual(first["beats"][-1]["to"], 1.0)
        self.assertIn("AU4", first["beats"][1]["en"])
        self.assertTrue(first["beats"][1]["en"].index("brows") < first["beats"][1]["en"].index("AU4"))
        second = ptl.build(who=A, emotion="急", emotion_en="urgent", line="冤枉你的人，不用赔罪？", curve=curve)
        self.assertEqual(second["curve"], "carried")
        self.assertIn("holds the stare", second["beats"][0]["en"])

    def test_a_jump_across_the_ladder_is_softened_and_recorded(self):
        curve = ptl.EmotionCurve()
        ptl.build(who=A, emotion="怒", emotion_en="angry", line="滚出去！", curve=curve)
        jumped = ptl.build(who=A, emotion="哀", emotion_en="grieving", line="我只是想见他。", curve=curve)
        self.assertEqual(jumped["curve"], "softened_jump")
        self.assertIn("starting to give way", jumped["beats"][0]["en"])
        self.assertTrue(curve.jumps)

    def test_grief_formula(self):
        tl = ptl.build(who=A, emotion="哀", emotion_en="grieving", line="他不会回来了。")
        text = " ".join(b["en"] for b in tl["beats"])
        for needle in ("red-rimmed eyes without tears", "less than half a second", "hard swallow"):
            self.assertIn(needle, text)
        self.assertNotIn("tears stream", text)

    def test_disfluency_by_psychology_on_the_hardest_word_capped(self):
        curve = ptl.EmotionCurve()
        shame = ptl.build(who=A, emotion="愧", emotion_en="ashamed", line="是我……对不起你。", curve=curve, hardest=True)
        self.assertEqual(shame["disfluency"]["psychology"], "shame")
        self.assertEqual(shame["disfluency"]["word"], "对不起")
        self.assertIn("failed inhale", shame["beats"][1]["en"])
        self.assertEqual(ptl.psychology("冷", "改口", "没什么"), "hiding")
        self.assertEqual(ptl.psychology("急", "", "我没有偷"), "misunderstood")
        self.assertEqual(ptl.psychology("急", "", "快走"), "")
        ptl.build(who=B, emotion="惊", emotion_en="shocked", line="你说什么？", curve=curve, hardest=True)
        third = ptl.build(who=A, emotion="羞", emotion_en="shy", line="我不是故意的。", curve=curve, hardest=True)
        self.assertIsNone(third["disfluency"])   # cap: 2 per scene
        for beat in shame["beats"]:
            self.assertFalse(CJK.search(beat["en"]), beat["en"])

    def test_compile_writes_the_timeline_and_the_directing_line(self):
        out = compiled()
        speaking = [s for s in out["contract"]["shots"] if s.get("dialogue")
                    and not s["prompt_spec"].get("offscreen_character_ids")]
        self.assertTrue(speaking)
        for shot in speaking:
            timeline = shot["prompt_spec"]["action"]["performance"]["timeline"]
            self.assertEqual(len(timeline["beats"]), 3)
        self.assertIn("表演分拍：", out["directing_md"])


# --------------------------------------------------------------------------- H3 render
def _with_timeline(unit: dict, *, bili: bool) -> dict:
    spec = unit["ordered_prompt_specs"][0]
    spec["action"] = {"performance": {"emotion": "哀", "timeline": ptl.build(
        who=A, emotion="哀", emotion_en="grieving", line="你还说他偷？", hardest=True)}}
    if bili:
        unit["craft_profile"] = "BILI_V1"
    return unit


def _outside_dialogue(text: str) -> str:
    return re.sub(r"<d>.*?</d>", "", text, flags=re.S)


class RenderTimelineTest(unittest.TestCase):
    def test_v2_prints_time_coded_beats_without_chinese(self):
        unit, plan = fixture()
        text, _ = render_h3_prompt(_with_timeline(unit, bili=True), plan)
        self.assertIn("Performance, played as visible changes", text)
        self.assertRegex(text, r"0–\d(\.\d)? s, Alpha: red-rimmed eyes")
        self.assertIn("on the stressed word at about", text)
        self.assertIn("looks at Beta for less than half a second", text)
        self.assertLess(text.index("Performance, played"), text.index("End:"))
        self.assertFalse(CJK.search(_outside_dialogue(text)))
        self.assertIn("subtitles", text)

    def test_v1_prints_the_timeline(self):
        unit, plan = fixture(director=False)
        text, _ = render_h3_prompt(_with_timeline(unit, bili=True), plan)
        self.assertIn("Performance, played as visible changes", text)
        self.assertFalse(CJK.search(_outside_dialogue(text)))

    def test_legacy_ignores_the_timeline(self):
        unit, plan = fixture()
        plain = _with_timeline(copy.deepcopy(unit), bili=False)
        plain["ordered_prompt_specs"][0]["action"]["performance"].pop("timeline")
        before, _ = render_h3_prompt(plain, plan)
        after, _ = render_h3_prompt(_with_timeline(unit, bili=False), plan)
        self.assertNotIn("Performance, played", after)
        self.assertEqual(before, after)


# --------------------------------------------------------------------------- writer layer
class ScriptDoctorTest(unittest.TestCase):
    def test_the_four_questions_are_warnings(self):
        contract = {
            "protagonist_ids": [A],
            "pacing": {"scene_plan": [{"scene_id": "S01", "objective": "", "objective_owner": B,
                                       "turn_shot_id": "S01-03"}]},
            "shots": [
                {"shot_id": "S01-01", "scene_id": "S01", "target_seconds": 6,
                 "prompt_spec": {"dialogue": "甲：天兵已经压境，大军三日后到。", "beat_role": "LINE"}},
                {"shot_id": "S01-02", "scene_id": "S01", "target_seconds": 6,
                 "prompt_spec": {"dialogue": "乙：据说北境已经失守多年。", "beat_role": "LINE"}},
                {"shot_id": "S01-03", "scene_id": "S01", "target_seconds": 4,
                 "prompt_spec": {"dialogue": "甲：原来是你。", "beat_role": "TURN",
                                 "action": {"field_sources": {"primary_action": "fallback"}}}},
            ]}
        doctor = bac.script_doctor(contract)
        codes = [w.split(":")[0] for w in doctor["warnings"]]
        for code in ("DOCTOR_FIRST_HIT_LATE", "DOCTOR_SCENE_EXPLAINS_ONLY", "DOCTOR_GOAL_UNCLEAR",
                     "DOCTOR_TURN_ON_EMPTY_LINE"):
            self.assertIn(code, codes)
            self.assertIn(code, bac.FIXES)
        result = bac.check(contract, "zh", ["S01"], [])
        self.assertFalse([f for f in result["failures"] if f.startswith("DOCTOR_")])
        self.assertTrue([w for w in result["warnings"] if w.startswith("DOCTOR_")])

    def test_bili_writer_section_carries_the_formula_and_questions(self):
        section = craft.codex_section(ROOT, craft_profile="BILI_V1")
        for needle in ("异常事件→即时目标→致命规则→限时阻力", "第一个情绪点是否太晚", "空台词", "双人不是默认",
                       "中近景", "不连续超过 2 镜", "最难的那个词"):
            self.assertIn(needle, section)
        self.assertLessEqual(len(section), craft.MAX_CODEX_SECTION_CHARS)
        production = (ROOT / "skills/nalu-claude-code/CLAUDE_CODE_PRODUCTION.md").read_text(encoding="utf-8")
        for needle in ("异常事件 → 即时目标", "第一个情绪点是不是太晚", "保护层逐步失效"):
            self.assertIn(needle, production)


if __name__ == "__main__":
    unittest.main()
