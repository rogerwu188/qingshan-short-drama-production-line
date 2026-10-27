"""Lab E05 2026-10-26: a pending redo is polled, never POSTed twice; one Pay row is one charge.

Replays the blocker E05_CODE_BLOCKER_20261026_S6_REENTRY offline.  Every provider call is a mock
that fails the test when a POST would be reached, so "no POST" is proven, not assumed.
"""
from __future__ import annotations

import hashlib
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

import tools.submit_giggle_video_manifest_v2 as submitter  # noqa: E402
from tools.giggle_credit_statements import parse_utc, reconcile_rows  # noqa: E402
from tools.video_live_binding import attributed_task_ids, live_bindings  # noqa: E402

EP = "E05"
KEY = "E05-VU-001"


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def _tx(store: Path, key: str, fingerprint: str, task_id: str, bound_epoch: float, **extra) -> Path:
    store.mkdir(parents=True, exist_ok=True)
    path = store / f"{key}__{fingerprint[:16]}.json"
    path.write_text(json.dumps({
        "schema": "qingshan.giggle_video_submit_transaction.v1", "task_key": key,
        "submission_fingerprint": fingerprint, "state": "SUBMITTED_TASK_ID_BOUND", "task_id": task_id,
        "intent_recorded_at": _iso(bound_epoch - 3), "response_recorded_at": _iso(bound_epoch),
        "prompt_sha256": "p" * 64, "reference_sha256": ["r" * 64],
        "request_binding": {"request_sha256": "q" * 64}, **extra}), encoding="utf-8")
    return path


def _park(root: Path, key: str) -> float:
    park = root / "workflow/nalu" / EP / "video" / "_superseded_redo"
    park.mkdir(parents=True, exist_ok=True)
    clip = park / f"{key}.mp4"
    clip.write_bytes(b"old take")
    return clip.stat().st_ctime


class LiveBindingRuleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = self.root / "workflow/tasks/giggle_video_submit_transactions" / EP

    def tearDown(self):
        self._tmp.cleanup()

    def live(self, **kw):
        return [r["task_id"] for r in live_bindings(self.store, KEY, root=self.root, episode=EP, **kw)]

    def test_take_bound_after_the_park_is_live_and_the_rejected_one_is_not(self):
        parked = _park(self.root, KEY)
        _tx(self.store, KEY, "a" * 64, "original", parked - 3600)        # harvested, then parked
        _tx(self.store, KEY, "b" * 64, "redo", parked + 60)             # the redo still rendering
        _tx(self.store, KEY, "c" * 64, "duplicate", parked + 660)       # the E05 duplicate
        self.assertEqual(self.live(), ["redo", "duplicate"], "oldest live take first")

    def test_never_parked_bound_task_is_live(self):
        _tx(self.store, KEY, "a" * 64, "only", time.time() - 10)
        self.assertEqual(self.live(), ["only"])

    def test_terminal_remote_failure_releases_the_binding(self):
        _tx(self.store, KEY, "a" * 64, "dead", time.time() - 10)
        report = self.root / "workflow/nalu" / EP / "preproduction/reports/E05_VIDEO_REMOTE_STATUS_V1_wave3.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({"results": [{"task_id": "dead", "remote_status": "failed"}]}), encoding="utf-8")
        self.assertEqual(self.live(), [])

    def test_durable_terminal_mark_releases_the_binding(self):
        _tx(self.store, KEY, "a" * 64, "dead", time.time() - 10, remote_terminal_state="failed")
        self.assertEqual(self.live(), [])

    def test_declared_supersede_and_own_fingerprint_are_excluded(self):
        _tx(self.store, KEY, "a" * 64, "t1", time.time() - 10)
        self.assertEqual(self.live(exclude_fingerprints={"a" * 64}), [])

    def test_other_task_keys_with_a_shared_prefix_do_not_leak(self):
        _tx(self.store, f"{KEY}-ZH", "a" * 64, "ab", time.time() - 10)
        self.assertEqual(self.live(), [])


def _task(tmp: Path) -> dict:
    prompt = tmp / "p.txt"
    prompt.write_text("PROMPT", encoding="utf-8")
    ref = tmp / "r.png"
    ref.write_bytes(b"ref")
    return {"task_key": KEY, "episode": EP, "model": "MiniMax-H3", "duration_seconds": 3,
            "resolution": "768p", "aspect_ratio": "9:16", "prompt_file": str(prompt),
            "prompt_sha256": hashlib.sha256(b"PROMPT").hexdigest(),
            "reference_images": [str(ref)], "reference_sha256": [hashlib.sha256(b"ref").hexdigest()]}


class SubmitterNeverRePostsALiveBindingTest(unittest.TestCase):
    """The submitter is the last line before money: a drifted fingerprint must not POST again."""

    def _submit(self, root: Path, task: dict, reached: list):
        def fake_request(*_a, **_k):
            reached.append(1)
            return {"code": 200, "data": {"task_id": "new-task"}}
        store = root / "workflow/tasks/giggle_video_submit_transactions" / EP
        with mock.patch.object(submitter, "ROOT", root), \
             mock.patch.object(submitter, "_request", fake_request), \
             mock.patch("tools.episode_prompt_batch_gate.require_generation_batch", lambda *a, **k: None), \
             mock.patch.object(submitter, "prompt_scope_gate_active", lambda _t: False), \
             mock.patch.object(submitter, "_reference_image_transport", lambda _t: ([{"base64": "cmVm"}], [])), \
             mock.patch.object(submitter, "task_fingerprint", lambda _t: "d" * 64), \
             mock.patch.object(submitter, "paid_video_submission_context", mock.MagicMock()):
            return submitter.submit_one(task, root / "receipts", store), store

    def test_drifted_fingerprint_polls_the_pending_redo_instead_of_posting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parked = _park(root, KEY)
            store = root / "workflow/tasks/giggle_video_submit_transactions" / EP
            _tx(store, KEY, "2" * 64, "4e2d4a56-redo", parked + 60)
            reached: list = []
            row, store = self._submit(root, _task(root), reached)
            self.assertEqual(reached, [], "a live binding must never be POSTed again")
            self.assertEqual(row["task_id"], "4e2d4a56-redo")
            self.assertTrue(row["recovered_from_transaction"])
            self.assertEqual(row["recovered_via"], "LIVE_BINDING_UNDER_OTHER_FINGERPRINT")
            self.assertFalse((store / f"{KEY}__{'d' * 16}.json").exists(), "no intent record for a poll")

    def test_take_parked_after_binding_allows_the_new_redo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = root / "workflow/tasks/giggle_video_submit_transactions" / EP
            _tx(store, KEY, "1" * 64, "original", time.time() - 7200)
            _park(root, KEY)
            reached: list = []
            row, _ = self._submit(root, _task(root), reached)
            self.assertEqual(reached, [1], "a redo after an explicit park is a new paid task")
            self.assertEqual(row["task_id"], "new-task")

    def test_explicit_supersede_reopens_the_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = root / "workflow/tasks/giggle_video_submit_transactions" / EP
            _tx(store, KEY, "2" * 64, "pending", time.time() - 60)
            task = {**_task(root), "supersedes_submission_fingerprints": ["2" * 64]}
            reached: list = []
            self._submit(root, task, reached)
            self.assertEqual(reached, [1])


def _pay(project_id: str, created: str) -> dict:
    return {"event_type": "Pay", "event_description": "SingleGenerateVideo", "model": "MiniMax-H3",
            "credit": "-48", "project_id": project_id, "created_at": created}


class ReconcileByTaskIdFirstTest(unittest.TestCase):
    ROWS = [_pay("1eb26c4b-852e-47d9-b4f6-eca50af4e76a", "2026-10-26 20:14:57"),
            _pay("c7c6ed06-bd34-4bec-b637-a4c0cae87372", "2026-10-26 20:15:19")]
    START, END = parse_utc("2026-10-26T20:14:56.929470Z"), parse_utc("2026-10-26T20:15:34.873177Z")

    def test_e05_wave29_window_without_ids_double_counts(self):
        legacy = reconcile_rows(self.ROWS, start=self.START, end=self.END, expected_count=1,
                                event_description="SingleGenerateVideo", model="MiniMax-H3")
        self.assertEqual((legacy["status"], legacy["matched_count"]), ("FAIL", 2))

    def test_row_attributed_to_another_wave_is_not_counted_again(self):
        fixed = reconcile_rows(self.ROWS, start=self.START, end=self.END, expected_count=1,
                               event_description="SingleGenerateVideo", model="MiniMax-H3",
                               known_task_ids={"c7c6ed06-bd34-4bec-b637-a4c0cae87372"},
                               exclude_task_ids={"1eb26c4b-852e-47d9-b4f6-eca50af4e76a"})
        self.assertEqual((fixed["status"], fixed["matched_count"], fixed["charged_credits"]), ("PASS", 1, 48))
        self.assertEqual(fixed["matched_by_task_id_count"], 1)
        self.assertEqual(fixed["excluded_rows_attributed_elsewhere"], ["1eb26c4b-852e-47d9-b4f6-eca50af4e76a"])

    def test_own_task_id_is_matched_even_outside_the_window(self):
        late = [_pay("own", "2026-10-26 21:00:00")]
        fixed = reconcile_rows(late, start=self.START, end=self.END, expected_count=1,
                               event_description="SingleGenerateVideo", model="MiniMax-H3",
                               known_task_ids={"own"})
        self.assertEqual((fixed["status"], fixed["matched_count"]), ("PASS", 1))

    def test_attributed_ids_cover_every_episode_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _tx(root / "E05", KEY, "a" * 64, "x1", time.time())
            _tx(root / "E04", "E04-VU-001", "b" * 64, "x2", time.time())
            self.assertEqual(attributed_task_ids(root), {"x1", "x2"})


class LedgerCountsEachPayRowOnceTest(unittest.TestCase):
    def test_overlapping_statements_count_a_shared_row_once(self):
        import nalu_budget_ledger as ledger
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "workflow/nalu/E05/preproduction/reports"
            reports.mkdir(parents=True)
            a, b = TestCaseRows.A, TestCaseRows.B
            (reports / "E05_VIDEO_SUBMIT_V1_wave28_RUN_wave1u_credit_statement.json").write_text(
                json.dumps({"charged_credits": 48, "matched_count": 1, "statement_rows": [a]}), encoding="utf-8")
            (reports / "E05_VIDEO_SUBMIT_V1_wave29_RUN_wave1u_credit_statement.json").write_text(
                json.dumps({"charged_credits": 96, "matched_count": 2, "statement_rows": [a, b]}), encoding="utf-8")
            (reports / "E05_VIDEO_SUBMIT_V1_wave4_OLD_credit_statement.json").write_text(
                json.dumps({"charged_credits": 144, "matched_count": 3}), encoding="utf-8")  # legacy: no rows
            with mock.patch.object(ledger, "ENGINE_ROOT", root):
                spend = ledger.scan_non_video_spend("E05", bgm_transactions_dir=root / "none")
            self.assertEqual(spend["batch_reconciled_credits"], 48 + 48 + 144)
            self.assertEqual(len(spend["batch_duplicate_statement_rows"]), 1)
            # the statement files themselves are evidence and stay untouched
            self.assertEqual(json.loads((reports / "E05_VIDEO_SUBMIT_V1_wave29_RUN_wave1u_credit_statement.json")
                                        .read_text(encoding="utf-8"))["charged_credits"], 96)


class TestCaseRows:
    A = _pay("1eb26c4b-852e-47d9-b4f6-eca50af4e76a", "2026-10-26 20:14:57")
    B = _pay("c7c6ed06-bd34-4bec-b637-a4c0cae87372", "2026-10-26 20:15:19")


class PollAlternateTakeTest(unittest.TestCase):
    def test_second_take_lands_under_its_output_name(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import poll_giggle_submit_report as poller
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            downloaded = []
            with mock.patch.object(poller, "query_task", lambda ns: {"data": {"status": "completed", "urls": ["u"]}}), \
                 mock.patch.object(poller, "download_atomic", lambda url, dest: downloaded.append(dest)):
                row = poller.poll_one(1, {"task_key": "E05-VU-001__take_1eb26c4b", "task_id": "t",
                                          "output_name": "_alt_takes/E05-VU-001__take_1eb26c4b.mp4"}, out, True)
            self.assertEqual(downloaded, [out / "_alt_takes/E05-VU-001__take_1eb26c4b.mp4"])
            self.assertEqual(row["remote_status"], "completed")
            with self.assertRaises(ValueError):
                poller.poll_one(1, {"task_key": "x", "task_id": "t", "output_name": "../escape.mp4"}, out, True)


class PipelineReentryPollsBeforeRecompileTest(unittest.TestCase):
    """The S6 wave loop harvests a live-bound re-entry wave without compiling or submitting."""

    def _ctx(self, root: Path, *, paid: bool):
        import nalu_pipeline as pipeline
        work = root / "workflow/nalu" / EP
        reports = work / "preproduction/reports"
        reports.mkdir(parents=True, exist_ok=True)
        calls = []
        ctx = SimpleNamespace(
            episode=EP, dry=not paid, paid_enabled=paid, planned_commands=[], run_id="T",
            p=SimpleNamespace(work=work, video_media=work / "video",
                              video_transaction=work / "preproduction/E05_VIDEO_TRANSACTION_MANIFEST_V1.json",
                              video_submit=reports / "E05_VIDEO_SUBMIT_V1_wave28.json",
                              video_remote_status=reports / "E05_VIDEO_REMOTE_STATUS_V1_wave28.json"),
            say=lambda *_: None)

        def run(argv, *, name, **_kw):
            calls.append((name, [str(a) for a in argv]))
            ctx.p.video_remote_status.write_text(json.dumps({"all_completed": True, "results": []}),
                                                 encoding="utf-8")
            return {"name": name, "exit_code": 0}
        ctx.run = run
        return pipeline, ctx, calls

    def _seed(self, root: Path):
        parked = _park(root, KEY)
        store = root / "workflow/tasks/giggle_video_submit_transactions" / EP
        _tx(store, KEY, "2" * 64, "4e2d4a56-2624-48d7-93e9-6fe7be3d2761", parked + 60)
        _tx(store, KEY, "8" * 64, "1eb26c4b-852e-47d9-b4f6-eca50af4e76a", parked + 660)
        _tx(store, "E05-VU-014", "a" * 64, "c7c6ed06-bd34-4bec-b637-a4c0cae87372", parked + 680)

    def test_dry_reentry_plans_zero_posts_and_polls_both_takes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            pipeline, ctx, calls = self._ctx(root, paid=False)
            wave = {"wave": 28, "units": [KEY], "submit_report": str(ctx.p.video_submit)}
            with mock.patch.object(pipeline, "ENGINE", root), \
                 mock.patch.object(pipeline, "_stage_s6_body", side_effect=AssertionError("recompiled")):
                plan = pipeline._s6_live_bound_wave(ctx, [KEY])
                self.assertIsNotNone(plan)
                result = pipeline._s6_poll_live_bound_wave(ctx, wave, plan)
            self.assertEqual(result.status, pipeline.DRY)
            self.assertEqual(calls, [], "nothing runs while paid steps are disabled")
            steps = [c["step"] for c in ctx.planned_commands]
            self.assertEqual(steps, ["s6_poll_live_bound_wave28"])
            self.assertFalse(any("submit_giggle_video_manifest" in c["paid_command"] for c in ctx.planned_commands))
            poll_input = json.loads(Path(result.details["live_bound_poll"]["poll_input"]).read_text(encoding="utf-8"))
            self.assertEqual(poll_input["posts_planned"], 0)
            self.assertEqual([(t["task_key"], t["task_id"][:8]) for t in poll_input["tasks"]],
                             [(KEY, "4e2d4a56"), (f"{KEY}__take_1eb26c4b", "1eb26c4b")])
            self.assertEqual(poll_input["tasks"][1]["output_name"], f"_alt_takes/{KEY}__take_1eb26c4b.mp4")

    def test_paid_reentry_runs_only_the_get_poll(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            pipeline, ctx, calls = self._ctx(root, paid=True)
            wave = {"wave": 29, "units": ["E05-VU-014"], "submit_report": str(ctx.p.video_submit)}
            with mock.patch.object(pipeline, "ENGINE", root):
                plan = pipeline._s6_live_bound_wave(ctx, ["E05-VU-014"])
                result = pipeline._s6_poll_live_bound_wave(ctx, wave, plan)
            self.assertEqual(result.status, pipeline.PASS)
            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0][1][1].endswith("poll_giggle_submit_report.py"))

    def test_unbound_unit_is_not_short_circuited(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pipeline, ctx, _ = self._ctx(root, paid=False)
            with mock.patch.object(pipeline, "ENGINE", root):
                self.assertIsNone(pipeline._s6_live_bound_wave(ctx, ["E05-VU-009"]))

    def test_planner_counts_a_drifted_live_task_as_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            pipeline, ctx, _ = self._ctx(root, paid=False)
            with mock.patch.object(pipeline, "ENGINE", root):
                keys = pipeline.s6_bound_task_keys(ctx, [{"task_key": KEY}, {"task_key": "E05-VU-009"}],
                                                   lambda _t: "f" * 64)
            self.assertEqual(keys, {KEY})


if __name__ == "__main__":
    unittest.main()
