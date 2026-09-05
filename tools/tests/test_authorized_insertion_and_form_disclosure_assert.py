#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/authorized_insertion_and_form_disclosure_assert.py 的测试。

授权：CL2X-1293 / SUPERVISOR_ORDERS seq=50 conditions[3],[4]

测试的写法遵循一条纪律：**每一条都必须能在真件上复现**。
其中 test_e48_v5_* 三条直接读盘上的 E48 v5 真件，
所以这套测试同时是「E48 v5 在新自检下是什么读数」的取证。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from authorized_insertion_and_form_disclosure_assert import (  # noqa: E402
    EFFECTIVE_FROM_EPISODE,
    InsertionDisclosureViolation,
    assert_manifest_ok,
    check_form_disclosure,
    check_insertions,
    evaluate,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(REPO_ROOT, "workflow", "claude_writer_agent", "scripts")
E48_MANIFEST = os.path.join(SCRIPTS, "E48_manifest_v5.json")
E48_CONTRACT = os.path.join(SCRIPTS, "E48_GENERATION_CONTRACT_v5.json")


def codes(items):
    return sorted(i["code"] for i in items)


GOOD_INSERTION = {
    "insertion_id": "INS-E51-01",
    "kind": "WRITER_INITIATED_SCENE",
    "supervisor_directed": False,
    "scene_id": "E51-S03",
    "why": "把上一集留下的悬置状态往前推一步。",
    "new_information": "门槛上那把短刀不见了 —— 观众知道而主角不知道。",
    "what_it_does_not_do": "不引入新事件、新人物、新地点。",
    "self_deduction": "D4（−3.0）",
}


def manifest_with(insertion=None, **extra):
    m = {"episode": "E51", "version": 5}
    if insertion is not None:
        m["★authorized_insertions"] = [insertion]
    m.update(extra)
    return m


def write_tmp(obj, name="E51_manifest_v5.json"):
    d = tempfile.mkdtemp()
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    return p


class TestInsertionThreePartTest(unittest.TestCase):
    """seq=50 c3 的三件要件 ① 不新增 ② 有新信息 ③ 登记并自扣分。"""

    def test_fully_compliant_insertion_passes(self):
        v, _ = check_insertions(manifest_with(GOOD_INSERTION))
        self.assertEqual(v, [])

    def test_missing_new_information_field_is_violation(self):
        ins = dict(GOOD_INSERTION)
        ins.pop("new_information")
        v, _ = check_insertions(manifest_with(ins))
        self.assertIn("INSERTION_MISSING_NEW_INFORMATION_FIELD", codes(v))

    def test_new_information_buried_in_prose_does_not_count(self):
        """c3 ② 要的是可指认的新信息；埋在 why 散文里下一轮机器复核不到。"""
        ins = dict(GOOD_INSERTION)
        ins.pop("new_information")
        ins["why"] = "②交出一件新事实：门槛上那把刀不见了。"
        v, _ = check_insertions(manifest_with(ins))
        self.assertIn("INSERTION_MISSING_NEW_INFORMATION_FIELD", codes(v))

    def test_missing_self_deduction_is_violation(self):
        ins = dict(GOOD_INSERTION)
        ins.pop("self_deduction")
        v, _ = check_insertions(manifest_with(ins))
        self.assertIn("INSERTION_MISSING_SELF_DEDUCTION", codes(v))

    def test_zero_self_deduction_is_violation(self):
        ins = dict(GOOD_INSERTION, self_deduction=0)
        v, _ = check_insertions(manifest_with(ins))
        self.assertIn("INSERTION_MISSING_SELF_DEDUCTION", codes(v))

    def test_missing_no_new_elements_declaration_is_violation(self):
        ins = dict(GOOD_INSERTION)
        ins.pop("what_it_does_not_do")
        v, _ = check_insertions(manifest_with(ins))
        self.assertIn("INSERTION_MISSING_NO_NEW_ELEMENTS_DECLARATION", codes(v))

    def test_supervisor_directed_insertion_is_out_of_scope(self):
        """c3 采纳的是**写手自发**的手法；监制指定项不受这三件要件约束。"""
        ins = {"insertion_id": "INS-E51-09", "kind": "SUPERVISOR_DIRECTED_SCENE",
               "supervisor_directed": True, "scene_id": "E51-S07"}
        v, _ = check_insertions(manifest_with(ins))
        self.assertEqual(v, [])

    def test_star_prefixed_field_names_are_matched(self):
        """★ 是给监制标重点用的，不是 schema；换个星号不得绕过任何一条。"""
        ins = {"★insertion_id": "INS-E51-02", "★kind": "WRITER_INITIATED_SCENE",
               "supervisor_directed": False, "scene_id": "E51-S03",
               "★new_information": "刀不见了。", "★what_it_does_not_do": "不新增。",
               "★self_deduction": "D4（−3.0）"}
        v, _ = check_insertions(manifest_with(ins))
        self.assertEqual(v, [])


class TestGateThresholdRefusalClause(unittest.TestCase):
    """c3 末句：只为满足地点或时长门限、不带新信息的场，不在采纳范围内。"""

    def test_gate_motive_without_new_information_is_refused(self):
        ins = dict(GOOD_INSERTION)
        ins.pop("new_information")
        ins["why"] = "为避开 S02–S04 连续三场同地点的 LOCATION_STAGNATION 硬失败。"
        v, _ = check_insertions(manifest_with(ins))
        self.assertIn("INSERTION_JUSTIFIED_ONLY_BY_GATE_THRESHOLD", codes(v))

    def test_gate_motive_with_new_information_is_adopted(self):
        """E48 v5 INS-E48-01 的形态：动机双重、写在明处 ⇒ 在采纳范围内。"""
        ins = dict(GOOD_INSERTION)
        ins["why"] = ("交出一件新事实，顺带避开 LOCATION_STAGNATION 硬失败 —— "
                      "这一份动机我写在明处。")
        v, d = check_insertions(manifest_with(ins))
        self.assertEqual(v, [])
        self.assertIn("INSERTION_HAS_GATE_MOTIVE_BUT_ALSO_NEW_INFORMATION", codes(d))

    def test_prose_new_information_blocks_the_refusal_but_field_is_still_required(self):
        """回归：拒绝条款的分母是『有没有新信息』，不是『有没有那个字段』。

        缺字段 = 形式没跟上；真没有新信息 = 这一场不该存在。两件事后果不同，
        并成一条会让 E48 v5 那种真有新信息、只是写在散文里的被扣上最重的帽子。
        """
        ins = dict(GOOD_INSERTION)
        ins.pop("new_information")
        ins["why"] = "交出一件新事实：门槛上那把刀不见了；顺带避开 LOCATION_STAGNATION。"
        v, _ = check_insertions(manifest_with(ins))
        self.assertNotIn("INSERTION_JUSTIFIED_ONLY_BY_GATE_THRESHOLD", codes(v))
        self.assertIn("INSERTION_MISSING_NEW_INFORMATION_FIELD", codes(v))

    def test_runtime_padding_motive_is_also_caught(self):
        ins = dict(GOOD_INSERTION)
        ins.pop("new_information")
        ins["why"] = "本集不足 180 秒，加这一场凑时长。"
        v, _ = check_insertions(manifest_with(ins))
        self.assertIn("INSERTION_JUSTIFIED_ONLY_BY_GATE_THRESHOLD", codes(v))


class TestInsertionCheckedAgainstContract(unittest.TestCase):
    """c3 ① 里地点与人物两项，对着生成合同实查，不只信声明。"""

    CONTRACT = {
        "scene_states": [
            {"scene_id": "E51-S01", "location_id": "LOC-A"},
            {"scene_id": "E51-S02", "location_id": "LOC-A"},
            {"scene_id": "E51-S03", "location_id": "LOC-A"},
            {"scene_id": "E51-S04", "location_id": "LOC-B"},
        ],
        "identity_registry_check": {"new_cards_required": ["元掌柜卡"]},
        "shots": [
            {"scene_id": "E51-S01", "speaker": "陈迹"},
            {"scene_id": "E51-S03", "speaker": "陈迹"},
        ],
    }

    def test_declaration_is_not_taken_on_trust_for_location(self):
        ins = dict(GOOD_INSERTION, scene_id="E51-S04")   # LOC-B 只在这一场出现
        v, _ = check_insertions(manifest_with(ins), self.CONTRACT)
        self.assertIn("INSERTION_INTRODUCES_NEW_LOCATION", codes(v))

    def test_reused_location_passes(self):
        ins = dict(GOOD_INSERTION, scene_id="E51-S03")   # LOC-A 别处也有
        v, _ = check_insertions(manifest_with(ins), self.CONTRACT)
        self.assertEqual(v, [])

    def test_character_only_in_insertion_and_on_new_cards_is_caught(self):
        contract = json.loads(json.dumps(self.CONTRACT))
        contract["shots"].append({"scene_id": "E51-S03", "speaker": "元掌柜卡"})
        ins = dict(GOOD_INSERTION, scene_id="E51-S03")
        v, _ = check_insertions(manifest_with(ins), contract)
        self.assertIn("INSERTION_INTRODUCES_NEW_CHARACTER", codes(v))

    def test_series_known_location_is_not_a_new_location(self):
        """回归：c3 ① 的『新地点』是故事世界里的新，不是本集场次表里的新。

        本模块首版按「本集内是否复用」判，在 E48 v5 真件上把承 E41–E47 的
        太平医馆正堂误判成新增地点。这条测试钉住修正后的行为。
        """
        import tempfile as _tf
        d = _tf.mkdtemp()
        with open(os.path.join(d, "E50_GENERATION_CONTRACT_v5.json"), "w", encoding="utf-8") as fh:
            json.dump({"space_chain": {"level_2_locations": ["LOC-B"]}}, fh)
        ins = dict(GOOD_INSERTION, scene_id="E51-S04")   # LOC-B 本集只此一场，但 E50 已建立
        v, dg = check_insertions(manifest_with(ins), self.CONTRACT, episode=51, scripts_dir=d)
        self.assertNotIn("INSERTION_INTRODUCES_NEW_LOCATION", codes(v))
        self.assertIn("INSERTION_USES_SERIES_KNOWN_LOCATION_UNIQUE_TO_THIS_EPISODE", codes(dg))

    def test_location_effect_is_measured_both_ways(self):
        """把『声称的动机』和『真实效果』分开：有它/没它两种读数都算出来。"""
        ins = dict(GOOD_INSERTION, scene_id="E51-S04")
        _, d = check_insertions(manifest_with(ins), self.CONTRACT)
        eff = [x for x in d if x["code"] == "INSERTION_LOCATION_EFFECT_MEASURED"]
        self.assertEqual(len(eff), 1)
        payload = json.loads(eff[0]["detail"])
        self.assertEqual(payload["max_consecutive_same_location_with_insertion"], 3)
        self.assertEqual(payload["max_consecutive_same_location_without_insertion"], 3)
        self.assertEqual(payload["distinct_locations_without_insertion"], 1)


class TestZeroInsertionClaim(unittest.TestCase):
    def test_unscoped_zero_claim_contradicting_registry_is_caught(self):
        m = manifest_with(GOOD_INSERTION, **{"★zero_insertions_note": "本集零插入项。"})
        v, _ = check_insertions(m)
        self.assertIn("ZERO_INSERTION_CLAIM_CONTRADICTS_REGISTERED_INSERTIONS", codes(v))

    def test_scoped_zero_claim_is_fine(self):
        m = manifest_with(GOOD_INSERTION,
                          **{"★zero_insertions_note": "本集零**监制指定**插入项。"})
        v, _ = check_insertions(m)
        self.assertNotIn("ZERO_INSERTION_CLAIM_CONTRADICTS_REGISTERED_INSERTIONS", codes(v))


class TestFormDisclosurePrecision(unittest.TestCase):
    """seq=50 c4：自述需精确到『繁→简转写＋句末标点规范化』。"""

    @staticmethod
    def kq(disclosure, src, dst):
        return {"key_quote_landing": {
            "landed": {"KEY-01": {"source": src, "landed": dst, "speaker": "金猪"}},
            "★form_disclosure": disclosure}}

    def test_added_period_while_claiming_unchanged_is_caught(self):
        m = self.kq("落地形态＝繁→简转写，字序与字面一字未改、标点未增删。",
                    "他們喜歡搶功勞，我則是喜歡送功勞", "他们喜欢抢功劳，我则是喜欢送功劳。")
        v, _ = check_form_disclosure(m)
        self.assertIn("FORM_DISCLOSURE_OVERCLAIMS_PUNCTUATION_UNCHANGED", codes(v))

    def test_precise_disclosure_passes(self):
        m = self.kq("落地形态＝繁→简转写＋句末标点规范化；字序与字面一字未改。",
                    "他們喜歡搶功勞，我則是喜歡送功勞", "他们喜欢抢功劳，我则是喜欢送功劳。")
        v, _ = check_form_disclosure(m)
        self.assertEqual(v, [])

    def test_silence_about_punctuation_change_is_also_caught(self):
        m = self.kq("落地形态＝繁→简转写。",
                    "他們喜歡搶功勞", "他们喜欢抢功劳。")
        v, _ = check_form_disclosure(m)
        self.assertIn("FORM_DISCLOSURE_OMITS_PUNCTUATION_NORMALIZATION", codes(v))

    def test_identical_punctuation_needs_no_admission(self):
        m = self.kq("落地形态＝繁→简转写，字序与字面一字未改、标点未增删。",
                    "瞧見沒有，什么是密諜司？", "瞧见没有，什么是密谍司？")
        v, d = check_form_disclosure(m)
        self.assertEqual(v, [])
        self.assertIn("FORM_DISCLOSURE_MATCHES_MEASUREMENT", codes(d))

    def test_dropped_characters_while_claiming_verbatim_is_caught(self):
        """比标点更重的一种：字被削掉了还自称逐字（R380 的九字自限病同型）。"""
        m = self.kq("落地形态＝繁→简转写，字序与字面一字未改、标点未增删。",
                    "今晚若抓住景朝諜探，功勞你一半，我一半", "今晚抓住谍探，功劳你我各一半")
        v, _ = check_form_disclosure(m)
        self.assertIn("FORM_DISCLOSURE_OVERCLAIMS_CHARACTERS_UNCHANGED", codes(v))


class TestEnforcementWindow(unittest.TestCase):
    """E51 起阻断出件；E50 及以前只诊断，永不改历史字节。"""

    def test_e51_violation_blocks_emit(self):
        ins = dict(GOOD_INSERTION)
        ins.pop("new_information")
        p = write_tmp(manifest_with(ins), "E51_manifest_v5.json")
        with self.assertRaises(InsertionDisclosureViolation):
            assert_manifest_ok(p)

    def test_e50_same_violation_is_diagnostic_only(self):
        ins = dict(GOOD_INSERTION)
        ins.pop("new_information")
        p = write_tmp(manifest_with(ins), "E50_manifest_v5.json")
        report = assert_manifest_ok(p)               # 不抛
        self.assertEqual(report["enforcement"], "DIAGNOSTIC_ONLY")
        self.assertTrue(report["violations"])

    def test_effective_episode_is_the_next_unwritten_one(self):
        self.assertEqual(EFFECTIVE_FROM_EPISODE, 51)


@unittest.skipUnless(os.path.exists(E48_MANIFEST), "E48 v5 真件不在盘上")
class TestAgainstRealE48V5(unittest.TestCase):
    """在真件上复现监制 seq=50 的两条读数 —— 这套断言不是空转。"""

    def setUp(self):
        self.report = evaluate(E48_MANIFEST, E48_CONTRACT)

    def test_e48_is_diagnostic_not_blocking(self):
        self.assertEqual(self.report["episode"], 48)
        self.assertEqual(self.report["enforcement"], "DIAGNOSTIC_ONLY")
        self.assertTrue(self.report["ok"], "E48 及以前永不被本模块阻断")

    def test_reproduces_supervisor_c4_punctuation_finding(self):
        """监制 c4 亲手抓到的那条，机器独立复现。"""
        self.assertIn("FORM_DISCLOSURE_OVERCLAIMS_PUNCTUATION_UNCHANGED",
                      codes(self.report["violations"]))

    def test_ins_e48_01_is_inside_the_adopted_form(self):
        """INS-E48-01 不触拒绝条款：它有新信息、地点承 E41–E47、不带新人物。"""
        got = codes(self.report["violations"])
        self.assertNotIn("INSERTION_JUSTIFIED_ONLY_BY_GATE_THRESHOLD", got)
        self.assertNotIn("INSERTION_INTRODUCES_NEW_LOCATION", got)
        self.assertNotIn("INSERTION_INTRODUCES_NEW_CHARACTER", got)

    def test_e48_readout_is_exactly_two_items_and_both_are_forward_looking(self):
        """E48 v5 在新自检下的完整读数，逐条钉住，供监制下轮复核。

        ① 监制 c4 亲手抓到的标点自述；② c3 ② 的新信息尚未写成独立字段
        （该字段是本模块本轮才定义的形态，E48 v5 早于它）。两条都不返修。
        """
        self.assertEqual(codes(self.report["violations"]),
                         ["FORM_DISCLOSURE_OVERCLAIMS_PUNCTUATION_UNCHANGED",
                          "INSERTION_MISSING_NEW_INFORMATION_FIELD"])




# ===========================================================================
# seq=51 / CL2X-1294 —— 本轮（R423）新增
# ===========================================================================
from authorized_insertion_and_form_disclosure_assert import (  # noqa: E402
    SELF_DEDUCTION_SIGN_EFFECTIVE_FROM,
    _landed_scene_finding,
    _split_canonical_scenes,
)

E49_MANIFEST = os.path.join(SCRIPTS, "E49_manifest_v5.json")
E49_CANONICAL = os.path.join(SCRIPTS, "E49_NARRATIVE_CANONICAL_v5.md")


def canonical_doc(scenes):
    """scenes = [(scene_id, 正文)] → 一份最小 canonical 全文。"""
    out = ["# 测试用 canonical"]
    for sid, body in scenes:
        out += [f"## {sid}｜LOC-X｜TIME-X｜线A", "", body, ""]
    return "\n".join(out)


def write_pair(manifest, canonical, episode=51, version=5):
    d = tempfile.mkdtemp()
    mp = os.path.join(d, f"E{episode}_manifest_v{version}.json")
    with open(mp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False)
    with open(os.path.join(d, f"E{episode}_NARRATIVE_CANONICAL_v{version}.md"),
              "w", encoding="utf-8") as fh:
        fh.write(canonical)
    return mp


GATE_MOTIVE_NO_FIELD = dict(GOOD_INSERTION)
GATE_MOTIVE_NO_FIELD.pop("new_information")
GATE_MOTIVE_NO_FIELD["why"] = "刻意压在 7.9 秒，不越过 8 秒长静默门限；顺带避开 LOCATION_STAGNATION 硬失败。"
GATE_MOTIVE_NO_FIELD["scene_id"] = "E51-S03"


class TestRefusalDenominatorIsTheLandedScene(unittest.TestCase):
    """seq=51 c2：拒绝条款的分母 = 落地场次正文，不是 why 字段、也不是散文。"""

    def test_landed_scene_with_new_facts_blocks_the_refusal_even_with_gate_motive(self):
        """正文交得出新事实 ⇒ 命中门限动机也不扣『只为门限而加的场』这顶帽子。"""
        doc = canonical_doc([
            ("E51-S01", "陈迹站在堂上，等一个不来的人。"),
            ("E51-S03", "门槛上扎着的那把短刀不见了，只剩一道裂口。"),
        ])
        p = write_pair(manifest_with(GATE_MOTIVE_NO_FIELD), doc)
        r = evaluate(p)
        self.assertNotIn("INSERTION_JUSTIFIED_ONLY_BY_GATE_THRESHOLD", codes(r["violations"]))
        self.assertIn("INSERTION_MISSING_NEW_INFORMATION_FIELD", codes(r["violations"]),
                      "缺字段仍是形式违规 —— seq=51 c2 明写『字段仍然必须写』")

    def test_landed_scene_that_only_restates_earlier_text_is_refused(self):
        """正文每一格都能在更早正文里找到 ⇒ 复述 ⇒ 拒绝条款成立。"""
        line = "红衣巷两头各站着一排蓑衣，中间没有人走动。"
        doc = canonical_doc([("E51-S01", line), ("E51-S03", line)])
        p = write_pair(manifest_with(GATE_MOTIVE_NO_FIELD), doc)
        r = evaluate(p)
        self.assertIn("INSERTION_JUSTIFIED_ONLY_BY_GATE_THRESHOLD", codes(r["violations"]))

    def test_empty_scene_body_is_pure_restatement(self):
        doc = canonical_doc([("E51-S01", "有人敲门。"), ("E51-S03", "")])
        got = _landed_scene_finding("E51-S03", doc, 51, tempfile.mkdtemp())
        self.assertEqual(got["verdict"], "PURE_RESTATEMENT")

    def test_unresolvable_scene_falls_back_to_prose_and_says_so(self):
        """canonical 不在盘上 ⇒ 不得把『查不到』悄悄当成『没有』。"""
        p = write_tmp(manifest_with(GATE_MOTIVE_NO_FIELD), "E51_manifest_v5.json")
        r = evaluate(p)
        self.assertIn("LANDED_SCENE_TEXT_UNRESOLVABLE_FELL_BACK_TO_PROSE", codes(r["diagnostics"]))
        self.assertIn("INSERTION_JUSTIFIED_ONLY_BY_GATE_THRESHOLD", codes(r["violations"]))

    def test_scene_id_absent_from_canonical_is_unresolvable_not_refusal(self):
        doc = canonical_doc([("E51-S01", "有人敲门。")])
        got = _landed_scene_finding("E51-S03", doc, 51, tempfile.mkdtemp())
        self.assertEqual(got["verdict"], "UNRESOLVABLE")

    def test_scene_splitter_keeps_order_and_drops_headings(self):
        doc = canonical_doc([("E51-S01", "甲。"), ("E51-S02", "乙。")])
        got = _split_canonical_scenes(doc)
        self.assertEqual(list(got), ["E51-S01", "E51-S02"])
        self.assertNotIn("LOC-X", got["E51-S01"])


class TestNewInformationMustBeAnchoredInTheScene(unittest.TestCase):
    """判在落地场次上的另一半：字段漂亮而正文不交货。"""

    def test_claim_absent_from_the_scene_is_a_violation(self):
        ins = dict(GOOD_INSERTION, scene_id="E51-S03",
                   new_information="门槛上那把短刀不见了。")
        doc = canonical_doc([("E51-S01", "有人敲门。"),
                             ("E51-S03", "屋外雨势转大，屋檐水连成线。")])
        p = write_pair(manifest_with(ins), doc)
        self.assertIn("INSERTION_NEW_INFORMATION_NOT_ANCHORED_IN_LANDED_SCENE",
                      codes(evaluate(p)["violations"]))

    def test_claim_present_in_the_scene_passes(self):
        ins = dict(GOOD_INSERTION, scene_id="E51-S03",
                   new_information="门槛上那把短刀不见了。",
                   self_deduction="D4（−3.0 分）")
        doc = canonical_doc([("E51-S01", "有人敲门。"),
                             ("E51-S03", "门槛上那把短刀不见了，只剩一道裂口。")])
        p = write_pair(manifest_with(ins), doc)
        self.assertEqual(evaluate(p)["violations"], [])


class TestSelfDeductionSignAndUnit(unittest.TestCase):
    """seq=51 c3：E51 起负值带单位；E48／E49 的号差不回头改。"""

    def test_effective_episode(self):
        self.assertEqual(SELF_DEDUCTION_SIGN_EFFECTIVE_FROM, 51)

    def test_missing_unit_is_a_violation_from_e51(self):
        v, _ = check_insertions(manifest_with(dict(GOOD_INSERTION, self_deduction="D4（−3.0）")),
                                episode=51)
        self.assertIn("SELF_DEDUCTION_SIGN_OR_UNIT_MISSING", codes(v))

    def test_missing_sign_is_a_violation_from_e51(self):
        v, _ = check_insertions(manifest_with(dict(GOOD_INSERTION, self_deduction="D4（1.0 分）")),
                                episode=51)
        self.assertIn("SELF_DEDUCTION_SIGN_OR_UNIT_MISSING", codes(v))

    def test_negative_with_unit_passes(self):
        v, _ = check_insertions(manifest_with(dict(GOOD_INSERTION, self_deduction="D4（−3.0 分）")),
                                episode=51)
        self.assertNotIn("SELF_DEDUCTION_SIGN_OR_UNIT_MISSING", codes(v))

    def test_e49_style_sign_is_not_touched_before_e51(self):
        v, _ = check_insertions(manifest_with(dict(GOOD_INSERTION, self_deduction="D4（1.0 分）")),
                                episode=49)
        self.assertNotIn("SELF_DEDUCTION_SIGN_OR_UNIT_MISSING", codes(v))


class TestNonRetroactivity(unittest.TestCase):
    """seq=51 c1：不溯及已冻结、已裁 PASS 的既有插入项。"""

    def test_pre_e51_report_carries_the_non_retroactivity_block(self):
        ins = dict(GOOD_INSERTION)
        ins.pop("new_information")
        p = write_tmp(manifest_with(ins), "E50_manifest_v5.json")
        r = evaluate(p)
        self.assertFalse(r["retroactivity"]["applies"])
        self.assertEqual(r["p2_disclosures"], r["violations"])
        self.assertTrue(r["ok"])

    def test_e51_and_after_has_no_such_shelter(self):
        ins = dict(GOOD_INSERTION)
        ins.pop("new_information")
        p = write_tmp(manifest_with(ins), "E51_manifest_v5.json")
        r = evaluate(p)
        self.assertNotIn("retroactivity", r)
        self.assertFalse(r["ok"])


@unittest.skipUnless(os.path.exists(E49_MANIFEST) and os.path.exists(E49_CANONICAL),
                     "E49 v5 真件不在盘上")
class TestAgainstRealE49V5(unittest.TestCase):
    """seq=51 c2 显式点名的那一条，机器独立复现监制的读数。"""

    def setUp(self):
        self.report = evaluate(E49_MANIFEST)

    def test_ins_e49_01_no_longer_trips_the_refusal_clause(self):
        self.assertNotIn("INSERTION_JUSTIFIED_ONLY_BY_GATE_THRESHOLD",
                         codes(self.report["violations"]))

    def test_the_screen_lands_on_the_three_cells_the_supervisor_read(self):
        screens = [d for d in self.report["diagnostics"] if d["code"] == "LANDED_SCENE_NEW_FACT_SCREEN"]
        self.assertEqual(len(screens), 1)
        got = json.loads(screens[0]["detail"])
        self.assertEqual(got["verdict"], "NEW_FACT_CANDIDATES")
        self.assertEqual(len(got["cells"]), 3)
        self.assertIn("雨水从赌坊门槛下面流出来，是淡红色的。", got["cells"])
        self.assertIn("一个想出巷的人被抬手拦住，退回门檐底下。", got["cells"])

    def test_e49_is_not_blocked_and_is_sheltered_by_c1(self):
        self.assertEqual(self.report["episode"], 49)
        self.assertTrue(self.report["ok"])
        self.assertFalse(self.report["retroactivity"]["applies"])

    def test_e49_readout_is_exactly_one_item_and_it_is_the_missing_field(self):
        """E49 v5 在新判据下的完整读数，逐条钉住。字段缺仍报，场不动。"""
        self.assertEqual(codes(self.report["violations"]),
                         ["INSERTION_MISSING_NEW_INFORMATION_FIELD"])


class TestEnforcementWindowUsesLineageNotFilename(unittest.TestCase):
    """seq=49 c1 血统认证键 × seq=51 c1 的伞：文件名集号不足以认归属。

    盘上 68 份编号 ≥E51 的 manifest 全是改基前旧稿。照文件名判，它们会被当成
    「新集」进阻断档，同时拿不到 c1 给冻结历史件的伞 —— 伞被从最需要它的人手里抽走。
    """

    PRE_REBASE_HEAD = ("# 《青山》E54 叙事权威 v3\n"
                       "源绑定依据 configs/episode_source_map_v2_observed_20260821.json（OBSERVED）：E54＝ch56。\n")
    POST_REBASE_HEAD = ("# 《青山》E51 叙事权威 v4\n"
                        "源绑定依据 configs/episode_source_map_rebase_v1_20260828.json：E51＝ch56。\n")

    def _report(self, head, episode):
        ins = dict(GOOD_INSERTION)
        ins.pop("new_information")
        doc = head + canonical_doc([("E%d-S01" % episode, "有人敲门。"),
                                    ("E51-S03", "门槛上那把短刀不见了。")])
        return evaluate(write_pair(manifest_with(ins), doc, episode=episode, version=4))

    def test_pre_rebase_file_numbered_above_51_is_not_blocked(self):
        r = self._report(self.PRE_REBASE_HEAD, 54)
        self.assertEqual(r["lineage"]["era"], "PRE_REBASE")
        self.assertEqual(r["enforcement"], "DIAGNOSTIC_ONLY")
        self.assertTrue(r["ok"])
        self.assertIn("血统认证键", r["retroactivity"]["shelter_basis"])

    def test_post_rebase_new_episode_is_blocked(self):
        r = self._report(self.POST_REBASE_HEAD, 51)
        self.assertEqual(r["lineage"]["era"], "POST_REBASE")
        self.assertEqual(r["enforcement"], "BLOCKING")
        self.assertFalse(r["ok"])

    def test_undeclared_lineage_falls_back_to_the_filename_number(self):
        r = self._report("# 无抬头\n", 51)
        self.assertEqual(r["lineage"]["era"], "UNDECLARED")
        self.assertEqual(r["enforcement"], "BLOCKING")


if __name__ == "__main__":
    unittest.main(verbosity=2)
