"""BILI_V1 L5 carry-through (CHANGE_SPEC WP4): screenplay action / prop / reaction text reaches the H3 prompt.

Everything is gated on the BILI_V1 craft profile: a LEGACY unit (no ``craft_profile``) with the very same authored
fields renders byte-identically to before (pinned by test_h3_director_prompt_v2.V1_SHA).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

from tools import bili_carry as carry
from tools import compile_grouped_seedance_manifest as grouped
from tools import script_structure_contract_gate as structure
from tools.h3_provider_prompt_renderer import render_h3_prompt
from tools.provider_semantic_coverage import build_semantic_coverage_receipt
from tools.submit_giggle_video_manifest_v2 import provider_prompt_unit
from tools.tests.test_h3_director_prompt_v2 import A, B, V1_SHA, fixture

ROOT = Path(__file__).resolve().parents[2]
RT = ROOT / "lines" / "nalu" / "runtime" / "tools"
if str(RT) not in sys.path:
    sys.path.insert(0, str(RT))
import nalu_craft_standard as craft  # noqa: E402

LEAD = "Alpha exhales once and sets the war token on the table"
LISTEN = "Beta's fingers tighten on the armrest"
TOKEN = {"prop_id": "PROP-TOKEN", "prop": "战神令", "english_name": "war token",
         "description_en": "a palm-sized black iron war token", "holder_id": A, "hand": "right"}


def authored(unit: dict, *, bili: bool) -> dict:
    """The fixture unit with the WP4 fields authored (and the BILI_V1 stamp when ``bili``)."""
    spec = unit["ordered_prompt_specs"][0]
    spec["action"] = {"listener_reaction_en": LISTEN, "lead_in_reaction_en": LEAD}
    spec["props"] = [dict(TOKEN)]
    if bili:
        unit["craft_profile"] = "BILI_V1"
    return unit


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class LegacyByteIdentity(unittest.TestCase):
    def test_legacy_v1_with_the_new_fields_renders_byte_identically(self):
        for director in (True, False):
            unit, plan = fixture(style=False, director=director)
            text, _ = render_h3_prompt(authored(unit, bili=False), plan)
            self.assertEqual(sha(text), V1_SHA[director])

    def test_legacy_v2_with_the_new_fields_is_unchanged(self):
        unit, plan = fixture(listener=LISTEN)
        before, before_receipt = render_h3_prompt(unit, plan)
        unit, plan = fixture()
        after, receipt = render_h3_prompt(authored(unit, bili=False), plan)
        self.assertEqual(before, after)
        self.assertNotIn("For the first", after)
        self.assertNotIn("In hand:", after)
        self.assertNotIn("authored_fact_ids_kept", receipt["provider_semantic_coverage_receipt"])

    def test_legacy_codex_section_is_unchanged(self):
        self.assertEqual(craft.codex_section(ROOT), craft.codex_section(ROOT, craft_profile="LEGACY"))
        self.assertNotIn("BILI_V1", craft.codex_section(ROOT))


class V1RendererBili(unittest.TestCase):
    def test_v1_renders_listener_and_lead_in_reaction(self):
        for director in (True, False):
            unit, plan = fixture(style=False, director=director)
            text, receipt = render_h3_prompt(authored(unit, bili=True), plan)
            self.assertIn("[0s-3s] For the first 1.5 seconds, before speaking, Alpha exhales once and sets the war "
                          "token on the table. Start from", text)
            self.assertIn("Beta's fingers tighten on the armrest.", text)
            self.assertEqual(receipt["provider_semantic_coverage_receipt"]["status"], "PASS")

    def test_v1_roster_names_the_prop_in_hand(self):
        unit, plan = fixture(style=False, director=True)
        text, _ = render_h3_prompt(authored(unit, bili=True), plan)
        self.assertIn("Alpha's right hand holds the palm-sized black iron war token.", text)

    def test_per_listener_reaction(self):
        unit, plan = fixture(style=False, director=True)
        authored(unit, bili=True)["ordered_prompt_specs"][0]["action"]["listener_reaction_en"] = {B: "looks away"}
        text, _ = render_h3_prompt(unit, plan)
        self.assertIn("Beta: looks away.", text)


class V2RendererBili(unittest.TestCase):
    def test_v2_lead_in_first_and_listener_reaction(self):
        unit, plan = fixture()
        text, _ = render_h3_prompt(authored(unit, bili=True), plan)
        action = text.split("Action (0", 1)[1]
        self.assertIn("For the first 1.5 seconds, before speaking, Alpha exhales once", action)
        self.assertLess(action.index("For the first"), action.index("Start:"))
        self.assertIn("Beta's fingers tighten on the armrest.", action)
        self.assertNotIn("Beta listens without speaking", text)

    def test_v2_who_is_in_frame_names_the_prop_in_hand(self):
        unit, plan = fixture()
        text, _ = render_h3_prompt(authored(unit, bili=True), plan)
        who = text.split("Who is in frame", 1)[1].split("\n\nSetting:", 1)[0]
        self.assertIn("In hand: Alpha's right hand holds the palm-sized black iron war token.", who)

    def test_holder_out_of_frame_is_not_named(self):
        unit, plan = fixture()
        authored(unit, bili=True)["ordered_prompt_specs"][0]["props"][0]["holder_id"] = "CHAR-NOBODY"
        text, _ = render_h3_prompt(unit, plan)
        self.assertNotIn("In hand:", text)

    def _micro(self, source: str) -> tuple[str, dict]:
        unit, plan = fixture()
        authored(unit, bili=True)
        unit["ordered_prompt_specs"][0]["action"]["field_sources"] = {"microexpression_design": source}
        plan["beats"][0]["microexpression_cue"] = "眼神一冷"
        unit["h3_provider_english_contract"]["beats"][0]["microexpression_cue"] = "Alpha's eyes turn cold"
        return render_h3_prompt(unit, plan)

    def test_authored_microexpression_is_stated_not_dropped(self):
        text, receipt = self._micro("authored")
        self.assertIn("Face: Alpha's eyes turn cold.", text)
        coverage = receipt["provider_semantic_coverage_receipt"]
        self.assertEqual(coverage["status"], "PASS")
        self.assertEqual(coverage["authored_fact_ids_kept"], ["BEAT.1.MICROEXPRESSION"])
        self.assertNotIn("BEAT.1.MICROEXPRESSION", coverage["style_omitted_fact_ids"])

    def test_fallback_microexpression_stays_omitted(self):
        text, receipt = self._micro("fallback")
        self.assertNotIn("Face:", text)
        self.assertIn("BEAT.1.MICROEXPRESSION",
                      receipt["provider_semantic_coverage_receipt"]["style_omitted_fact_ids"])

    def test_kept_fact_fails_closed_when_not_in_the_prompt(self):
        unit, plan = fixture()
        plan["beats"][0]["microexpression_cue"] = "眼神一冷"
        receipt = build_semantic_coverage_receipt(plan=plan, prompt_text="nothing", model_family="MINIMAX_H3",
                                                  clause_evidence={}, prompt_style="DIRECTOR_PROMPT_V2",
                                                  keep_fact_ids=["BEAT.1.MICROEXPRESSION"])
        self.assertIn("PROVIDER_SEMANTIC_FACT_UNCOVERED:E64-VU-T01:BEAT.1.MICROEXPRESSION", receipt["failures"])


class CompilerAndTransport(unittest.TestCase):
    def setUp(self):
        from tools import craft_profile  # noqa: F401 - loads the implementation module
        self.runtime = Path(tempfile.mkdtemp())
        impl = sys.modules["nalu_craft_profile_impl"]
        patcher = mock.patch.object(impl, "default_runtime_root", return_value=self.runtime)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_bili_v1_stamps_profile_and_v2_default(self):
        units = [{"unit_id": "U1", "model": "MiniMax-H3"}, {"unit_id": "U2", "model": "Seedance"},
                 {"unit_id": "U3", "model": "MiniMax-H3", "h3_prompt_style": "OTHER"}]
        self.assertTrue(grouped.stamp_bili_v1_units(units, {"craft_profile": "BILI_V1"}, episode="E01"))
        self.assertEqual(units[0], {"unit_id": "U1", "model": "MiniMax-H3", "craft_profile": "BILI_V1",
                                    "h3_prompt_style": "DIRECTOR_PROMPT_V2", "h3_prompt_format": "OFFICIAL_REF_V1"})
        self.assertEqual(units[1], {"unit_id": "U2", "model": "Seedance"})
        self.assertEqual(units[2]["h3_prompt_style"], "OTHER")
        # the contract's h3_prompt_format=DIRECTOR_V2 keeps the previous V2 text (official-format A/B 2026-11-27)
        legacy = [{"unit_id": "U4", "model": "MiniMax-H3"}]
        self.assertTrue(grouped.stamp_bili_v1_units(legacy, {"craft_profile": "BILI_V1",
                                                             "h3_prompt_format": "DIRECTOR_V2"}, episode="E01"))
        self.assertEqual(legacy[0]["h3_prompt_format"], "DIRECTOR_V2")

    def test_runtime_switch_and_legacy_default(self):
        units = [{"unit_id": "U1", "model": "MiniMax-H3"}]
        self.assertFalse(grouped.stamp_bili_v1_units(units, {}, episode="E01"))
        self.assertEqual(units, [{"unit_id": "U1", "model": "MiniMax-H3"}])
        (self.runtime / "qingshan.json").write_text(json.dumps({"project": {"craft_profile": "BILI_V1"}}))
        self.assertTrue(grouped.stamp_bili_v1_units(units, {}, episode="E01"))

    def test_task_carries_the_profile_to_the_paid_boundary_render(self):
        self.assertEqual(provider_prompt_unit({"model": "MiniMax-H3", "craft_profile": "BILI_V1"})["craft_profile"],
                         "BILI_V1")
        self.assertNotIn("craft_profile", provider_prompt_unit({"model": "MiniMax-H3"}))
        # the H3 prompt format reaches the paid-boundary re-render too, else it would re-render V2 and mismatch
        self.assertEqual(provider_prompt_unit({"model": "MiniMax-H3", "h3_prompt_format": "OFFICIAL_REF_V1"})
                         ["h3_prompt_format"], "OFFICIAL_REF_V1")
        self.assertNotIn("h3_prompt_format", provider_prompt_unit({"model": "MiniMax-H3"}))


def contract(**action) -> dict:
    return {"episode": "E01", "shots": [{"shot_id": "E01-S01-01", "scene_id": "E01-S01", "target_seconds": 3,
                                         "prompt_spec": {"action": dict(action), "props": []}}]}


class EnTwinCheck(unittest.TestCase):
    def test_missing_twins_are_named_per_shot_and_field(self):
        c = contract(primary_action="他把战神令按在扶手上", listener_reaction="她攥紧袖子", lead_in_reaction="他先冷笑",
                     performance={"delivery": "压低声音"})
        c["shots"][0]["prompt_spec"]["props"] = [{"prop_id": "PROP-TOKEN", "description": "黑铁令牌"}]
        c["non_character_entities"] = [{"entity_id": "PROP-TOKEN", "description": "黑铁令牌，巴掌大"}]
        self.assertEqual(carry.en_twin_failures(c), [
            "EN_TWIN_MISSING:E01-S01-01:business_en", "EN_TWIN_MISSING:E01-S01-01:listener_reaction_en",
            "EN_TWIN_MISSING:E01-S01-01:lead_in_reaction_en", "EN_TWIN_MISSING:E01-S01-01:delivery_en",
            "EN_TWIN_MISSING:E01-S01-01:props[PROP-TOKEN].description_en", "EN_TWIN_MISSING:PROP-TOKEN:description_en"])

    def test_english_twins_pass_and_chinese_twins_fail(self):
        ok = contract(primary_action="他把战神令按在扶手上", business_en="presses the war token onto the armrest",
                      listener_reaction="她攥紧袖子", listener_reaction_en={"CHAR-B": "grips her sleeve"})
        self.assertEqual(carry.en_twin_failures(ok), [])
        bad = contract(primary_action="他把战神令按在扶手上", business_en="按在扶手上")
        self.assertEqual(carry.en_twin_failures(bad), ["EN_TWIN_MISSING:E01-S01-01:business_en"])

    def test_structure_gate_checks_only_under_bili_v1(self):
        c = contract(primary_action="他把战神令按在扶手上")
        legacy = structure.evaluate(c)
        self.assertNotIn("en_twins", legacy["measurements"])
        self.assertFalse(any(f.startswith("EN_TWIN_MISSING") for f in legacy["failures"]))
        bili = structure.evaluate(c, craft_profile="BILI_V1")
        self.assertIn("EN_TWIN_MISSING:E01-S01-01:business_en", bili["failures"])
        self.assertIn("keep the object, the hand, the verb", bili["measurements"]["en_twins"]["rule"])
        self.assertIn("EN_TWIN_MISSING:E01-S01-01:business_en",
                      structure.evaluate({**c, "craft_profile": "BILI_V1"})["failures"])


class CodexCompressedText(unittest.TestCase):
    def test_bili_section_carries_the_coverage_rules_within_the_cap(self):
        section = craft.codex_section(ROOT, craft_profile="BILI_V1")
        self.assertLessEqual(len(section), craft.MAX_CODEX_SECTION_CHARS)
        for needle in ("过肩", "≥2 个双人", "反应", "BACK_AND_SHOULDERS_ONLY", "CU+MCU ≤80%", "lead_in_reaction",
                       "推近", "台账", "不写生成脚本", "EN_TWIN_MISSING"):
            self.assertIn(needle, section)
        body = craft.load_items(ROOT)["codex_compressed_zh_bili_v1"]
        self.assertIn(body, section)  # not truncated
        self.assertNotIn("双人同框只在无对白时", section)  # the old C-07 contradiction is gone
        anime = craft.codex_section(ROOT, craft_profile="BILI_V1", render_style="anime")
        self.assertLessEqual(len(anime), craft.MAX_CODEX_SECTION_CHARS)


if __name__ == "__main__":
    unittest.main()


class EditorialCarry(unittest.TestCase):
    """PRE build_editorial (WP4 items 4-5): BILI_V1 copies the writer's twins, field sources and prop holders."""

    @classmethod
    def setUpClass(cls):
        from tools.tests import test_voice_over_narration as vo_test
        cls.vo = vo_test
        try:
            cls.bnp = vo_test.load("bnp_bili_carry", vo_test.NALU_TOOLS / "build_nalu_preproduction.py")
        except Exception as exc:  # noqa: BLE001 - the module needs the full engine tree
            raise unittest.SkipTest(f"build_nalu_preproduction not importable: {exc}")

    def build(self, *, bili: bool):
        vo = self.vo
        row = vo.shot("E01-S01-01", 3.0, "Elias：Not yet.", cast=[vo.ELIAS], speaker_id=vo.ELIAS)
        row["prompt_spec"]["action"].update(
            lead_in_reaction_en="Elias exhales once", business_en="presses the token onto the desk",
            microexpression_design="眼神一冷", performance={"delivery_en": "low and clipped"})
        row["prompt_spec"]["props"] = [{"prop_id": "PROP-TOKEN", "holder_id": vo.ELIAS, "hand": "right"}]
        contract, plan_rows, index = vo.editorial_inputs([row], vo.entities(with_ledger=False))
        contract["non_character_entities"] = [{"entity_id": "PROP-TOKEN", "name": "令牌",
                                               "english_name": "war token", "description_en": "a black iron token"}]
        plan_rows[0]["prop_ids"] = ["PROP-TOKEN"]
        if bili:
            contract["craft_profile"] = "BILI_V1"
        engine = SimpleNamespace(dialogue_limit=200, dialogue_length=len, language="en")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, vo.CURRENT, clear=False):
            root = Path(tmp)
            (root / "c.json").write_text("{}\n")
            (root / "g.json").write_text("{}\n")
            manifest, _ = self.bnp.build_editorial(contract, plan_rows, index, engine, "E01",
                                                   root / "c.json", root / "g.json", root)
        return manifest["shots"][0]["prompt_spec"]

    def test_legacy_spec_is_unchanged(self):
        spec = self.build(bili=False)
        for key in ("lead_in_reaction_en", "business_en", "field_sources"):
            self.assertNotIn(key, spec["action"])
        self.assertEqual(sorted(spec["props"][0]), sorted(["prop", "prop_id", "anchor", "continuity_scope", "note"]))

    def test_bili_carries_twins_sources_performance_and_holder(self):
        spec = self.build(bili=True)
        action = spec["action"]
        self.assertEqual(action["lead_in_reaction_en"], "Elias exhales once")
        self.assertEqual(action["business_en"], "presses the token onto the desk")
        self.assertEqual(action["performance"], {"delivery_en": "low and clipped"})
        self.assertEqual(action["field_sources"]["microexpression_design"], "authored")
        self.assertEqual(action["field_sources"]["physical_action_design"], "fallback")
        self.assertEqual(action["performance_business_en"], "presses the token onto the desk")
        prop = spec["props"][0]
        self.assertEqual((prop["holder_id"], prop["hand"], prop["description_en"]),
                         (self.vo.ELIAS, "right", "a black iron token"))
