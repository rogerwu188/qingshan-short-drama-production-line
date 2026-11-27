#!/usr/bin/env python3
"""Final fix round v2 (first real run, E18 on device 1101, 2026-11-20).  Offline: no provider, no credits.

Covers: a burned-text redo is measured with the S6 detector and retried with an escalated request inside the round's
budget (best take kept); the classifier catches burned-text / face / sheen / voice-gender wording on any path;
findings are deduped across the checklist and reviewer-problem paths; the second review is reconciled against the
first (RESOLVED / PERSISTS / UNVERIFIED / NEW, "unresolved" = PERSISTS + NEW, never double counted); the voice
contract mapping check; the measured cause of a clipped tail that survives the guard.
"""
from __future__ import annotations

import hashlib
import io
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

import build_nalu_preproduction as bnp  # noqa: E402
import final_fix_round as ffr  # noqa: E402
import h3_burn_retry as br  # noqa: E402
import nalu_pipeline as P  # noqa: E402
from tools import h3_provider_prompt_renderer as h3  # noqa: E402
from tools.h3_provider_english_contract import validate_h3_provider_text_boundary  # noqa: E402
from tools.tests.test_h3_director_performance import unit_plan  # noqa: E402
from tools.tests.test_nalu_final_fix_round import SEGMENTS, _Ctx, checklist, sha  # noqa: E402


# ------------------------------------------------------------------------------------------- classifier
class ClassifierWordingTest(unittest.TestCase):
    def test_burned_text_wording_on_any_path(self):
        burned = [
            (None, 'VU-009 32.75 s model-burned "劳烦师兄了" on screen'),   # the E18 classifier miss
            (None, "画面烧入台词“劳烦师兄了”"),
            (None, "33.8s 劳烦师兄了 烧字"),
            ("OTHER", "字幕上叠了一行模型字"),                               # Gemini class OTHER
            ("QA-PHYSICS", "画面里出现一行字"),                               # record-only item
            (None, "台词「劳烦师兄了」出现在画面下方"),
            (None, "the quoted line is rendered on screen"),
            (None, "burned caption at 12s"),
            (None, "the spoken text is burned into the frame"),
            ("CRAFT-CLARITY", "caption text burned in the picture over her face"),
            ("QA-SUBTITLE-WRAP", "a second model subtitle sits above ours"),
        ]
        for item, text in burned:
            self.assertEqual(ffr.classify(item, text), "BURNED_TEXT", (item, text))
            self.assertEqual(ffr.fix_class(ffr.classify(item, text)), ffr.PAID)

    def test_not_burned_text(self):
        cases = {
            (None, "the house burned in the night scene"): "OTHER",
            (None, "画面里多出一个人"): "OTHER",
            ("QA-SUBTITLE-WRAP", "画面里的字幕换行不当"): "SUBTITLE_WRAP",
            (None, "没有显示字幕"): "OTHER",
            (None, "the line in the shot is cut off"): "DIALOGUE_TAIL_GUARD",
        }
        for (item, text), kind in cases.items():
            self.assertEqual(ffr.classify(item, text), kind, (item, text))

    def test_face_sheen_and_voice_gender_wording(self):
        cases = {
            ("QA-BODY-MORPH", "her face morphs into a different person mid-shot"): "FACE_DRIFT",
            ("CRAFT-EMOTION", "他的相貌变了，不像同一个人"): "FACE_DRIFT",
            (None, "the guard no longer looks like himself"): "FACE_DRIFT",
            ("QA-LOOKALIKE-CAST", "she turns into another character"): "FACE_DRIFT",
            (None, "皮肤油光发亮"): "SKIN_SHEEN",
            ("QA-FLICKER", "greasy-looking skin on the elder"): "SKIN_SHEEN",
            (None, "a woman on screen is given a low male voice line"): "VOICE_GENDER_MISMATCH",
            ("QA-WRONG-SPEAKER", "女子开口却是低沉的男声"): "VOICE_GENDER_MISMATCH",
            ("QA-VOICE-INCONSISTENT", "声音与角色性别不符"): "VOICE_GENDER_MISMATCH",
        }
        for (item, text), kind in cases.items():
            self.assertEqual(ffr.classify(item, text), kind, (item, text))
        # 2026-11-20: a paid redo with the own-voice sentence when the contract is consistent (a mapping / casting
        # bug is downgraded to RECORD by nalu_pipeline._final_fix_annotate)
        self.assertEqual(ffr.fix_class("VOICE_GENDER_MISMATCH"), ffr.PAID)
        # an actionable item is never overridden by face / sheen wording
        self.assertEqual(ffr.classify("QA-DIALOGUE-TAIL-CUT", "her face changes as the line is cut"),
                         "DIALOGUE_TAIL_GUARD")


# --------------------------------------------------------------------------------------------- dedupe
class DedupeTest(unittest.TestCase):
    def test_checklist_and_problem_paths_count_once(self):
        cl = checklist({"QA-BURNED-TEXT": [{"note": "劳烦师兄了", "at_seconds": 6.0}],
                        "QA-DIALOGUE-TAIL-CUT": [{"at_seconds": 13.0}]})
        report = {"problems": [
            {"severity": "P1", "at_seconds": 6.4, "issue": "model-burned caption 劳烦师兄了", "fix": "redo"},
            {"severity": "P2", "at_seconds": 13.6, "issue": "last syllable clipped at the cut", "fix": "guard"},
            {"severity": "P2", "at_seconds": 20.0, "issue": "last syllable clipped", "fix": "guard"},
            {"severity": "P3", "issue": "pacing drags", "fix": "tighten"},
            {"severity": "P3", "issue": "pacing drags in the middle", "fix": "tighten"}]}
        raw = ffr.map_findings(ffr.collect_findings(report, cl), SEGMENTS)
        self.assertEqual(len(raw), 7)
        got = ffr.dedupe(raw)
        self.assertEqual([(f["kind"], f.get("unit_id"), f["source"]) for f in got],
                         [("BURNED_TEXT", "E01-VU-002", "QA_CHECKLIST_REVIEWER"),
                          ("DIALOGUE_TAIL_GUARD", "E01-VU-003", "QA_CHECKLIST_REVIEWER"),
                          ("DIALOGUE_TAIL_GUARD", "E01-VU-004", "REVIEW_PROBLEM"),
                          ("PACING", None, "REVIEW_PROBLEM")])
        self.assertEqual(got[0]["sources"], ["QA_CHECKLIST_REVIEWER", "REVIEW_PROBLEM"])
        self.assertEqual((got[0]["merged"], got[0]["severity"], got[0]["window"]), (2, "P1", [6.0, 6.4]))
        self.assertEqual(got[3]["merged"], 2)
        self.assertTrue(ffr.triggered(False, got))           # the confirmed copy is the one kept
        self.assertEqual(ffr.dedupe(got), got)               # idempotent (a record re-deduped at the round's end)

    def test_tail_cut_just_after_a_boundary_belongs_to_the_outgoing_unit(self):
        mapped = ffr.map_findings([{"source": "REVIEW_PROBLEM", "item": None, "text": "line tail cut off",
                                    "window": [12.2, 12.2]}], SEGMENTS)
        self.assertEqual(mapped[0]["unit_id"], "E01-VU-002")
        burned = ffr.map_findings([{"source": "REVIEW_PROBLEM", "item": None, "text": "burned caption",
                                    "window": [12.2, 12.2]}], SEGMENTS)
        self.assertEqual(burned[0]["unit_id"], "E01-VU-003")


# ------------------------------------------------------------------------------------- reconciliation
def finding(kind, uid=None, window=None, source="REVIEW_PROBLEM"):
    row = {"kind": kind, "class": ffr.fix_class(kind), "source": source}
    if uid:
        row["unit_id"] = uid
    if window:
        row["window"] = window
    return row


class ReconcileTest(unittest.TestCase):
    def test_statuses_and_unresolved_is_persists_plus_new(self):
        first = [finding("BURNED_TEXT", "E01-VU-002", [6.0, 6.0]),
                 finding("BURNED_TEXT", "E01-VU-004", [18.0, 18.0]),
                 finding("DIALOGUE_TAIL_GUARD", "E01-VU-003", [15.9, 15.9]),
                 finding("PACING"),                                       # no time, no unit
                 finding("BGM_FADES", None, [1.0, 2.0])]
        second = [finding("BURNED_TEXT", "E01-VU-004", [18.3, 18.3]),     # persists (same unit)
                  finding("DIALOGUE_TAIL_GUARD", "E01-VU-003", [16.4, 16.4]),  # persists (window)
                  finding("DIALOGUE_TAIL_GUARD", "E01-VU-004", [21.0, 21.0]),  # new
                  finding("VOICE_GENDER_MISMATCH", "E01-VU-004", [22.0, 22.0])]  # new
        rec = ffr.reconcile(first, second)
        self.assertEqual([r["status"] for r in rec["rows"]],
                         [ffr.RESOLVED, ffr.PERSISTS, ffr.PERSISTS, ffr.UNVERIFIED, ffr.RESOLVED])
        self.assertEqual(rec["counts"], {ffr.RESOLVED: 2, ffr.PERSISTS: 2, ffr.UNVERIFIED: 1, ffr.NEW: 2})
        self.assertEqual(rec["unresolved_count"], 4)
        record = {"status": "DONE", "findings": first, "reconciliation": rec,
                  "second_review": {"verdict": "REJECT_RECUT"},
                  "paid": {"selected": [{"unit_id": "E01-VU-002"}, {"unit_id": "E01-VU-004"}]}}
        unresolved = ffr.unresolved(record)
        self.assertEqual([(u["kind"], u["state"]) for u in unresolved],
                         [("BURNED_TEXT", "PERSISTS"), ("DIALOGUE_TAIL_GUARD", "PERSISTS"),
                          ("DIALOGUE_TAIL_GUARD", "NEW"), ("VOICE_GENDER_MISMATCH", "NEW")])
        self.assertNotIn("UNVERIFIED_AFTER_FIX", json.dumps(unresolved))
        record["unresolved"] = unresolved
        note = ffr.status_note({**record, "first_review": {"verdict": "REJECT_RECUT"}})
        self.assertIn("resolved 2 persists 2 new 2 unverified 1", note)
        self.assertIn("unresolved 4", note)

    def test_no_second_review_is_unverified(self):
        rec = ffr.reconcile([finding("BURNED_TEXT", "U1", [1, 1])], None)
        self.assertEqual((rec["rows"][0]["status"], rec["second_findings"]), (ffr.UNVERIFIED, None))


# ------------------------------------------------------------------------------- the round end to end
class RoundV2Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        p = SimpleNamespace(
            assembly=root / "assembly", video_media=root / "video", preprod_reports=root / "reports",
            preprod=root / "pre", final_candidate=root / "assembly" / "E01_final_candidate_9x16.mp4",
            video_transaction=root / "pre" / "tx.json", agentcut_project=root / "assembly" / "proj.json",
            grouping_plan=root / "pre" / "grouping.json", editorial=root / "pre" / "editorial.json")
        for d in (p.assembly / "final_qa", p.video_media, p.preprod_reports, p.preprod):
            d.mkdir(parents=True, exist_ok=True)
        for i in range(1, 5):
            (p.video_media / f"E01-VU-00{i}.mp4").write_bytes(f"clip{i}".encode())
        (p.assembly / "E01_release_timeline.json").write_text(json.dumps({"segments": SEGMENTS}), encoding="utf-8")
        p.final_candidate.write_bytes(b"cut-1")
        self.p = p
        self.ctx = _Ctx(episode="E01", p=p, run_id="RUN1", state={}, lines=[], headroom=500, dry=False,
                        config={}, paid_order=None, authority={})
        self.spent = 100.0
        self.patches = [mock.patch.object(P, "episode_video_model", return_value="MiniMax-H3"),
                        mock.patch.object(P, "episode_video_resolution", return_value="768p"),
                        mock.patch.object(P, "video_task_credits", return_value=8),
                        mock.patch.object(P, "credits_summary",
                                          side_effect=lambda _c: {"recorded_total_credits": self.spent}),
                        mock.patch.object(P, "REVIEWS_ROOT", root / "reviews"),
                        mock.patch.dict(os.environ, {}, clear=False)]
        for patch in self.patches:
            patch.start()
        for name in ("NALU_FINAL_FIX_ROUNDS", "NALU_FINAL_FIX_BUDGET_CREDITS", ffr.FIX_BURN_RETRY_ENV):
            os.environ.pop(name, None)

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def review(self, report, cl=None):
        final_qa = self.p.assembly / "final_qa"
        (final_qa / "E01_AUDIENCE_SCORE_REPORT.json").write_text(json.dumps(report), encoding="utf-8")
        cl_path = final_qa / "E01_QA_DEFECT_CHECKLIST.json"
        if cl is not None:
            cl_path.write_text(json.dumps(cl), encoding="utf-8")
        elif cl_path.exists():
            cl_path.unlink()
        return {"report": str(final_qa / "E01_AUDIENCE_SCORE_REPORT.json"),
                "final_video_sha256": sha(self.p.final_candidate)}

    def record(self):
        return json.loads((self.p.assembly / "final_qa" / "final_fix_round.json").read_text(encoding="utf-8"))

    def test_round_dedupes_plans_once_and_reconciles(self):
        cl = checklist({"QA-BURNED-TEXT": [{"note": "劳烦师兄了", "at_seconds": 6.0}]})
        first = self.review({"problems": [
            {"severity": "P1", "at_seconds": 6.3, "issue": "model-burned '劳烦师兄了' in the picture", "fix": "redo"},
            {"severity": "P1", "at_seconds": 18.0, "issue": "画面烧入台词", "fix": "redo"},
            {"severity": "P2", "at_seconds": 15.9, "issue": "last syllable clipped", "fix": "tail"}]}, cl)
        out = P.s7_final_fix_round(self.ctx, None, first, True)
        self.assertEqual(out["action"], "S6_REDO_PENDING")
        rec = self.record()
        self.assertEqual(len(rec["findings"]), 3)                        # 4 raw -> 3 distinct
        self.assertEqual(sorted(out["units"]), ["E01-VU-002", "E01-VU-004"])
        self.assertEqual(rec["paid"]["planned_credits"], 16)
        # the redo lands; the second review of the new cut: VU-004 still burned, a NEW voice-gender P1
        (self.p.video_media / "E01-VU-002.mp4").write_bytes(b"redo2")
        (self.p.video_media / "E01-VU-004.mp4").write_bytes(b"redo4")
        self.p.final_candidate.write_bytes(b"cut-2")
        self.spent = 117.0
        second = self.review({"problems": [
            {"severity": "P1", "at_seconds": 18.4, "issue": "burned caption still in the picture", "fix": "redo"},
            {"severity": "P1", "at_seconds": 22.0, "issue": "a woman on screen is given a low male voice line",
             "fix": "voice"}]})
        out = P.s7_final_fix_round(self.ctx, None, second, True)
        self.assertEqual(out["action"], "PROCEED")
        rec = self.record()
        counts = rec["reconciliation"]["counts"]
        self.assertEqual(counts, {ffr.RESOLVED: 2, ffr.PERSISTS: 1, ffr.UNVERIFIED: 0, ffr.NEW: 1})
        self.assertEqual([(u["kind"], u["state"]) for u in rec["unresolved"]],
                         [("BURNED_TEXT", "PERSISTS"), ("VOICE_GENDER_MISMATCH", "NEW")])
        self.assertEqual(out["unresolved"], 2)
        self.assertEqual(rec["second_review"]["findings"][1]["voice_check"]["status"], "NO_TASK")
        self.assertTrue(any("resolved=2 persists=1 new=1 unverified=0 unresolved=2" in line
                            for line in self.ctx.lines))
        self.assertEqual(rec["paid"]["burn_checks"]["E01-VU-004"]["status"], "NOT_MEASURED")
        note = ffr.status_note(rec)
        self.assertIn("burn 004=NOT_MEASURED,002=NOT_MEASURED", note)
        self.assertIn("resolved 2 persists 1 new 1 unverified 0; unresolved 2", note)


# ------------------------------------------------------------------------------- burned-text redo loop
class BurnRedoLoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        self.p = SimpleNamespace(video_media=root / "video", preprod=root / "pre", preprod_reports=root / "reports",
                                 assembly=root / "assembly", video_transaction=root / "pre" / "tx.json",
                                 grouping_plan=root / "pre" / "g.json", editorial=root / "pre" / "e.json")
        for d in (self.p.video_media, self.p.preprod, self.p.preprod_reports, self.p.assembly / "final_qa"):
            d.mkdir(parents=True, exist_ok=True)
        self.headroom = 500
        self.said: list[str] = []
        self.ctx = SimpleNamespace(episode="E01", p=self.p, run_id="RUN", say=self.said.append, dry=False,
                                   budget_check=lambda _x, label: {"budget_verdict": {"headroom_credits": self.headroom}})
        self.burned: dict[str, int] = {}
        self.detect_kwargs: list[dict] = []

        def detect(clip, **kw):
            # 2026-11-23: S6 also passes the unit's lines + dialogue language (whole-frame text pass); this test
            # pins the burn-run rule only
            self.detect_kwargs.append({k: v for k, v in kw.items() if k not in ("lines", "lang")})
            frames = self.burned.get(Path(clip).read_text(), 0)
            return {"status": "BURNED" if frames else "CLEAN", "frames_sampled": 24, "burned_frames": frames,
                    "longest_run": frames, "elapsed_ms": 1.0, "hits": []}

        self.patches = [mock.patch.object(br, "detect", detect),
                        mock.patch.object(P, "episode_video_model", lambda _e: "MiniMax-H3"),
                        mock.patch.object(P, "episode_video_resolution", lambda _e: "768p"),
                        mock.patch.object(P, "video_task_credits", lambda *_a, **_k: 8),
                        mock.patch.dict(os.environ, {}, clear=False)]
        for patch in self.patches:
            patch.start()
        for name in ("NALU_FINAL_FIX_BUDGET_CREDITS", ffr.FIX_BURN_RETRY_ENV):
            os.environ.pop(name, None)
        self.write_round(planned=16)
        self.redo({"U1": ["BURNED_TEXT"], "U2": ["FACE_DRIFT"]})

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def write_round(self, planned):
        ffr.write_record(self.p.assembly / "final_qa" / ffr.RECORD_NAME,
                         {"status": "S6_REDO_PENDING", "paid": {"planned_credits": planned, "selected": []}})

    def redo(self, units):
        P.write_json(P.final_fix_redo_path(self.ctx), {"schema": ffr.REDO_SCHEMA, "units": {
            uid: {"round": 1, "kind": kinds[0], "kinds": kinds, "sentence": ffr.redo_sentence(kinds),
                  "status": "PARKED", "parked_clip_sha256": "orig"} for uid, kinds in units.items()}})

    def land(self, uid, content):
        clip = self.p.video_media / f"{uid}.mp4"
        clip.write_text(content)
        return P.s6_burn_check_landed(self.ctx, [uid])

    def state(self):
        return json.loads(P.final_fix_redo_path(self.ctx).read_text(encoding="utf-8"))["units"]

    def test_still_burned_retries_with_escalation_then_keeps_best(self):
        self.burned = {"U1-take1": 6, "U1-take2": 2, "U1-take3": 4}
        rows = self.land("U1", "U1-take1")
        self.assertEqual((rows[0]["action"], rows[0]["retry"]), ("RETRY", 1))
        self.assertEqual(self.detect_kwargs[-1], {"min_consecutive": 1})  # the reviewer already confirmed it
        rec = self.state()["U1"]
        self.assertFalse((self.p.video_media / "U1.mp4").exists())
        self.assertTrue(Path(rec["burn_retries"][0]["parked_clip"]).is_file())
        self.assertEqual((rec["burn_retry"], rec["status"]), (1, "BURN_RETRY_PENDING"))
        self.assertEqual(rec["sentence"], ffr.BURN_RETRY_SENTENCES[1])
        self.assertEqual(rec["burn_retries"][0]["previous_sentence"], ffr.SENTENCES["BURNED_TEXT"])
        self.assertIn("U1", P.final_fix_redo_pending(self.ctx))
        # the posted retry is noted
        self.assertEqual(P.s6_burn_retry_note_posted(self.ctx, ["U1"]), ["U1"])
        self.assertEqual(self.state()["U1"]["status"], "BURN_RETRY_SUBMITTED")
        # the recompile carries the retry index and sentence (the submitter's stronger perturbation)
        fields = bnp.final_fix_redo_fields(self.root, "E01")
        self.assertEqual((fields["U1"]["burn_retry"], fields["U1"]["sentence"]), (1, ffr.BURN_RETRY_SENTENCES[1]))
        rows = self.land("U1", "U1-take2")
        self.assertEqual((rows[0]["action"], rows[0]["retry"]), ("RETRY", 2))
        self.assertEqual(self.state()["U1"]["sentence"], ffr.BURN_RETRY_SENTENCES[2])
        rows = self.land("U1", "U1-take3")
        self.assertEqual((rows[0]["action"], rows[0]["reason"]), ("KEEP_BEST", "RETRY_MAX_REACHED"))
        self.assertEqual((self.p.video_media / "U1.mp4").read_text(), "U1-take2")   # fewest burned frames
        rec = self.state()["U1"]
        self.assertEqual((rec["burn_status"], rec["kept_take_burned_frames"]), ("UNRESOLVED", 2))
        self.assertEqual(self.land("U1", (self.p.video_media / "U1.mp4").read_text()), [])  # decided: not again
        summary = P.final_fix_burn_summary(json.loads(P.final_fix_redo_path(self.ctx).read_text()))
        # v7 burn escalation: no start frame on record here -> skipped, the best take is kept as before
        self.assertEqual(summary["U1"], {"status": "UNRESOLVED", "retries": 2, "retry_credits": 16.0,
                                         "kept_burned_frames": 2, "reason": "RETRY_MAX_REACHED",
                                         "escalation": "SKIPPED:NO_START_FRAME"})
        said = "\n".join(self.said)
        for tag in ("FINAL_FIX_BURN_RETRY unit=U1 frames=6/24 retry=1/2", "FINAL_FIX_BURN_RETRY_SUBMITTED unit=U1",
                    "FINAL_FIX_BURN_UNRESOLVED unit=U1 retry=2/2 reason=RETRY_MAX_REACHED"):
            self.assertIn(tag, said)

    def test_clean_redo_resolves_and_other_kinds_are_never_retried(self):
        self.burned = {"U2-take1": 9}
        rows = self.land("U1", "U1-take1")
        self.assertEqual((rows[0]["action"], rows[0]["reason"]), ("KEEP", "CLEAN"))
        self.assertEqual(self.state()["U1"]["burn_status"], "RESOLVED")
        self.assertEqual(self.land("U2", "U2-take1"), [])                # a face-drift redo is its one take
        self.assertEqual(self.detect_kwargs, [{"min_consecutive": 1}])

    def test_budget_shared_across_units_caps_the_retries(self):
        os.environ["NALU_FINAL_FIX_BUDGET_CREDITS"] = "30"  # 30 - 16 planned = 14 left: one 8-credit retry
        self.redo({"U1": ["BURNED_TEXT"], "U3": ["BURNED_TEXT", "FACE_DRIFT"]})
        self.burned = {"U1-take1": 5, "U3-take1": 3}
        self.assertEqual(self.land("U1", "U1-take1")[0]["action"], "RETRY")
        row = self.land("U3", "U3-take1")[0]
        self.assertEqual((row["action"], row["reason"], row["budget_left"]), ("KEEP_BEST", "FINAL_FIX_BUDGET_CAP", 6.0))
        self.assertTrue((self.p.video_media / "U3.mp4").is_file())       # kept, nothing parked
        # the cap arithmetic is logged and recorded (E23 2026-11-22: read as a misjudgment next to headroom 1341)
        self.assertIn("FINAL_FIX_BURN_UNRESOLVED unit=U3 retry=0/2 reason=FINAL_FIX_BUDGET_CAP kept_take=",
                      "\n".join(self.said))
        self.assertIn("cost=8 round_budget_left=6.0 round_cap=30 episode_headroom=500", "\n".join(self.said))
        self.assertEqual(self.state()["U3"]["burn_unresolved_budget"],
                         {"cost": 8, "round_budget_left": 6.0, "round_cap": 30, "episode_headroom": 500})
        self.assertEqual(ffr.round_budget_left({"paid": {"planned_credits": 16}},
                                               json.loads(P.final_fix_redo_path(self.ctx).read_text()), 30), 6.0)

    def test_headroom_and_env(self):
        self.headroom = 5
        self.burned = {"U1-take1": 5}
        row = self.land("U1", "U1-take1")[0]
        self.assertEqual((row["action"], row["reason"]), ("KEEP_BEST", "BUDGET_HEADROOM_SHORT"))
        self.assertEqual(ffr.burn_retry_max({ffr.FIX_BURN_RETRY_ENV: "7"}), 2)
        self.assertEqual(ffr.burn_retry_max({ffr.FIX_BURN_RETRY_ENV: "0"}), 0)
        self.assertEqual(ffr.plan_burn_retry({}, {"status": "BURNED"}, retry_max=0, budget_left=99, headroom=99,
                                             cost=1)["reason"], "RETRY_DISABLED")
        self.assertEqual(ffr.plan_burn_retry({}, {"status": "FAIL_OPEN"}, retry_max=2, budget_left=99, headroom=99,
                                             cost=1)["action"], "KEEP")


class BurnRetryTransportTest(unittest.TestCase):
    def test_sentences_are_distinct_and_pass_the_h3_boundary(self):
        from tools import h3_burn_retry as tbr
        texts = [ffr.SENTENCES["BURNED_TEXT"], *ffr.BURN_RETRY_SENTENCES.values(), *tbr.RETRY_SENTENCES.values()]
        self.assertEqual(len(set(texts)), len(texts))
        base, _ = h3.render_h3_prompt(*unit_plan(stamped=True, performance=None))
        for n in (1, 2):
            sentence = ffr.redo_sentence(["BURNED_TEXT", "COSTUME_IDENTITY"], burn_retry=n)
            self.assertTrue(sentence.startswith(ffr.BURN_RETRY_SENTENCES[n]))
            unit, plan = unit_plan(stamped=True, performance=None)
            unit["h3_final_fix"] = {"round": 1, "kind": "BURNED_TEXT", "kinds": ["BURNED_TEXT"],
                                    "sentence": ffr.redo_sentence(["BURNED_TEXT"], burn_retry=n), "burn_retry": n}
            text, receipt = h3.render_h3_prompt(unit, plan)
            self.assertEqual(receipt["h3_final_fix"]["sentence"], ffr.BURN_RETRY_SENTENCES[n])
            self.assertEqual(ffr.strip_sentence(text, ffr.BURN_RETRY_SENTENCES[n]), (base, True))
            self.assertEqual(validate_h3_provider_text_boundary(text, source_id="T")["status"], "PASS")

    def test_compile_carries_the_retry_and_the_submitter_escalates(self):
        from tools.submit_giggle_video_manifest_v2 import _final_fix_burn_retry
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "reports").mkdir()
            (out / "reports" / "E01_FINAL_FIX_REDO.json").write_text(json.dumps({"units": {
                "U1": {"round": 1, "kind": "BURNED_TEXT", "kinds": ["BURNED_TEXT"], "sentence": "s", "burn_retry": 2},
                "U2": {"round": 1, "kind": "FACE_DRIFT", "kinds": ["FACE_DRIFT"], "sentence": "f"}}}), encoding="utf-8")
            fields = bnp.final_fix_redo_fields(out, "E01")
        self.assertEqual(fields["U1"]["burn_retry"], 2)
        self.assertNotIn("burn_retry", fields["U2"])
        self.assertEqual(_final_fix_burn_retry({"h3_final_fix": fields["U1"]}), 2)
        self.assertEqual(_final_fix_burn_retry({"h3_final_fix": fields["U2"]}), 0)

    def test_strong_perturbation_differs_per_retry_and_keeps_the_size(self):
        from PIL import Image
        image = Image.new("RGB", (720, 1280), (120, 80, 60))
        for x in range(0, 720, 40):
            for y in range(0, 1280, 40):
                image.putpixel((x, y), (x % 255, y % 255, 9))
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=95)
        data = buf.getvalue()
        plain, _ = br.perturb_start_frame(data, 3)
        one, n1 = br.perturb_start_frame_strong(data, 3, 1)
        two, n2 = br.perturb_start_frame_strong(data, 3, 2)
        self.assertEqual(len({hashlib.sha256(x).hexdigest() for x in (data, plain, one, two)}), 4)
        self.assertEqual((n1["method"], n2["method"]), ("CROP_SCALE_1PCT_JPEG_Q86", "CROP_SCALE_2PCT_JPEG_Q80"))
        for blob, note in ((one, n1), (two, n2)):
            self.assertEqual(Image.open(io.BytesIO(blob)).size, (720, 1280))
            x0, y0, x1, y1 = note["crop_box"]
            self.assertLessEqual(720 - (x1 - x0), round(720 * 0.02) + 1)   # at most ~2 % per axis
        self.assertEqual(br.perturb_start_frame_strong(data, 3, 0)[1]["method"], br.perturb_start_frame(data, 3)[1]["method"])
        self.assertEqual(br.perturb_start_frame_strong(b"not an image", 3, 1)[1]["status"], "SKIPPED_UNDECODABLE")

    def test_finalization_receipt_follows_the_retry_sentence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pre = root / "pre"
            (pre / "reports").mkdir(parents=True)
            base = "Shot text.\nLine two.\n"
            sentence = ffr.redo_sentence(["BURNED_TEXT"], burn_retry=1)
            final = root / "final.txt"
            final.write_text(ffr.apply_sentence(base, sentence), encoding="utf-8")
            tx = pre / "tx.json"
            tx.write_text(json.dumps({"tasks": [{"unit_id": "U1", "prompt_file": str(final)}]}), encoding="utf-8")
            (pre / "reports" / "E01_FINAL_FIX_REDO.json").write_text(json.dumps(
                {"units": {"U1": {"sentence": sentence, "kinds": ["BURNED_TEXT"], "burn_retry": 1}}}), encoding="utf-8")
            digest = root / "digest.json"
            digest.write_text("{}", encoding="utf-8")
            report = {"rows": [{"unit_id": "U1", "status": "CHANGED", "planned_sha256": P.sha256_text(base),
                                "final_sha256": hashlib.sha256(final.read_bytes()).hexdigest()}]}
            ctx = SimpleNamespace(episode="E01", p=SimpleNamespace(preprod=pre, preprod_reports=pre / "reports",
                                                                    video_transaction=tx))
            self.assertEqual(list(P.s6_final_fix_finalization_receipts(ctx, ["U1"], report, digest)), ["U1"])


# ---------------------------------------------------------------------------------- voice / tail cause
class VoiceCheckTest(unittest.TestCase):
    REGISTRY = [{"entity_id": "v_lin", "character_id": "CHAR-LIN", "gender": "female"},
                {"entity_id": "v_shen", "character_id": "CHAR-SHEN", "gender": "male"}]

    def test_mapping_bug_ok_unknown(self):
        ok = ffr.voice_assignment_check([{"speaker": "林", "character_id": "CHAR-LIN", "voice_entity_id": "v_lin"}],
                                        self.REGISTRY)
        self.assertEqual(ok["status"], "CONTRACT_OK")
        bug = ffr.voice_assignment_check([{"speaker": "林", "character_id": "CHAR-LIN", "voice_entity_id": "v_shen"}],
                                         self.REGISTRY)
        self.assertEqual(bug["status"], "MAPPING_BUG")
        self.assertEqual(bug["bugs"][0]["problem"], "VOICE_ENTITY_OF_ANOTHER_CHARACTER:CHAR-SHEN")
        gender = ffr.voice_assignment_check(
            [{"speaker": "林", "character_id": "CHAR-LIN", "voice_entity_id": "v_x"}],
            [{"entity_id": "v_x", "gender": "male"}], [{"character_id": "CHAR-LIN", "gender": "女"}])
        self.assertEqual(gender["bugs"][0]["problem"], "VOICE_GENDER_MALE_FOR_FEMALE_SPEAKER")
        self.assertEqual(ffr.voice_assignment_check(
            [{"character_id": "CHAR-Q", "voice_entity_id": "v_q"}], [])["status"], "UNKNOWN")
        self.assertEqual(ffr.voice_assignment_check([], self.REGISTRY)["status"], "NO_BINDINGS")

    def test_pipeline_check_reads_task_registry_and_vo_placement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reg = root / "registry.json"
            reg.write_text(json.dumps({"major_roles": self.REGISTRY}), encoding="utf-8")
            tx = root / "tx.json"
            tx.write_text(json.dumps({"tasks": [{"unit_id": "U7", "speaker_voice_contract": {"bindings": [
                {"speaker": "林", "character_id": "CHAR-LIN", "voice_entity_id": "v_shen", "audio_slot": "@音频1"}]}}]}),
                encoding="utf-8")
            (root / "asm").mkdir()
            (root / "asm" / "E01_voice_over_placement.json").write_text(json.dumps({"rows": [
                {"shot_id": "S9", "line_index": 0, "character_id": "CHAR-SHEN", "start": 39.6, "end": 41.0}]}),
                encoding="utf-8")
            said: list[str] = []
            ctx = SimpleNamespace(episode="E01", say=said.append, p=SimpleNamespace(
                video_transaction=tx, assembly=root / "asm", scope={"voice_registry": str(reg)}))
            got = P.final_fix_voice_check(ctx, "U7", [40.0, 40.0])
            self.assertEqual(got["status"], "MAPPING_BUG")
            self.assertEqual(got["cause_hint"], "VOICE_OVER_PLACED_OVER_THIS_SHOT")
            mapped = [{"kind": "VOICE_GENDER_MISMATCH", "unit_id": "U7", "window": [40.0, 40.0]}]
            P._final_fix_annotate(ctx, mapped, [])
            self.assertTrue(any(line.startswith("FINAL_FIX_VOICE_MAPPING_BUG unit=U7") for line in said))
            record = {"status": "DONE", "findings": mapped, "first_review": {"verdict": "REJECT_RECUT"}}
            self.assertEqual(ffr.summary(record)["voice_mapping_bugs"], ["U7"])
            self.assertIn("VOICE MAPPING BUG U7", ffr.status_note(record))


class TailCauseTest(unittest.TestCase):
    def test_causes(self):
        room = {"unit_id": "A", "original_seconds": 6.0, "after_out": 5.2,
                "tail_guard": {"word_end": 4.5, "speech_end": 4.6, "guard": 4.9, "cut": 5.2,
                               "capped_by_next_speech": False}}
        no_room = {"unit_id": "A", "original_seconds": 5.0, "after_out": 5.0,
                   "tail_guard": {"word_end": 4.7, "speech_end": None, "guard": 5.1, "cut": 5.0,
                                  "capped_by_next_speech": False}}
        capped = {**room, "tail_guard": {**room["tail_guard"], "capped_by_next_speech": True}}
        head = {"unit_id": "B", "after_in": 0.0, "line_start_seconds": 0.05}
        self.assertEqual(ffr.tail_cut_cause(no_room)["cause"], "CLIP_END_NO_ROOM")
        self.assertEqual(ffr.tail_cut_cause(room, head)["cause"], "NEXT_SHOT_SPEECH_AT_HEAD")
        self.assertEqual(ffr.tail_cut_cause(capped)["cause"], "NEXT_SPEECH_IN_TAKE")
        self.assertEqual(ffr.tail_cut_cause(room, {"after_in": 0.0, "line_start_seconds": 0.6})["cause"],
                         "GUARD_APPLIED")
        self.assertEqual(ffr.tail_cut_cause(None)["cause"], "NO_PERFORMANCE_CUT_ROW")
        self.assertEqual(ffr.tail_cut_cause({"unit_id": "A", "status": "NO_ASR_WORDS"})["cause"],
                         "NOT_A_MATCHED_LINE")

    def test_round_annotates_a_tail_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "E01_PERFORMANCE_CUT.json").write_text(json.dumps({"units": [
                {"unit_id": "E01-VU-002", "original_seconds": 7.0, "after_out": 7.0,
                 "tail_guard": {"word_end": 6.8, "speech_end": None, "guard": 7.2, "cut": 7.0}}]}), encoding="utf-8")
            ctx = SimpleNamespace(episode="E01", say=lambda _l: None, p=SimpleNamespace(assembly=root))
            mapped = [{"kind": "DIALOGUE_TAIL_GUARD", "unit_id": "E01-VU-002", "window": [11.9, 11.9]}]
            P._final_fix_annotate(ctx, mapped, SEGMENTS)
            self.assertEqual(mapped[0]["tail_cause"]["cause"], "CLIP_END_NO_ROOM")


if __name__ == "__main__":
    unittest.main()
