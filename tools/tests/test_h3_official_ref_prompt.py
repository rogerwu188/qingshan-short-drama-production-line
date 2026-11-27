"""OFFICIAL_REF_V1: BILI_V1 H3 units rendered in MiniMax's official six-section reference format
(tools/h3_official_ref_prompt.py; lab A/B ~/nalu_lab/perf_lab/OFFICIAL_FORMAT_AB.md).  Zero credits."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tools import h3_official_ref_prompt as official  # noqa: E402
from tools.h3_provider_english_contract import is_director_v2_text, is_official_ref_text  # noqa: E402
from tools.h3_provider_prompt_renderer import render_h3_prompt  # noqa: E402
from tools.provider_scope_projection import validate_provider_scope_projection  # noqa: E402

LAB = ROOT / "tools" / "tests" / "fixtures" / "snippet_lab_e28"
CJK = re.compile(r"[㐀-鿿]")


def _lab_module():
    spec = importlib.util.spec_from_file_location("snippet_lab_official", ROOT / "tools" / "lab" / "snippet_lab.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OfficialFormatTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lab = _lab_module()
        cls.eng = cls.lab.load_engine(ROOT)
        cls.out = cls.lab.compile_lab(LAB, cls.eng)

    def setUp(self):
        self._env = mock.patch.dict(os.environ, {official.ENV_SWITCH: ""})
        self._env.start()
        self.addCleanup(self._env.stop)

    def unit(self, sid: str, fmt: str | None = official.FORMAT, voice: bool = True):
        cfg = json.loads((LAB / "LAB.json").read_text(encoding="utf-8"))
        for row in cfg["characters"].values():
            row["face"] = "face.png"
            row["voice"] = "voice.wav" if voice else ""
        if fmt:
            cfg["h3_prompt_format"] = fmt
        shot = next(s for s in self.out["contract"]["shots"] if s["shot_id"] == f"LAB-{sid}")
        return self.lab.lab_unit(self.out["contract"], shot, cfg, self.eng["english_schema"], voice=voice)

    def render(self, sid: str, fmt: str | None = official.FORMAT, voice: bool = True):
        unit, plan = self.unit(sid, fmt, voice)
        text, receipt = render_h3_prompt(unit, plan)
        self.assertEqual(receipt["status"], "PASS")
        return text, receipt, unit

    def test_six_sections_in_order_and_receipted(self):
        text, receipt, _ = self.render("S01-03")
        self.assertTrue(is_official_ref_text(text))
        self.assertFalse(is_director_v2_text(text))
        positions = [text.index(f"{name}:\n") for name in official.SECTIONS]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(receipt["h3_prompt_format"], official.FORMAT)
        self.assertEqual(receipt["provider_semantic_coverage_receipt"]["status"], "PASS")
        self.assertIn("summary:\n[keyframe completion + reference generation + audio reference] ", text)
        self.assertTrue(text.rstrip().endswith("non_diegetic_music:\nN/A"))
        description = text.split("detailed_description:\n", 1)[1].split("\n\noverall_soundscape:", 1)[0]
        self.assertIn("\n[Shot 1] The shot begins exactly on <Picture 1>", description)
        self.assertGreaterEqual(len(description.split()), 300)  # the guide: 350-500 words for generation

    def test_speaker_ids_and_dialogue_tag_hold_only_language_and_words(self):
        text, _, _ = self.render("S01-03")
        self.assertIn("<Audio 1> is the voice-timbre reference for <Subject 1> (S1), a woman's voice.", text)
        self.assertIn("<Subject 1> (S1), using the voice timbre referenced from <Audio 1>, says: "
                      "<d>[Chinese] 别再琢磨了。先告诉我怎么救他。</d>", text)
        retention = text.split("retention_analysis:\n", 1)[1].split("\n\n", 1)[0]
        self.assertNotIn("(S1)", retention)  # the guide: no speaker ids in retention_analysis
        outside = re.sub(r"<d>\[Chinese\].*?</d>", "", text, flags=re.S)
        self.assertFalse(CJK.search(outside))
        self.assertNotIn('"', outside)  # quotation marks only for text visible on screen

    def test_no_text_negatives_no_never_list_no_at_labels(self):
        text, _, _ = self.render("S01-05")
        for phrase in ("subtitle", "caption", "lettering", "written word", "Never:", "@Image", "@Audio"):
            self.assertNotIn(phrase, text)

    def test_camera_lock_and_identity_binding_live_in_the_official_sections(self):
        text, _, _ = self.render("S01-03")
        retention = text.split("retention_analysis:\n", 1)[1].split("\n\n", 1)[0]
        self.assertIn("<Picture 1> ([Shot 1] first frame): fully_preserved", retention)
        self.assertIn("the camera keeps this framing to the last frame", retention)
        self.assertIn("<Subject 1> (appears in [Shot 1]): fully_preserved - Lingyao's face", retention)
        self.assertIn("<Subject 2> (appears in [Shot 1]): partially_preserved - only Dongyang's hair, build and "
                      "wardrobe from behind", retention)
        self.assertIn("The camera holds a static shot on a tripod", text)
        self.assertIn("Dongyang is seen from behind in the foreground, over-the-shoulder", text)
        self.assertIn("Exactly two people are in frame, each exactly once", text)

    def test_writer_performance_plays_around_the_line_in_playback_order(self):
        text, _, _ = self.render("S01-03")
        start = text.index("Lingyao starts with")
        line = text.index("<d>[Chinese]")
        crack = text.index("her guard cracks")
        self.assertLess(start, line)
        self.assertLess(line, crack)
        self.assertIn("eyes redden", text)

    def test_scope_gate_accepts_the_official_text(self):
        text, _, unit = self.render("S01-01")
        gate = validate_provider_scope_projection(unit, prompt_text=text, model="MiniMax-H3")
        self.assertEqual(gate["failures"], [])
        broken = re.sub(r"Exactly \w+ people are in frame", "People are here", text)
        gate = validate_provider_scope_projection(unit, prompt_text=broken, model="MiniMax-H3")
        self.assertIn("H3_PROVIDER_SCOPE_EXCLUSIVE_POPULATION_CLAUSE_MISSING", gate["failures"])

    def test_switch_keeps_the_v2_text_byte_identical(self):
        v2_explicit, receipt, _ = self.render("S01-05", official.LEGACY_FORMAT)
        v2_unstamped, _, _ = self.render("S01-05", None)
        self.assertEqual(v2_explicit, v2_unstamped)
        self.assertTrue(is_director_v2_text(v2_explicit))
        self.assertEqual(receipt["h3_prompt_format"], official.LEGACY_FORMAT)
        with mock.patch.dict(os.environ, {official.ENV_SWITCH: official.LEGACY_FORMAT}):
            forced, _, _ = self.render("S01-05", official.FORMAT)
        self.assertEqual(forced, v2_explicit)

    def test_stamp_defaults_to_official_and_honours_the_contract(self):
        self.assertEqual(official.stamp_format({}), official.FORMAT)
        self.assertEqual(official.stamp_format({"h3_prompt_format": "director_v2"}), official.LEGACY_FORMAT)
        self.assertEqual(official.requested_format({}), official.LEGACY_FORMAT)

    def test_batch_qa_reads_the_official_sections(self):
        import prompt_batch_qa as qa
        text, _, _ = self.render("S01-03")
        self.assertTrue(qa.is_h3_official(text))
        self.assertIn("[Shot 1]", qa.section(text, "时间轴"))
        self.assertIn("Faint breathing", qa.section(text, "声音"))
        self.assertTrue(all(h in text for h in qa.H3_OFFICIAL_REQUIRED))


if __name__ == "__main__":
    unittest.main()
