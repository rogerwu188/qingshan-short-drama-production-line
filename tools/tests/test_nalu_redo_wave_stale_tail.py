#!/usr/bin/env python3
"""A redo wave must not be frozen by the parked take, nor start from the parked take's tail.

Device 0030 E15, 2026-11-15: 22 clips were parked for a controlled redo.  The redo wave 25 was
opened and never POSTed, yet the old takes' SUBMITTED_TASK_ID_BOUND records kept its membership
frozen; and because real_final_frames/E15-VU-002.png (cut from the parked clip) was still on
disk, the hard-continuation successor VU-003 was planned into the same wave as VU-002 and bound
to the tail of a clip that no longer existed.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import nalu_pipeline as P  # noqa: E402


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RedoWaveStaleTailTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.preprod = root / "preproduction"
        self.tails = self.preprod / "real_final_frames"; self.tails.mkdir(parents=True)
        self.keyframes = self.preprod / "keyframes"; self.keyframes.mkdir()
        self.video = root / "video"; self.video.mkdir()
        self.reports = root / "reports"; self.reports.mkdir()
        self.engine = root / "engine"
        self.store = self.engine / "workflow/tasks/giggle_video_submit_transactions/E15"
        self.store.mkdir(parents=True)
        self.receipts = self.engine / "reports/start_frame_evidence"; self.receipts.mkdir(parents=True)
        (self.preprod / "E15_VIDEO_UNIT_GROUPING_PLAN_V1.json").write_text(json.dumps({"units": [
            {"unit_id": "E15-VU-002", "editorial_shot_ids": ["E15-S01-02"]},
            {"unit_id": "E15-VU-003", "editorial_shot_ids": ["E15-S01-03"]}]}))
        (self.preprod / "E15_VIDEO_UNIT_ANCHOR_PLAN_V1.json").write_text(json.dumps({"units": [
            {"unit_id": "E15-VU-002"},
            {"unit_id": "E15-VU-003", "opening_anchor_contract": {
                "source": "PREVIOUS_UNIT_REAL_FINAL_FRAME", "previous_unit_id": "E15-VU-002"}}]}))
        self.ctx = SimpleNamespace(episode="E15", run_id="RUN", dry=False,
                                   p=SimpleNamespace(preprod=self.preprod, video_media=self.video,
                                                     keyframes=self.keyframes))
        self._engine = P.ENGINE
        P.ENGINE = self.engine
        self.units = ["E15-VU-002", "E15-VU-003"]

    def tearDown(self):
        P.ENGINE = self._engine
        self._tmp.cleanup()

    # -- wave release ---------------------------------------------------------------------------
    def bind(self, uid, when):
        (self.store / f"{uid}__fp.json").write_text(json.dumps(
            {"state": "SUBMITTED_TASK_ID_BOUND", "task_id": f"t-{uid}", "task_key": uid,
             "response_recorded_at": when}))

    def park_clip(self, uid):
        park = self.video / "_superseded_20261115_first_controlled_redo"; park.mkdir(exist_ok=True)
        (park / f"{uid}.mp4").write_bytes(b"old take")

    def wave(self, n):
        return {"wave": n, "units": list(self.units), "opened_at": "t",
                "submit_report": str(self.reports / f"submit_wave{n}.json")}

    def test_a_redo_wave_that_never_posted_is_released_despite_the_parked_takes_records(self):
        for uid in self.units:
            self.bind(uid, "2026-11-15T03:00:00Z")
            self.park_clip(uid)
        state = {"waves": [self.wave(25)]}
        released = P.release_unposted_waves(self.ctx, state)
        self.assertEqual([r["wave"] for r in released], [25])

    def test_a_take_bound_after_the_park_keeps_the_wave_frozen(self):
        for uid in self.units:
            self.park_clip(uid)
        later = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
        self.bind("E15-VU-002", later)
        state = {"waves": [self.wave(25)]}
        self.assertEqual(P.release_unposted_waves(self.ctx, state), [])

    def test_a_bound_take_of_a_unit_that_was_never_parked_keeps_the_wave_frozen(self):
        self.bind("E15-VU-002", "2026-11-15T03:00:00Z")
        state = {"waves": [self.wave(25)]}
        self.assertEqual(P.release_unposted_waves(self.ctx, state), [])

    # -- tails ----------------------------------------------------------------------------------
    def derived(self, tail_bytes):
        dst = self.keyframes / "E15-S01-03-keyframe-v1.png"
        dst.write_bytes(tail_bytes)
        dst.with_suffix(".derived.json").write_text(json.dumps(
            {"previous_unit_id": "E15-VU-002", "source_sha256": _sha(tail_bytes)}))
        (self.receipts / "E15-VU-003_start_frame_evidence.json").write_text("{}")
        return dst

    def test_the_tail_of_a_parked_clip_and_the_start_frame_copied_from_it_are_moved_aside(self):
        tail = self.tails / "E15-VU-002.png"; tail.write_bytes(b"old tail")
        tail.with_suffix(".source.sha256").write_text(_sha(b"old take") + "\n")
        dst = self.derived(b"old tail")
        rows = P.park_stale_real_final_frames(self.ctx, self.units)
        self.assertEqual({r["status"] for r in rows},
                         {"TAIL_PARKED_CLIP_NOT_ON_DISK", "DERIVED_START_FRAME_PARKED_TAIL_NOT_CURRENT"})
        self.assertFalse(tail.exists())
        self.assertTrue((self.tails / "_superseded_RUN" / "E15-VU-002.png").is_file())  # evidence kept
        self.assertFalse(dst.exists())
        self.assertFalse((self.receipts / "E15-VU-003_start_frame_evidence.json").exists())
        park = self.keyframes / "_superseded_RUN_stale_tail"
        self.assertTrue((park / dst.name).is_file())
        self.assertTrue((park / "E15-VU-003_start_frame_evidence.json").is_file())

    def test_a_current_tail_and_its_start_frame_are_left_alone(self):
        (self.video / "E15-VU-002.mp4").write_bytes(b"current take")
        tail = self.tails / "E15-VU-002.png"; tail.write_bytes(b"tail")
        tail.with_suffix(".source.sha256").write_text(_sha(b"current take") + "\n")
        dst = self.derived(b"tail")
        self.assertEqual(P.park_stale_real_final_frames(self.ctx, self.units), [])
        self.assertTrue(tail.is_file() and dst.is_file())

    def test_a_unit_with_its_own_clip_keeps_its_start_frame(self):
        (self.video / "E15-VU-003.mp4").write_bytes(b"successor clip")
        tail = self.tails / "E15-VU-002.png"; tail.write_bytes(b"old tail")
        dst = self.derived(b"old tail")
        rows = P.park_stale_real_final_frames(self.ctx, self.units)
        self.assertEqual([r["status"] for r in rows], ["TAIL_PARKED_CLIP_NOT_ON_DISK"])
        self.assertTrue(dst.is_file())

    def test_a_dry_run_moves_nothing(self):
        self.ctx.dry = True
        tail = self.tails / "E15-VU-002.png"; tail.write_bytes(b"old tail")
        self.assertEqual(P.park_stale_real_final_frames(self.ctx, self.units), [])
        self.assertTrue(tail.is_file())

    def test_the_wave_loop_calls_it_before_readiness(self):
        src = (TOOLS / "nalu_pipeline.py").read_text(encoding="utf-8")
        body = src[src.index("def stage_s6(ctx: Ctx)"):]
        self.assertLess(body.index("park_stale_real_final_frames(ctx"), body.index("materialise_derived_keyframes(ctx)"))


if __name__ == "__main__":
    unittest.main()
