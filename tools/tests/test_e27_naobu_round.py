"""E27 脑补 round (device 1101, 2026-11-25, line owner feedback on E27): zero credits, no new blocking gate.

Covers: the silent units policy (a procedure-step silent shot folds into the adjacent line, readable silent beats --
tags, entrances -- stay, two silent shots in a row merge, what is left is a warning; the director pass reports the
same on any contract); the opening check (the scene's @see stakes put the bound character in the first shot); the
visual expansion (``@see`` / ``（画面）`` -> ``prompt_spec.visual`` + English twins -> H3 V1 / V2 sentences without
Chinese or appearance words, inside the rune limit; LEGACY untouched; keyframe takes the static facts); the
character-voice script-doctor advisories (warnings only); the writer guidance carrying the rules."""
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
import screenplay_compile as spc  # noqa: E402
from tools import bili_carry  # noqa: E402
from tools.h3_provider_prompt_renderer import _PROVIDER_RUNE_LIMIT, render_h3_prompt  # noqa: E402
from tools.tests.test_h3_director_prompt_v2 import A, B, fixture  # noqa: E402

CJK = re.compile(r"[㐀-鿿]")

CAST_PROPS = {
    "episode": "E27", "dialogue_language": "zh",
    "cast": [{"id": "CHAR-LINGYAO", "name": "凌瑶", "english_name": "Lingyao"},
             {"id": "CHAR-AYE", "name": "阿夜", "english_name": "Aye"},
             {"id": "CHAR-MASTER", "name": "掌门", "english_name": "the Master"}],
    "props": [{"id": "PROP-SWORD", "name": "飓风剑", "owner": "CHAR-LINGYAO", "hand": "右手", "description": "长剑",
               "description_en": "a longsword"},
              {"id": "PROP-ROPE", "name": "绑绳", "owner": "CHAR-AYE", "hand": "腕部", "description": "粗麻绳",
               "description_en": "a hemp rope"}],
    "locations": [{"id": "LOC-YARD", "name": "玄门宗静院", "time": "夜", "light": "冷夜光", "weather": "雷后阴",
                   "set_pieces": ["绑缚石柱", "木桌"], "ambience": "檐水滴落"}],
}
CARD = "@card goal[凌瑶]=带阿夜离开 | obstacle=掌门咬定他偷 | turn=法宝认主 | type=问罪→揭示 | source=阿夜还被绑在柱子上"
SEE = ("@see 赌注=阿夜双腕反绑在绑缚石柱上，额角带血；飓风剑摆在掌门面前的木桌上 | 环境=檐水成串滴在青石上，廊灯在风里晃 | "
       "凌瑶=说话前先把左手衣袖压平 | 掌门=指节一下下敲着桌沿")

# 1101 E27 S01 as written (silent procedure steps between the lines)
E27_S01 = "\n".join([
    "# E27", "", "## S01 玄门宗静院 · 夜 · 冷夜光", CARD,
    "掌门眼皮一跳，右手压住木桌。",
    "掌门（对凌瑶，先硬撑）：外门弟子，哪来的这等宝物？",
    "（无声）凌瑶右手接住滑到桌沿的飓风剑；掌门缩回右手。 #转折",
    "[掌门 反应：右手压住胸口]",
    "凌瑶看着掌门。",
    "凌瑶（对掌门，冷而清楚）：东西认得主人。你还说他偷？",
    "（无声）凌瑶右手用飓风剑划断阿夜腕边的绑绳，阿夜双膝落地，左手撑住石地。",
    "（无声）断开的粗麻绳落在石地，凌瑶右手收剑，阿夜抬手挡住冷光。",
    "阿夜右手攥着绑绳，抬眼看凌瑶。",
    "阿夜（对凌瑶，气短）：别管他们了。我只想离开。",
    "凌瑶蹲下，左手握住阿夜右腕。",
    "凌瑶（对阿夜，声音放柔）：冤枉你的人，不用赔罪？",
    "阿夜看着凌瑶。",
    "阿夜（对凌瑶，一字一顿）：我的真名是龙夜澈。 #揭示",
    "（无声）阿夜手肘一软向地面倒去，凌瑶左臂托住阿夜肩背。",
    "",
])


def compile_md(md: str, answers: dict | None = None, target: float = 10.0) -> dict:
    """A one-scene fixture: a 10 s brief target leaves the runtime budget free to fold (see RuntimeBudgetTest)."""
    return spc.compile_screenplay(spc.parse(md), copy.deepcopy(CAST_PROPS), {}, {}, episode="E27",
                                  translations=answers, en_fallback=True, brief={"target_seconds": target})


def s01(out: dict) -> list[dict]:
    return out["contract"]["shots"]


def silent(shots: list[dict]) -> list[dict]:
    return [s for s in shots if not s.get("dialogue")]


# --------------------------------------------------------------------------- silent units policy
class SilentPolicyTest(unittest.TestCase):
    def test_e27_s01_procedure_steps_fold_into_the_lines(self):
        out = compile_md(E27_S01)
        shots = s01(out)
        policy = out["report"]["silent_policy"]
        self.assertEqual(policy["scenes"][0], {"scene": "S01", "before": 4, "after": 1})
        self.assertEqual(len(shots), 6)
        self.assertEqual(len(silent(shots)), 1)
        # the #转折 sword catch now plays inside Lingyao's line, which keeps the turn (tightest shot + push)
        turn = next(s for s in shots if "东西认得主人" in (s.get("dialogue") or ""))
        self.assertIn("接住滑到桌沿的飓风剑", turn["prompt_spec"]["action"]["primary_action"])
        self.assertEqual(turn["prompt_spec"]["beat_role"], "TURN")
        self.assertEqual(turn["prompt_spec"]["camera_plan"]["motion_direction"], "PUSH_IN")
        self.assertEqual(turn["prompt_spec"]["action"]["folded_silent"][0]["where"], "next")
        # the silent shot's reaction is the line's listener reaction (no lead-in second added)
        self.assertIn("右手压住胸口", turn["prompt_spec"]["action"]["listener_reaction"])
        self.assertNotIn("lead_in_reaction", turn["prompt_spec"]["action"])
        # the collapse after the reveal folds back into the reveal line (the subject's own line)
        reveal = next(s for s in shots if "龙夜澈" in (s.get("dialogue") or ""))
        self.assertIn("手肘一软", reveal["prompt_spec"]["action"]["primary_action"])
        self.assertEqual(reveal["prompt_spec"]["beat_role"], "REVEAL")
        self.assertEqual(reveal["prompt_spec"]["action"]["folded_silent"][0]["where"], "prev")
        # no two silent units in a row; the step that cannot fit is reported, not blocked
        kinds = ["S" if not s.get("dialogue") else "D" for s in shots]
        self.assertNotIn("SS", "".join(kinds))
        self.assertIn("SILENT_PROCEDURE_KEPT:S01:L11", out["report"]["warnings"])
        self.assertEqual(out["report"]["status"], "PASS")
        self.assertIn("并入的无声动作（边说边做）", out["directing_md"])

    def test_readable_silent_beats_stay(self):
        md = "\n".join(["## S01 玄门宗静院 · 夜 · 冷夜光", CARD,
                        "（无声）掌门走进静院，停在木桌后。",
                        "掌门（对凌瑶）：你来做什么？",
                        "（无声）凌瑶把飓风剑拍在木桌上。 #爽点",
                        "凌瑶（对掌门）：来拿回我的东西。",
                        "（无声）阿夜抬起头，看着凌瑶的背影。 #反应", ""])
        out = compile_md(md)
        self.assertEqual(len(silent(s01(out))), 3)
        self.assertEqual(out["report"]["silent_policy"]["applied"], [])
        roles = [s["prompt_spec"]["beat_role"] for s in silent(s01(out))]
        self.assertEqual(roles, ["ACTION", "PAYOFF", "REACTION"])
        # entrance + payoff counted (reaction close-up exempt): over the per-scene budget -> a warning only
        self.assertIn("SILENT_UNITS_OVER:S01:2", out["report"]["warnings"])

    def test_two_silent_steps_merge_when_no_line_can_take_them(self):
        md = "\n".join(["## S01 玄门宗静院 · 夜 · 冷夜光", CARD,
                        "凌瑶右手按住剑柄。",
                        "凌瑶左手扶着桌沿，盯着掌门。",
                        "凌瑶（对掌门）：东西还我。",
                        "（无声）掌门后退。",
                        "（无声）凌瑶收剑。", ""])
        out = compile_md(md, target=1.0)
        shots = s01(out)
        self.assertEqual(len(silent(shots)), 1)
        self.assertTrue(any(a.startswith("SILENT_MERGED:S01") for a in out["report"]["silent_policy"]["applied"]))
        self.assertIn("掌门后退。凌瑶收剑。", silent(shots)[0]["prompt_spec"]["action"]["primary_action"])

    def test_music_passage_is_left_alone(self):
        md = "\n".join(["## S01 玄门宗静院 · 夜 · 冷夜光", CARD,
                        "凌瑶（对掌门）：东西还我。",
                        "（无声）檐水滴落。 #音乐", "（无声）灯影晃动。 #音乐", ""])
        out = compile_md(md)
        self.assertEqual(len(silent(s01(out))), 2)
        self.assertFalse([w for w in out["report"]["warnings"] if w.startswith(("SILENT_RUN", "SILENT_UNITS"))])

    def test_director_pass_reports_runs_and_heavy_openings(self):
        shots = []
        for i, line in enumerate(["", "", "甲：你来了。", "", ""], 1):
            shots.append({"shot_id": f"E09-S01-{i:02d}", "scene_id": "E09-S01", "target_seconds": 3.0,
                          "prompt_spec": {"dialogue": line, "beat_role": "LINE" if line else "ACTION"}})
        codes = dp.silent_policy_advisories(shots)
        self.assertIn("SILENT_UNITS_OVER:E09-S01:4", codes)
        self.assertIn("SILENT_RUN:E09-S01-02", codes)
        self.assertIn("OPENING_SILENT_HEAVY:3", codes)  # 0 / 3 / 6 / 9 s: three silent
        shots[3]["prompt_spec"]["beat_role"] = shots[4]["prompt_spec"]["beat_role"] = "MUSIC_PASSAGE"
        self.assertNotIn("SILENT_RUN:E09-S01-05", dp.silent_policy_advisories(shots))


# --------------------------------------------------------------------------- runtime budget after folding
class RuntimeEstimateTest(unittest.TestCase):
    def test_estimate_counts_lines_and_silent_units_after_folding(self):
        before = spc.cut_runtime_estimate([
            {"target_seconds": 4, "prompt_spec": {"dialogue": "甲：东西认得主人。你还说他偷？"}},
            {"target_seconds": 4, "prompt_spec": {"beat_role": "ACTION"}},
            {"target_seconds": 4, "prompt_spec": {"beat_role": "REACTION"}},
            {"target_seconds": 4, "prompt_spec": {"beat_role": "MUSIC_PASSAGE"}}], target=20)
        line = spc._dialogue_seconds("甲：东西认得主人。你还说他偷？", "zh")
        self.assertEqual(before["estimated_cut_seconds"], round(line + 3.0 + 2.0 + 2.0, 1))
        self.assertEqual(before["nominal_seconds"], 16.0)
        self.assertEqual(before["silent_units"], 3)
        self.assertTrue(before["warning"].startswith("RUNTIME_ESTIMATE_SHORT:"))
        self.assertEqual(spc.cut_runtime_estimate([], target=None)["target_seconds"], 110.0)

    def test_compile_reports_the_post_fold_estimate_and_warns_short(self):
        out = compile_md(E27_S01, target=110)
        est = out["report"]["runtime_estimate"]
        self.assertEqual(est["silent_units"], 4)        # far under budget: nothing folds (runtime-aware)
        self.assertLess(est["estimated_cut_seconds"], est["nominal_seconds"])
        self.assertIn("RUNTIME_ESTIMATE_SHORT", " ".join(out["report"]["warnings"]))
        self.assertIn("never pad with silent inserts", est["fix"])
        self.assertEqual(out["report"]["status"], "PASS")   # a warning, never a blocker
        long = spc.compile_screenplay(spc.parse(E27_S01), copy.deepcopy(CAST_PROPS), {}, {}, episode="E27",
                                      en_fallback=True, brief={"target_seconds": 18})
        self.assertFalse(long["report"]["runtime_estimate"]["warning"])


    def test_folding_stops_at_the_runtime_floor_least_readable_first(self):
        pre = spc.fold_budget([("S01", spc._shot_items(spc.parse(E27_S01)["scenes"][0],
                                                       spc.Cast(CAST_PROPS["cast"]), []))], "zh", 10.0)
        full = pre["pre_fold_estimate"]
        # a target that leaves room for exactly two 3 s folds: the untagged steps go first, the #转折 catch stays
        target = (full - 6.5) / spc.RUNTIME_FOLD_FLOOR
        out = compile_md(E27_S01, target=target)
        budget = out["report"]["silent_policy"]["runtime_budget"]
        self.assertEqual(budget["granted"], 2)
        self.assertGreaterEqual(budget["post_fold_estimate"], budget["floor_seconds"])
        applied = out["report"]["silent_policy"]["applied"]
        self.assertTrue(all("L7->" not in a for a in applied))            # the #转折 silent (line 7) is kept
        self.assertIn("SILENT_KEPT_FOR_RUNTIME:S01:L7", out["report"]["warnings"])
        turn = next(s for s in s01(out) if s["prompt_spec"]["beat_role"] == "TURN")
        self.assertFalse(turn.get("dialogue"))
        self.assertEqual(out["report"]["status"], "PASS")

    def test_s1_routes_a_short_cut_to_the_writer_once(self):
        import json as _json
        import tempfile
        from types import SimpleNamespace

        import nalu_pipeline as npl
        length = {"advisory": "RUNTIME_ESTIMATE_SHORT:90s<104.5s(target 110s): deepen"}
        with tempfile.TemporaryDirectory() as d:
            p = SimpleNamespace(logs=Path(d))
            first = npl.s1_runtime_feedback(p, {"a": "1"}, length)
            self.assertTrue(first.startswith("RUNTIME_ESTIMATE_SHORT"))
            self.assertTrue(first.startswith(npl.S1_INTEGRITY_PREFIXES))         # rides the bounded integrity loop
            decision = npl.s1_integrity_round(p, {"a": "1"}, [first])
            self.assertEqual(decision["decision"], "REVISE")
            self.assertTrue(npl.s1_runtime_feedback(p, {"a": "1"}, length))      # same script: same round
            self.assertEqual(npl.s1_runtime_feedback(p, {"a": "2"}, length), "")  # revised script: recorded only
            self.assertEqual(npl.s1_runtime_feedback(p, {"a": "2"}, {}), "")
            self.assertIn("RUNTIME_ESTIMATE_SHORT", npl.s1_integrity_admission_marker([first]))
            _json.loads((Path(d) / npl.S1_INTEGRITY_LEDGER).read_text())

    def test_s1_length_check_carries_the_estimate_as_an_advisory(self):
        import json as _json
        import tempfile
        from types import SimpleNamespace
        from unittest import mock

        import nalu_pipeline as npl
        # 30 silent shots of 4 s: 120 s nominal passes the length floor, but the cut is ~90 s -> advisory, not blocked
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            contract = d / "contract.json"
            contract.write_text(_json.dumps({"shots": [{"target_seconds": 4.0} for _ in range(30)]}), encoding="utf-8")
            (d / "briefs").mkdir()
            (d / "briefs" / "E03_PRODUCTION_BRIEF.json").write_text(_json.dumps({"target_seconds": 110}))
            ctx = SimpleNamespace(episode="E03", p=SimpleNamespace(contract=contract))
            with mock.patch.object(npl, "RUNTIME", d), mock.patch.object(npl, "_camera_grammar_on", lambda _c: True):
                out = npl.script_length_check(ctx)
        self.assertEqual(out["status"], npl.PASS)
        self.assertEqual(out["cut_estimate_seconds"], 90.0)
        self.assertTrue(out["advisory"].startswith("RUNTIME_ESTIMATE_SHORT:90s<104.5s"))
        self.assertNotIn("integrity_blocker", out)


# --------------------------------------------------------------------------- opening + 脑补
class VisualExpansionTest(unittest.TestCase):
    def _see_md(self) -> str:
        return E27_S01.replace(CARD, CARD + "\n" + SEE).replace(
            "凌瑶蹲下，左手握住阿夜右腕。", "（画面）阿夜腕上勒出的红痕还在渗血。\n凌瑶蹲下，左手握住阿夜右腕。")

    def test_opening_without_stakes_warns(self):
        out = compile_md(E27_S01)
        self.assertIn("OPENING_STAKES_UNDECLARED:E27-S01", out["report"]["warnings"])
        self.assertIn("SEE_MISSING:S01", out["report"]["warnings"])
        first = s01(out)[0]
        self.assertNotIn("CHAR-AYE", [r["character_id"] for r in first["prompt_spec"]["cast"]])

    def test_see_puts_the_stakes_in_the_first_shot_and_requests_twins(self):
        out = compile_md(self._see_md())
        first = s01(out)[0]
        visual = first["prompt_spec"]["visual"]
        self.assertIn("双腕反绑在绑缚石柱上", visual["stakes"])
        self.assertIn("CHAR-AYE", [r["character_id"] for r in first["prompt_spec"]["cast"]])  # the bound one is seen
        self.assertTrue(out["report"]["opening"]["stakes_visible"])
        self.assertFalse([w for w in out["report"]["warnings"] if w.startswith(("OPENING_", "SEE_MISSING"))])
        self.assertIn("檐水", visual["environment"])
        self.assertEqual(visual["business"], {"CHAR-MASTER": "指节一下下敲着桌沿",
                                              "CHAR-LINGYAO": "说话前先把左手衣袖压平"})
        detail = next(s for s in s01(out) if "冤枉你的人" in (s.get("dialogue") or ""))
        self.assertIn("红痕", detail["prompt_spec"]["visual"]["detail"])
        # English twins: one request row per distinct text; the fallback leaves the field out, never stalls
        rows = [r for r in out["en_request"]["rows"] if r["field"] == "visual"]
        self.assertTrue(rows)
        self.assertNotIn("stakes_en", visual)
        self.assertEqual(out["report"]["status"], "PASS")
        self.assertIn("看得见的处境：", out["directing_md"])
        # answered twins land in the block
        answers = {"schema": spc.EN_SCHEMA, "rows": {r["key"]: f"English {i}" for i, r in enumerate(rows)}}
        visual = s01(compile_md(self._see_md(), answers))[0]["prompt_spec"]["visual"]
        self.assertTrue(visual["stakes_en"].startswith("English"))
        self.assertEqual(set(visual["business_en"]), {"CHAR-MASTER", "CHAR-LINGYAO"})

    def test_parse_see_keys(self):
        see = spc.parse_see("赌注=A | 关系=B ｜ env=C | 感官=D | 人[凌瑶]=E | 掌门=F | 掌门=G")
        self.assertEqual((see["stakes"], see["relations"], see["environment"], see["senses"]), ("A", "B", "C", "D"))
        self.assertEqual(see["business"], {"凌瑶": "E", "掌门": "F；G"})


VISUAL = {"stakes_en": "Beta's wrists are tied to the stone pillar behind Alpha, blood at the temple",
          "detail_en": "the rope has cut a red line into the wrist; rain water beads on the table edge",
          "environment_en": "Rain drips in strings from the eaves; the lantern sways; wet stone catches the light",
          "business_en": {A: "smooths the left sleeve flat before speaking, handsome face calm",
                          B: "keeps the head down, shoulders flinch at the name"}}


def _with_visual(unit: dict, *, bili: bool, folded: bool = False) -> dict:
    spec = unit["ordered_prompt_specs"][0]
    spec["visual"] = copy.deepcopy(VISUAL)
    if folded:
        spec.setdefault("action", {})["folded_silent"] = [{"line_no": 3, "where": "next", "text": "x"}]
    if bili:
        unit["craft_profile"] = "BILI_V1"
    return unit


def _outside_dialogue(text: str) -> str:
    return re.sub(r"<d>.*?</d>", "", text, flags=re.S)


class RenderVisualTest(unittest.TestCase):
    def test_v2_prints_the_visual_sentences(self):
        unit, plan = fixture()
        before, _ = render_h3_prompt(_bili_only(copy.deepcopy(unit)), plan)
        text, _ = render_h3_prompt(_with_visual(unit, bili=True, folded=True), plan)
        self.assertIn("In the frame: Beta's wrists are tied", text)
        self.assertIn("Visible detail: the rope has cut a red line", text)
        self.assertIn("Around them: rain drips in strings", text)
        self.assertIn("Beta's own way of moving here: keeps the head down", text)
        self.assertIn(bili_carry.FOLDED_WHILE_SPEAKING, text)
        self.assertNotIn("handsome", text)          # appearance clause dropped: the reference owns the face
        self.assertIn("Alpha's own way of moving here: smooths the left sleeve flat before speaking.", text)
        self.assertLess(text.index("In the frame:"), text.index("End:"))
        self.assertFalse(CJK.search(_outside_dialogue(text)))
        self.assertLess(len(text), _PROVIDER_RUNE_LIMIT)
        self.assertGreater(len(text), len(before))
        self.assertLessEqual(len(text) - len(before), bili_carry.VISUAL_MAX_CHARS + 20)

    def test_v1_prints_the_visual_sentences(self):
        unit, plan = fixture(director=False)
        text, _ = render_h3_prompt(_with_visual(unit, bili=True), plan)
        self.assertIn("In the frame:", text)
        self.assertIn("Around them:", text)
        self.assertFalse(CJK.search(_outside_dialogue(text)))

    def test_legacy_ignores_the_visual_block(self):
        unit, plan = fixture()
        before, _ = render_h3_prompt(copy.deepcopy(unit), plan)
        legacy = _with_visual(unit, bili=False)
        legacy["ordered_prompt_specs"][0]["visual"]["detail_en"] = "the rope has cut a red line into the wrist"
        after, _ = render_h3_prompt(legacy, plan)
        self.assertEqual(before, after)

    def test_environment_alone_keeps_the_dry_skin_negative(self):
        unit, plan = fixture()
        unit = _with_visual(unit, bili=True)
        visual = unit["ordered_prompt_specs"][0]["visual"]
        visual.update(stakes_en="Beta stands by the pillar", detail_en="a red line on the wrist")
        text, _ = render_h3_prompt(unit, plan)
        self.assertIn("Around them: rain drips", text)
        self.assertIn("sweaty skin sheen", text)   # eave water on stone wets no skin: the guard stays

    def test_visual_sentences_cap_and_skip(self):
        spec = {"visual": {"stakes_en": "x " * 300, "detail_en": "y " * 300, "environment_en": "z " * 200}}
        rows = bili_carry.visual_sentences(spec, [], skip={"ENVIRONMENT"})
        self.assertNotIn("ENVIRONMENT", [k for k, _ in rows])
        self.assertLessEqual(sum(len(s) for _, s in rows), bili_carry.VISUAL_MAX_CHARS)
        self.assertEqual(bili_carry.visual_sentences({"visual": {"stakes_en": "绑在柱上"}}, []), [])


def _bili_only(unit: dict) -> dict:
    unit["craft_profile"] = "BILI_V1"
    return unit


class KeyframeVisualTest(unittest.TestCase):
    def test_keyframe_segments_take_only_the_static_facts(self):
        source = (ROOT / "lines/nalu/runtime/tools/build_keyframe_manifest.py").read_text(encoding="utf-8")
        self.assertIn('("see_stakes", f"看得见的处境：{see[\'stakes\']}", False)', source)
        self.assertIn('("see_environment", f"环境细节：{see[\'environment\']}", False)', source)
        self.assertNotIn("see['detail']", source)   # a shot detail may describe motion: never in a still


# --------------------------------------------------------------------------- character voice
def _line(sid: str, scene: str, text: str, listener: str = "", **action) -> dict:
    return {"shot_id": sid, "scene_id": scene, "target_seconds": 4,
            "prompt_spec": {"dialogue": text, "beat_role": "LINE", "action": action,
                            "role_semantic_disambiguation": {"dialogue_listener_id": listener}}}


class VoiceDoctorTest(unittest.TestCase):
    def contract(self) -> dict:
        shots = [
            _line("S01-01", "S01", "甲：你为什么来这里？", "CHAR-B"),
            _line("S01-02", "S01", "乙：你为什么要管我？", "CHAR-A"),
            _line("S01-03", "S01", "甲：你到底想怎么样？", "CHAR-B", listener_reaction="乙：别过脸"),
            _line("S01-04", "S01", "乙：你到底要做什么？", "CHAR-A"),
            _line("S01-05", "S01", "甲：你今天必须说清楚？", "CHAR-B"),
            _line("S01-06", "S01", "丙：灵气与他不容，他体内有邪骨。"),
            _line("S01-07", "S01", "乙：你凭什么这么说话？", "CHAR-A"),
        ]
        return {"shots": shots,
                "character_entities": [{"character_id": "CHAR-A", "canonical_name": "甲"},
                                       {"character_id": "CHAR-B", "canonical_name": "乙"},
                                       {"character_id": "CHAR-C", "canonical_name": "丙"}],
                "series_card": {"characters": [{"character_id": "CHAR-A", "name": "甲", "voice": "冷，短句",
                                                "verbal_habit": "反问收尾"},
                                               {"character_id": "CHAR-B", "name": "乙", "voice": "急"}]}}

    def test_voice_codes_are_warnings_with_fixes(self):
        doctor = bac.script_doctor(self.contract())
        codes = {w.split(":")[0]: w for w in doctor["warnings"]}
        self.assertEqual(codes["DOCTOR_VOICE_UNDECLARED"], "DOCTOR_VOICE_UNDECLARED:CHAR-B")
        self.assertEqual(codes["DOCTOR_VOICES_ALIKE"], "DOCTOR_VOICES_ALIKE:甲|乙")
        self.assertIn("DOCTOR_EXPOSITION_LINE:S01-06", doctor["warnings"])
        self.assertIn("DOCTOR_LINE_LANDS_NOWHERE:S01-05", doctor["warnings"])   # a bystander talks over it
        self.assertNotIn("DOCTOR_LINE_LANDS_NOWHERE:S01-03", doctor["warnings"])  # the listener reacts
        for code in ("DOCTOR_VOICE_UNDECLARED", "DOCTOR_VOICES_ALIKE", "DOCTOR_EXPOSITION_LINE",
                     "DOCTOR_LINE_LANDS_NOWHERE"):
            self.assertIn(code, bac.FIXES)
        result = bac.check(self.contract(), "zh", ["S01"], [])
        self.assertFalse([f for f in result["failures"] if f.startswith("DOCTOR_")])

    def test_distinct_voices_pass(self):
        contract = self.contract()
        contract["shots"][1]["prompt_spec"]["dialogue"] = "乙：行吧，我走就是了，反正也没人留我。"
        contract["shots"][3]["prompt_spec"]["dialogue"] = "乙：唉……算了吧，说了你也不会听的嘛。"
        contract["shots"][6]["prompt_spec"]["dialogue"] = "乙：好好好，都听你的，行了吧！"
        doctor = bac.script_doctor(contract)
        self.assertFalse([w for w in doctor["warnings"] if w.startswith("DOCTOR_VOICES_ALIKE")])

    def test_series_card_keeps_voice_fields(self):
        block = spc._series_card_block({"characters": [{"id": "CHAR-A", "name": "甲", "voice": "冷",
                                                        "verbal_habit": "反问"}]})
        self.assertEqual(block["characters"][0]["voice"], "冷")
        self.assertEqual(block["characters"][0]["verbal_habit"], "反问")


# --------------------------------------------------------------------------- writer guidance
class WriterGuidanceTest(unittest.TestCase):
    def test_bili_section_and_docs_carry_the_rules(self):
        section = craft.codex_section(ROOT, craft_profile="BILI_V1")
        for needle in ("无台词镜 只给看得懂的一拍", "边说边做", "开场10秒", "@see", "（画面）", "verbal_habit", "潜台词",
                       "第一个情绪点是否太晚"):
            self.assertIn(needle, section)
        self.assertLessEqual(len(section), craft.MAX_CODEX_SECTION_CHARS)
        production = (ROOT / "skills/nalu-claude-code/CLAUDE_CODE_PRODUCTION.md").read_text(encoding="utf-8")
        for needle in ("边说边做", "SILENT_PROCEDURE_KEPT", "RUNTIME_ESTIMATE_SHORT", "@see 赌注=", "（画面）", "verbal_habit", "DOCTOR_VOICES_ALIKE",
                       "不写长相"):
            self.assertIn(needle, production)
        fmt = (ROOT / "docs/knowledge/SCREENPLAY_FORMAT_V1.md").read_text(encoding="utf-8")
        for needle in ("`@see k=v", "`（画面）…`", "`#反应`", "Silent units (E27", "Opening (E27)", "Runtime budget after folding", "脑补 (E27)"):
            self.assertIn(needle, fmt)
        contract = (ROOT / "agent_factory/storyclaw_portable/WRITER_CONTRACT.md").read_text(encoding="utf-8")
        for needle in ("Silent units (11-25", "What the viewer must see (11-25", "Character voice (11-25"):
            self.assertIn(needle, contract)


if __name__ == "__main__":
    unittest.main()
