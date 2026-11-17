"""Fleet device ...1205 E13, 2026-11-17: a redo whose request equals the parked take is named, not waited on.

Seven QA-rejected clips were parked for a controlled redo with unchanged requests.  The planner read each
unit as "already bound -> poll only" (exact fingerprint of the parked take), the new wave had no submit
report, the poll child crashed, and the heartbeat re-ran S6 90 times on VIDEO_NOT_ALL_COMPLETED.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import nalu_pipeline as pipeline  # noqa: E402
import paid_run_status  # noqa: E402

EP = "E13"
KEY = "E13-VU-001"
SAME = "a" * 64


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def _tx(store: Path, key: str, fingerprint: str, task_id: str, bound_epoch: float, **extra) -> None:
    store.mkdir(parents=True, exist_ok=True)
    (store / f"{key}__{fingerprint[:16]}.json").write_text(json.dumps({
        "task_key": key, "submission_fingerprint": fingerprint, "state": "SUBMITTED_TASK_ID_BOUND",
        "task_id": task_id, "response_recorded_at": _iso(bound_epoch), **extra}), encoding="utf-8")


class RedoIdenticalToParkedTakeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.work = self.root / "workflow/nalu" / EP
        self.video = self.work / "video"
        self.video.mkdir(parents=True)
        self.store = self.root / "workflow/tasks/giggle_video_submit_transactions" / EP
        self.ctx = SimpleNamespace(episode=EP, p=SimpleNamespace(work=self.work, video_media=self.video))
        patcher = mock.patch.object(pipeline, "ENGINE", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def _park(self, key: str = KEY) -> float:
        park = self.video / "_superseded_redo"
        park.mkdir(exist_ok=True)
        clip = park / f"{key}.mp4"
        clip.write_bytes(b"rejected take")
        return clip.stat().st_ctime

    def stale(self, fingerprint: str = SAME, **task) -> list[str]:
        return pipeline.s6_redo_identical_to_parked_take(
            self.ctx, [{"task_key": KEY, **task}], lambda _t: fingerprint)

    def test_unchanged_request_of_a_parked_clip_is_named(self):
        parked = self._park()
        _tx(self.store, KEY, SAME, "original", parked - 3600)
        self.assertEqual(self.stale(), [KEY])

    def test_changed_request_is_not_named(self):
        parked = self._park()
        _tx(self.store, KEY, SAME, "original", parked - 3600)
        self.assertEqual(self.stale("b" * 64), [])

    def test_take_bound_after_the_park_is_a_real_remote_wait(self):
        parked = self._park()
        _tx(self.store, KEY, SAME, "redo", parked + 60)
        self.assertEqual(self.stale(), [])

    def test_never_parked_unit_is_a_real_remote_wait(self):
        _tx(self.store, KEY, SAME, "only", 1_700_000_000)
        self.assertEqual(self.stale(), [])

    def test_live_redo_under_a_drifted_fingerprint_is_a_real_remote_wait(self):
        parked = self._park()
        _tx(self.store, KEY, SAME, "original", parked - 3600)
        _tx(self.store, KEY, "c" * 64, "redo", parked + 60)
        self.assertEqual(self.stale(), [])

    def test_clip_on_disk_is_not_named(self):
        parked = self._park()
        _tx(self.store, KEY, SAME, "original", parked - 3600)
        (self.video / f"{KEY}.mp4").write_bytes(b"clip")
        self.assertEqual(self.stale(), [])

    def test_the_blocker_is_not_classified_as_a_remote_wait(self):
        state = {"stages": {"S6": {"status": "BLOCKED",
                                   "blockers": [f"wave100:REDO_REQUEST_IDENTICAL_TO_PARKED_TAKE:{KEY}"]}}}
        self.assertNotEqual(paid_run_status.classify(state, "S6", "S6")["verdict"], paid_run_status.WAIT)
        waiting = {"stages": {"S6": {"status": "BLOCKED", "blockers": ["wave100:VIDEO_NOT_ALL_COMPLETED"]}}}
        self.assertEqual(paid_run_status.classify(waiting, "S6", "S6")["verdict"], paid_run_status.WAIT)


if __name__ == "__main__":
    unittest.main()
