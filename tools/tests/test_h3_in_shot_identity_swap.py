"""In-shot identity swap + anime sheen (line owner 2026-11-20, JA-01 anime E01 on device 1485).

"The scene and camera angle don't change, but the character transforms in place into the one who is speaking":
a tail-started unit opens on the predecessor's real final frame (person A) while its first storyboard shot shows
the speaker B on screen.  The InsightFace start-frame check that rejects such a tail is NOT_APPLICABLE for anime, so
the tail was always accepted and the prompt told H3 that B is "already in @Image1".  Free fixes only:

* a declared-cast start-frame check (no image read) rejects the tail for anime / when the face check did not run;
* a hard continuation (always opens on the tail) records the mismatch as an advisory identity-swap risk;
* V2 prompts carry an identity-lock sentence; an off-screen speaker's plate says nobody on screen takes that face;
* anime units carry a matte cel-shading finish clause (skipped on wet beats), live action keeps its own clause;
* the final review / fix round route an in-shot transformation to the FACE_DRIFT redo.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines" / "nalu" / "runtime" / "tools"))
sys.path.insert(0, str(ROOT / "tools"))

import final_fix_round as ffr  # noqa: E402
import nalu_pipeline as npl  # noqa: E402
import nalu_qa_defect_checklist as qdc  # noqa: E402
from tools import h3_director_prompt_v2 as v2  # noqa: E402
from tools import h3_provider_prompt_renderer as h3v1  # noqa: E402
from tools.h3_provider_prompt_renderer import render_h3_prompt  # noqa: E402
from tools.tests.test_h3_director_prompt_v2 import A, B, fixture  # noqa: E402

ANIME_VCC = {"render_style": "anime"}


def _shot(shot_id, cast, dialogue=""):
    return {"shot_id": shot_id, "prompt_spec": {"dialogue": dialogue, "cast": cast}}


def _member(name, cid, face="FRONT"):
    return {"character": name, "character_id": cid, "face_visibility": face}


AKI, REN = _member("アキ", "CHAR-AKI"), _member("レン", "CHAR-REN")
EDITORIAL = {"shots": [
    _shot("E01-S01-01", [AKI], "アキ：行こう。"),
    _shot("E01-S01-02", [REN], "レン：待って。"),                       # speaker Ren, tail shows Aki only
    _shot("E01-S01-03", [REN, AKI], "レン：本当に？"),                  # Ren in a two-shot
    _shot("E01-S01-04", [AKI, _member("レン", "CHAR-REN", "OFFSCREEN_VOICE_ONLY")], "レン：ここだ。"),
]}
PLAN = {"units": [{"unit_id": "E01-VU-001", "editorial_shot_ids": ["E01-S01-01"]},
                  {"unit_id": "E01-VU-002", "editorial_shot_ids": ["E01-S01-02"]},
                  {"unit_id": "E01-VU-003", "editorial_shot_ids": ["E01-S01-03"]},
                  {"unit_id": "E01-VU-004", "editorial_shot_ids": ["E01-S01-04"]}]}


class TailCastCheckTest(unittest.TestCase):
    def test_on_screen_speaker_missing_from_tail_rejects(self):
        got = npl.tail_cast_mismatch(EDITORIAL, PLAN, "E01-VU-002", "E01-VU-001")
        self.assertEqual(got["verdict"], "REJECT")
        self.assertIn("ON_SCREEN_SPEAKER_NOT_IN_TAIL:CHAR-REN", got["reasons"])
        self.assertIn("TAIL_SHOWS_A_DIFFERENT_CAST", got["reasons"])

    def test_speaker_in_tail_accepts_and_off_unit_character_in_tail_rejects(self):
        # VU-003's tail (VU-002) shows Ren, who speaks in VU-003 (two-shot with Aki)
        self.assertEqual(npl.tail_cast_mismatch(EDITORIAL, PLAN, "E01-VU-003", "E01-VU-002")["verdict"], "ACCEPT")
        # VU-004: Ren speaks off screen over Aki; the VU-003 tail still shows Ren, who is not on screen here
        got = npl.tail_cast_mismatch(EDITORIAL, PLAN, "E01-VU-004", "E01-VU-003")
        self.assertEqual(got["reasons"], ["TAIL_SHOWS_OFF_UNIT_CHARACTER:CHAR-REN"])

    def test_missing_rows_never_reject(self):
        self.assertEqual(npl.tail_cast_mismatch(EDITORIAL, PLAN, "E01-VU-009", "E01-VU-001")["verdict"],
                         "NOT_MEASURED")

    def _ctx(self, d: Path, style: str):
        preprod = d / "preprod"
        preprod.mkdir()
        (preprod / "E01_VIDEO_UNIT_GROUPING_PLAN_V1.json").write_text(json.dumps(PLAN), encoding="utf-8")
        editorial = preprod / "E01_EDITORIAL_SEEDANCE_MANIFEST_V1.json"
        editorial.write_text(json.dumps(EDITORIAL, ensure_ascii=False), encoding="utf-8")
        return SimpleNamespace(render_style=style, episode="E01",
                               p=SimpleNamespace(preprod=preprod, editorial=editorial))

    def test_anime_tail_check_uses_the_declared_cast(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = self._ctx(Path(d), "anime")
            with mock.patch.object(npl, "qa_run") as run:
                bad = npl.check_tail_start_frame(ctx, "E01-VU-002", Path("tail.png"), "E01-VU-001")
                ok = npl.check_tail_start_frame(ctx, "E01-VU-003", Path("tail.png"), "E01-VU-002")
                run.assert_not_called()  # InsightFace never runs for anime
            self.assertEqual(bad["verdict"], "REJECT")
            self.assertEqual(bad["method"], npl.TAIL_CAST_METHOD)
            self.assertEqual((ok["verdict"], ok["status"]), ("ACCEPT", "NOT_APPLICABLE"))

    def test_live_action_declared_cast_decides_before_the_face_check(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = self._ctx(Path(d), "live_action")
            with mock.patch.object(npl, "qa_run") as run:
                got = npl.check_tail_start_frame(ctx, "E01-VU-002", Path("t.png"), "E01-VU-001")
                run.assert_not_called()
            self.assertEqual(got["verdict"], "REJECT")
            with mock.patch.object(npl, "qa_run", return_value={}), \
                    mock.patch.object(npl, "qa_json", return_value={"verdict": "ACCEPT", "status": "MEASURED"}):
                self.assertEqual(npl.check_tail_start_frame(ctx, "E01-VU-003", Path("t.png"), "E01-VU-002")["status"],
                                 "MEASURED")


class PlannerTailInvariantTest(unittest.TestCase):
    """Device 1485 JA-01 E01: motivated cuts in shot / reverse-shot dialogue were sent their own keyframe of Y plus the
    previous unit's tail of X; no unit may carry a predecessor tail showing someone not on screen in that unit."""

    @staticmethod
    def _grouping(tail: Path, casts: list[list[dict]]) -> tuple[dict, dict]:
        sys.path.insert(0, str(ROOT / "tools" / "tests"))
        from test_e51_pipeline_rectification import E51PipelineRectificationTests as E51
        state = E51._persistent_state()
        units, shots = [], []
        for index, cast in enumerate(casts, 1):
            sid = f"S{index}"
            unit = {"episode": "E54", "unit_id": f"E54-VU-00{index}", "scene_id": "E54-S01",
                    "editorial_shot_ids": [sid], "persistent_state_contract": state,
                    "camera_plan": {"shot_scale": "MEDIUM", "camera_side": f"AXIS_{index}"}}
            if index > 1:
                unit["previous_unit_final_frame"] = {"path": str(tail.with_name(f"E54-VU-00{index - 1}.png")),
                                                     "sha256": "abc"}
            units.append(unit)
            shots.append({"shot_id": sid, "scene_id": "E54-S01", "prompt_spec": {"cast": cast}})
        return {"episode": "E54", "units": units}, {"shots": shots}

    def _build(self, casts):
        from tools import build_video_unit_anchor_plan as bva

        def boundary(prev, unit):
            if prev is None:
                return {"status": "PASS", "boundary_class": "NEW_EVENT_ANCHOR", "previous_unit_id": None}
            return {"status": "PASS", "boundary_class": "MOTIVATED_CUT", "previous_unit_id": prev["unit_id"],
                    "same_continuous_event": True}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(bva, "classify_boundary", boundary), \
                mock.patch.object(bva, "compile_internal_shot_boundaries", lambda _u: {"status": "PASS"}), \
                mock.patch.object(bva.unit_action_continuity_contract, "evaluate", lambda *_a: {"status": "PASS"}):
            for index in range(1, len(casts) + 1):
                Path(tmp, f"S{index}-keyframe-v1.png").touch()
            return bva.build(*self._grouping(Path(tmp) / "tail.png", casts), Path(tmp))

    def test_shot_reverse_shot_never_carries_the_other_characters_tail(self):
        from tools.video_unit_anchor_count_gate import evaluate
        plan = self._build([[AKI], [REN], [AKI], [AKI]])
        by_id = {u["unit_id"]: u for u in plan["units"]}
        for uid in ("E54-VU-002", "E54-VU-003"):  # reverse shots: the tail shows the other character
            unit = by_id[uid]
            self.assertFalse(any(p.endswith(".png") and "E54-VU-00" in Path(p).name
                                 for p in unit["reference_image_paths"]), unit["reference_image_paths"])
            contract = unit["opening_anchor_contract"]
            self.assertEqual(contract["start_frame_source"], "OWN_KEYFRAME_TAIL_REJECTED")
            self.assertEqual(contract["previous_state_reference_transport"], "NOT_TRANSPORTED_TAIL_REJECTED")
            self.assertEqual(contract["tail_rejected_reason"], "PREVIOUS_TAIL_SHOWS_OFF_UNIT_CHARACTER")
        # same character on both sides of the cut: the tail stays the state reference
        self.assertIn("PREVIOUS_REAL_TAIL_STATE_AUTHORITY", by_id["E54-VU-004"]["anchor_count_decision"]["anchor_roles"])
        self.assertEqual(evaluate(plan)["status"], "PASS")

    def test_invariant_over_every_unit(self):
        from tools import build_video_unit_anchor_plan as bva
        casts = [[AKI], [REN], [REN, AKI], [AKI], [REN]]
        plan = self._build(casts)
        names = [{m["character"] for m in cast} for cast in casts]
        for index, unit in enumerate(plan["units"][1:], 1):
            tail_name = f"E54-VU-00{index}.png"
            if any(Path(p).name == tail_name for p in unit["reference_image_paths"]):
                self.assertTrue(names[index - 1] <= names[index], (unit["unit_id"], names[index - 1], names[index]))
        self.assertEqual(bva.tail_cast_conflict([{"prompt_spec": {"cast": [AKI]}}], [{"prompt_spec": {"cast": [AKI, REN]}}]), [])


class DirectorPromptIdentityLockTest(unittest.TestCase):
    def test_identity_lock_sentence_present(self):
        text, receipt = render_h3_prompt(*fixture())
        self.assertEqual(receipt["status"], "PASS")
        self.assertIn(v2.IDENTITY_LOCK_V2, text)
        self.assertLess(text.index(v2.IDENTITY_LOCK_V2), text.index("\n\nWho is in frame"))

    def test_offscreen_plate_forbids_taking_that_face(self):
        unit, plan = fixture()
        unit = deepcopy(unit)
        for member in unit["ordered_prompt_specs"][0]["cast"]:
            if str(member.get("character_id")) == B:
                member["face_visibility"] = "OFFSCREEN_VOICE_ONLY"
        lines = v2._reference_lines(unit, plan, onscreen={A}, people=1, beings=0, exact_first_frame=True)
        beta = next(line for line in lines if line.startswith("@Image3"))
        self.assertIn("stays out of frame in this clip; nobody on screen takes on Beta's face, hair or outfit.", beta)

    def test_no_identity_lock_without_identity_references(self):
        unit, plan = fixture()
        unit["reference_images"] = unit["reference_images"][:1]
        unit["provider_scope_projection"]["reference_identity_bindings"] = []
        try:
            text, _ = render_h3_prompt(unit, plan)
        except ValueError:
            self.skipTest("fixture needs identity references to render")
        self.assertNotIn(v2.IDENTITY_LOCK_V2, text)


class AnimeFinishClauseTest(unittest.TestCase):
    def test_anime_v2_carries_the_matte_cel_clause_and_not_the_live_action_one(self):
        unit, plan = fixture()
        unit["visual_culture_contract"] = {**(unit.get("visual_culture_contract") or {}), **ANIME_VCC}
        text, receipt = render_h3_prompt(unit, plan)
        self.assertEqual(receipt["status"], "PASS")
        self.assertIn(v2.ANIME_FINISH_NEVER, text)
        self.assertNotIn(v2.SKIN_FINISH_NEVER, text)

    def test_live_action_v2_keeps_its_own_clause(self):
        text, _ = render_h3_prompt(*fixture())
        self.assertIn(v2.SKIN_FINISH_NEVER, text)
        self.assertNotIn(v2.ANIME_FINISH_NEVER, text)

    def test_wet_beat_skips_the_anime_clause(self):
        unit, plan = fixture()
        unit["visual_culture_contract"] = {**(unit.get("visual_culture_contract") or {}), **ANIME_VCC}
        unit["h3_provider_english_contract"]["space_weather_fact"] += "; heavy rain"
        self.assertFalse(h3v1.anime_finish_applies(unit, plan, anime=True, has_people=True))
        text, _ = render_h3_prompt(unit, plan)
        self.assertNotIn(v2.ANIME_FINISH_NEVER, text)

    def test_anime_v1_negative(self):
        unit, plan = fixture(style=False)
        unit["visual_culture_contract"] = {**(unit.get("visual_culture_contract") or {}), **ANIME_VCC}
        text, _ = render_h3_prompt(unit, plan)
        self.assertIn(h3v1.ANIME_FINISH_NEGATIVE, text)
        self.assertNotIn(h3v1.SKIN_FINISH_NEGATIVE, text)
        self.assertFalse(h3v1.anime_finish_applies(unit, plan, anime=False, has_people=True))


class IdentitySwapDetectionTest(unittest.TestCase):
    def test_hard_continuation_records_an_advisory_risk_and_still_materialises(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            preprod = d / "preprod"
            (preprod / "real_final_frames").mkdir(parents=True)
            (preprod / "keyframes").mkdir()
            (preprod / "real_final_frames" / "E01-VU-001.png").write_bytes(b"tail of aki")
            (preprod / "E01_VIDEO_UNIT_GROUPING_PLAN_V1.json").write_text(json.dumps(PLAN), encoding="utf-8")
            (preprod / "E01_VIDEO_UNIT_ANCHOR_PLAN_V1.json").write_text(json.dumps({"units": [
                {"unit_id": "E01-VU-002", "opening_anchor_contract": {
                    "source": "PREVIOUS_UNIT_REAL_FINAL_FRAME", "previous_unit_id": "E01-VU-001"}}]}),
                encoding="utf-8")
            editorial = preprod / "E01_EDITORIAL_SEEDANCE_MANIFEST_V1.json"
            editorial.write_text(json.dumps(EDITORIAL, ensure_ascii=False), encoding="utf-8")
            said = []
            ctx = SimpleNamespace(episode="E01", dry=False, run_id="R", render_style="anime", say=said.append,
                                  p=SimpleNamespace(preprod=preprod, preprod_reports=preprod / "reports",
                                                    editorial=editorial, contract=d / "contract.json",
                                                    video_media=d / "video", keyframes=preprod / "keyframes"))
            with mock.patch.object(npl, "_camera_grammar_on", return_value=True), \
                    mock.patch.object(npl, "check_tail_start_frame",
                                      side_effect=AssertionError("a hard continuation never switches frames")):
                rows = npl.materialise_derived_keyframes(ctx)
            self.assertEqual(rows[0]["status"], "MATERIALISED")
            side = json.loads((preprod / "keyframes" / "E01-S01-02-keyframe-v1.derived.json").read_text())
            self.assertIn("ON_SCREEN_SPEAKER_NOT_IN_TAIL:CHAR-REN", side["identity_swap_risk"]["reasons"])
            self.assertTrue(any("identity-swap risk" in line for line in said))
            measured = qdc.measure(shots=[], keyframes_dir=preprod / "keyframes")
            self.assertEqual(measured["identity_swap_risk"]["units"][0]["unit_id"], "E01-VU-002")
            self.assertEqual(qdc.MEASUREMENT_ITEM["identity_swap_risk"], "QA-LOOKALIKE-CAST")

    def test_in_shot_transformation_is_a_face_drift_redo(self):
        self.assertEqual(ffr.classify_text("at 12s the girl morphs into Ren while he speaks"), "FACE_DRIFT")
        self.assertEqual(ffr.classify_text("画面里的人变成另一个角色"), "FACE_DRIFT")
        self.assertEqual(ffr.classify("QA-LOOKALIKE-CAST", "Aki turns into another character mid-shot"),
                         "FACE_DRIFT")
        self.assertEqual(ffr.classify("QA-LOOKALIKE-CAST", "Aki and Mio look alike"), "LOOKALIKE")


if __name__ == "__main__":
    unittest.main()
