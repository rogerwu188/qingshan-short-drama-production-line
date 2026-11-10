"""HopsAPI billing-usage reconciliation of lost create responses (lab E11 S6, 2026-10-31).

Every HTTP call is mocked at ``hopsapi_usage.hops._http``: no request leaves this host.  Covered:
grace period, VERIFIED_ZERO_NO_REMOTE_TASK, single-task adoption (+ poller pickup), manual
attribution (and that its own ids never make themselves look bound), scope=key proof vs the
scope=account fallback, a failed usage read changing nothing, the image kind, the submitters
letting a verified-zero attempt POST again, the ledger states, and the summary aggregation.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
for _path in (str(ROOT), str(ROOT / "tools"), str(ROOT / "lines" / "nalu" / "runtime" / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import hopsapi_usage as usage  # noqa: E402
import nalu_budget_ledger as ledger  # noqa: E402
import poll_giggle_submit_report as poller  # noqa: E402

NOW = datetime(2026, 10, 31, 9, 0, 0, tzinfo=timezone.utc)
ENV = {"HOPSAPI_API_KEY": "test-key-not-real", "HOPSAPI_RETRY_DELAY_SECONDS": "0"}
SIB = "tsk_sibling_000000000000000000000001"
OTHER = "tsk_unattributed_0000000000000000001"


def at(minutes_before: float) -> str:
    return (NOW - timedelta(minutes=minutes_before)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class FakeUsage:
    """Scripted usage API: rows per scope, one page size of 1 to exercise the cursor."""

    def __init__(self, rows=None, account_rows=None, fail=None, page=1):
        self.rows = list(rows or [])
        self.account_rows = list(self.rows if account_rows is None else account_rows)
        self.calls: list[dict] = []
        self.fail = fail
        self.page = page

    def __call__(self, method, url, *, body=None, headers=None, timeout=None):
        assert method == "GET", "usage reconciliation must never POST"
        parsed = urlparse(url)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        self.calls.append({"path": parsed.path, "query": query, "headers": dict(headers or {})})
        if self.fail:
            raise self.fail
        if parsed.path.endswith("/account/usage"):
            rows = self.rows if query.get("scope") == "key" else self.account_rows
            rows = [r for r in rows if r["model"] == query.get("model", r["model"])]
            start = int(query.get("cursor") or 0)
            chunk = rows[start:start + self.page]
            more = start + self.page < len(rows)
            body = {"data": chunk, "has_more": more, "next_cursor": str(start + self.page) if more else None}
            return 200, body, json.dumps(body)
        raise AssertionError(f"unexpected url {url}")


def row(task_id, minutes_before, model="MiniMax-H3", charge="6.230000", key_id=15067):
    return {"request_id": task_id, "kind": "media", "model": model, "charge": charge, "status": 200,
            "created_at": (NOW - timedelta(minutes=minutes_before)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "key": {"id": key_id, "name": "lab", "key_masked": "sk-…"}}


class ReconcileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "workflow" / "tasks"
        self.env = patch.dict(os.environ, ENV)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def tx(self, name, *, kind="video", episode="E11", **fields):
        directory = self.root / usage.STORES[kind] / episode
        directory.mkdir(parents=True, exist_ok=True)
        payload = {"provider": "hopsapi", "task_key": name, "attempt_id": f"att-{name}",
                   "submission_fingerprint": f"fp-{name}", **fields}
        path = directory / f"{name}__abc.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def lost(self, name, minutes_before, **fields):
        return self.tx(name, state=usage.LOST_STATE, intent_recorded_at=at(minutes_before),
                       response_lost_at=at(minutes_before - 1), **fields)

    def run_reconcile(self, fake, **kw):
        with patch.object(usage.hops, "_http", fake):
            return usage.reconcile_episode("E11", tasks_root=self.root, now=NOW, **kw)

    def load(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def test_grace_period_defers_without_network(self):
        self.lost("E11-VU-008", 10)
        fake = FakeUsage()
        report = self.run_reconcile(fake)
        self.assertEqual(report["kinds"]["video"]["status"], "PENDING_GRACE")
        self.assertEqual(fake.calls, [])
        self.assertTrue(report["unresolved_remaining"])

    def test_no_unattributed_rows_verifies_zero_with_evidence(self):
        a = self.lost("E11-VU-008", 44)
        b = self.lost("E11-VU-018", 44)
        self.tx("E11-VU-013", state="SUBMITTED_TASK_ID_BOUND", task_id=SIB, intent_recorded_at=at(44))
        fake = FakeUsage(rows=[row(SIB, 42), row("tsk_other_episode_bound", 30)])
        self.tx("E10-VU-001", episode="E10", state="SUBMITTED_TASK_ID_BOUND", task_id="tsk_other_episode_bound")
        report = self.run_reconcile(fake)
        video = report["kinds"]["video"]
        self.assertEqual(video["status"], usage.VERIFIED_ZERO_STATE)
        self.assertEqual(video["scope"], "key")  # sibling bound in the same run is billed on this key
        self.assertFalse(report["unresolved_remaining"])
        for path in (a, b):
            data = self.load(path)
            self.assertEqual(data["state"], usage.VERIFIED_ZERO_STATE)
            self.assertEqual(data["credit"], 0)
            self.assertEqual(data["retry_guard"], "RETRY_ALLOWED_NEW_ATTEMPT")
            self.assertEqual(data["state_history"][0]["state"], usage.LOST_STATE)
            self.assertIn("response_lost_at", data)  # the lost-response record is kept
        first = fake.calls[0]["query"]
        self.assertEqual((first["kind"], first["model"], first["scope"], first["limit"]),
                         ("media", "MiniMax-H3", "key", "500"))
        self.assertEqual(first["from"], (NOW - timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.assertTrue(all("Bearer test-key-not-real" == c["headers"]["Authorization"] for c in fake.calls))
        lines = usage.evidence_path(self.root, "E11").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        record = json.loads(lines[0])
        self.assertEqual(record["row_count"], 2)
        self.assertEqual(record["query"]["pages"], 2)
        self.assertEqual(record["transaction_before"]["state"], usage.LOST_STATE)
        self.assertNotIn("test-key-not-real", usage.evidence_path(self.root, "E11").read_text(encoding="utf-8"))
        # the ledger now treats them as settled (0), not unresolved
        with patch.object(ledger, "ENGINE_ROOT", self.root.parent.parent):
            states = ledger.scan_transaction_states("E11")
            spend = ledger.scan_hopsapi_spend("E11")
        self.assertEqual(states["unresolved_transactions"], [])
        self.assertEqual(spend["pending_exposure_credits"], 160)  # only the sibling (no estimate) counts

    def test_single_unattributed_row_after_intent_is_adopted_and_polled(self):
        path = self.lost("E11-VU-008", 44, estimated_credits=7)
        self.tx("E11-VU-013", state="SUBMITTED_TASK_ID_BOUND", task_id=SIB, intent_recorded_at=at(44))
        report = self.run_reconcile(FakeUsage(rows=[row(SIB, 42), row(OTHER, 40)]))
        self.assertEqual(report["kinds"]["video"]["status"], usage.BOUND_STATE)
        data = self.load(path)
        self.assertEqual((data["state"], data["task_id"]), ("SUBMITTED_TASK_ID_BOUND", OTHER))
        self.assertEqual(data["task_id_source"], "HOPSAPI_USAGE_RECONCILIATION_ADOPTED")
        self.assertEqual(data["provider_cost_credits"], 6.23)
        with patch.object(ledger, "ENGINE_ROOT", self.root.parent.parent):
            spend = ledger.scan_hopsapi_spend("E11")
        self.assertIn(OTHER, {r["task_id"] for r in spend["rows"] if r["status"] == "SETTLED_PROVIDER_COST"})
        # a poll-only re-entry reads the old wave report, where the unit is a failure without task id
        report_rows = poller.adopted_failure_rows(
            {"failures": [{"task_key": "E11-VU-008", "transaction": str(path)}]}, {SIB})
        self.assertEqual(report_rows[0]["task_id"], OTHER)
        self.assertEqual(report_rows[0]["provider"], "hopsapi")

    def test_row_billed_before_intent_is_foreign_not_adopted_and_does_not_block(self):
        # …0899 E01 (one HopsAPI key shared by the fleet): a row billed before the lost intent is another
        # device's task -- never adopted, and it no longer holds the episode at NEEDS_MANUAL_ATTRIBUTION
        path = self.lost("E11-VU-008", 30)
        report = self.run_reconcile(FakeUsage(rows=[row(OTHER, 40)]))
        self.assertEqual(report["kinds"]["video"]["status"], usage.VERIFIED_ZERO_STATE)
        data = self.load(path)
        self.assertEqual(data["state"], usage.VERIFIED_ZERO_STATE)
        self.assertNotIn("task_id", data)

    def test_post_intent_row_still_decides_next_to_a_pre_intent_foreign_row(self):
        path = self.lost("E11-VU-008", 30)
        report = self.run_reconcile(FakeUsage(rows=[row(OTHER, 40), row(SIB, 20)]))
        self.assertEqual(report["kinds"]["video"]["status"], usage.BOUND_STATE)
        self.assertEqual(self.load(path)["task_id"], SIB)

    def test_ambiguous_rows_need_manual_attribution_and_stay_unresolved(self):
        a = self.lost("E11-VU-008", 44)
        self.lost("E11-VU-018", 44)
        self.tx("E11-VU-013", state="SUBMITTED_TASK_ID_BOUND", task_id=SIB, intent_recorded_at=at(44))
        fake = FakeUsage(rows=[row(SIB, 42), row(OTHER, 40)])
        report = self.run_reconcile(fake)
        self.assertEqual(report["kinds"]["video"]["status"], usage.MANUAL_STATE)
        self.assertEqual(report["kinds"]["video"]["unattributed_task_ids"], [OTHER])
        self.assertEqual(self.load(a)["state"], usage.MANUAL_STATE)
        with patch.object(ledger, "ENGINE_ROOT", self.root.parent.parent):
            unresolved = ledger.scan_transaction_states("E11")["unresolved_transactions"]
        self.assertEqual(len(unresolved), 2)
        # re-run: the ids written as unattributed_task_ids never count as bound
        again = self.run_reconcile(fake)
        self.assertEqual(again["kinds"]["video"]["status"], usage.MANUAL_STATE)
        self.assertEqual(len(self.load(a)["usage_reconciliation_history"]), 2)

    def test_other_episode_lost_post_blocks_adoption(self):
        self.lost("E11-VU-008", 44)
        self.tx("E12-VU-001", episode="E12", state=usage.LOST_STATE, intent_recorded_at=at(50))
        report = self.run_reconcile(FakeUsage(rows=[row(OTHER, 40)]))
        self.assertEqual(report["kinds"]["video"]["status"], usage.MANUAL_STATE)

    def test_unproven_key_widens_to_account_scope(self):
        path = self.lost("E11-VU-008", 44, hopsapi_key_fingerprint="0000000000000000")
        fake = FakeUsage(rows=[], account_rows=[row(OTHER, 40, key_id=1)])
        report = self.run_reconcile(fake)
        self.assertEqual(report["kinds"]["video"]["scope"], "account")
        self.assertEqual([c["query"]["scope"] for c in fake.calls], ["key", "account"])
        self.assertEqual(self.load(path)["state"], usage.BOUND_STATE)

    def test_current_key_fingerprint_keeps_key_scope(self):
        with patch.dict(os.environ, ENV):
            fp = usage.key_fingerprint()
        self.assertEqual(len(fp), 16)
        self.assertNotIn("test-key", fp)
        self.lost("E11-VU-008", 44, hopsapi_key_fingerprint=fp)
        fake = FakeUsage(rows=[], account_rows=[row(OTHER, 40)])
        report = self.run_reconcile(fake)
        self.assertEqual(report["kinds"]["video"]["status"], usage.VERIFIED_ZERO_STATE)
        self.assertEqual([c["query"]["scope"] for c in fake.calls], ["key"])

    def test_failed_usage_read_changes_nothing(self):
        path = self.lost("E11-VU-008", 44)
        before = path.read_text(encoding="utf-8")
        report = self.run_reconcile(FakeUsage(fail=usage.hops.HopsapiHTTPError(401, None, "bad key")))
        self.assertEqual(report["kinds"]["video"]["status"], "USAGE_READ_FAILED_NOTHING_CHANGED")
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        self.assertTrue(report["unresolved_remaining"])

    def test_dry_run_writes_nothing(self):
        path = self.lost("E11-VU-008", 44)
        before = path.read_text(encoding="utf-8")
        report = self.run_reconcile(FakeUsage(rows=[]), dry_run=True)
        self.assertEqual(report["kinds"]["video"]["status"], usage.VERIFIED_ZERO_STATE)
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        self.assertFalse(usage.evidence_path(self.root, "E11").exists())

    def test_image_kind_uses_its_model_and_shorter_grace(self):
        path = self.tx("E11-S01-01-KEYFRAME-V1", kind="image", state=usage.LOST_STATE,
                       intent_recorded_at=at(12))
        fake = FakeUsage(rows=[row("tsk_bound_img", 11, model="gpt-image-2")])
        self.tx("E11-S01-02-KEYFRAME-V1", kind="image", state="SUBMITTED_TASK_ID_BOUND",
                task_id="tsk_bound_img", intent_recorded_at=at(12))
        report = self.run_reconcile(fake)
        self.assertEqual(report["kinds"]["image"]["status"], usage.VERIFIED_ZERO_STATE)
        self.assertEqual(fake.calls[0]["query"]["model"], "gpt-image-2")
        self.assertEqual(self.load(path)["state"], usage.VERIFIED_ZERO_STATE)

    def test_nothing_lost_means_no_network(self):
        self.tx("E11-VU-013", state="SUBMITTED_TASK_ID_BOUND", task_id=SIB)
        fake = FakeUsage()
        report = self.run_reconcile(fake)
        self.assertEqual(fake.calls, [])
        self.assertFalse(report["unresolved_remaining"])
        self.assertEqual(usage.pending_lost("E11", self.root), 0)


class SubmitterReentryTest(unittest.TestCase):
    def test_video_prior_bound_lets_verified_zero_post_again(self):
        from tools import submit_giggle_video_manifest_v2 as video
        task = {"task_key": "E11-VU-008"}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(video, "task_fingerprint", return_value="fp"), \
                patch.object(video, "transaction_path", return_value=Path(tmp) / "t.json"):
            (Path(tmp) / "t.json").write_text(json.dumps({"submission_fingerprint": "fp",
                                                          "state": usage.VERIFIED_ZERO_STATE}))
            self.assertIsNone(video.prior_bound(task, Path(tmp)))
            (Path(tmp) / "t.json").write_text(json.dumps({"submission_fingerprint": "fp",
                                                          "state": usage.MANUAL_STATE}))
            with self.assertRaises(RuntimeError):
                video.prior_bound(task, Path(tmp))


class SummaryTest(unittest.TestCase):
    def test_summary_totals_by_model(self):
        calls = []

        def fake(method, url, *, body=None, headers=None, timeout=None):
            calls.append(url)
            body = {"data": [{"model": "gpt-6.1-terra", "channel": "flex", "calls": 70,
                              "tokens": {"input": 10, "output": 2}, "charge": "8.078122"},
                             {"model": "gpt-image-2", "channel": "flex", "calls": 20, "tokens": {},
                              "charge": "22.761530"}],
                    "total": {"calls": 90, "charge": "30.839652"}}
            return 200, body, json.dumps(body)

        with patch.dict(os.environ, ENV), patch.object(usage.hops, "_http", fake):
            out = usage.summarize(start=NOW - timedelta(hours=3), end=NOW, kind="llm")
        self.assertIn("/account/usage/summary", calls[0])
        self.assertIn("kind=llm", calls[0])
        self.assertIn("group_by=model", calls[0])
        self.assertEqual(out["by_model"][0]["model"], "gpt-image-2")
        self.assertEqual(out["total"], {"calls": 90, "charge": "30.839652", "usd": "0.3084"})


if __name__ == "__main__":
    unittest.main()


class PipelineWiringTest(unittest.TestCase):
    def test_reconcile_runs_only_on_a_real_paid_run(self):
        import nalu_pipeline as pipeline
        ctx = pipeline.Ctx.__new__(pipeline.Ctx)
        ctx.dry, ctx.paid_enabled, ctx.episode = True, True, "E11"
        with patch.dict(os.environ, ENV), patch.object(usage, "reconcile_episode") as rec:
            self.assertIsNone(ctx.reconcile_hopsapi_lost(label="t"))
            ctx.dry = False
            with patch.object(usage, "pending_lost", return_value=0):
                self.assertIsNone(ctx.reconcile_hopsapi_lost(label="t"))
            rec.assert_not_called()
            messages = []
            ctx.say = messages.append
            ctx.run_id = "r"
            with tempfile.TemporaryDirectory() as tmp, \
                    patch.object(usage, "pending_lost", return_value=2):
                ctx.p = type("P", (), {"logs": Path(tmp)})()
                rec.return_value = {"kinds": {"video": {"status": usage.VERIFIED_ZERO_STATE}}}
                self.assertIsNotNone(ctx.reconcile_hopsapi_lost(label="t"))
                self.assertIsNone(ctx.reconcile_hopsapi_lost(label="t"))  # at most once a minute
            rec.assert_called_once()
            self.assertIn("VERIFIED_ZERO_NO_REMOTE_TASK", messages[0])
