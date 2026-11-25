"""Line owner 2026-11-25 ("AI face": airbrushed / porcelain / oily faces in the last episode).  Prompt text only, zero
credits, no new gate: a six-part positive skin description for live-action image prompts (full detail at MCU and
closer), no quality-booster words, no look text in stamped H3 prompts, and negatives that never forbid the shot's own
prop, say "character count" in multi-person shots and carry the texture negatives.  Offline, fakes only."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
for entry in (str(TOOLS), str(ROOT / "tools"), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import build_episode_asset_requirements as bar  # noqa: E402
import build_keyframe_manifest as bkm  # noqa: E402
import character_reference_sheet as crs  # noqa: E402
import render_style as rs  # noqa: E402
from tools import h3_director_prompt_v2 as h3v2  # noqa: E402
from tools import h3_provider_prompt_renderer as h3v1  # noqa: E402
from tools.tests.test_h3_director_prompt_v2 import fixture  # noqa: E402

BOOSTERS = ("8K", "4K", "超高清", "高清", "电影质感", "ultra-detailed", "ultra HD", "hyper-realistic", "hyperrealistic",
            "masterpiece", "best quality", "highly detailed", "cinematic quality")


class SkinPositive(unittest.TestCase):
    def test_full_detail_only_at_mcu_and_closer(self):
        for scale in ("MEDIUM_CLOSE_UP", "CLOSE_UP", "EXTREME_CLOSE_UP", "MCU", "close up", "特写", "近景",
                      "FRONT_NEUTRAL_HEADSHOT", "THREE_QUARTER_BUST", "FACE_CLOSE_UP", "PORTRAIT"):
            self.assertEqual(rs.live_skin_positive(scale), rs.LIVE_SKIN_POSITIVE_FULL_ZH, scale)
        for scale in ("MEDIUM", "MEDIUM_SHOT", "WIDE", "FULL_BODY", "ESTABLISHING", "", None):
            self.assertEqual(rs.live_skin_positive(scale), rs.LIVE_SKIN_POSITIVE_BASE_ZH, scale)
        self.assertEqual(rs.live_skin_positive("CLOSE_UP", "en"), rs.LIVE_SKIN_POSITIVE_FULL_EN)
        self.assertEqual(rs.live_skin_positive("WIDE", "en"), rs.LIVE_SKIN_POSITIVE_BASE_EN)

    def test_six_parts_and_never_flawless(self):
        full = rs.LIVE_SKIN_POSITIVE_FULL_ZH
        for part in ("自然半哑光", "额头有细小毛孔", "鼻翼毛孔", "唇纹", "唇中略润", "肤色轻微不均", "鼻翼淡淡泛红",
                     "鼻梁上段", "颧骨", "下唇中央", "侧光", "随表情", "各镜头肤质与肤色一致"):
            self.assertIn(part, full)
        for text in (full, rs.LIVE_SKIN_POSITIVE_BASE_ZH):
            self.assertIn("不追求完美无瑕", text)
        self.assertNotIn("毛孔", rs.LIVE_SKIN_POSITIVE_BASE_ZH)
        self.assertIn("never flawless", rs.LIVE_SKIN_POSITIVE_FULL_EN)

    def test_identity_cards_views_and_sheets(self):
        row = {"asset_id": "CHAR-A", "specification": {"canonical_name": "A", "apparent_age_range": "30-35",
                                                       "sex": "male", "appearance_ch1": "短发"}}
        live, _ = bar.character_prompt(row, "西装", "【视觉文化档案】X")
        anime, _ = bar.character_prompt(row, "西装", "【视觉文化档案】X\n" + rs.IMAGE_STYLE_BLOCK_ZH)
        self.assertIn(rs.LIVE_SKIN_FINISH_ZH, live)  # the anti-oil negatives stay
        self.assertIn(rs.LIVE_SKIN_POSITIVE_BASE_ZH, live)  # full-body base card: overall tone only
        self.assertNotIn(rs.LIVE_SKIN_POSITIVE_FULL_ZH, live)
        self.assertNotIn("皮肤真实感", anime)
        import bootstrap_identity_cards as bic
        for view in ("FRONT_NEUTRAL_HEADSHOT", "THREE_QUARTER_BUST"):
            text = bic.view_prompt_text(live, view, reference_clause="【参考】")
            self.assertIn(rs.LIVE_SKIN_POSITIVE_FULL_ZH, text, view)
            self.assertNotIn(rs.LIVE_SKIN_POSITIVE_BASE_ZH, text, view)
        sheet = crs.sheet_prompt({"canonical_name": "A"})
        self.assertIn(rs.LIVE_SKIN_POSITIVE_FULL_ZH, sheet)  # the sheet carries a face close-up view
        self.assertNotIn("皮肤真实感", crs.sheet_prompt({"canonical_name": "A"}, render_style="anime"))

    def test_keyframe_culture_block_scales_with_shot_size(self):
        vcc = {"profile_id": "P", "image_texture": "真人实拍，8K，超高清，电影质感"}
        mcu = bkm.visual_culture_block(vcc, shot_scale="MEDIUM_CLOSE_UP")
        wide = bkm.visual_culture_block(vcc, shot_scale="WIDE")
        self.assertIn(rs.LIVE_SKIN_POSITIVE_FULL_ZH, mcu)
        self.assertIn(rs.LIVE_SKIN_POSITIVE_BASE_ZH, wide)
        self.assertNotIn("毛孔", wide)
        self.assertNotIn("皮肤真实感", bkm.visual_culture_block(vcc, shot_scale="WIDE", people=False))
        self.assertNotIn("皮肤真实感", bkm.visual_culture_block({**vcc, "render_style": "anime"}, shot_scale="CLOSE_UP"))
        self.assertIn("质感：真人实拍\n", mcu)
        for word in ("8K", "超高清", "电影质感"):
            self.assertNotIn(word, mcu)


class QualityBoosters(unittest.TestCase):
    def test_strip(self):
        self.assertEqual(rs.strip_quality_boosters("真实摄影质感、细腻皮肤纹理、高清晰度。"), "真实摄影质感、细腻皮肤纹理。")
        self.assertEqual(rs.strip_quality_boosters("8K, masterpiece, natural light, ultra-detailed"), "natural light")
        self.assertEqual(rs.strip_quality_boosters("live-action photographic realism, real materials"),
                         "live-action photographic realism, real materials")
        self.assertEqual(rs.strip_quality_boosters(None), "")

    def test_no_booster_in_live_prompt_sources(self):
        import generate_period_look as gpl
        from tools import minimax_h3_prompt_compiler  # noqa: F401  (imports cleanly)
        texts = [gpl.PROMPT, rs.LIVE_SKIN_FINISH_ZH, rs.LIVE_SKIN_POSITIVE_FULL_ZH, rs.LIVE_SKIN_POSITIVE_BASE_ZH,
                 rs.LIVE_SKIN_POSITIVE_FULL_EN, rs.LIVE_SKIN_POSITIVE_BASE_EN, h3v1.SKIN_FINISH_NEGATIVE,
                 h3v1.H3_NEUTRAL_PERIOD_LOCK, h3v1.H3_AUTHORED_WORLD_LOCK,
                 (ROOT / "tools/minimax_h3_prompt_compiler.py").read_text(encoding="utf-8")]
        for text in texts:
            for word in BOOSTERS:
                self.assertNotIn(word, text)
        self.assertIn("{skin}", gpl.PROMPT)


class Negatives(unittest.TestCase):
    def test_prop_the_shot_needs_is_never_forbidden(self):
        out = rs.filter_negatives(["手机", "现代物件、电脑", "字幕", "木桌纹理"], prop_names=["手机", "木桌"],
                                  action_text="他拿起电脑")
        self.assertEqual(out, ["现代物件", "字幕"])
        # a sign / letter prop never unlocks on-screen text
        self.assertEqual(rs.filter_negatives(["文字、字幕"], prop_names=["文字"]), ["文字、字幕"])
        self.assertEqual(rs.filter_negatives(["No phones or laptops", "No captions or letters"],
                                             prop_names=["phone", "letter"], lang="en"),
                         ["No captions or letters"])

    def test_multi_person_uses_character_count(self):
        terms = ["多人", "第二个人物", "额外人物", "人群", "现代物件"]
        self.assertEqual(rs.filter_negatives(terms, multi_person=True), ["现代物件", "人物数量变化"])
        self.assertEqual(rs.filter_negatives(terms), terms)  # single-person shots keep them
        self.assertEqual(rs.filter_negatives(["extra person", "a crowd", "modern cars"], multi_person=True, lang="en"),
                         ["modern cars", "character count changes"])

    def test_keyframe_prompt_negatives(self):
        prompt = _keyframe_prompt(["CHAR-A", "CHAR-B"])
        never = prompt.split("【严格禁止】\n", 1)[1]
        self.assertNotIn("手机", never)  # the shot's own prop
        for term in ("多人", "第二个人物"):
            self.assertNotIn(term, never)
        for term in ("现代物件", "字幕", "人物数量变化", *rs.TEXTURE_NEGATIVES_ZH):
            self.assertIn(term, never)
        self.assertIn(rs.LIVE_SKIN_POSITIVE_FULL_ZH, prompt)  # MEDIUM_CLOSE_UP
        single = _keyframe_prompt(["CHAR-A"]).split("【严格禁止】\n", 1)[1]
        self.assertIn("多人", single)
        self.assertNotIn("人物数量变化", single)


def _keyframe_prompt(cast: list[str]) -> str:
    names = {"CHAR-A": "甲", "CHAR-B": "乙"}
    shot = {"shot_size": "MEDIUM_CLOSE_UP", "scene_id": "S01", "entry_state": "甲拿着手机站在桌前",
            "completion_state": "甲放下手机",
            "prompt_spec": {"negative_prompts": ["手机", "多人", "第二个人物", "字幕"], "cast": [], "camera": "固定",
                            "action": {"primary_action": "甲把手机递给对方"},
                            "scene_state": {"time": "夜", "weather": "晴", "lighting": "台灯", "palette": "暖"}}}
    inputs = SimpleNamespace(
        episode="E01", shots={"S01-01": shot}, contract={}, render_style=None, wardrobe_by_character={},
        place_maps={}, visual_culture={"profile_id": "P", "forbidden_influences": ["现代物件"], "image_texture": "真人实拍"},
        subspace_tasks={"S01-01": {"subspace_layout": {}, "blocking": {
            "characters": [{"character_id": cid, "character": names[cid]} for cid in cast],
            "props": [{"prop_id": "PROP-PHONE", "prop": "手机"}]}}})
    bindings = [{"role": "character", "entity_id": cid, "entity_name": names[cid]} for cid in cast]
    bindings.append({"role": "prop", "entity_id": "PROP-PHONE", "entity_name": "手机"})
    return bkm.build_prompt(inputs, "S01-01", bindings, cast, {}, [])


class H3Prompts(unittest.TestCase):
    def _unit(self, **kwargs):
        unit, plan = fixture(**kwargs)
        unit["ordered_prompt_specs"][0]["props"] = [{"prop": "gray long table", "prop_id": "PROP-TABLE"}]
        unit["h3_provider_english_contract"]["negative_constraints"] = [
            "No gray long tables", "No extra person in the background", "No modern objects"]
        unit["character_entities"] = [{**row, "appearance_anchor_en": "man, short black hair, pale porcelain skin"}
                                      for row in unit.get("character_entities") or []]
        return unit, plan

    def test_v1_stamped_has_no_look_text_and_clean_negatives(self):
        text, _ = h3v1.render_h3_prompt(*self._unit(style=False, director=True))
        self.assertNotIn("Same look in every frame", text)
        self.assertNotIn("porcelain", text)
        self.assertNotIn("short black hair", text)
        never = next(line for line in text.splitlines() if line.startswith("negative_constraints: "))
        self.assertNotIn("gray long table", never)
        self.assertNotIn("extra person", never)
        self.assertIn("No modern objects", never)
        self.assertIn(h3v1.CHARACTER_COUNT_NEGATIVE, never)
        self.assertIn(h3v1.TEXTURE_NEGATIVE_PEOPLE, never)
        self.assertIn(h3v1.SKIN_FINISH_NEGATIVE, never)  # anti-oil negative stays

    def test_v1_unstamped_keeps_its_bytes(self):
        text, _ = h3v1.render_h3_prompt(*self._unit(style=False, director=False))
        self.assertIn("Same look in every frame", text)
        self.assertIn("No gray long tables", text)
        self.assertNotIn(h3v1.TEXTURE_NEGATIVE_PEOPLE, text)

    def test_v2_stamped_has_no_look_text_and_clean_negatives(self):
        text, _ = h3v1.render_h3_prompt(*self._unit())
        who = text.split("Who is in frame", 1)[1].split("\n\n", 1)[0]
        self.assertNotIn("short black hair", who)
        self.assertNotIn("Woman, 28", who)
        never = text.split("\n\nNever: ", 1)[1]
        self.assertNotIn("gray long table", never)
        self.assertNotIn("extra person", never)
        self.assertIn(h3v2.CHARACTER_COUNT_NEVER, never)
        self.assertIn(h3v2.TEXTURE_NEVER_PEOPLE, never)


if __name__ == "__main__":
    unittest.main()
