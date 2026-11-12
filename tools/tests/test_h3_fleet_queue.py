"""HopsAPI MiniMax-H3 fleet concurrency queue (line owner 2026-11-12: 5 concurrent H3 tasks per account, fleet-wide).

A fake nalu-fleet service (real HTTP, in-process) answers /v1/h3/acquire|renew|release; HopsAPI is the scripted
FakeHops of test_hopsapi_video_transport.  Covered: lease before the create POST and released at completed /
failed, waiting while not granted, the wait cap, the local cap-1 fallback when the fleet is off, no self-deadlock
under the submitter's per-transaction flock (a waiting worker settles its own finished task), and Giggle / image
paths never touching the queue.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from test_hopsapi_video_transport import MP4, FakeHops, HopsapiTestBase, poller, video  # noqa: E402

q = video.h3_fleet_queue
TASK_ID = "tsk_mvtw42uw_aead3bfa7fa718aa3ab01c87"


class FakeFleet:
    """In-process nalu-fleet H3 queue: capacity, FIFO, one device token."""

    def __init__(self, capacity: int = 5, timeline: list | None = None):
        self.capacity = capacity
        self.leases: dict[str, dict] = {}
        self.waiters: list[str] = []
        self.calls: list[tuple[str, dict]] = []
        self.timeline = timeline if timeline is not None else []
        self.deny_first = 0
        self.lock = threading.Lock()
        fleet = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if self.headers.get("Authorization") != "Bearer devtok":
                    return self.reply(401, {"error": "UNAUTHORIZED"})
                with fleet.lock:
                    out = fleet.handle(self.path, body)
                self.reply(200 if out is not None else 404, out or {"error": "NOT_FOUND"})

            def reply(self, code, payload):
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def active(self) -> list[dict]:
        return [row for row in self.leases.values() if row["released"] is None]

    def handle(self, path: str, body: dict) -> dict | None:
        self.calls.append((path, body))
        self.timeline.append(("fleet", path))
        if path == "/v1/h3/acquire":
            key = body["task_key"]
            for lid, row in self.leases.items():
                if row["task_key"] == key and row["released"] is None:
                    return {"granted": True, "lease_id": lid, "ttl_s": 900}
            if key not in self.waiters:
                self.waiters.append(key)
            pos = self.waiters.index(key)
            if self.deny_first > 0:
                self.deny_first -= 1
                return {"granted": False, "position": pos + 1, "active": len(self.active()),
                        "capacity": self.capacity, "retry_after_s": 15}
            if pos < self.capacity - len(self.active()):
                self.waiters.remove(key)
                lid = f"h3_{len(self.leases) + 1}"
                self.leases[lid] = {"task_key": key, "released": None, "task_id": None}
                return {"granted": True, "lease_id": lid, "ttl_s": 900}
            return {"granted": False, "position": pos + 1, "active": len(self.active()),
                    "capacity": self.capacity, "retry_after_s": 15}
        if path == "/v1/h3/renew":
            row = self.leases[body["lease_id"]]
            row["task_id"] = body.get("provider_task_id") or row["task_id"]
            return {"ok": row["released"] is None}
        if path == "/v1/h3/release":
            self.leases[body["lease_id"]]["released"] = body["reason"]
            return {"ok": True}
        return None

    def close(self):
        self.srv.shutdown()


class TimelineHops(FakeHops):
    def __init__(self, timeline: list, **kw):
        super().__init__(**kw)
        self.timeline = timeline

    def __call__(self, method, url, **kw):
        self.timeline.append(("hops", url.rsplit("/", 2)[-1] if "/router/tasks/" not in url else "query"))
        return super().__call__(method, url, **kw)


class QueueTestBase(HopsapiTestBase):
    def setUp(self):
        super().setUp()
        self.runtime = self.root / "runtime"
        (self.runtime / "credentials").mkdir(parents=True)
        (self.runtime / "credentials" / "fleet_token").write_text("devtok\n")
        self.timeline: list = []
        self.fleet = FakeFleet(timeline=self.timeline)
        self.addCleanup(self.fleet.close)
        env = patch.dict(os.environ, {"NALU_RUNTIME_ROOT": str(self.runtime), "NALU_FLEET_URL": self.fleet.url,
                                      "NALU_H3_QUEUE": "", "NALU_H3_QUEUE_MAX_WAIT_S": "14400"})
        env.start()
        self.addCleanup(env.stop)
        self.sleeps: list[float] = []
        for name, value in (("_sleep", self.sleeps.append), ("REAP_MIN_INTERVAL_S", 0)):
            p = patch.object(q, name, value)
            p.start()
            self.addCleanup(p.stop)

    def poll_once(self, tx_path, query):
        report = self.root / "submit.json"
        report.write_text(json.dumps({"tasks": [{"task_key": "E10-VU-001", "task_id": TASK_ID,
                                                 "transaction": str(tx_path)}]}), encoding="utf-8")
        fake = FakeHops(queries=[query])
        with patch.object(poller.hopsapi, "_http", side_effect=fake), \
             patch.object(poller.hopsapi, "_download_bytes", return_value=MP4), \
             patch.object(poller, "query_task", side_effect=AssertionError("Giggle query")), \
             patch.dict(os.environ, {"GIGGLE_API_KEY": ""}):
            return poller.poll(report, self.root / "video", self.root / "status.json", True)


class LeaseLifecycleTests(QueueTestBase):
    def test_lease_acquired_before_post_renewed_while_rendering_released_on_completed(self):
        task = self.task()
        self.submit(task, TimelineHops(self.timeline))
        steps = [s for s in self.timeline if s in (("fleet", "/v1/h3/acquire"), ("hops", "create"))]
        self.assertEqual(steps, [("fleet", "/v1/h3/acquire"), ("hops", "create")])
        first_upload = next(i for i, s in enumerate(self.timeline) if s[0] == "hops")
        self.assertLess(self.timeline.index(("fleet", "/v1/h3/acquire")), first_upload)  # before the uploads too
        tx_path = video.transaction_path(self.transactions, task)
        tx = json.loads(tx_path.read_text())
        self.assertEqual((tx["h3_lease"]["lease_id"], tx["h3_lease"]["mode"]), ("h3_1", "fleet"))
        self.assertEqual(self.fleet.leases["h3_1"]["task_id"], TASK_ID)  # bound: renewed with the task id
        self.assertIsNone(self.fleet.leases["h3_1"]["released"])
        self.assertNotIn("devtok", tx_path.read_text())

        n = len(self.fleet.calls)
        self.poll_once(tx_path, (200, {"task_id": TASK_ID, "status": 1, "results": []}))
        self.assertEqual([c[0] for c in self.fleet.calls[n:]], ["/v1/h3/renew"])
        self.poll_once(tx_path, (200, {"task_id": TASK_ID, "status": 2, "cost": 6.2,
                                       "results": [{"urls": ["https://static.giggle.pro/x.mp4"]}]}))
        self.assertEqual(self.fleet.leases["h3_1"]["released"], "completed")
        tx = json.loads(tx_path.read_text())
        self.assertEqual(tx["h3_lease"]["release_reason"], "completed")
        self.assertEqual(tx["provider_cost_credits"], 6.2)
        released = len([c for c in self.fleet.calls if c[0] == "/v1/h3/release"])
        self.poll_once(tx_path, (200, {"task_id": TASK_ID, "status": 2, "cost": 6.2,
                                       "results": [{"urls": ["https://static.giggle.pro/x.mp4"]}]}))
        self.assertEqual(len([c for c in self.fleet.calls if c[0] == "/v1/h3/release"]), released)  # once

    def test_released_on_failed_and_zero_cost_retry_still_works(self):
        task = self.task()
        self.submit(task, FakeHops())
        tx_path = video.transaction_path(self.transactions, task)
        self.poll_once(tx_path, (200, {"task_id": TASK_ID, "status": 3, "error": "Provider error"}))
        self.assertEqual(self.fleet.leases["h3_1"]["released"], "failed")
        tx = json.loads(tx_path.read_text())
        self.assertEqual((tx["provider_cost_credits"], tx["remote_terminal_state"]), (0.0, "failed"))
        # the zero-cost terminal take is released to a new attempt, which queues for a fresh lease
        retry = FakeHops(create=lambda: (200, {"code": 200, "task_id": "tsk_second"}))
        result = self.submit(self.task(), retry)
        self.assertEqual(result["task_id"], "tsk_second")
        self.assertEqual(json.loads(tx_path.read_text())["h3_lease"]["lease_id"], "h3_2")

    def test_declined_create_releases_submit_failed_and_lost_response_keeps_lease(self):
        hops = video.hopsapi
        task = self.task()
        declined = FakeHops(create=lambda: hops.HopsapiHTTPError(400, {"code": 400, "message": "bad"}, "bad"))
        with self.assertRaisesRegex(RuntimeError, "not charged"):
            self.submit(task, declined)
        self.assertEqual(self.fleet.leases["h3_1"]["released"], "submit_failed")
        self.assertEqual(json.loads(video.transaction_path(self.transactions, task).read_text())
                         ["h3_lease"]["release_reason"], "submit_failed")
        lost = FakeHops(create=lambda: TimeoutError("read timed out"))
        with self.assertRaises(Exception):
            self.submit(self.task(), lost)
        self.assertIsNone(self.fleet.leases["h3_2"]["released"])  # a task may be rendering: expires by TTL
        tx = json.loads(video.transaction_path(self.transactions, task).read_text())
        self.assertTrue(tx["h3_lease"]["kept_until_expiry"])

    def test_pre_intent_failure_releases_the_slot(self):
        task = self.task()
        with patch.object(video, "_hopsapi_reference_uploads", side_effect=RuntimeError("upload broke")):
            with self.assertRaisesRegex(RuntimeError, "upload broke"):
                self.submit(task, FakeHops())
        self.assertEqual(self.fleet.leases["h3_1"]["released"], "submit_failed")
        self.assertFalse(video.transaction_path(self.transactions, task).exists())


class WaitingTests(QueueTestBase):
    def test_waits_while_not_granted_then_proceeds(self):
        self.fleet.deny_first = 3
        hops = TimelineHops(self.timeline)
        with patch.object(q, "_log") as log:
            self.submit(self.task(), hops)
        acquires = [c for c in self.fleet.calls if c[0] == "/v1/h3/acquire"]
        self.assertEqual(len(acquires), 4)
        self.assertEqual(self.sleeps, [15.0, 15.0, 15.0])
        self.assertEqual(len(hops.posts("/router/task/create")), 1)
        position_lines = [c for c in log.call_args_list if "queue position" in c.args[0]]
        self.assertEqual(len(position_lines), 1)  # logged on change only

    def test_wait_cap_gives_up_before_intent_and_post(self):
        self.fleet.capacity = 0
        clock = iter(range(0, 10_000, 15))
        task = self.task()
        hops = FakeHops()
        with patch.dict(os.environ, {"NALU_H3_QUEUE_MAX_WAIT_S": "60"}), \
             patch.object(q, "_clock", lambda: next(clock)):
            with self.assertRaisesRegex(q.H3QueueTimeout, "H3_FLEET_QUEUE_WAIT_TIMEOUT"):
                self.submit(task, hops)
        self.assertEqual(hops.calls, [])  # no upload, no create
        self.assertFalse(video.transaction_path(self.transactions, task).exists())  # pre-intent: not charged


class FallbackTests(QueueTestBase):
    def test_fleet_off_caps_this_device_at_one_h3_task(self):
        with patch.dict(os.environ, {"NALU_FLEET_URL": "off"}):
            first = self.task(key="E10-VU-001")
            self.submit(first, FakeHops())
            lease = json.loads(video.transaction_path(self.transactions, first).read_text())["h3_lease"]
            self.assertEqual((lease["mode"], lease["fallback_reason"]), ("local", "FLEET_OFF"))
            # a second H3 task waits for the single local slot
            clock = iter(range(0, 10_000, 15))
            with patch.dict(os.environ, {"NALU_H3_QUEUE_MAX_WAIT_S": "45"}), patch.object(q, "_clock", lambda: next(clock)):
                with self.assertRaises(q.H3QueueTimeout):
                    q.acquire("E10-VU-002", "E10", reap=lambda **_k: 0)
            # the first one settles -> its local slot is freed -> the second gets it
            tx_path = video.transaction_path(self.transactions, first)
            self.poll_once(tx_path, (200, {"task_id": TASK_ID, "status": 3, "error": "Provider error"}))
            second = q.acquire("E10-VU-002", "E10", reap=lambda **_k: 0)
            self.assertEqual(second["mode"], "local")
        self.assertEqual(self.fleet.calls, [])
        events = (self.runtime / "runtime" / "h3_queue" / "events.jsonl").read_text()
        self.assertIn('"fallback"', events)

    def test_unreachable_fleet_and_missing_token_fall_back(self):
        with patch.dict(os.environ, {"NALU_FLEET_URL": "http://127.0.0.1:9"}):
            self.assertEqual(q.acquire("K1", "E10", reap=lambda **_k: 0)["fallback_reason"],
                             "FLEET_UNREACHABLE:URLError")
        (self.runtime / "credentials" / "fleet_token").write_text("wrong\n")
        lease = q.acquire("K1", "E10", reap=lambda **_k: 0)  # same task key: idempotent local slot
        self.assertEqual((lease["mode"], lease["fallback_reason"]), ("local", "FLEET_TOKEN_REJECTED"))

    def test_queue_inactive_without_a_device_runtime(self):
        with patch.dict(os.environ, {"NALU_RUNTIME_ROOT": ""}):
            self.assertIsNone(q.acquire("K1", "E10"))
        with patch.dict(os.environ, {"NALU_H3_QUEUE": "off"}):
            self.assertIsNone(q.acquire("K1", "E10"))


class NoDeadlockTests(QueueTestBase):
    def test_waiting_worker_settles_its_own_finished_task_under_the_flock(self):
        """Capacity 1, two tasks of one wave in two submit workers (each holding its own transaction flock).
        The second waits; its reaper sees the first task completed and settles it with a NON-blocking lock,
        which releases the lease; the second is granted.  Without the reaper this would wait for the poll step,
        which only runs after the submitter exits."""
        self.fleet.capacity = 1
        a, b = self.task(key="E10-VU-001"), self.task(key="E10-VU-002")
        creates = iter(["tsk_a", "tsk_b"])
        hops = FakeHops(create=lambda: (200, {"code": 200, "task_id": next(creates)}),
                        queries=[(200, {"task_id": "tsk_a", "status": 2, "cost": 5.0, "results": []})] * 50)
        results, errors = {}, []

        def worker(task):
            try:
                results[task["task_key"]] = video.submit_one(task, self.receipts, self.transactions)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        with patch.object(video.hopsapi, "_http", side_effect=hops), \
             patch.object(video.hopsapi, "_download_bytes", return_value=b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 64), \
             patch.object(video, "prompt_scope_gate_active", return_value=False), \
             patch("tools.episode_prompt_batch_gate.require_generation_batch"):
            t1 = threading.Thread(target=worker, args=(a,))
            t1.start()
            t1.join(20)
            t2 = threading.Thread(target=worker, args=(b,))
            t2.start()
            t2.join(20)
        self.assertFalse(t2.is_alive(), "second worker deadlocked")
        self.assertEqual(errors, [])
        self.assertEqual({k: v["task_id"] for k, v in results.items()}, {"E10-VU-001": "tsk_a", "E10-VU-002": "tsk_b"})
        self.assertEqual(self.fleet.leases["h3_1"]["released"], "completed")
        self.assertEqual(json.loads(video.transaction_path(self.transactions, a).read_text())["provider_cost_credits"], 5.0)

    def test_reaper_never_waits_on_a_held_transaction_lock(self):
        import fcntl
        task = self.task()
        self.submit(task, FakeHops())
        tx_path = video.transaction_path(self.transactions, task)
        with tx_path.with_suffix(".lock").open("a") as held:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX)  # another worker owns this transaction
            done = []
            t = threading.Thread(target=lambda: done.append(q.reap_own(
                query=lambda _tid: {"remote_status": "completed", "cost": 1.0, "urls": []}, force=True)))
            t.start()
            t.join(10)
            self.assertFalse(t.is_alive(), "reaper blocked on a held transaction lock")
        self.assertEqual(done, [0])
        self.assertIsNone(self.fleet.leases["h3_1"]["released"])  # settled by a later round / the poll step


class UnaffectedPathsTests(QueueTestBase):
    def test_giggle_route_never_queues(self):
        task = self.task()
        with patch.dict(os.environ, {"NALU_VIDEO_PROVIDER": "giggle", "GIGGLE_API_KEY": "x"}), \
             patch.object(q, "acquire", side_effect=AssertionError("Giggle task queued")) as acquire, \
             patch.object(video, "_request", side_effect=RuntimeError("GIGGLE_POST_REACHED")):
            try:
                video.submit_one(task, self.receipts, self.transactions)
            except AssertionError:
                raise
            except BaseException:  # noqa: BLE001 -- any Giggle-path outcome; the point is no queue
                pass
        acquire.assert_not_called()
        self.assertEqual(self.fleet.calls, [])

    def test_settlement_of_a_row_without_lease_never_calls_the_queue(self):
        tx = self.root / "image_tx.json"
        tx.write_text(json.dumps({"task_id": "tsk_img", "state": "SUBMITTED_TASK_ID_BOUND"}))
        with patch.object(q, "release", side_effect=AssertionError("image released a lease")):
            row = video.hopsapi.record_settlement(tx, "tsk_img", {"remote_status": "completed", "cost": 2.0},
                                                  now="2026-11-12T00:00:00Z")
        self.assertEqual(row["provider_cost_credits"], 2.0)
        self.assertNotIn("h3_lease", row)
        self.assertEqual(self.fleet.calls, [])


if __name__ == "__main__":
    unittest.main()
