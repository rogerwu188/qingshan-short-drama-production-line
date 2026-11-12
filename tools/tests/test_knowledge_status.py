"""knowledge_status.py: model-free on-device status of the cloud shared knowledge base (fleet diagnose).

No network (``network=False`` / ``--no-network``), temp dirs only, and the report must never carry a
credential value -- only booleans, counts, timestamps and host names."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills/nalu-claude-code/scripts"
sys.path.insert(0, str(SCRIPTS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import knowledge_status as ks  # noqa: E402

SECRET = "fake-secret-value-must-never-appear-0123456789"
ACCESS = "FAKEACCESSKEYID0123456789"


class KnowledgeStatusTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.home = tmp / "home"
        self.home.mkdir()
        self.engine = tmp / "engine"
        (self.engine / "configs").mkdir(parents=True)
        (self.engine / "knowledge").mkdir()
        (self.engine / ks.REGISTRY).write_text(json.dumps({"rules": [{"id": "K001"}, {"id": "K002"}]}))
        (self.engine / ks.FAILURE_MEMORY).write_text('{"a": 1}\n{"b": 2}\n')
        self.runtime = tmp / "runtime"
        self.reports = self.runtime / "runtime" / "reports"
        self.reports.mkdir(parents=True)
        (self.runtime / "series").mkdir()
        (self.runtime / "series" / "CURRENT_EPISODE").write_text("E05\n")
        (self.reports / "E05_KNOWLEDGE_BRIEFING.json").write_text(json.dumps({"rules": [{"id": "K001"}]}))
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home)}, clear=False)
        self.env.start()
        for name in (*ks.CRED_NAMES, *ks.NONSECRET_ENV, "NALU_FLEET_URL"):
            os.environ.pop(name, None)

    def tearDown(self):
        self.env.stop()
        self._tmp.cleanup()

    def _configure_active(self):
        cfg = {"tenant_id": "nalu", "line_id": "nalu", "device_store": True, "trust_store": "trust.json",
               "cache_dir": "bundle_cache", "channel": "RELEASED", "engine_api_version": "v1", "batch_id": "B1",
               "sync": {"mode": "s3"}, "env_file": "collective.env",
               "object_store": {"endpoint_url": "https://s3api.example.test", "bucket": "b",
                                "public_base_url": "https://pub.example.test/b"}}
        (self.reports / ks.CONFIG_NAME).write_text(json.dumps(cfg))
        (self.reports / "trust.json").write_text(json.dumps({"publishers": {"pub-nalu": {}}}))
        (self.reports / "collective.env").write_text(f"AWS_ACCESS_KEY_ID={ACCESS}\nAWS_SECRET_ACCESS_KEY={SECRET}\n")
        cache = self.reports / "bundle_cache"
        cache.mkdir()
        (cache / "index.json").write_text(json.dumps({"entries": [
            {"bundle_id": "directing", "version": "2", "digest": "d" * 64, "release_channel": "RELEASED",
             "admitted_at": "2026-11-12T01:00:00+00:00", "source": "s3:collective/nalu/bundles/directing/2.json"}]}))
        from tools.collective_learning.device_store import DeviceStore
        DeviceStore(self.reports / ks.STORE_NAME, tenant_id="nalu", line_id="nalu")
        db = sqlite3.connect(self.reports / ks.STORE_NAME)
        db.execute("INSERT INTO events VALUES('e1','s','{}','nalu.E05.B1','E05','FAILURE_OBSERVATION','LINE',1,"
                   "'2026-11-12T02:00:00+00:00')")
        db.execute("INSERT INTO outbox(item_kind,item_id,payload,state,created_at,delivered_at) "
                   "VALUES('EVENT','e1','{}','DELIVERED','2026-11-12T02:00:00+00:00','2026-11-12T02:05:00+00:00')")
        db.execute("INSERT INTO outbox(item_kind,item_id,payload,state,created_at) "
                   "VALUES('ADOPTION','r1','{}','PENDING','2026-11-12T03:00:00+00:00')")
        db.commit()
        db.close()
        locks = self.reports / "knowledge_locks"
        locks.mkdir()
        (locks / "nalu.E05.B1.knowledge_lock.json").write_text("{}")
        (locks / "nalu.E05.B1.knowledge_lock.adoption.jsonl").write_text("\n".join(json.dumps(r) for r in (
            {"state": "SELECTED"}, {"state": "APPLIED"},
            {"state": "APPLIED", "evidence_scope": "PROVIDER_REQUEST"})) + "\n")
        state_dir = self.runtime / "runtime" / "pipeline_state"
        state_dir.mkdir()
        (state_dir / "E05.json").write_text(json.dumps({"line_upgrade_preflight": {
            "knowledge": {"status": "READ"},
            "collective": {"status": "LOCKED", "bundles": [{"bundle_id": "directing"}], "rejected": []}}}))
        agents = self.home / "Library" / "LaunchAgents"
        agents.mkdir(parents=True)
        (agents / "com.nalu.collective-device.nalu.plist").write_text("<string>device-sync</string>")

    def test_unconfigured_device_reports_not_configured(self):
        r = ks.report(self.engine, self.runtime, network=False)
        self.assertEqual(r["verdict"], "NOT_CONFIGURED")
        self.assertIn("NO_COLLECTIVE_LEARNING_CONFIG", r["gaps"])
        self.assertFalse(r["collective"]["config_present"])
        self.assertFalse(r["collective"]["store"]["present"])
        self.assertEqual(r["episode"], "E05")
        self.assertEqual(r["local_kb"]["registry_rules"], 2)
        self.assertEqual(r["local_kb"]["failure_memory_rows"], 2)
        self.assertTrue(r["local_kb"]["briefing"]["present"])
        self.assertFalse(r["episode_run"]["kb_injected_in_provider_prompts"])
        self.assertEqual(r["remote"], {"checked": False})

    def test_configured_and_active_device(self):
        self._configure_active()
        r = ks.report(self.engine, self.runtime, network=False)
        c = r["collective"]
        self.assertEqual(r["verdict"], "ACTIVE_APPLIED", r["gaps"])
        self.assertEqual(r["gaps"], [])
        self.assertEqual(c["endpoint_host"], "s3api.example.test")
        self.assertEqual(c["public_base_host"], "pub.example.test")
        self.assertTrue(c["credentials"]["resolvable"])
        self.assertEqual(c["credentials"]["sources_with_any"], ["config_env_file"])
        self.assertEqual(c["cache"]["entries"], 1)
        self.assertEqual(c["cache"]["from_s3"], 1)
        self.assertEqual(c["store"]["events"], 1)
        self.assertEqual(c["store"]["outbox"], {"DELIVERED": 1, "PENDING": 1})
        self.assertEqual(c["store"]["last_delivered_at"], "2026-11-12T02:05:00+00:00")
        self.assertTrue(c["sync_agent"]["launchd_plist"])
        run = r["episode_run"]
        self.assertEqual(run["collective_status"], "LOCKED")
        self.assertEqual(run["adoption"], {"SELECTED": 1, "APPLIED": 2})
        self.assertEqual(run["provider_request_applied"], 1)
        self.assertTrue(run["kb_injected_in_provider_prompts"])

    def test_configured_without_credentials_or_bundles_names_the_gaps(self):
        self._configure_active()
        (self.reports / "collective.env").unlink()
        (self.reports / "bundle_cache" / "index.json").unlink()
        (self.reports / "knowledge_locks" / "nalu.E05.B1.knowledge_lock.adoption.jsonl").unlink()
        r = ks.report(self.engine, self.runtime, network=False)
        self.assertEqual(r["verdict"], "LOCKED_NOT_APPLIED")
        self.assertIn("S3_CREDENTIALS_NOT_RESOLVABLE", r["gaps"])
        self.assertIn("BUNDLE_CACHE_EMPTY", r["gaps"])

    def test_cli_never_prints_a_secret_and_last_line_fits_diagnose(self):
        self._configure_active()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = ks.main(["--engine-root", str(self.engine), "--runtime-root", str(self.runtime), "--no-network"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertNotIn(SECRET, out)
        self.assertNotIn(ACCESS, out)
        lines = out.strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["verdict"], "ACTIVE_APPLIED")
        self.assertLessEqual(len(lines[1]), 240)  # fleet_sync._short keeps only the last line, cut at 240
        self.assertEqual(json.loads(lines[1])["v"], "ACTIVE_APPLIED")

    def test_fleet_off_skips_the_network_probe(self):
        with mock.patch.dict(os.environ, {"NALU_FLEET_URL": "off"}), \
                mock.patch.object(ks, "probe", side_effect=AssertionError("network used")):
            r = ks.report(self.engine, self.runtime, network=True)
        self.assertEqual(r["remote"], {"checked": False})

    def test_diagnose_runs_the_script(self):
        import fleet_sync
        src = (SCRIPTS / "fleet_sync.py").read_text(encoding="utf-8")
        self.assertIn('out["knowledge"] = _short(_run(["python3", str(scripts / "knowledge_status.py")], 60, env), 1)',
                      src)
        self.assertTrue(hasattr(fleet_sync, "diagnose"))


if __name__ == "__main__":
    unittest.main()
