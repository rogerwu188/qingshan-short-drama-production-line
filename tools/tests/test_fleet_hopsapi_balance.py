"""Fleet report carries the HopsAPI account balance (line owner 2026-11-12: one credit pool; at 0 every S6
video fails at zero cost).  GET /v1/account/credits only, cached 10 min, the key never reported."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "nalu-claude-code" / "scripts"))

import fleet_sync  # noqa: E402

KEY = "sk-fleet-test-key-0123456789"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class HopsapiBalanceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.engine, self.runtime = root / "engine", root / "runtime"
        (self.runtime / "credentials").mkdir(parents=True)
        self.engine.mkdir()
        (self.runtime / "credentials/llm_provider.json").write_text(
            json.dumps({"base_url": "https://hopsapi.com/v1", "api_key": KEY}))
        self.env = mock.patch.dict(os.environ, {"NALU_FLEET_URL": "https://fleet.test"})
        self.env.start()
        self.calls = []

    def tearDown(self):
        self.env.stop()
        self._tmp.cleanup()

    def _open(self, payload=None, error=None):
        def fake(req, timeout=None):
            self.calls.append((req.full_url, req.get_header("Authorization")))
            if error:
                raise error
            return _Resp(json.dumps(payload).encode())
        return mock.patch.object(fleet_sync.urllib.request, "urlopen", side_effect=fake)

    def test_balance_read_with_the_codex_key_and_cached(self):
        body = {"data": {"credits": 1842.68, "outstanding": 12.5, "key_limit": None}}
        with self._open(body):
            first = fleet_sync.hopsapi_credits(self.engine, self.runtime, now=1000.0)
            again = fleet_sync.hopsapi_credits(self.engine, self.runtime, now=1300.0)
        self.assertEqual(first["credits"], 1842.68)
        self.assertEqual(first["outstanding"], 12.5)
        self.assertEqual(again, first, "cached inside 10 min")
        self.assertEqual(self.calls, [("https://hopsapi.com/v1/account/credits", "Bearer " + KEY)])
        self.assertNotIn(KEY, json.dumps(first))
        self.assertNotIn(KEY, (self.runtime / "series/.hopsapi_credits.json").read_text())

    def test_env_key_and_base_url_win(self):
        (self.engine / ".env").write_text("HOPSAPI_API_KEY='sk-env-key-abcdefghijklmnop'\nHOPSAPI_BASE_URL=https://alt.hops/v1\n")
        with self._open({"data": {"credits": 5, "key_limit": {"remaining": 3}}}):
            out = fleet_sync.hopsapi_credits(self.engine, self.runtime, now=1.0)
        self.assertEqual(self.calls[0], ("https://alt.hops/v1/account/credits", "Bearer sk-env-key-abcdefghijklmnop"))
        self.assertEqual(out["key_remaining"], 3)

    def test_errors_are_reported_not_raised(self):
        err = urllib.error.HTTPError("u", 503, "x", {}, None)
        with self._open(error=err):
            self.assertEqual(fleet_sync.hopsapi_credits(self.engine, self.runtime, now=1.0)["error"], "HTTP 503")

    def test_no_hopsapi_key_or_fleet_off_means_no_probe(self):
        (self.runtime / "credentials/llm_provider.json").write_text(json.dumps({"base_url": "https://relay.x/v1", "api_key": KEY}))
        with self._open({"data": {}}):
            self.assertIsNone(fleet_sync.hopsapi_credits(self.engine, self.runtime, now=1.0))
        with mock.patch.dict(os.environ, {"NALU_FLEET_URL": "off"}), self._open({"data": {}}):
            self.assertIsNone(fleet_sync.hopsapi_credits(self.engine, self.runtime, now=1.0))
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
