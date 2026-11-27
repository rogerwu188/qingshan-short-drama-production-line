"""E28 review (2026-11-26): writer-authored performance, clean scripts, subtext, lean H3 prompt, snippet lab.

Zero credits, no new blocking gate.  Covers: the ``@演`` / ``@arc`` grammar compiled into the performance (timeline
source ``writer``, trigger from the writer's stress note, the lexicon only as a flagged fallback, English twins via the
``perf`` request rows with the crack's word anchor stripped); engine rules in action lines dropped and reported; one
source of truth per shot (action line beats @see business); the series-card voice backfill and the one-time S1 craft
feedback; the quest-line doctor; the BILI_V1 V2 prompt (performance block between Action and Dialogue, each guardrail
once, #352 clean-picture clauses kept, no reference to the spoken words); the snippet lab renders offline."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import bili_adaptation_check as bac  # noqa: E402
import bili_carry  # noqa: E402
import performance_timeline as ptl  # noqa: E402
import screenplay_compile as spc  # noqa: E402
from tools import h3_director_prompt_v2 as v2  # noqa: E402
from tools.h3_provider_prompt_renderer import render_h3_prompt  # noqa: E402

LAB = ROOT / "tools" / "tests" / "fixtures" / "snippet_lab_e28"
SPOKEN = re.compile(r"\b(?:word|words|syllables?|sentence|stressed|trigger|voice)\b|\bthe line\b|\d", re.I)
CJK = re.compile(r"[㐀-鿿]")


def _lab_module():
    spec = importlib.util.spec_from_file_location("snippet_lab", ROOT / "tools" / "lab" / "snippet_lab.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read(name: str):
    text = (LAB / name).read_text(encoding="utf-8")
    return json.loads(text) if name.endswith((".json", ".yaml")) else text


def compile_lab(md: str | None = None, *, answers: dict | None = None, series: dict | None = None) -> dict:
    return spc.compile_screenplay(spc.parse(md if md is not None else _read("LAB_SCREENPLAY.md")),
                                  _read("LAB_CAST_PROPS.yaml"), series if series is not None else _read("SERIES_CARD.yaml"),
                                  {}, episode="LAB",
                                  translations=answers if answers is not None else _read("LAB_SCREENPLAY_EN.json"))


def shot(out: dict, sid: str) -> dict:
    return next(s for s in out["contract"]["shots"] if s["shot_id"] == f"LAB-{sid}")


class StressWordTest(unittest.TestCase):
    def test_the_writer_stress_note_picks_the_trigger(self):
        cases = {("别再琢磨了。先告诉我怎么救他。", "对东阳，截住推想，先救他三个字落重"): "救他",
                 ("这邪骨能不能压住？他等不起。", "对东阳，追问压得很低，等不起突然加重"): "等不起",
                 ("怪就怪在，他只有一部分邪骨。", "对凌瑶，困惑地放慢，在一部分前停顿"): "一部分",
                 ("天君若知道，你也会被牵连。", "对凌瑶，接近耳语，天君二字压低"): "天君"}
        for (line, paren), word in cases.items():
            self.assertEqual(ptl.stress_word(line, paren)[0], word, line)
        self.assertEqual(ptl.stress_word("别再琢磨了。先告诉我怎么救他。", "", "到“救他”时眼眶红了")[:3:2], ("救他", "crack"))
        self.assertEqual(ptl.stress_word("你好。", "冷冷地")[0], "")

    def test_lexicon_fallback_uses_the_stress_note_not_the_auto_pick(self):
        out = ptl.build(who="A", emotion="冷", emotion_en="cold", line="别再琢磨了。先告诉我怎么救他。",
                        paren="先救他三个字落重")
        self.assertEqual(out["trigger_word"], "救他")  # E28 auto-picked 「我」
        self.assertEqual(out["source"], "lexicon_fallback")
        self.assertEqual(out["trigger_source"], "paren")

    def test_anchor_is_stripped_for_the_translator(self):
        self.assertEqual(ptl.strip_anchor('到"等不起"时目光第一次离开东阳'), "目光第一次离开东阳")
        self.assertEqual(ptl.parse_authored("要=a | 压=b | 漏=c | 裂=d | 做=e | 收=f | 听=g | 其他=x"),
                         {"want": "a", "hide": "b", "leak": "c", "crack": "d", "visible": "e", "end": "f",
                          "listener": "g"})


class AuthoredCompileTest(unittest.TestCase):
    def test_authored_block_becomes_the_performance(self):
        out = compile_lab()
        perf = shot(out, "S01-01")["prompt_spec"]["action"]["performance"]
        self.assertEqual(perf["source"], "writer")
        self.assertEqual(perf["timeline"]["source"], "writer")
        self.assertEqual(perf["timeline"]["trigger_word"], "等不起")
        self.assertEqual(perf["timeline"]["curve"], "arc_entry")
        self.assertEqual(set(perf["authored_en"]), {"want", "hide", "leak", "crack", "visible", "end"})
        # the next line of the same character starts where this one ended
        nxt = shot(out, "S01-03")["prompt_spec"]["action"]["performance"]["timeline"]
        self.assertEqual(nxt["curve"], "carried")
        self.assertIn("盯着东阳等答案", nxt["beats"][0]["zh"])
        self.assertFalse([w for w in out["report"]["warnings"] if w.startswith("PERFORMANCE_LEXICON_FALLBACK")])
        self.assertEqual(out["report"]["performance"]["authored"], 5)
        self.assertIn("表演（写手）：要=逼东阳现在就给一句准话", out["directing_md"])
        self.assertIn("情绪线：凌瑶 强撑的冷静", out["directing_md"])

    def test_listener_note_becomes_the_in_frame_reaction(self):
        action = shot(compile_lab(), "S01-01")["prompt_spec"]["action"]
        self.assertIn("避开她的目光", action["listener_reaction"])
        # three people in frame: the reaction belongs to the listener only, never to everyone
        self.assertEqual(list(action["listener_reaction_en"]), ["CHAR-DONGYANG"])

    def test_perf_rows_are_requested_without_the_word_anchor_and_never_stall(self):
        out = compile_lab(answers={"schema": spc.EN_SCHEMA, "rows": {}})
        rows = [r for r in out["en_request"]["rows"] if r["field"] == "perf"]
        self.assertTrue(rows)
        self.assertFalse([r for r in rows if re.search(r"[「“\"]", r["zh"])])
        self.assertIn("perf", out["en_request"]["instruction_by_field"])
        fallback = spc.compile_screenplay(spc.parse(_read("LAB_SCREENPLAY.md")), _read("LAB_CAST_PROPS.yaml"),
                                          _read("SERIES_CARD.yaml"), {}, episode="LAB", translations=None,
                                          en_fallback=True)
        perf = shot(fallback, "S01-01")["prompt_spec"]["action"]["performance"]
        self.assertNotIn("authored_en", perf)  # never Chinese, never compiler-invented acting
        self.assertEqual(fallback["report"]["en_missing"], 0)

    def test_unauthored_lines_fall_back_flagged_and_feed_back_once(self):
        md = "\n".join(line for line in _read("LAB_SCREENPLAY.md").splitlines() if not line.startswith(("@演", "@arc")))
        out = compile_lab(md)
        perf = shot(out, "S01-01")["prompt_spec"]["action"]["performance"]
        self.assertEqual(perf["source"], "lexicon_fallback")
        self.assertEqual(perf["timeline"]["trigger_word"], "等不起")  # the paren's stress note, not the auto pick
        self.assertIn("PERFORMANCE_LEXICON_FALLBACK:5/5", out["report"]["warnings"])
        self.assertIn("SCRIPT_CRAFT_REVISE:PERFORMANCE_UNAUTHORED:5/5", out["report"]["craft_feedback"])
        self.assertIn("PERFORMANCE_UNAUTHORED", out["report"]["craft_feedback_fix"])


class CleanScriptTest(unittest.TestCase):
    def test_rule_talk_is_dropped_and_reported(self):
        md = _read("LAB_SCREENPLAY.md").replace("东阳右手指尖在桌沿上停住。", "东阳右手指尖在桌沿上停住，不让药碗进入首帧。")
        out = compile_lab(md)
        action = shot(out, "S01-02")["prompt_spec"]["action"]
        self.assertNotIn("首帧", action["primary_action"])
        self.assertIn("东阳右手指尖在桌沿上停住", action["primary_action"])
        self.assertTrue([w for w in out["report"]["warnings"] if w.startswith("SCRIPT_RULE_TALK:S01:不让药碗进入首帧")])
        self.assertIn("SCRIPT_CRAFT_REVISE:RULE_TALK:1", out["report"]["craft_feedback"])
        self.assertEqual(spc.rule_talk("凌瑶看着他，镜头外的门被风吹开。")[0], "凌瑶看着他。")
        self.assertEqual(spc.rule_talk("凌瑶右手按住被角。")[1], [])

    def test_own_action_line_supersedes_the_scene_business(self):
        out = compile_lab()
        visual = shot(out, "S01-03")["prompt_spec"]["visual"]
        # 凌瑶 has her own action line in S01-03: the @see 「左手压平红色衣袖后抬眼」 does not contradict it there
        self.assertNotIn("CHAR-LINGYAO", visual.get("business") or {})
        self.assertIn("CHAR-LINGYAO", visual["business_superseded"])


class VoiceAndSubtextTest(unittest.TestCase):
    def test_series_card_voice_backfill_is_asked_once_and_reaches_the_entities(self):
        card = _read("SERIES_CARD.yaml")
        out = compile_lab()
        self.assertFalse([c for c in out["report"]["craft_feedback"] if "VOICE" in c])
        entity = next(e for e in out["contract"]["character_entities"] if e["character_id"] == "CHAR-DONGYANG")
        self.assertTrue(entity["voice_style"] and entity["verbal_habit"])
        card["characters"] = [c for c in card["characters"] if c["id"] != "CHAR-DONGYANG"]
        out = compile_lab(series=card)
        self.assertIn("SCRIPT_CRAFT_REVISE:SERIES_CARD_VOICE_MISSING:东阳", out["report"]["craft_feedback"])

    def test_s1_sends_the_craft_feedback_once(self):
        import nalu_pipeline as npl
        row = {"craft_feedback": ["SCRIPT_CRAFT_REVISE:RULE_TALK:1"], "craft_feedback_fix": {"RULE_TALK": "fix it"}}
        with tempfile.TemporaryDirectory() as d:
            p = SimpleNamespace(logs=Path(d))
            first = npl.s1_craft_feedback(p, {"a": "1"}, row)
            self.assertEqual(first, ["SCRIPT_CRAFT_REVISE:RULE_TALK:1 (fix: fix it)"])
            decision = npl.s1_integrity_round(p, {"a": "1"}, first)
            self.assertEqual(decision["decision"], "REVISE")
            self.assertEqual(npl.s1_craft_feedback(p, {"a": "1"}, row), first)  # same bytes: same round
            self.assertEqual(npl.s1_craft_feedback(p, {"a": "2"}, row), [])  # revised script: recorded only

    def test_quest_lines_are_flagged_by_the_doctor(self):
        out = compile_lab()
        lines = [{"shot_id": s["shot_id"], "scene_id": s["scene_id"], "speaker": s["dialogue"].split("：")[0],
                  "text": s["dialogue"].split("：", 1)[1]} for s in out["contract"]["shots"] if s.get("dialogue")]
        found = bac.voice_doctor(out["contract"], lines)["answers"]["quest_lines"]
        self.assertIn("LAB-S01-04", found)  # 想压住邪气，得用清风神草。
        self.assertIn("LAB-S01-05", found)  # 青玄那里就有，我可以去找他。
        self.assertNotIn("LAB-S01-03", found)
        self.assertIn("DOCTOR_QUEST_LINE", bac.FIXES)
        self.assertFalse(bac.QUEST_PATTERNS_ZH.search("你敢去找青玄，我就不认你。") and
                         not bac.PRESSURE_ZH.search("你敢去找青玄，我就不认你。"))


class LeanPromptTest(unittest.TestCase):
    def setUp(self):
        self.lab = _lab_module()
        self.eng = self.lab.load_engine(ROOT)
        self.cfg = json.loads((LAB / "LAB.json").read_text(encoding="utf-8"))
        for row in self.cfg["characters"].values():
            row["face"] = "face.png"  # render reads no image; a face makes an identity reference
        self.out = self.lab.compile_lab(LAB, self.eng)

    def render(self, sid: str) -> str:
        unit, plan = self.lab.lab_unit(self.out["contract"], shot(self.out, sid), self.cfg, self.eng["english_schema"],
                                       voice=False)
        text, receipt = render_h3_prompt(unit, plan)
        self.assertEqual(receipt["status"], "PASS")
        return text

    def test_performance_block_has_the_bulk_and_never_points_at_the_words(self):
        text = self.render("S01-03")
        block = text.split("Lingyao's performance", 1)[1].split("\n\nDialogue", 1)[0]
        self.assertLess(text.index("Action (0"), text.index("Lingyao's performance"))
        self.assertLess(text.index("Lingyao's performance"), text.index("Dialogue ("))
        for head in ("Starts", "Wants right now", "Holding back", "What leaks out", "Then the guard cracks", "Visibly",
                     "Ends on"):
            self.assertIn(f"- {head}: ", block)
        self.assertIn("eyes redden", block)
        self.assertNotRegex(block, SPOKEN)
        outside = re.sub(r"<d>.*?</d>", "", text, flags=re.S)
        self.assertFalse(CJK.search(outside))
        self.assertNotIn("face and body change visibly", text)  # the lexicon line is not added on top
        self.assertNotIn("Delivery: Cold", text)

    def test_each_guardrail_once_and_the_clean_picture_clauses_stay(self):
        text = self.render("S01-01")
        self.assertEqual(text.count("tripod"), 1)
        self.assertNotIn(v2.LOCKED_OFF_STILL, text)
        self.assertNotIn("never draw a second", text)
        self.assertNotIn("Never show two people with identical appearance", text)
        self.assertNotIn("Nobody else appears", text)
        self.assertNotIn("the frame moving with a person", text)
        self.assertNotIn("zooming in, pushing in", text)
        self.assertEqual(text.count(v2.LEAN_IDENTITY_V2), 1)
        self.assertIn(v2.CLEAN_PICTURE_V2, text)
        self.assertIn(v2.SPOKEN_NOT_WRITTEN_ONE, text)
        self.assertIn("Never: captions, subtitles", text)
        self.assertEqual(v2.director_v2_self_check(text, *self.lab.lab_unit(
            self.out["contract"], shot(self.out, "S01-01"), self.cfg, self.eng["english_schema"], voice=False),
            stamped=True), [])

    def test_render_command_writes_the_prompts(self):
        with tempfile.TemporaryDirectory() as d:
            lab = Path(d) / "lab"
            lab.mkdir()
            for f in LAB.iterdir():
                (lab / f.name).write_bytes(f.read_bytes())
            self.assertEqual(self.lab.main(["render", str(lab), "--arm", "t", "--shots", "S01-01,S01-05"]), 0)
            prompts = json.loads((lab / "t" / "prompts.json").read_text(encoding="utf-8"))
            self.assertEqual(set(prompts), {"S01-01", "S01-05"})
            self.assertTrue(all(row["receipt_status"] == "PASS" and row["chars"] < 9000 for row in prompts.values()))


class VoiceOnlyDeliveryTest(unittest.TestCase):
    """Lab A/B 2026-11-26: with a Delivery that names / paraphrases the stressed words ("stresses saving him first") H3
    burned the line as subtitles in 12 of 14 E28 clips; with a voice-only Delivery in 3 of 8 (fewer, not none)."""

    def test_the_stress_note_loses_its_words_before_translation(self):
        cases = {("截住推想，先救他三个字落重", "别再琢磨了。先告诉我怎么救他。"): "截住推想，落重",
                 ("想到近路，去找他由轻转稳", "青玄那里就有，我可以去找他。"): "想到近路，由轻转稳",
                 ("困惑地放慢，在一部分前停顿", "怪就怪在，他只有一部分邪骨。"): "困惑地放慢，停顿",
                 ("犹疑后下决定，药名说得清楚", "想压住邪气，得用清风神草。"): "犹疑后下决定，说得清楚",
                 ("急而克制，后半句明显加重", "到底什么病？能不能救？"): "急而克制，明显加重",
                 ("冷笑", "你好。"): "冷笑"}
        for (note, line), want in cases.items():
            self.assertEqual(ptl.voice_only(note, line), want)
        perf = shot(compile_lab(), "S01-03")["prompt_spec"]["action"]["performance"]
        self.assertEqual(perf["delivery"], "截住推想，先救他三个字落重")  # the data keeps the full note
        out = compile_lab(answers={"schema": spc.EN_SCHEMA, "rows": {}})
        rows = [r["zh"] for r in out["en_request"]["rows"] if r["field"] == "delivery"]
        self.assertIn("截住推想，落重", rows)
        self.assertFalse([z for z in rows if "救他" in z or "去找他" in z])
        self.assertIn("delivery", out["en_request"]["instruction_by_field"])

    def test_renderer_cuts_a_delivery_clause_that_points_at_the_words(self):
        cases = {"She cuts off his speculation and stresses saving him first.": "Delivery: She cuts off his speculation.",
                 "She keeps the question very low, then suddenly stresses that he cannot wait.":
                     "Delivery: She keeps the question very low.",
                 "Thinking of the nearer route, she begins softly and becomes steady on going to find him.":
                     "Delivery: Thinking of the nearer route, she begins softly and becomes steady.",
                 "Almost whispering, lowering his voice on the Heavenly Ruler's title.":
                     "Delivery: Almost whispering, lowering his voice.",
                 "Low, clipped and impatient, cutting him off, with rising pressure.":
                     "Delivery: Low, clipped and impatient, cutting him off, with rising pressure."}
        for given, want in cases.items():
            self.assertEqual(v2.stamped_delivery({"delivery_en": given, "emotion": "冷", "emotion_basis": "default"})[0],
                             want)


class AuthoredLinesHelperTest(unittest.TestCase):
    def test_spoken_clauses_dropped_but_a_thin_line_kept(self):
        action = {"performance": {"authored_en": {
            "visible": "lips pressed into a thin line; she says the word slowly",
            "crack": "on the last word her voice breaks, her eyes redden",
            "end": "waits, eyes on him"}}}
        rows = bili_carry.authored_performance_lines(action, "Lingyao", "Dongyang")
        joined = "\n".join(rows)
        self.assertIn("thin line", joined)
        self.assertNotIn("says", joined)
        self.assertNotIn("voice", joined)
        self.assertIn("eyes redden", joined)
        self.assertEqual(bili_carry.authored_performance_lines({"performance": {}}, "A"), [])


if __name__ == "__main__":
    unittest.main()
