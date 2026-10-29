"""Device-side store: contracts, concurrency (T01), crash consistency (T02), conflicts (T06 local).

Every test runs on a temp directory with synthetic, work-agnostic data; nothing here
reads or writes a production runtime root.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools import knowledge_event_log as legacy
from tools.collective_learning import contracts as c
from tools.collective_learning import device_store as ds

SHA = "a" * 64


def _evidence() -> dict:
    return {"gate": "EYELINE_CHECK", "timecodes": [
        {"video_sha256": SHA, "timeline": "FINAL_CUT", "start_ms": 1200, "end_ms": 2400}]}


def _store(tmp: Path, device_id: str | None = None) -> ds.DeviceStore:
    return ds.DeviceStore(tmp / "store.sqlite", tenant_id="tenant-1", line_id="line-A", device_id=device_id)


def _worker_record(args: tuple[str, int, int]) -> int:
    path, worker, n = args
    store = ds.DeviceStore(Path(path), tenant_id="tenant-1", line_id="line-A")
    for i in range(n):
        store.record_observation(run_id=f"run-{worker}", episode_id="EP01", stage="S6",
                                 event_kind="RUN_ANOMALY", symptom=f"worker {worker} item {i}",
                                 evidence={"i": i, "w": worker}, detected_by="test", visibility="LINE")
    return n


def _worker_legacy(args: tuple[str, int, int]) -> int:
    path, worker, n = args
    written = 0
    for i in range(n):
        try:
            legacy.record_event(Path(path), episode="EP01", line="line-A", stage="S6",
                                symptom=f"worker {worker} item {i}", evidence={"i": i, "w": worker},
                                detected_by="test")
            written += 1
        except (OSError, ValueError):
            # Two writers racing on the same ``.tmp`` rename, or one reading the
            # other's torn write: both are the defect being demonstrated.
            pass
    return written


class ContractTest(unittest.TestCase):
    def test_fact_cannot_carry_root_cause_or_authority(self) -> None:
        base = dict(tenant_id="t", line_id="l", device_id="d", run_id="r", episode_id="e", stage="S6",
                    event_kind="RUN_ANOMALY", symptom="x", evidence={"k": 1}, detected_by="t",
                    producer_sequence=1)
        event = c.make_observation(**base)
        for key in ("root_cause", "publication_authorized", "paid_retry_authorized", "budget"):
            with self.assertRaises(c.ContractError) as ctx:
                c.validate_observation({**event, key: True})
            self.assertIn(f"FORBIDDEN_KEY_ON_FACT:{key}", ctx.exception.codes)

    def test_rate_kinds_need_opportunity_denominator(self) -> None:
        base = dict(tenant_id="t", line_id="l", device_id="d", run_id="r", episode_id="e", stage="S6",
                    event_kind="FAILURE_OBSERVATION", symptom="x", evidence={"k": 1}, detected_by="t",
                    producer_sequence=1)
        with self.assertRaises(c.ContractError) as ctx:
            c.make_observation(**base)
        self.assertIn("OPPORTUNITY_REQUIRED_FOR_RATE_KIND", ctx.exception.codes)
        ok = c.make_observation(**base, opportunity={"applicable_units": 5, "observed_units": 2})
        self.assertEqual(ok["opportunity"]["applicable_units"], 5)

    def test_timecode_must_name_video_version_and_timeline(self) -> None:
        base = dict(tenant_id="t", line_id="l", device_id="d", run_id="r", episode_id="e", stage="S7",
                    event_kind="RUN_ANOMALY", symptom="x", detected_by="t", producer_sequence=1)
        with self.assertRaises(c.ContractError) as ctx:
            c.make_observation(**base, evidence={"timecodes": [{"start_ms": 0, "end_ms": 10}]})
        self.assertIn("TIMECODE_VIDEO_VERSION_REQUIRED:0", ctx.exception.codes)
        self.assertIn("TIMECODE_TIMELINE_INVALID:0:None", ctx.exception.codes)
        with self.assertRaises(c.ContractError):
            c.make_observation(**base, evidence={"timecodes": [
                {"video_sha256": SHA, "timeline": "FINAL_CUT", "start_ms": 5, "end_ms": 2}]})

    def test_unknown_versions_stay_unknown_not_invented(self) -> None:
        event = c.make_observation(tenant_id="t", line_id="l", device_id="d", run_id="r", episode_id="e",
                                   stage="S6", event_kind="RUN_ANOMALY", symptom="x", evidence={"k": 1},
                                   detected_by="t", producer_sequence=1, provider_model_version="")
        self.assertEqual(event["provider_model_version"], "UNKNOWN")
        self.assertEqual(event["engine_version"], "UNKNOWN")

    def test_shareable_event_rejects_sensitive_content(self) -> None:
        for bad in ({"p": "/Us" + "ers/someone/x.png"}, {"u": "https://h/x?X-Amz-Signature=abc"},
                    {"k": "Bearer abcdefghijklmnop"}):
            with self.assertRaises(c.ContractError) as ctx:
                c.make_observation(tenant_id="t", line_id="l", device_id="d", run_id="r", episode_id="e",
                                   stage="S6", event_kind="RUN_ANOMALY", symptom="x", evidence=bad,
                                   detected_by="t", producer_sequence=1, visibility="LINE")
            self.assertTrue(any(code.startswith("SENSITIVE_CONTENT") for code in ctx.exception.codes))
        # The same content is allowed to stay on the device.
        c.make_observation(tenant_id="t", line_id="l", device_id="d", run_id="r", episode_id="e",
                           stage="S6", event_kind="RUN_ANOMALY", symptom="x",
                           evidence={"p": "/Us" + "ers/someone/x.png"}, detected_by="t",
                           producer_sequence=1, visibility="PRIVATE_LOCAL")

    def test_candidate_cannot_self_release_or_grant_authority(self) -> None:
        cand = {"candidate_id": "cand-1", "revision": 1, "category": "DIRECTING_HEURISTIC",
                "scope": {"models": ["H3"], "stages": ["S6"]}, "trigger": "t", "recommendation": "r",
                "verification": "v", "cost_class": "FREE_LOCAL", "evidence_level": "NEEDS_EVIDENCE",
                "exceptions": ["monologue"]}
        c.validate_candidate(cand)
        with self.assertRaises(c.ContractError) as ctx:
            c.validate_candidate({**cand, "status": "RELEASED"})
        self.assertIn("CANDIDATE_CANNOT_SELF_DECLARE_STATE:RELEASED", ctx.exception.codes)
        with self.assertRaises(c.ContractError) as ctx:
            c.validate_candidate({**cand, "paid_retry_authorized": True})
        self.assertIn("CANDIDATE_CANNOT_GRANT_AUTHORITY:paid_retry_authorized", ctx.exception.codes)
        with self.assertRaises(c.ContractError) as ctx:
            c.validate_candidate({**cand, "scope": {"stages": ["S6"]}})
        self.assertIn("SCOPE_MODELS_REQUIRED", ctx.exception.codes)
        with self.assertRaises(c.ContractError) as ctx:
            c.validate_candidate({**cand, "python": "import os"})
        self.assertIn("KNOWLEDGE_CANNOT_CARRY_EXECUTABLE:python", ctx.exception.codes)

    def test_adoption_states_need_matching_evidence(self) -> None:
        base = {"receipt_id": c.new_uuid(), "tenant_id": "t", "line_id": "l", "device_id": "d",
                "run_id": "r", "rule_id": "R1", "rule_version": 1, "bundle_digest": SHA, "stage": "S6",
                "entrypoint": "compile"}
        c.validate_adoption({**base, "state": "SELECTED"})
        with self.assertRaises(c.ContractError) as ctx:
            c.validate_adoption({**base, "state": "NOT_APPLICABLE"})
        self.assertIn("ADOPTION_REASON_REQUIRED:NOT_APPLICABLE", ctx.exception.codes)
        with self.assertRaises(c.ContractError) as ctx:
            c.validate_adoption({**base, "state": "APPLIED"})
        self.assertIn("APPLIED_NEEDS_COMPILED_OUTPUT_DIGEST", ctx.exception.codes)
        applied = {**base, "state": "APPLIED", "source_contract_digest": SHA, "compiled_output_digest": SHA,
                   "change_evidence": {"fragment": "x"}, "evidence_scope": "COMPILED_REQUEST"}
        c.validate_adoption(applied)
        with self.assertRaises(c.ContractError) as ctx:
            c.validate_adoption({**applied, "state": "VERIFIED"})
        self.assertIn("VERIFIED_NEEDS_PASSING_NAMED_ASSERTION", ctx.exception.codes)
        with self.assertRaises(c.ContractError) as ctx:
            c.validate_adoption({**applied, "state": "OUTCOME_OBSERVED",
                                 "verification": {"test_name": "t", "result": "PASS", "assertion": "a"},
                                 "outcome": {"kind": "DEFECT_FIXED", "media_sha256": SHA}})
        self.assertIn("OUTCOME_KIND_INVALID", ctx.exception.codes)
        self.assertIn("OUTCOME_NEEDS_MEDIA_OR_FILM_SCOPE", ctx.exception.codes)

    def test_scope_unknown_capability_never_matches(self) -> None:
        scope = {"models": ["H3"], "stages": ["S6"], "scene_types": ["DIALOGUE"]}
        self.assertTrue(c.scope_matches(scope, {"model": "H3", "stage": "S6", "scene_type": "DIALOGUE"})[0])
        ok, why = c.scope_matches(scope, {"model": "H3", "stage": "S6"})
        self.assertFalse(ok)
        self.assertEqual(why, ["CAPABILITY_UNKNOWN:scene_type"])
        ok, why = c.scope_matches(scope, {"model": "SD2", "stage": "S6", "scene_type": "DIALOGUE"})
        self.assertEqual(why, ["OUT_OF_SCOPE:model=SD2"])


class StoreBasicsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def test_device_identity_is_stable_and_line_bound(self) -> None:
        a = _store(self.tmp)
        b = _store(self.tmp)
        self.assertEqual(a.device_id, b.device_id)
        self.assertTrue(a.device_id.startswith("dev-"))
        with self.assertRaises(c.ContractError):
            ds.DeviceStore(self.tmp / "store.sqlite", tenant_id="tenant-1", line_id="line-B")
        with self.assertRaises(c.ContractError):
            _store(self.tmp, device_id="other-device")

    def test_fact_and_outbox_written_together_private_stays_local(self) -> None:
        store = _store(self.tmp)
        shared = store.record_observation(run_id="r", episode_id="EP01", stage="S6", event_kind="RUN_ANOMALY",
                                          symptom="s", evidence=_evidence(), detected_by="t", visibility="LINE")
        store.record_observation(run_id="r", episode_id="EP01", stage="S6", event_kind="RUN_ANOMALY",
                                 symptom="p", evidence=_evidence(), detected_by="t", visibility="PRIVATE_LOCAL")
        self.assertEqual(store.count("events"), 2)
        self.assertEqual(store.outbox_status()["counts"]["PENDING"], 1)
        self.assertEqual(store.claim_due(10)[0]["item_id"], shared["event_id"])
        self.assertTrue(c.is_uuid(shared["event_id"]))

    def test_same_id_same_content_idempotent_different_content_conflict(self) -> None:
        store = _store(self.tmp)
        event = store.record_observation(run_id="r", episode_id="EP01", stage="S6", event_kind="RUN_ANOMALY",
                                         symptom="s", evidence=_evidence(), detected_by="t", visibility="LINE")
        self.assertEqual(store.put_observation(dict(event))["status"], "DUPLICATE")
        with self.assertRaises(ds.EventConflict):
            store.put_observation({**event, "symptom": "rewritten"})
        self.assertEqual(store.count("events"), 1)
        self.assertEqual(store.events()[0]["symptom"], "s")
        self.assertEqual(store.conflicts()[0]["event_id"], event["event_id"])
        self.assertEqual(store.outbox_status()["counts"]["PENDING"], 1)

    def test_reviews_are_immutable_revisions_not_overwrites(self) -> None:
        store = _store(self.tmp)
        event = store.record_observation(run_id="r", episode_id="EP01", stage="S6", event_kind="RUN_ANOMALY",
                                         symptom="s", evidence=_evidence(), detected_by="t", visibility="LINE")
        with self.assertRaises(c.ContractError) as ctx:
            store.record_review(event_id=event["event_id"], reviewer_id="rev", status="ATTRIBUTED",
                                root_cause_hypothesis="guess", basis="MODEL_HYPOTHESIS", confidence="HIGH",
                                supporting_evidence=["x"])
        self.assertIn("MODEL_HYPOTHESIS_CANNOT_BE_HIGH_CONFIDENCE", ctx.exception.codes)
        r1 = store.record_review(event_id=event["event_id"], reviewer_id="rev", status="ATTRIBUTED",
                                 root_cause_hypothesis="eyeline not propagated", basis="REPRODUCED",
                                 confidence="MEDIUM", supporting_evidence=["compile diff"])
        r2 = store.record_review(event_id=event["event_id"], reviewer_id="rev2", status="INCONCLUSIVE",
                                 reason="counter evidence found")
        chain = store.attribution_chain(event["event_id"])
        self.assertEqual([r["review_version"] for r in chain], [1, 2])
        self.assertEqual(chain[0]["review_id"], r1["review_id"])
        self.assertEqual(chain[1]["review_id"], r2["review_id"])
        self.assertNotIn("root_cause", store.events()[0])  # the fact itself is untouched
        self.assertEqual(store.outbox_status()["counts"]["PENDING"], 3)
        with self.assertRaises(c.ContractError):
            store.record_review(event_id=c.new_uuid(), reviewer_id="rev", status="INCONCLUSIVE", reason="x")

    def test_legacy_jsonl_export_is_a_derived_view(self) -> None:
        store = _store(self.tmp)
        event = store.record_observation(run_id="r", episode_id="EP01", stage="S6", event_kind="RUN_ANOMALY",
                                         symptom="s", evidence=_evidence(), detected_by="t")
        store.record_review(event_id=event["event_id"], reviewer_id="rev", status="INCONCLUSIVE", reason="why")
        out = self.tmp / "KNOWLEDGE_EVENTS.jsonl"
        self.assertEqual(store.export_jsonl(out), 1)
        rows = legacy.events(self.tmp, relpath=out.name)
        self.assertEqual(rows[0]["attribution"]["status"], legacy.STATUS_INCONCLUSIVE)
        self.assertEqual(legacy.unattributed(self.tmp, relpath=out.name), [])

    def test_outbox_backoff_and_quarantine(self) -> None:
        store = _store(self.tmp)
        store.record_observation(run_id="r", episode_id="EP01", stage="S6", event_kind="RUN_ANOMALY",
                                 symptom="s", evidence=_evidence(), detected_by="t", visibility="LINE")
        item = store.claim_due(10, now=0)[0]
        store.mark_retry([item["outbox_id"]], "timeout", now=1000.0)
        self.assertEqual(store.claim_due(10, now=1000.0), [])
        self.assertEqual(len(store.claim_due(10, now=1000.0 + 600)), 1)
        store.quarantine(item["outbox_id"], "PAYLOAD_INVALID:x")
        status = store.outbox_status()
        self.assertEqual(status["counts"]["QUARANTINED"], 1)
        self.assertEqual(status["quarantined"][0]["reason"], "PAYLOAD_INVALID:x")
        self.assertEqual(store.claim_due(10, now=1e9), [])


class CrashConsistencyTest(unittest.TestCase):
    """T02: a crash between the fact insert and the outbox insert leaves neither."""

    def test_crash_between_fact_and_outbox_rolls_back_both(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = _store(tmp)
        with self.assertRaises(RuntimeError):
            store.record_observation(run_id="r", episode_id="EP01", stage="S6", event_kind="RUN_ANOMALY",
                                     symptom="s", evidence=_evidence(), detected_by="t", visibility="LINE",
                                     _crash_after_event_insert=True)
        self.assertEqual(store.count("events"), 0)
        self.assertEqual(store.count("outbox"), 0)
        # The sequence counter is also rolled back, so the next fact gets sequence 1.
        event = store.record_observation(run_id="r", episode_id="EP01", stage="S6", event_kind="RUN_ANOMALY",
                                         symptom="s", evidence=_evidence(), detected_by="t", visibility="LINE")
        self.assertEqual(event["producer_sequence"], 1)
        self.assertEqual(store.count("outbox"), 1)

    def test_store_reopens_after_process_exit_with_pending_items(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        path = str(tmp / "store.sqlite")
        ctx = mp.get_context("spawn")
        with ctx.Pool(1) as pool:
            pool.map(_worker_record, [(path, 1, 5)])
        reopened = ds.DeviceStore(Path(path), tenant_id="tenant-1", line_id="line-A")
        self.assertEqual(reopened.count("events"), 5)
        self.assertEqual(reopened.outbox_status()["counts"]["PENDING"], 5)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")


class MultiProcessTest(unittest.TestCase):
    """T01: concurrent writers from separate processes lose nothing and overwrite nothing."""

    WORKERS = 6
    PER_WORKER = 40

    def test_sqlite_store_keeps_every_row_from_every_process(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        path = str(tmp / "store.sqlite")
        ds.DeviceStore(Path(path), tenant_id="tenant-1", line_id="line-A")  # mint identity once
        ctx = mp.get_context("spawn")
        with ctx.Pool(self.WORKERS) as pool:
            pool.map(_worker_record, [(path, w, self.PER_WORKER) for w in range(self.WORKERS)])
        store = ds.DeviceStore(Path(path), tenant_id="tenant-1", line_id="line-A")
        events = store.events()
        self.assertEqual(len(events), self.WORKERS * self.PER_WORKER)
        self.assertEqual(len({e["event_id"] for e in events}), len(events))
        self.assertEqual(sorted(e["producer_sequence"] for e in events), list(range(1, len(events) + 1)))
        self.assertEqual(len({e["device_id"] for e in events}), 1)
        self.assertEqual(store.outbox_status()["counts"]["PENDING"], len(events))
        self.assertEqual(store.conflicts(), [])

    def test_legacy_jsonl_log_loses_rows_under_the_same_load(self) -> None:
        """Documents WHY the SQLite store exists: the read-all/rewrite-all JSONL log races.

        This is a demonstration of the baseline defect the requirement names (section 3,
        "cannot let hundreds of devices share this file"), not a flake: with no lock, two
        processes that both read N rows and both write N+1 rows lose one of them.  The
        assertion is on the weak side (<=) so a lucky interleaving does not fail CI; the
        SQLite assertion above is the strict one.
        """
        tmp = Path(tempfile.mkdtemp())
        ctx = mp.get_context("spawn")
        with ctx.Pool(self.WORKERS) as pool:
            written = sum(pool.map(_worker_legacy, [(str(tmp), w, self.PER_WORKER) for w in range(self.WORKERS)]))
        try:
            rows = legacy.events(tmp)
        except ValueError:
            rows = []  # a torn write corrupted the file: also a loss
        self.assertLessEqual(len(rows), self.WORKERS * self.PER_WORKER)
        lost = self.WORKERS * self.PER_WORKER - len(rows)
        failed_writes = self.WORKERS * self.PER_WORKER - written
        os.environ["COLLECTIVE_LEGACY_LOG_ROWS_LOST"] = f"{lost} lost, {failed_writes} writes raised"


if __name__ == "__main__":
    unittest.main()
