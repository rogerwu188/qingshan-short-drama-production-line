"""skills/nalu-claude-code Codex executor: provider config, start/status, and the heartbeat tick (fake codex CLI)."""
from __future__ import annotations

import json
import shutil
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
        self._review_status_code = codex_production.review_status_code

    def tearDown(self):
        self.cp.review_status_code = self._review_status_code
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
        t = self.cp.tick()  # no mp4 here, so nothing to publish; no E02 dispatch, so the agent takes over once
        self.assertEqual((t["action"], t["reason"]), ("AGENT", "NEXT_EPISODE_PREVIOUS_DISPATCH_MISSING"))

        self.run_episode('需要线主\nNALU_STATUS: {"episode":"E03","state":"OWNER_DECISION_REQUIRED","question":"q"}', "E03")
        self.assertEqual(self.cp.tick()["action"], "AGENT")
        again = self.cp.tick()  # handed over once; the next heartbeats stay quiet
        self.assertEqual(again["action"], "NONE")
        self.assertTrue(again["reason"].startswith("WAITING_ON_AGENT_OR_OWNER"))

        (self.runtime / "series/PAUSED").write_text("")
        self.assertEqual(self.cp.tick()["reason"], "PAUSED")

    def test_finished_episode_starts_the_next_one_without_the_agent(self):
        # line owner + boss 2026-11-10: update between episodes, then Codex writes the next dispatch and produces
        self.write_provider()
        (self.runtime / "briefs").mkdir()
        (self.runtime / "briefs/E04_DISPATCH.md").write_text("order_text: E04 上限 1500", encoding="utf-8")
        self.run_episode('完成。\nNALU_STATUS: {"episode":"E04","state":"FINAL_CUT_READY"}', "E04")
        import fleet_sync
        calls = []
        saved = fleet_sync.scripted_update
        fleet_sync.scripted_update = lambda cp, pin: calls.append(pin) or (True, {"before": "a", "after": "b"}, {})
        os.environ["FAKE_REPLY"] = '写派单\nNALU_STATUS: {"episode":"E05","state":"RUNNING"}'
        try:
            t = self.cp.tick()
        finally:
            fleet_sync.scripted_update = saved
        self.assertEqual((t["action"], t["reason"]), ("NONE", "NEXT_EPISODE_STARTED"))
        self.assertEqual(calls, [""])  # the engine update ran first
        self.reap(t["next_episode"]["pid"])
        self.assertEqual(self.cp.current_episode(), "E05")
        prompt = Path(json.loads((self.runtime / "claude_code/E05/session.json").read_text())["log"]).parent
        text = "".join(x.read_text(encoding="utf-8") for x in prompt.glob("*prompt*"))
        self.assertIn("E04_DISPATCH.md", text)
        self.assertIn("E05_DISPATCH.md", text)
        self.assertEqual(self.cp.next_episode_id("E09"), "E10")

    def test_fleet_agent_task_goes_to_the_agent_heartbeat_once(self):
        self.write_provider()
        task = self.runtime / "series/FLEET_AGENT_TASK.json"
        task.parent.mkdir(parents=True, exist_ok=True)
        task.write_text(json.dumps({"message": "检查心跳模型", "delivered": False}), encoding="utf-8")
        self.assertNotEqual(self.cp.tick(system=True).get("reason"), "FLEET_AGENT_TASK")  # cron never consumes it
        t = self.cp.tick()
        self.assertEqual((t["action"], t["reason"], t["fleet_agent_task"]), ("AGENT", "FLEET_AGENT_TASK", "检查心跳模型"))
        self.assertNotEqual(self.cp.tick().get("reason"), "FLEET_AGENT_TASK")

    def test_cron_finds_codex_through_recorded_tool_dirs(self):
        # …1037 / …0899: the system cron's bare PATH could not find codex (CODEX_NOT_INSTALLED)
        self.write_provider()
        self.cp.tick()  # the heartbeat (full PATH, fake codex on it) records where codex lives
        recorded = (self.home / ".nalu_tool_path").read_text(encoding="utf-8").strip()
        self.assertTrue(recorded)
        os.environ["PATH"] = "/usr/bin:/bin"
        self.assertIn(recorded.split(":")[0], self.cp.codex_env()["PATH"].split(":"))
        self.assertIsNotNone(shutil.which("codex", path=self.cp.codex_env()["PATH"]))

    def test_failed_waiting_remote_resume_is_surfaced(self):
        # …1101: under the cron every WAITING_REMOTE resume failed silently for hours
        self.write_provider()
        self.run_episode('等云端\nNALU_STATUS: {"episode":"E08","state":"WAITING_REMOTE"}', "E08")
        saved = self.cp.resume
        self.cp.resume = lambda ep, msg: {"status": "BLOCKED", "reason": "CODEX_NOT_INSTALLED"}
        try:
            t = self.cp.tick()
        finally:
            self.cp.resume = saved
        self.assertEqual((t["action"], t["reason"]), ("AGENT", "RESUME_FAILED:CODEX_NOT_INSTALLED"))

    def test_gateway_path_dirs_never_raises(self):
        self.assertIsInstance(self.cp.gateway_path_dirs(), list)

    def test_series_done_is_quiet(self):
        self.write_provider()
        self.run_episode('完\nNALU_STATUS: {"episode":"E09","state":"SERIES_DONE"}', "E09")
        t = self.cp.tick()
        self.assertEqual((t["action"], t["reason"]), ("NONE", "SERIES_DONE"))

    def test_blocked_is_handed_back_hourly_for_an_update_check(self):
        # field device …1324 E02: a blocked machine never ran self_update, so a maintainer fix never reached it
        self.write_provider()
        self.run_episode('卡住\nNALU_STATUS: {"episode":"E05","state":"BLOCKED","note":"CODE_BLOCKER"}', "E05")
        self.assertEqual(self.cp.tick()["reason"], "BLOCKED")
        self.assertEqual(self.cp.tick()["action"], "NONE")  # within the hour: quiet
        session_path = self.runtime / "claude_code/E05/session.json"
        session = json.loads(session_path.read_text())
        session["tick_notified_at"] = "2020-01-01T00:00:00Z"
        session_path.write_text(json.dumps(session))
        again = self.cp.tick()
        self.assertEqual((again["action"], again["reason"]), ("AGENT", "BLOCKED_RECHECK_UPDATE"))
        self.assertEqual(self.cp.tick()["action"], "NONE")

    def test_system_tick_leaves_the_hand_off_for_the_agent(self):
        # line owner + boss 2026-11-10: the system cron advances production; AGENT hand-offs stay with the agent
        self.write_provider()
        self.run_episode('需要线主\nNALU_STATUS: {"episode":"E07","state":"OWNER_DECISION_REQUIRED","question":"q"}', "E07")
        self.assertEqual(self.cp.tick(system=True)["action"], "AGENT_PENDING")
        self.assertEqual(self.cp.tick(system=True)["action"], "AGENT_PENDING")
        self.assertEqual(self.cp.tick()["action"], "AGENT")  # the heartbeat still gets it once
        self.assertEqual(self.cp.tick(system=True)["action"], "NONE")

    def final_review_episode(self):
        self.write_provider()
        self.run_episode('等终审\nNALU_STATUS: {"episode":"E06","state":"FINAL_REVIEW_REQUIRED"}', "E06")
        req = self.runtime / "runtime/reviews/E06/final_audience_request.json"
        req.parent.mkdir(parents=True)
        req.write_text('{"schema": "x"}')
        return req

    def reviewer_state(self):
        return json.loads((self.runtime / "claude_code/E06/final_reviewer/reviewer.json").read_text())

    def test_final_review_launches_an_independent_codex_reviewer(self):
        # line owner 2026-11-09: the engine starts the reviewer (gpt-6.1-sol), no agent hand-off needed
        self.final_review_episode()
        self.cp.review_status_code = lambda _ep: self.cp.REVIEW_REQUIRED_CODE
        t = self.cp.tick()
        self.assertEqual(t["action"], "NONE")
        self.assertEqual(t["final_review"]["status"], "STARTED")
        state = self.reviewer_state()
        self.reap(state["pid"])
        self.assertEqual(state["model"], "hopsapi/gpt-6.1-sol")
        prompt = next(Path(state["log"]).parent.glob("review_*.prompt.md")).read_text(encoding="utf-8")
        self.assertIn(state["process_id"], prompt)
        self.assertIn("hopsapi/gpt-6.1-sol", prompt)
        self.assertIn("final_audience_review.py submit --episode E06", prompt)
        # second attempt, then the agent takes over
        self.assertEqual(self.cp.tick()["final_review"]["status"], "STARTED")
        self.reap(self.reviewer_state()["pid"])
        t = self.cp.tick()
        self.assertEqual((t["action"], t["reason"]), ("AGENT", "FINAL_REVIEW_REQUIRED:EXHAUSTED"))

    def test_exhausted_review_gets_fresh_attempts_after_a_reviewer_prompt_fix(self):
        # …1324 E04 2026-11-10: both attempts wrote sound pass completed=false ("cannot hear"); the fixed prompt
        # defines ASR + audio measurement as the sound pass, and an updated engine retries the same request
        self.final_review_episode()
        self.cp.review_status_code = lambda _ep: self.cp.REVIEW_REQUIRED_CODE
        path = self.runtime / "claude_code/E06/final_reviewer/reviewer.json"
        path.parent.mkdir(parents=True)
        req_sha = self.cp._file_sha(self.runtime / "runtime/reviews/E06/final_audience_request.json")
        path.write_text(json.dumps({"request_sha256": req_sha, "attempts": 2}))  # written by the older engine
        out = self.cp.final_review_step("E06")
        self.assertEqual(out["status"], "STARTED")
        self.reap(self.reviewer_state()["pid"])
        prompt = next(path.parent.glob("review_*.prompt.md")).read_text(encoding="utf-8")
        self.assertIn("completed: true", prompt)
        self.assertEqual(self.reviewer_state()["prompt_version"], self.cp.REVIEWER_PROMPT_VERSION)

    def test_review_status_query_gets_the_runtime_roots(self):
        # field device …1324 E03: the cron ran tick without NALU_RUNTIME_ROOT and the query read another runtime
        seen = {}
        real = self.cp.subprocess.run
        def fake(argv, **kw):
            seen.update(kw.get("env") or {})
            return subprocess.CompletedProcess(argv, 10)
        self.cp.subprocess.run = fake
        try:
            self.assertEqual(self._review_status_code("E06"), 10)
        finally:
            self.cp.subprocess.run = real
        self.assertEqual(seen.get("NALU_RUNTIME_ROOT"), str(self.runtime))
        self.assertEqual(seen.get("NALU_ENGINE_ROOT"), str(self.engine))

    def test_submitted_review_resumes_the_producer_at_most_twice(self):
        self.final_review_episode()
        self.cp.review_status_code = lambda _ep: 3   # rejected review on record
        t = self.cp.tick()
        self.assertTrue(any(d.startswith("resume_after_final_review") for d in t["did"]))
        self.reap(json.loads((self.runtime / "claude_code/E06/session.json").read_text())["pid"])
        self.run_episode('还在等\nNALU_STATUS: {"episode":"E06","state":"FINAL_REVIEW_REQUIRED"}', "E06")
        self.assertTrue(any(d.startswith("resume_after_final_review") for d in self.cp.tick()["did"]))
        self.reap(json.loads((self.runtime / "claude_code/E06/session.json").read_text())["pid"])
        self.run_episode('还在等\nNALU_STATUS: {"episode":"E06","state":"FINAL_REVIEW_REQUIRED"}', "E06")
        t = self.cp.tick()
        self.assertEqual((t["action"], t["reason"]), ("AGENT", "FINAL_REVIEW_REQUIRED:PRODUCER_STILL_STOPPED"))

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
