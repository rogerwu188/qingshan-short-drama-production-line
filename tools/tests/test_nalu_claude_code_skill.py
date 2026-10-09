"""skills/nalu-claude-code: relay wiring for Claude Code and the NALU_STATUS bridge."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/nalu-claude-code/scripts"
sys.path.insert(0, str(SCRIPTS))
import claude_production as cp  # noqa: E402

KEY = "sk-test-0000000000000000000000000000wxyz"


class ConfigureClaudeCodeTests(unittest.TestCase):
    def run_tool(self, home: Path, *args: str) -> tuple[int, dict]:
        env = dict(os.environ, HOME=str(home))
        run = subprocess.run([sys.executable, str(SCRIPTS / "configure_claude_code.py"), *args],
                             capture_output=True, text=True, env=env)
        return run.returncode, json.loads(run.stdout)

    def test_writes_relay_env_and_never_prints_the_key(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / ".openclaw").mkdir()
            (home / ".openclaw/openclaw.json").write_text(json.dumps({"models": {"providers": {"storyclaw": {
                "baseUrl": "https://llm.example.test/", "apiKey": KEY,
                "models": [{"id": "gpt-6-astra"}, {"id": "claude-opus-5"}]}}}}))
            code, out = self.run_tool(home)
            self.assertEqual(code, 0)
            self.assertEqual(out["status"], "CONFIGURED")
            self.assertNotIn(KEY, json.dumps(out))
            settings = json.loads((home / ".claude/settings.json").read_text())
            self.assertEqual(settings["env"]["ANTHROPIC_BASE_URL"], "https://llm.example.test")
            self.assertEqual(settings["env"]["ANTHROPIC_API_KEY"], KEY)
            self.assertEqual(settings["env"]["ANTHROPIC_MODEL"], "claude-opus-5-5")  # line-owner default
            self.assertIn("Read(~/.openclaw/**)", settings["permissions"]["deny"])
            self.assertEqual(oct((home / ".claude/settings.json").stat().st_mode & 0o777), "0o600")
            self.assertTrue(json.loads((home / ".claude.json").read_text())["hasCompletedOnboarding"])

    def test_uses_the_relays_own_spelling_of_opus_5_5(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / ".openclaw").mkdir()
            (home / ".openclaw/openclaw.json").write_text(json.dumps({"models": {"providers": {"storyclaw": {
                "baseUrl": "https://llm.example.test", "apiKey": KEY,
                "models": [{"id": "storyclaw/claude-opus-5"}, {"id": "storyclaw/claude-opus-5.5"}]}}}}))
            code, out = self.run_tool(home)
            self.assertEqual(code, 0)
            self.assertEqual(out["model"], "storyclaw/claude-opus-5.5")

    def test_missing_provider_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / ".openclaw").mkdir()
            (home / ".openclaw/openclaw.json").write_text(json.dumps({"models": {"providers": {}}}))
            code, out = self.run_tool(home)
            self.assertEqual(code, 2)
            self.assertEqual(out["status"], "BLOCKED")


class NaluStatusBridgeTests(unittest.TestCase):
    def test_parse_log_reads_session_and_last_status_line(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "run.jsonl"
            final = 'S3 dry planned.\nNALU_STATUS: {"episode":"E01","state":"OWNER_DECISION_REQUIRED","stage":"S3","question":"授权？"}'
            log.write_text("\n".join(json.dumps(ev, ensure_ascii=False) for ev in [
                {"type": "system", "subtype": "init", "session_id": "sess-1"},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "working"}]}},
                {"type": "result", "result": final, "is_error": False, "session_id": "sess-1"},
            ]) + "\nnot json\n", encoding="utf-8")
            info = cp.parse_log(log)
            self.assertEqual(info["session_id"], "sess-1")
            self.assertEqual(info["nalu_status"]["state"], "OWNER_DECISION_REQUIRED")
            self.assertEqual(info["nalu_status"]["question"], "授权？")


if __name__ == "__main__":
    unittest.main()
