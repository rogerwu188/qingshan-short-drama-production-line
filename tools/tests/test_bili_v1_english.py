"""BILI_V1 + SCREENPLAY_V1 on an English series (device 1205, 2026-11-28; the profile had only run on a zh line).

Covers: an English screenplay (English names, prose and dialogue; fixtures/screenplay_en_e25) compiles with no
translation request and passes the S1 structure gate (English action verbs give CONTACT / POSSESSION / POSITION, so
a silent opening hook is not POSTURE-only); the series language outranks a CAST_PROPS copied from the zh example;
Chinese dialogue on an English series is a compile error; colon tags and reactions with multi-word English names;
the dialogue register gate's English verbatim run (words, not 8 letters); static R8 strips a long English speaker
label; the official H3 format drops the authored-world lock's all-caps title (it failed the V2 self-check) and
tags the line <d>[English]. Zero credits.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import screenplay_compile as spc  # noqa: E402
import static_design_gate as sdg  # noqa: E402
from tools import dialogue_register_gate as drg  # noqa: E402
from tools import h3_official_ref_prompt as official  # noqa: E402
from tools import script_structure_contract_gate as ssg  # noqa: E402
from tools.h3_provider_prompt_renderer import render_h3_prompt  # noqa: E402

FIXTURE = ROOT / "tools" / "tests" / "fixtures" / "screenplay_en_e25"
LAB = ROOT / "tools" / "tests" / "fixtures" / "snippet_lab_en"
LEXICON = ROOT / "lines" / "nalu" / "runtime" / "configs" / "LEXICON_portable_template_v1.json"
CJK = re.compile(r"[㐀-鿿]")


def _copy_fixture(tmp: str) -> Path:
    dst = Path(tmp) / "scripts"
    shutil.copytree(FIXTURE, dst)
    return dst


class EnglishScreenplay(unittest.TestCase):
    def compile(self, scripts: Path = FIXTURE, brief=None):
        return spc.compile_files(scripts, "E25", brief=brief if brief is not None else {"series_dialogue_language": "en"})

    def test_compiles_without_translation_and_passes_structure(self):
        out = self.compile()
        report = out["report"]
        self.assertEqual(report["status"], "PASS", report.get("errors"))
        self.assertEqual(report.get("en_missing"), 0)
        self.assertFalse(report.get("en_fallback_used"))
        contract, manifest = out["contract"], out["manifest"]
        self.assertEqual(contract["dialogue_language"], "en")
        lexicon = json.loads(LEXICON.read_text(encoding="utf-8"))
        structure = ssg.evaluate(contract, manifest, lexicon, schema=ssg.load_contract_schema())
        self.assertEqual(structure["status"], "PASS", structure["failures"][:5])
        self.assertEqual(sdg.evaluate(contract, dict(sdg.POLICY))["failures"], [])
        # the writer's own English is the twin (no "says the line" compiler fallback for authored actions)
        first = contract["shots"][0]
        self.assertNotIn("#", json.dumps(first["prompt_spec"].get("action"), ensure_ascii=False))

    def test_english_verbs_give_action_dimensions(self):
        self.assertIn("CONTACT", spc._dims(["Mara grabs Doyle's wrist."], False))
        self.assertIn("POSSESSION", spc._dims(["Doyle hands over the token."], False))
        self.assertIn("POSITION", spc._dims(["Rhys stands and walks to the throne."], False))
        self.assertEqual(spc._dims(["A handsome man waits."], False), ["POSTURE"])  # "hand" is a whole word

    def test_series_language_outranks_a_copied_zh_cast_props(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts = _copy_fixture(tmp)
            path = scripts / "E25_CAST_PROPS.yaml"
            path.write_text(path.read_text(encoding="utf-8").replace("dialogue_language: en", "dialogue_language: zh"),
                            encoding="utf-8")
            out = self.compile(scripts)
            self.assertEqual(out["contract"]["dialogue_language"], "en")
            self.assertIn("DIALOGUE_LANGUAGE_OVERRIDDEN:zh->en", out["report"]["warnings"])
            # a zh series keeps the historical CAST_PROPS-first order
            self.assertEqual(self.compile(scripts, {"series_dialogue_language": "zh"})["contract"]["dialogue_language"],
                             "zh")

    def test_chinese_dialogue_on_an_english_series_is_a_compile_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts = _copy_fixture(tmp)
            path = scripts / "E25_SCREENPLAY.md"
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("Three days are up. Where is your king?", "三天到了。你们的王呢？", 1),
                            encoding="utf-8")
            errors = self.compile(scripts)["report"]["errors"]
            self.assertTrue(any(e.startswith("DIALOGUE_NOT_IN_SERIES_LANGUAGE:") for e in errors), errors)

    def test_tags_and_reactions_with_multi_word_names(self):
        self.assertEqual(spc._TAG.search("he spins it #先物:PROP:brass token:TILT_UP").group("tag"),
                         "先物:PROP:brass token:TILT_UP")
        self.assertEqual(spc._TAG.search("text #招牌").group("tag"), "招牌")
        m = spc._REACTION.match("[Mara Quinn 反应：her smile drops]")
        self.assertEqual(m.group("who"), "Mara Quinn")
        self.assertEqual(spc._REACTION.match("[凌瑶 反应：一怔]").group("who"), "凌瑶")


class EnglishGates(unittest.TestCase):
    def test_register_gate_english_verbatim_is_words_not_letters(self):
        policy = drg.policy_loaded()
        run = drg.verbatim_min_run_for("en", policy)
        self.assertEqual(run, 30)
        self.assertEqual(drg.verbatim_min_run_for("zh", policy), 8)
        source = "The kingdom was destroyed, and you are the king now, the old man said quietly by the fire."
        lines = [{"speaker": "Mara", "text": "You are the king? Then the hall is destroyed.", "shot_id": "S01-01"},
                 {"speaker": "Doyle", "text": "The kingdom was destroyed, and you are the king now.",
                  "shot_id": "S01-02"}]
        flagged = {row.get("shot_id") for row in drg.analyse(lines, source, verbatim_min_run=run)["verbatim"]}
        self.assertEqual(flagged, {"S01-02"})

    def test_static_r8_strips_a_long_english_speaker_label(self):
        contract = spc.compile_files(FIXTURE, "E25", brief={"series_dialogue_language": "en"})["contract"]
        spoken = [s for s in contract["shots"] if (s.get("prompt_spec") or {}).get("dialogue")]
        self.assertTrue(spoken)
        for shot in spoken:  # the compiler's "Name：line" with a long full English name
            line = shot["prompt_spec"]["dialogue"].split("：", 1)[-1].split(":", 1)[-1]
            shot["prompt_spec"]["dialogue"] = "Lady Mara Quinn：" + line.strip()
        rows = sdg.evaluate(contract, dict(sdg.POLICY))["rows"]
        self.assertEqual([f for row in rows for f in row.get("flags", []) if f.startswith("R8_")], [])


def _lab_module():
    spec = importlib.util.spec_from_file_location("snippet_lab_en", ROOT / "tools" / "lab" / "snippet_lab.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EnglishOfficialFormat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lab = _lab_module()
        cls.eng = cls.lab.load_engine(ROOT)
        cls.out = cls.lab.compile_lab(LAB, cls.eng)

    def test_authored_world_line_renders_official_with_english_tag(self):
        with mock.patch.dict(os.environ, {official.ENV_SWITCH: ""}):
            cfg = json.loads((LAB / "LAB.json").read_text(encoding="utf-8"))
            shot = next(s for s in self.out["contract"]["shots"] if s["shot_id"] == "LAB-S01-02")
            unit, plan = self.lab.lab_unit(self.out["contract"], shot, cfg, self.eng["english_schema"], voice=True)
            text, receipt = render_h3_prompt(unit, plan)
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt.get("h3_prompt_format"), official.FORMAT)
        self.assertIn("<d>[English] Three days are up. Where is your king?</d>", text)
        self.assertNotIn("WORLD VISUAL LOCK", text)
        self.assertFalse(CJK.search(text))

    def test_lock_title_regex(self):
        self.assertEqual(official._LOCK_TITLE.sub("", "WORLD VISUAL LOCK: keep the world.", count=1),
                         "keep the world.")
        self.assertEqual(official._LOCK_TITLE.sub("", "Keep the world.", count=1), "Keep the world.")


if __name__ == "__main__":
    unittest.main()
