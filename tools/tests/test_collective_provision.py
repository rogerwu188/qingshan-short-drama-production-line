"""Fleet provisioning of collective learning on a device + the rate-limited, locked device-sync tick.

Offline: the fleet response is a fake; device-sync runs against the fake bucket (tools/tests/fake_s3)
through a tiny runner script, so no network is touched."""
from __future__ import annotations

import base64
import json
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills/nalu-claude-code/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import collective_provision as cp  # noqa: E402
from tools.collective_learning import bundles as b  # noqa: E402
from tools.collective_learning import s3_sync as s3  # noqa: E402

SECRET = "sk-test-SECRET-value-0123456789"


def _trust() -> dict:
    _, public = b.generate_keypair()
    return b.make_trust_store({"pub-fleet": {"public_key_b64": public, "status": "ACTIVE",
                                             "roles": [b.KNOWLEDGE_PUBLISHER]}})


def _body(channel: str = "RELEASED", trust: dict | None = None) -> dict:
    return {"enabled": True, "channel": channel, "device_id": "sn-abc123",
            "config": {"tenant_id": "nalu", "line_id": "nalu", "engine_api_version": "nalu-engine-api-1",
                       "capabilities": {"model": "MiniMax-H3"}, "event_visibility": "LINE",
                       "object_store": {"endpoint_url": "https://s3.test", "bucket": "drama01",
                                        "public_base_url": "https://cdn.test/drama01"}},
            "trust": trust or _trust(),
            "credentials": {"AWS_ACCESS_KEY_ID": "AKIDTEST", "AWS_SECRET_ACCESS_KEY": SECRET}}


class ProvisionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = Path(tempfile.mkdtemp())
        (self.runtime / "runtime").mkdir()
        self.reports = cp.reports_dir(self.runtime)
        self.calls = 0

    def fetch(self, code: int, body: dict):
        def _f():
            self.calls += 1
            return code, body
        return _f

    def test_disabled_or_unreachable_touches_nothing(self) -> None:
        for fetch in (self.fetch(404, {"error": "NOT_FOUND"}), self.fetch(200, {"enabled": False}),
                      self.fetch(500, {}), lambda: (_ for _ in ()).throw(OSError("down"))):
            out = cp.provision(self.runtime, fetch, force=True)
            self.assertIn(out["status"], ("DISABLED", "HTTP_500", "UNREACHABLE"))
            self.assertFalse(self.reports.exists(), out)

    def test_enabled_writes_config_trust_env_0600_and_device_sync_can_read_them(self) -> None:
        body = _body()
        out = cp.provision(self.runtime, self.fetch(200, body), now=1_000_000.0)
        self.assertEqual(out["status"], "PROVISIONED")
        self.assertEqual(sorted(out["changed"]), sorted([cp.CONFIG_NAME, "collective/trust.json", "collective/s3.env"]))
        config = json.loads((self.reports / cp.CONFIG_NAME).read_text())
        self.assertEqual((config["tenant_id"], config["line_id"], config["device_id"], config["channel"]),
                         ("nalu", "nalu", "sn-abc123", "RELEASED"))
        self.assertEqual((config["sync"], config["device_store"], config["env_file"]),
                         ({"mode": "s3"}, True, "collective/s3.env"))
        env_path = self.reports / "collective" / "s3.env"
        self.assertEqual(stat.S_IMODE(env_path.stat().st_mode), 0o600)
        env = s3.load_env_file(env_path)  # the exact format device_sync reads
        self.assertEqual((env["AWS_ACCESS_KEY_ID"], env["AWS_SECRET_ACCESS_KEY"], env["S3CTL_BUCKET"]),
                         ("AKIDTEST", SECRET, "drama01"))
        self.assertTrue((self.reports / "collective" / "bundle_cache").is_dir())
        b.load_trust_store(self.reports / "collective" / "trust.json")
        loaded, base = s3.load_device_config(self.reports / cp.CONFIG_NAME)
        self.assertEqual(base, self.reports.resolve())
        # no secret anywhere but the env file
        self.assertNotIn(SECRET, json.dumps(out))
        self.assertNotIn(SECRET, cp.state_path(self.runtime).read_text())
        self.assertNotIn(SECRET, (self.reports / cp.CONFIG_NAME).read_text())
        self.assertNotIn(SECRET, json.dumps(cp.report(self.runtime)))

    def test_idempotent_and_rate_limited(self) -> None:
        body = _body()
        cp.provision(self.runtime, self.fetch(200, body), now=1_000_000.0)
        mtimes = {p: p.stat().st_mtime_ns for p in self.reports.rglob("*") if p.is_file()}
        out = cp.provision(self.runtime, self.fetch(200, body), now=1_000_000.0 + 60)
        self.assertEqual((out["status"], self.calls), ("RATE_LIMITED", 1))
        out = cp.provision(self.runtime, self.fetch(200, body), now=1_000_000.0 + cp.PROVISION_INTERVAL_S + 1)
        self.assertEqual((out["status"], out["changed"], self.calls), ("UNCHANGED", [], 2))
        self.assertEqual(mtimes, {p: p.stat().st_mtime_ns for p in self.reports.rglob("*") if p.is_file()})
        # the canary cohort moves this device: only the config changes
        canary = {**body, "channel": "CANARY"}
        out = cp.provision(self.runtime, self.fetch(200, canary), force=True)
        self.assertEqual(out["changed"], [cp.CONFIG_NAME])
        self.assertEqual(json.loads((self.reports / cp.CONFIG_NAME).read_text())["channel"], "CANARY")
        # a loosened env-file mode is put back even when the bytes are unchanged
        os.chmod(self.reports / "collective" / "s3.env", 0o644)
        cp.provision(self.runtime, self.fetch(200, canary), force=True)
        self.assertEqual(stat.S_IMODE((self.reports / "collective" / "s3.env").stat().st_mode), 0o600)

    def test_malformed_response_is_refused_without_writing(self) -> None:
        bad = _body()
        bad["credentials"]["AWS_SECRET_ACCESS_KEY"] = "x\ninjected=1"
        bad["config"]["object_store"]["secret_key"] = "no"
        bad["channel"] = "BETA"
        out = cp.provision(self.runtime, self.fetch(200, bad), force=True)
        self.assertEqual(out["status"], "INVALID")
        self.assertIn("CREDENTIAL_INVALID:AWS_SECRET_ACCESS_KEY", out["problems"])
        self.assertIn("OBJECT_STORE_CARRIES_CREDENTIALS", out["problems"])
        self.assertIn("CHANNEL_INVALID:BETA", out["problems"])
        self.assertFalse(self.reports.exists())


FAKE_SYNC = textwrap.dedent("""
    import json, sys, time
    mode = sys.argv[1]
    if mode == "sleep":
        time.sleep(5)
    print(json.dumps({"status": "OK", "device_id": "sn-abc123", "push": {"delivered": 2, "in_flight": 1},
                      "pull": [{"channel": "RELEASED", "status": "OK", "sequence": 4,
                                "fetched": [{"status": "FETCHED"}]}],
                      "cache_entries": [{"bundle_id": "nalu-kb", "version": 3, "release_channel": "RELEASED",
                                         "digest": "x"}]} if mode == "ok" else
                     {"status": "ERROR", "code": "CredentialsMissing", "error": "env file missing"}))
""")


class SyncTickTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = Path(tempfile.mkdtemp())
        (self.runtime / "runtime").mkdir()
        cp.provision(self.runtime, lambda: (200, _body()), force=True)
        self.script = Path(tempfile.mkdtemp()) / "fake_sync.py"
        self.script.write_text(FAKE_SYNC)
        self.spawned: list[list[str]] = []

    def spawn(self, argv, log):
        self.spawned.append(argv)

    def test_not_configured_is_a_no_op(self) -> None:
        empty = Path(tempfile.mkdtemp())
        self.assertEqual(cp.sync_tick(empty, ROOT, spawn=self.spawn)["status"], "NOT_CONFIGURED")
        self.assertEqual(self.spawned, [])

    def test_rate_limit_and_lock(self) -> None:
        self.assertEqual(cp.sync_tick(self.runtime, ROOT, now=5_000_000.0, spawn=self.spawn)["status"], "STARTED")
        self.assertIn("device-sync-run", self.spawned[0])
        self.assertEqual(cp.sync_tick(self.runtime, ROOT, now=5_000_000.0 + 60, spawn=self.spawn)["status"], "RATE_LIMITED")
        import fcntl
        lock = cp._lock_path(self.runtime)
        with open(lock, "a") as held:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            later = 5_000_000.0 + cp.SYNC_INTERVAL_S + 1
            self.assertEqual(cp.sync_tick(self.runtime, ROOT, now=later, spawn=self.spawn)["status"], "SYNC_RUNNING")
            self.assertEqual(cp.run_device_sync(self.runtime, ROOT, argv=[sys.executable, str(self.script), "ok"]),
                             {"status": "SYNC_RUNNING"})
        self.assertEqual(len(self.spawned), 1)
        self.assertEqual(cp.sync_tick(self.runtime, ROOT, now=5_000_000.0 + cp.SYNC_INTERVAL_S + 2,
                                      spawn=self.spawn)["status"], "STARTED")

    def test_runner_records_result_and_timeout(self) -> None:
        out = cp.run_device_sync(self.runtime, ROOT, argv=[sys.executable, str(self.script), "ok"])
        self.assertEqual((out["status"], out["push"]["delivered"], out["cache_entries"]),
                         ("OK", 2, ["nalu-kb@3:RELEASED"]))
        last = json.loads((cp.reports_dir(self.runtime) / "collective_logs" / "device-sync.last.json").read_text())
        self.assertEqual(last["status"], "OK")
        rep = cp.report(self.runtime)
        self.assertEqual((rep["provisioned"], rep["channel"], rep["last_sync_status"], rep["pack"]),
                         (True, "RELEASED", "OK", ["nalu-kb@3"]))
        failed = cp.run_device_sync(self.runtime, ROOT, argv=[sys.executable, str(self.script), "err"])
        self.assertEqual((failed["status"], failed["error_code"]), ("ERROR", "CredentialsMissing"))
        slow = cp.run_device_sync(self.runtime, ROOT, timeout_s=1, argv=[sys.executable, str(self.script), "sleep"])
        self.assertEqual(slow["status"], "TIMEOUT")
        self.assertEqual(cp.report(self.runtime)["last_sync_ok_at"], out["finished_at"])

    def test_real_device_sync_against_fake_bucket(self) -> None:
        """The provisioned files drive the real s3_sync.device_sync (fake bucket client)."""
        from tools.tests.fake_s3 import FakeS3
        from tools.collective_learning import device_store as ds
        reports = cp.reports_dir(self.runtime)
        fake = FakeS3()
        result = s3.device_sync(reports / cp.CONFIG_NAME, env={}, client_factory=lambda cfg, creds: fake)
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["device_id"], "sn-abc123")
        store = ds.DeviceStore(reports / "COLLECTIVE_DEVICE_STORE.sqlite", tenant_id="nalu", line_id="nalu")
        self.assertEqual(store.device_id, "sn-abc123")


class FleetSyncHookTest(unittest.TestCase):
    def test_fleet_off_touches_nothing_and_on_provisions(self) -> None:
        import fleet_sync
        runtime = Path(tempfile.mkdtemp())
        (runtime / "runtime").mkdir()
        fake_cp = SimpleNamespace(roots=lambda: (ROOT, runtime))
        with mock.patch.dict(os.environ, {"NALU_FLEET_URL": "off"}):
            self.assertEqual(fleet_sync.sync(fake_cp, {}), {})
        self.assertFalse(cp.reports_dir(runtime).exists())
        with mock.patch.object(fleet_sync, "_req", return_value=(200, _body())) as req, \
                mock.patch.object(cp, "_spawn_detached") as spawn:
            out = fleet_sync.collective_tick(fake_cp, "tok")
        self.assertEqual(out, {"provision": "PROVISIONED", "sync": "STARTED"})
        self.assertEqual(req.call_args.args[:2], ("GET", "/v1/collective/provision"))
        self.assertEqual(spawn.call_count, 1)


if __name__ == "__main__":
    unittest.main()
