"""Anti-template v2 (owner 2026-11-23, CHANGE_SPEC WP2): distinctness / periodicity / similarity checks replace the
phrase blacklists for BILI_V1 contracts.

Covers checks 1-7 of the spec (scene cards, action density, touch, props, emotion periodicity, action-text
similarity, generator script), their severity (integrity under SCREENPLAY_V1, taste for a BILI_V1 contract JSON),
the archived fleet contracts that motivated them (1101 E25, 1485 E11 -- trimmed fixtures trip EMOTION_PERIODIC,
ACTION_TEXT_TEMPLATE and SCENE_CARD_REPEATED), the pacing-report wiring, the seq29 split (LEGACY keeps R7B/R7C,
SCREENPLAY_V1 derives emotions) and LEGACY byte-identity of the S1 pacing / self-check decisions against a golden
recorded on origin/main 4103b32.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import nalu_writer_selfcheck_seq29 as s29  # noqa: E402
import screenplay_checks as spk  # noqa: E402
import screenplay_compile as spc  # noqa: E402
import script_pacing_check as pace  # noqa: E402

FIX = ROOT / "tools" / "tests" / "fixtures" / "anti_template_v2"
E25_FIX = ROOT / "tools" / "tests" / "fixtures" / "screenplay_e25"


def archived(name: str, **stamp) -> dict:
    contract = json.loads((FIX / f"archived_{name}_trimmed.json").read_text(encoding="utf-8"))
    contract.update(stamp)
    return contract


def codes(rows: list[str]) -> set[str]:
    return {r.split(":", 1)[0] for r in rows}


def screenplay_contract() -> dict:
    return spc.compile_files(E25_FIX, "E25")["contract"]


BILI = {"craft_profile": "BILI_V1"}
SP = {"craft_profile": "BILI_V1", "writer_format": "SCREENPLAY_V1"}


class ArchivedContractsTest(unittest.TestCase):
    def test_e25_rotation_and_identical_scene_cards(self):
        out = spk.evaluate(archived("e25", **SP))
        self.assertIn("EMOTION_PERIODIC:5:0.95", out["integrity"])
        self.assertTrue({"SCENE_CARD_REPEATED", "EMOTION_PERIODIC"} <= codes(out["integrity"]))
        for field in ("goal", "obstacle", "turn"):
            self.assertIn(f"SCENE_CARD_REPEATED:{field}:pairs=10", out["integrity"])

    def test_e11_cycle_with_inserts_and_action_template(self):
        out = spk.evaluate(archived("e11", **SP))
        self.assertEqual({"SCENE_CARD_REPEATED", "EMOTION_PERIODIC", "ACTION_TEXT_TEMPLATE"}, codes(out["integrity"]))
        self.assertIn("EMOTION_PERIODIC:4:0.83", out["integrity"])  # sad/confident/fearful/surprised (+happy/angry)
        self.assertTrue(any(c.startswith("ACTION_TEXT_TEMPLATE:pairs=") for c in out["integrity"]))

    def test_bili_contract_json_is_taste_and_legacy_runs_nothing(self):
        out = spk.evaluate(archived("e11", **BILI))
        self.assertEqual([], out["integrity"])
        self.assertTrue({"SCENE_CARD_REPEATED", "EMOTION_PERIODIC", "ACTION_TEXT_TEMPLATE"} <= codes(out["taste"]))
        self.assertFalse(spk.evaluate(archived("e11"))["active"])
        self.assertFalse(spk.evaluate(archived("e11", writer_format="SCREENPLAY_V1"))["active"])  # LEGACY wins


class ChecksTest(unittest.TestCase):
    def test_scene_cards_distinct_after_name_masking(self):
        c = {**SP, "character_entities": [{"canonical_name": "林乔"}, {"canonical_name": "周衡"}],
             "pacing": {"scene_plan": [
                 {"scene_id": "E01-S01", "objective": "林乔逼周衡在S01签字", "conflict": "周衡拖延", "physical_action": "夺笔"},
                 {"scene_id": "E01-S02", "objective": "周衡逼林乔在S02签字", "conflict": "门被反锁", "physical_action": "摔门"},
                 {"scene_id": "E01-S03", "objective": "找到账本", "conflict": "保安巡逻", "physical_action": "藏进柜子"}]}}
        self.assertEqual(["SCENE_CARD_REPEATED:goal:E01-S01,E01-S02"], spk.scene_card_repeats(c))

    def test_similarity_and_mask(self):
        a = spk.mask("Rei Taylor grabs the prop in response to the exact line: 次は私が。", [], ["次は私が。"])
        b = spk.mask("Claire Francois grabs the prop in response to the exact line: あなたは。", [], ["あなたは。"])
        self.assertEqual(1.0, spk.similarity(a, b))
        self.assertLess(spk.similarity(spk.mask("白桃停下令牌，磕在扶手上", ["白桃"]),
                                       spk.mask("麒麟冲上一步，抓住商余烬的袖子", ["麒麟", "商余烬"])), 0.2)

    def test_periodicity(self):
        self.assertEqual((0, 0.0, ""), spk.periodicity(["怒"] * 12))  # constant: R7C's business, not a cycle
        self.assertGreaterEqual(spk.periodicity(list("冷喜怜急狠" * 3))[1], 0.8)
        self.assertLess(spk.periodicity(list("傲怯讥冷疑坚狠疑戏倦急怜"))[1], 0.6)
        self.assertEqual((0, 0.0, ""), spk.periodicity(list("冷喜怜冷")))  # too short to call

    def test_action_template_skips_fallback_rows(self):
        def row(sid, text, source="screenplay", line="甲：好。"):
            return {"shot_id": sid, "prompt_spec": {"dialogue": line, "action": {"primary_action": text,
                                                                                 "source": source}}}
        c = {**SP, "character_entities": [{"canonical_name": "甲"}, {"canonical_name": "乙"}], "shots": [
            row("E01-S01-01", "甲对乙说出「好。」", "fallback"), row("E01-S01-02", "甲对乙说出「好。」", "fallback"),
            row("E01-S01-03", "甲抓起桌上的茶盏摔在地上"), row("E01-S01-04", "乙抓起桌上的茶盏摔在地上")]}
        self.assertEqual(["ACTION_TEXT_TEMPLATE:E01-S01-03,E01-S01-04"], spk.action_templates(c))

    def test_detail_checks_on_the_screenplay_block(self):
        c = screenplay_contract()
        self.assertEqual(([], []), (spk.detail_checks(c)[0], spk.detail_checks(c)[1]))
        thin = copy.deepcopy(c)
        scene = thin["screenplay_v1"]["scenes"][0]
        scene["lines"] = [ln for ln in scene["lines"] if ln["kind"] != "action"] + [
            {"kind": "action", "text": "战雷拱手。", "subject": "CHAR-ZHANLEI", "named": ["CHAR-ZHANLEI"]},
            {"kind": "action", "text": "白桃把玉佩扔给战雷。", "subject": "CHAR-BAITAODIJI",
             "named": ["CHAR-BAITAODIJI", "CHAR-ZHANLEI"]}]
        taste, advisory, _ = spk.detail_checks(thin)
        self.assertIn("ACTION_LINES_THIN:E25-S01:2/12", taste)
        self.assertIn("NO_TOUCH_IN_TWO_PERSON_SCENE:E25-S01", taste)
        self.assertIn("PROP_UNDECLARED:玉佩", advisory)
        self.assertIn("PROP_UNUSED:PROP-ZHANLEI-SPEAR", advisory)

    def test_generator_script_is_integrity(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "build_e25_layers.py").write_text("# generator\n", encoding="utf-8")
            files = spk.generator_scripts("E25", Path(d))
            self.assertEqual(1, len(files))
            out = spk.evaluate(screenplay_contract(), generator_files=files)
            self.assertEqual(["GENERATOR_SCRIPT_PRESENT:build_e25_layers.py"], out["integrity"])
            self.assertIn("GENERATOR_SCRIPT_PRESENT", out["fixes"])
            self.assertEqual([], spk.evaluate(archived("e25", **BILI), generator_files=files)["integrity"])


class PacingWiringTest(unittest.TestCase):
    def test_screenplay_integrity_reaches_the_pacing_report(self):
        report = pace.evaluate(archived("e11", **SP), "ja")
        self.assertEqual("FAIL", report["integrity_status"])
        self.assertTrue({"EMOTION_PERIODIC", "ACTION_TEXT_TEMPLATE"} <= codes(report["integrity_failures"]))
        self.assertIn("EMOTION_PERIODIC", report["fixes"])
        self.assertTrue(pace.integrity_blocker_codes(report)[0].startswith("SCRIPT_INTEGRITY_FAIL:"))
        # the phrase blacklist / placeholder check is superseded for SCREENPLAY_V1, kept for BILI contract JSON
        self.assertNotIn("PERFORMANCE_PLACEHOLDER", codes(report["failures"]))
        bili = pace.evaluate(archived("e11", **BILI), "ja")
        self.assertIn("PERFORMANCE_PLACEHOLDER", codes(bili["failures"]))
        self.assertIn("EMOTION_PERIODIC", codes(bili["failures"]))
        self.assertEqual([], bili["integrity_failures"])

    def test_compiled_screenplay_is_integrity_clean(self):
        report = pace.evaluate(screenplay_contract(), "zh")
        self.assertEqual("PASS", report["integrity_status"])
        self.assertEqual(3, report["metrics"]["screenplay_checks"]["touches_per_scene"]["E25-S01"])


class Seq29SplitTest(unittest.TestCase):
    def _three_in_a_row(self, **stamp) -> dict:
        c = screenplay_contract()
        for k in ("craft_profile", "writer_format"):
            c.pop(k, None)
        c.update(stamp)
        lines = [s for s in c["shots"] if s["prompt_spec"]["dialogue"]][:3]
        for s in lines:
            s["prompt_spec"]["action"]["performance"]["emotion"] = "怒"
        lines[0]["prompt_spec"]["action"]["performance"].pop("emotion")
        lines[1]["prompt_spec"]["action"]["performance"]["emotion"] = "怒"
        return c

    def test_legacy_keeps_r7b_and_r7c(self):
        failures = s29.evaluate(self._three_in_a_row())["failures"]
        self.assertTrue(any(f.startswith("R7B_PERFORMANCE_INCOMPLETE") and f.endswith(":emotion") for f in failures))

    def test_screenplay_v1_derives_emotions(self):
        failures = s29.evaluate(self._three_in_a_row(**SP))["failures"]
        self.assertFalse(any(f.startswith(("R7B_PERFORMANCE_INCOMPLETE", "R7C_EMOTION_REPEATED")) for f in failures),
                         failures)
        c = self._three_in_a_row(**SP)
        for s in [s for s in c["shots"] if s["prompt_spec"]["dialogue"]][:3]:
            s["prompt_spec"]["action"]["performance"]["emotion"] = "怒"
        self.assertFalse(any(f.startswith("R7C_EMOTION_REPEATED") for f in s29.evaluate(c)["failures"]))
        legacy = self._three_in_a_row()
        for s in [s for s in legacy["shots"] if s["prompt_spec"]["dialogue"]][:3]:
            s["prompt_spec"]["action"]["performance"]["emotion"] = "怒"
        self.assertTrue(any(f.startswith("R7C_EMOTION_REPEATED") for f in s29.evaluate(legacy)["failures"]))


class LegacyByteIdentityTest(unittest.TestCase):
    """S1 pacing + seq29 decisions on archived LEGACY contracts equal the golden recorded on origin/main 4103b32."""

    def test_golden(self):
        golden = json.loads((FIX / "legacy_golden_origin_main_4103b32.json").read_text(encoding="utf-8"))
        for name in ("e25", "e11"):
            contract = archived(name)
            report = pace.evaluate(contract)
            selfcheck = s29.evaluate(contract)
            now = {"pace": {k: report[k] for k in ("status", "failures", "warnings", "integrity_failures",
                                                   "integrity_status", "boilerplate_warnings", "fixes")},
                   "seq29": {k: selfcheck.get(k) for k in ("status", "failures", "warnings")}}
            self.assertEqual(json.dumps(golden[name], ensure_ascii=False, sort_keys=True),
                             json.dumps(now, ensure_ascii=False, sort_keys=True), name)

    def test_legacy_never_imports_the_checks_path(self):
        with mock.patch.object(spk, "evaluate", side_effect=AssertionError("called under LEGACY")):
            pace.evaluate(archived("e25"))
        self.assertEqual({}, pace.screenplay_checks_row(archived("e25")))


if __name__ == "__main__":
    unittest.main()
