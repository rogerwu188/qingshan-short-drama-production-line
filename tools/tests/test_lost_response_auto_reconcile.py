"""Automatic reconciliation of lost HopsAPI create responses (line owner standing ruling A).

Fleet devices 1485 E03 S6 and 1101 E20 S5 (2026-11-21): a HopsAPI 502 / timeout during a paid create left the
transaction RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION (1101: the S5 neutral health probe, which the
reconciliation skipped for good); the budget gate refused every further submit and the line stopped until a
human pasted ruling A.  Covered here, offline (every HTTP call mocked at ``hopsapi_usage.hops._http``):

* a billed task found for the lost POST -> bound, polled, never resubmitted;
* nothing found after the grace period -> written off at the reserved price (counted as spend) and exactly ONE
  new attempt; the written-off row stays counted after the new intent replaced it;
* the resubmit losing its response again -> written off (counted) and refused: no paid retry loop;
* the budget gate is unblocked once reconciled; before that the refusal is a remote WAIT the tick re-runs
  (pipeline + paid_stage.sh preflight), never a stop for a human;
* a failing usage read writes nothing off; the kill switch stops every automatic use;
* a lost health probe is reconciled.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
RT_TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _path in (str(ROOT), str(ROOT / "tools"), str(RT_TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import hopsapi_usage as usage  # noqa: E402
import nalu_budget_ledger as ledger  # noqa: E402
import paid_run_status as prs  # noqa: E402

NOW = datetime(2026, 11, 21, 7, 0, 0, tzinfo=timezone.utc)
ENV = {"HOPSAPI_API_KEY": "test-key-not-real", "HOPSAPI_RETRY_DELAY_SECONDS": "0"}
EP = "E03"
KEY = "E03-VU-014"
FOUND = "tsk_found_after_502_00000000000000001"


def at(minutes_before: float) -> str:
    return (NOW - timedelta(minutes=minutes_before)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def billed(task_id: str, minutes_before: float, model: str = "MiniMax-H3") -> dict:
    return {"request_id": task_id, "kind": "media", "model": model, "charge": "42.000000", "status": 200,
            "created_at": (NOW - timedelta(minutes=minutes_before)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "key": {"id": 1, "name": "fleet"}}


class FakeUsage:
    """GET-only usage API; ``fail`` raises on every call."""

    def __init__(self, rows=None, fail=None):
        self.rows = list(rows or [])
        self.fail = fail
        self.calls: list[dict] = []

    def __call__(self, method, url, *, body=None, headers=None, timeout=None):
        assert method == "GET", "reconciliation must never POST"
        parsed = urlparse(url)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        self.calls.append(query)
        if self.fail:
            raise self.fail
        rows = [r for r in self.rows if r["model"] == query.get("model", r["model"])]
        return 200, {"data": rows, "has_more": False, "next_cursor": None}, "{}"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = Path(self.tmp.name)
        self.root = self.engine / "workflow" / "tasks"
        env = patch.dict(os.environ, ENV)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(usage.KILL_SWITCH_ENV, None)

    def store(self, kind: str = "video") -> Path:
        directory = self.root / usage.STORES[kind] / EP
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def write(self, path: Path, **fields) -> Path:
        path.write_text(json.dumps({"provider": "hopsapi", "task_key": KEY, "submission_fingerprint": "fp",
                                    **fields}), encoding="utf-8")
        return path

    def lost(self, path: Path, attempt: str, minutes_before: float, **fields) -> Path:
        return self.write(path, attempt_id=attempt, state=usage.LOST_STATE, intent_recorded_at=at(minutes_before),
                          response_lost_at=at(minutes_before - 0.5), estimated_credits=42, **fields)

    def reconcile(self, fake, now=NOW, auto=True):
        err = io.StringIO()
        with patch.object(usage.hops, "_http", fake), redirect_stderr(err):
            report = usage.reconcile_episode(EP, tasks_root=self.root, now=now, auto=auto)
        return report, err.getvalue()

    def load(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def ledger_scan(self):
        with patch.object(ledger, "ENGINE_ROOT", self.engine):
            return ledger.scan_transaction_states(EP), ledger.scan_hopsapi_spend(EP)

    def video_prior_bound(self, path: Path):
        from tools import submit_giggle_video_manifest_v2 as video  # noqa: PLC0415
        with patch.object(video, "task_fingerprint", return_value="fp"), \
                patch.object(video, "transaction_path", return_value=path):
            return video.prior_bound({"task_key": KEY}, path.parent)


class VideoLostResponseTest(Base):
    def test_remote_task_found_is_bound_and_never_resubmitted(self):
        path = self.lost(self.store() / f"{KEY}__fp.json", "att-1", 30)
        report, log = self.reconcile(FakeUsage(rows=[billed(FOUND, 25)]))
        self.assertEqual(report["kinds"]["video"]["status"], usage.BOUND_STATE)
        row = self.load(path)
        self.assertEqual((row["state"], row["task_id"]), ("SUBMITTED_TASK_ID_BOUND", FOUND))
        self.assertIn(f"LOST_RESPONSE_RECONCILED kind=BOUND episode={EP} store=video task_key={KEY}", log)
        self.assertIn(f"task_id={FOUND}", log)
        recovered = self.video_prior_bound(path)  # the re-entry polls the bound task: no POST
        self.assertEqual((recovered["task_id"], recovered["recovered_from_transaction"]), (FOUND, True))
        states, spend = self.ledger_scan()
        self.assertEqual(states["unresolved_transactions"], [])
        self.assertEqual(spend["settled_credits"], 42)  # the billed row's charge

    def test_nothing_found_after_grace_is_written_off_and_gets_exactly_one_new_attempt(self):
        path = self.lost(self.store() / f"{KEY}__fp.json", "att-1", 30)
        report, log = self.reconcile(FakeUsage(rows=[]))
        self.assertEqual(report["kinds"]["video"]["status"], usage.AUTO_WRITEOFF_STATE)
        row = self.load(path)
        self.assertEqual((row["state"], row["written_off_credits"], row["credit_status"]),
                         (usage.AUTO_WRITEOFF_STATE, 42.0, usage.NO_BILLED_TASK_CREDIT_STATUS))
        self.assertEqual(row["written_off_by_order"]["kind"], "LINE_OWNER_STANDING_RULING")
        self.assertIn("LOST_RESPONSE_RECONCILED kind=WRITTEN_OFF", log)
        self.assertIn("credits=42.0 reason=NO_BILLED_TASK_FOUND resubmit=ONE_NEW_ATTEMPT", log)
        states, spend = self.ledger_scan()
        self.assertEqual(states["unresolved_transactions"], [])           # the budget gate is unblocked
        self.assertEqual(spend["settled_credits"], 42)                     # reserved credits counted as spent
        self.assertIsNone(self.video_prior_bound(path))                    # ONE new attempt may POST
        self.assertIsNone(self.video_prior_bound(path))                    # stopped before its intent: still open
        archive = path.with_name(path.name + usage.RETRY_ARCHIVE_SUFFIX)
        self.assertEqual(self.load(archive)["attempt_id"], "att-1")
        # the new attempt's intent replaces the live row: the write-off stays counted through the archive
        self.write(path, attempt_id="att-2", state="SUBMITTED_TASK_ID_BOUND", task_id="tsk_new",
                   intent_recorded_at=at(1), estimated_credits=42, provider_cost_credits=40)
        _states, spend = self.ledger_scan()
        self.assertEqual(spend["settled_credits"], 82)

    def test_second_lost_response_on_the_resubmit_does_not_loop(self):
        path = self.lost(self.store() / f"{KEY}__fp.json", "att-1", 60)
        self.reconcile(FakeUsage(rows=[]))
        self.assertIsNone(self.video_prior_bound(path))                    # the one new attempt
        self.lost(path, "att-2", 30)                                       # ...whose response is lost too
        report, log = self.reconcile(FakeUsage(rows=[]))
        self.assertEqual(report["kinds"]["video"]["status"], usage.AUTO_WRITEOFF_STATE)
        self.assertIn("attempt=att-2", log)
        with self.assertRaisesRegex(RuntimeError, "one automatic new attempt after a lost response is already used"):
            self.video_prior_bound(path)
        with self.assertRaises(RuntimeError):                              # and stays refused
            self.video_prior_bound(path)
        states, spend = self.ledger_scan()
        self.assertEqual(states["unresolved_transactions"], [])           # nothing left unresolved...
        self.assertEqual(spend["settled_credits"], 84)                     # ...and both losses counted

    def test_provider_query_error_writes_nothing_off_and_waits(self):
        path = self.lost(self.store() / f"{KEY}__fp.json", "att-1", 30)
        before = path.read_text(encoding="utf-8")
        report, log = self.reconcile(FakeUsage(fail=usage.hops.HopsapiHTTPError(503, None, "busy")))
        self.assertEqual(report["kinds"]["video"]["status"], "USAGE_READ_FAILED_NOTHING_CHANGED")
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        self.assertNotIn("LOST_RESPONSE_RECONCILED", log)
        self.assertIsNone(self.video_prior_bound_or_error(path))
        states, _spend = self.ledger_scan()
        wait = usage.lost_response_wait(EP, failures=["UNRECONCILED_TRANSACTIONS:1"],
                                        unresolved=states["unresolved_transactions"], tasks_root=self.root, now=NOW)
        self.assertEqual(wait["phase"], "RECONCILE_DUE")                  # retried by the next re-run
        self.assertTrue(wait["blocker"].startswith(f"{usage.WAIT_BLOCKER}:1:RECONCILE_DUE"))

    def video_prior_bound_or_error(self, path: Path):
        with self.assertRaisesRegex(RuntimeError, "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION"):
            self.video_prior_bound(path)                                   # a lost row is never resent
        return None

    def test_within_grace_nothing_is_queried_and_the_budget_refusal_is_a_wait(self):
        self.lost(self.store() / f"{KEY}__fp.json", "att-1", 5)
        fake = FakeUsage(rows=[])
        report, _log = self.reconcile(fake)
        self.assertEqual(report["kinds"]["video"]["status"], "PENDING_GRACE")
        self.assertEqual(fake.calls, [])
        states, _spend = self.ledger_scan()
        unresolved = states["unresolved_transactions"]
        self.assertEqual(len(unresolved), 1)
        wait = usage.lost_response_wait(EP, failures=["UNRECONCILED_TRANSACTIONS:1"], unresolved=unresolved,
                                        tasks_root=self.root, now=NOW)
        self.assertEqual((wait["lost"], wait["phase"], wait["task_keys"]), (1, "PENDING_GRACE", [KEY]))
        self.assertEqual(wait["eligible_at"], (NOW + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        # anything else in the refusal stays a hard stop
        self.assertIsNone(usage.lost_response_wait(
            EP, failures=["UNRECONCILED_TRANSACTIONS:1", "EPISODE_CREDIT_CAP_WOULD_BE_EXCEEDED:x"],
            unresolved=unresolved, tasks_root=self.root, now=NOW))
        self.assertIsNone(usage.lost_response_wait(
            EP, failures=["UNRECONCILED_TRANSACTIONS:2"],
            unresolved=unresolved + [{"transaction": str(self.store() / "other.json")}], tasks_root=self.root))
        # paid_run_status: a stage blocked only by this is a remote wait the tick re-runs
        verdict = prs.classify({"stages": {"S6": {"status": "BLOCKED", "blockers": [wait["blocker"]]}}}, "S6", "S6")
        self.assertEqual((verdict["verdict"], verdict["interval_s"]), (prs.WAIT, 300))

    def test_kill_switch_stops_every_automatic_use(self):
        path = self.lost(self.store() / f"{KEY}__fp.json", "att-1", 30)
        fake = FakeUsage(rows=[])
        with patch.dict(os.environ, {usage.KILL_SWITCH_ENV: "0"}):
            report, _log = self.reconcile(fake)
            self.assertEqual(report["status"], "AUTO_RECONCILE_DISABLED")
            self.assertTrue(report["unresolved_remaining"])
            states, _spend = self.ledger_scan()
            self.assertIsNone(usage.lost_response_wait(EP, failures=["UNRECONCILED_TRANSACTIONS:1"],
                                                       unresolved=states["unresolved_transactions"],
                                                       tasks_root=self.root))
            self.assertEqual(fake.calls, [])
            self.assertEqual(self.load(path)["state"], usage.LOST_STATE)
            manual, _log = self.reconcile(fake, auto=False)              # the operator CLI still works
            self.assertEqual(manual["kinds"]["video"]["status"], usage.AUTO_WRITEOFF_STATE)


class ImageLostResponseTest(Base):
    def setUp(self):
        super().setUp()
        import tools.submit_giggle_image_manifest as submitter  # noqa: PLC0415
        self.submitter = submitter
        self.task = {"task_key": "E20-S02-04-KEYFRAME-V1", "prompt_sha256": "p" * 64,
                     "reference_bindings": [{"role": "character", "sha256": "r" * 64}]}
        self.path = submitter.transaction_path(self.store("image"), self.task)

    def image_lost(self, attempt: str, minutes_before: float) -> None:
        self.lost(self.path, attempt, minutes_before, task_key=self.task["task_key"],
                  submission_fingerprint=self.submitter.submission_fingerprint(self.task))

    def test_keyframe_written_off_once_then_refused(self):
        self.image_lost("img-1", 30)
        report, _log = self.reconcile(FakeUsage(rows=[]))
        self.assertEqual(report["kinds"]["image"]["status"], usage.AUTO_WRITEOFF_STATE)
        self.assertIsNone(self.submitter.prior_submission_result(self.task, self.store("image")))
        self.image_lost("img-2", 12)
        self.reconcile(FakeUsage(rows=[]))
        with self.assertRaisesRegex(self.submitter.DuplicateSubmissionBlocked, "already used"):
            self.submitter.prior_submission_result(self.task, self.store("image"))
        states, spend = self.ledger_scan()
        self.assertEqual(states["unresolved_transactions"], [])
        self.assertEqual(spend["settled_credits"], 84)

    def test_lost_health_probe_is_reconciled(self):
        # device 1101 E20 S5: the neutral health probe lost its response and nothing ever settled it
        probe = self.write(self.store("image") / "HOPSAPI-IMAGE-HEALTH-PROBE__abc.json",
                           task_key="HOPSAPI-IMAGE-HEALTH-PROBE", hopsapi_health_probe=True, attempt_id="probe-1",
                           state=usage.LOST_STATE, intent_recorded_at=at(20), estimated_credits=0.2)
        states, _spend = self.ledger_scan()
        self.assertEqual(len(states["unresolved_transactions"]), 1)       # the gate refuses on it...
        self.assertIsNotNone(usage.lost_response_wait(EP, failures=["UNRECONCILED_TRANSACTIONS:1"],
                                                      unresolved=states["unresolved_transactions"],
                                                      tasks_root=self.root, now=NOW))  # ...as a wait
        report, log = self.reconcile(FakeUsage(rows=[]))
        self.assertEqual(report["kinds"]["image"]["status"], usage.AUTO_WRITEOFF_STATE)
        self.assertEqual(self.load(probe)["written_off_credits"], 0.2)
        self.assertIn("task_key=HOPSAPI-IMAGE-HEALTH-PROBE", log)
        states, _spend = self.ledger_scan()
        self.assertEqual(states["unresolved_transactions"], [])


class PipelineLostWaitTest(Base):
    def test_budget_refusal_only_by_lost_creates_is_recorded_as_a_wait(self):
        import nalu_pipeline as pipeline  # noqa: PLC0415
        self.lost(self.store() / f"{KEY}__fp.json", "att-1", 5)
        states, _spend = self.ledger_scan()
        logs = self.engine / "logs"
        logs.mkdir()
        (logs / "r_budget_s6_submit.json").write_text(json.dumps({
            "failures": ["UNRECONCILED_TRANSACTIONS:1"], "durable_transaction_stores": states}))
        ctx = pipeline.Ctx.__new__(pipeline.Ctx)
        ctx.episode, ctx.run_id, ctx.p = EP, "r", SimpleNamespace(logs=logs)
        messages: list[str] = []
        ctx.say = messages.append
        with patch.object(pipeline, "ENGINE", self.engine):
            wait = ctx.lost_response_wait({}, label="s6_submit")
        self.assertTrue(wait["blocker"].startswith(usage.WAIT_BLOCKER))
        self.assertIs(ctx._lost_response_wait, wait)
        self.assertIn("no human needed", messages[-1])
        (logs / "r_budget_s6_submit.json").write_text(json.dumps({
            "failures": ["EPISODE_CREDIT_CAP_WOULD_BE_EXCEEDED:x"], "durable_transaction_stores": states}))
        with patch.object(pipeline, "ENGINE", self.engine):
            self.assertIsNone(ctx.lost_response_wait({}, label="s6_submit"))
        self.assertIsNone(ctx._lost_response_wait)                         # the last refusal decides

    def test_stage_loop_turns_the_hard_stop_into_a_remote_wait(self):
        source = (RT_TOOLS / "nalu_pipeline.py").read_text(encoding="utf-8")
        self.assertIn('if result.status == HARD_STOP and lost_wait:', source)
        self.assertIn('ctx._lost_response_wait = None\n        try:\n            result = STAGE_FUNCS[sid](ctx)', source)


FAKE_PY = r"""#!/bin/bash
case "$1" in
  */paid_run_status.py) exec python3 "$@" ;;
  */hopsapi_image_client.py|*/hopsapi_video_client.py) echo giggle; exit 0 ;;
  */hopsapi_usage.py)
    if [ "$2" = "wait-state" ]; then echo "HOPSAPI_LOST_RESPONSE_RECONCILING:1:PENDING_GRACE:eligible_at=X"; exit 0; fi
    exit 0 ;;
  */nalu_budget_ledger.py) echo '{"status": "BLOCKED"}'; exit 2 ;;
  */nalu_pipeline.py) echo "pipeline must not run"; exit 9 ;;
  -) cat >/dev/null; exit 0 ;;
  -c) echo "$NALU_LATEST_ORDER_SEQ"; exit 0 ;;
esac
exit 0
"""


class PaidStagePreflightWaitTest(unittest.TestCase):
    """paid_stage.sh with a fake interpreter (no provider, no key, no spend): a preflight refused only by lost
    creates ends the turn as a remote wait the tick re-runs, instead of exit 3 for a human."""

    def test_preflight_refusal_by_lost_creates_records_a_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime"
            (runtime / "runtime").mkdir(parents=True)
            fake = root / "fakepy"
            fake.write_text(FAKE_PY)
            fake.chmod(0o755)
            orders = root / "orders.json"
            orders.write_text(json.dumps({"latest_order_seq": 7, "orders": []}))
            env = {"PATH": os.environ["PATH"], "HOME": str(root), "NALU_VENV_PYTHON": str(fake),
                   "GIGGLE_API_KEY": "test-not-a-key", "NALU_PAID_ORDER_SEQ": "7", "NALU_LATEST_ORDER_SEQ": "7",
                   "NALU_RUNTIME_ROOT": str(runtime), "NALU_ENGINE_ROOT": str(ROOT),
                   "NALU_SUPERVISOR_ORDERS_PATH": str(orders), "NALU_LINE_OWNER_ID": "owner",
                   "NALU_IMAGE_PROVIDER": "giggle", "NALU_PAID_STAGE_NO_DETACH": "1"}
            out = subprocess.run(["/bin/bash", str(RT_TOOLS / "paid_stage.sh"), EP, "S6", "S6"], env=env,
                                 capture_output=True, text=True, timeout=120)
            self.assertEqual(out.returncode, 4, out.stderr)
            self.assertNotIn("pipeline must not run", out.stdout)
            self.assertIn("refused only by lost HopsAPI creates", out.stdout)
            self.assertTrue(out.stdout.strip().splitlines()[-1].startswith(prs.NEXT_WAIT), out.stdout)
            rec = prs.last_record(runtime, EP)
            self.assertEqual((rec["verdict"], rec["reason"], rec["from"], rec["until"]),
                             (prs.WAIT, "REMOTE_PENDING:HOPSAPI_LOST_RESPONSE_RECONCILING", "S6", "S6"))
            now = rec["finished_at"]
            self.assertEqual(prs.tick_decision(runtime, EP, since=now - 60, reruns_done=0, now=now + 10)["action"],
                             "BACKOFF")
            due = prs.tick_decision(runtime, EP, since=now - 60, reruns_done=0, now=now + 301)
            self.assertEqual((due["action"], due["from"], due["until"]), ("RERUN", "S6", "S6"))
            capped = prs.tick_decision(runtime, EP, since=now - 60, reruns_done=36, now=now + 301)
            self.assertEqual(capped["action"], "RESUME")                   # 3 h later the producer judges


if __name__ == "__main__":
    unittest.main()
