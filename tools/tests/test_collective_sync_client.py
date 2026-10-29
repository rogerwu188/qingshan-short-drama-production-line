"""Device uploader against a real local HTTP service: loss, outage, restart, quarantine.

Covers requirement test matrix rows T05, T07 (device side), T08, server database
restart mid-stream, and part of T24 (a dead cloud never blocks recording).
"""
from __future__ import annotations

import base64
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tools.collective_learning import contracts as c
from tools.collective_learning import device_store as ds
from tools.collective_learning import http_api as api
from tools.collective_learning import service as svc_mod
from tools.collective_learning import sync_client as sc

ROOT = Path(__file__).resolve().parents[2]
FAR = sc.far_future


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LossyTransport:
    """Delivers the request to the real service, then 'loses' the response N times."""

    def __init__(self, inner: sc.HttpTransport, losses: int = 1):
        self.inner, self.losses, self.calls = inner, losses, 0

    def request(self, method, path, body=None, headers=None):
        self.calls += 1
        result = self.inner.request(method, path, body, headers)
        if self.losses > 0:
            self.losses -= 1
            raise sc.TransportError("SIMULATED_RESPONSE_LOST_AFTER_SERVER_COMMIT")
        return result


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="collective-sync-"))
        self.db = self.tmp / "svc.sqlite"
        self.svc = svc_mod.Service(self.db, max_batch=50)
        admin = self.svc.authenticate(self.svc.bootstrap_tenant("acme")["token"])
        self.token = self.svc.register_principal(admin, principal_id="dev-a", role="device_writer",
                                                 line_ids=["lineA"])["token"]
        self.server, _ = api.start_server(self.svc)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.store_path = self.tmp / "device.sqlite"
        self.store = ds.DeviceStore(self.store_path, tenant_id="acme", line_id="lineA", device_id="dev-a")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.svc.close()

    def record(self, n: int, **kw) -> list[dict]:
        return [self.store.record_observation(run_id="run-1", episode_id="EP01", stage="S6",
                                              event_kind="RUN_ANOMALY", symptom=f"synthetic {i}",
                                              evidence={"i": i}, detected_by="test", visibility="LINE", **kw)
                for i in range(n)]


class UploadTest(Base):
    def test_T05_response_lost_after_commit_is_not_double_counted(self) -> None:
        self.record(3)
        lossy = LossyTransport(sc.HttpTransport(self.base, self.token), losses=1)
        client = sc.SyncClient(self.store, lossy)
        first = client.run_once()
        self.assertEqual((first["delivered"], first["retry"]), (0, 3))
        self.assertEqual(self.svc.event_counts("acme")["unique_events"], 3)  # the server did commit
        second = sc.drain(client, now=FAR())
        self.assertEqual(second["outbox"]["DELIVERED"], 3)
        counts = self.svc.event_counts("acme")
        self.assertEqual((counts["unique_events"], counts["deliveries"], counts["duplicate_deliveries"]), (3, 6, 3))

    def test_T07_device_quarantines_rejected_item_and_delivers_the_rest(self) -> None:
        good = self.record(2)
        # an item that slipped into the outbox with another device's identity (e.g. a restored backup)
        alien = c.make_observation(tenant_id="acme", line_id="lineA", device_id="dev-zz", run_id="r", episode_id="EP01",
                                   stage="S6", event_kind="RUN_ANOMALY", symptom="alien", evidence={"x": 1},
                                   detected_by="t", producer_sequence=99, visibility="LINE")
        import sqlite3
        db = sqlite3.connect(self.store_path)
        db.execute("INSERT INTO outbox(item_kind, item_id, payload, created_at) VALUES('EVENT',?,?,?)",
                   (alien["event_id"], json.dumps(alien), c.now_iso()))
        db.commit()
        db.close()
        summary = sc.drain(sc.SyncClient(self.store, sc.HttpTransport(self.base, self.token)), now=FAR())
        self.assertEqual(summary["outbox"], {"PENDING": 0, "DELIVERED": 2, "QUARANTINED": 1})
        quarantined = self.store.outbox_status()["quarantined"][0]
        self.assertEqual(quarantined["item_id"], alien["event_id"])
        self.assertIn("IDENTITY_MISMATCH:device_id", quarantined["reason"])
        self.assertEqual(self.svc.event_counts("acme")["unique_events"], len(good))

    def test_T08_outage_then_process_restart_delivers_everything_exactly_once(self) -> None:
        dead = sc.HttpTransport(f"http://127.0.0.1:{_free_port()}", self.token, timeout=1)
        self.record(4)
        summary = sc.SyncClient(self.store, dead).run_once()
        self.assertEqual((summary["delivered"], summary["retry"]), (0, 4))
        # a separate OS process records more facts while the cloud is still down, then exits
        script = ("import sys; sys.path.insert(0, sys.argv[1]);"
                  "from tools.collective_learning import device_store as ds;"
                  "s = ds.DeviceStore(sys.argv[2], tenant_id='acme', line_id='lineA');"
                  "[s.record_observation(run_id='run-2', episode_id='EP02', stage='S6', event_kind='RUN_ANOMALY',"
                  " symptom=f'from child {i}', evidence={'i': i}, detected_by='child', visibility='LINE')"
                  " for i in range(3)]")
        subprocess.run([sys.executable, "-c", script, str(ROOT), str(self.store_path)], check=True, timeout=60)
        # restart: brand-new store object on the same file, cloud back
        reopened = ds.DeviceStore(self.store_path, tenant_id="acme", line_id="lineA")
        self.assertEqual(reopened.device_id, "dev-a")
        result = sc.drain(sc.SyncClient(reopened, sc.HttpTransport(self.base, self.token)), now=FAR())
        self.assertEqual(result["outbox"], {"PENDING": 0, "DELIVERED": 7, "QUARANTINED": 0})
        counts = self.svc.event_counts("acme")
        self.assertEqual((counts["unique_events"], counts["duplicate_deliveries"]), (7, 0))
        sequences = sorted(e["producer_sequence"] for e in reopened.events())
        self.assertEqual(sequences, list(range(1, 8)))

    def test_server_database_restart_mid_stream(self) -> None:
        self.record(5)
        client = sc.SyncClient(self.store, sc.HttpTransport(self.base, self.token), batch_size=2,
                               max_batches_per_run=1)
        client.run_once()
        self.assertEqual(self.svc.event_counts("acme")["unique_events"], 2)
        port = self.server.server_address[1]
        self.server.shutdown()
        self.server.server_close()
        self.svc.close()
        down = client.run_once(now=FAR())
        self.assertEqual(down["delivered"], 0)
        self.svc = svc_mod.Service(self.db, max_batch=50)
        self.server = api.ApiServer(("127.0.0.1", port), self.svc)
        import threading
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        final = sc.drain(sc.SyncClient(self.store, sc.HttpTransport(self.base, self.token)), now=FAR() + 10 ** 8)
        self.assertEqual(final["outbox"]["DELIVERED"], 5)
        self.assertEqual(self.svc.event_counts("acme")["unique_events"], 5)

    def test_413_halves_batch_size_and_retries(self) -> None:
        self.record(60)  # service max_batch is 50
        client = sc.SyncClient(self.store, sc.HttpTransport(self.base, self.token), batch_size=60)
        summary = sc.drain(client, now=FAR())
        self.assertEqual(client.batch_size, 30)
        self.assertEqual(summary["outbox"]["DELIVERED"], 60)

    def test_private_local_facts_never_enter_the_outbox(self) -> None:
        self.store.record_observation(run_id="r", episode_id="EP01", stage="S6", event_kind="RUN_ANOMALY",
                                      symptom="private", evidence={"x": 1}, detected_by="t",
                                      visibility="PRIVATE_LOCAL")
        self.assertEqual(self.store.count("outbox"), 0)


class NonBlockingTest(Base):
    def test_T24_dead_cloud_never_blocks_recording(self) -> None:
        dead = sc.HttpTransport(f"http://127.0.0.1:{_free_port()}", self.token, timeout=2)
        runner = sc.BackgroundSync(sc.SyncClient(self.store, dead), interval=0.05).start()
        try:
            started = time.monotonic()
            self.record(20)
            elapsed = time.monotonic() - started
        finally:
            runner.stop()
        self.assertLess(elapsed, 5.0)
        self.assertEqual(self.store.count("events"), 20)
        self.assertEqual(self.store.outbox_status()["counts"]["PENDING"], 20)

    def test_pull_offline_and_online_hands_bytes_to_accept_hook(self) -> None:
        dead = sc.SyncClient(self.store, sc.HttpTransport(f"http://127.0.0.1:{_free_port()}", self.token, timeout=1))
        self.assertEqual(dead.pull_bundles({"model": "MiniMax-H3", "stage": "S6"})["status"], "OFFLINE")
        admin = self.svc.authenticate(self.svc.bootstrap_tenant("t2")["token"])
        del admin  # tenant isolation sanity: unused second tenant must not leak bundles
        pub_admin = self.svc.authenticate(self.svc.register_principal(
            self.svc.authenticate(self._admin_token()), principal_id="pub-x", role="publisher")["token"])
        payload = b'{"rules":[]}'
        verifier_svc = svc_mod.Service(self.db, signature_verifier=lambda r, p: (True, "test"))
        verifier_svc.upload_bundle(pub_admin, {
            "bundle_id": "kb", "version": "1", "digest": c.sha256_bytes(payload),
            "payload_b64": base64.b64encode(payload).decode(), "signature_b64": "c2ln", "key_id": "k",
            "manifest": {"scope": {"models": ["MiniMax-H3"], "stages": ["S6"]}, "baseline": True}})
        verifier_svc.release(pub_admin, bundle_id="kb", version="1", channel="RELEASED")
        verifier_svc.close()
        seen = []
        client = sc.SyncClient(self.store, sc.HttpTransport(self.base, self.token))
        result = client.pull_bundles({"model": "MiniMax-H3", "stage": "S6"}, accept=lambda rec: seen.append(rec) or "ok")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(seen[0]["digest"], c.sha256_bytes(payload))
        self.assertEqual(base64.b64decode(seen[0]["payload_b64"]), payload)
        none = client.pull_bundles({"model": "Seedance-2.0", "stage": "S6"}, accept=seen.append)
        self.assertEqual(none["fetched"], [])

    def _admin_token(self) -> str:
        return self.svc.rotate_credential(
            svc_mod.Principal("admin-acme", "acme", "admin"), "admin-acme")["token"]


if __name__ == "__main__":
    unittest.main()
