#!/usr/bin/env python3
"""An S6 wave that never POSTed must not keep a frozen unit list.

Frozen membership exists because re-entering a SUBMITTED wave with a different list
double-POSTed on 2026-09-13.  E11's wave 1 was opened on 2026-10-06 by a forward run that
reached S6 before any keyframe existed.  It never submitted, but its frozen list held a unit id
that is in no plan (VU-042) and a continuity-derived unit whose start frame cannot exist yet
(VU-040), so every later pass asked for a review of media that did not exist.

The release is narrow on purpose.  Any sign that a wave may have POSTed (a submit report, a
bound transaction, or a video on disk) keeps the frozen membership exactly as before.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import nalu_pipeline as P  # noqa: E402


class ReleaseUnpostedWavesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.preprod = root / "preproduction"; self.preprod.mkdir()
        self.video = root / "video"; self.video.mkdir()
        self.reports = root / "reports"; self.reports.mkdir()
        self.engine = root / "engine"
        self.store = self.engine / "workflow/tasks/giggle_video_submit_transactions/E11"
        self.store.mkdir(parents=True)
        (self.preprod / "E11_VIDEO_UNIT_GROUPING_PLAN_V1.json").write_text(json.dumps(
            {"units": [{"unit_id": f"E11-VU-{i:03d}"} for i in range(1, 42)]}))
        self.ctx = SimpleNamespace(episode="E11", p=SimpleNamespace(preprod=self.preprod, video_media=self.video))
        self._engine = P.ENGINE
        P.ENGINE = self.engine

    def tearDown(self):
        P.ENGINE = self._engine
        self._tmp.cleanup()

    def wave(self, n, units):
        return {"wave": n, "units": units, "opened_at": "t",
                "submit_report": str(self.reports / f"submit_wave{n}.json")}

    def test_a_wave_that_never_posted_is_released_and_names_the_unknown_unit(self):
        state = {"waves": [self.wave(1, ["E11-VU-001", "E11-VU-040", "E11-VU-042"])]}
        released = P.release_unposted_waves(self.ctx, state)
        self.assertEqual(len(released), 1)
        self.assertIn("E11-VU-042", released[0]["reason"])
        self.assertTrue(state["waves"][0]["completed_at"])

    def test_a_submit_report_on_disk_keeps_the_wave_frozen(self):
        (self.reports / "submit_wave1.json").write_text("{}")
        state = {"waves": [self.wave(1, ["E11-VU-001"])]}
        self.assertEqual(P.release_unposted_waves(self.ctx, state), [])
        self.assertNotIn("completed_at", state["waves"][0])

    def test_a_bound_transaction_keeps_the_wave_frozen(self):
        (self.store / "x.json").write_text(json.dumps(
            {"state": "SUBMITTED_TASK_ID_BOUND", "task_id": "t1", "task_key": "E11-VU-001-V1"}))
        state = {"waves": [self.wave(1, ["E11-VU-001", "E11-VU-002"])]}
        self.assertEqual(P.release_unposted_waves(self.ctx, state), [])

    def test_a_video_on_disk_keeps_the_wave_frozen(self):
        (self.video / "E11-VU-002.mp4").write_bytes(b"x")
        state = {"waves": [self.wave(1, ["E11-VU-001", "E11-VU-002"])]}
        self.assertEqual(P.release_unposted_waves(self.ctx, state), [])

    def test_completed_waves_are_left_alone(self):
        w = self.wave(1, ["E11-VU-001"]); w["completed_at"] = "done"
        state = {"waves": [w]}
        self.assertEqual(P.release_unposted_waves(self.ctx, state), [])
        self.assertNotIn("release_reason", w)


if __name__ == "__main__":
    unittest.main()
