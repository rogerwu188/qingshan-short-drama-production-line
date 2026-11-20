"""Fleet device JA-01, E01, 2026-11-19: a completed take of an OLD request is not the new episode's take.

The line owner ordered E01 redone in anime style.  The device archived workflow/nalu/E01/ but not the
durable video store, and S6 reused 28 completed live-action takes because "a bound transaction is never
resubmitted" never compared the request (VU-001's transaction prompt sha was the archived v1 prompt).
Offline: no provider call is ever made, a POST attempt fails the test.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import nalu_budget_ledger as ledger  # noqa: E402
import nalu_pipeline as pipeline  # noqa: E402
import tools.submit_giggle_video_manifest_v2 as submitter  # noqa: E402
from tools import video_live_binding as vlb  # noqa: E402

EP = "E01"
KEY = "E01-VU-001"
OLD_PROMPT, NEW_PROMPT = "1" * 64, "2" * 64
OLD_REFS, NEW_REFS = ["a" * 64], ["b" * 64]
GUARD_ON = {vlb.STALE_BINDING_GUARD_ENV: "1"}


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def _tx(store: Path, fingerprint: str, task_id: str, *, prompt: str = OLD_PROMPT, refs=None,
        bound_epoch: float | None = None, completed: bool = True, key: str = KEY, **extra) -> Path:
    store.mkdir(parents=True, exist_ok=True)
    bound_epoch = time.time() - 600 if bound_epoch is None else bound_epoch
    row = {"schema": "qingshan.giggle_video_submit_transaction.v1", "task_key": key, "provider": "hopsapi",
           "submission_fingerprint": fingerprint, "state": "SUBMITTED_TASK_ID_BOUND", "task_id": task_id,
           "intent_recorded_at": _iso(bound_epoch - 3), "response_recorded_at": _iso(bound_epoch),
           "prompt_sha256": prompt, "reference_sha256": list(refs or OLD_REFS),
           "sent_reference_sha256": ["f" * 64], "estimated_credits": 120, **extra}
    if completed:
        row.update(provider_remote_status="completed", provider_cost_credits=120.0)
    path = store / f"{key}__{fingerprint[:16]}.json"
    path.write_text(json.dumps(row), encoding="utf-8")
    return path


def _task(prompt: str = NEW_PROMPT, refs=None, **extra) -> dict:
    return {"task_key": KEY, "episode": EP, "prompt_sha256": prompt, "reference_sha256": list(refs or NEW_REFS),
            **extra}


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.work = self.root / "workflow/nalu" / EP
        self.video = self.work / "video"
        self.video.mkdir(parents=True)
        self.preprod = self.work / "preproduction"
        self.store = self.root / "workflow/tasks/giggle_video_submit_transactions" / EP
        env = mock.patch.dict(os.environ, GUARD_ON)
        env.start()
        self.addCleanup(env.stop)

    def live(self, task=None):
        return [r["task_id"] for r in vlb.live_bindings(self.store, KEY, root=self.root, episode=EP,
                                                         current_task=task)]

    def retire(self, task, logs=None):
        return vlb.retire_stale_bindings(self.store, task, root=self.root, episode=EP,
                                         log=(logs.append if logs is not None else None))

    def stale_dirs(self):
        return sorted(p for p in self.store.glob(f"{vlb.STALE_ARCHIVE_PREFIX}*") if p.is_dir())


class StaleBindingRuleTest(_Base):
    def test_matching_request_is_reused(self):
        _tx(self.store, "c" * 64, "same", prompt=NEW_PROMPT, refs=NEW_REFS)
        self.assertEqual(self.live(_task()), ["same"])
        self.assertEqual(self.retire(_task())["archived"], [])
        self.assertEqual(self.stale_dirs(), [])

    def test_crash_reentry_with_identical_request_and_drifted_fingerprint_is_reused(self):
        # lab E05: episode-wide contract drift changes the fingerprint, prompt + ordered refs are identical
        _tx(self.store, "c" * 64, "rendered", prompt=NEW_PROMPT, refs=NEW_REFS, completed=True)
        _tx(self.store, "d" * 64, "pending", prompt=NEW_PROMPT, refs=NEW_REFS, completed=False,
            bound_epoch=time.time() - 60)
        self.assertEqual(self.live(_task()), ["rendered", "pending"])
        self.assertEqual(self.retire(_task())["archived"], [])
        self.assertTrue((self.store / f"{KEY}__{'c' * 16}.json").is_file())

    def test_differing_completed_take_is_archived_never_deleted(self):
        tx = _tx(self.store, "c" * 64, "old-live-action")
        alt = self.video / vlb.ALT_TAKES_DIRNAME / f"{KEY}__take_old-live.mp4"
        alt.parent.mkdir(parents=True)
        alt.write_bytes(b"old alt take")
        self.assertEqual(self.live(_task()), [], "a stale completed take is not live")
        self.assertEqual(self.live(), ["old-live-action"], "without the current task: unchanged rule")
        logs: list[str] = []
        got = self.retire(_task(), logs)
        self.assertEqual([r["task_id"] for r in got["archived"]], ["old-live-action"])
        self.assertFalse(tx.exists())
        [stale] = self.stale_dirs()
        kept = json.loads((stale / tx.name).read_text(encoding="utf-8"))
        self.assertEqual(kept["task_id"], "old-live-action")
        self.assertTrue((stale / "STALE_BINDING_ARCHIVE.jsonl").is_file())
        self.assertFalse(alt.exists())
        self.assertTrue((alt.parent / stale.name / alt.name).is_file())
        self.assertTrue(any(line.startswith(f"S6_STALE_BINDING_ARCHIVED unit={KEY} ") and
                            f"old_prompt={OLD_PROMPT[:16]}" in line and f"new_prompt={NEW_PROMPT[:16]}" in line
                            for line in logs), logs)
        self.assertEqual(self.live(_task()), [])
        self.assertEqual(self.live(), [], "the archived row is out of every live scan")

    def test_changed_references_alone_make_a_completed_take_stale(self):
        _tx(self.store, "c" * 64, "old", prompt=NEW_PROMPT, refs=OLD_REFS)
        self.assertEqual([r["task_id"] for r in self.retire(_task())["archived"]], ["old"])

    def test_completion_from_a_remote_status_report_counts(self):
        _tx(self.store, "c" * 64, "giggle-old", completed=False)
        report = self.preprod / "reports/E01_VIDEO_REMOTE_STATUS_V1_wave1.json"
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps({"results": [{"task_id": "giggle-old", "remote_status": "completed"}]}),
                          encoding="utf-8")
        self.assertEqual([r["task_id"] for r in self.retire(_task())["archived"]], ["giggle-old"])

    def test_differing_in_flight_take_is_kept_and_warned(self):
        tx = _tx(self.store, "c" * 64, "rendering", completed=False)
        logs: list[str] = []
        got = self.retire(_task(), logs)
        self.assertEqual(got["archived"], [])
        self.assertEqual([r["task_id"] for r in got["in_flight"]], ["rendering"])
        self.assertTrue(tx.is_file())
        self.assertTrue(any(line.startswith("S6_STALE_BINDING_IN_FLIGHT WARNING") for line in logs), logs)
        rows = vlb.live_bindings(self.store, KEY, root=self.root, episode=EP, current_task=_task())
        self.assertEqual([r["task_id"] for r in rows], ["rendering"])
        self.assertTrue(rows[0]["stale_request_in_flight"])

    def test_clip_on_disk_is_never_touched(self):
        # D-46 / lab Holmes E06: a harvested take is the unit's authority whatever its recompiled prompt says;
        # this is also the "best burn take restored to the assembly path" case.
        tx = _tx(self.store, "c" * 64, "harvested")
        (self.video / f"{KEY}.mp4").write_bytes(b"harvested take")
        self.assertEqual(self.retire(_task())["archived"], [])
        self.assertTrue(tx.is_file())
        self.assertEqual(self.live(_task()), ["harvested"])

    def test_burn_retry_parked_take_is_not_classified(self):
        # PR #278: the burned take is parked to _superseded_<run>_burn_retry1/, the recompile carries the retry
        # sentence (new prompt sha) and the submitter perturbs @Image1 (sent_reference_sha256 only).
        park = self.video / "_superseded_run1_burn_retry1"
        park.mkdir()
        (park / f"{KEY}.mp4").write_bytes(b"burned take")
        parked = (park / f"{KEY}.mp4").stat().st_ctime
        tx = _tx(self.store, "c" * 64, "burned", bound_epoch=parked - 600)
        retry_task = _task(prompt=OLD_PROMPT[:-1] + "9", refs=OLD_REFS, h3_burn_retry=1)
        self.assertEqual(self.live(retry_task), [], "a parked take is not live, with or without the guard")
        self.assertEqual(self.retire(retry_task), {"archived": [], "in_flight": []})
        self.assertTrue(tx.is_file(), "the parked burn take's transaction stays where it is")
        self.assertEqual(self.stale_dirs(), [])

    def test_burn_retry_in_flight_with_same_request_is_reused(self):
        # the retry itself: same retry prompt + same source refs; only the SENT @Image1 bytes differ
        retry_task = _task(prompt=NEW_PROMPT, refs=NEW_REFS, h3_burn_retry=1)
        _tx(self.store, "c" * 64, "retry1", prompt=NEW_PROMPT, refs=NEW_REFS, sent_reference_sha256=["e" * 64])
        self.assertEqual(self.live(retry_task), ["retry1"])
        self.assertEqual(self.retire(retry_task)["archived"], [])

    def test_env_opt_out_restores_the_old_rule(self):
        tx = _tx(self.store, "c" * 64, "old")
        with mock.patch.dict(os.environ, {vlb.STALE_BINDING_GUARD_ENV: "0"}):
            self.assertEqual(self.live(_task()), ["old"])
            self.assertEqual(self.retire(_task()), {"archived": [], "in_flight": []})
        self.assertTrue(tx.is_file())

    def test_unknown_identity_is_never_called_different(self):
        _tx(self.store, "c" * 64, "legacy", prompt="", refs=[])
        path = self.store / f"{KEY}__{'c' * 16}.json"
        row = json.loads(path.read_text(encoding="utf-8"))
        row.pop("prompt_sha256"); row.pop("reference_sha256")
        path.write_text(json.dumps(row), encoding="utf-8")
        self.assertEqual(self.live(_task()), ["legacy"])

    def test_archived_take_stays_attributed_and_charged(self):
        _tx(self.store, "c" * 64, "old")
        self.retire(_task())
        self.assertIn("old", vlb.attributed_task_ids(self.store.parent))
        files = ledger._store_json_files(self.store)
        self.assertEqual([json.loads(p.read_text(encoding="utf-8"))["task_id"] for p in files], ["old"])
        with mock.patch.object(ledger, "ENGINE_ROOT", self.root):
            spend = ledger.scan_hopsapi_spend(EP, kinds=("video",))
        self.assertEqual(float(spend["by_kind"]["video"]["settled_credits"]), 120.0)


class SubmitterStaleBindingTest(_Base):
    """The submitter's last check before money: a stale completed take is archived, an in-flight one polled."""

    def _elsewhere(self, task):
        with mock.patch.object(submitter, "ROOT", self.root), \
             mock.patch.object(submitter, "task_fingerprint", lambda _t: "d" * 64):
            return submitter.live_bound_elsewhere(task, self.store)

    def test_differing_completed_take_is_archived_and_the_task_goes_on_to_post(self):
        tx = _tx(self.store, "c" * 64, "old-live-action")
        self.assertIsNone(self._elsewhere(_task()), "nothing to recover: the task proceeds to a fresh attempt")
        self.assertFalse(tx.exists())
        self.assertEqual(len(self.stale_dirs()), 1)

    def test_differing_in_flight_take_is_polled_never_reposted(self):
        tx = _tx(self.store, "c" * 64, "rendering", completed=False)
        row = self._elsewhere(_task())
        self.assertEqual(row["task_id"], "rendering")
        self.assertEqual(row["recovered_via"], "LIVE_BINDING_UNDER_OTHER_FINGERPRINT")
        self.assertTrue(tx.is_file())

    def test_identical_request_under_drifted_fingerprint_is_recovered(self):
        _tx(self.store, "c" * 64, "same", prompt=NEW_PROMPT, refs=NEW_REFS)
        self.assertEqual(self._elsewhere(_task())["task_id"], "same")

    def test_opt_out(self):
        _tx(self.store, "c" * 64, "old")
        with mock.patch.dict(os.environ, {vlb.STALE_BINDING_GUARD_ENV: "0"}):
            self.assertEqual(self._elsewhere(_task())["task_id"], "old")


class PipelineStaleBindingTest(_Base):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(pipeline, "ENGINE", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.logs: list[str] = []
        self.ctx = SimpleNamespace(episode=EP, run_id="RUN1", dry=False, say=self.logs.append,
                                   p=SimpleNamespace(work=self.work, video_media=self.video, preprod=self.preprod))

    def bound(self, task):
        return pipeline.s6_bound_task_keys(self.ctx, [task], lambda t: "d" * 64)

    def test_planner_reads_a_stale_completed_take_as_unbound(self):
        _tx(self.store, "c" * 64, "old")
        self.assertEqual(self.bound(_task()), set(), "planned + budgeted as a fresh attempt")
        _tx(self.store, "e" * 64, "same", prompt=NEW_PROMPT, refs=NEW_REFS)
        self.assertEqual(self.bound(_task()), {KEY}, "an identical-request binding is still reused")

    def test_planner_keeps_an_in_flight_differing_take_bound(self):
        _tx(self.store, "c" * 64, "rendering", completed=False)
        self.assertEqual(self.bound(_task()), {KEY}, "never a second charge for a take still rendering")

    def test_retire_archives_take_and_tail_then_resubmits(self):
        tx = _tx(self.store, "c" * 64, "old")
        tails = self.preprod / "real_final_frames"
        tails.mkdir(parents=True)
        (tails / f"{KEY}.png").write_bytes(b"old tail")
        (tails / f"{KEY}.source.sha256").write_text("x\n", encoding="utf-8")
        got = pipeline.s6_retire_stale_bindings(self.ctx, [_task()])
        self.assertEqual(got["status"], "ARCHIVED")
        self.assertFalse(tx.exists())
        self.assertFalse((tails / f"{KEY}.png").exists())
        self.assertTrue((tails / "_superseded_RUN1_stale_binding" / f"{KEY}.png").is_file())
        self.assertTrue(any(line.startswith("S6_STALE_BINDING_ARCHIVED") for line in self.logs), self.logs)
        self.assertEqual(self.bound(_task()), set())
        self.assertEqual(pipeline._units_with_bound_submission(self.ctx), set(),
                         "an unposted redo wave is not frozen by the archived take")

    def test_dry_run_archives_nothing(self):
        tx = _tx(self.store, "c" * 64, "old")
        self.ctx.dry = True
        self.assertEqual(pipeline.s6_retire_stale_bindings(self.ctx, [_task()])["status"], "SKIPPED_DRY")
        self.assertTrue(tx.is_file())

    def test_live_bound_wave_poll_skips_a_stale_take(self):
        _tx(self.store, "c" * 64, "old")
        manifest = self.preprod / "E01_VIDEO_TRANSACTION_MANIFEST_V1.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"tasks": [_task()]}), encoding="utf-8")
        self.ctx.p.video_transaction = manifest
        self.assertIsNone(pipeline._s6_live_bound_wave(self.ctx, [KEY]), "compile + gates, not a poll of v1")
        manifest.write_text(json.dumps({"tasks": [_task(prompt=OLD_PROMPT, refs=OLD_REFS)]}), encoding="utf-8")
        self.assertIsNotNone(pipeline._s6_live_bound_wave(self.ctx, [KEY]), "same request: poll only")

    def test_parked_redo_identical_request_still_named(self):
        # REDO_REQUEST_IDENTICAL_TO_PARKED_TAKE: untouched by the guard
        park = self.video / "_superseded_redo"
        park.mkdir()
        (park / f"{KEY}.mp4").write_bytes(b"rejected")
        parked = (park / f"{KEY}.mp4").stat().st_ctime
        _tx(self.store, "d" * 64, "orig", prompt=NEW_PROMPT, refs=NEW_REFS, bound_epoch=parked - 3600)
        got = pipeline.s6_redo_identical_to_parked_take(self.ctx, [_task()], lambda _t: "d" * 64)
        self.assertEqual(got, [KEY])


if __name__ == "__main__":
    unittest.main()
