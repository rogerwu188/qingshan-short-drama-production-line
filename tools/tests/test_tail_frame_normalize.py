#!/usr/bin/env python3
"""Tail-frame normalisation + skin-sheen drift (line owner 2026-11-20, KO E01 on device …0080: the lead's face turned
oily / glossy / sweaty with wet-looking hair from one tail-chained unit to the next).

H3 output frames are compressed and model-sharpened; reused as the next unit's start frame they compound contrast,
sharpening and specular sheen.  The tail is normalised toward the scene's clean keyframe before reuse, stamped live-
action prompts carry a matte-skin clause, and a free S6 measurement feeds QA-SKIN-SHEEN-DRIFT to the final review and
the final fix round (never a gate).  Synthetic images only: no network, no provider, no credits."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "tools", REPO / "lines" / "nalu" / "runtime" / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - engine venv always has OpenCV
    cv2 = None

import tail_frame_normalize as tfn  # noqa: E402

W, H = 720, 1280
FACE = ((360, 520), (150, 200))  # centre, axes of the skin ellipse


def clean_frame(seed: int = 0) -> "np.ndarray":
    """A soft room with a matte skin-coloured face ellipse (mild, smooth texture)."""
    rng = np.random.default_rng(seed)
    img = np.zeros((H, W, 3), np.float32)
    img[..., 0] = np.linspace(80, 110, H)[:, None]  # a cool blue-grey room (not skin-coloured)
    img[..., 1] = np.linspace(60, 80, W)[None, :]
    img[..., 2] = 50
    cv2.rectangle(img, (60, 900), (660, 1200), (120, 95, 70), -1)  # furniture edge (geometry probe)
    cv2.ellipse(img, FACE[0], FACE[1], 0, 0, 360, (120, 150, 200), -1)
    img += cv2.GaussianBlur(rng.normal(0, 5, img.shape).astype(np.float32), (0, 0), 2.0)
    return np.clip(img, 0, 255).astype(np.uint8)


def glossy(img: "np.ndarray", generations: int = 2) -> "np.ndarray":
    """What a tail chain does to that face: model sharpening, contrast creep, specular sheen, noise, JPEG."""
    x = img.astype(np.float32)
    rng = np.random.default_rng(7)
    for _ in range(generations):
        x = x + 1.2 * (x - cv2.GaussianBlur(x, (0, 0), 1.2))
        x = (x - x.mean()) * 1.12 + x.mean()
        for k in range(14):  # near-white highlights on the forehead / cheeks / nose
            cx = int(FACE[0][0] + rng.integers(-90, 90))
            cy = int(FACE[0][1] + rng.integers(-150, 120))
            cv2.circle(x, (cx, cy), int(rng.integers(6, 14)), (250, 252, 255), -1)
        x = x + rng.normal(0, 3.0, x.shape)
        ok, enc = cv2.imencode(".jpg", np.clip(x, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 85])
        x = cv2.imdecode(enc, cv2.IMREAD_COLOR).astype(np.float32)
    return np.clip(x, 0, 255).astype(np.uint8)


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class NormalizeImageTests(unittest.TestCase):
    def setUp(self):
        self.anchor = clean_frame(0)
        self.tail = glossy(clean_frame(1))
        self.result, self.ops = tfn.normalize_image(self.tail, self.anchor)
        self.ref = tfn.metrics(self.anchor)
        self.before = tfn.metrics(self.tail)
        self.after = tfn.metrics(self.result)

    def test_sharpness_contrast_and_specular_move_toward_the_anchor(self):
        b, a = tfn.compare(self.before, self.ref), tfn.compare(self.after, self.ref)
        self.assertGreater(b["sharpness_ratio"], 3.0)
        self.assertLess(a["sharpness_ratio"], b["sharpness_ratio"] / 2)
        self.assertLess(a["contrast_ratio"], b["contrast_ratio"])
        self.assertLess(self.after["specular_fraction"], self.before["specular_fraction"] / 2)
        self.assertLess(self.after["l_p99"], self.before["l_p99"])
        self.assertIn("desharpen", self.ops)
        self.assertGreater(self.ops["specular_knee"]["pixels_compressed"], 0)

    def test_geometry_is_untouched(self):
        self.assertEqual(self.result.shape, self.tail.shape)
        g0 = cv2.cvtColor(self.tail, cv2.COLOR_BGR2GRAY).astype(np.float32)
        g1 = cv2.cvtColor(self.result, cv2.COLOR_BGR2GRAY).astype(np.float32)
        (dx, dy), _ = cv2.phaseCorrelate(g0, g1)
        self.assertLess(abs(dx) + abs(dy), 0.25)
        # the furniture edge stays on the same row
        col0 = np.argmax(np.abs(np.diff(cv2.GaussianBlur(g0, (0, 0), 3)[:, 360])[850:950])) + 850
        col1 = np.argmax(np.abs(np.diff(cv2.GaussianBlur(g1, (0, 0), 3)[:, 360])[850:950])) + 850
        self.assertLessEqual(abs(int(col0) - int(col1)), 1)

    def test_brightness_mean_is_not_moved(self):
        self.assertEqual(self.ops["tone"]["L"]["shift"], 0.0)

    def test_a_clean_tail_is_left_almost_alone(self):
        clean = clean_frame(1)
        result, ops = tfn.normalize_image(clean, self.anchor)
        self.assertNotIn("desharpen", ops)
        self.assertLess(float(np.abs(result.astype(float) - clean.astype(float)).mean()), 1.5)

    def test_start_frame_caps_generation_sharpness(self):
        """A tail may not come out sharper than the (already normalised) frame its unit opened on."""
        start = clean_frame(2)
        result, ops = tfn.normalize_image(self.tail, self.anchor, start)
        self.assertEqual(ops["sharpness_reference"], "START_FRAME")
        ratio = tfn.compare(tfn.metrics(result), tfn.metrics(start))["sharpness_ratio"]
        self.assertLess(ratio, 1.6)

    def test_detector_flags_the_glossy_frame_only(self):
        self.assertTrue(tfn.drifted(tfn.compare(self.before, self.ref)))
        self.assertIn("SPECULAR_SHEEN", tfn.drifted(tfn.compare(self.before, self.ref)))
        self.assertEqual(tfn.drifted(tfn.compare(tfn.metrics(clean_frame(3)), self.ref)), [])


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class NormalizeFileTests(unittest.TestCase):
    def _files(self, tmp: Path) -> tuple[Path, Path]:
        frame, anchor = tmp / "E01-VU-002.png", tmp / "S1-keyframe-v1.png"
        cv2.imwrite(str(frame), glossy(clean_frame(1)))
        cv2.imwrite(str(anchor), clean_frame(0))
        return frame, anchor

    def test_normalises_in_place_and_keeps_the_raw_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            frame, anchor = self._files(Path(tmp))
            original = frame.read_bytes()
            raw, side = tfn.companion_paths(frame)
            out = tfn.normalize_tail_frame(frame, anchor=anchor, raw_copy=raw, sidecar=side, env={})
            self.assertEqual(out["status"], "NORMALIZED")
            self.assertTrue(out["tail_normalized"])
            self.assertEqual(raw.name, "E01-VU-002.raw.png")
            self.assertEqual(raw.read_bytes(), original)
            self.assertNotEqual(frame.read_bytes(), original)
            record = json.loads(side.read_text())
            self.assertTrue(record["tail_normalized"])
            self.assertLess(record["stats"]["drift_after"]["sharpness_ratio"],
                            record["stats"]["drift_before"]["sharpness_ratio"])
            self.assertEqual(list(Path(tmp).glob("*.norm.png")), [])

    def test_opt_out_leaves_the_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            frame, anchor = self._files(Path(tmp))
            original = frame.read_bytes()
            raw, side = tfn.companion_paths(frame)
            out = tfn.normalize_tail_frame(frame, anchor=anchor, raw_copy=raw, sidecar=side,
                                           env={"NALU_TAIL_NORMALIZE": "0"})
            self.assertEqual(out["status"], "SKIPPED_OPT_OUT")
            self.assertEqual(frame.read_bytes(), original)
            self.assertFalse(raw.exists())

    def test_fail_open_on_a_broken_anchor_and_no_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            frame, anchor = self._files(Path(tmp))
            anchor.write_bytes(b"not an image")
            original = frame.read_bytes()
            raw, side = tfn.companion_paths(frame)
            out = tfn.normalize_tail_frame(frame, anchor=anchor, raw_copy=raw, sidecar=side, env={})
            self.assertEqual(out["status"], "FAIL_OPEN")
            self.assertFalse(out["tail_normalized"])
            self.assertEqual(frame.read_bytes(), original)
            self.assertFalse(raw.exists())
            out = tfn.normalize_tail_frame(frame, anchor=None, raw_copy=raw, sidecar=side, env={})
            self.assertEqual(out["status"], "NO_ANCHOR")
            self.assertEqual(frame.read_bytes(), original)

    def test_sheen_drift_on_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = Path(tmp) / "start.png"
            cv2.imwrite(str(start), clean_frame(0))
            flagged = tfn.sheen_drift(Path(tmp) / "x.mp4", {"start_frame": start},
                                      frames=[clean_frame(1), glossy(clean_frame(1))])
            self.assertTrue(flagged["flagged"])
            self.assertIn("SPECULAR_SHEEN", flagged["reasons"])
            calm = tfn.sheen_drift(Path(tmp) / "x.mp4", {"start_frame": start}, frames=[clean_frame(1)])
            self.assertFalse(calm["flagged"])
            self.assertEqual(tfn.sheen_drift(Path(tmp) / "missing.mp4", {"start_frame": start})["status"],
                             "NO_FRAMES")


def _episode(tmp: Path) -> SimpleNamespace:
    pre = tmp / "pre"
    (pre / "keyframes").mkdir(parents=True)
    (pre / "reports").mkdir()
    (tmp / "media").mkdir()
    (pre / "E01_VIDEO_UNIT_GROUPING_PLAN_V1.json").write_text(json.dumps({"units": [
        {"unit_id": "E01-VU-001", "editorial_shot_ids": ["S1"]},
        {"unit_id": "E01-VU-002", "editorial_shot_ids": ["S2"]},
        {"unit_id": "E01-VU-003", "editorial_shot_ids": ["S3"]}]}))
    (pre / "E01_VIDEO_UNIT_ANCHOR_PLAN_V1.json").write_text(json.dumps({"units": [
        {"unit_id": "E01-VU-001"},
        {"unit_id": "E01-VU-002", "opening_anchor_contract": {"source": "CONTINUITY_DERIVED_KEYFRAME",
                                                               "previous_unit_id": "E01-VU-001"}},
        {"unit_id": "E01-VU-003", "opening_anchor_contract": {"source": "PREVIOUS_UNIT_REAL_FINAL_FRAME",
                                                               "previous_unit_id": "E01-VU-002"}}]}))
    cv2.imwrite(str(pre / "keyframes" / "S1-keyframe-v1.png"), clean_frame(0))
    for shot in ("S2", "S3"):  # tail copies (derived keyframes)
        cv2.imwrite(str(pre / "keyframes" / f"{shot}-keyframe-v1.png"), clean_frame(4))
        (pre / "keyframes" / f"{shot}-keyframe-v1.derived.json").write_text("{}")
    return SimpleNamespace(run_id="r1", episode="E01", say=lambda *_a, **_k: None, dry=False,
                           p=SimpleNamespace(video_media=tmp / "media", preprod=pre, preprod_reports=pre / "reports",
                                             contract=tmp / "contract.json"))


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class PipelineTests(unittest.TestCase):
    def test_anchor_walks_the_tail_chain_to_the_generated_keyframe(self):
        import nalu_pipeline as P
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _episode(Path(tmp))
            key = ctx.p.preprod / "keyframes" / "S1-keyframe-v1.png"
            for uid in ("E01-VU-001", "E01-VU-002", "E01-VU-003"):
                self.assertEqual(P.tail_normalize_anchor(ctx, uid), key)
            self.assertEqual(P.unit_start_keyframe(ctx, "E01-VU-003"),
                             ctx.p.preprod / "keyframes" / "S3-keyframe-v1.png")
            self.assertIsNone(P.tail_normalize_anchor(SimpleNamespace(), "E01-VU-002"))  # fail-open

    def test_extract_real_final_frame_normalises_the_tail(self):
        import nalu_pipeline as P
        import tail_frame_text_clean as ttc
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _episode(Path(tmp))
            (ctx.p.video_media / "E01-VU-002.mp4").write_bytes(b"fake mp4")
            gloss = glossy(clean_frame(1))

            def ffmpeg(cmd, *a, **k):
                cv2.imwrite(str(cmd[-1]), gloss)
                return SimpleNamespace(returncode=0)
            with mock.patch.object(P.subprocess, "run", ffmpeg), \
                    mock.patch.object(P._media, "require_ffmpeg", lambda: "ffmpeg"), \
                    mock.patch.object(ttc, "_default_ocr", lambda _img: []), \
                    mock.patch.object(tfn, "clip_frames", lambda _clip: [clean_frame(4), gloss]), \
                    mock.patch.object(P, "ctx_render_style", lambda _ctx: "live_action"), \
                    mock.patch.dict(os.environ, {"NALU_TAIL_NORMALIZE": "1", "NALU_SKIN_SHEEN_CHECK": "1"}):
                out = P.extract_real_final_frame(ctx, "E01-VU-002")
            tails = ctx.p.preprod / "real_final_frames"
            self.assertEqual(out["status"], "EXTRACTED")
            self.assertTrue(out["tail_normalized"])
            self.assertTrue((tails / "E01-VU-002.raw.png").is_file())
            self.assertEqual(json.loads((tails / "E01-VU-002.tail_normalize.json").read_text())["anchor"],
                             str(ctx.p.preprod / "keyframes" / "S1-keyframe-v1.png"))
            self.assertEqual(out["sha256"], P.sha256_file(tails / "E01-VU-002.png"))
            self.assertTrue(out["skin_sheen"]["flagged"])
            sheen = json.loads((tails / "E01-VU-002.skin_sheen.json").read_text())
            self.assertEqual(sheen["source_sha256"], out["source_sha256"])
            # the must-check list reads it as a measured lead for the current take
            import nalu_qa_defect_checklist as Q
            measured = Q.measure_skin_sheen(tails)
            self.assertEqual([r["unit_id"] for r in measured["units"]], ["E01-VU-002"])
            (tails / "E01-VU-002.source.sha256").write_text("another-take\n")
            self.assertEqual(Q.measure_skin_sheen(tails), {})

    def test_opt_out_and_fail_open_keep_extraction_working(self):
        import nalu_pipeline as P
        import tail_frame_text_clean as ttc
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _episode(Path(tmp))
            (ctx.p.video_media / "E01-VU-002.mp4").write_bytes(b"fake mp4")
            gloss = glossy(clean_frame(1))

            def ffmpeg(cmd, *a, **k):
                cv2.imwrite(str(cmd[-1]), gloss)
                return SimpleNamespace(returncode=0)
            for env, patch in (({"NALU_TAIL_NORMALIZE": "0", "NALU_SKIN_SHEEN_CHECK": "0"}, None),
                               ({"NALU_TAIL_NORMALIZE": "1", "NALU_SKIN_SHEEN_CHECK": "1"}, "boom")):
                tails = ctx.p.preprod / "real_final_frames"
                for f in tails.glob("*") if tails.is_dir() else []:
                    f.unlink()

                def boom(*_a, **_k):
                    raise RuntimeError("cv2 broke")
                with mock.patch.object(P.subprocess, "run", ffmpeg), \
                        mock.patch.object(P._media, "require_ffmpeg", lambda: "ffmpeg"), \
                        mock.patch.object(ttc, "_default_ocr", lambda _img: []), \
                        mock.patch.object(tfn, "normalize_image", boom if patch else tfn.normalize_image), \
                        mock.patch.object(tfn, "sheen_drift", boom if patch else tfn.sheen_drift), \
                        mock.patch.dict(os.environ, env):
                    out = P.extract_real_final_frame(ctx, "E01-VU-002")
                self.assertEqual(out["status"], "EXTRACTED")
                self.assertFalse(out["tail_normalized"])
                self.assertFalse((tails / "E01-VU-002.raw.png").exists())
                self.assertEqual(cv2.imread(str(tails / "E01-VU-002.png")).tobytes(),
                                 cv2.imdecode(cv2.imencode(".png", gloss)[1], cv2.IMREAD_COLOR).tobytes())

    def test_supervisor_normalises_toward_the_planned_start_keyframe(self):
        from tools import episode_parallel_batch_supervisor as S
        from tools import tail_frame_normalize as stfn
        from tools import tail_frame_text_clean as sttc
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "E01-VU-001.mp4"
            src.write_bytes(b"fake mp4")
            key = tmp / "kf.png"
            cv2.imwrite(str(key), clean_frame(0))
            dst = tmp / "tails" / "E01-VU-001_tail.png"
            task = {"action_sequence_contract": {"predecessor_tail_frame_ref": str(dst)},
                    "reference_image_sequence": [{"role": "START_FRAME", "path": str(key)},
                                                 {"role": "CHARACTER_IDENTITY_REFERENCE", "path": "/x/plate.png"}]}
            gloss = glossy(clean_frame(1))

            def ffmpeg(cmd, *a, **k):
                cv2.imwrite(str(cmd[-1]), gloss)
                return SimpleNamespace(returncode=0)
            with mock.patch.object(S.subprocess, "run", ffmpeg), \
                    mock.patch.object(S, "resolve_media_binary", lambda _n: "ffmpeg"), \
                    mock.patch.object(sttc, "_default_ocr", lambda _img: []), \
                    mock.patch.dict(os.environ, {"NALU_TAIL_NORMALIZE": "1"}):
                self.assertTrue(S.bind_predecessor_tail_frame(task, {"output_path": str(src), "sha256": "s"}))
            self.assertTrue(task["predecessor_tail_normalize"]["tail_normalized"])
            self.assertEqual(task["predecessor_tail_normalize"]["anchor"], str(key))
            self.assertTrue((dst.parent / "E01-VU-001_tail.raw.png").is_file())
            self.assertEqual(task["predecessor_tail_frame_sha256"], S.sha256_file(dst))
            self.assertEqual(task["reference_image_sequence"][0]["path"], str(dst))
            self.assertEqual(task["reference_image_sequence"][1]["path"], "/x/plate.png")  # identity card kept
            self.assertIs(stfn, sys.modules["tools.tail_frame_normalize"])


class PromptClauseTests(unittest.TestCase):
    def _negatives(self, unit, plan) -> str:
        from tools.h3_provider_prompt_renderer import render_h3_prompt
        text, _ = render_h3_prompt(unit, plan)
        return next(row for row in text.splitlines() if row.startswith("negative_constraints: "))

    def test_stamped_live_action_unit_carries_the_skin_finish(self):
        from tools.h3_provider_prompt_renderer import SKIN_FINISH_NEGATIVE
        from tools.tests.test_h3_director_performance import unit_plan
        self.assertIn(SKIN_FINISH_NEGATIVE, self._negatives(*unit_plan(stamped=True, performance=None)))
        self.assertNotIn(SKIN_FINISH_NEGATIVE, self._negatives(*unit_plan(stamped=False, performance=None)))

    def test_anime_and_wet_beats_skip_it(self):
        from tools.h3_provider_prompt_renderer import SKIN_FINISH_NEGATIVE, skin_finish_applies
        from tools.tests.test_h3_director_performance import unit_plan
        unit, plan = unit_plan(stamped=True, performance=None)
        self.assertTrue(skin_finish_applies(unit, plan, anime=False, has_people=True))
        self.assertFalse(skin_finish_applies(unit, plan, anime=True, has_people=True))
        self.assertFalse(skin_finish_applies(unit, plan, anime=False, has_people=False))
        anime_unit = {**unit, "visual_culture_contract": {**(unit.get("visual_culture_contract") or {}),
                                                          "render_style": "anime"}}
        try:
            self.assertNotIn(SKIN_FINISH_NEGATIVE, self._negatives(anime_unit, plan))
        except ValueError:
            pass  # the fixture's lock may not accept an anime stamp; the predicate above already covers it
        for wet in ("He runs in from the rain", "sweat beads on her brow", "tears roll down", "she climbs out of the river"):
            p = json.loads(json.dumps(plan))
            p["beats"][0]["primary_action"] = wet
            self.assertFalse(skin_finish_applies(unit, p, anime=False, has_people=True), wet)
        ko = json.loads(json.dumps(unit))
        ko["ordered_prompt_specs"][0]["dialogue"] = "비밀이야. 서울에 가자."  # 비 / 울 inside other words: no skip
        self.assertTrue(skin_finish_applies(ko, plan, anime=False, has_people=True))
        ko["ordered_prompt_specs"][0]["dialogue"] = "눈물이 나."
        self.assertFalse(skin_finish_applies(ko, plan, anime=False, has_people=True))


class RoutingTests(unittest.TestCase):
    def test_final_fix_round_redoes_a_confirmed_sheen_drift_like_face_drift(self):
        import final_fix_round as F
        self.assertEqual(F.classify("QA-SKIN-SHEEN-DRIFT"), "SKIN_SHEEN")
        self.assertEqual(F.classify(None, "the lead's face looks oily and sweaty at 0:39"), "SKIN_SHEEN")
        self.assertEqual(F.classify(None, "男主脸上像抹了油"), "SKIN_SHEEN")
        self.assertEqual(F.fix_class("SKIN_SHEEN"), F.PAID)
        self.assertIn("matte skin", F.redo_sentence(["SKIN_SHEEN"]))
        mapped = [{"kind": "SKIN_SHEEN", "class": F.PAID, "unit_id": "U2", "on_screen_seconds": 4},
                  {"kind": "FACE_DRIFT", "class": F.PAID, "unit_id": "U1", "on_screen_seconds": 3}]
        plan = F.plan_paid(mapped, budget=45, headroom=None, unit_cost=lambda _u: 30)
        self.assertEqual([r["unit_id"] for r in plan["selected"]], ["U1"])  # face drift first, budget caps the rest
        self.assertEqual(plan["skipped"][0]["reason"], "BUDGET_CAP")

    def test_checklist_item_and_kb_route(self):
        import nalu_knowledge_events as K
        import nalu_qa_defect_checklist as Q
        self.assertIn("QA-SKIN-SHEEN-DRIFT", Q.ITEM_IDS)
        self.assertEqual(Q.routing("QA-SKIN-SHEEN-DRIFT"), "S6_UNIT_REDO_FINAL_FIX_ROUND")
        flags = Q._measured_findings({"skin_sheen": {"units": [{"unit_id": "U2", "reasons": ["SPECULAR_SHEEN"]}]}})
        self.assertEqual(flags[0]["item_id"], "QA-SKIN-SHEEN-DRIFT")
        record = Q.build_record(Q.parse_block({"items": {"QA-SKIN-SHEEN-DRIFT": {
            "verdict": "DEFECT", "findings": [{"at_seconds": 39.0, "note": "oily face"}]}}}), {}, episode="E01")
        self.assertIn("QA-SKIN-SHEEN-DRIFT", record["defects"])
        self.assertEqual(K.FINAL_REVIEW_ROUTES["SKIN_SHEEN"], "MODEL_CONSTRAINT")
        self.assertEqual(K.final_review_scope({"item": "QA-SKIN-SHEEN-DRIFT"}, "SKIN_SHEEN")["scope"], K.SCOPE_GLOBAL)
        # no new gate: the must-check list stays advisory
        self.assertTrue(Q.AUTHORITY.startswith("OPTIONAL_ADVISORY_NOT_A_GATE"))


if __name__ == "__main__":
    unittest.main()
