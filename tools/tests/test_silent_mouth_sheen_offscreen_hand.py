"""Line owner 2026-11-24: KO E01 (device ...1437) -- an oily / wet-looking face at 0:32 and a man talking with NO sound
at 0:39 (S7 muted the voice H3 generated in a unit with no line); JA E11 (device ...1485) -- characters shaking hands
with a disembodied off-screen hand at 1:03 / 1:07.  Offline, fakes only."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
for entry in (str(TOOLS), str(ROOT / "tools"), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import final_fix_round as ffr  # noqa: E402
import gemini_review_passes as mp  # noqa: E402
import nalu_qa_defect_checklist as qa  # noqa: E402
import q2_auto_redo as redo  # noqa: E402
import render_style as rs  # noqa: E402
import video_q2_builder as q2  # noqa: E402
import vlm_review_protocol as vlm  # noqa: E402
from tools import h3_provider_english_contract as en  # noqa: E402


class Q2ObjectiveFailures(unittest.TestCase):
    def test_new_questions_are_objective_and_mirrored(self):
        questions = vlm.QUESTIONNAIRES["video_q2"]
        for q in ("no_offscreen_limb_reaching_in", "skin_finish_natural"):
            self.assertIn(q, questions)
            self.assertIn(q, q2.GATE_QUESTIONS[q2.ACTION_GATE])
        self.assertEqual(vlm.VLM_OBJECTIVE_FAILURES, redo.VLM_QUESTION_FAILURES)
        self.assertEqual(redo.vlm_objective_failures({"no_offscreen_limb_reaching_in": "FAIL"}), ["invented_person"])
        self.assertEqual(redo.vlm_objective_failures({"skin_finish_natural": "FAIL"}), ["skin_sheen"])
        self.assertEqual(len(redo.VLM_FAILURES), len(set(redo.VLM_FAILURES)))
        self.assertIn("anime", questions["no_offscreen_limb_reaching_in"]["question"])

    def test_silent_speech_is_redone_once_in_every_style(self):
        rows = {"VU-003": {"render_style": "anime", "silent_speech": {"status": "FAIL"}, "media_sha256": "a"},
                "VU-004": {"silent_speech": {"status": "PASS"}}}
        out = redo.plan(rows, {}, headroom=100, unit_cost=lambda u: 9)
        self.assertEqual([r["unit_id"] for r in out["selected"]], ["VU-003"])
        self.assertEqual(out["selected"][0]["failures"], ["silent_speech"])
        self.assertFalse(redo.needs_own_keyframe(["silent_speech"]))
        self.assertEqual(redo.objective_failures({"silent_speech": {"status": "FAIL"}}, technical_only=True),
                         ["silent_speech"])
        again = redo.plan(rows, {"VU-003": {"failures": ["silent_speech"]}}, headroom=100, unit_cost=lambda u: 9)
        self.assertEqual(again["selected"], [])

    def test_redo_prompt_states_the_measured_problem(self):
        state = {redo.STATE_KEY: {"VU-003": {"failures": ["silent_speech", "skin_sheen", "invented_person"]}}}
        findings = redo.redo_findings(state, "VU-003")
        self.assertEqual(findings, ["silent_speech", "skin_sheen", "invented_person"])
        text = " ".join(en.redo_finding_sentences({"h3_redo_findings": findings}))
        self.assertIn("lips closed", text)
        self.assertIn("matte skin", text)
        self.assertIn("from off screen", text)

    def test_silent_speech_check(self):
        exp = {"expected_dialogue": [], "required_visible_character_ids": ["CHAR-A"]}
        talk = q2.silent_speech_check(exp, Path("/x.mp4"), duration=4.0,
                                      measure=lambda p, a, d: {"method": "FAKE", "windows": [[1.0, 1.8]]})
        self.assertEqual(talk["status"], "FAIL")
        self.assertEqual(talk["flagged_windows"], [[1.0, 1.8]])
        murmur = q2.silent_speech_check(exp, Path("/x.mp4"), duration=4.0,
                                        measure=lambda p, a, d: {"method": "FAKE", "windows": [[1.0, 1.1]]})
        self.assertEqual(murmur["status"], "PASS")
        self.assertIsNone(q2.silent_speech_check({**exp, "expected_dialogue": [{"spoken_text": "x"}]},
                                                 Path("/x.mp4"), duration=4.0))
        self.assertIsNone(q2.silent_speech_check({"expected_dialogue": []}, Path("/x.mp4"), duration=4.0))
        broken = q2.silent_speech_check(exp, Path("/x.mp4"), duration=4.0, measure=lambda p, a, d: 1 / 0)
        self.assertEqual(broken["status"], "ERROR")


class FinalReview(unittest.TestCase):
    REPORT = {"units": [{"unit_id": "E01-VU-009", "muted": True, "flagged": True, "speech_seconds": 1.4},
                        {"unit_id": "E01-VU-010", "muted": True, "flagged": False, "speech_seconds": 0.1}],
              "mute_windows": [{"unit_id": "E01-VU-009", "start_seconds": 39.1, "end_seconds": 39.9},
                               {"unit_id": "E01-VU-009", "start_seconds": 40.2, "end_seconds": 40.8},
                               {"unit_id": "E01-VU-010", "start_seconds": 44.0, "end_seconds": 44.1}]}

    def test_muted_voices_become_must_check_and_gemini_suspects(self):
        m = qa.measure_silent_mouth(self.REPORT)
        self.assertEqual(m["units"], [{"unit_id": "E01-VU-009", "window": [39.1, 40.8], "speech_seconds": 1.4}])
        self.assertIn("QA-SILENT-MOUTH", qa.ITEM_IDS)
        self.assertEqual(qa.routing("QA-SILENT-MOUTH"), "S6_UNIT_REDO_FINAL_FIX_ROUND")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "E01_SILENT_UNIT_STRAY_SPEECH.json"
            path.write_text(__import__("json").dumps(self.REPORT), encoding="utf-8")
            self.assertEqual(qa.measure(shots=[], silent_speech_path=path)["silent_mouth"], m)
        sus = mp.silent_mouth_suspects(m, 3)
        self.assertEqual(sus[0]["kind"], "silent_mouth")
        self.assertEqual(sus[0]["id"], "S4")
        split = mp.split_suspects({"silent_mouth": sus})
        self.assertEqual(split["A"]["silent_mouth"], sus)
        self.assertEqual(split["E"]["silent_mouth"], sus)
        self.assertEqual(mp.CLASS_TEXT["QA-SILENT-MOUTH"][0], "A")
        self.assertIn("即使前后镜头也一样油", mp.CLASS_TEXT["QA-SKIN-SHEEN-DRIFT"][1])
        self.assertIn("画框外伸进来", mp.CLASS_TEXT["QA-PLAN-MISMATCH"][1])

    def test_fix_round_redoes_a_silent_mouth(self):
        self.assertEqual(ffr.classify("QA-SILENT-MOUTH", ""), "SILENT_MOUTH")
        self.assertEqual(ffr.fix_class("SILENT_MOUTH"), ffr.PAID)
        self.assertIn("lips closed", ffr.SENTENCES["SILENT_MOUTH"])
        self.assertEqual(ffr.classify("QA-LIPSYNC", "the man's mouth is moving but there is no sound"),
                         "SILENT_MOUTH")
        self.assertEqual(ffr.classify("QA-LIPSYNC", "0:39 男人嘴在动却没有声音"), "SILENT_MOUTH")
        obj = ffr.objective_defects({}, suspect_checks=[
            {"suspect": {"kind": "silent_mouth", "unit": "VU-009", "window": [39.1, 40.8]}, "decision": "CONFIRMED"},
            {"suspect": {"kind": "silent_mouth", "unit": "VU-012", "window": [50.0, 51.0]}, "decision": "DISMISSED"}])
        self.assertEqual([r["unit"] for r in obj["silent_mouths"]], ["VU-009"])
        self.assertIn("SILENT_MOUTH", obj["classes"])
        self.assertNotIn("SILENT_MOUTH", ffr.release_policy(obj, env={})["held_classes"])


class LiveActionSkinFinish(unittest.TestCase):
    def test_cards_sheets_and_keyframes_ask_for_matte_skin(self):
        import build_episode_asset_requirements as bar
        import build_keyframe_manifest as bkm
        import character_reference_sheet as crs
        row = {"asset_id": "CHAR-A", "specification": {"canonical_name": "A", "apparent_age_range": "30-35",
                                                       "sex": "male", "appearance_ch1": "短发"}}
        live, _ = bar.character_prompt(row, "西装", "【视觉文化档案】X")
        anime, _ = bar.character_prompt(row, "西装", "【视觉文化档案】X\n" + rs.IMAGE_STYLE_BLOCK_ZH)
        self.assertIn(rs.LIVE_SKIN_FINISH_ZH, live)
        self.assertNotIn(rs.LIVE_SKIN_FINISH_ZH, anime)
        self.assertIn(rs.LIVE_SKIN_FINISH_ZH, crs.sheet_prompt({"canonical_name": "A"}))
        self.assertNotIn(rs.LIVE_SKIN_FINISH_ZH, crs.sheet_prompt({"canonical_name": "A"}, render_style="anime"))
        self.assertIn(rs.LIVE_SKIN_FINISH_ZH, bkm.visual_culture_block({"profile_id": "P"}))
        self.assertNotIn(rs.LIVE_SKIN_FINISH_ZH, bkm.visual_culture_block({"profile_id": "P", "render_style": "anime"}))


if __name__ == "__main__":
    unittest.main()
