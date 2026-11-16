"""Codex cost cut (device …1144 E08/E09, 2026-11-16): remote waits go to the system tick, compact tool output,
the short knowledge briefing, and a fresh Codex thread when a resumed thread is already large."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
SCRIPTS = ROOT / "skills" / "nalu-claude-code" / "scripts"
for _p in (TOOLS, SCRIPTS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import paid_run_status as prs  # noqa: E402
import line_upgrade_gate as lug  # noqa: E402


def _state(runtime: Path, ep: str, stages: dict) -> Path:
    path = runtime / "runtime" / "pipeline_state" / f"{ep}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"stages": stages}), encoding="utf-8")
    return path


S6_WAIT = {"S5": {"status": "PASS"}, "S6": {"status": "BLOCKED", "blockers": ["wave3:VIDEO_NOT_ALL_COMPLETED",
                                                                             "VIDEO_NOT_ALL_COMPLETED"]}}


class ClassifyTest(unittest.TestCase):
    def test_remote_only_blockers_wait(self) -> None:
        out = prs.classify({"stages": S6_WAIT}, "S6", "S6")
        self.assertEqual((out["verdict"], out["stage"]), (prs.WAIT, "S6"))
        self.assertEqual(out["interval_s"], 240)

    def test_image_outage_waits_ten_minutes_six_times(self) -> None:
        out = prs.classify({"stages": {"S5": {"status": "BLOCKED", "blockers": ["HOPSAPI_IMAGE_PROVIDER_OUTAGE"]}}},
                           "S5", "S5")
        self.assertEqual((out["verdict"], out["interval_s"], out["max_reruns"]), (prs.WAIT, 600, 6))

    def test_anything_needing_judgement_acts(self) -> None:
        for stages, reason in (
                ({"S6": {"status": "REVIEW_REQUIRED", "blockers": ["S6.q2:REVIEW_REQUIRED"]}}, "S6_REVIEW_REQUIRED"),
                ({"S6": {"status": "BLOCKED", "blockers": ["VIDEO_NOT_ALL_COMPLETED",
                                                          "LIVE_BOUND_TASK_TERMINAL_REMOTE_FAILURE:VU-3"]}},
                 "S6_BLOCKED"),
                ({"S6": {"status": "BLOCKED", "blockers": []}}, "S6_BLOCKED"),
                ({"S6": {"status": "HARD_STOP_BUDGET", "blockers": ["VIDEO_NOT_ALL_COMPLETED"]}},
                 "S6_HARD_STOP_BUDGET"),
                ({"S6": {"status": "PASS"}, "S7": {"status": "SKIPPED"}}, "STAGES_PASS:S6..S7")):
            out = prs.classify({"stages": stages}, "S6", "S7")
            self.assertEqual((out["verdict"], out["reason"]), (prs.ACT, reason), stages)

    def test_record_prints_one_next_line_and_rejects_a_stale_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            started = time.time()
            _state(runtime, "E08", S6_WAIT)
            rec = prs.record(runtime, "E08", "S6", "S6", 1, "/x.log", started)
            self.assertEqual(rec["verdict"], prs.WAIT)
            self.assertTrue(prs.next_line(rec).startswith("NEXT: END_TURN_WAIT_FOR_TICK"))
            stale = prs.record(runtime, "E08", "S6", "S6", 1, "/x.log", time.time() + 60)
            self.assertEqual((stale["verdict"], stale["reason"]), (prs.ACT, "PIPELINE_STATE_NOT_UPDATED_BY_THIS_RUN"))
            self.assertTrue(prs.next_line(stale).startswith("NEXT: ACT"))

    def test_status_is_a_few_short_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            _state(runtime, "E08", {**S6_WAIT, "S6": {**S6_WAIT["S6"], "details": {"missing_videos": ["a", "b"]}}})
            prs.record(runtime, "E08", "S6", "S6", 1, "/x.log", time.time() - 5)
            logs = runtime / "runtime" / "pipeline_logs" / "E08"
            logs.mkdir(parents=True)
            (logs / "run_1.log").write_text("x" * 500 + "\n" + "[t] $ video_q2_builder.py " + "y" * 900 + "\n")
            lines = prs.status_lines(runtime, "E08")
            self.assertLessEqual(len(lines), 12)
            self.assertTrue(all(len(line) <= prs.LINE_MAX for line in lines), lines)
            self.assertEqual(lines[0], "paid run: none active")
            self.assertIn("S6 missing videos: 2", lines)
            self.assertTrue(lines[-1].startswith("NEXT: END_TURN_WAIT_FOR_TICK"))
            lock = runtime / "runtime" / ".paid_E08.lock"
            lock.mkdir()
            (lock / "pid").write_text(str(os.getpid()))
            self.assertTrue(prs.status_lines(runtime, "E08")[0].startswith("paid run: ACTIVE"))


class TickDecisionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = Path(self.tmp.name)
        _state(self.runtime, "E08", S6_WAIT)
        self.rec = prs.record(self.runtime, "E08", "S6", "S6", 1, "/x.log", time.time() - 5)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_waits_reruns_then_caps(self) -> None:
        now = self.rec["finished_at"]
        decide = lambda **kw: prs.tick_decision(self.runtime, "E08", since=now - 100, **kw)  # noqa: E731
        self.assertEqual(decide(reruns_done=0, now=now + 10)["action"], "BACKOFF")
        due = decide(reruns_done=0, now=now + 241)
        self.assertEqual((due["action"], due["from"], due["until"]), ("RERUN", "S6", "S6"))
        self.assertEqual(decide(reruns_done=90, now=now + 241)["action"], "RESUME")
        self.assertEqual(prs.tick_decision(self.runtime, "E08", since=now + 1, reruns_done=0)["action"], "NO_RECORD")
        lock = self.runtime / "runtime" / ".paid_E08.lock"
        lock.mkdir()
        (lock / "pid").write_text(str(os.getpid()))
        self.assertEqual(decide(reruns_done=0)["action"], "IN_FLIGHT")

    def test_actionable_record_resumes(self) -> None:
        _state(self.runtime, "E08", {"S6": {"status": "REVIEW_REQUIRED", "blockers": ["x"]}})
        prs.record(self.runtime, "E08", "S6", "S6", 1, "/x.log", time.time() - 5)
        out = prs.tick_decision(self.runtime, "E08", since=None, reruns_done=0)
        self.assertEqual((out["action"], out["reason"]), ("RESUME", "S6_REVIEW_REQUIRED"))


FAKE_PY = r"""#!/bin/bash
case "$1" in
  */paid_run_status.py) exec python3 "$@" ;;
  */hopsapi_image_client.py|*/hopsapi_video_client.py) echo giggle; exit 0 ;;
  */nalu_budget_ledger.py) echo "budget ok"; exit 0 ;;
  */nalu_pipeline.py) shift; exec python3 "$FAKE_PIPELINE" "$@" ;;
  -) cat >/dev/null; exit 0 ;;
  -c) echo "$NALU_LATEST_ORDER_SEQ"; exit 0 ;;
esac
exit 0
"""

FAKE_PIPELINE = r"""
import json, os, sys
from pathlib import Path
for i in range(200):
    print(f"[t] step line {i} " + "z" * 600)
state = Path(os.environ["NALU_RUNTIME_ROOT"]) / "runtime" / "pipeline_state" / "E08.json"
state.parent.mkdir(parents=True, exist_ok=True)
stages = {"S6": {"status": "BLOCKED", "blockers": ["VIDEO_NOT_ALL_COMPLETED"]}} if os.environ.get("FAKE_MODE") == "wait" \
    else {"S6": {"status": "PASS"}}
state.write_text(json.dumps({"stages": stages}))
print("===== E08 status =====")
sys.exit(1 if os.environ.get("FAKE_MODE") == "wait" else 0)
"""


class PaidStageOutputTest(unittest.TestCase):
    """paid_stage.sh end to end with a fake interpreter: no provider, no key, no spend."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.runtime = root / "runtime"
        (self.runtime / "runtime").mkdir(parents=True)
        fake = root / "fakepy"
        fake.write_text(FAKE_PY)
        fake.chmod(0o755)
        (root / "pipeline.py").write_text(FAKE_PIPELINE)
        orders = root / "orders.json"
        orders.write_text(json.dumps({"latest_order_seq": 7, "orders": []}))
        self.env = {"PATH": os.environ["PATH"], "HOME": str(root), "NALU_VENV_PYTHON": str(fake),
                    "FAKE_PIPELINE": str(root / "pipeline.py"), "GIGGLE_API_KEY": "test-not-a-key",
                    "NALU_PAID_ORDER_SEQ": "7", "NALU_LATEST_ORDER_SEQ": "7", "NALU_RUNTIME_ROOT": str(self.runtime),
                    "NALU_ENGINE_ROOT": str(ROOT), "NALU_SUPERVISOR_ORDERS_PATH": str(orders),
                    "NALU_LINE_OWNER_ID": "owner", "NALU_IMAGE_PROVIDER": "giggle"}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_stage(self, *args: str, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["/bin/bash", str(TOOLS / "paid_stage.sh"), *args], capture_output=True, text=True,
                              env={**self.env, **extra}, timeout=120)

    def test_waiting_stage_prints_a_tail_and_ends_the_turn(self) -> None:
        out = self.run_stage("E08", "S6", "S6", FAKE_MODE="wait")
        lines = out.stdout.strip().splitlines()
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertTrue(lines[-1].startswith("NEXT: END_TURN_WAIT_FOR_TICK"), lines[-3:])
        self.assertLessEqual(len(out.stdout.encode()), 16_000)            # 200 x 600-char lines streamed before
        self.assertTrue(all(len(line) <= 400 for line in lines))
        self.assertIn("earlier lines only in the full log", out.stdout)
        log = next(line.split("full log: ", 1)[1] for line in lines if "full log: " in line)
        self.assertEqual(len(Path(log).read_text().splitlines()), 201)   # the full output is kept
        self.assertEqual(prs.last_record(self.runtime, "E08")["verdict"], prs.WAIT)
        status = self.run_stage("--status", "E08")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("last paid run: S6..S6 rc=1", status.stdout)

    def test_passing_stage_acts(self) -> None:
        out = self.run_stage("E08", "S6", "S6", FAKE_MODE="pass")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.strip().splitlines()[-1].startswith("NEXT: ACT (STAGES_PASS:S6..S6)"))

    def test_a_second_run_while_one_is_in_flight_ends_the_turn(self) -> None:
        lock = self.runtime / "runtime" / ".paid_E08.lock"
        lock.mkdir()
        (lock / "pid").write_text(str(os.getpid()))
        out = self.run_stage("E08", "S6", "S6", FAKE_MODE="wait")
        self.assertEqual(out.returncode, 4)
        self.assertTrue(out.stdout.strip().splitlines()[-1].startswith("NEXT: END_TURN_WAIT_FOR_TICK"))


class CompactPipelineOutputTest(unittest.TestCase):
    def test_compact_mode_prints_stage_lines_only_and_logs_everything(self) -> None:
        import nalu_pipeline as np_  # noqa: PLC0415
        saved = np_.COMPACT_OUTPUT
        np_.COMPACT_OUTPUT = True
        try:
            with tempfile.TemporaryDirectory() as tmp:
                ctx = SimpleNamespace(run_log=Path(tmp) / "run.log")
                buf = io.StringIO()
                with redirect_stdout(buf):
                    for line in ("$ python tools/video_q2_builder.py --episode E08", "\n-- S6 video",
                                 "   S6 => BLOCKED   blockers: VIDEO_NOT_ALL_COMPLETED", "  -> exit=0 log=x.log"):
                        np_.Ctx.log(ctx, line)
                printed = buf.getvalue()
                self.assertIn("-- S6 video", printed)
                self.assertIn("S6 => BLOCKED", printed)
                self.assertNotIn("video_q2_builder", printed)
                self.assertIn("video_q2_builder", ctx.run_log.read_text())
        finally:
            np_.COMPACT_OUTPUT = saved


class ShortBriefingTest(unittest.TestCase):
    @staticmethod
    def brief(n_rules: int = 120) -> dict:
        rules, memory = [], []
        for i in range(1, n_rules + 1):
            status = "GUIDANCE_ONLY" if i % 10 == 0 else "REFERENCE_IMPLEMENTATION"
            stage = "S2" if i % 3 == 0 else "S6"
            rules.append({"id": f"K{i:03d}", "stage": stage, "status": status, "rule": "规则正文" * 40,
                          "do_not_repeat": f"不要犯第{i}类错误" + "，细节" * 10})
            memory.append({"failure_code": f"CODE_{i}", "do_not_repeat": f"不要犯第{i}类错误", "stage": stage,
                           "knowledge_id": f"K{i:03d}"})
        return {"episode": "E08", "line": "nalu", "registry_version": "1", "rule_count": n_rules,
                "context": {"rules": rules}, "failure_memory": memory}

    def test_short_briefing_fits_and_selects(self) -> None:
        text = lug.briefing_short_markdown(self.brief(), "/r/E08_KNOWLEDGE_BRIEFING.md")
        self.assertLessEqual(len(text.encode("utf-8")), lug.SHORT_BRIEFING_MAX_BYTES)
        self.assertIn("/r/E08_KNOWLEDGE_BRIEFING.md", text)               # look-ups go to the full file
        rules_part, causes = text.split("## Failure causes", 1)
        # unenforced rules: authoring stages first, newest first
        self.assertLess(rules_part.index("- K120 [S2]"), rules_part.index("- K090 [S2]"))
        self.assertLess(rules_part.index("- K030 [S2]"), rules_part.index("- K110 [S6]"))
        self.assertNotIn("K119", rules_part)                              # enforced rules stay out of this part
        stages = [line.split("[", 1)[1].split("]", 1)[0] for line in causes.splitlines() if line.startswith("- K")]
        self.assertEqual(stages, sorted(stages, key=lambda st: st != "S2"))   # authoring causes first
        self.assertTrue(causes.splitlines()[1].startswith("- K117 `CODE_117`"), causes[:200])
        self.assertNotIn("`CODE_120`", causes)                            # already listed as an unenforced rule
        self.assertIn("more in the full briefing", text)

    def test_preflight_writes_the_short_file_and_the_real_registry_fits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            receipt = lug.preflight("nalu", "E08", Path(tmp), ROOT)
            short = Path(receipt["knowledge"]["briefing_short_md"])
            self.assertTrue(short.name.endswith("E08_KNOWLEDGE_BRIEFING_SHORT.md"))
            self.assertLessEqual(len(short.read_bytes()), lug.SHORT_BRIEFING_MAX_BYTES)
            self.assertIn(receipt["knowledge"]["briefing_md"], short.read_text(encoding="utf-8"))


class ContractTest(unittest.TestCase):
    def test_contract_and_adapter_forbid_wait_loops(self) -> None:
        import codex_production as cp  # noqa: PLC0415
        contract = (ROOT / "skills/nalu-claude-code/CLAUDE_CODE_PRODUCTION.md").read_text(encoding="utf-8")
        for needle in ("NEXT: END_TURN_WAIT_FOR_TICK", "paid_stage.sh --status", "_KNOWLEDGE_BRIEFING_SHORT.md",
                       "20 KB", "pgrep"):
            self.assertIn(needle, contract)
        self.assertNotIn("sleep 240", contract)
        self.assertNotIn("sleep 600", contract)
        self.assertNotIn("sleep 240", cp.CODEX_ADAPTER)
        self.assertIn("END_TURN_WAIT_FOR_TICK", cp.CODEX_ADAPTER)


if __name__ == "__main__":
    unittest.main()
