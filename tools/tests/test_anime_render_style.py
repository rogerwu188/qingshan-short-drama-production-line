"""render_style (owner + boss 2026-11-19): a per-series ``live_action`` | ``anime`` switch.

Covers: the style resolution; the anime prompt blocks at each site with the live-action text unchanged; the
InsightFace identity gates NOT_APPLICABLE for anime with no auto-redo; the VLM identity evidence being required;
the rubric switch; the exemplar split; the 9:16 aspect normalisation; the anime poster.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import render_style as rs  # noqa: E402  (runtime tools dir)
from tools import render_style as rs_shim  # noqa: E402
from tools import visual_culture_contract as vcc_mod  # noqa: E402

ANIME_VCC = {"render_style": "anime"}


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- resolution
class StyleResolution(unittest.TestCase):
    def test_normalise_aliases(self):
        self.assertEqual(rs.normalise("anime"), "anime")
        self.assertEqual(rs.normalise("2D-Anime"), "anime")
        self.assertEqual(rs.normalise("Live Action"), "live_action")
        self.assertIsNone(rs.normalise("watercolour"))
        self.assertIsNone(rs.normalise(None))

    def test_default_is_live_action(self):
        self.assertEqual(rs.resolve(), "live_action")
        self.assertEqual(rs.resolve({"visual_culture_contract": {"profile_id": "X"}}), "live_action")

    def test_contract_beats_brief_beats_config(self):
        contract = {"visual_culture_contract": {"render_style": "anime"}}
        self.assertEqual(rs.resolve(contract, {"render_style": "live_action"}), "anime")
        self.assertEqual(rs.resolve(None, {"render_style": "anime"}, {"project": {"render_style": "live_action"}}),
                         "anime")
        self.assertEqual(rs.resolve(None, {}, {"project": {"render_style": "anime"}}), "anime")
        self.assertEqual(rs.resolve({"visual_culture_contract": {"render_style": "live_action"}}, None,
                                    {"project": {"render_style": "anime"}}), "live_action")

    def test_unit_and_vcc_shapes(self):
        self.assertTrue(rs.is_anime({"visual_culture_contract": {"render_style": "anime"}}))
        self.assertTrue(rs.is_anime({"render_style": "anime"}))  # a vcc itself / a stamped unit
        self.assertTrue(rs.is_anime("anime"))
        self.assertFalse(rs.is_anime({"visual_culture_contract": {}}))
        self.assertFalse(rs.is_anime(None))

    def test_runtime_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(rs.resolve_runtime("E02", runtime_root=root), "live_action")
            _write(root / "qingshan.json", {"project": {"render_style": "anime"}})
            self.assertEqual(rs.resolve_runtime("E02", runtime_root=root), "anime")
            _write(root / "briefs" / "E02_PRODUCTION_BRIEF.json", {"render_style": "live_action"})
            self.assertEqual(rs.resolve_runtime("E02", runtime_root=root), "live_action")
            self.assertEqual(rs.resolve_runtime("E02", runtime_root=root,
                                                contract={"visual_culture_contract": ANIME_VCC}), "anime")

    def test_stamp_only_for_anime(self):
        vcc = {"profile_id": "X"}
        self.assertIs(rs.stamp(vcc, "live_action"), vcc)
        self.assertEqual(rs.stamp(vcc, "anime"), {"profile_id": "X", "render_style": "anime"})

    def test_engine_tools_shim_reexports(self):
        self.assertEqual(rs_shim.ANIME, "anime")
        self.assertEqual(rs_shim.H3_GENRE, rs.H3_GENRE)


# --------------------------------------------------------------------------- H3 prompts
class H3Prompts(unittest.TestCase):
    def _fixture(self, **kwargs):
        from tools.tests.test_h3_director_prompt_v2 import fixture
        return fixture(**kwargs)

    def test_live_action_v1_is_byte_identical(self):
        from tools.h3_provider_prompt_renderer import render_h3_prompt
        from tools.tests.test_h3_director_prompt_v2 import V1_SHA
        for director in (True, False):
            text, _ = render_h3_prompt(*self._fixture(style=False, director=director))
            self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(), V1_SHA[director])
            self.assertIn("vertical 9:16 live-action short drama", text)
            self.assertNotIn("art_style:", text)

    def test_anime_v1_genre_art_style_lock_and_negatives(self):
        from tools.h3_provider_prompt_renderer import render_h3_prompt
        unit, plan = self._fixture(style=False)
        unit["visual_culture_contract"] = {**(unit.get("visual_culture_contract") or {}), **ANIME_VCC}
        text, receipt = render_h3_prompt(unit, plan)
        self.assertEqual(receipt["status"], "PASS")
        self.assertIn("vertical 9:16 2D anime short drama", text)
        self.assertNotIn("live-action short drama", text)
        self.assertIn("\n" + rs.H3_ART_STYLE_LINE + "\n", text)
        self.assertIn("NOT photorealistic, not live-action, not 3D CGI", text)
        self.assertNotIn("real materials", text)
        self.assertNotIn("game-poster", text)
        self.assertIn("photorealistic, live-action, real people, 3D render", text)

    def test_anime_v2_director_prompt(self):
        from tools.h3_provider_prompt_renderer import render_h3_prompt
        unit, plan = self._fixture()
        unit["visual_culture_contract"] = {**(unit.get("visual_culture_contract") or {}), **ANIME_VCC}
        text, receipt = render_h3_prompt(unit, plan)
        self.assertEqual(receipt["status"], "PASS")
        self.assertIn("Art style: 2D Japanese TV anime, cel-shaded", text)
        self.assertNotIn("real materials", text)
        self.assertIn("style drift or face morphing", text)

    def test_period_and_world_locks(self):
        from tools import h3_provider_prompt_renderer as h3
        unit = {"unit_id": "E02-VU-001", "dialogue_language": "ja", "visual_culture_contract": {}}
        self.assertEqual(h3.h3_visual_culture_block(unit), h3.H3_AUTHORED_WORLD_LOCK)
        unit["visual_culture_contract"] = dict(ANIME_VCC)
        anime_lock = h3.h3_visual_culture_block(unit)
        self.assertNotIn("real materials", anime_lock)
        self.assertNotIn("game-poster", anime_lock)
        self.assertIn("clean anime line art and stable cel shading", anime_lock)
        neutral = {"unit_id": "E02-VU-001", "dialogue_language": "zh", "visual_culture_contract": dict(ANIME_VCC)}
        self.assertEqual(h3.h3_visual_culture_block(neutral), rs.anime_lock(h3.H3_NEUTRAL_PERIOD_LOCK))
        self.assertNotIn("real materials", h3.h3_visual_culture_block(neutral))

    def test_insert_genre(self):
        self.assertTrue(rs.h3_insert_genre("a cup").startswith("a single anime insert shot of a cup"))

    def test_audio_rescue_compiler(self):
        from tools.minimax_h3_prompt_compiler import compile_h3_english_machine_audio_rescue_prompt as rescue
        unit = {"reference_images": [{"path": "a.png"}], "ordered_prompt_specs": [{"dialogue": "甲：你好"}],
                "duration_seconds": 5}
        live = rescue(unit)
        self.assertTrue(live.startswith("H3 LIVE-ACTION SHORT-DRAMA AUDIO RESCUE."))
        self.assertIn("STYLE=LIVE_ACTION_ANCIENT_CHINA.", live)
        anime = rescue({**unit, "visual_culture_contract": dict(ANIME_VCC)})
        self.assertTrue(anime.startswith(rs.H3_RESCUE_HEADER))
        self.assertIn(rs.H3_RESCUE_STYLE, anime)
        self.assertNotIn("LIVE_ACTION", anime)


# --------------------------------------------------------------------------- visual culture / image prompts
class ImagePromptBlocks(unittest.TestCase):
    def test_visual_culture_blocks_live_unchanged(self):
        contract = dict(vcc_mod.DEFAULT_CONTRACT)
        live_en, live_zh = vcc_mod.prompt_block_en(contract), vcc_mod.prompt_block_zh(contract)
        self.assertIn("real materials", live_en)
        self.assertIn("真实材质", live_zh)
        self.assertEqual(vcc_mod.image_texture(contract), contract["image_texture"])
        anime = {**contract, **ANIME_VCC}
        self.assertNotIn("real materials", vcc_mod.prompt_block_en(anime))
        self.assertNotIn("真实材质", vcc_mod.prompt_block_zh(anime))
        self.assertIn("black-gold", vcc_mod.prompt_block_en(anime))  # the E54+ validator token survives
        self.assertEqual(vcc_mod.image_texture(anime), rs.IMAGE_TEXTURE_ZH)
        self.assertEqual(vcc_mod.prompt_block_en(contract, render_style="anime"), vcc_mod.prompt_block_en(anime))

    def test_authored_world_block(self):
        contract = {"profile_id": "JA01", "story_world": "a European-style fantasy kingdom academy"}
        live = vcc_mod.authored_world_prompt_block(contract, language="en")
        self.assertIn("no game-poster light", live)
        anime = vcc_mod.authored_world_prompt_block(contract, language="en", render_style="anime")
        self.assertTrue(anime.endswith(rs.IMAGE_STYLE_BLOCK_EN))
        self.assertNotIn("game-poster", anime)
        self.assertIn(rs.STYLE_PHRASE_EN, rs.IMAGE_STYLE_BLOCK_ZH)

    def test_keyframe_visual_culture_block(self):
        import build_keyframe_manifest as bkm
        contract = dict(vcc_mod.DEFAULT_CONTRACT)
        live = bkm.visual_culture_block(contract)
        self.assertIn(f"质感：{contract['image_texture']}", live)
        anime = bkm.visual_culture_block({**contract, **ANIME_VCC})
        self.assertIn(f"质感：{rs.IMAGE_TEXTURE_ZH}", anime)
        self.assertNotIn("真人实拍", anime)

    def test_keyframe_header_and_hard_line_constants(self):
        source = (TOOLS / "build_keyframe_manifest.py").read_text(encoding="utf-8")
        # the live-action strings are still in the source verbatim (unchanged branch)
        self.assertIn("竖屏 9:16 实拍质感单帧电影画面，", source)
        self.assertIn("真实透视、人物脚底落地、可信人体解剖与真实材质；单帧静止画面，无运动模糊特效。", source)
        self.assertIn("输出必须是实拍质感画面，不得画成地图、示意图、平面图或带任何标注线条。", source)
        for text in (rs.KEYFRAME_HEADER_STYLE_ZH, rs.KEYFRAME_HARD_STYLE_ZH, rs.TOPOLOGY_OUTPUT_ZH):
            self.assertNotIn("实拍", text)
            self.assertNotIn("真实材质", text)

    def test_asset_requirements_style_block_and_location(self):
        import build_episode_asset_requirements as bear
        vcc = dict(vcc_mod.DEFAULT_CONTRACT)
        live = bear.style_block(vcc)
        self.assertIn(f"质感：{vcc['image_texture']}", live)
        self.assertNotIn("画风锁", live)
        anime = bear.style_block(vcc, "anime")
        self.assertIn(f"质感：{rs.IMAGE_TEXTURE_ZH}", anime)
        self.assertIn(rs.IMAGE_STYLE_BLOCK_ZH, anime)
        row = {"asset_id": "LOC-HALL", "label": "Hall",
               "specification": {"lighting_variants_required": ["day"], "spatial_topology": "hall",
                                 "scene_states": [{"time_id": "DAY", "weather": "clear"}],
                                 "key_fixed_elements": ["chandelier"]}}
        place, room = {"global_space_map_id": "G"}, {"room_id": "R"}
        live_body, _ = bear.location_prompt(row, place, room, "STYLE")
        self.assertIn("输出必须是实拍质感的场景照片", live_body)
        anime_body, _ = bear.location_prompt(row, place, room, "STYLE", "anime")
        self.assertIn(rs.LOCATION_OUTPUT_ZH, anime_body)
        self.assertNotIn("实拍", anime_body)

    def test_human_realism_not_applicable_for_anime(self):
        from tools import human_realism_prompt_contract as hr
        from tools.shot_prompt_professionalism_gate import validate_task
        live = hr.build_keyframe_realism_block(character_ids=[], character_locks={}, shot_scale="", lens_intent="",
                                               action="")
        self.assertIn("真人质感合同", live)
        self.assertEqual(hr.build_keyframe_realism_block(character_ids=["C"], character_locks={}, shot_scale="",
                                                         lens_intent="", action="x", render_style="anime"), "")
        self.assertEqual(hr.build_expression_realism_block(expression_arc="a", action="b", framing="c",
                                                           render_style="anime"), "")
        self.assertEqual(hr.validate_human_realism_prompt("plain", render_style="anime"), [])
        self.assertTrue(hr.validate_human_realism_prompt("plain"))
        task = {"task_key": "K", "tool_type": "image_generation", "prompt": "x",
                "prompt_realism_contract_version": hr.CONTRACT_VERSION}
        live_codes = {f["check"] for f in validate_task(task)["failures"]}
        anime_codes = {f["check"] for f in validate_task({**task, "render_style": "anime"})["failures"]}
        self.assertIn("skin_microtexture", live_codes)
        self.assertNotIn("skin_microtexture", anime_codes)

    def test_parallel_prompt_batch_anime_line(self):
        from tools import compile_episode_parallel_prompt_batch as batch
        self.assertEqual(batch.ANIME_FRAME_LINE, rs.PROMPT_BATCH_FRAME_EN)

    def test_codex_note(self):
        import nalu_craft_standard as craft
        live = craft.codex_section(ROOT)
        self.assertNotIn("render_style=anime", live)
        anime = craft.codex_section(ROOT, render_style="anime")
        self.assertIn(rs.CODEX_NOTE_ZH, anime)
        self.assertLessEqual(len(anime), craft.MAX_CODEX_SECTION_CHARS)
        if live:  # standard on: the anime section still carries it
            self.assertIn(craft.SECTION_TITLE, anime)


# --------------------------------------------------------------------------- identity cards
class IdentityCards(unittest.TestCase):
    def test_culture_lock_live_unchanged_and_anime(self):
        import bootstrap_identity_cards as bic
        gc = {"dialogue_language": "ja", "visual_culture_contract": {"profile_id": "JA01", "story_world": "academy"}}
        live_contract, live_block = bic.culture_lock_for("E02", gc, render_style="live_action")
        self.assertEqual((live_contract, live_block), bic._culture_lock_for("E02", gc))
        self.assertEqual(live_contract["image_texture"], "live-action photographic realism, real materials")
        anime_contract, anime_block = bic.culture_lock_for("E02", gc, render_style="anime")
        self.assertEqual(anime_contract["render_style"], "anime")
        self.assertEqual(anime_contract["image_texture"], rs.IMAGE_TEXTURE_EN)
        self.assertNotIn("game CG or concept-poster look", anime_contract["forbidden_influences"])
        self.assertIn("photorealistic, live-action or 3D CGI look", anime_contract["forbidden_influences"])
        self.assertGreaterEqual(len(anime_contract["forbidden_influences"]), 6)
        self.assertTrue(anime_block.endswith(rs.IMAGE_STYLE_BLOCK_EN))
        zh_contract, zh_block = bic.culture_lock_for("E02", {"dialogue_language": "zh"}, render_style="anime")
        self.assertTrue(zh_block.startswith("【东方时代视觉锁】"))
        self.assertTrue(zh_block.endswith(rs.IMAGE_STYLE_BLOCK_ZH))
        self.assertNotIn("真实材质", zh_block)

    def test_anime_cards_ignore_real_photos_and_keep_design(self):
        import bootstrap_identity_cards as bic
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            prompts = tmp / "prompts"
            prompts.mkdir()
            (prompts / "E02-CHAR-CLAIRE.txt").write_text("【人物身份基准卡】Claire\n构图：全身\n", encoding="utf-8")
            photo = tmp / "CHAR-CLAIRE__SOURCE_V2.png"
            photo.write_bytes(b"not really a png")
            plates = tmp / "plates"
            plates.mkdir()
            (plates / "E02_CHAR-CLAIRE_tsk_abcdefgh12.png").write_bytes(b"base plate")
            subject = {"subject_id": "CHAR-CLAIRE", "kind": "CHARACTER", "canonical_name": "Claire",
                       "card_deliverables": ["FULL_BODY_STANDING", "FRONT_NEUTRAL_HEADSHOT"]}
            sources = {"CHAR-CLAIRE": [{"file": str(photo)}]}
            gc = {"dialogue_language": "ja", "visual_culture_contract": {"profile_id": "JA01"}}
            plan, _, _ = bic.build_plan([subject], sources, episode="E02", prompt_dir=prompts,
                                        gate_report_path=tmp / "gate.json", authorization_ref="R",
                                        plates_dir=plates, generation_contract=gc, render_style="anime")
            rows = {row["id"]: row for row in plan["new_asset_groups"]}
            base = rows["CHAR-CLAIRE"]
            self.assertEqual(base["reference_images"], [])  # drawn from the description, not the photo
            self.assertEqual(base["identity_rule"], "NEW_UNIQUE_FACE_NO_REUSE")
            self.assertEqual(plan["render_style"], "anime")
            view = rows["CHAR-CLAIRE__FRONT_NEUTRAL_HEADSHOT"]
            view_text = Path(view["prompt_file"]).read_text(encoding="utf-8")
            self.assertIn(rs.SAME_IDENTITY_CLAUSE_ZH, view_text)
            self.assertNotIn("人脸识别应判定为同一人", view_text)
            self.assertNotIn("真人", view_text)
            self.assertIn(rs.IMAGE_STYLE_BLOCK_EN, Path(base["prompt_file"]).read_text(encoding="utf-8"))
            self.assertEqual(base["visual_culture_contract"]["render_style"], "anime")

    def test_reference_sheet_anime(self):
        import character_reference_sheet as crs
        entity = {"character_id": "CHAR-CLAIRE", "english_name": "Claire", "appearance_en": "Blonde drill curls."}
        live = crs.sheet_prompt(entity)
        self.assertIn("同一人物已锁定的身份照", live)
        anime = crs.sheet_prompt(entity, render_style="anime")
        self.assertIn(rs.SHEET_REFERENCE_CLAUSE_ZH, anime)
        self.assertIn(rs.IMAGE_STYLE_BLOCK_ZH, anime)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plates = tmp / "plates"
            plates.mkdir()
            sheet = plates / "E02_CHAR-CLAIRE__MULTIVIEW_REFERENCE_SHEET_tsk_abcdefgh12.png"
            sheet.write_bytes(b"sheet")
            head = plates / "E02_CHAR-CLAIRE__FRONT_NEUTRAL_HEADSHOT_tsk_abcdefgh34.png"
            head.write_bytes(b"head")
            library = _write(tmp / "lib.json", {"assets": {"characters": {"CHAR-CLAIRE": {}}}})
            calls = []
            report = crs.register(library, plates, "E02", measure=lambda *a: calls.append(a) or 0.1,
                                  render_style="anime")
            self.assertEqual(calls, [])
            self.assertEqual(report[0]["status"], "NOT_MEASURED")
            self.assertEqual(report[0]["identity_measurement"]["decision"], "NOT_APPLICABLE")

    def test_runtime_root_bootstrap_no_photo_for_anime(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "qingshan.json", {"project": {"name": "JA-01"}})
            out = subprocess.run([sys.executable, str(TOOLS / "bootstrap_runtime_root.py"), "--runtime-root",
                                  str(root), "--render-style", "anime"], capture_output=True, text=True, check=True)
            payload = json.loads(out.stdout)
            self.assertEqual(payload["render_style"], "anime")
            self.assertFalse(any("SOURCE_V2_TANG" in row for row in payload["owner_inputs_todo"]))
            self.assertEqual(json.loads((root / "qingshan.json").read_text())["project"]["render_style"], "anime")

    def test_period_look_refuses_for_anime(self):
        import generate_period_look as gpl
        from unittest import mock
        with mock.patch.object(rs, "resolve_runtime", return_value="anime"):
            self.assertEqual(gpl.anime_refusal()["status"], "NOT_APPLICABLE")
        with mock.patch.object(rs, "resolve_runtime", return_value="live_action"):
            self.assertIsNone(gpl.anime_refusal())


# --------------------------------------------------------------------------- identity gates
def _answers(**extra):
    return {"cast_exactly_as_declared": "PASS", "each_visible_character_identity_recognisable": "PASS", **extra}


class AnimeIdentityGates(unittest.TestCase):
    def test_questionnaire_switch(self):
        import vlm_review_protocol as vrp
        live = vrp.QUESTIONNAIRES["identity"]
        self.assertIs(rs.style_questionnaire("identity", live, "live_action"), live)
        anime = rs.style_questionnaire("identity", live, "anime")
        self.assertNotIn("plate_is_photographic_not_illustrated", anime)
        self.assertIn(rs.ART_STYLE_QUESTION, anime)
        self.assertIn("consistent with the declared art style", anime[rs.ART_STYLE_QUESTION]["question"])
        for kind in ("keyframe", "video_q2"):
            questions = rs.style_questionnaire(kind, vrp.QUESTIONNAIRES[kind], "anime")
            self.assertIn(rs.VLM_IDENTITY_QUESTION, questions)
            self.assertIn("cast_exactly_as_declared", questions)  # semantic checks kept
            for word in ("hair colour", "eye colour", "outfit", "accessories"):
                self.assertIn(word, questions[rs.VLM_IDENTITY_QUESTION]["question"])
        self.assertIs(rs.style_questionnaire("post_gen_plot", vrp.QUESTIONNAIRES["post_gen_plot"], "anime"),
                      vrp.QUESTIONNAIRES["post_gen_plot"])

    def test_vlm_evidence_required(self):
        self.assertEqual(rs.vlm_identity_failures({}), ["ANIME_VLM_IDENTITY_EVIDENCE_MISSING"])
        self.assertEqual(rs.vlm_identity_failures({rs.VLM_IDENTITY_QUESTION: "FAIL"}),
                         ["ANIME_VLM_IDENTITY_NOT_CONFIRMED:FAIL"])
        self.assertEqual(rs.vlm_identity_failures({rs.VLM_IDENTITY_QUESTION: "PASS"}), [])
        self.assertTrue(rs.vlm_identity_failures({rs.VLM_IDENTITY_QUESTION: "NOT_APPLICABLE"}))
        self.assertEqual(rs.vlm_identity_failures({rs.VLM_IDENTITY_QUESTION: "NOT_APPLICABLE"},
                                                   characters_declared=False), [])

    def test_s3_identity_lock(self):
        import identity_qa_lock as iql
        passed = iql.anime_identity_measurement({"answers": {rs.VLM_IDENTITY_QUESTION: "PASS"}})
        self.assertEqual(passed["decision"], "NOT_APPLICABLE")  # accepted by the lock, zero faces never fail
        self.assertEqual(passed["failures"], [])
        self.assertEqual(passed["vlm_identity"]["method"], rs.VLM_IDENTITY_METHOD)
        missing = iql.anime_identity_measurement({"answers": {}})
        self.assertEqual(missing["decision"], "FAIL")
        self.assertIn("ANIME_VLM_IDENTITY_EVIDENCE_MISSING", missing["failures"])

    def test_q1_identity_is_vlm_for_anime(self):
        import keyframe_q1_builder as q1
        measurement = rs.not_applicable_measurement("INSIGHTFACE_COSINE_V1", per_keyframe={})
        item = {"item_id": "E02-S01-01", "answers": _answers(**{rs.VLM_IDENTITY_QUESTION: "PASS"})}
        verification, failures, method = q1.build_identity_verification(
            item, {}, "sha", ["CHAR-CLAIRE"], measurement, declared_characters=["CHAR-CLAIRE"],
            render_style="anime")
        self.assertEqual(method, rs.VLM_IDENTITY_METHOD)
        self.assertEqual(failures, [])
        self.assertEqual(verification["decision"], "PASS")
        self.assertFalse(any("FACE_COUNT_ZERO" in f or "FACE_NOT_FOUND" in f or "NO_EMBEDDING" in f
                             for f in verification["failures"]))
        no_evidence = {"item_id": "E02-S01-01", "answers": _answers()}
        _, failures, _ = q1.build_identity_verification(no_evidence, {}, "sha", ["CHAR-CLAIRE"], measurement,
                                                        declared_characters=["CHAR-CLAIRE"], render_style="anime")
        self.assertIn("ANIME_VLM_IDENTITY_EVIDENCE_MISSING", failures)
        # live-action with no face measured keeps failing exactly as before
        _, live_failures, live_method = q1.build_identity_verification(
            item, {}, "sha", ["CHAR-CLAIRE"], {"per_keyframe": {}}, declared_characters=["CHAR-CLAIRE"])
        self.assertEqual(live_method, "INSIGHTFACE_COSINE_V1")
        self.assertIn("NO_EMBEDDING_SAMPLE_FOR_DECLARED_CHARACTER:CHAR-CLAIRE", live_failures)

    def test_admission_gate_accepts_only_complete_anime_evidence(self):
        from tools import shot_media_admission_gate as gate
        import keyframe_q1_builder as q1
        item = {"item_id": "E02-S01-01", "answers": _answers(**{rs.VLM_IDENTITY_QUESTION: "PASS"})}
        verification, _, _ = q1.build_identity_verification(
            item, {}, "sha", [], {}, declared_characters=["CHAR-CLAIRE"], render_style="anime")
        ok, reason = gate._objective_p0_pass("CHARACTER-IDENTITY-ADMISSION",
                                             {"objective_verification": verification}, {})
        self.assertTrue(ok, reason)
        stripped = {**verification, "checks": [r for r in verification["checks"]
                                               if r["question_id"] != rs.VLM_IDENTITY_QUESTION]}
        ok, reason = gate._objective_p0_pass("CHARACTER-IDENTITY-ADMISSION", {"objective_verification": stripped}, {})
        self.assertFalse(ok)
        self.assertEqual(reason, "p0_anime_vlm_identity_evidence_missing")
        live = {**verification, "render_style": None}
        self.assertFalse(gate._objective_p0_pass("CHARACTER-IDENTITY-ADMISSION",
                                                 {"objective_verification": live}, {})[0])

    def test_q2_identity_face_count_speaker_and_no_auto_redo(self):
        import video_q2_builder as q2
        import q2_auto_redo as redo
        item = {"item_id": "E02-VU-001", "answers": _answers(**{rs.VLM_IDENTITY_QUESTION: "PASS"})}
        verification, failures, method = q2.build_identity_verification(
            item, {}, "sha", ["CHAR-CLAIRE"], rs.not_applicable_measurement("INSIGHTFACE_COSINE_V1"),
            render_style="anime")
        self.assertEqual((method, failures, verification["decision"]), (rs.VLM_IDENTITY_METHOD, [], "PASS"))
        _, failures, _ = q2.build_identity_verification({"item_id": "E02-VU-001", "answers": _answers()}, {}, "sha",
                                                        ["CHAR-CLAIRE"], {}, render_style="anime")
        self.assertIn("ANIME_VLM_IDENTITY_EVIDENCE_MISSING", failures)
        # NOT_APPLICABLE measurements never override the reviewer
        checks, failed = [], []
        self.assertFalse(q2.apply_face_count(rs.not_applicable_measurement(q2.FACE_COUNT_METHOD), checks, failed))
        self.assertFalse(q2.apply_speaker_framing(rs.not_applicable_measurement(q2.SPEAKER_FRAMING_METHOD),
                                                  checks, failed))
        self.assertFalse(q2.apply_push_in(rs.not_applicable_measurement(q2.PUSH_IN_METHOD), checks, failed))
        self.assertEqual(failed, [])
        # even a FAIL-shaped anime prepare row never triggers a paid redo
        fail = {"status": "FAIL", "failure": "NO_FACE_DETECTED"}
        live_row = {"face_count": fail, "speaker_framing": fail}
        self.assertEqual(redo.objective_failures(live_row), ["face_count", "speaker_framing"])
        anime_row = {**live_row, "render_style": "anime"}
        self.assertEqual(redo.objective_failures(anime_row), [])
        plan = redo.plan({"E02-VU-001": anime_row}, {}, headroom=1000, unit_cost=lambda uid: 10)
        self.assertEqual(plan["selected"], [])

    def test_pipeline_redo_tail_and_push_in_skip_for_anime(self):
        import nalu_pipeline as npl
        from types import SimpleNamespace
        from unittest import mock
        empty = Path(tempfile.mkdtemp())  # no clip carries a letterbox FAIL (the only anime-eligible redo, 2026-11-19)
        ctx = SimpleNamespace(render_style="anime", episode="E02",
                              p=SimpleNamespace(preprod=empty, q2_dir=empty, video_media=empty))
        self.assertEqual(npl.ctx_render_style(ctx), "anime")
        self.assertEqual(npl.ctx_render_style(SimpleNamespace()), "live_action")
        with mock.patch.object(npl, "_camera_grammar_on", return_value=True):
            self.assertEqual(npl.s6_q2_auto_redo(ctx)["reason"], "RENDER_STYLE_ANIME")
        with mock.patch.object(npl, "qa_run") as run:
            verdict = npl.check_tail_start_frame(ctx, "E02-VU-002", Path("tail.png"))
            run.assert_not_called()
        self.assertEqual((verdict["verdict"], verdict["status"]), ("ACCEPT", "NOT_APPLICABLE"))
        from tools import push_in_compensation as pic
        self.assertTrue(pic.applies("live_action"))
        self.assertFalse(pic.applies("anime"))
        self.assertEqual(pic.not_applicable_report("E02", "anime")["compensated_units"], [])

    def test_resolve_render_style_in_pipeline(self):
        import nalu_pipeline as npl
        self.assertEqual(npl.resolve_render_style(None, {}, None), "live_action")
        self.assertEqual(npl.resolve_render_style(None, {"project": {"render_style": "anime"}}, None), "anime")
        self.assertEqual(npl.resolve_render_style({"visual_culture_contract": ANIME_VCC}, {}, None), "anime")

    def test_no_face_standing_rule_not_applicable(self):
        import roger_gate_acceptance as rga
        kwargs = dict(failed_gates=["CHARACTER-IDENTITY-ADMISSION"],
                      identity_failures=["DECLARED_CHARACTER_FACE_NOT_FOUND:E02-S01-01:CHAR-CLAIRE"],
                      identity_gate_id="CHARACTER-IDENTITY-ADMISSION", decisions=[],
                      declared_characters=["CHAR-CLAIRE"])
        self.assertTrue(rga.standing_rule_condition(**kwargs)["covered"])
        anime = rga.standing_rule_condition(**kwargs, render_style="anime")
        self.assertFalse(anime["covered"])
        self.assertEqual(anime["reason"], "NO_FACE_RULE_NOT_APPLICABLE_RENDER_STYLE_ANIME")

    def test_flat_transport_and_output_gate(self):
        from tools import image_model_adapter as ima
        from tools import keyframe_output_identity_gate as kog
        bindings = [{"path": "a.png", "role": "character", "entity_id": "CHAR-A", "asset_label": "A"}]
        _, live, live_prompt = ima.compile_labeled_flat_identity_transport("K", bindings, "body")
        self.assertEqual(live["output_identity_verification_method"], "INSIGHTFACE_COSINE_V1")
        self.assertIn("InsightFace", live_prompt)
        _, anime, anime_prompt = ima.compile_labeled_flat_identity_transport(
            "K", bindings, "body", output_identity_verification_method=rs.VLM_IDENTITY_METHOD)
        self.assertEqual(anime["output_identity_verification_method"], rs.VLM_IDENTITY_METHOD)
        self.assertNotIn("InsightFace", anime_prompt)
        with self.assertRaises(ValueError):
            ima.compile_labeled_flat_identity_transport("K", bindings, "body",
                                                        output_identity_verification_method="GUESS")
        contract = {**anime, "authority_map": {"CHAR-A": "A"}}
        tasks = [{"shot_id": "S1", "identity_reference_transport": contract}]
        accepted = [{"shot_id": "S1", "sha256": "X"}]
        vlm_row = {"shot_id": "S1", "entity_id": "CHAR-A", "method": rs.VLM_IDENTITY_METHOD,
                   "output_sha256": "X", "status": "PASS"}
        self.assertEqual(kog.evaluate(tasks, accepted, [vlm_row])["status"], "PASS")
        live_tasks = [{"shot_id": "S1", "identity_reference_transport": {**live, "authority_map": {"CHAR-A": "A"}}}]
        self.assertEqual(kog.evaluate(live_tasks, accepted, [vlm_row])["status"], "FAIL")


# --------------------------------------------------------------------------- rubric + exemplars
class RubricAndExemplars(unittest.TestCase):
    def test_anti_ai_redefined_not_added(self):
        import final_audience_review as far
        live = far.dimension_questions()
        anime = far.dimension_questions("anime")
        self.assertEqual(list(live), list(anime))  # same dimensions: same floor, no new gate
        self.assertEqual(live["anti_ai"],
                         "Does the film avoid obvious AI drift, repetition, warping, and synthetic rhythm?")
        self.assertEqual(anime["anti_ai"], rs.ANTI_AI_QUESTION_ANIME)
        for word in ("intended", "off-model", "style drift", "warping"):
            self.assertIn(word, anime["anti_ai"])
        self.assertEqual({k: v for k, v in live.items() if k != "anti_ai"},
                         {k: v for k, v in anime.items() if k != "anti_ai"})
        from tools import final_cut_quality_gates as fcq
        self.assertIn("anti_ai", fcq.CRAFT_DIMENSIONS)

    def test_exemplars_tagged_and_never_mixed(self):
        from tools.collective_learning import exemplars as ex
        live = ex.practice_exemplar("visual", 4.6, "Clean staging kept both leads readable in every shot.",
                                    language="ja", genre="romance", model="H3", overall=4.5)
        anime = ex.practice_exemplar("visual", 4.6, "Clean staging kept both leads readable in every shot.",
                                     language="ja", genre="romance", model="H3", overall=4.5, render_style="anime")
        self.assertIsNotNone(live)
        self.assertIsNotNone(anime)
        self.assertNotIn("render_style", live["tags"])  # live-action exemplar (and its id) unchanged
        self.assertEqual(anime["tags"]["render_style"], "anime")
        self.assertNotEqual(live["exemplar_id"], anime["exemplar_id"])
        library = [live, anime]
        self.assertEqual([e["exemplar_id"] for e in ex.select_for_episode(library, language="ja")],
                         [live["exemplar_id"]])
        self.assertEqual([e["exemplar_id"] for e in ex.select_for_episode(library, language="ja",
                                                                          render_style="anime")],
                         [anime["exemplar_id"]])
        self.assertNotEqual(ex.type_key(live), ex.type_key(anime))


# --------------------------------------------------------------------------- aspect normalisation
class AspectNormalisation(unittest.TestCase):
    def _png(self, path: Path, size, colour=(200, 30, 30)) -> Path:
        from PIL import Image
        image = Image.new("RGB", size, colour)
        # a centred marker column, so the test can prove the centre (the subject) is kept
        for y in range(size[1]):
            for x in range(size[0] // 2 - 4, size[0] // 2 + 4):
                image.putpixel((x, y), (0, 0, 255))
        image.save(path, format="PNG")
        return path

    def test_two_by_three_becomes_true_nine_sixteen(self):
        from PIL import Image
        from tools import hopsapi_image_client as client
        with tempfile.TemporaryDirectory() as tmp:
            path = self._png(Path(tmp) / "kf.png", (1024, 1536))
            result = client.normalise_portrait_9_16(path)
            self.assertEqual(result["status"], "CROPPED")
            self.assertEqual(result["method"], "CENTRE_CROP_SIDES")
            with Image.open(path) as image:
                self.assertEqual(image.size, (864, 1536))
                self.assertAlmostEqual(image.size[0] / image.size[1], 9 / 16, places=4)
                self.assertEqual(image.getpixel((432, 10)), (0, 0, 255))  # centre kept, top row (heads) kept
            self.assertEqual(client.normalise_portrait_9_16(path)["status"], "UNCHANGED")  # idempotent

    def test_true_nine_sixteen_and_odd_shapes(self):
        from PIL import Image
        from tools import hopsapi_image_client as client
        with tempfile.TemporaryDirectory() as tmp:
            exact = self._png(Path(tmp) / "a.png", (1152, 2048))
            before = exact.read_bytes()
            self.assertEqual(client.normalise_portrait_9_16(exact)["status"], "UNCHANGED")
            self.assertEqual(exact.read_bytes(), before)
            square = self._png(Path(tmp) / "b.png", (1024, 1024))
            self.assertEqual(client.normalise_portrait_9_16(square)["status"], "SKIPPED_NOT_A_NEAR_PORTRAIT_FRAME")
            tall = self._png(Path(tmp) / "c.png", (900, 1800))
            result = client.normalise_portrait_9_16(tall)
            self.assertEqual(result["method"], "TOP_ANCHORED_CROP_BOTTOM")
            with Image.open(tall) as image:
                self.assertEqual(image.size, (900, 1600))
            self.assertEqual(client.normalise_portrait_9_16(Path(tmp) / "missing.png")["status"], "SKIPPED_ERROR")

    def test_harvest_normalises_new_downloads_only(self):
        from unittest import mock
        from PIL import Image
        from tools import harvest_giggle_image_batch as harvest
        self.assertTrue(harvest.wants_true_9_16({"task_key": "E02-S01-01"}))
        self.assertFalse(harvest.wants_true_9_16({"task_key": "CHAR-A__MULTIVIEW_REFERENCE_SHEET"}))
        self.assertFalse(harvest.wants_true_9_16({"task_key": "X", "aspect_ratio": "16:9"}))
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            out, raw = tmp / "out", tmp / "raw"
            out.mkdir()
            raw.mkdir()

            def fake_download(url, destination, fetch=None):
                self._png(Path(destination), (1024, 1536))
                return {}

            status = {"remote_status": "completed", "urls": ["https://x/y.png"], "cost": 0.6}
            with mock.patch.object(harvest.image_client, "query_task", return_value=status), \
                    mock.patch.object(harvest.image_client, "download_image", side_effect=fake_download):
                item = harvest.harvest_one_hopsapi({"task_id": "tsk_1", "task_key": "E02-S01-01"}, "E02", out, raw)
            self.assertEqual(item["aspect_normalisation"]["status"], "CROPPED")
            with Image.open(item["output_path"]) as image:
                self.assertEqual(image.size, (864, 1536))
            self.assertEqual(item["sha256"], hashlib.sha256(Path(item["output_path"]).read_bytes()).hexdigest())


# --------------------------------------------------------------------------- poster
class Poster(unittest.TestCase):
    def test_anime_poster_prompt(self):
        from tools import series_poster as sp
        ident = {"title": "T", "genre": "romance", "style": "", "synopsis": "Two girls at an academy."}
        refs = [{"role": "LEAD", "path": "a.png"}]
        live = sp.build_art_prompt(ident, refs)
        self.assertEqual(live, sp._build_art_prompt(ident, refs))
        self.assertTrue(live.startswith("Cinematic vertical 9:16 key-art poster"))
        anime = sp.build_art_prompt({**ident, "render_style": "anime"}, refs)
        self.assertTrue(anime.startswith(rs.POSTER_OPENING_EN))
        self.assertNotIn("film-still", anime)
        self.assertIn("ABSOLUTELY NO TEXT", anime)
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp) / "qingshan.json", {"project": {"render_style": "anime"}})
            self.assertEqual(sp.poster_render_style({}, Path(tmp)), "anime")
            self.assertEqual(sp.poster_render_style({"render_style": "live_action"}, Path(tmp)), "live_action")


if __name__ == "__main__":
    unittest.main()
