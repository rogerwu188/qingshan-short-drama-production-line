"""Cross-character distinctness (S3 + Q2) and the final review's must-check defect list (line owner 2026-11-19,
《摄政王她又来找茬了》 device …0841: two characters with the same face, a stray burned 「能」, cut line tails, oversized
masks, a lone 「！」 caption row, music that stops after a shot).

Offline, fakes only: no image / video / audio provider call, InsightFace replaced by fixed vectors."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
for entry in (str(TOOLS), str(ROOT / "tools"), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import character_distinctness as cd  # noqa: E402
import nalu_qa_defect_checklist as qa  # noqa: E402
import render_style as rs  # noqa: E402

TWIN_A = [1.0, 0.0, 0.0]
TWIN_B = [0.9, 0.3, 0.0]       # cosine ~0.95 with TWIN_A
OTHER = [0.0, 0.0, 1.0]        # cosine 0 with both


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


CAST = {
    "CHAR-MOON": {"subject_id": "CHAR-MOON", "name": "墨辰", "sex": "男", "age": "22-26岁",
                  "appearance": "黑袍青年，额间新月印记"},
    "CHAR-DRAGON": {"subject_id": "CHAR-DRAGON", "name": "玄甲", "sex": "男", "age": "24-28岁",
                    "appearance": "黑甲青年，龙纹肩甲"},
    "CHAR-LADY": {"subject_id": "CHAR-LADY", "name": "摄政王", "sex": "女", "age": "24-28岁",
                  "appearance": "红衣女子"},
}


class DifferentiationPromptTest(unittest.TestCase):
    def test_contrast_block_names_same_band_peers_and_face_structure(self):
        block = cd.contrast_block(CAST["CHAR-DRAGON"], CAST.values())
        for word in ("脸型", "下颌", "眼型", "鼻", "眉形", "年龄感", "体型", "标志性特征", "墨辰"):
            self.assertIn(word, block)
        self.assertNotIn("摄政王", block)  # other sex: not a peer
        self.assertIn("不能只靠服装", block)
        alone = cd.contrast_block(CAST["CHAR-LADY"], CAST.values())
        self.assertIn("脸型", alone)
        self.assertNotIn("同性别", alone)
        english = cd.contrast_block({**CAST["CHAR-DRAGON"], "name": "Xuan"}, CAST.values(), language="en")
        self.assertIn("jawline", english)

    def test_differentiation_block_names_the_lookalike_and_cosine(self):
        block = cd.differentiation_block(CAST["CHAR-DRAGON"], [CAST["CHAR-MOON"]], cosine=0.52)
        self.assertIn("墨辰", block)
        self.assertIn("0.52", block)
        self.assertIn("下颌", block)

    def test_new_card_prompt_carries_the_contrast(self):
        import build_episode_asset_requirements as bear
        row = {"asset_id": "CHAR-DRAGON", "specification": {"canonical_name": "玄甲", "apparent_age_range": "24-28岁",
                                                           "sex": "男", "appearance_ch1": "黑甲青年"}}
        contrast = cd.contrast_block(cd.cast_row(row["specification"], "CHAR-DRAGON"), CAST.values())
        body, _ = bear.character_prompt(row, "黑甲", "STYLE", contrast)
        self.assertIn("【面部区分·硬性】", body)
        plain, _ = bear.character_prompt(row, "黑甲", "STYLE")
        self.assertNotIn("【面部区分", plain)

    def test_writer_contract_requires_distinct_faces(self):
        text = (ROOT / "skills/nalu-claude-code/CLAUDE_CODE_PRODUCTION.md").read_text(encoding="utf-8")
        self.assertIn("角色面孔区分", text)
        self.assertIn("同性别、同年龄段", text)


class PairwiseAndCapTest(unittest.TestCase):
    def setUp(self):
        self.emb = {"CHAR-MOON": [TWIN_A], "CHAR-DRAGON": [TWIN_B], "CHAR-LADY": [OTHER]}
        self.order = ["CHAR-MOON", "CHAR-DRAGON", "CHAR-LADY"]

    def test_pairwise_cosine_between_different_characters(self):
        rows = cd.pairwise(self.emb, self.order)
        self.assertEqual(len(rows), 3)
        top = rows[0]
        self.assertEqual((top["a"], top["b"]), ("CHAR-MOON", "CHAR-DRAGON"))
        self.assertGreater(top["cosine"], 0.9)

    def test_threshold_is_above_the_registry_boundary_midpoint(self):
        registry = json.loads((ROOT / "configs/GATE_REGISTRY_v3_20260716.json").read_text(encoding="utf-8"))
        params = next(g["parameters"] for g in registry["gates"] if g.get("gate_id") == "CHARACTER-IDENTITY-ADMISSION")
        self.assertGreater(cd.TOO_SIMILAR_COSINE, params["embedding_cosine_boundary_auto_decision_midpoint"])
        self.assertLess(cd.TOO_SIMILAR_COSINE, params["embedding_cosine_pass_threshold"])

    def test_later_regenerable_character_is_regenerated_once_then_advisory(self):
        report = cd.evaluate(self.emb, order=self.order, cast=CAST, policy={},
                             regenerable={"CHAR-MOON", "CHAR-DRAGON", "CHAR-LADY"})
        self.assertEqual(report["status"], "REGENERATE")
        self.assertEqual([r["subject_id"] for r in report["regenerate"]], ["CHAR-DRAGON"])
        self.assertIn("墨辰", report["regenerate"][0]["block"])
        with tempfile.TemporaryDirectory() as tmp:
            prompt_dir = Path(tmp) / "prompts"
            plates = Path(tmp) / "plates"
            prompt_dir.mkdir()
            base = _write(plates / "E05_CHAR-DRAGON_tsk_abcdef123456.png", "old")
            view = _write(plates / "E05_CHAR-DRAGON__FRONT_NEUTRAL_HEADSHOT_tsk_abcdef999999.png", "old")
            keep = _write(plates / "E05_CHAR-MOON_tsk_abcdef123456.png", "keep")
            applied = cd.apply_regenerations(report, prompt_dir=prompt_dir, plates_dir=plates, episode="E05")
            self.assertFalse(base.exists())
            self.assertFalse(view.exists())
            self.assertTrue(keep.exists())
            self.assertEqual(len(applied["parked"]), 2)
            policy = cd.load_policy(prompt_dir)
            self.assertEqual(policy["regenerations"]["CHAR-DRAGON"]["suffix"], "__DISTINCT_R1")
            # second measurement: still alike -> accepted with an advisory, never a second regeneration
            again = cd.evaluate(self.emb, order=self.order, cast=CAST, policy=policy,
                                regenerable={"CHAR-MOON", "CHAR-DRAGON", "CHAR-LADY"})
            self.assertEqual(again["regenerate"], [])
            self.assertEqual(again["status"], "ADVISORY")
            self.assertEqual(again["advisories"][0]["reason"], "TOO_SIMILAR_AFTER_ONE_REGENERATION_ACCEPTED")

    def test_operator_photo_or_locked_cards_are_never_regenerated(self):
        report = cd.evaluate(self.emb, order=self.order, cast=CAST, policy={}, regenerable={"CHAR-LADY"})
        self.assertEqual(report["regenerate"], [])
        self.assertEqual(report["advisories"][0]["reason"], "TOO_SIMILAR_NO_REGENERABLE_CARD")

    def test_bootstrap_plans_a_new_prompt_for_the_regenerated_card(self):
        import bootstrap_identity_cards as boot
        with tempfile.TemporaryDirectory() as tmp:
            prompt_dir = Path(tmp) / "prompts"
            _write(prompt_dir / "E05-CHAR-DRAGON.txt", "【人物身份基准卡】玄甲\n构图：单人\n")
            subjects = [{"subject_id": "CHAR-DRAGON", "kind": "CHARACTER", "canonical_name": "玄甲",
                         "card_deliverables": ["FULL_BODY_STANDING"]}]
            kwargs = dict(episode="E05", prompt_dir=prompt_dir, gate_report_path=Path(tmp) / "g.json",
                          authorization_ref="test", plates_dir=Path(tmp) / "plates", generation_contract={},
                          render_style="live_action")
            with mock.patch.object(boot, "apply_culture_lock"):
                before, _, _ = boot.build_plan(subjects, {}, **kwargs)
                _write(prompt_dir.parent / cd.POLICY_NAME, {"regenerations": {"CHAR-DRAGON": {
                    "block": "【面部区分·重做】不同", "suffix": "__DISTINCT_R1", "round": 1,
                    "against": ["CHAR-MOON"], "cosine_before": 0.6}}})
                after, _, _ = boot.build_plan(subjects, {}, **kwargs)
            row0, row1 = before["new_asset_groups"][0], after["new_asset_groups"][0]
            self.assertEqual(row0["id"], row1["id"])
            self.assertNotEqual(row0["prompt_sha256"], row1["prompt_sha256"])
            self.assertTrue(row1["prompt_file"].endswith("E05-CHAR-DRAGON__DISTINCT_R1.txt"))
            self.assertIn("【面部区分·重做】", Path(row1["prompt_file"]).read_text(encoding="utf-8"))
            self.assertEqual(row1["distinctness_regeneration"]["round"], 1)


class PipelineS3HookTest(unittest.TestCase):
    def _ctx(self, tmp: Path, *, paid: bool, style: str = "live_action"):
        identity = tmp / "identity"
        plates = identity / "plates"
        for cid in ("CHAR-MOON", "CHAR-DRAGON"):
            _write(plates / f"E05_{cid}_tsk_abcdef123456.png", cid)
        rt_pre = tmp / "pre"
        _write(rt_pre / "asset_requirements.json", {"assets": {"characters": [
            {"asset_id": "CHAR-MOON", "specification": {"canonical_name": "墨辰", "sex": "男",
                                                         "apparent_age_range": "22-26岁"}},
            {"asset_id": "CHAR-DRAGON", "specification": {"canonical_name": "玄甲", "sex": "男",
                                                           "apparent_age_range": "24-28岁"}}]}})
        (rt_pre / "prompts").mkdir(parents=True, exist_ok=True)
        p = SimpleNamespace(identity=identity, identity_harvest_dir=plates, asset_requirements=rt_pre /
                            "asset_requirements.json", prompt_dir=rt_pre / "prompts", scope={})
        return SimpleNamespace(p=p, episode="E05", paid_enabled=paid, render_style=style, say=lambda *_: None)

    def _rows(self):
        return [{"id": cid, "kind": "CHARACTER", "view": "FULL_BODY_STANDING", "reference_images": []}
                for cid in ("CHAR-MOON", "CHAR-DRAGON")]

    def test_live_action_regenerates_later_card_and_parks_its_plate(self):
        mod = importlib.import_module("nalu_pipeline")
        vectors = {"CHAR-MOON": TWIN_A, "CHAR-DRAGON": TWIN_B}
        embed = (lambda path: [vectors["CHAR-DRAGON" if "DRAGON" in Path(path).name else "CHAR-MOON"]], cd._cos)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(mod, "kb_events",
                                                                     return_value={"status": "OK"}) as kb:
            ctx = self._ctx(Path(tmp), paid=True)
            res = SimpleNamespace(receipts=[])
            report = mod.s3_character_distinctness(ctx, res, self._rows(), library={}, embedder=embed)
            self.assertEqual([r["subject_id"] for r in report["regenerate"]], ["CHAR-DRAGON"])
            self.assertFalse((ctx.p.identity_harvest_dir / "E05_CHAR-DRAGON_tsk_abcdef123456.png").exists())
            self.assertTrue((ctx.p.identity / "E05_CHARACTER_DISTINCTNESS.json").is_file())
            self.assertEqual(kb.call_args[0][0], "record_lookalike_cast")

    def test_without_paid_route_nothing_is_parked(self):
        mod = importlib.import_module("nalu_pipeline")
        embed = (lambda path: [TWIN_A if "MOON" in Path(path).name else TWIN_B], cd._cos)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(mod, "kb_events", return_value={}):
            ctx = self._ctx(Path(tmp), paid=False)
            report = mod.s3_character_distinctness(ctx, SimpleNamespace(receipts=[]), self._rows(), library={},
                                                   embedder=embed)
            self.assertEqual(report["regenerate"], [])
            self.assertEqual(report["status"], "ADVISORY_REGENERATION_NEEDS_PAID_RUN")
            self.assertTrue((ctx.p.identity_harvest_dir / "E05_CHAR-DRAGON_tsk_abcdef123456.png").exists())

    def test_anime_uses_the_review_question_not_insightface(self):
        mod = importlib.import_module("nalu_pipeline")
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self._ctx(Path(tmp), paid=True, style="anime")
            out = mod.s3_character_distinctness(ctx, SimpleNamespace(receipts=[]), self._rows(), library={},
                                                embedder=None)
            self.assertEqual(out["status"], "NOT_APPLICABLE")


class AnimePathTest(unittest.TestCase):
    def test_anime_identity_questionnaire_has_a_descriptive_distinctness_question(self):
        out = rs.style_questionnaire("identity", {"plate_is_photographic_not_illustrated": {"enum": ["PASS"]}},
                                     "anime")
        spec = out[rs.CAST_DISTINCT_QUESTION]
        self.assertEqual(rs.CAST_DISTINCT_QUESTION, cd.ANIME_QUESTION)
        import vlm_review_protocol as vrp
        self.assertFalse(set(spec["enum"]) & (vrp.FAIL_ANSWERS | vrp.UNCERTAIN_ANSWERS))
        self.assertNotIn(rs.CAST_DISTINCT_QUESTION, rs.style_questionnaire("keyframe", {}, "anime"))
        self.assertNotIn(rs.CAST_DISTINCT_QUESTION, rs.style_questionnaire("identity", {}, "live_action"))

    def test_anime_record_turns_too_similar_into_an_advisory(self):
        record = cd.anime_record([
            {"item_id": "CHAR-A", "answers": {cd.ANIME_QUESTION: "TOO_SIMILAR"}, "observation": "same hair as B"},
            {"item_id": "CHAR-B", "answers": {cd.ANIME_QUESTION: "DISTINCT"}}])
        self.assertEqual(record["status"], "ADVISORY")
        self.assertEqual(record["insightface"], "NOT_APPLICABLE")
        self.assertEqual(cd.lookalike_pairs(record)[0]["a"], "CHAR-A")


class Q2WrongFaceTest(unittest.TestCase):
    def setUp(self):
        self.q2 = importlib.import_module("video_q2_builder")

    def _samples(self, own, other, n=4, closest="CHAR-MOON"):
        return {"CHAR-DRAGON": [{"frame": f"f{i}", "own": own, "closest_other": closest, "other": other}
                                for i in range(n)]}

    def test_face_of_another_character_fails_and_is_redo_eligible(self):
        verdict = self.q2.wrong_face_verdict(self._samples(0.33, 0.62), declared={"CHAR-DRAGON"})
        self.assertEqual(verdict["status"], "FAIL")
        self.assertIn("WRONG_CHARACTER_FACE:CHAR-DRAGON:looks_like:CHAR-MOON", verdict["failure"])
        checks, failures = [{"question_id": "each_visible_character_identity_recognisable", "answer": "PASS"}], []
        self.assertTrue(self.q2.apply_wrong_face(verdict, checks, failures))
        self.assertEqual(checks[0]["answer"], "FAIL")
        self.assertEqual(checks[0]["reviewer_answer"], "PASS")
        self.assertIn("each_visible_character_identity_recognisable", failures)
        import q2_auto_redo as redo
        self.assertEqual(redo.objective_failures({"wrong_face": verdict}), ["wrong_face"])
        self.assertTrue(redo.needs_own_keyframe(["wrong_face"]))

    def test_lookalike_without_confidence_is_only_advisory(self):
        verdict = self.q2.wrong_face_verdict(self._samples(0.50, 0.53))
        self.assertEqual(verdict["status"], "ADVISORY")
        self.assertFalse(self.q2.apply_wrong_face(verdict, [], []))

    def test_intended_face_passes_and_few_samples_are_not_measured(self):
        self.assertEqual(self.q2.wrong_face_verdict(self._samples(0.7, 0.2))["status"], "PASS")
        self.assertEqual(self.q2.wrong_face_verdict(self._samples(0.2, 0.7, n=2))["status"], "NOT_MEASURED")

    def test_sample_records_closest_other_character(self):
        row = self.q2.wrong_face_sample("f0", "CHAR-DRAGON", 0.3, TWIN_A,
                                        {"CHAR-MOON": [TWIN_B], "CHAR-LADY": [OTHER], "CHAR-DRAGON": [TWIN_A]},
                                        cd._cos)
        self.assertEqual(row["closest_other"], "CHAR-MOON")


SHOTS = [{"shot_index": 0, "start_seconds": 0.0, "end_seconds": 4.0},
         {"shot_index": 1, "start_seconds": 4.0, "end_seconds": 9.0},
         {"shot_index": 2, "start_seconds": 9.0, "end_seconds": 20.0}]


class DefectMeasurementTest(unittest.TestCase):
    def test_dialogue_tail_gap_to_cut(self):
        asr = [{"start": 1.0, "end": 3.97, "unit_id": "VU-1"}, {"start": 4.5, "end": 8.85},
               {"start": 10.0, "end": 12.0}]
        out = qa.measure_dialogue_tail(asr, SHOTS)
        flags = {r["line_end"]: r["flag"] for r in out["flagged"]}
        self.assertEqual(flags, {3.97: "LIKELY_CLIPPED", 8.85: "NO_PAUSE"})

    def test_masks_area_and_oversized(self):
        scan = {"intervals": [[1.0, 2.0], [5.0, 6.0]],
                "bands": [{"y0": 0.66, "y1": 0.81, "x0": 0.06, "x1": 0.94},
                          {"y0": 0.40, "y1": 0.95, "x0": 0.0, "x1": 1.0}]}
        out = qa.measure_masks(scan)
        self.assertFalse(out["runs"][0]["oversized"])
        self.assertEqual([r["start"] for r in out["oversized"]], [5.0])

    def test_burned_text_hits_per_timestamp(self):
        verify = {"status": "FAIL", "text_outside_bar": [{"t": 18.5, "text": "能", "box": [0.4, 0.88, 0.5, 0.93]}],
                  "text_inside_bar_not_the_caption": []}
        out = qa.measure_burned_text({"intervals": [[18.25, 19.0]], "seconds": 0.75}, verify)
        self.assertEqual(out["hits"][0]["t"], 18.5)
        self.assertEqual(out["covered_runs"], [[18.25, 19.0]])

    def test_subtitle_wrap_flags_lone_exclamation_row(self):
        ass = ("[Events]\nDialogue: 0,0:00:01.00,0:00:03.00,Default,甲,0,0,0,,你竟敢这样对我说话\\N！\n"
               "Dialogue: 0,0:00:04.00,0:00:05.00,Default,乙,0,0,0,,好\n")
        out = qa.measure_subtitle_wrap(ass)
        self.assertEqual(out["captions"], 2)
        self.assertEqual(out["flagged"][0]["start"], 1.0)
        self.assertIn("LONE_PUNCTUATION_ROW", out["flagged"][0]["reasons"])

    def test_bgm_short_run_and_abrupt_stop_at_cut(self):
        plan = {"cues": [{"cue_id": "C1", "timeline_start": 0.0, "duration": 4.0, "fade_out_s": 0.0},
                         {"cue_id": "C2", "timeline_start": 9.0, "duration": 11.0, "fade_in_s": 1.0,
                          "fade_out_s": 1.5}]}
        out = qa.measure_bgm(plan, {"params": {"music_mode": "cues_only"}, "pad_regions": []}, SHOTS)
        self.assertEqual([s["start"] for s in out["segments"]], [0.0, 9.0])
        flagged = out["flagged"][0]
        self.assertEqual(flagged["start"], 0.0)
        self.assertIn("SHORT_RUN", flagged["reasons"])
        self.assertIn("ABRUPT_STOP_AT_CUT", flagged["reasons"])
        self.assertEqual(len(out["flagged"]), 1)

    def test_lookalike_measurement_from_s3_report(self):
        report = cd.evaluate({"CHAR-MOON": [TWIN_A], "CHAR-DRAGON": [TWIN_B]}, order=["CHAR-MOON", "CHAR-DRAGON"],
                             cast=CAST, policy={}, regenerable=set())
        out = qa.measure_lookalike(report)
        self.assertEqual(out["too_similar"][0]["a"], "CHAR-MOON")


class FinalReviewChecklistTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_request_carries_all_six_items_and_measurements(self):
        from lines.nalu.runtime.tools import final_audience_review as review
        from tools.tests.test_nalu_final_audience_review import FinalAudienceReviewTests
        case = FinalAudienceReviewTests("test_prepare_binds_real_media_and_never_writes_reviewer_outputs")
        case.setUp()
        try:
            measured = {"dialogue_tail": {"flagged": [{"line_end": 5.9, "flag": "NO_PAUSE"}]}}
            with mock.patch.object(review, "qa_defect_measurements", return_value=measured):
                case._prepare()
            request = json.loads(case.request.read_text(encoding="utf-8"))
        finally:
            case.tearDown()
        self.assertEqual(qa.items_present(request), list(qa.ITEM_IDS))
        self.assertEqual(set(qa.ITEM_IDS), {"QA-BURNED-TEXT", "QA-DIALOGUE-TAIL-CUT", "QA-OVERSIZED-MASK",
                                            "QA-LOOKALIKE-CAST", "QA-SUBTITLE-WRAP", "QA-BGM-DISCONTINUOUS",
                                            "QA-SKIN-SHEEN-DRIFT", "QA-EDIT-FRAGMENT", "QA-CAMERA-WOBBLE",
                                            "QA-SILENT-MOUTH"})
        self.assertEqual(request["qa_defect_checklist_request"]["measurements"], measured)
        self.assertIn("qa_defect_checklist", request["answer_contract"])
        self.assertIn("qa_defect_checklist_request", request["reviewer_contract"]["instruction"])

    def test_measurements_read_s7_reports_without_editing_them(self):
        assembly = self.root / "assembly"
        scan = _write(assembly / "E05_H3_BURNED_TEXT_INTERVALS.json",
                      {"intervals": [[1.0, 2.0]], "bands": [{"y0": 0.3, "y1": 0.95, "x0": 0.0, "x1": 1.0}]})
        ass = _write(assembly / "E05.ass", "Dialogue: 0,0:00:01.00,0:00:02.00,D,甲,0,0,0,,走\\N！\n")
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (scan, ass)}
        out = qa.measure(shots=SHOTS, asr=[], scan_path=scan, verify_path=None, ass_path=ass)
        self.assertTrue(out["masks"]["oversized"])
        self.assertTrue(out["subtitle_wrap"]["flagged"])
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (scan, ass)})

    def test_lenient_parse_record_routing_and_events(self):
        parsed = qa.parse_block({"items": {
            "QA-BURNED-TEXT": {"verdict": "DEFECT", "findings": [{"at_seconds": 18.5, "note": "stray 能"}]},
            "qa-subtitle-wrap": {"verdict": "PASS"},
            "QA-NOPE": {"verdict": "DEFECT"},
            "QA-BGM-DISCONTINUOUS": {"verdict": "DEFECT", "findings": [{"note": "no time"}]}}}, duration=60.0)
        self.assertEqual(parsed["status"], "PARTIAL")
        self.assertIn("QA-SUBTITLE-WRAP", parsed["items"])
        measured = {"dialogue_tail": {"flagged": [{"line_end": 3.97, "flag": "LIKELY_CLIPPED", "gap_seconds": 0.03}]},
                    "lookalike_cast": {"too_similar": [{"a": "CHAR-MOON", "b": "CHAR-DRAGON", "cosine": 0.6}]}}
        record = qa.build_record(parsed, measured, episode="E05")
        self.assertEqual(record["items"]["QA-BURNED-TEXT"]["status"], "DEFECT")
        self.assertEqual(record["items"]["QA-DIALOGUE-TAIL-CUT"]["status"], "MEASURED_FLAG_UNREVIEWED")
        self.assertEqual(record["items"]["QA-LOOKALIKE-CAST"]["routing"],
                         "KNOWLEDGE_BASE_AND_NEXT_EPISODE_IDENTITY_DESIGN")
        self.assertEqual(record["items"]["QA-BURNED-TEXT"]["routing"], "S6_UNIT_REDO_FINAL_FIX_ROUND")
        self.assertTrue(record["items"]["QA-BGM-DISCONTINUOUS"]["routing"].startswith("S7_FIXABLE"))
        specs = {s["item_id"]: s for s in qa.event_specs(record)}
        self.assertEqual(specs["QA-BURNED-TEXT"]["evidence"]["cluster_key"], "QA_DEFECT|QA-BURNED-TEXT")
        self.assertEqual(specs["QA-BURNED-TEXT"]["evidence"]["detail"]["at_seconds"], [18.5])
        self.assertEqual(specs["QA-LOOKALIKE-CAST"]["stage"], "S3")
        self.assertNotIn("stray", json.dumps(specs, ensure_ascii=False))  # no reviewer note / OCR text in events
        self.assertEqual(qa.parse_block(None)["status"], "MISSING")
        self.assertEqual(qa.parse_block("x")["status"], "MALFORMED")

    def test_submit_writes_checklist_without_changing_the_verdict(self):
        from lines.nalu.runtime.tools import final_audience_review as review
        request = {"episode": "E05", "media": {"sha256": "a" * 64}, "objective_summary": {"duration_seconds": 30},
                   "qa_defect_checklist_request": {"measurements": {}}}
        answers = {"qa_defect_checklist": {"items": {"QA-OVERSIZED-MASK": {
            "verdict": "DEFECT", "findings": [{"window": [5, 6], "note": "blur covers the face"}]}}},
                   "reviewer": {"model": "hopsapi/gpt-6.1-sol"}}
        out = review._record_qa_defects(request, "b" * 64, answers, self.root / "final_qa" / "E05_REPORT.json")
        self.assertEqual(out["defects"], ["QA-OVERSIZED-MASK"])
        self.assertEqual(out["authority"], "ADVISORY_NOT_A_GATE")
        record = json.loads(Path(out["path"]).read_text(encoding="utf-8"))
        self.assertEqual(record["items"]["QA-OVERSIZED-MASK"]["reviewer_findings"][0]["window"], [5.0, 6.0])

    def test_reviewer_prompt_and_craft_crosswalk(self):
        import nalu_craft_standard as craft
        self.assertEqual(craft.QA_DEFECT_CRAFT_ITEMS, qa.craft_mapping())
        sys.path.insert(0, str(ROOT / "skills/nalu-claude-code/scripts"))
        import codex_production as cp
        prompt = cp.reviewer_prompt("E05", Path("/r.json"), Path("/a.json"), "pid", "submit")
        for iid in qa.ITEM_IDS:
            self.assertIn(iid, prompt)


class KnowledgeEventsTest(unittest.TestCase):
    def test_qa_defect_and_lookalike_events_are_recorded_once(self):
        import nalu_knowledge_events as kbe
        rt = Path(tempfile.mkdtemp()) / "runtime"
        (rt / "reports").mkdir(parents=True)
        record = qa.build_record(qa.parse_block({"items": {"QA-SUBTITLE-WRAP": {
            "verdict": "DEFECT", "findings": [{"at_seconds": 12.0, "note": "lone ！"}]}}}), {}, episode="E05",
            bindings={"final_video_sha256": "c" * 64})
        path = _write(rt / "E05_QA_DEFECT_CHECKLIST.json", record)
        out = kbe.record_qa_defects(rt, episode="E05", checklist_path=str(path))
        self.assertEqual([e["failure_type"] for e in out["events"]], ["QA_DEFECT:QA-SUBTITLE-WRAP"])
        self.assertEqual(out["events"][0]["status"], "RECORDED")
        again = kbe.record_qa_defects(rt, episode="E05", checklist_path=str(path))
        self.assertEqual(again["events"][0]["status"], "DUPLICATE")
        report = cd.evaluate({"CHAR-MOON": [TWIN_A], "CHAR-DRAGON": [TWIN_B]}, order=["CHAR-MOON", "CHAR-DRAGON"],
                             cast=CAST, policy={}, regenerable=set())
        rpath = _write(rt / "E05_CHARACTER_DISTINCTNESS.json", report)
        look = kbe.record_lookalike_cast(rt, episode="E05", report_path=str(rpath))
        self.assertEqual(look["events"][0]["failure_type"], "QA_DEFECT:QA-LOOKALIKE-CAST")
        self.assertEqual(look["events"][0]["status"], "RECORDED")


class S8SummaryTest(unittest.TestCase):
    def test_checkpoint_lists_findings_with_timestamps_and_lookalike_cast(self):
        mod = importlib.import_module("nalu_pipeline")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            p = SimpleNamespace(assembly=tmp / "assembly", identity=tmp / "identity")
            record = qa.build_record(qa.parse_block({"items": {"QA-BURNED-TEXT": {
                "verdict": "DEFECT", "findings": [{"at_seconds": 18.5, "note": "能"}]}}}),
                {"bgm": {"flagged": [{"start": 0.0, "end": 4.0, "reasons": ["SHORT_RUN"]}]}}, episode="E05")
            _write(p.assembly / "final_qa" / "E05_QA_DEFECT_CHECKLIST.json", record)
            report = cd.evaluate({"CHAR-MOON": [TWIN_A], "CHAR-DRAGON": [TWIN_B]},
                                 order=["CHAR-MOON", "CHAR-DRAGON"], cast=CAST, policy={}, regenerable=set())
            _write(p.identity / "E05_CHARACTER_DISTINCTNESS.json", report)
            text = "\n".join(mod.qa_defect_checkpoint_lines(SimpleNamespace(p=p, episode="E05")))
        self.assertIn("Final-review must-check defects", text)
        self.assertIn("`QA-BURNED-TEXT`", text)
        self.assertIn("18.5s", text)
        self.assertIn("QA-BGM-DISCONTINUOUS", text)
        self.assertIn("0.0-4.0s", text)
        self.assertIn("`CHAR-MOON` ~ `CHAR-DRAGON`", text)

    def test_checkpoint_is_empty_without_records(self):
        mod = importlib.import_module("nalu_pipeline")
        with tempfile.TemporaryDirectory() as tmp:
            p = SimpleNamespace(assembly=Path(tmp), identity=Path(tmp))
            self.assertEqual(mod.qa_defect_checkpoint_lines(SimpleNamespace(p=p, episode="E05")), [])


if __name__ == "__main__":
    unittest.main()
