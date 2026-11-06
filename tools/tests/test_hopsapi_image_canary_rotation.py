"""HopsAPI gpt-image-2 batch canary rotation (device …1324 E01 S5, 2026-11-06).

The provider's content filter rejected ONE task (E01-S01-01) with the same zero-cost 424 "Provider
error" an upstream outage produces, and every retry probed that same task first, so 35 keyframes waited
on a cooldown forever.  Now a 424 canary rotates to a DIFFERENT pending task (fewest shared references):
a pass releases the batch and the rejected task becomes PROVIDER_REJECTED_TASK; only two different tasks
failing is an outage.  A fake transport answers the create (no network) and the status GETs; no key.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for _path in (str(ROOT), str(ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

try:
    from tools import hopsapi_image_client as images  # noqa: E402
    from tools import submit_giggle_image_manifest as submitter  # noqa: E402
    IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - CI base deps only
    images = submitter = None  # type: ignore[assignment]
    IMPORT_ERROR = exc


def utc(offset: float = 0.0) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset))


class FakeTransport:
    """Durable-submitter stand-in: one bound transaction per POST, recovered bindings are never re-POSTed,
    a terminal-failed binding is retired first (the real _submit_one_locked contract); status GETs answer
    the 424 for ``rejected`` task keys (or every key when ``rejected`` is None) and ``completed`` otherwise."""

    def __init__(self, store: Path, rejected: set[str] | None):
        self.store, self.rejected, self.posts = store, rejected, []

    def path(self, task):
        return self.store / f"{task['task_key']}__{'0' * 16}.json"

    def submit_one(self, task, receipt_dir, transaction_dir, provider=None):
        path = self.path(task)
        if path.is_file():
            row = json.loads(path.read_text(encoding="utf-8"))
            if images.retire_terminal_failed(path, row) is None:
                return {"task_key": task["task_key"], "task_id": row["task_id"], "status": "submitted",
                        "transaction": str(path), "recovered_from_transaction": True}
        self.posts.append(task["task_key"])
        task_id = f"tsk_{task['task_key']}_{len(self.posts)}"
        path.write_text(json.dumps({
            "provider": "hopsapi", "provider_model": images.MODEL, "task_key": task["task_key"],
            "state": "SUBMITTED_TASK_ID_BOUND", "task_id": task_id, "intent_recorded_at": utc(len(self.posts)),
        }), encoding="utf-8")
        return {"task_key": task["task_key"], "task_id": task_id, "status": "submitted",
                "transaction": str(path), "recovered_from_transaction": False}

    def query(self, task_id):
        key = task_id.split("_")[1]
        if self.rejected is None or key in self.rejected:
            return {"task_id": task_id, "remote_status": "failed", "provider_code": 424, "cost": 0.0,
                    "error": f"Provider error (request id: aitk-{task_id})"}
        return {"task_id": task_id, "remote_status": "completed", "cost": 1.16, "urls": ["https://x/y.png"]}


def task(key, *refs):
    return {"task_key": key, "beat_id": key, "reference_bindings": [{"sha256": ref} for ref in refs]}


TASKS = [task("E01-S01-01", "child", "quilt"), task("E01-S01-02", "child", "street"),
         task("E01-S02-01", "street", "stall"), task("E01-S02-02", "child")]


@unittest.skipIf(IMPORT_ERROR is not None, f"engine modules unavailable: {IMPORT_ERROR}")
class CanaryRotationTests(unittest.TestCase):

    def run_batch(self, store, fake, tasks=TASKS):
        deferred: list[dict] = []
        with patch.object(submitter, "submit_one", side_effect=fake.submit_one), \
                patch.object(submitter.image_client, "query_task", side_effect=fake.query), \
                patch.dict("os.environ", {"HOPSAPI_IMAGE_CANARY_WAIT_SECONDS": "0"}):
            results, failures = submitter.submit_all(list(tasks), store, store, 4, "hopsapi", deferred=deferred)
        rotation = next(row["canary_rotation"] for row in deferred if "canary_rotation" in row)
        not_posted = [row for row in deferred if "canary" not in row and "canary_rotation" not in row]
        return results, failures, not_posted, rotation

    def test_one_filtered_task_does_not_hold_the_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "E01"
            store.mkdir()
            fake = FakeTransport(store, {"E01-S01-01"})
            results, failures, not_posted, rotation = self.run_batch(store, fake)
            self.assertEqual(not_posted, [])
            self.assertEqual(rotation["outcome"], "RELEASED_AFTER_ROTATION")
            self.assertEqual(rotation["probes_tried"], 2)
            # the second probe shares no reference with the rejected task (no child headshot, no quilt)
            self.assertEqual([p["task_key"] for p in rotation["probes"]], ["E01-S01-01", "E01-S02-01"])
            self.assertEqual(sorted(row["task_key"] for row in results),
                             ["E01-S01-02", "E01-S02-01", "E01-S02-02"])
            self.assertEqual(len(failures), 1)
            rejected = failures[0]
            self.assertEqual((rejected["task_key"], rejected["status"], rejected["credit"]),
                             ("E01-S01-01", "PROVIDER_REJECTED_TASK", 0))
            self.assertEqual(rejected["provider_request_id"], "aitk-tsk_E01-S01-01_1")
            self.assertEqual(sorted(fake.posts), sorted(t["task_key"] for t in TASKS))  # each POSTed once
            # the rejection is settled (0 credits) on its durable transaction and is not an outage
            row = json.loads(fake.path(TASKS[0]).read_text(encoding="utf-8"))
            self.assertEqual((row["provider_failure_code"], row["provider_cost_credits"]), (424, 0.0))
            self.assertIsNone(images.recent_provider_outage(store.parent))
            summary, _ = submitter.hopsapi_credit_summary(results, failures, store)
            self.assertEqual(failures[0]["credit_status"], "NOT_CHARGED_PROVIDER_REJECTED_424")
            self.assertEqual(summary["ambiguous_response_count"], 0)

            # rerun: live bindings are recovered (never re-POSTed); only the rejected task POSTs again
            posts_before = list(fake.posts)
            results, failures, not_posted, rotation = self.run_batch(store, fake)
            self.assertEqual(fake.posts[len(posts_before):], ["E01-S01-01"])
            self.assertEqual(rotation["deprioritized_task_keys"], ["E01-S01-01"])
            self.assertEqual(not_posted, [])

    def test_a_task_rejected_in_an_earlier_run_is_not_the_next_canary(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "E01"
            store.mkdir()
            for attempt in range(4):  # the field: the same task failed every retry
                (store / f"E01-S01-01__{'0' * 16}.terminal-tsk_{attempt}.json").write_text(json.dumps({
                    "provider": "hopsapi", "provider_model": images.MODEL, "task_key": "E01-S01-01",
                    "state": "SUBMITTED_TASK_ID_BOUND", "task_id": f"tsk_{attempt}",
                    "intent_recorded_at": utc(-600 + attempt), "provider_remote_status": "failed",
                    "remote_terminal_state": "failed", "remote_terminal_observed_at": utc(-590 + attempt),
                    "provider_cost_credits": 0.0, "provider_failure_code": 424,
                    "provider_failure": "Provider error (request id: aitk-x)"}), encoding="utf-8")
            # one task failing four times is that task, not an outage: no store-wide cooldown
            self.assertIsNone(images.recent_provider_outage(store.parent))
            fake = FakeTransport(store, {"E01-S01-01"})
            results, failures, not_posted, rotation = self.run_batch(store, fake)
            self.assertEqual(rotation["probes"][0]["task_key"], "E01-S02-01")
            self.assertEqual(rotation["outcome"], "RELEASED")
            self.assertEqual(not_posted, [])
            self.assertEqual(len(fake.posts), 4)

    def test_every_task_424_is_still_an_outage_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "E01"
            store.mkdir()
            fake = FakeTransport(store, None)
            results, failures, not_posted, rotation = self.run_batch(store, fake)
            self.assertEqual(rotation["outcome"], "PROVIDER_OUTAGE")
            self.assertEqual(len(fake.posts), 2)
            self.assertEqual(len(set(fake.posts)), 2)  # two DIFFERENT tasks probed
            self.assertEqual(failures, [])
            self.assertEqual([row["status"] for row in not_posted], ["NOT_POSTED_PROVIDER_OUTAGE"] * 2)
            self.assertTrue(all(row["credit"] == 0 for row in not_posted))
            self.assertEqual(len(results), 2)  # bound probes stay bound; the harvest settles them

    def test_store_outage_needs_two_different_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "E01"
            store.mkdir()
            for index, key in enumerate(["A", "A", "B"]):
                (store / f"{key}__{'0' * 16}.terminal-tsk_{index}.json").write_text(json.dumps({
                    "provider": "hopsapi", "provider_model": images.MODEL, "task_key": key,
                    "task_id": f"tsk_{index}", "intent_recorded_at": utc(-60 + index),
                    "provider_remote_status": "failed", "remote_terminal_observed_at": utc(-50 + index),
                    "provider_cost_credits": 0.0, "provider_failure_code": 424}), encoding="utf-8")
            outage = images.recent_provider_outage(store.parent)
            self.assertEqual(outage["blocker"], "HOPSAPI_IMAGE_PROVIDER_OUTAGE")
            self.assertEqual(outage["distinct_failed_tasks"], ["E01/A", "E01/B"])


if __name__ == "__main__":
    unittest.main()
