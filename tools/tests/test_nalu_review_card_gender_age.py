"""Final review identity cards carry gender / apparent age (deep review 1101 E26, 2026-11-27).

Pass B graded a female character with a moustache as "P3 rough make-up" and missed a 45-55 magistrate played by a
~25-year-old: the cards it received had a face description only, no gender and no age.  The cards now carry the
contract's ``gender`` / ``apparent_age_range`` and pass B is told such a mismatch is QA-IDENTITY-MISMATCH, at least P1.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
for entry in (str(TOOLS), str(ROOT / "tools"), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import gemini_review_passes as mp  # noqa: E402

EP = "E26"
CONTRACT = {
    "episode": EP,
    "character_entities": [
        {"character_id": "CHAR-MUYUNER", "canonical_name": "沐云儿", "gender": "女", "apparent_age_range": "22-28",
         "appearance_ch1": "鹅蛋脸、细长上挑眼、锋利眉尾"},
        {"character_id": "CHAR-YE", "canonical_name": "叶大人", "gender": "男", "apparent_age_range": "45-55"}],
    "shots": [
        {"shot_id": "E26-S04-01", "prompt_spec": {"cast": [{"character": "沐云儿", "character_id": "CHAR-MUYUNER"}]}},
        {"shot_id": "E26-S01-04", "prompt_spec": {"cast": [{"character": "叶大人", "character_id": "CHAR-YE"}]}}]}


class ReviewCardGenderAgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        work = Path(self.tmp.name) / EP
        (work / "preproduction").mkdir(parents=True)
        (work / "assembly").mkdir(parents=True)
        (work / "preproduction" / f"{EP}_GENERATION_CONTRACT_v1.json").write_text(
            json.dumps(CONTRACT, ensure_ascii=False), encoding="utf-8")
        self.context = mp.episode_context(EP, work_root=work)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cards_carry_contract_gender_and_age(self):
        cards = {c["character_id"]: c for c in self.context["cards"]}
        self.assertEqual((cards["CHAR-MUYUNER"]["gender"], cards["CHAR-MUYUNER"]["age"]), ("女", "22-28"))
        self.assertEqual(cards["CHAR-MUYUNER"]["appearance"], "鹅蛋脸、细长上挑眼、锋利眉尾")   # entity fallback
        self.assertEqual((cards["CHAR-YE"]["gender"], cards["CHAR-YE"]["age"]), ("男", "45-55"))

    def test_identity_and_sound_prompts_show_gender_and_age(self):
        b = mp.build_pass_prompt("B", duration=60.0, context=self.context)
        for text in ('"gender":"女"', '"age":"22-28"', '"age":"45-55"', "QA-IDENTITY-MISMATCH", "胡子", "至少 P1"):
            self.assertIn(text, b.replace(", ", ",").replace(": ", ":"))
        for name in ("沐云儿", "叶大人"):
            self.assertNotIn(name, b)
        c = mp.build_pass_prompt("C", duration=60.0, context=self.context)
        self.assertIn('"gender":"男"', c.replace(", ", ",").replace(": ", ":"))

    def test_card_without_gender_or_age_keeps_old_shape(self):
        view = mp._card_view({"label": "角色A", "appearance": "圆脸", "gender": "", "age": "", "wardrobe": "红袍"},
                             wardrobe=False)
        self.assertEqual(view, {"label": "角色A", "appearance": "圆脸"})


if __name__ == "__main__":
    unittest.main()
