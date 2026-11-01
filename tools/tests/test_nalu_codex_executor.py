"""skills/nalu-claude-code Codex executor: provider config, start/status, and the heartbeat tick (fake codex CLI)."""
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

FAKE_CODEX = r"""#!/bin/sh
# fake codex: --version, or `exec [resume] ... -o <file> ...`; replies with $FAKE_REPLY
[ "$1" = "--version" ] && { echo "codex-cli 0.0-test"; exit 0; }
out=""; prev=""
for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done
cat >/dev/null 2>&1 || true
echo '{"type":"thread.started","thread_id":"th-1"}'
echo '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":5}}'
[ -n "$out" ] && printf '%s' "${FAKE_REPLY:-OK}" > "$out"
exit 0
"""


class CodexExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home, self.runtime, self.engine = root / "home", root / "runtime", root / "engine"
        bindir = root / "bin"
        for d in (self.home, self.runtime / "credentials", self.engine / "skills/nalu-claude-code", bindir):
            d.mkdir(parents=True)
        (self.engine / "skills/nalu-claude-code/CLAUDE_CODE_PRODUCTION.md").write_text("合同", encoding="utf-8")
        (bindir / "codex").write_text(FAKE_CODEX)
        (bindir / "codex").chmod(0o755)
        self.saved = dict(os.environ)
        os.environ.update(HOME=str(self.home), NALU_RUNTIME_ROOT=str(self.runtime), NALU_ENGINE_ROOT=str(self.engine),
                          PATH=f"{bindir}:{os.environ['PATH']}")
        import codex_production
        self.cp = codex_production

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)
        self.tmp.cleanup()

    def configure(self, *args):
        r = subprocess.run([sys.executable, str(SCRIPTS / "configure_codex.py"), *args], capture_output=True, text=True)
        return json.loads(r.stdout.strip().splitlines()[-1].split("CODEX_CONFIG: ", 1)[1])

    def write_provider(self, **kw):
        p = {"base_url": "https://relay.example/v1", "api_key": "sk-test-1234", "model": "gpt-5.6", **kw}
        (self.runtime / "credentials/llm_provider.json").write_text(json.dumps(p))

    def test_provider_is_required_then_configured_and_verified(self):
        self.assertEqual(self.configure("--verify")["status"], "NEEDS_PROVIDER")
        self.write_provider()
        out = self.configure("--verify")
        self.assertEqual(out["status"], "VERIFIED")
        # gpt-5.6 is a retired default: it follows DEFAULT_MODEL unless the provider file locks it
        self.assertEqual(out["model"], "gpt-6.1-sol")
        cfg = (self.home / ".codex/config.toml").read_text()
        self.assertIn('base_url = "https://relay.example/v1"', cfg)
        self.assertNotIn("sk-test-1234", cfg)
        self.assertNotIn("sk-test-1234", json.dumps(out))
        self.assertEqual(oct((self.runtime / "credentials/llm_provider.json").stat().st_mode & 0o777), "0o600")

    def test_model_locked_keeps_retired_default(self):
        self.write_provider(model_locked=True)
        self.assertEqual(self.configure()["model"], "gpt-5.6")

    def test_legacy_codex_key_host_is_migrated(self):
        (self.home / ".codex").mkdir()
        (self.home / ".codex/config.toml").write_text('model = "gpt-5.6"\nbase_url = "https://hopsapi.com/v1"\n')
        (self.runtime / "credentials/codex_api_key").write_text("sk-legacy-9999\n")
        out = self.configure()
        self.assertEqual(out["status"], "CONFIGURED")
        self.assertEqual(out["base_url"], "https://hopsapi.com/v1")
        migrated = json.loads((self.runtime / "credentials/llm_provider.json").read_text())
        self.assertEqual(migrated["api_key"], "sk-legacy-9999")

    def run_episode(self, reply, ep="E02"):
        os.environ["FAKE_REPLY"] = reply
        out = self.cp.start(ep)
        self.assertEqual(out["status"], "STARTED")
        self.reap(out["pid"])
        return out

    @staticmethod
    def reap(pid):  # in production the launcher exits and init reaps the runner; here the test is its parent
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass

    def test_tick_routes_each_state(self):
        self.write_provider()
        self.assertEqual(self.cp.tick()["reason"], "NO_EPISODE_STARTED")

        self.run_episode('完成。\nNALU_STATUS: {"episode":"E02","state":"FINAL_CUT_READY"}')
        self.assertEqual(self.cp.status("E02")["codex"]["nalu_status"]["state"], "FINAL_CUT_READY")
        t = self.cp.tick()
        self.assertEqual(t["action"], "WRITE_NEXT_EPISODE")  # no mp4 here, so nothing to publish

        self.run_episode('需要线主\nNALU_STATUS: {"episode":"E03","state":"OWNER_DECISION_REQUIRED","question":"q"}', "E03")
        self.assertEqual(self.cp.tick()["action"], "AGENT")
        again = self.cp.tick()  # handed over once; the next heartbeats stay quiet
        self.assertEqual(again["action"], "NONE")
        self.assertTrue(again["reason"].startswith("WAITING_ON_AGENT_OR_OWNER"))

        (self.runtime / "series/PAUSED").write_text("")
        self.assertEqual(self.cp.tick()["reason"], "PAUSED")

    def test_tick_resumes_without_status_then_escalates(self):
        self.write_provider()
        self.run_episode("没有状态行", "E04")
        for _ in range(self.cp.MAX_NO_STATUS_RESUMES):
            t = self.cp.tick()
            self.assertTrue(any(d.startswith("resume_no_status") for d in t["did"]))
            self.reap(json.loads((self.runtime / "claude_code/E04/session.json").read_text())["pid"])
        self.assertEqual(self.cp.tick()["action"], "AGENT")


if __name__ == "__main__":
    unittest.main()


class EngineModificationTests(unittest.TestCase):
    def test_tick_reports_a_patched_engine_once_and_keeps_the_diff(self):
        import importlib
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            engine, runtime = root / "engine", root / "runtime"
            (engine / "tools").mkdir(parents=True); runtime.mkdir()
            (engine / "tools/x.py").write_text("A = 1\n")
            for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"]):
                subprocess.run(["git", "-C", str(engine), *cmd], check=True)
            saved = dict(os.environ)
            os.environ.update(NALU_ENGINE_ROOT=str(engine), NALU_RUNTIME_ROOT=str(runtime))
            try:
                import codex_production as cp
                importlib.reload(cp)
                self.assertIsNone(cp.engine_modification())
                (engine / "tools/x.py").write_text("A = 2\n")
                first = cp.tick()
                self.assertEqual(first["reason"], "ENGINE_MODIFIED_ON_HOST")
                self.assertTrue(Path(first["engine_modification"]["patch"]).is_file())
                self.assertIn("A = 2", Path(first["engine_modification"]["patch"]).read_text())
                self.assertNotEqual(cp.tick().get("reason"), "ENGINE_MODIFIED_ON_HOST")  # once per diff
            finally:
                os.environ.clear(); os.environ.update(saved)
