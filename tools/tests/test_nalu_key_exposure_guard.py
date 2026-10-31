"""Secret guard (lab 2026-10-31): Codex is told never to read/print key files or key env vars, never gets the
provider keys in its own environment, and the orchestrator redacts key values from every step log/tail."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills/nalu-claude-code/scripts"
for _path in (str(ROOT), str(SCRIPTS), str(ROOT / "lines/nalu/runtime/tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import codex_production  # noqa: E402
import nalu_pipeline  # noqa: E402

CONTRACT = ROOT / "skills/nalu-claude-code/CLAUDE_CODE_PRODUCTION.md"
FAKE = "fake-secret-value-0123456789"


class ContractRuleTests(unittest.TestCase):
    def test_contract_section_1_forbids_reading_or_printing_keys(self):
        text = CONTRACT.read_text(encoding="utf-8")
        rules = text.split("## 1. 绝对规则", 1)[1].split("## 2.0", 1)[0]
        self.assertIn("密钥绝不读、绝不打印", rules)
        for needle in (".env", "credentials/", "*.key", "printenv", "paid_stage.sh --check"):
            self.assertIn(needle, rules)
        env_section = text.split("## 0. 环境与位置", 1)[1].split("## 1.", 1)[0]
        self.assertIn("paid_stage.sh --check <EP>", env_section)

    def test_codex_adapter_carries_the_same_rule(self):
        adapter = codex_production.CODEX_ADAPTER
        self.assertIn("密钥硬规则", adapter)
        for needle in (".env", "credentials/", "printenv", "paid_stage.sh --check"):
            self.assertIn(needle, adapter)

    def test_provider_keys_are_not_handed_to_codex(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GIGGLE_API_KEY": FAKE, "HOPSAPI_API_KEY": FAKE, "X2C_API_KEY": FAKE,
                                         "NALU_RUNTIME_ROOT": tmp, "NALU_ENGINE_ROOT": tmp}), \
                    patch.object(codex_production, "provider", return_value={"api_key": "codex-own-key"}):
                env = codex_production.codex_env()
        for name in ("GIGGLE_API_KEY", "HOPSAPI_API_KEY", "X2C_API_KEY"):
            self.assertNotIn(name, env)
        self.assertEqual(env[codex_production.KEY_ENV], "codex-own-key")

    def test_configured_shell_policy_excludes_every_provider_key(self):
        text = (SCRIPTS / "configure_codex.py").read_text(encoding="utf-8")
        line = next(row for row in text.splitlines() if row.startswith("exclude = ["))
        for needle in ("GIGGLE_API_KEY", "HOPSAPI_API_KEY", "X2C_API_KEY", "*_API_KEY", "*_TOKEN"):
            self.assertIn(needle, line)


class RedactionTests(unittest.TestCase):
    def test_secret_env_values_and_bearer_tokens_are_masked(self):
        env = {"HOPSAPI_API_KEY": FAKE, "GIGGLE_API_KEY": "another-fake-secret-42", "SHORT_KEY": "abc",
               "PATH": "/usr/bin:/bin"}
        text = f"key={FAKE} giggle=another-fake-secret-42 Authorization: Bearer abcdefghijklmnop12 abc /usr/bin"
        out = nalu_pipeline.redact_secrets(text, env)
        self.assertNotIn(FAKE, out)
        self.assertNotIn("another-fake-secret-42", out)
        self.assertNotIn("abcdefghijklmnop12", out)
        self.assertIn("***HOPSAPI_API_KEY***", out)
        self.assertIn("abc /usr/bin", out)  # short values and non-secret names are left alone

    def test_step_log_and_tails_never_keep_a_key_a_child_printed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = nalu_pipeline.Ctx.__new__(nalu_pipeline.Ctx)
            ctx.run_id = "r1"
            ctx.p = type("P", (), {"logs": Path(tmp)})()
            ctx.log = lambda *_a, **_k: None
            ctx.child_env = lambda paid, extra=None: dict(os.environ)
            with patch.dict(os.environ, {"HOPSAPI_API_KEY": FAKE}):
                step = nalu_pipeline.Ctx.run(ctx, [sys.executable, "-c",
                                                   "import os,sys; print(os.environ['HOPSAPI_API_KEY']); "
                                                   "print(os.environ['HOPSAPI_API_KEY'], file=sys.stderr)"],
                                             name="leak", cwd=Path(tmp))
            self.assertNotIn(FAKE, step["stdout_tail"] + step["stderr_tail"])
            self.assertNotIn(FAKE, Path(step["log"]).read_text(encoding="utf-8"))
            self.assertIn("***HOPSAPI_API_KEY***", step["stdout_tail"])


if __name__ == "__main__":
    unittest.main()
