#!/usr/bin/env python3
"""Camera wobble, look-alike cast and the detailed Gemini final review (line owner 2026-11-21, KO E05 on device ...0080).

A. "The camera shakes along with a character's small movements -- the person AND the background move together."
   The S7 lock-off stabiliser tracked the whole frame, locked onto the swaying actor and moved the set with him; it
   now tracks the set only.  S6 measures the set's own motion on locked-off units (tools/h3_camera_wobble) and
   retries a wobbling take once with the locked-off sentence; prompts of locked-off units state that the set stays
   still.
B. "The male lead speaking looks like the same person": every same-sex pair is scored with a stricter same-band
   threshold, and a pair of LOCKED cards re-designs the secondary character's card once (the lead keeps his).
C. The multi-pass Gemini review checks QA-CAMERA-WOBBLE / QA-LOOKALIKE-CAST / QA-EDIT-FRAGMENT with concrete criteria
   and answers passes A / B as a per-shot checklist.

Offline: synthetic clips, mocked HTTP, no credits.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
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

import numpy as np  # noqa: E402

import build_nalu_preproduction as bnp  # noqa: E402
import character_distinctness as cd  # noqa: E402
import final_fix_round as ffr  # noqa: E402
import gemini_review_passes as mp  # noqa: E402
import h3_burn_retry as br  # noqa: E402
import h3_camera_wobble as wob  # noqa: E402
import nalu_knowledge_events as kbe  # noqa: E402
import nalu_pipeline as P  # noqa: E402
import nalu_qa_defect_checklist as qadc  # noqa: E402

W, H, FPS = 240, 426, 24
#: the subject (an "actor") occupies this box in fractions of the frame; tests hand it to the detector as the person
SUBJECT_BOX = (0.30, 0.22, 0.70, 1.0)


def _scene(n: int = 72, *, shake_px: float = 0.0, sway_px: float = 14.0, seed: int = 3):
    """Synthetic frames: a textured still set (vertical lines + noise) and a textured actor swaying sideways;
    ``shake_px`` moves the WHOLE set in step with the actor (the H3 wobble)."""
    rng = np.random.default_rng(seed)
    margin = 40
    bg = (rng.random((H + 2 * margin, W + 2 * margin)) * 255).astype(np.uint8)
    import cv2
    bg = cv2.GaussianBlur(bg, (5, 5), 0)
    for x in range(0, W + 2 * margin, 24):
        bg[:, x:x + 2] = 255
    actor = (rng.random((int(H * 0.78), int(W * 0.3))) * 255).astype(np.uint8)
    frames = []
    for k in range(n):
        phase = math.sin(2 * math.pi * 0.8 * k / FPS)
        cam = int(round(shake_px * phase))
        frame = bg[margin:margin + H, margin + cam:margin + cam + W].copy()
        x0 = int(W * 0.35 + sway_px * phase) - cam
        y0 = int(H * 0.22)
        frame[y0:y0 + actor.shape[0], x0:x0 + actor.shape[1]] = actor
        frames.append(cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR))
    return frames


def _reader(frames):
    def read(_video, fps):
        step = max(1, int(round(FPS / fps)))
        for i in range(0, len(frames), step):
            yield round(i / FPS, 3), frames[i]
    return read


def _write_clip(path: Path, frames) -> Path:
    """An H.264 mp4 with a silent audio track (needs ffmpeg)."""
    import cv2
    raw = path.with_suffix(".avi")
    vw = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (W, H))
    for f in frames:
        vw.write(f)
    vw.release()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)
    raw.unlink()
    return path


# ============================================================================================ A. detector
class WobbleDetectorTest(unittest.TestCase):
    def _detect(self, frames, **kw):
        return wob.detect(Path("clip.mp4"), frames=_reader(frames), faces=[], boxes=[SUBJECT_BOX], **kw)

    def test_still_set_with_moving_actor_is_clean(self):
        res = self._detect(_scene(shake_px=0.0))
        self.assertEqual(res["status"], "CLEAN", res)
        self.assertLess(res["metrics"]["excursion_pct"], wob.EXCURSION_MIN_PCT)

    def test_set_moving_with_the_actor_is_wobble(self):
        res = self._detect(_scene(shake_px=6.0))
        self.assertEqual(res["status"], "WOBBLE", res)
        self.assertIn("COUPLED_TO_SUBJECT", res["reasons"])
        self.assertGreaterEqual(res["metrics"]["excursion_pct"], wob.EXCURSION_MIN_PCT)
        self.assertGreater(wob.wobble_score(res), 0.0)

    def test_moving_plan_not_measured_and_failures_open(self):
        self.assertEqual(wob.detect(Path("x.mp4"), plan_static=False)["status"], "NOT_STATIC_PLAN")

        def boom(_v, _f):
            raise RuntimeError("no decoder")
            yield  # pragma: no cover
        self.assertEqual(wob.detect(Path("x.mp4"), frames=boom, faces=[])["status"], "FAIL_OPEN")
        # a close-up with no visible set cannot be measured -- never a verdict
        res = wob.detect(Path("x.mp4"), frames=_reader(_scene()), faces=[], boxes=[(0.0, 0.0, 1.0, 1.0)])
        self.assertEqual(res["status"], "NOT_MEASURABLE")

    def test_classify_mild_vs_strong_and_static_plan(self):
        self.assertEqual(wob.classify({"excursion_pct": 0.5, "coupling": 0.99})["status"], "CLEAN")
        mild = wob.classify({"excursion_pct": 1.2, "coupling": 0.8})
        self.assertEqual((mild["status"], mild["severity"]), ("WOBBLE", "MILD"))
        self.assertEqual(wob.classify({"excursion_pct": 4.0, "reversals_per_s": 1.0})["severity"], "STRONG")
        self.assertTrue(wob.static_plan({"camera_plan": {"motion_family": "LOCKED"}}))
        self.assertFalse(wob.static_plan({"camera_plan": {"motion_family": "LOCKED"},
                                          "ordered_prompt_specs": [{"camera_plan": {"motion_family": "DOLLY"}}]}))
        self.assertIsNone(wob.static_plan({}))


class WobbleRetryPlanTest(unittest.TestCase):
    WOB = {"status": "WOBBLE", "severity": "MILD", "metrics": {"excursion_pct": 1.5}}

    def test_one_wobble_retry_within_budget_and_the_s6_cap(self):
        plan = wob.plan(None, self.WOB, retry_max=1, total_max=2, headroom=100, cost=10)
        self.assertEqual((plan["action"], plan["retry"]), ("RETRY", 1))
        done = {"attempts": [{"retry": 1, "camera_wobble": True}]}
        self.assertEqual(wob.plan(done, self.WOB, retry_max=1, total_max=2, headroom=100, cost=10)["reason"],
                         "WOBBLE_RETRY_MAX_REACHED")
        # after a burned-text retry the wobble retry is the unit's second (and last) S6 retry
        burn = {"attempts": [{"retry": 1}]}
        self.assertEqual(wob.plan(burn, self.WOB, retry_max=1, total_max=2, headroom=100, cost=10)["retry"], 2)
        two = {"attempts": [{"retry": 1}, {"retry": 2}]}
        self.assertEqual(wob.plan(two, self.WOB, retry_max=1, total_max=2, headroom=100, cost=10)["reason"],
                         "S6_RETRY_MAX_REACHED")
        self.assertEqual(wob.plan(None, self.WOB, retry_max=1, total_max=2, headroom=5, cost=10)["reason"],
                         "BUDGET_HEADROOM_SHORT")
        self.assertEqual(wob.plan(None, {"status": "CLEAN"}, retry_max=1, total_max=2, headroom=9, cost=1)["action"],
                         "KEEP")

    def test_best_take_prefers_less_wobble_after_burn(self):
        takes = [{"sha256": "a", "path": "a", "burned_frames": 0, "wobble_pct": 2.5},
                 {"sha256": "b", "path": "b", "burned_frames": 0, "wobble_pct": 1.1},
                 {"sha256": "c", "path": "c", "burned_frames": 3, "wobble_pct": 0.0}]
        self.assertEqual(br.best_take(takes)["sha256"], "b")

    def test_wobble_sentence_roundtrip_and_recompile_field(self):
        text = "Camera:\nLocked camera.\n"
        varied = br.apply_retry_sentence(text, 1, wobble=True)
        self.assertIn(wob.retry_sentence(1), varied)
        self.assertNotIn(br.RETRY_SENTENCES[1], varied)
        self.assertEqual(br.strip_retry_sentence(varied), (text, 1))
        for sentence in br.WOBBLE_RETRY_SENTENCES.values():  # plain words: no digits, no all-caps label
            self.assertFalse(any(ch.isdigit() for ch in sentence))
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp) / "reports"
            reports.mkdir()
            (reports / "E05_S6_WAVE_STATE.json").write_text(json.dumps({"s6_burn_retry": {
                "VU-1": {"attempts": [{"retry": 1, "camera_wobble": True}]},
                "VU-2": {"attempts": [{"retry": 1}]}}}))
            self.assertEqual(bnp.s6_wobble_retry_units(Path(tmp), "E05"), {"VU-1"})
            self.assertEqual(bnp.s6_burn_retry_indices(Path(tmp), "E05"), {"VU-1": 1, "VU-2": 1})


class LockedOffClauseTest(unittest.TestCase):
    def test_locked_unit_states_the_set_stays_still(self):
        from tools.tests.test_h3_director_prompt_v2 import render
        import h3_director_prompt_v2 as v2
        text, _receipt = render()
        camera = text.split("\nCamera:\n", 1)[1].split("\n\n", 1)[0]
        self.assertIn(v2.LOCKED_OFF_STILL, camera)
        self.assertNotIn(v2.STEADY_MOVE, camera)
        self.assertIn(v2.FRAME_WOBBLE_NEVER, text.split("\nNever: ", 1)[1])
        for word in ("handheld", "shake", "sway", "follows"):
            self.assertNotIn(word, camera.lower())

    def test_moving_unit_keeps_its_move_and_stays_steady(self):
        from tools.tests import test_h3_director_prompt_v2 as tdp
        import h3_director_prompt_v2 as v2
        moving = {**tdp.CAMERA, "motion_family": "DOLLY", "motion_direction": "PUSH_IN"}
        with mock.patch.object(tdp, "CAMERA", moving):
            text, _receipt = tdp.render()
        camera = text.split("\nCamera:\n", 1)[1].split("\n\n", 1)[0]
        self.assertIn("dolly", camera.lower())
        self.assertIn(v2.STEADY_MOVE, camera)
        self.assertNotIn(v2.LOCKED_OFF_STILL, camera)

    def test_v1_tripod_clause_names_the_still_set(self):
        from tools import h3_provider_prompt_renderer as v1
        self.assertIn("the background and the frame stay perfectly still", v1.TRIPOD_CLAUSE)


# ===================================================================================== A. stabiliser fix
@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
class StabiliserTracksTheSetTest(unittest.TestCase):
    """The KO E05 cause: with whole-frame tracking the lock-off pass pinned the swaying actor and moved the set."""

    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"NALU_S6_WOBBLE_FACES": "off"})
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_still_set_is_left_alone_and_the_old_tracker_moved_it(self):
        import clip_lockoff_stabilize as cls
        with tempfile.TemporaryDirectory() as tmp:
            src = _write_clip(Path(tmp) / "VU-001.mp4", _scene(shake_px=0.0, sway_px=10.0))
            new = cls.stabilize_clip(src, Path(tmp) / "new", out_size=(W, H), face_guard=False)
            self.assertEqual(new["mode"], "NONE", new["reasons"])
            self.assertTrue(any(r.startswith(("SET_ALREADY_STILL", "ALREADY_LOCKED_OFF")) for r in new["reasons"]))
            self.assertEqual(new["feature_region"], "BACKGROUND")
            # the pre-fix whole-frame tracker "stabilises" the actor and the set starts moving
            old = cls.stabilize_clip(src, Path(tmp) / "old", out_size=(W, H), face_guard=False,
                                     background_only=False)
            if old["mode"] != "NONE":
                moved = wob.detect(Path(tmp) / "old" / src.name, faces=[], boxes=[SUBJECT_BOX])
                self.assertGreater(moved["metrics"]["excursion_pct"],
                                   wob.detect(src, faces=[], boxes=[SUBJECT_BOX])["metrics"]["excursion_pct"])

    def test_metrics_default_to_background_features(self):
        import camera_motion_metrics as cmm
        with tempfile.TemporaryDirectory() as tmp:
            src = _write_clip(Path(tmp) / "VU-002.mp4", _scene(shake_px=0.0, sway_px=10.0))
            row = cmm.measure_clip(src)
            self.assertEqual(row["feature_region"], "BACKGROUND")
            whole = cmm.measure_clip(src, background_only=False)
            self.assertEqual(whole["feature_region"], "WHOLE_FRAME")
            self.assertLessEqual(row["translation_px_per_s_median"], whole["translation_px_per_s_median"])


# =========================================================================================== A. S6 wiring
class S6WobbleWiringTest(unittest.TestCase):
    def _ctx(self, tmp: Path):
        video = tmp / "video"
        reports = tmp / "preproduction" / "reports"
        for d in (video, reports):
            d.mkdir(parents=True, exist_ok=True)
        (tmp / "tx.json").write_text(json.dumps({"tasks": [
            {"unit_id": "VU-1", "duration_seconds": 6, "camera_plan": {"motion_family": "LOCKED"}}]}))
        said: list[str] = []
        ctx = SimpleNamespace(episode="E05", dry=False, paid_enabled=True, say=said.append, run_id="RUN",
                              budget_check=lambda _c, label: {"budget_verdict": {"headroom_credits": 500}},
                              p=SimpleNamespace(preprod=tmp / "preproduction", video_media=video,
                                                preprod_reports=reports, video_transaction=tmp / "tx.json",
                                                assembly=tmp / "assembly"))
        return ctx, video, said

    def _patches(self, wobbles: dict[str, dict]):
        def check(_ctx, _uid, clip):
            return wobbles.get(Path(clip).read_text())
        return [mock.patch.object(P, "episode_video_model", lambda _e: "MiniMax-H3"),
                mock.patch.object(P, "episode_video_resolution", lambda _e: "480p"),
                mock.patch.object(P, "video_task_credits", lambda *_a, **_k: 7),
                mock.patch.object(P, "_owner_accepted_clips", lambda _c, _u: set()),
                mock.patch.object(P, "s6_sheet_leak_check", lambda *_a: None),
                mock.patch.object(P, "s6_camera_wobble_check", check),
                mock.patch.object(P, "kb_events", lambda *_a, **_k: {"status": "OK"}),
                mock.patch.object(br, "detect", lambda clip, **_k: {"status": "CLEAN", "burned_frames": 0,
                                                                     "frames_sampled": 18, "hits": []})]

    def test_wobble_take_is_parked_for_one_retry_then_kept_and_flagged(self):
        strong = {"status": "WOBBLE", "severity": "MILD", "reasons": ["COUPLED_TO_SUBJECT"],
                  "metrics": {"excursion_pct": 1.6, "coupling": 0.8}}
        with tempfile.TemporaryDirectory() as tmp:
            ctx, video, said = self._ctx(Path(tmp))
            patches = self._patches({"take1": strong, "take2": {**strong, "metrics": {"excursion_pct": 1.2}}})
            for p in patches:
                p.start()
            try:
                (video / "VU-1.mp4").write_text("take1")
                rows = P.s6_burn_check_landed(ctx, ["VU-1"])
                self.assertEqual(rows[0]["action"], "RETRY")
                self.assertFalse((video / "VU-1.mp4").is_file())  # parked: the wave machinery redoes it
                state = json.loads((ctx.p.preprod_reports / "E05_S6_WAVE_STATE.json").read_text())
                rec = state["s6_burn_retry"]["VU-1"]
                self.assertTrue(rec["attempts"][-1]["camera_wobble"])
                self.assertTrue(br.wobble_retry(rec))
                (video / "VU-1.mp4").write_text("take2")
                rows = P.s6_burn_check_landed(ctx, ["VU-1"])
                self.assertEqual((rows[0]["action"], rows[0]["reason"]), ("KEEP_BEST", "WOBBLE_RETRY_MAX_REACHED"))
                rec = json.loads((ctx.p.preprod_reports / "E05_S6_WAVE_STATE.json").read_text())[
                    "s6_burn_retry"]["VU-1"]
                self.assertTrue(rec["camera_wobble_unresolved"])
                self.assertFalse(rec["burned_text_unresolved"])  # a wobble is never reported as burned text
                self.assertEqual((video / "VU-1.mp4").read_text(), "take2")  # the smaller wobble is kept
                self.assertEqual(rec["kept_take_wobble"]["severity"], "MILD")
                self.assertTrue(any(line.startswith("S6_CAMERA_WOBBLE") for line in said))
                # S7 offers the kept MILD take to the <= 5 % lock-off pass
                with mock.patch.object(P, "_wave_state_path", lambda _c: ctx.p.preprod_reports
                                       / "E05_S6_WAVE_STATE.json"):
                    self.assertEqual(P.s7_wobble_stabilize_units(ctx), ["VU-1"])
            finally:
                for p in reversed(patches):
                    p.stop()

    def test_clean_take_leaves_no_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx, video, _said = self._ctx(Path(tmp))
            patches = self._patches({"ok": {"status": "CLEAN", "metrics": {"excursion_pct": 0.1}}})
            for p in patches:
                p.start()
            try:
                (video / "VU-1.mp4").write_text("ok")
                self.assertEqual(P.s6_burn_check_landed(ctx, ["VU-1"]), [])
                self.assertTrue((video / "VU-1.mp4").is_file())
            finally:
                for p in reversed(patches):
                    p.stop()


# ================================================================================ A/C. routing + checklist
class WobbleRoutingTest(unittest.TestCase):
    def test_item_and_wording_route_to_a_paid_redo_below_p0(self):
        self.assertEqual(ffr.classify("QA-CAMERA-WOBBLE", "background moves"), "CAMERA_WOBBLE")
        self.assertEqual(ffr.fix_class("CAMERA_WOBBLE"), ffr.PAID)
        self.assertEqual(ffr.classify("CRAFT-SHOT-GRAMMAR", "人物点头时背景跟着一起晃"), "CAMERA_WOBBLE")
        self.assertEqual(ffr.classify("OTHER", "the background moves along with the actor's gesture"),
                         "CAMERA_WOBBLE")
        self.assertEqual(ffr.classify("QA-EDIT-FRAGMENT", "a 1 s shot"), "EDIT_FRAGMENT")  # PR #295 class kept
        order = ffr.PAID_KINDS
        self.assertLess(order.index("REFERENCE_SHEET_LEAK"), order.index("CAMERA_WOBBLE"))
        self.assertLess(order.index("CAMERA_WOBBLE"), order.index("COSTUME_IDENTITY"))
        self.assertTrue(ffr.SENTENCES["CAMERA_WOBBLE"])
        mapped = [{"kind": "CAMERA_WOBBLE", "class": ffr.PAID, "unit_id": "VU-2", "severity": "P2",
                   "on_screen_seconds": 4},
                  {"kind": "BURNED_TEXT", "class": ffr.PAID, "unit_id": "VU-1", "severity": "P2",
                   "on_screen_seconds": 4},
                  {"kind": "SKIN_SHEEN", "class": ffr.PAID, "unit_id": "VU-3", "severity": "P2",
                   "on_screen_seconds": 4}]
        plan = ffr.plan_paid(mapped, budget=100, headroom=None, unit_cost=lambda _u: 7)
        self.assertEqual([r["unit_id"] for r in plan["selected"]], ["VU-1", "VU-2", "VU-3"])

    def test_unresolved_s6_wobble_joins_the_round_unless_stabilised(self):
        state = {"s6_burn_retry": {
            "VU-1": {"camera_wobble_unresolved": True, "unresolved_reason": "WOBBLE_RETRY_MAX_REACHED",
                     "attempts": [{"camera_wobble": True}], "kept_take_wobble": {"severity": "STRONG",
                                                                                 "excursion_pct": 4.0},
                     "checks": {"sha": {"camera_wobble": {"status": "WOBBLE", "excursion_pct": 4.0,
                                                          "reasons": ["JITTER"]}}}},
            "VU-2": {"camera_wobble_unresolved": True, "attempts": [{"camera_wobble": True}],
                     "kept_take_wobble": {"severity": "MILD"}}}}
        stab = {"results": [{"source": "/x/VU-2.mp4", "mode": "LOCK_OFF"}]}
        m = qadc.measure_camera_wobble(state, stab)
        self.assertEqual(len(m["measured"]), 1)
        self.assertEqual({r["unit_id"]: r["s7_stabilized"] for r in m["unresolved"]}, {"VU-1": False, "VU-2": True})
        record = qadc.build_record({"items": {}}, {"camera_wobble": m}, episode="E05")
        self.assertEqual([r["unit_id"] for r in record["s6_wobble_unresolved"]], ["VU-1"])
        self.assertEqual(record["items"]["QA-CAMERA-WOBBLE"]["status"], "MEASURED_FLAG_UNREVIEWED")
        self.assertEqual(record["items"]["QA-CAMERA-WOBBLE"]["routing"], "S6_UNIT_REDO_FINAL_FIX_ROUND")
        findings = ffr.collect_findings({}, record)
        wob_rows = [f for f in findings if f.get("item") == "QA-CAMERA-WOBBLE"]
        self.assertEqual(len(wob_rows), 1)
        self.assertEqual((wob_rows[0]["kind_hint"], wob_rows[0]["severity"]), ("CAMERA_WOBBLE", "P2"))

    def test_kb_global_model_constraint(self):
        self.assertEqual(kbe.FINAL_REVIEW_ROUTES["CAMERA_WOBBLE"], "MODEL_CONSTRAINT")
        self.assertIn("CAMERA_WOBBLE", kbe.GLOBAL_KINDS)
        self.assertEqual(kbe.final_review_scope({"item": "QA-CAMERA-WOBBLE", "text": "x"}, "CAMERA_WOBBLE")["scope"],
                         "global")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(kbe, "emit", lambda _rt, **kw: kw):
            out = kbe.record_s6_camera_wobble(Path(tmp), episode="E05", unit_id="VU-1",
                                              detection={"excursion_pct": 1.4, "reasons": ["COUPLED_TO_SUBJECT"]},
                                              clip_sha256="abc")
        self.assertEqual(out["status"], "OK")
        event = out["events"][0]
        self.assertEqual(event["failure_type"], "QA_DEFECT:QA-CAMERA-WOBBLE")
        self.assertEqual(event["evidence"]["lesson_route"], "MODEL_CONSTRAINT")
        self.assertEqual(event["evidence"]["kb_scope"], "global")


# ============================================================================================ B. distinctness
MEN = {
    "CHAR-LEAD": {"subject_id": "CHAR-LEAD", "name": "Sa", "sex": "male", "age": "30-35", "appearance": ""},
    "CHAR-WON": {"subject_id": "CHAR-WON", "name": "Won", "sex": "male", "age": "30-35", "appearance": ""},
    "CHAR-SEC": {"subject_id": "CHAR-SEC", "name": "Secretary", "sex": "male", "age": "28-40",
                 "appearance": "middle-aged Korean man, dark suit"},
    "CHAR-HER": {"subject_id": "CHAR-HER", "name": "Ha", "sex": "female", "age": "28-32", "appearance": ""},
}


def _cos(vectors):
    """embeddings {cid: [[i]]} and a cosine that reads a fixed pair table."""
    table = {frozenset(k): v for k, v in vectors.items()}
    return (lambda a, b: table.get(frozenset((a[0], b[0])), 0.0))


class DistinctnessTest(unittest.TestCase):
    ORDER = ["CHAR-LEAD", "CHAR-WON", "CHAR-SEC", "CHAR-HER"]

    def _eval(self, pairs, **kw):
        emb = {cid: [[cid]] for cid in self.ORDER}
        return cd.evaluate(emb, order=self.ORDER, cast=MEN, policy=kw.pop("policy", {}),
                           regenerable=kw.pop("regenerable", ()), cosine=_cos(pairs), **kw)

    def test_every_pair_is_scored_and_same_band_is_stricter(self):
        rep = self._eval({("CHAR-LEAD", "CHAR-SEC"): 0.35, ("CHAR-WON", "CHAR-HER"): 0.35},
                         regenerable=self.ORDER)
        self.assertEqual(len(rep["pairs"]), 6)  # all pairs, not only neighbours
        flagged = {r["pair"] for r in rep["too_similar"]}
        self.assertIn(cd.pair_key("CHAR-LEAD", "CHAR-SEC"), flagged)       # same sex, same band: 0.35 >= 0.32
        self.assertNotIn(cd.pair_key("CHAR-WON", "CHAR-HER"), flagged)     # different sex: 0.35 < 0.38
        self.assertEqual([r["subject_id"] for r in rep["regenerate"]], ["CHAR-SEC"])  # the later card

    def test_locked_cards_redesign_the_secondary_character_once(self):
        # KO E05: all three men locked since E01; Sa Je-yeon leads (15 units), the secretary 4, Won 1
        pairs = {("CHAR-LEAD", "CHAR-WON"): 0.637, ("CHAR-LEAD", "CHAR-SEC"): 0.622, ("CHAR-WON", "CHAR-SEC"): 0.54}
        screen = {"CHAR-LEAD": 60.0, "CHAR-SEC": 16.0, "CHAR-WON": 4.0}
        rep = self._eval(pairs, locked_regenerable={"CHAR-LEAD", "CHAR-WON", "CHAR-SEC"}, screen_time=screen)
        targets = {r["subject_id"]: r for r in rep["regenerate"]}
        self.assertEqual(set(targets), {"CHAR-WON", "CHAR-SEC"})
        self.assertNotIn("CHAR-LEAD", targets)                              # the lead keeps his card
        self.assertTrue(all(r["unlock_locked"] for r in targets.values()))
        block = targets["CHAR-SEC"]["block"]
        self.assertIn("本卡必须具备这些区分特征", block) if cd._cjk(block) else self.assertIn("exactly these", block)
        # once per card: a card already re-designed is never chosen again
        policy = {"regenerations": {"CHAR-WON": {"pairs": [], "block": "x"}, "CHAR-SEC": {"pairs": [], "block": "x"}}}
        again = self._eval(pairs, policy=policy, locked_regenerable={"CHAR-LEAD", "CHAR-WON", "CHAR-SEC"},
                           screen_time=screen)
        self.assertEqual(again["regenerate"], [])
        # cap per episode
        capped = self._eval(pairs, locked_regenerable={"CHAR-LEAD", "CHAR-WON", "CHAR-SEC"}, screen_time=screen,
                            locked_cap=1)
        self.assertEqual(len(capped["regenerate"]), 1)

    def test_traits_are_explicit_and_differ_from_the_lookalike(self):
        own, other = MEN["CHAR-SEC"], MEN["CHAR-LEAD"]
        a, b = cd.trait_plan(own, avoid=[cd.trait_plan(other)]), cd.trait_plan(other)
        self.assertTrue(all(a[t] != b[t] for t in a))
        en = cd.differentiation_block(own, [other], cosine=0.62, language="en")
        for word in ("face", "build", "age range"):
            self.assertIn(word, en)
        self.assertFalse(cd.has_facial_traits(own["appearance"]))
        self.assertIn("Concrete traits for this card", cd.contrast_block(own, MEN.values(), language="en"))
        self.assertTrue(cd.has_facial_traits("方脸宽下颌，浓眉，短发"))
        self.assertNotIn("本卡具体特征", cd.contrast_block({**own, "appearance": "方脸宽下颌，浓眉，短发"}, MEN.values()))


class LockedRedesignPipelineTest(unittest.TestCase):
    def test_unlock_supersedes_the_lock_and_copies_the_card_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "preproduction" / "E01" / "prompts"
            first.mkdir(parents=True)
            (first / "E01-CHAR-SEC.txt").write_text("secretary card prompt")
            lib = root / "asset_library.json"
            lib.write_text(json.dumps({"assets": {"characters": {"CHAR-SEC": {
                "status": "LOCKED", "version": 1, "qa": {"status": "PASS"},
                "artifacts": [{"path": "p.png", "source_reference": None}]}}}}))
            ctx = SimpleNamespace(episode="E05", paid_enabled=True, say=lambda _m: None,
                                  p=SimpleNamespace(rt_pre=root / "preproduction" / "E05",
                                                    prompt_dir=root / "preproduction" / "E05" / "prompts",
                                                    scope={"asset_library": lib, "character_sources": root / "src"}))
            with mock.patch.object(P, "ctx_render_style", lambda _c: "live_action"):
                library = json.loads(lib.read_text())
                self.assertTrue(P.s3_locked_card_redesignable(ctx, "CHAR-SEC", library))
                out = P.s3_unlock_locked_card(ctx, {"subject_id": "CHAR-SEC", "against": ["CHAR-LEAD"],
                                                    "cosine_before": 0.62})
            self.assertEqual(out["status"], "UNLOCKED")
            entry = json.loads(lib.read_text())["assets"]["characters"]["CHAR-SEC"]
            self.assertEqual(entry["status"], cd.LOCKED_SUPERSEDED_STATUS)
            self.assertEqual(entry["superseded_locks"][0]["status"], "LOCKED")
            self.assertEqual(entry["distinctness_regeneration"]["episode"], "E05")
            self.assertEqual((ctx.p.prompt_dir / "E05-CHAR-SEC.txt").read_text(), "secretary card prompt")
            # never again, and never an operator-photo card
            with mock.patch.object(P, "ctx_render_style", lambda _c: "live_action"):
                self.assertFalse(P.s3_locked_card_redesignable(ctx, "CHAR-SEC", json.loads(lib.read_text())))
                photo = {"assets": {"characters": {"CHAR-X": {"status": "LOCKED",
                                                               "artifacts": [{"source_reference": "src.png"}]}}}}
                self.assertFalse(P.s3_locked_card_redesignable(ctx, "CHAR-X", photo))

    def test_no_redesign_after_s6_started(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "video"
            video.mkdir()
            ctx = SimpleNamespace(p=SimpleNamespace(video_media=video))
            with mock.patch.object(P, "_wave_state_path", lambda _c: Path(tmp) / "none.json"):
                self.assertFalse(P.s3_s6_started(ctx))
                (video / "VU-1.mp4").write_bytes(b"x")
                self.assertTrue(P.s3_s6_started(ctx))


# ========================================================================================== C. Gemini detail
class GeminiDetailTest(unittest.TestCase):
    def test_prompts_name_the_classes_with_criteria_and_per_shot_rows(self):
        a = mp.build_pass_prompt("A", duration=60, context={"cuts": [{"start": 0, "end": 2}]})
        self.assertIn("QA-CAMERA-WOBBLE", a)
        self.assertIn("门框", a)                       # a concrete reference line to watch
        self.assertIn('"fail":[', a)
        self.assertIn("逐镜头清单", a)
        for cls in ("QA-BURNED-TEXT", "QA-REFERENCE-SHEET-LEAK", "QA-SKIN-SHEEN-DRIFT", "QA-HAND-ARTIFACT"):
            self.assertIn(cls, a)
        b = mp.build_pass_prompt("B", duration=60, context={"cards": [{"label": "角色A", "_sent": True}]})
        self.assertIn("QA-LOOKALIKE-CAST", b)
        self.assertIn("cast_compare", b)
        self.assertIn("同性别角色两两", b)
        c = mp.build_pass_prompt("C", duration=60)
        self.assertIn("QA-VOICE-GENDER", c)
        self.assertIn("QA-DIALOGUE-TAIL-CUT", c)
        d = mp.build_pass_prompt("D", duration=60)
        self.assertIn("QA-EDIT-FRAGMENT", d)
        self.assertIn("中位数", d)
        self.assertIn("CRAFT-ACTING-MONOTONY", d)
        self.assertEqual(mp.CLASS_TEXT["QA-CAMERA-WOBBLE"][0], "A")

    def test_per_shot_fail_without_finding_is_promoted(self):
        answer = json.dumps({"findings": [{"class": "QA-HAND-ARTIFACT", "start": 0.5, "end": 1.0}],
                             "shot_log": [{"shot": 1, "start": 0, "end": 2, "fail": ["QA-HAND-ARTIFACT"]},
                                          {"shot": 2, "start": 2, "end": 5, "fail": ["qa-camera-wobble", "BOGUS"],
                                           "note": "门框跟着晃"},
                                          {"shot": 3, "start": 5, "end": 7, "fail": []}],
                             "verdict": "PASS"})
        parsed = mp.parse_pass(answer, pid="A", duration=60)
        self.assertEqual(parsed["shot_log_rows"], 3)
        self.assertEqual(parsed["shot_log"][1]["fail"], ["QA-CAMERA-WOBBLE"])
        promoted = mp.promote_shot_checklist(parsed["shot_log"], parsed["findings"], "A")
        self.assertEqual([(f["item"], f["start"], f["severity"]) for f in promoted], [("QA-CAMERA-WOBBLE", 2.0, "P3")])
        self.assertTrue(promoted[0]["from_checklist"])

    def test_cast_compare_not_distinct_becomes_a_lookalike_finding(self):
        answer = json.dumps({"findings": [], "cast_compare": [
            {"a": "角色A", "b": "角色C", "distinct": False, "a_at": [3.0, 20.0], "b_at": [11.5], "note": "同脸同发型"},
            {"a": "角色A", "b": "角色B", "distinct": True, "a_at": [3.0], "b_at": [8.0]}], "verdict": "PASS"})
        parsed = mp.parse_pass(answer, pid="B", duration=60, offset=10.0)
        self.assertEqual(parsed["cast_compare"][0]["b_at"], [21.5])
        rows = mp.promote_cast_compare(parsed["cast_compare"], parsed["findings"])
        self.assertEqual([(r["item"], r["start"], r["severity"]) for r in rows], [("QA-LOOKALIKE-CAST", 13.0, "P2")])
        self.assertIn("21.5", rows[0]["evidence"])
        self.assertEqual(mp.promote_cast_compare(parsed["cast_compare"], [{"item": "QA-LOOKALIKE-CAST"}]), [])

    def test_wobble_suspects_reach_pass_a(self):
        ctx = {"shots": [{"unit": "VU-004", "start": 10.0, "end": 14.0}]}
        rows = mp.camera_wobble_suspects({"measured": [{"unit_id": "E05-VU-004", "excursion_pct": 1.4,
                                                        "coupling": 0.8}]}, ctx, 2)
        self.assertEqual((rows[0]["id"], rows[0]["window"]), ("S3", [10.0, 14.0]))
        self.assertEqual(mp.split_suspects({"camera_wobble": rows})["A"]["camera_wobble"], rows)
        prompt = mp.build_pass_prompt("A", duration=60, suspects=mp.split_suspects({"camera_wobble": rows})["A"])
        self.assertIn("suspect_checks", prompt)

    def test_mocked_run_merges_checklist_rows_and_stays_in_budget(self):
        def post(_url, data, _headers, _timeout):
            prompt = json.loads(data)["contents"][0]["parts"][-1]["text"]
            if "IDENTITY_CONTINUITY" in prompt:
                body = {"findings": [], "shot_log": [{"shot": 1, "start": 0, "end": 3, "who": ["角色A"], "fail": []}],
                        "cast_compare": [{"a": "角色A", "b": "角色B", "distinct": False, "a_at": [1.0], "b_at": [4.0]}],
                        "verdict": "PASS"}
            elif "PICTURE_AI_ARTEFACTS" in prompt:
                body = {"findings": [], "shot_log": [{"shot": 1, "start": 0, "end": 3, "fail": ["QA-CAMERA-WOBBLE"]}],
                        "verdict": "PASS"}
            else:
                body = {"findings": [], "verdict": "PASS"}
            payload = {"candidates": [{"content": {"parts": [{"text": json.dumps(body)}]}}],
                       "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 100}}
            return 200, json.dumps(payload).encode()

        def transcoder(_video, out, **_kw):
            Path(out).write_bytes(b"\x00" * 64)
            return Path(out)

        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "final.mp4"
            video.write_bytes(b"\x00")
            res = mp.run_passes(video=video, duration=90, model="gemini-3.8-flash",
                                prices={"gemini-3.8-flash": (50.25, 251.25)}, cap=8.0, key="k", base_url="http://x",
                                post=post, context={"cards": []}, leads={}, suspects={}, anime=False, craft=[],
                                measured_pacing=None, transcoder=transcoder, sleep=lambda _s: None,
                                response_text=lambda p: p["candidates"][0]["content"]["parts"][0]["text"],
                                actual_credits=lambda _m, _u: 0.1)
        self.assertLessEqual(res["plan"]["estimated_credits"], 8.0)
        items = sorted(f["item"] for f in res["merged"]["findings"])
        self.assertEqual(items, ["QA-CAMERA-WOBBLE", "QA-LOOKALIKE-CAST"])
        self.assertEqual(res["passes"]["A"]["shot_log_rows"], 1)


if __name__ == "__main__":
    unittest.main()
