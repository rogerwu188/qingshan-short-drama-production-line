"""Cut to the performance (CAMERA_GRAMMAR_V1, owner 2026-11-02, lab 化神 E01): each unit is cut at head/tail to its
scripted performance -- unscripted tail / head speech, a repeated line, talking in a silent unit -- never inside the
take; a too-short result holds 1.2 s with a warning.  ASR word timings below were measured on lab 化神 E01."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for _path in (str(REPO), str(REPO / "tools"), str(REPO / "lines" / "nalu" / "runtime" / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import performance_cut as pc  # noqa: E402


def seg(*words):
    return {"start": words[0][0], "end": words[-1][1], "text": "".join(w for _, _, w in words),
            "words": [{"start": a, "end": b, "word": w} for a, b, w in words]}


def chars(start, text, step=0.16):
    return [(round(start + i * step, 3), round(start + (i + 1) * step, 3), ch) for i, ch in enumerate(text)]


def contract(lines_by_shot, language="zh", voice_only=()):
    rows = [{"shot_id": sid, "speaker_id": spk, "text": text}
            for sid, items in lines_by_shot.items() for spk, text in items]
    return {"episode": "E01", "dialogue_language": language, "camera_grammar_policy": "CAMERA_GRAMMAR_V1",
            "character_entities": [{"character_id": c, "identity_source": {"mode": "VOICE_ONLY_NO_PLATE"}}
                                   for c in voice_only],
            "audio_contract": {"dialogue_units": rows}}


def grouping(units):
    return {"units": [{"unit_id": uid, "editorial_shot_ids": shots} for uid, shots in units.items()]}


def row(report, uid):
    return next(r for r in report["units"] if r["unit_id"] == uid)


# lab 化神 E01-VU-020: "叫您干嘛？" then a whole invented sentence
VU020 = [seg((0.0, 0.36, "教"), (0.36, 0.5, "您"), (0.5, 0.66, "干"), (0.66, 0.86, "嘛,"), (1.22, 1.5, "这"),
             (1.5, 1.7, "天"), (1.7, 1.86, "快"), (1.86, 2.04, "发"), (2.04, 2.16, "着"), (2.16, 2.28, "大"),
             (2.28, 2.46, "天"), (2.46, 2.64, "族"), (2.64, 2.78, "还"), (2.78, 2.94, "收"), (2.94, 3.1, "黑"),
             (3.1, 3.28, "的是"), (3.28, 3.5, "趁"), (3.5, 3.66, "早"), (3.66, 3.82, "遭"), (3.82, 4.02, "回去"),
             (4.02, 4.24, "吧。"))]
# lab 化神 E01-VU-018: the first line said (garbled) once, then the whole scripted sequence
VU018 = [seg(*chars(0.27, "您怎么知道"), *chars(2.03, "撞失了还是战铁"), *chars(3.65, "起锁了"),
             *chars(4.43, "您怎么知道"), *chars(5.91, "掌门刚接的战铁"), *chars(7.91, "魔尊银酒然"),
             *chars(8.95, "明天率十万魔军压境"), *chars(10.93, "全宗都在备战呢"))]
VU018_LINES = {"S05-01": [("SHIDI", "您怎么知道？掌门刚接的战帖，")], "S05-02": [("SHIDI", "魔尊殷九燃明天率十万魔军压境，")],
               "S05-03": [("SHIDI", "全宗都在备战呢！")]}
# lab 化神 E01-VU-002: ~3.5 s of gibberish before line 1 (评价 heard as 凭驾)
VU002 = [seg(*chars(1.01, "占占地岩石脚踏着肘军形飞浮之嘴里"), *chars(5.55, "谢师弟还有空凭驾我"),
             *chars(7.79, "看来睡得比我多"), *chars(9.53, "明天开始"), *chars(10.77, "我也睡一个半时辰好了"))]
VU002_LINES = {"S01-03": [("ST", "谢师弟还有空评价我，")], "S01-04": [("ST", "看来睡得比我多，明天开始")],
               "S01-05": [("ST", "我也睡一个半时辰好了。")]}


def energy(duration, loud=(), level=-8.0, floor=-50.0):
    frames = [floor] * int(duration / pc.ENERGY_HOP)
    for a, b in loud:
        for i in range(int(a / pc.ENERGY_HOP), min(len(frames), int(b / pc.ENERGY_HOP))):
            frames[i] = level
    return frames


class SpeakingUnitTests(unittest.TestCase):
    def test_tail_unscripted_sentence_is_cut_and_short_result_holds_1_2_s(self):
        c = contract({"S05-05": [("SHIDI", "叫您干嘛？")]})
        rep = pc.plan(c, grouping({"VU-020": ["S05-05"]}), {"VU-020": VU020}, {"VU-020": 4.458})
        r = row(rep, "VU-020")
        self.assertEqual(r["removed_tail_text"], "这天快发着大天族还收黑的是趁早遭回去吧")
        self.assertIn("TRIM_TAIL_UNSCRIPTED", r["reasons"])
        # cut at the invented speech (1.22 - 0.05 = 1.17) is under 1.2 s -> 1.2 s hold centred on the line + warning
        self.assertIn("MIN_LENGTH_HOLD", r["reasons"])
        self.assertAlmostEqual(r["after_out"] - r["after_in"], pc.MIN_KEEP_SECONDS, places=3)
        self.assertLess(r["after_out"], 1.22)
        self.assertTrue(rep["warnings"] and rep["warnings"][0].startswith("MIN_LENGTH_HOLD:VU-020"))

    def test_tail_cut_at_unscripted_speech_start_minus_gap(self):
        c = contract({"S1": [("A", "我从今天清早起就一直守在这里。")]})
        words = chars(0.5, "我从今天清早起就一直守在这里") + chars(3.5, "还有一件事情要说")
        rep = pc.plan(c, grouping({"U": ["S1"]}), {"U": [seg(*words)]}, {"U": 6.0})
        r = row(rep, "U")
        self.assertEqual(r["after_out"], round(2.74 + pc.TAIL_PAD, 3))  # line end + pad comes first here
        self.assertEqual(r["after_in"], round(0.5 - pc.HEAD_LEAD, 3))
        words = chars(0.5, "我从今天清早起就一直守在这里") + chars(2.9, "还有一件事情要说")
        r = row(pc.plan(c, grouping({"U": ["S1"]}), {"U": [seg(*words)]}, {"U": 6.0}), "U")
        self.assertEqual(r["after_out"], round(2.9 - pc.SPEECH_GAP, 3))  # invented speech starts sooner
        self.assertEqual(r["reasons"], ["TRIM_HEAD_TO_LINE", "TRIM_TAIL_UNSCRIPTED"])

    def test_plain_line_keeps_lead_and_tail_pad(self):
        c = contract({"S1": [("A", "不练了！")]})
        rep = pc.plan(c, grouping({"U": ["S1"]}), {"U": [seg(*chars(2.0, "不练了", step=0.3))]}, {"U": 4.458})
        r = row(rep, "U")
        self.assertEqual((r["after_in"], r["after_out"]), (1.85, round(2.9 + pc.TAIL_PAD, 3)))
        self.assertEqual(r["reasons"], ["TRIM_HEAD_TO_LINE", "TRIM_TAIL_TO_LINE"])

    def test_repeated_line_keeps_last_complete_occurrence(self):
        units = grouping({"VU-018": list(VU018_LINES)})
        rep = pc.plan(contract(VU018_LINES), units, {"VU-018": VU018}, {"VU-018": 12.25})
        r = row(rep, "VU-018")
        self.assertEqual(r["reasons"], ["DROP_REPEAT"])
        self.assertEqual(r["removed_head_text"], "您怎么知道撞失了还是战铁起锁了")
        self.assertAlmostEqual(r["after_in"], 4.43 - pc.HEAD_LEAD, places=3)
        self.assertEqual(r["after_out"], 12.25)

    def test_full_take_said_twice_keeps_the_last(self):
        c = contract({"S1": [("A", "全宗都在备战呢！")]})
        words = chars(0.3, "全宗都在备战呢") + chars(2.4, "全宗都在备战呢")
        r = row(pc.plan(c, grouping({"U": ["S1"]}), {"U": [seg(*words)]}, {"U": 4.5}), "U")
        self.assertIn("DROP_REPEAT", r["reasons"])
        self.assertAlmostEqual(r["after_in"], 2.4 - pc.HEAD_LEAD, places=3)

    def test_leading_gibberish_is_cut_homophones_tolerated(self):
        units = grouping({"VU-002": list(VU002_LINES)})
        r = row(pc.plan(contract(VU002_LINES), units, {"VU-002": VU002}, {"VU-002": 12.25}), "VU-002")
        self.assertEqual(r["reasons"], ["TRIM_HEAD_UNSCRIPTED"])
        self.assertEqual(r["removed_head_text"], "占占地岩石脚踏着肘军形飞浮之嘴里")
        self.assertAlmostEqual(r["after_in"], 5.55 - pc.HEAD_LEAD, places=3)
        self.assertEqual(r["after_out"], 12.25)  # the last word runs to the clip end

    def test_head_false_start_dropped_but_a_mid_take_repeat_never_spliced(self):
        c = contract({"S1": [("H", "It was clamped to the floor.")]}, language="en")
        words = [(0.0, 0.28, " It"), (0.28, 0.52, " was,"), (0.68, 1.26, " it"), (1.26, 1.44, " was"),
                 (1.44, 2.0, " clamped"), (2.0, 2.18, " to"), (2.18, 2.3, " the"), (2.3, 2.58, " floor.")]
        r = row(pc.plan(c, grouping({"U": ["S1"]}), {"U": [seg(*words)]}, {"U": 4.0}), "U")
        self.assertEqual((r["after_in"], r["reasons"][0]), (0.53, "DROP_REPEAT"))  # partial earlier take at the head
        words = [(0.2, 0.4, " It"), (0.4, 0.6, " was"), (0.6, 1.0, " clamped,"), (1.2, 1.6, " clamped"),
                 (1.6, 1.8, " to"), (1.8, 1.9, " the"), (1.9, 2.3, " floor.")]
        r = row(pc.plan(c, grouping({"U": ["S1"]}), {"U": [seg(*words)]}, {"U": 4.0}), "U")
        self.assertEqual((r["after_in"], r["after_out"]), (0.05, 2.7))  # only head/tail; the take is never spliced
        self.assertNotIn("DROP_REPEAT", r["reasons"])

    def test_english_misheard_word_and_trailing_babble(self):
        c = contract({"S1": [("H", "Which of you is Mister Farintosh?")]}, language="en")
        words = [(0.3, 0.5, " Which"), (0.5, 0.6, " of"), (0.6, 0.8, " you"), (0.8, 0.9, " is"),
                 (0.9, 1.2, " Mister"), (1.2, 1.8, " Farintash?"), (2.6, 2.9, " all"), (2.9, 3.3, " in"),
                 (3.3, 3.8, " lust")]
        r = row(pc.plan(c, grouping({"U": ["S1"]}), {"U": [seg(*words)]}, {"U": 4.5}), "U")
        self.assertEqual(r["removed_tail_text"], "all in lust")
        self.assertEqual(r["after_out"], round(min(1.8 + pc.TAIL_PAD, 2.6 - pc.SPEECH_GAP), 3))

    def test_silent_last_shot_is_kept_unless_speech_follows(self):
        c = contract({"S1": [("A", "不练了！")]})
        units = grouping({"U": ["S1", "S2"]})
        r = row(pc.plan(c, units, {"U": [seg(*chars(0.4, "不练了"))]}, {"U": 8.0}), "U")
        self.assertEqual(r["after_out"], 8.0)  # authored silent reaction shot after the line stays

    def test_unmatched_line_keeps_existing_plan(self):
        c = contract({"S1": [("A", "我从今天清早起就一直守在这里。")]})
        r = row(pc.plan(c, grouping({"U": ["S1"]}), {"U": [seg(*chars(0.5, "完全不同的话语内容"))]}, {"U": 4.0}), "U")
        self.assertEqual((r["status"], r["reasons"], r["after_in"], r["after_out"]), ("NOT_MATCHED", [], 0.0, 4.0))


class HomophoneTests(unittest.TestCase):
    def test_homophone_name_at_line_start_is_kept(self):
        # lab 化神 E02-VU-002: ASR heard 殷九燃 as 因久然 with a pause before 化; it must not be cut as unscripted
        script = list("殷九燃化神后期")
        heard = [{"tok": t, "start": a, "end": b} for t, a, b in
                 [("因", 0.40, 0.70), ("久", 0.75, 1.10), ("然", 1.15, 1.46),
                  ("化", 1.84, 2.0), ("神", 2.0, 2.2), ("後", 2.2, 2.4), ("期", 2.4, 2.6)]]
        hit = pc.align(script, heard, cjk_mode=True)
        self.assertEqual(hit["first"], 0)
        self.assertEqual(hit["coverage"], 1.0)


class SilentUnitTests(unittest.TestCase):
    def test_speech_in_silent_unit_keeps_longest_clean_window(self):
        asr = {"VU-011": [seg(*chars(2.0, "只献献虚一次")), seg(*chars(3.7, "魂见天"))]}
        e = {"VU-011": energy(4.46, loud=[(2.0, 3.0), (3.6, 4.3)])}
        rep = pc.plan(contract({}), grouping({"VU-011": ["S03-04"]}), asr, {"VU-011": 4.46}, e)
        r = row(rep, "VU-011")
        self.assertEqual(r["reasons"], ["SILENT_SPEECH_WINDOW"])
        self.assertEqual(r["after_in"], 0.0)
        self.assertAlmostEqual(r["after_out"], 2.0 - pc.SPEECH_PAD, places=2)

    def test_hallucination_on_near_silence_is_not_speech(self):
        asr = {"VU-013": [seg((0.0, 0.82, "字幕by索兰娅"))], "VU-008": [seg((2.0, 4.4, "Thanks for watching"))]}
        e = {"VU-013": energy(4.46), "VU-008": energy(4.46, loud=[(2.4, 2.5)], level=-28.0)}
        rep = pc.plan(contract({}), grouping({"VU-013": ["S1"], "VU-008": ["S2"]}), asr,
                      {"VU-013": 4.46, "VU-008": 4.46}, e)
        for uid in ("VU-013", "VU-008"):
            r = row(rep, uid)
            self.assertEqual((r["status"], r["reasons"], r["after_out"]), ("ASR_HALLUCINATION_IGNORED", [], 4.46))

    def test_silent_unit_min_length_hold_picks_cleanest_window(self):
        asr = {"U": [seg(*chars(0.6, "前十年")), seg(*chars(1.9, "填诗心情")), seg(*chars(3.2, "七星世纪"))]}
        e = {"U": energy(4.5, loud=[(0.6, 1.1), (1.9, 2.5), (3.2, 3.8)])}
        rep = pc.plan(contract({}), grouping({"U": ["S1"]}), asr, {"U": 4.5}, e)
        r = row(rep, "U")
        self.assertEqual(r["reasons"], ["SILENT_SPEECH_WINDOW", "MIN_LENGTH_HOLD"])
        self.assertAlmostEqual(r["after_out"] - r["after_in"], pc.MIN_KEEP_SECONDS, places=3)
        self.assertTrue(any(w.startswith("MIN_LENGTH_HOLD:U") for w in rep["warnings"]))

    def test_voice_over_unit_counts_as_silent_and_vo_guard_keeps_its_narration(self):
        c = contract({"S1": [("SYSTEM", "检测到宿主彻底放弃修行执念，")], "S2": [("A", "不练了！")]},
                     voice_only=("SYSTEM",))
        units = grouping({"V": ["S1"], "D": ["S2"]})
        asr = {"V": [seg(*chars(1.4, "前十年填诗心情七星世纪"))], "D": [seg(*chars(0.2, "不练了"))]}
        e = {"V": energy(5.0, loud=[(1.4, 3.2)]), "D": energy(4.0, loud=[(0.2, 0.7)])}
        rep = pc.plan(c, units, asr, {"V": 5.0, "D": 4.0}, e, vo_seconds={"V": [3.0]})
        r = row(rep, "V")
        self.assertEqual(r["kind"], "SILENT")
        need = pc.VO_LEAD_IN + 3.0 + pc.VO_SEPARATION
        self.assertGreaterEqual(r["after_out"] - r["after_in"] + 1e-6, need)
        self.assertTrue(any(w.startswith("VO_HOLD:V") for w in r["warnings"]))


class MergeAndAsrTests(unittest.TestCase):
    def test_merge_writes_build_inputs_and_asr_follows(self):
        c = contract({"S05-05": [("SHIDI", "叫您干嘛？")]})
        tail = {"units": [{"unit_id": "VU-020", "trimmed": False, "kept_seconds": 4.458, "reason": "LINE_FILLS_SLOT"}]}
        head = {"units": [{"unit_id": "VU-020", "trimmed": False, "head_cut_seconds": 0.0}]}
        asr = {"VU-020": VU020}
        rep = pc.plan(c, grouping({"VU-020": ["S05-05"]}), asr, {"VU-020": 4.458}, None, tail, head)
        t2, h2 = pc.merge(tail, head, rep)
        self.assertTrue(t2["units"][0]["trimmed"])
        self.assertEqual(t2["units"][0]["kept_seconds"], 1.2)
        self.assertFalse(h2["units"][0]["trimmed"])
        win = pc.windows(t2, h2, {"VU-020": 4.458})
        self.assertEqual(win["VU-020"], (0.0, 1.2))
        cut = pc.cut_unit_asr(asr, win, rep)["VU-020"]
        self.assertEqual(len(cut), 1)
        self.assertEqual(cut[0]["text"], "教您干嘛,")
        self.assertLessEqual(cut[0]["end"], 1.2)
        # levelling convention: seconds from the cut in-point
        shifted = pc.shift_to_cut({"U": [{"start": 5.6, "end": 7.0, "text": "x"}]}, {"U": (5.4, 9.0)})
        self.assertEqual(shifted["U"][0]["start"], 0.2)

    def test_silent_unit_asr_dropped_after_speech_cut(self):
        asr = {"U": [seg(*chars(2.0, "只献献虚一次"))]}
        rep = pc.plan(contract({}), grouping({"U": ["S1"]}), asr, {"U": 4.46}, {"U": energy(4.46, loud=[(2.0, 3.0)])})
        win = {"U": (row(rep, "U")["after_in"], row(rep, "U")["after_out"])}
        self.assertEqual(pc.cut_unit_asr(asr, win, rep)["U"], [])

    def test_report_accounts_total_duration(self):
        c = contract({"S05-05": [("SHIDI", "叫您干嘛？")]})
        rep = pc.plan(c, grouping({"VU-020": ["S05-05"]}), {"VU-020": VU020}, {"VU-020": 4.458})
        self.assertEqual(rep["before_total_seconds"], 4.458)
        self.assertEqual(rep["after_total_seconds"], 1.2)
        self.assertEqual(rep["removed_seconds"], 3.258)


class PipelineWiringTests(unittest.TestCase):
    def test_s7_runs_the_performance_cut_only_inside_the_stamped_tail_trim_step(self):
        src = (REPO / "lines/nalu/runtime/tools/nalu_pipeline.py").read_text(encoding="utf-8")
        body = src[src.index("def s7_dialogue_tail_trim"):src.index("def s7_push_in_compensation")]
        self.assertLess(body.index("_cgp.active(contract"), body.index("_perf.plan("))
        self.assertIn("_perf.merge(report, head, perf)", body)
        self.assertIn("_perf.shift_to_cut(", src)


if __name__ == "__main__":
    unittest.main()
