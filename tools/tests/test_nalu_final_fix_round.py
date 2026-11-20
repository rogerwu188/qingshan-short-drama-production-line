#!/usr/bin/env python3
"""Final fix round + S8 never waits for the owner on quality (line owner 2026-11-20: 「不要等我了，我自己看不过来」).

Offline: no provider, no credits, no media tools.  Covers the finding -> fix-class mapping, the paid budget cap and
priority, one round only (the second verdict never loops), the S8 engine approval and the opt-in owner wait, the
NO_PLATFORM_PUBLICATION scope, the zero-defect passthrough, the redo prompt sentence and the receipt / env knobs.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, REPO / "tools", REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import bgm_cue_shaping as bcs  # noqa: E402
import build_nalu_preproduction as bnp  # noqa: E402
import dialogue_tail_guard as dtg  # noqa: E402
import final_fix_round as ffr  # noqa: E402
import nalu_pipeline as P  # noqa: E402
from tools import h3_provider_prompt_renderer as h3  # noqa: E402
from tools.h3_provider_english_contract import validate_h3_provider_text_boundary  # noqa: E402
from tools.tests.test_h3_director_performance import unit_plan  # noqa: E402
from tools.tests.test_h3_director_prompt_v2 import fixture  # noqa: E402

SEGMENTS = [{"unit_id": "E01-VU-001", "output_start": 0.0, "output_end": 5.0},
            {"unit_id": "E01-VU-002", "output_start": 5.0, "output_end": 12.0},
            {"unit_id": "E01-VU-003", "output_start": 12.0, "output_end": 16.0},
            {"unit_id": "E01-VU-004", "output_start": 16.0, "output_end": 24.0}]


def checklist(defects: dict[str, list[dict]] | None = None, gemini: list[dict] | None = None, sha: str = "") -> dict:
    items = {iid: {"status": "DEFECT" if iid in (defects or {}) else "PASS",
                   "reviewer_findings": (defects or {}).get(iid, [])} for iid in
             ("QA-BURNED-TEXT", "QA-DIALOGUE-TAIL-CUT", "QA-OVERSIZED-MASK", "QA-LOOKALIKE-CAST",
              "QA-SUBTITLE-WRAP", "QA-BGM-DISCONTINUOUS")}
    out = {"items": items, "bindings": {"final_video_sha256": sha} if sha else {}}
    if gemini is not None:
        out["video_review"] = {"findings": gemini}
    return out


# --------------------------------------------------------------------------------------------- mapping
class MappingTest(unittest.TestCase):
    def test_items_and_text_map_to_classes(self):
        cases = {
            ("QA-BURNED-TEXT", ""): ("BURNED_TEXT", ffr.PAID),
            ("QA-DIALOGUE-TAIL-CUT", ""): ("DIALOGUE_TAIL_GUARD", ffr.FREE),
            ("QA-SUBTITLE-WRAP", ""): ("SUBTITLE_WRAP", ffr.FREE),
            ("QA-BGM-DISCONTINUOUS", ""): ("BGM_FADES", ffr.FREE),
            ("QA-OVERSIZED-MASK", ""): ("MASK", ffr.RECORD),
            ("QA-LOOKALIKE-CAST", ""): ("LOOKALIKE", ffr.RECORD),
            ("LETTERBOX", ""): ("LETTERBOX", ffr.RECORD),
            ("LOOK-DRIFT", "her robe turns from blue to red"): ("COSTUME_IDENTITY", ffr.PAID),
            ("LOOK-DRIFT", "his face changes between shots"): ("FACE_DRIFT", ffr.PAID),
            (None, "Static shot held too long on the empty hall"): ("STATIC_SHOT_SPLIT", ffr.FREE),
            (None, "audio bed RMS jumps at the cut, loudness window too hot"): ("AUDIO_SMOOTHING", ffr.FREE),
            (None, "背景音乐在切点生硬停止"): ("BGM_FADES", ffr.FREE),
            (None, "画面里烧进去一行字幕"): ("BURNED_TEXT", ffr.PAID),
            (None, "主角服装颜色不一致"): ("COSTUME_IDENTITY", ffr.PAID),
            (None, "wrong face on the guard in this shot"): ("FACE_DRIFT", ffr.PAID),
            (None, "pacing is slow in the middle act"): ("PACING", ffr.RECORD),
            (None, "the plot motivation is unclear"): ("STORY", ffr.RECORD),
            (None, "episode is too short for the brief"): ("LENGTH", ffr.RECORD),
            (None, "two characters share one voice"): ("VOICE", ffr.RECORD),
            (None, "lip movement does not match the line"): ("ASR_MISMATCH", ffr.RECORD),
            (None, "the two sisters look alike"): ("LOOKALIKE", ffr.RECORD),
            (None, "something odd"): ("OTHER", ffr.RECORD),
        }
        for (item, text), (kind, klass) in cases.items():
            got = ffr.classify(item, text)
            self.assertEqual((got, ffr.fix_class(got)), (kind, klass), (item, text))

    def test_collect_only_confirmed_and_map_units(self):
        cl = checklist({"QA-BURNED-TEXT": [{"note": "stray 能", "at_seconds": 6.0}]}, gemini=[
            {"id": "G1", "item": "QA-BURNED-TEXT", "window": [5.5, 6.5], "status": "CONFIRMED"},  # dup of reviewer
            {"id": "G2", "item": "LOOK-DRIFT", "window": [17.0, 18.0], "status": "CONFIRMED", "note": "robe colour"},
            {"id": "G3", "item": "QA-BGM-DISCONTINUOUS", "window": [1, 2], "status": "DISMISSED"},
            {"id": "G4", "item": "OTHER", "window": [3, 4], "status": "UNVERIFIED"}])
        cl["items"]["QA-SUBTITLE-WRAP"]["status"] = "MEASURED_FLAG_UNREVIEWED"  # never a confirmed finding
        report = {"problems": [{"severity": "P1", "at_seconds": 13.0, "issue": "face drift on the maid",
                                "fix": "redo"}], "hard_fail": ["identity_color_mismatch"]}
        mapped = ffr.map_findings(ffr.collect_findings(report, cl), SEGMENTS)
        rows = [(f["source"], f["kind"], f.get("unit_id")) for f in mapped]
        self.assertEqual(rows, [("QA_CHECKLIST_REVIEWER", "BURNED_TEXT", "E01-VU-002"),
                                ("GEMINI_CONFIRMED", "COSTUME_IDENTITY", "E01-VU-004"),
                                ("REVIEW_PROBLEM", "FACE_DRIFT", "E01-VU-003"),
                                ("REVIEW_HARD_FAIL", "COSTUME_IDENTITY", None)])
        self.assertEqual(mapped[0]["on_screen_seconds"], 7.0)

    def test_trigger_rules(self):
        problem_only = ffr.map_findings(ffr.collect_findings(
            {"problems": [{"issue": "music stops abruptly", "fix": "fade", "at_seconds": 1}]}, {}), SEGMENTS)
        self.assertFalse(ffr.triggered(False, problem_only))            # PASS with listed problems: no round
        self.assertTrue(ffr.needs_round(True, problem_only))             # REJECT: round (free fix)
        pacing = ffr.map_findings(ffr.collect_findings({"problems": [{"issue": "pacing slow", "fix": "tighten"}]},
                                                       {}), SEGMENTS)
        self.assertFalse(ffr.needs_round(True, pacing))                 # record-only: nothing to act on
        defect = ffr.map_findings(ffr.collect_findings({}, checklist(
            {"QA-BGM-DISCONTINUOUS": [{"window": [1, 2]}]})), SEGMENTS)
        self.assertTrue(ffr.needs_round(False, defect))                 # PASS + confirmed DEFECT: round


# ------------------------------------------------------------------------------------------ budget plan
class BudgetPlanTest(unittest.TestCase):
    def mapped(self):
        return [
            {"class": ffr.PAID, "kind": "FACE_DRIFT", "unit_id": "U1", "on_screen_seconds": 8.0},
            {"class": ffr.PAID, "kind": "COSTUME_IDENTITY", "unit_id": "U2", "on_screen_seconds": 4.0},
            {"class": ffr.PAID, "kind": "BURNED_TEXT", "unit_id": "U3", "on_screen_seconds": 3.0},
            {"class": ffr.PAID, "kind": "BURNED_TEXT", "unit_id": "U4", "on_screen_seconds": 6.0},
            {"class": ffr.PAID, "kind": "COSTUME_IDENTITY", "unit_id": "U5", "on_screen_seconds": 9.0},
            {"class": ffr.PAID, "kind": "FACE_DRIFT", "unit_id": "U4", "on_screen_seconds": 6.0},  # same unit
            {"class": ffr.PAID, "kind": "BURNED_TEXT"},                                            # no unit
            {"class": ffr.FREE, "kind": "BGM_FADES"},
        ]

    def test_priority_and_cap(self):
        plan = ffr.plan_paid(self.mapped(), budget=45, headroom=1000, unit_cost=lambda _u: 10)
        self.assertEqual([r["unit_id"] for r in plan["selected"]], ["U4", "U3", "U5", "U2"])
        self.assertEqual(plan["selected"][0]["kinds"], ["BURNED_TEXT", "FACE_DRIFT"])  # one redo per unit
        self.assertEqual(plan["planned_credits"], 40)
        skipped = {r.get("unit_id"): r["reason"] for r in plan["skipped"]}
        self.assertEqual(skipped, {"U1": "BUDGET_CAP", None: "NO_UNIT_FOR_FINDING"})

    def test_headroom_and_env_cap(self):
        plan = ffr.plan_paid(self.mapped(), budget=45, headroom=15, unit_cost=lambda _u: 10)
        self.assertEqual([r["unit_id"] for r in plan["selected"]], ["U4"])
        self.assertEqual(ffr.budget_credits({}), 45)
        self.assertEqual(ffr.budget_credits({"NALU_FINAL_FIX_BUDGET_CREDITS": "20"}), 20)
        plan = ffr.plan_paid(self.mapped(), budget=ffr.budget_credits({"NALU_FINAL_FIX_BUDGET_CREDITS": "20"}),
                             headroom=None, unit_cost=lambda u: 12 if u == "U4" else 8)
        self.assertEqual([r["unit_id"] for r in plan["selected"]], ["U4", "U3"])  # cheaper U3 still fits

    def test_eligibility_skips(self):
        plan = ffr.plan_paid(self.mapped(), budget=45, headroom=100, unit_cost=lambda _u: 5,
                             eligible=lambda u: "CLIP_NOT_ON_DISK" if u == "U4" else None)
        self.assertNotIn("U4", [r["unit_id"] for r in plan["selected"]])

    def test_rounds_env_never_more_than_one(self):
        self.assertEqual(ffr.rounds({}), 1)
        self.assertEqual(ffr.rounds({"NALU_FINAL_FIX_ROUNDS": "0"}), 0)
        self.assertEqual(ffr.rounds({"NALU_FINAL_FIX_ROUNDS": "3"}), 1)


# ------------------------------------------------------------------------------------ free fix helpers
class FreeFixTest(unittest.TestCase):
    def test_settings_keep_operator_env(self):
        got = ffr.free_settings(["BGM_FADES", "DIALOGUE_TAIL_GUARD", "STATIC_SHOT_SPLIT"],
                                {"NALU_BGM_MIN_CUE_SECONDS": "20"})
        self.assertEqual(got["env"], {"NALU_BGM_FADE_SCALE": "1.6", "NALU_S7_TAIL_GUARD_SECONDS": "0.4",
                                      "NALU_S7_POST_LINE_BEAT_SECONDS": "0.7"})
        self.assertEqual(got["kept_operator_env"], ["NALU_BGM_MIN_CUE_SECONDS"])

    def test_static_split_cutaway_then_punch_in(self):
        got = ffr.static_shot_segments("A", (0.5, 6.5), neighbours=[{"unit_id": "B", "unused": [(0.0, 0.3), (4.0, 6.0)]}])
        self.assertEqual((got["method"], got["borrowed_from"]), ("CUTAWAY", "B"))
        segs = got["segments"]
        self.assertEqual(segs[1]["video"][0], "B")
        self.assertEqual(segs[1]["audio"][0], "A")                       # the unit's own sound runs on
        total = sum(s["video"][2] - s["video"][1] for s in segs)
        self.assertAlmostEqual(total, 6.0, places=3)                     # duration and timing unchanged
        self.assertEqual(segs[0]["audio"][1:], [0.5, segs[0]["audio"][2]])
        got = ffr.static_shot_segments("A", (0.0, 6.0), neighbours=[{"unit_id": "B", "unused": [(0.0, 0.5)]}])
        self.assertEqual(got["method"], "PUNCH_IN")
        self.assertEqual(got["segments"][1]["reframe"], ffr.PUNCH_IN_FRAME)
        self.assertEqual(ffr.static_shot_segments("A", (0.0, 3.0), neighbours=[])["status"], "TOO_SHORT_TO_SPLIT")
        import unit_recut
        self.assertEqual(unit_recut.validate_segments("A", got["segments"]), [])

    def test_tool_knobs_default_unchanged(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NALU_S7_TAIL_GUARD_SECONDS", None)
            os.environ.pop("NALU_BGM_FADE_SCALE", None)
            self.assertEqual(dtg.guard(1.0)["guard"], 1.25)
            self.assertEqual(bcs.fade_scale(), 1.0)
            os.environ["NALU_S7_TAIL_GUARD_SECONDS"] = "0.4"
            os.environ["NALU_BGM_FADE_SCALE"] = "1.6"
            self.assertEqual(dtg.guard(1.0)["guard"], 1.4)
            self.assertEqual(bcs.fade_scale(), 1.6)
            os.environ.pop("NALU_S7_TAIL_GUARD_SECONDS")
            os.environ.pop("NALU_BGM_FADE_SCALE")
        with mock.patch.dict(os.environ, {"NALU_S7_CUT_CROSSFADE_SECONDS": "0.16"}):
            self.assertEqual(P.s7_cut_crossfade_seconds(0.08), 0.16)
        self.assertEqual(P.s7_cut_crossfade_seconds(0.08), 0.08)


# --------------------------------------------------------------------------------------- redo sentence
class RedoSentenceTest(unittest.TestCase):
    def test_costume_pin_from_identity_card(self):
        rows = [{"character_id": "CHAR-A", "character": "Lin Yue", "primary_color": "pale blue",
                 "outer_layer": "silk robe"},
                {"character_id": "CHAR-B", "character": "林月", "primary_color": "红色"}]
        text = ffr.redo_sentence(["COSTUME_IDENTITY"], wardrobe_rows=rows, character_ids=["CHAR-A", "CHAR-B"])
        self.assertIn("Lin Yue in pale blue silk robe", text)
        self.assertNotIn("红", text)
        self.assertEqual(ffr.costume_sentence([{"character": "林月", "primary_color": "红色"}]),
                         ffr.SENTENCES["COSTUME_IDENTITY"])
        self.assertTrue(ffr.redo_sentence(["FACE_DRIFT", "BURNED_TEXT"]).startswith(ffr.SENTENCES["BURNED_TEXT"]))

    def test_renderer_appends_and_strips_exactly(self):
        for make in (lambda: unit_plan(stamped=True, performance=None), lambda: fixture()):
            base, _ = h3.render_h3_prompt(*make())
            for kinds in (["BURNED_TEXT"], ["COSTUME_IDENTITY"], ["FACE_DRIFT"]):
                sentence = ffr.redo_sentence(kinds)
                unit, plan = make()
                unit["h3_final_fix"] = {"round": 1, "kind": kinds[0], "kinds": kinds, "sentence": sentence}
                text, receipt = h3.render_h3_prompt(unit, plan)
                self.assertEqual(receipt["h3_final_fix"]["sentence"], sentence, kinds)
                self.assertTrue(text.rstrip("\n").endswith(sentence))
                self.assertEqual(ffr.strip_sentence(text, sentence), (base, True))
                self.assertEqual(validate_h3_provider_text_boundary(text, source_id="T")["status"], "PASS")
            unit, plan = make()
            unit["h3_burn_retry"] = 1
            unit["h3_final_fix"] = {"round": 1, "kind": "BURNED_TEXT", "sentence": ffr.SENTENCES["BURNED_TEXT"]}
            text, _ = h3.render_h3_prompt(unit, plan)
            self.assertTrue(text.rstrip("\n").endswith(ffr.SENTENCES["BURNED_TEXT"]))  # after the retry sentence
            unit, plan = make()
            self.assertEqual(h3.render_h3_prompt(unit, plan)[0], base)  # absent field: byte-identical

    def test_field_transport_and_compile_read(self):
        from tools.submit_giggle_video_manifest_v2 import _final_fix_round, provider_prompt_unit
        fix = {"round": 1, "kind": "BURNED_TEXT", "sentence": "x"}
        with mock.patch("tools.submit_giggle_video_manifest_v2.grouped_sequence_unit", lambda _t: {}):
            self.assertEqual(provider_prompt_unit({"h3_final_fix": fix}).get("h3_final_fix"), fix)
            self.assertNotIn("h3_final_fix", provider_prompt_unit({}))
        self.assertEqual((_final_fix_round({"h3_final_fix": fix}), _final_fix_round({})), (1, 0))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "reports").mkdir()
            (out / "reports" / "E01_FINAL_FIX_REDO.json").write_text(json.dumps(
                {"units": {"E01-VU-002": {"round": 1, "kind": "BURNED_TEXT", "kinds": ["BURNED_TEXT"],
                                          "sentence": "s"}}}), encoding="utf-8")
            self.assertEqual(bnp.final_fix_redo_fields(out, "E01"),
                             {"E01-VU-002": {"round": 1, "kind": "BURNED_TEXT", "kinds": ["BURNED_TEXT"],
                                             "sentence": "s"}})
            self.assertEqual(bnp.final_fix_redo_fields(out, "E02"), {})


# ------------------------------------------------------------------------------ the S7 round + S8 approve
class _Ctx(SimpleNamespace):
    def stage_state(self, sid):
        return self.state.setdefault("stages", {}).setdefault(sid, {})

    def save_state(self):
        self.saved = getattr(self, "saved", 0) + 1

    def say(self, line):
        self.lines.append(str(line))

    def budget_check(self, _planned, *, label):
        return {"budget_verdict": {"headroom_credits": self.headroom}}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RoundTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        p = SimpleNamespace(
            assembly=root / "assembly", video_media=root / "video", preprod_reports=root / "reports",
            preprod=root / "pre", final_candidate=root / "assembly" / "E01_final_candidate_9x16.mp4",
            video_transaction=root / "pre" / "tx.json", agentcut_project=root / "assembly" / "proj.json",
            grouping_plan=root / "pre" / "grouping.json", editorial=root / "pre" / "editorial.json",
            final_mp4=root / "deliver" / "E01_final_9x16.mp4", approval=root / "approvals" / "E01.APPROVED.json",
            checkpoint=root / "deliver" / "CHECKPOINT.md", deliver=root / "deliver")
        for d in (p.assembly / "final_qa", p.video_media, p.preprod_reports, p.preprod):
            d.mkdir(parents=True, exist_ok=True)
        for i in range(1, 5):
            (p.video_media / f"E01-VU-00{i}.mp4").write_bytes(f"clip{i}".encode())
        (p.assembly / "E01_release_timeline.json").write_text(json.dumps({"segments": SEGMENTS}), encoding="utf-8")
        p.final_candidate.write_bytes(b"cut-1")
        self.p = p
        self.ctx = _Ctx(episode="E01", p=p, run_id="RUN1", state={}, lines=[], headroom=500, dry=False,
                        config={}, paid_order=None, authority={})
        self.patches = [mock.patch.object(P, "episode_video_model", return_value="MiniMax-H3"),
                        mock.patch.object(P, "episode_video_resolution", return_value="768p"),
                        mock.patch.object(P, "video_task_credits", return_value=10),
                        mock.patch.object(P, "credits_summary", side_effect=lambda _c: {"recorded_total_credits": self.spent}),
                        mock.patch.object(P, "REVIEWS_ROOT", root / "reviews"),
                        mock.patch.object(P, "_probe_seconds", return_value=8.0),
                        mock.patch.dict(os.environ, {}, clear=False)]
        self.spent = 100.0
        for patch in self.patches:
            patch.start()
        for name in ("NALU_FINAL_FIX_ROUNDS", "NALU_FINAL_FIX_BUDGET_CREDITS"):
            os.environ.pop(name, None)

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def review(self, *, report: dict, cl: dict | None = None) -> dict:
        final_qa = self.p.assembly / "final_qa"
        (final_qa / "E01_AUDIENCE_SCORE_REPORT.json").write_text(json.dumps(report), encoding="utf-8")
        if cl is not None:
            (final_qa / "E01_QA_DEFECT_CHECKLIST.json").write_text(json.dumps(cl), encoding="utf-8")
        return {"report": str(final_qa / "E01_AUDIENCE_SCORE_REPORT.json"),
                "final_video_sha256": sha(self.p.final_candidate)}

    def record(self) -> dict:
        return json.loads((self.p.assembly / "final_qa" / "final_fix_round.json").read_text(encoding="utf-8"))

    def test_zero_defect_passthrough(self):
        out = P.s7_final_fix_round(self.ctx, None, self.review(report={"problems": []}, cl=checklist()), False)
        self.assertEqual(out["action"], "PROCEED")
        self.assertEqual(self.record()["status"], "NOT_NEEDED")
        self.assertFalse(any("FINAL_FIX_ROUND_START" in line for line in self.ctx.lines))
        self.assertFalse((self.p.assembly / "E01_FINAL_FIX_S7_SETTINGS.json").exists())

    def test_disabled(self):
        os.environ["NALU_FINAL_FIX_ROUNDS"] = "0"
        out = P.s7_final_fix_round(self.ctx, None, self.review(report={"problems": [
            {"issue": "music stops abruptly", "fix": "fade", "at_seconds": 2}]}), True)
        self.assertEqual((out["action"], self.record()["status"]), ("PROCEED", "DISABLED"))

    def test_record_only_reject_proceeds_without_second_review(self):
        out = P.s7_final_fix_round(self.ctx, None, self.review(report={"problems": [
            {"issue": "pacing drags", "fix": "tighten the story", "at_seconds": 2}]}), True)
        self.assertEqual((out["action"], self.record()["status"]), ("PROCEED", "NO_ACTIONABLE_FIX"))
        self.assertEqual(self.record()["unresolved"][0]["state"], "RECORD_ONLY")

    def test_free_round_then_second_review_never_loops(self):
        fa = self.review(report={"problems": [{"issue": "music starts abruptly at the cut", "fix": "fade in",
                                               "at_seconds": 6}]},
                         cl=checklist({"QA-DIALOGUE-TAIL-CUT": [{"at_seconds": 13.0}]}))
        out = P.s7_final_fix_round(self.ctx, None, fa, True)
        self.assertEqual(out["action"], "S7_RERUN")
        settings = json.loads((self.p.assembly / "E01_FINAL_FIX_S7_SETTINGS.json").read_text(encoding="utf-8"))
        self.assertEqual(settings["env"]["NALU_BGM_FADE_SCALE"], "1.6")
        self.assertEqual(settings["env"]["NALU_S7_TAIL_GUARD_SECONDS"], "0.4")
        self.assertTrue(any(l.startswith("FINAL_FIX_ROUND_START") for l in self.ctx.lines))
        self.assertTrue(any(l.startswith("FINAL_FIX_FREE_RECUT kind=BGM_FADES") for l in self.ctx.lines))
        self.assertTrue((self.p.assembly / "final_qa" / "final_fix_round" / "first_review"
                         / "E01_AUDIENCE_SCORE_REPORT.json").is_file())
        # the settings are applied to the S7 pass and bound into the candidate bindings
        os.environ.pop("NALU_BGM_FADE_SCALE", None)
        with P._final_fix_env(self.ctx) as applied:
            self.assertEqual(os.environ.get("NALU_BGM_FADE_SCALE"), "1.6")
        self.assertIn("NALU_BGM_FADE_SCALE", applied)
        self.assertIsNone(os.environ.get("NALU_BGM_FADE_SCALE"))
        # second review (new cut) rejects again: DONE, proceed, never another round
        self.p.final_candidate.write_bytes(b"cut-2")
        self.spent = 101.5
        second = self.review(report={"problems": [{"issue": "music starts abruptly", "fix": "f", "at_seconds": 6}]})
        out = P.s7_final_fix_round(self.ctx, None, second, True)
        self.assertEqual(out["action"], "PROCEED")
        rec = self.record()
        self.assertEqual((rec["status"], rec["second_review"]["verdict"], rec["credits_spent"]),
                         ("DONE", "REJECT_RECUT", 1.5))
        self.assertTrue(any(l.startswith("FINAL_FIX_ROUND_DONE verdict=REJECT_RECUT") for l in self.ctx.lines))
        self.p.final_candidate.write_bytes(b"cut-3")
        out = P.s7_final_fix_round(self.ctx, None, self.review(report={"problems": []}), True)
        self.assertEqual(out["action"], "PROCEED")
        self.assertEqual(self.record()["second_review"]["final_video_sha256"], hashlib.sha256(b"cut-2").hexdigest())

    def test_paid_redo_parks_reopens_s6_and_waits(self):
        fa = self.review(report={"problems": []}, cl=checklist({"QA-BURNED-TEXT": [{"at_seconds": 6.0}]}))
        self.ctx.stage_state("S6")["status"] = "PASS"
        out = P.s7_final_fix_round(self.ctx, None, fa, False)  # PASS verdict + confirmed DEFECT triggers too
        self.assertEqual((out["action"], out["units"]), ("S6_REDO_PENDING", ["E01-VU-002"]))
        self.assertFalse((self.p.video_media / "E01-VU-002.mp4").exists())
        self.assertTrue((self.p.video_media / "_superseded_RUN1_final_fix" / "E01-VU-002.mp4").is_file())
        redo = json.loads((self.p.preprod_reports / "E01_FINAL_FIX_REDO.json").read_text(encoding="utf-8"))
        self.assertEqual(redo["units"]["E01-VU-002"]["sentence"], ffr.SENTENCES["BURNED_TEXT"])
        self.assertEqual(self.ctx.stage_state("S6")["status"], "REOPENED_FINAL_FIX")
        self.assertEqual(P.final_fix_redo_pending(self.ctx), ["E01-VU-002"])
        self.assertTrue(any(l.startswith("FINAL_FIX_UNIT_REDO unit=E01-VU-002") for l in self.ctx.lines))
        # S7 entered before S6 landed the redo: it names the paid command and stops
        res = P.stage_s7(self.ctx)
        self.assertEqual(res.blockers, ["FINAL_FIX_ROUND_S6_REDO_PENDING:E01-VU-002"])
        self.assertIn("paid_stage.sh E01 S6 S8", res.details["final_fix_round"]["next"])
        # the redo landed, the new cut was reviewed (PASS): done, one redo, never another
        (self.p.video_media / "E01-VU-002.mp4").write_bytes(b"redo")
        self.p.final_candidate.write_bytes(b"cut-2")
        out = P.s7_final_fix_round(self.ctx, None, self.review(report={"problems": []}), False)
        rec = self.record()
        self.assertEqual((out["action"], rec["status"], rec["second_review"]["verdict"]), ("PROCEED", "DONE", "PASS"))
        self.assertEqual(rec["paid"]["planned_credits"], 10)

    def test_paid_cap_and_ineligible_model(self):
        cl = checklist({"QA-BURNED-TEXT": [{"at_seconds": 1.0}, {"at_seconds": 6.0}, {"at_seconds": 13.0},
                                           {"at_seconds": 20.0}, {"at_seconds": 18.0}]})
        os.environ["NALU_FINAL_FIX_BUDGET_CREDITS"] = "25"
        P.s7_final_fix_round(self.ctx, None, self.review(report={}, cl=cl), True)
        rec = self.record()
        self.assertEqual([r["unit_id"] for r in rec["paid"]["selected"]], ["E01-VU-004", "E01-VU-002"])  # longest
        self.assertEqual({r["unit_id"]: r["reason"] for r in rec["paid"]["skipped"]},
                         {"E01-VU-001": "BUDGET_CAP", "E01-VU-003": "BUDGET_CAP"})

    def test_paid_needs_h3(self):
        with mock.patch.object(P, "episode_video_model", return_value="seedance-2.0-pro"):
            out = P.s7_final_fix_round(self.ctx, None, self.review(
                report={}, cl=checklist({"QA-BURNED-TEXT": [{"at_seconds": 6.0}]})), True)
        self.assertEqual(out["action"], "PROCEED")
        rec = self.record()
        self.assertEqual(rec["status"], "NO_ACTIONABLE_FIX")
        self.assertTrue(rec["paid"]["skipped"][0]["reason"].startswith("MODEL_NOT_H3"))
        self.assertTrue((self.p.video_media / "E01-VU-002.mp4").is_file())

    def test_stage_s7_reruns_once(self):
        calls = []

        def fake_pass(ctx):
            calls.append(1)
            res = P.StageResult(P.BLOCKED)
            res.details = {"final_fix_round": {"action": "S7_RERUN"}}
            return res

        with mock.patch.object(P, "_stage_s7_pass", side_effect=fake_pass):
            P.stage_s7(self.ctx)
        self.assertEqual(len(calls), 2)

    # ------------------------------------------------------------------------------------------- S8
    def s8(self, *, config=None, order=None):
        self.p.final_mp4.parent.mkdir(parents=True, exist_ok=True)
        self.p.final_mp4.write_bytes(b"final")
        self.ctx.stage_state("S7")["status"] = "PASS"
        self.ctx.config = config or {}
        self.ctx.paid_order = order
        self.ctx.authority = {"line_owner_id": "owner"}
        with mock.patch.object(P, "knowledge_sync_summary", return_value={"status": "OK"}), \
                mock.patch.object(P, "_record_line_upgrade", return_value=None), \
                mock.patch.object(P, "write_checkpoint", side_effect=lambda c: c.p.checkpoint.write_text("cp")):
            return P.stage_s8(self.ctx)

    def test_s8_auto_approves_with_unresolved_findings_and_no_publication(self):
        P.s7_final_fix_round(self.ctx, None, self.review(report={"problems": [
            {"issue": "pacing drags", "fix": "tighten", "at_seconds": 2}]}), True)
        order = {"seq": 7, "id": "O7", "publication_allowed": False,
                 "condition_ids": ["PAID_REQUESTS_EXPLICITLY_AUTHORIZED", "NO_PLATFORM_PUBLICATION"]}
        res = self.s8(order=order)
        self.assertEqual((res.status, res.blockers), (P.PASS, []))
        approval = json.loads(self.p.approval.read_text(encoding="utf-8"))
        self.assertEqual((approval["approved_by"], approval["owner_policy"]),
                         ("engine_default_terms", "never_wait_quality"))
        self.assertEqual(approval["release_scope"], "DELIVERABLE_ONLY_NO_PLATFORM_PUBLICATION")
        self.assertFalse(approval["publication_allowed"])
        self.assertIn("NO_PLATFORM_PUBLICATION", approval["paid_order"]["conditions"])
        self.assertEqual(approval["unresolved_findings"][0]["kind"], "PACING")
        self.assertEqual(self.ctx.state["approval"]["by"], "engine_default_terms")
        self.assertTrue(any(l.startswith("S8_AUTO_APPROVED episode=E01") for l in self.ctx.lines))
        self.assertEqual(res.details["platform_upload"], "NEVER — this pipeline has no publish path.")

    def test_s8_publication_scope_follows_order(self):
        self.s8(order={"seq": 8, "publication_allowed": True, "condition_ids": []})
        approval = json.loads(self.p.approval.read_text(encoding="utf-8"))
        self.assertEqual(approval["release_scope"], "DELIVERABLE_AND_PUBLICATION_PER_ORDER")

    def test_s8_opt_in_owner_wait(self):
        res = self.s8(config={"project": {"owner_review_required": True}})
        self.assertEqual((res.status, res.blockers), ("AWAITING_APPROVAL", ["AWAITING_LINE_OWNER_APPROVAL"]))
        self.assertFalse(self.p.approval.exists())

    def test_s8_not_eligible_without_release(self):
        self.ctx.stage_state("S7")["status"] = "BLOCKED"
        with mock.patch.object(P, "knowledge_sync_summary", return_value={}), \
                mock.patch.object(P, "_record_line_upgrade", return_value=None), \
                mock.patch.object(P, "write_checkpoint", return_value=None):
            res = P.stage_s8(self.ctx)
        self.assertEqual(res.status, "AWAITING_APPROVAL")
        self.assertTrue(res.blockers[0].startswith("S8_AUTO_APPROVE_NOT_ELIGIBLE"))
        self.assertFalse(self.p.approval.exists())


class FinalizationReceiptTest(unittest.TestCase):
    def test_engine_receipt_only_for_exact_sentence_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pre = root / "pre"
            (pre / "reports").mkdir(parents=True)
            sentence = ffr.SENTENCES["FACE_DRIFT"]
            base = "Shot text.\nLine two.\n"
            final_ok = root / "ok.txt"
            final_ok.write_text(ffr.apply_sentence(base, sentence), encoding="utf-8")
            final_bad = root / "bad.txt"
            final_bad.write_text(ffr.apply_sentence(base + "extra edit\n", sentence), encoding="utf-8")
            tx = pre / "tx.json"
            tx.write_text(json.dumps({"tasks": [{"unit_id": "U1", "prompt_file": str(final_ok)},
                                                {"unit_id": "U2", "prompt_file": str(final_bad)}]}), encoding="utf-8")
            (pre / "reports" / "E01_FINAL_FIX_REDO.json").write_text(json.dumps(
                {"units": {"U1": {"sentence": sentence, "kinds": ["FACE_DRIFT"]},
                           "U2": {"sentence": sentence, "kinds": ["FACE_DRIFT"]}}}), encoding="utf-8")
            digest = root / "digest.json"
            digest.write_text("{}", encoding="utf-8")
            planned = P.sha256_text(base)
            report = {"rows": [{"unit_id": u, "status": "CHANGED", "planned_sha256": planned,
                                "final_sha256": hashlib.sha256(f.read_bytes()).hexdigest()}
                               for u, f in (("U1", final_ok), ("U2", final_bad))]}
            ctx = SimpleNamespace(episode="E01", p=SimpleNamespace(preprod=pre, preprod_reports=pre / "reports",
                                                                    video_transaction=tx))
            done = P.s6_final_fix_finalization_receipts(ctx, ["U1", "U2"], report, digest)
            self.assertEqual(list(done), ["U1"])
            receipt = json.loads((pre / "prompt_batch_finalization" / "U1.final_fix.json").read_text(encoding="utf-8"))
            self.assertEqual((receipt["status"], receipt["base_authority"]), ("PASS", "PLANNED_PROMPT"))
            task = json.loads(tx.read_text(encoding="utf-8"))["tasks"][0]
            self.assertIn("prompt_batch_finalization", task)
            self.assertEqual(bnp.finalization_receipt_for(pre, "U1", receipt["final_prompt_sha256"]),
                             pre / "prompt_batch_finalization" / "U1.final_fix.json")


class RecordViewsTest(unittest.TestCase):
    def test_summary_note_and_checkpoint(self):
        rec = {"status": "DONE", "first_review": {"verdict": "REJECT_RECUT"}, "second_review": {"verdict": "PASS"},
               "findings": [{"kind": "BGM_FADES", "class": ffr.FREE}, {"kind": "PACING", "class": ffr.RECORD}],
               "free_actions": [{"kind": "BGM_FADES"}],
               "paid": {"selected": [{"unit_id": "E01-VU-002"}], "planned_credits": 10, "budget_cap": 45}}
        rec["unresolved"] = ffr.unresolved(rec)
        self.assertEqual(rec["unresolved"], [{"kind": "PACING", "class": ffr.RECORD, "state": "RECORD_ONLY"}])
        note = ffr.status_note(rec)
        self.assertIn("2nd PASS", note)
        self.assertIn("redo E01-VU-002 (10 cr)", note)
        self.assertTrue(ffr.checkpoint_lines(rec)[0].startswith("## Final fix round"))
        self.assertEqual(ffr.status_note({}), "")


class FleetNoteTest(unittest.TestCase):
    def test_fleet_status_carries_the_round(self):
        sys.path.insert(0, str(REPO / "skills" / "nalu-claude-code" / "scripts"))
        import fleet_sync
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "work"
            path = work / "E03" / "assembly" / "final_qa" / "final_fix_round.json"
            path.parent.mkdir(parents=True)
            ffr.write_record(path, {"status": "DONE", "first_review": {"verdict": "REJECT_RECUT"},
                                    "second_review": {"verdict": "PASS"}, "findings": [],
                                    "paid": {"selected": [{"unit_id": "E03-VU-004"}], "planned_credits": 9}})
            with mock.patch.dict(os.environ, {"NALU_WORK_ROOT": str(work)}):
                summary, note = fleet_sync.final_fix_note(REPO, "E03")
                self.assertEqual(fleet_sync.final_fix_note(REPO, "E04"), (None, ""))
        self.assertEqual(summary["units_redone"], ["E03-VU-004"])
        self.assertIn("2nd PASS", note)


if __name__ == "__main__":
    unittest.main()
