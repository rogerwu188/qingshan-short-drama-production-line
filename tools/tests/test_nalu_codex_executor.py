"""skills/nalu-claude-code Codex executor: provider config, start/status, and the heartbeat tick (fake codex CLI)."""
from __future__ import annotations

import json
import shutil
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/nalu-claude-code/scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parents[2] / "lines/nalu/runtime/tools"))

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

    def _exit_with_error(self, message, ep="E06"):
        self.write_provider()
        out = self.run_episode("中途退出", ep)
        with open(out["log"], "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "error", "message": message}) + "\n")

    def test_rate_limited_exit_is_resumed_by_the_system_tick_after_backoff(self):
        # fleet 2026-11-14: 19/20 devices exited on a 429 and waited hours for the 6-hourly agent heartbeat
        self._exit_with_error("exceeded retry limit, last status: 429 Too Many Requests")
        resumed = []
        saved = self.cp.resume
        self.cp.resume = lambda ep, msg: resumed.append((ep, msg)) or {"status": "STARTED"}
        try:
            t = self.cp.tick(system=True)
            self.assertTrue(t["reason"].startswith("PROVIDER_RATE_LIMIT_BACKOFF"), t)
            self.assertNotEqual(t.get("action"), "AGENT_PENDING")
            self.assertEqual(resumed, [])
            d = self.cp.run_dir("E06")
            session = self.cp.read_json(d / "session.json")
            session["rate_limit_resume_after"] = 0  # backoff elapsed
            self.cp.write_json(d / "session.json", session)
            self.cp.tick(system=True)
            self.assertEqual(len(resumed), 1)
            self.assertIn("429", resumed[0][1])
            self.assertEqual(self.cp.read_json(d / "session.json")["rate_limit_resumes"], 1)
        finally:
            self.cp.resume = saved

    def test_exhausted_account_still_goes_to_the_agent(self):
        self._exit_with_error("402 insufficient balance", "E07")
        t = self.cp.tick(system=True)
        self.assertEqual(t["action"], "AGENT_PENDING")
        self.assertTrue(t["reason"].startswith("PROVIDER_ERROR"))

    def test_backoff_is_jittered_and_capped(self):
        first = [self.cp.rate_limit_backoff_s(1) for _ in range(20)]
        self.assertTrue(all(300 <= x <= 900 for x in first))
        self.assertGreater(len({round(x) for x in first}), 1)
        self.assertTrue(all(x <= 1800 for x in (self.cp.rate_limit_backoff_s(n) for n in range(1, 12))))

    def test_finished_episode_starts_the_next_one_without_the_agent(self):
        # line owner + boss 2026-11-10: update between episodes, then Codex writes the next dispatch and produces
        self.write_provider()
        (self.runtime / "briefs").mkdir()
        (self.runtime / "briefs/E04_DISPATCH.md").write_text("order_text: E04 上限 1500", encoding="utf-8")
        (self.runtime / "briefs/E04_PRODUCTION_BRIEF.json").write_text('{"episode_display_number": 3}', encoding="utf-8")
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
        self.assertIn("必须是 **4**", text)  # previous display number + 1, never copied
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

    def test_newest_node_goes_first(self):
        # …1101: /usr/bin (node v12) ahead of nvm's v22 -> codex.js:2 SyntaxError under the cron
        self.write_provider()
        old, new = Path(self.tmp.name) / "old", Path(self.tmp.name) / "new"
        for d, v in ((old, "v12.22.9"), (new, "v99.0.0")):
            d.mkdir()
            (d / "node").write_text(f"#!/bin/sh\necho {v}\n")
            (d / "node").chmod(0o755)
        (self.home / ".nalu_tool_path").write_text(f"{old}:{new}\n", encoding="utf-8")
        self.assertEqual(self.cp.newest_node_dir([str(old), str(new)]), str(new))
        os.environ["PATH"] = f"{old}:{os.environ['PATH']}"
        self.assertEqual(self.cp.codex_env()["PATH"].split(":")[0], str(new))
        self.assertTrue(self.cp.codex_exe(self.cp.codex_env()).endswith("codex"))

    def test_broken_codex_ahead_on_path_is_skipped(self):
        self.write_provider()
        broken = Path(self.tmp.name) / "broken"
        broken.mkdir()
        (broken / "codex").write_text("#!/bin/sh\necho 'Missing optional dependency' >&2\nexit 1\n")
        (broken / "codex").chmod(0o755)
        os.environ["PATH"] = f"{broken}:{os.environ['PATH']}"
        exe = self.cp.codex_exe(self.cp.codex_env())
        self.assertNotEqual(Path(exe).parent, broken)

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

    # ---------------------------------------------------------------- Codex cost cut (2026-11-16)
    def _waiting_s6(self, ep="E08"):
        import paid_run_status as prs  # noqa: PLC0415
        self.write_provider()
        self.run_episode(f'等云端\nNALU_STATUS: {{"episode":"{ep}","state":"WAITING_REMOTE","stage":"S6"}}', ep)
        self.set_stages(ep, {"S5": {"status": "PASS"}, "S6": {"status": "BLOCKED",
                                                              "blockers": ["VIDEO_NOT_ALL_COMPLETED"]}})
        prs.record(self.runtime, ep, "S6", "S6", 1, "/x.log", time.time() - 2)
        self.age(ep, 1000)
        return prs

    def age(self, ep, seconds):
        """Move this Codex turn and its paid-run record ``seconds`` into the past."""
        import paid_run_status as prs  # noqa: PLC0415
        from datetime import datetime, timedelta  # noqa: PLC0415
        d = self.cp.run_dir(ep)
        session = self.cp.read_json(d / "session.json")
        session["started_at"] = (datetime.fromisoformat(session["started_at"]) - timedelta(seconds=seconds)).isoformat()
        self.cp.write_json(d / "session.json", session)
        last = prs.runs_dir(self.runtime, ep) / "last.json"
        rec = json.loads(last.read_text())
        rec["finished_at"] -= seconds - 10
        last.write_text(json.dumps(rec))

    def set_stages(self, ep, stages):
        path = self.runtime / "runtime/pipeline_state" / f"{ep}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"stages": stages}))

    def _patch(self, name, fn):
        saved = getattr(self.cp, name)
        setattr(self.cp, name, fn)
        self.addCleanup(setattr, self.cp, name, saved)

    def test_waiting_remote_is_followed_by_the_tick_without_codex(self):
        prs = self._waiting_s6()
        resumed, reruns = [], []
        self._patch("resume", lambda ep, msg: resumed.append(msg) or {"status": "STARTED"})
        self._patch("launch_paid_rerun", lambda ep, a, b: reruns.append((ep, a, b)) or {"status": "STARTED", "pid": 1})
        last = prs.runs_dir(self.runtime, "E08") / "last.json"
        rec = json.loads(last.read_text())
        rec["finished_at"] = time.time() - 5
        last.write_text(json.dumps(rec))
        t = self.cp.tick(system=True)
        self.assertEqual(t["reason"], "REMOTE_WAIT_BACKOFF", t)          # the 240 s interval has not passed
        rec["finished_at"] -= 300
        last.write_text(json.dumps(rec))
        t = self.cp.tick(system=True)
        self.assertEqual(t["reason"], "REMOTE_WAIT_RERUN_STARTED", t)
        self.assertEqual(reruns, [("E08", "S6", "S6")])                 # the SAME paid command, by the tick
        self.assertEqual(self.cp.tick(system=True)["reason"], "REMOTE_WAIT_RERUN_STARTING")
        self.assertEqual(resumed, [])                                    # no model round trip while waiting
        lock = self.runtime / "runtime/.paid_E08.lock"
        lock.mkdir()
        (lock / "pid").write_text(str(os.getpid()))
        self.assertEqual(self.cp.tick(system=True)["reason"], "REMOTE_WAIT_IN_FLIGHT")
        shutil.rmtree(lock)
        # the re-run finished with a wave review to answer: Codex is woken with the reason
        self.set_stages("E08", {"S6": {"status": "REVIEW_REQUIRED", "blockers": ["S6.q2:REVIEW_REQUIRED"]}})
        prs.record(self.runtime, "E08", "S6", "S6", 1, "/x.log", time.time() - 2)
        t = self.cp.tick(system=True)
        self.assertEqual(len(resumed), 1, t)
        self.assertIn("S6_REVIEW_REQUIRED", resumed[0])
        self.assertIn("paid_stage.sh --status E08", resumed[0])

    def test_a_tick_rerun_that_left_no_record_wakes_codex(self):
        self._waiting_s6("E09")
        resumed = []
        self._patch("resume", lambda ep, msg: resumed.append(msg) or {"status": "STARTED"})
        d = self.cp.run_dir("E09")
        session = self.cp.read_json(d / "session.json")
        session["remote_wait"] = {"key": session["log"], "reruns": 1, "last_rerun_at": time.time() - 150}
        self.cp.write_json(d / "session.json", session)
        self.cp.tick(system=True)
        self.assertEqual(len(resumed), 1)
        self.assertIn("TICK_RERUN_ENDED_WITHOUT_A_RECORD", resumed[0])

    def test_rerun_cap_wakes_codex(self):
        self._waiting_s6("E10")
        resumed = []
        self._patch("resume", lambda ep, msg: resumed.append(msg) or {"status": "STARTED"})
        d = self.cp.run_dir("E10")
        session = self.cp.read_json(d / "session.json")
        session["remote_wait"] = {"key": session["log"], "reruns": 90}
        self.cp.write_json(d / "session.json", session)
        self.cp.tick(system=True)
        self.assertIn("REMOTE_WAIT_CAP", resumed[0])

    def _rollout(self, thread_id, input_tokens):
        home = self.home / ".codex/sessions/2026/11/16"
        home.mkdir(parents=True, exist_ok=True)
        rows = [{"type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 9_000_000}, "last_token_usage": {"input_tokens": n}}}}
            for n in (217_000, input_tokens)]
        (home / f"rollout-2026-11-16T00-00-00-{thread_id}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n")

    def test_large_thread_resumes_in_a_fresh_thread_with_a_handoff(self):
        self.write_provider()
        os.environ["FAKE_REPLY"] = '等云端\nNALU_STATUS: {"episode":"E11","state":"WAITING_REMOTE"}'
        out = self.cp.start("E11", "派单附加说明：第 11 集，原著第 40-42 章。")
        self.reap(out["pid"])
        self.set_stages("E11", {"S5": {"status": "PASS"}, "S6": {"status": "BLOCKED", "blockers": ["Q2_FAIL:VU-7"]}})
        (self.runtime / "runtime/SUPERVISOR_ORDERS.json").write_text(json.dumps({"latest_order_seq": 41, "orders": [
            {"seq": 41, "status": "active", "decision": {"kind": "GATE_FAIL_ACCEPTANCE", "episode": "E11",
                                                         "gate_id": "ACTION-ROLE-EVIDENCE", "detectors": ["VU-3:x"]}}]}))
        d = self.cp.run_dir("E11")
        session = self.cp.read_json(d / "session.json")
        session["no_status_resumes"] = 2
        self.cp.write_json(d / "session.json", session)
        self._rollout("th-1", 650_000)

        out = self.cp.resume("E11", "继续")
        self.reap(out["pid"])
        self.assertIsNone(out["resumed_from"])                           # a new thread, not `exec resume`
        self.assertEqual(out["fresh_thread"]["from_thread"], "th-1")
        prompt = Path(out["log"]).with_suffix(".prompt.md").read_text(encoding="utf-8")
        for needle in ("合同", "新线程接手", "650000", "S6 BLOCKED", "Q2_FAIL:VU-7", "seq=41", "ACTION-ROLE-EVIDENCE",
                       "派单附加说明：第 11 集", "paid_stage.sh --status E11", "NALU_STATUS"):
            self.assertIn(needle, prompt)
        session = self.cp.read_json(d / "session.json")
        self.assertEqual(session["no_status_resumes"], 2)               # the resume caps still count
        self.assertEqual(session["fresh_threads"][-1]["from_thread"], "th-1")
        self.assertEqual(session["codex_thread_id"], "th-1")             # the runner records the new thread's id

    def test_provider_rejected_resume_hands_off_to_a_fresh_thread(self):
        """Device …1485 (2026-11-19): codex-cli 0.170 sent `additional_tools` on exec resume and HopsAPI refused
        every resume before the first token; the next resume must start a fresh thread instead."""
        self.write_provider()
        self.run_episode('等\nNALU_STATUS: {"episode":"E13","state":"WAITING_REMOTE"}', "E13")
        self._rollout("th-1", 120_000)                                    # small thread: no size hand-off
        d = self.cp.run_dir("E13")
        session = self.cp.read_json(d / "session.json")
        with open(session["log"], "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "turn.failed", "error": {"message": "Invalid value: 'additional_tools'.",
                                 "type": "invalid_request_error", "param": "input[0].type"}}) + "\n")
        out = self.cp.resume("E13", "继续")
        self.reap(out["pid"])
        self.assertIsNone(out["resumed_from"])
        self.assertEqual(out["fresh_thread"]["from_thread"], "th-1")

    def test_small_thread_is_resumed_in_place(self):
        self.write_provider()
        self.run_episode('等\nNALU_STATUS: {"episode":"E12","state":"WAITING_REMOTE"}', "E12")
        self._rollout("th-1", 250_000)
        out = self.cp.resume("E12", "继续")
        self.reap(out["pid"])
        self.assertEqual(out["resumed_from"], "th-1")
        os.environ["NALU_CODEX_FRESH_THREAD_TOKENS"] = "200000"         # configurable threshold
        out = self.cp.resume("E12", "继续")
        self.reap(out["pid"])
        self.assertIsNone(out["resumed_from"])
        os.environ["NALU_CODEX_FRESH_THREAD_TOKENS"] = "0"              # 0 = never
        out = self.cp.resume("E12", "继续")
        self.reap(out["pid"])
        self.assertEqual(out["resumed_from"], "th-1")


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
