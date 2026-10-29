"""Collective learning with the bucket as the cloud: device batch → inbox object → collector
ingest → ack; duplicate re-upload not double counted; signed channel pointer publish/resolve;
tampered pointer rejected; collector re-run idempotent; unparsable inbox object quarantined."""
from __future__ import annotations

import base64
import io
import json
import tempfile
import unittest
from pathlib import Path

from tools.collective_learning import bundles as b
from tools.collective_learning import contracts as c
from tools.collective_learning import device_store as ds
from tools.collective_learning import object_store as osm
from tools.collective_learning import s3_sync as s3
from tools.collective_learning import service as svc_mod
from tools.collective_learning import sync_client as sc
from tools.collective_learning_demo import demo_rule
from tools.tests.fake_s3 import FakeS3

TENANT = "tenant-t"
API = "engine-api-1"
SD2 = "seedance-2.0-pro"
ENV = {osm.ENV_ACCESS_KEY: "k", osm.ENV_SECRET_KEY: "s", "S3CTL_ENDPOINT_URL": "https://s3.test",
       "S3CTL_BUCKET": "drama01", "S3CTL_PUBLIC_BASE_URL": "https://cdn.test/drama01"}


class Fixture:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.fake = FakeS3()
        self.cfg = osm.ObjectStoreConfig.from_mapping({"endpoint_url": "https://s3.test", "bucket": "drama01",
                                                       "public_base_url": "https://cdn.test/drama01"}, env=ENV)
        self.store = osm.ObjectStore(self.cfg, self.fake, line_id=s3.SERVICE_LINE, receipt_path=tmp / "pre.json")
        self.store.preflight()
        self.private, public = b.generate_keypair()
        self.trust = b.make_trust_store({"pub-1": {"public_key_b64": public, "status": "ACTIVE",
                                                   "roles": [b.KNOWLEDGE_PUBLISHER]}})
        self.svc = svc_mod.Service(tmp / "svc.sqlite", trust_store=self.trust, object_store=self.store)
        self.svc.bootstrap_tenant(TENANT)
        self.collector = s3.Collector(self.svc, self.store, tenant_id=TENANT)
        self.dstore = ds.DeviceStore(tmp / "dev" / "store.sqlite", tenant_id=TENANT, line_id="line-x", device_id="dev-1")
        self.transport = s3.S3Transport(self.store, tenant_id=TENANT, line_id="line-x", device_id="dev-1")
        self.client = sc.SyncClient(self.dstore, self.transport)

    def event(self, **over):
        return self.dstore.record_observation(
            run_id="line-x.EP01.R1", episode_id="EP01", stage="S7", event_kind="FAILURE_OBSERVATION",
            unit_ids=["EP01-VU-001"], visibility="LINE", detected_by="reviewer",
            symptom=over.pop("symptom", "speaker eyeline drifts toward the lens during a line"),
            evidence={"gate": "DIRECTOR_SCORE_V1.performance_interaction", "level": 2,
                      "timecodes": [{"video_sha256": "a" * 64, "timeline": "FINAL_CUT", "start_ms": 100, "end_ms": 900}]},
            opportunity={"applicable_units": 3, "observed_units": 1}, provider_model_version=SD2, **over)

    def keys(self, prefix: str) -> list[str]:
        return sorted(k for (_, k) in self.fake.objects if k.startswith(prefix))


class TransportCollectorTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture(Path(tempfile.mkdtemp()))

    def test_batch_lands_in_inbox_then_collector_ingests_and_acks(self):
        fx = self.fx
        ev = fx.event()
        push = fx.client.run_once()
        self.assertEqual((push["delivered"], push["quarantined"], push["retry"]), (1, 0, 0), push)
        inbox = fx.keys("collective/tenant-t/inbox/")
        self.assertEqual(len(inbox), 1)
        self.assertTrue(inbox[0].startswith("collective/tenant-t/inbox/line-x/dev-1/event/"))
        self.assertEqual(fx.dstore.outbox_status()["counts"].get("DELIVERED"), 1)

        out = fx.collector.run_once()
        self.assertEqual((out["ingested_batches"], out["created"], out["quarantined_batches"]), (1, 1, 0), out)
        self.assertEqual(fx.svc.event_counts(TENANT)["unique_events"], 1)
        self.assertEqual(fx.keys("collective/tenant-t/inbox/"), [])
        self.assertEqual(len(fx.keys("collective/tenant-t/processed/line-x/dev-1/event/")), 1)
        acks = fx.keys("collective/tenant-t/acks/line-x/dev-1/")
        self.assertEqual(len(acks), 1)
        ack = json.loads(fx.store.get_bytes(acks[0]))
        self.assertEqual((ack["results"][0]["id"], ack["results"][0]["status"]), (ev["event_id"], "CREATED"))
        status = fx.transport.sync_status()
        self.assertEqual((status["accepted"], status["rejected"], status["inbox_pending_batches"]), (1, 0, 0))

    def test_duplicate_reupload_is_not_double_counted_and_rerun_is_idempotent(self):
        fx = self.fx
        fx.event()
        fx.client.run_once()
        inbox_key = fx.keys("collective/tenant-t/inbox/")[0]
        doc = json.loads(fx.store.get_bytes(inbox_key))
        fx.collector.run_once()
        self.assertEqual(fx.svc.event_counts(TENANT)["unique_events"], 1)
        # the same batch bytes arrive again (lost ack on the device): same key, ingested as DUPLICATE
        fx.store.put_bytes(inbox_key, (json.dumps(doc, sort_keys=True) + "\n").encode(), "application/json")
        out = fx.collector.run_once()
        self.assertEqual((out["ingested_batches"], out["created"], out["duplicate"]), (1, 0, 1), out)
        self.assertEqual(fx.svc.event_counts(TENANT)["unique_events"], 1)
        # a plain re-run finds nothing: processed objects are never re-ingested
        again = fx.collector.run_once()
        self.assertEqual((again["ingested_batches"], again["items"]), (0, 0))
        # transport-level: posting the identical batch twice produces one key
        status, body, _ = fx.transport.request("POST", "/v1/events:batch", {"events": doc["items"]})
        status2, body2, _ = fx.transport.request("POST", "/v1/events:batch", {"events": doc["items"]})
        self.assertEqual((status, status2, body["inbox_key"], body2["inbox_key"]), (200, 200, inbox_key, inbox_key))

    def test_sensitive_item_refused_before_upload_and_bad_object_quarantined(self):
        fx = self.fx
        status, body, _ = fx.transport.request("POST", "/v1/events:batch", {"events": [
            {"event_id": "e-bad", "symptom": "path /Us" + "ers/x/private"}]})
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["status"], "REJECTED")
        self.assertIn("ABSOLUTE_HOME_PATH", ";".join(body["results"][0]["codes"]))
        self.assertEqual(fx.keys("collective/tenant-t/inbox/"), [])
        # garbage in the inbox never stops the collector
        fx.store.put_bytes("collective/tenant-t/inbox/line-x/dev-1/event/garbage.json", b"{not json", "application/json")
        fx.event()
        fx.client.run_once()
        out = fx.collector.run_once()
        self.assertEqual((out["ingested_batches"], out["quarantined_batches"]), (1, 1), out)
        self.assertEqual(fx.keys("collective/tenant-t/inbox/"), [])
        q = fx.keys("collective/tenant-t/quarantine/line-x/dev-1/event/")
        self.assertEqual(len(q), 2)  # the object and its error note
        note = json.loads(fx.store.get_bytes([k for k in q if k.endswith(".error.json")][0]))
        self.assertEqual(note["status"], "QUARANTINED")
        self.assertEqual(fx.transport.failures()["quarantined_batches"], q)

    def test_bucket_outage_means_retry_never_crash(self):
        fx = self.fx
        fx.event()
        fx.fake.fail_put = RuntimeError("endpoint down")
        push = fx.client.run_once()
        self.assertEqual((push["delivered"], push["retry"]), (0, 1), push)
        self.assertTrue(push["errors"][0].startswith("TRANSPORT:"))
        fx.fake.fail_put = None
        self.assertEqual(sc.drain(fx.client, now=sc.far_future())["outbox"].get("DELIVERED"), 1)


class ChannelTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture(Path(tempfile.mkdtemp()))
        fx = self.fx
        pub = s3.principal(TENANT, "pub-1", "publisher")
        rule = demo_rule()
        bundle = {"schema": c.BUNDLE_SCHEMA, "bundle_id": "directing-dialogue", "version": 2,
                  "created_at": c.now_iso(), "release_channel": "CANARY",
                  "compat": {"engine_api_versions": [API], "models": [SD2]}, "rules": [rule]}
        self.envelope = b.sign_bundle(bundle, key_id="pub-1", private_raw=fx.private)
        self.raw = json.dumps(self.envelope, ensure_ascii=False).encode("utf-8")
        up = fx.svc.upload_bundle(pub, {
            "bundle_id": "directing-dialogue", "version": "2", "digest": c.sha256_bytes(self.raw),
            "payload_b64": base64.b64encode(self.raw).decode("ascii"),
            "signature_b64": self.envelope["signature"]["value_b64"], "key_id": "pub-1",
            "manifest": {"scope": {"models": [SD2], "stages": ["VIDEO_COMPILE"]}}})
        self.assertEqual(up["object_mirror"]["status"], "MIRRORED", up)
        self.mirror_key = up["object_mirror"]["key"]
        self.channel = s3.S3Channel(fx.store, tenant_id=TENANT)
        self.channel.publish_trust(fx.trust)
        self.caps = {"model": SD2, "stage": "VIDEO_COMPILE", "engine_api_version": API}

    def test_publish_then_clean_device_resolves_verified_bundle(self):
        fx = self.fx
        pointer = self.channel.publish("CANARY", bundle_id="directing-dialogue", version="2",
                                       bundle_digest=self.envelope["digest"], payload_sha256=c.sha256_bytes(self.raw),
                                       key_id="pub-1", private_raw=fx.private)
        self.assertEqual(pointer["sequence"], 1)
        self.assertEqual(self.mirror_key, "collective/tenant-t/bundles/directing-dialogue/2.json")
        clean = Path(tempfile.mkdtemp())
        trust = json.loads(fx.store.get_bytes("collective/tenant-t/trust.json"))
        cache = b.BundleCache(clean / "cache", trust)
        resolved = self.channel.resolve(self.caps, cache, trust, channel="CANARY")
        self.assertEqual([e["bundle_id"] for e in resolved["selected"]], ["directing-dialogue"])
        self.assertEqual(resolved["selected"][0]["digest"], self.envelope["digest"])
        self.assertEqual([p["status"] for p in resolved["s3_pull"]], ["OK", "NO_POINTER"])
        self.assertEqual(cache.entries()[0]["release_channel"], "CANARY")
        # SyncClient.pull_bundles works over the same transport (HTTP-shaped resolve + get)
        transport = s3.S3Transport(fx.store, tenant_id=TENANT, line_id="line-x", device_id="dev-2")
        cache2 = b.BundleCache(clean / "cache2", trust)
        client = sc.SyncClient(ds.DeviceStore(clean / "s.sqlite", tenant_id=TENANT, line_id="line-x"), transport)
        pulled = client.pull_bundles(self.caps, channels=["CANARY"],
                                     accept=lambda rec: cache2.admit(base64.b64decode(rec["payload_b64"]), source="s3"))
        self.assertEqual(pulled["fetched"][0]["status"], "FETCHED")
        self.assertEqual(cache2.entries()[0]["digest"], self.envelope["digest"])
        # a RELEASED-only device does not take the canary
        released = self.channel.resolve(self.caps, b.BundleCache(clean / "cache3", trust), trust, channel="RELEASED")
        self.assertEqual(released["selected"], [])

    def test_tampered_pointer_and_unknown_signer_rejected(self):
        fx = self.fx
        self.channel.publish("CANARY", bundle_id="directing-dialogue", version="2",
                             bundle_digest=self.envelope["digest"], payload_sha256=c.sha256_bytes(self.raw),
                             key_id="pub-1", private_raw=fx.private)
        key = "collective/tenant-t/channels/canary.json"
        pointer = json.loads(fx.store.get_bytes(key))
        pointer["body"]["bundles"]["directing-dialogue"]["version"] = "3"
        fx.store.put_bytes(key, json.dumps(pointer).encode(), "application/json")
        with self.assertRaises(b.BundleError) as ctx:
            self.channel.fetch_into_cache(b.BundleCache(Path(tempfile.mkdtemp()), fx.trust), fx.trust, channel="CANARY")
        self.assertTrue(any(code.startswith("CHANNEL_POINTER_DIGEST_MISMATCH") for code in ctx.exception.codes))
        # re-signed by a key the device does not trust
        other_private, other_public = b.generate_keypair()
        bad = self.channel.publish("CANARY", bundle_id="directing-dialogue", version="2",
                                   bundle_digest=self.envelope["digest"], payload_sha256=c.sha256_bytes(self.raw),
                                   key_id="pub-evil", private_raw=other_private)
        with self.assertRaises(b.BundleError) as ctx:
            self.channel.fetch_into_cache(b.BundleCache(Path(tempfile.mkdtemp()), fx.trust), fx.trust, channel="CANARY")
        self.assertIn("SIGNER_UNKNOWN:pub-evil", ctx.exception.codes)
        # swapping the bundle object under a valid pointer is caught by the payload sha
        fx.store.put_bytes(self.mirror_key, b'{"schema":"x"}', "application/json")
        self.channel.publish("CANARY", bundle_id="directing-dialogue", version="2",
                             bundle_digest=self.envelope["digest"], payload_sha256=c.sha256_bytes(self.raw),
                             key_id="pub-1", private_raw=fx.private)
        pull = self.channel.fetch_into_cache(b.BundleCache(Path(tempfile.mkdtemp()), fx.trust), fx.trust, channel="CANARY")
        self.assertEqual(pull["fetched"][0]["status"], "PAYLOAD_SHA_MISMATCH")


class CliTest(unittest.TestCase):
    def test_bootstrap_device_sync_collect_status_with_fake_bucket(self):
        tmp = Path(tempfile.mkdtemp())
        fake = FakeS3()
        factory = lambda cfg, creds: fake  # noqa: E731

        def run(*argv):
            buf = io.StringIO()
            code = s3.main(list(argv), env=ENV, client_factory=factory, out=buf)
            return code, json.loads(buf.getvalue())

        code, boot = run("bootstrap", "--runtime-root", str(tmp / "rt"), "--tenant", "t1")
        self.assertEqual((code, boot["tenant_status"]), (0, "CREATED"), boot)
        root = s3.CollectiveRoot(tmp / "rt")
        self.assertTrue(root.key_path.is_file() and root.trust_path.is_file() and root.db.is_file())
        self.assertEqual(oct(root.key_path.stat().st_mode & 0o777), "0o600")
        self.assertIn(("drama01", "collective/t1/trust.json"), fake.objects)
        self.assertNotIn("private_key_b64", json.dumps(boot))
        code, again = run("bootstrap", "--runtime-root", str(tmp / "rt"), "--tenant", "t1")
        self.assertEqual((again["tenant_status"], again["publisher_key_created"]), ("EXISTS", False))

        # a device line directory with the config the line upgrade gate reads
        dev = tmp / "line-reports"
        dev.mkdir()
        (dev / "trust.json").write_bytes(root.trust_path.read_bytes())
        (dev / "COLLECTIVE_LEARNING_CONFIG.json").write_text(json.dumps({
            "tenant_id": "t1", "line_id": "line-y", "device_store": True, "trust_store": "trust.json",
            "cache_dir": "bundle_cache", "channel": "RELEASED", "engine_api_version": API,
            "capabilities": {"model": SD2}, "batch_id": "B1", "sync": {"mode": "s3"},
            "object_store": {"endpoint_url": "https://s3.test", "bucket": "drama01"}}))
        store = ds.DeviceStore(dev / "COLLECTIVE_DEVICE_STORE.sqlite", tenant_id="t1", line_id="line-y")
        store.record_observation(run_id="line-y.EP01.B1", episode_id="EP01", stage="S7", event_kind="FAILURE_OBSERVATION",
                                 unit_ids=["EP01-VU-001"], visibility="LINE", detected_by="reviewer",
                                 symptom="synthetic symptom for the cli test",
                                 evidence={"gate": "x", "level": 1}, opportunity={"applicable_units": 1, "observed_units": 1})
        code, sync = run("device-sync", "--config", str(dev / "COLLECTIVE_LEARNING_CONFIG.json"))
        self.assertEqual((code, sync["push"]["delivered"]), (0, 1), sync)
        self.assertEqual(sync["sync_status"]["inbox_pending_batches"], 1)
        code, col = run("collect", "--runtime-root", str(tmp / "rt"), "--tenant", "t1")
        self.assertEqual((code, col["created"], col["event_counts"]["unique_events"]), (0, 1, 1), col)
        code, st = run("status", "--runtime-root", str(tmp / "rt"), "--tenant", "t1")
        self.assertEqual((st["objects"]["inbox"], st["objects"]["processed"], st["objects"]["acks"]), (0, 1, 1))
        self.assertTrue(st["trust_in_bucket"])


class BackgroundCollectorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fake = FakeS3()
        self.factory = lambda cfg, creds: self.fake  # noqa: E731
        buf = io.StringIO()
        assert s3.main(["bootstrap", "--runtime-root", str(self.tmp / "rt"), "--tenant", "t1"], env=ENV,
                       client_factory=self.factory, out=buf) == 0, buf.getvalue()
        self.root = s3.CollectiveRoot(self.tmp / "rt")

    def test_fails_closed_without_env_file_and_with_incomplete_env_file(self):
        status = s3.run_cycle(self.tmp / "rt", "t1", client_factory=self.factory)
        self.assertEqual(status["status"], "CREDENTIALS_MISSING")
        self.assertEqual(len(status["required_lines"]), 5)
        self.assertTrue(self.root.status_path.is_file())
        self.root.env_path.write_text("AWS_ACCESS_KEY_ID=k\nS3CTL_BUCKET=drama01\n")
        status = s3.run_cycle(self.tmp / "rt", "t1", client_factory=self.factory)
        self.assertEqual(status["status"], "CREDENTIALS_MISSING")
        self.assertIn("AWS_SECRET_ACCESS_KEY", status["reason"])
        log = (self.root.log_dir / "collector.log").read_text()
        self.assertIn("CREDENTIALS_MISSING", log)
        self.assertNotIn("drama01-user1", log)

    def test_cycle_collects_publishes_released_channels_and_writes_status(self):
        fx_env = {**ENV}
        self.root.env_path.write_text("\n".join(f"{k}={v}" for k, v in {
            "AWS_ACCESS_KEY_ID": "k", "AWS_SECRET_ACCESS_KEY": "s", "S3CTL_ENDPOINT_URL": "https://s3.test",
            "S3CTL_BUCKET": "drama01", "S3CTL_PUBLIC_BASE_URL": "https://cdn.test/drama01"}.items()) + "\n")
        # a bundle released in the service but whose pointer never reached the bucket (e.g. machine was off)
        store = s3.open_object_store(None, line_id=s3.SERVICE_LINE, receipt_path=self.root.preflight_path, env=fx_env,
                                     client_factory=self.factory)
        svc = s3.open_service(self.root, store)
        pub = s3.principal("t1", "pub-cli", "publisher")
        key_id, private = self.root.publisher_key()
        bundle = {"schema": c.BUNDLE_SCHEMA, "bundle_id": "directing-dialogue", "version": 3, "created_at": c.now_iso(),
                  "release_channel": "RELEASED", "compat": {"engine_api_versions": [API], "models": [SD2]},
                  "rules": [demo_rule()]}
        env_ = b.sign_bundle(bundle, key_id=key_id, private_raw=private)
        raw = json.dumps(env_).encode()
        svc.upload_bundle(pub, {"bundle_id": "directing-dialogue", "version": "3", "digest": c.sha256_bytes(raw),
                                "payload_b64": base64.b64encode(raw).decode(), "signature_b64": env_["signature"]["value_b64"],
                                "key_id": key_id, "manifest": {"scope": {"models": [SD2], "stages": ["VIDEO_COMPILE"]}}})
        svc.release(pub, bundle_id="directing-dialogue", version="3", channel="RELEASED")
        # a device batch waiting in the inbox
        transport = s3.S3Transport(store, tenant_id="t1", line_id="line-z", device_id="dev-z")
        transport.request("POST", "/v1/events:batch", {"events": [{
            "event_id": c.new_uuid(), "schema": c.OBSERVATION_SCHEMA if hasattr(c, "OBSERVATION_SCHEMA") else "x",
            "tenant_id": "t1", "line_id": "line-z", "device_id": "dev-z", "run_id": "line-z.EP01.B1", "episode_id": "EP01",
            "stage": "S7", "event_kind": "FAILURE_OBSERVATION", "symptom": "synthetic symptom text for the cycle test",
            "evidence": {"gate": "x", "level": 1}, "opportunity": {"applicable_units": 1, "observed_units": 1},
            "visibility": "LINE", "detected_by": "reviewer", "occurred_at": c.now_iso(), "unit_ids": ["EP01-VU-001"],
            "engine_version": "t", "provider_model_version": SD2, "knowledge_bundle_digest": "NONE"}]})
        status = s3.run_cycle(self.tmp / "rt", "t1", interval_s=300, client_factory=self.factory)
        self.assertEqual(status["status"], "OK", status)
        self.assertEqual(status["collected"]["ingested_batches"], 1)
        self.assertEqual(status["latest_bundle_versions"], {"RELEASED": {"directing-dialogue": "3"}})
        self.assertEqual(status["channels"]["published"][0]["sequence"], 1)
        self.assertEqual(status["backlog_inbox_batches"], 0)
        self.assertEqual(status["interval_s"], 300)
        self.assertEqual(json.loads(self.root.status_path.read_text())["status"], "OK")
        # second cycle: nothing to publish, pointer unchanged, still OK
        again = s3.run_cycle(self.tmp / "rt", "t1", client_factory=self.factory)
        self.assertEqual((again["status"], again["channels"]["published"], len(again["channels"]["unchanged"])), ("OK", [], 1))
        # a clean device resolves the released pointer
        trust = json.loads(store.get_bytes("collective/t1/trust.json"))
        cache = b.BundleCache(self.tmp / "clean-cache", trust)
        resolved = s3.S3Channel(store, tenant_id="t1").resolve({"model": SD2, "stage": "VIDEO_COMPILE", "engine_api_version": API},
                                                                cache, trust, channel="RELEASED")
        self.assertEqual(resolved["selected"][0]["version"], 3)

    def test_lock_prevents_overlapping_cycles(self):
        self.root.env_path.write_text("\n".join(f"{k}=v" for k in s3.REQUIRED_ENV) + "\n")
        import fcntl
        self.root.lock_path.touch()
        with self.root.lock_path.open("r+") as held:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            status = s3.run_cycle(self.tmp / "rt", "t1", client_factory=self.factory)
        self.assertEqual(status["status"], "SKIPPED_OVERLAP")

    def test_install_agent_writes_plist_without_loading(self):
        out = s3.install_agent(self.tmp / "rt", "t1", interval_s=300, python="/usr/bin/python3",
                               agents_dir=self.tmp / "agents", load=False)
        import plistlib
        doc = plistlib.loads(Path(out["plist"]).read_bytes())
        self.assertEqual(doc["Label"], s3.AGENT_LABEL)
        self.assertEqual(doc["StartInterval"], 300)
        self.assertEqual(doc["ProgramArguments"][2:4], ["run-cycle", "--runtime-root"])
        self.assertTrue(doc["RunAtLoad"])
        self.assertIsNone(out["loaded"])
        self.assertIn("launchctl bootstrap gui/", out["load_command"])


if __name__ == "__main__":
    unittest.main()
