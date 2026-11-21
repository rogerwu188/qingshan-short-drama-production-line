"""Own start keyframe after a tail rejection (PR #286 follow-up, device 0080 E05 VU-001, 2026-11-21).

S6's free declared-cast check rejected a motivated cut's predecessor tail, so the unit opens on its OWN keyframe.
The keyframe was generated and harvested, but the plate never reached ``keyframes/<shot>-keyframe-v1.png`` and S6
kept blocking OWN_KEYFRAME_NOT_GENERATED.  Offline, no paid call:

* S6-time rejection -> the S5 keyframe path is called once and the harvested plate is bound to the keyframe path;
* a plate already harvested (another run / a manual harvest) is bound without calling S5 again (no double charge);
  a plate older than the own-keyframe decision is never bound;
* a redo-switched own keyframe on disk without Q1 asks for exactly that still's review (not "not generated");
* the planner anticipates the rejection: the declared-cast check runs at plan time (S5 keyframe manifest, and S6
  before the predecessor's tail exists), and an own-start opener never "reuses" a tail-derived keyframe.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines" / "nalu" / "runtime" / "tools"))
sys.path.insert(0, str(ROOT / "tools"))

import build_keyframe_manifest as bkm  # noqa: E402
import nalu_pipeline as npl  # noqa: E402

STAMPED = {"camera_grammar_policy": "CAMERA_GRAMMAR_V1"}
SHOT = "E05-S01-02"
UID = "E05-VU-002"


def _member(name, cid, face="FRONT"):
    return {"character": name, "character_id": cid, "face_visibility": face}


JI, SEO = _member("지우", "CHAR-JI"), _member("서준", "CHAR-SEO")
# VU-002's tail (VU-001) shows Seo; VU-002 shows Ji with Seo only as an off-screen voice: same cast ids (so D-68 keeps
# it tail-derived), but the tail shows a character who is not on screen in VU-002 -> the declared-cast check rejects
EDITORIAL = {"shots": [
    {"shot_id": "E05-S01-01", "prompt_spec": {"dialogue": "서준：가자.", "cast": [SEO, JI]}},
    {"shot_id": SHOT, "prompt_spec": {"dialogue": "서준：여기야.", "cast": [JI, _member("서준", "CHAR-SEO",
                                                                                   "OFFSCREEN_VOICE_ONLY")]}},
    {"shot_id": "E05-S01-03", "prompt_spec": {"dialogue": "", "cast": [JI]}},
]}
PLAN = {"units": [{"unit_id": "E05-VU-001", "editorial_shot_ids": ["E05-S01-01"]},
                  {"unit_id": UID, "editorial_shot_ids": [SHOT]},
                  {"unit_id": "E05-VU-003", "editorial_shot_ids": ["E05-S01-03"]}]}


class Fixture:
    def __init__(self, tmp: Path):
        preprod = tmp / "preproduction"
        for sub in ("keyframes", "real_final_frames", "reports", "keyframe_harvest", "prompts/keyframes"):
            (preprod / sub).mkdir(parents=True, exist_ok=True)
        (tmp / "video").mkdir()
        (tmp / "contract.json").write_text(json.dumps(STAMPED))
        (preprod / "E05_VIDEO_UNIT_GROUPING_PLAN_V1.json").write_text(json.dumps(PLAN))
        editorial = preprod / "E05_EDITORIAL_SEEDANCE_MANIFEST_V1.json"
        editorial.write_text(json.dumps(EDITORIAL, ensure_ascii=False), encoding="utf-8")
        self.preprod = preprod
        self.kf = preprod / "keyframes" / f"{SHOT}-keyframe-v1.png"
        self.harvest = preprod / "keyframe_harvest"
        self.ctx = SimpleNamespace(
            episode="E05", dry=False, run_id="RUN1", say=lambda *_a, **_k: None, render_style="live_action",
            p=SimpleNamespace(preprod=preprod, preprod_reports=preprod / "reports", contract=tmp / "contract.json",
                              editorial=editorial, video_media=tmp / "video", keyframes=preprod / "keyframes",
                              keyframe_harvest_dir=self.harvest, q2_dir=preprod / "reports" / "qa" / "q2",
                              keyframe_manifest=preprod / "reports" / "E05_KEYFRAME_MANIFEST.json",
                              keyframe_manifest_report=preprod / "reports" / "E05_KEYFRAME_MANIFEST_REPORT.json"))
        info = {UID: {"previous_unit_id": "E05-VU-001", "first_shot_id": SHOT, "keyframe_path": self.kf}}
        self.patches = [mock.patch.object(npl, "continuity_derived_units", lambda _ctx: dict(info)),
                        mock.patch.object(npl, "hard_continuation_units", lambda _ctx: {}),
                        mock.patch.object(npl, "ENGINE", tmp / "engine")]

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()

    def tail(self):
        tail = self.preprod / "real_final_frames" / "E05-VU-001.png"
        tail.write_bytes(b"tail of VU-001 showing Seo")
        return tail

    def plate(self, name=f"E05_{SHOT}-KEYFRAME-V1_task-abc.png", data=b"own keyframe of Ji", age_s=0.0):
        path = self.harvest / name
        path.write_bytes(data)
        if age_s:
            t = time.time() - age_s
            os.utime(path, (t, t))
        return path


class _StopAfterOwnKeyframe(Exception):
    """Raised by the first call after the own-keyframe branch: the S6 loop got past it."""


def _run_s6(fx, stage_s5):
    with mock.patch.object(npl, "previs_gate", lambda *_a: {}), \
            mock.patch.object(npl, "release_unposted_waves", lambda *_a: []), \
            mock.patch.object(npl, "unit_dependency_order",
                              lambda _c: [("E05-VU-001", None, False), (UID, "E05-VU-001", True)]), \
            mock.patch.object(npl, "park_stale_real_final_frames", lambda *_a: []), \
            mock.patch.object(npl, "redo_switch_start_frames", lambda _c: []), \
            mock.patch.object(npl, "stage_s5", side_effect=stage_s5) as s5, \
            mock.patch.object(npl, "derived_units_pending_q1", side_effect=_StopAfterOwnKeyframe):
        (fx.ctx.p.video_media / "E05-VU-001.mp4").write_bytes(b"mp4")
        try:
            res = npl.stage_s6(fx.ctx)
        except _StopAfterOwnKeyframe:
            res = None
    return res, s5


class S6TimeTailRejectionTest(unittest.TestCase):
    def test_rejected_tail_generates_and_binds_the_own_keyframe(self):
        with tempfile.TemporaryDirectory() as d, Fixture(Path(d)) as fx:
            fx.tail()

            def s5(_ctx):  # the S5 keyframe path POSTed + harvested, but the plate stayed in the harvest dir
                fx.plate()
                return npl.StageResult(npl.PASS)
            res, s5_mock = _run_s6(fx, s5)
            self.assertIsNone(res, getattr(res, "blockers", None))  # the loop went on to the wave planner
            s5_mock.assert_called_once()
            self.assertEqual(fx.kf.read_bytes(), b"own keyframe of Ji")
            side = json.loads(fx.kf.with_suffix(".own_keyframe.json").read_text())
            self.assertEqual((side["unit_id"], side["action"]), (UID, "RENAMED"))
            row = npl.start_frame_source_decisions(fx.ctx)[UID]
            self.assertEqual(row["start_frame_source"], npl.START_FRAME_OWN)
            self.assertEqual(row["measurement"]["reasons"], ["TAIL_SHOWS_OFF_UNIT_CHARACTER:CHAR-SEO"])
            # the derived tail was never copied over the own keyframe
            self.assertFalse(fx.kf.with_suffix(".derived.json").exists())

    def test_still_missing_names_the_cause(self):
        with tempfile.TemporaryDirectory() as d, Fixture(Path(d)) as fx:
            fx.tail()
            res, s5_mock = _run_s6(fx, lambda _c: npl.StageResult(npl.PASS))
            s5_mock.assert_called_once()
            self.assertEqual(res.status, npl.BLOCKED)
            self.assertEqual(res.blockers, [f"S6.own_keyframe:OWN_KEYFRAME_NOT_GENERATED:{UID}"])
            self.assertEqual(res.details["own_keyframe_diagnosis"][UID]["first_shot_id"], SHOT)


class PreHarvestedKeyframeTest(unittest.TestCase):
    def test_harvested_plate_is_bound_without_calling_s5(self):
        with tempfile.TemporaryDirectory() as d, Fixture(Path(d)) as fx:
            fx.tail()
            npl.materialise_derived_keyframes(fx.ctx)  # records the own-keyframe decision
            time.sleep(0.01)
            fx.plate()  # the maintainer-authorised generation, harvested by another run
            res, s5_mock = _run_s6(fx, lambda _c: self.fail("S5 must not run: the image is already paid for"))
            self.assertIsNone(res)
            s5_mock.assert_not_called()
            self.assertEqual(fx.kf.read_bytes(), b"own keyframe of Ji")
            self.assertFalse(any(fx.harvest.glob("*.png")))

    def test_plate_in_a_harvest_status_report_is_copied(self):
        with tempfile.TemporaryDirectory() as d, Fixture(Path(d)) as fx:
            fx.tail()
            npl.materialise_derived_keyframes(fx.ctx)
            time.sleep(0.01)
            elsewhere = Path(d) / "manual_harvest" / "plate.png"
            elsewhere.parent.mkdir()
            elsewhere.write_bytes(b"manual plate")
            (fx.preprod / "reports" / "E05_KEYFRAME_HARVEST_STATUS.json").write_text(json.dumps({"results": [
                {"task_key": f"{SHOT}-KEYFRAME-V1", "task_id": "t-1", "remote_status": "completed",
                 "output_path": str(elsewhere), "sha256": npl.sha256_file(elsewhere)}]}))
            rows = npl.bind_harvested_own_keyframes(fx.ctx, [UID])
            self.assertEqual([(r["unit_id"], r["action"]) for r in rows], [(UID, "COPIED")])
            self.assertEqual(fx.kf.read_bytes(), b"manual plate")

    def test_plate_older_than_the_decision_is_not_bound(self):
        with tempfile.TemporaryDirectory() as d, Fixture(Path(d)) as fx:
            fx.tail()
            npl.materialise_derived_keyframes(fx.ctx)
            fx.plate(age_s=3600)  # a leftover of a superseded prompt
            self.assertEqual(npl.bind_harvested_own_keyframes(fx.ctx, [UID]), [])
            self.assertFalse(fx.kf.exists())


class RedoOwnKeyframeReviewTest(unittest.TestCase):
    def test_on_disk_but_unadmitted_asks_for_that_still(self):
        with tempfile.TemporaryDirectory() as d, Fixture(Path(d)) as fx:
            fx.kf.write_bytes(b"regenerated own keyframe")

            def review(_ctx, res, kind, **kw):
                res.status = npl.REVIEW_REQUIRED
                return {"review_kind": kind, "items": kw.get("items")}
            with mock.patch.object(npl, "own_keyframes_needed", lambda _c: [UID]), \
                    mock.patch.object(npl, "materialise_derived_keyframes", lambda _c: []), \
                    mock.patch.object(npl, "merge_keyframe_answers", lambda _c, shots: (None, [], list(shots))), \
                    mock.patch.object(npl, "request_review", side_effect=review):
                res, s5_mock = _run_s6(fx, lambda _c: self.fail("the image exists: no S5 / no POST"))
            s5_mock.assert_not_called()
            self.assertEqual(res.status, npl.REVIEW_REQUIRED)
            self.assertEqual(res.blockers, ["S6.q1_own:REVIEW_REQUIRED:1_frames"])
            self.assertEqual(res.details["items"], [SHOT])


class PlannerAnticipatesTest(unittest.TestCase):
    def test_s6_decides_before_the_predecessor_tail_exists(self):
        with tempfile.TemporaryDirectory() as d, Fixture(Path(d)) as fx:
            rows = npl.materialise_derived_keyframes(fx.ctx)  # no tail on disk yet
            self.assertEqual(rows[0]["status"], "OWN_KEYFRAME_REQUIRED")
            row = npl.start_frame_source_decisions(fx.ctx)[UID]
            self.assertTrue(row["decided_before_tail"])
            self.assertEqual(npl.own_keyframes_needed(fx.ctx), [UID])

    def _inputs(self, tmp: Path, decisions_reuse: bool = False):
        grouping = tmp / "grouping.json"
        grouping.write_text(json.dumps(PLAN))
        anchors = {"units": [{"unit_id": uid, "opening_anchor_contract": {"source": "CONTINUITY_DERIVED_KEYFRAME"}}
                             for uid in (UID, "E05-VU-003")]}
        contract = {"episode": "E05", "camera_grammar_policy": "CAMERA_GRAMMAR_V1",
                    "shots": [{"shot_id": s["shot_id"], "scene_id": "SC1", "prompt_spec": s["prompt_spec"]}
                              for s in EDITORIAL["shots"]]}
        return SimpleNamespace(contract=contract, episode="E05", grouping_plan_path=grouping, anchor_plan=anchors,
                               seedance=EDITORIAL, dir=tmp)

    def test_keyframe_manifest_plans_the_own_keyframe(self):
        with tempfile.TemporaryDirectory() as d:
            inputs = self._inputs(Path(d))
            # VU-002: cast ids equal (Seo off screen), so D-68 alone would defer it to the tail; the declared-cast
            # check rejects that tail -> its opener is generated in S5.  VU-003 (tail shows Ji only... and Seo is
            # not in VU-003) is handled by the existing cast-differs rule.
            self.assertNotIn(SHOT, bkm.derived_opener_shot_ids(inputs))
            self.assertIn(SHOT, bkm.derived_opener_shot_ids(inputs, camera_grammar=False))
            self.assertEqual(bkm.own_start_opener_shot_ids(inputs), {SHOT})

    def test_own_start_opener_never_reuses_a_tail_derived_keyframe(self):
        with tempfile.TemporaryDirectory() as d:
            inputs = self._inputs(Path(d))
            rows = [{"shot_id": SHOT, "decision": "REUSE_NO_NEW_KEYFRAME",
                     "reuse_mode": "EXACT_SHA_REUSE_OF_EARLIER_KEYFRAME", "reuse_source": "E05-S01-01"},
                    {"shot_id": "E05-S01-03", "decision": "REUSE_NO_NEW_KEYFRAME",
                     "reuse_mode": "EXACT_SHA_REUSE_OF_EARLIER_KEYFRAME", "reuse_source": "E05-S01-01"}]
            changed = bkm.promote_own_start_openers(inputs, rows, derived_openers={"E05-S01-01"})
            self.assertEqual([r["shot_id"] for r in changed], [SHOT])
            self.assertEqual(rows[0]["decision"], "NEW_KEYFRAME")
            self.assertEqual(rows[1]["decision"], "REUSE_NO_NEW_KEYFRAME")
            # a reuse of a real generated keyframe stays a reuse (no extra credits)
            again = [{"shot_id": SHOT, "decision": "REUSE_NO_NEW_KEYFRAME",
                      "reuse_mode": "EXACT_SHA_REUSE_OF_EARLIER_KEYFRAME", "reuse_source": "E05-S01-01"}]
            self.assertEqual(bkm.promote_own_start_openers(inputs, again, derived_openers=set()), [])


if __name__ == "__main__":
    unittest.main()
