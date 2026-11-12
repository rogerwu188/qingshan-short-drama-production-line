"""billing_key_guard: which account production bills, by fingerprint (never values); informational only.

Line owner 2026-11-12: StoryClaw, Codex, image and video all bill one HopsAPI pool (the StoryClaw account),
so a platform key is allowed -- paid stages and Codex launches must NOT refuse it."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills/nalu-claude-code/scripts"
sys.path.insert(0, str(SCRIPTS))

import billing_key_guard as guard  # noqa: E402

PLATFORM = "sk-storyclaw-platform-0123456789abcdef"
OWN = "sk-line-owner-own-hopsapi-fedcba9876543210"


class BillingKeyGuardTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        cfg = self.home / ".openclaw"
        (cfg / "agents/main/agent").mkdir(parents=True)
        (cfg / "openclaw.json").write_text(json.dumps(
            {"models": {"providers": {"storyclaw": {"baseUrl": "https://hopsapi.com/v1", "apiKey": PLATFORM}}}}))
        (cfg / "agents/main/agent/auth-profiles.json").write_text(json.dumps({"profiles": [{"key": "short"}]}))
        self.engine, self.runtime = self.home / "nalu_engine", self.home / "nalu_runtime"
        (self.runtime / "credentials").mkdir(parents=True)
        self.engine.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_platform_key_is_recognised_and_own_key_is_not(self):
        self.assertTrue(guard.is_platform_key(PLATFORM, self.home))
        self.assertTrue(guard.is_platform_key(PLATFORM + "\n", self.home), "whitespace from .env is ignored")
        self.assertFalse(guard.is_platform_key(OWN, self.home))
        self.assertFalse(guard.is_platform_key("", self.home))

    def _report(self, codex: str, hops: str | None) -> dict:
        (self.runtime / "credentials/llm_provider.json").write_text(json.dumps({"base_url": "x", "api_key": codex}))
        if hops is not None:
            (self.engine / ".env").write_text(f"GIGGLE_API_KEY=g\nHOPSAPI_API_KEY='{hops}'\n")
        with mock.patch.dict(os.environ, {"NALU_ENGINE_ROOT": str(self.engine), "NALU_RUNTIME_ROOT": str(self.runtime)}):
            return guard.report(self.home)

    def test_report_names_provenance_never_values(self):
        r = self._report(PLATFORM, None)
        self.assertEqual(r["hopsapi_key_source"], "llm_provider.json")
        self.assertTrue(r["codex_key_is_storyclaw"] and r["hopsapi_key_is_storyclaw"])
        r = self._report(OWN, OWN)
        self.assertEqual(r["hopsapi_key_source"], ".env")
        self.assertFalse(r["codex_key_is_storyclaw"] or r["hopsapi_key_is_storyclaw"])
        self.assertTrue(r["hopsapi_equals_codex"])
        r = self._report(OWN, PLATFORM)
        self.assertTrue(r["hopsapi_key_is_storyclaw"])
        self.assertFalse(r["codex_key_is_storyclaw"])
        self.assertNotIn(OWN, json.dumps(r))
        self.assertNotIn(PLATFORM, json.dumps(r))

    def _check_env(self, value: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "HOME": str(self.home), "HOPSAPI_API_KEY": value}
        return subprocess.run([sys.executable, str(SCRIPTS / "billing_key_guard.py"), "check-env", "HOPSAPI_API_KEY"],
                              capture_output=True, text=True, env=env)

    def test_check_env_exit_codes_and_no_echo(self):
        bad = self._check_env(PLATFORM)
        self.assertEqual(bad.returncode, 3)
        self.assertIn(guard.BLOCKER, bad.stdout)
        self.assertNotIn(PLATFORM, bad.stdout + bad.stderr)
        self.assertEqual(self._check_env(OWN).returncode, 0)
        self.assertEqual(self._check_env("").returncode, 2)

    def test_platform_key_is_never_a_blocker(self):
        self.assertNotIn("billing_key_guard", (ROOT / "lines/nalu/runtime/tools/paid_stage.sh").read_text(encoding="utf-8"))
        import codex_production as cp
        self.assertFalse(hasattr(cp, "provider_is_storyclaw_billing"))

if __name__ == "__main__":
    unittest.main()
