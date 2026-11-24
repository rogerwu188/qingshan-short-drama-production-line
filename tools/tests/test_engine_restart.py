"""Restart the in-flight episode from S1 on a new engine (line owner rule 2026-11-23, engine_restart.py)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "nalu-claude-code" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import engine_restart as er  # noqa: E402
import fleet_sync  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def _write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class Fixture:
    """A tiny engine checkout (old HEAD, newer pin) + runtime with E16 in flight and E15 finished."""

    def __init__(self, d: Path, ep: str = "E16"):
        self.engine, self.runtime, self.archive = d / "engine", d / "runtime", d / "archive"
        self.ep = ep
        e, r = self.engine, self.runtime
        e.mkdir()
        _git(e, "init", "-q")
        _write(e / ".gitignore", "/workflow/*\n!/workflow/time_ledger/\n")
        _write(e / "workflow" / "time_ledger" / f"{ep}_time_ledger.json", "{}")   # tracked: never moved
        _git(e, "add", "-A")
        _git(e, "commit", "-qm", "old")
        self.old = _git(e, "rev-parse", "HEAD")
        _write(e / "NEW", "1")
        _git(e, "add", "-A")
        _git(e, "commit", "-qm", "new")
        self.pin = _git(e, "rev-parse", "HEAD")
        _git(e, "checkout", "-q", "--detach", self.old)
        # per-episode artefacts
        self.plate = _write(e / "workflow" / "nalu" / ep / "identity" / "plates" / "hero.png", "plate")
        _write(e / "workflow" / "nalu" / ep / "preproduction" / "x.json", "{}")
        _write(e / "workflow" / "nalu" / "E15" / "keep.json", "{}")
        _write(e / "workflow" / "tasks" / "giggle_video_submit_transactions" / ep / "t.json", "{}")
        _write(e / "workflow" / "tasks" / "giggle_bgm_transactions" / "SCOPE" / ep / "b.json", "{}")
        _write(e / "workflow" / "tasks" / "giggle_video_submit_transactions" / "E15" / "t.json", "{}")
        _write(e / "workflow" / "claude_writer_agent" / "scripts" / f"{ep}_GENERATION_CONTRACT_v1.json", "{}")
        _write(e / "workflow" / "claude_writer_agent" / "scripts" / "E15_GENERATION_CONTRACT_v1.json", "{}")
        _write(e / "workflow" / "claude_writer_agent" / "scripts" / "E160_NOT_OURS.md", "")
        rt = r / "runtime"
        _write(rt / "pipeline_state" / f"{ep}.json", "{}")
        _write(rt / "pipeline_state" / "approvals" / f"{ep}.APPROVED.json", "{}")
        _write(rt / "pipeline_state" / "E15.json", "{}")
        _write(rt / "paid_runs" / ep / "tick_rerun.out", "")
        _write(rt / "reviews" / ep / "final_audience_request.json", "{}")
        _write(rt / "reports" / f"{ep}_AUTHORING_GUIDANCE.json", "{}")
        _write(rt / "budget" / f"{ep}_cost_plan.json", "{}")
        _write(rt / "E01_ASSET_LIBRARY_V1.json", "{}")   # series seed: stays
        _write(rt / "asset_library.json", json.dumps({"assets": [{"path": str(self.plate)}]}))
        _write(rt / "budget" / "ledger.json", json.dumps({
            "schema": "nalu.episode_credit_budget_ledger_log.v1", "cap_credits_per_episode": 400,
            "entries": [{"episode": "E15", "recorded_total_credits": 200},
                        {"episode": ep, "recorded_total_credits": 120},
                        {"episode": ep, "recorded_total_credits": 230.5}]}))
        _write(r / "deliverables" / ep / "cut.mp4", "v")
        _write(r / "deliverables" / "E15" / "E15_final_9x16.mp4", "v")
        _write(r / "briefs" / f"{ep}_DISPATCH.md", "dispatch")
        _write(r / "briefs" / f"{ep}_PRODUCTION_BRIEF.json", "{}")
        _write(r / "series" / "CURRENT_EPISODE", ep + "\n")
        _write(r / "series" / "STATUS.md", "- start\n")
        log = _write(r / "claude_code" / ep / "run_1.jsonl", json.dumps(
            {"type": "result", "result": 'x\nNALU_STATUS: {"episode":"%s","state":"WAITING_REMOTE"}' % ep}) + "\n")
        _write(r / "claude_code" / ep / "session.json", json.dumps({"engine": "codex", "pid": None, "log": str(log)}))
        _write(r / "claude_code" / ep / "start_brief.md", "按派单生产")
        _write(r / "claude_code" / "E15" / "session.json", "{}")

    def env(self):
        return mock.patch.dict(os.environ, {"NALU_ENGINE_ROOT": str(self.engine), "NALU_RUNTIME_ROOT": str(self.runtime),
                                            "NALU_WORK_ROOT": str(self.engine / "workflow" / "nalu"),
                                            "NALU_ARCHIVE_ROOT": str(self.archive)})


class EngineRestartTest(unittest.TestCase):
    def test_selection_takes_only_this_episode_and_never_tracked_or_series_files(self):
        with tempfile.TemporaryDirectory() as d:
            f = Fixture(Path(d))
            with f.env():
                got = {str(p.relative_to(Path(d))) for p in er.select_paths(f.engine, f.runtime, "E16")}
        self.assertEqual(got, {
            "engine/workflow/nalu/E16",
            "engine/workflow/tasks/giggle_video_submit_transactions/E16",
            "engine/workflow/tasks/giggle_bgm_transactions/SCOPE/E16",
            "engine/workflow/claude_writer_agent/scripts/E16_GENERATION_CONTRACT_v1.json",
            "runtime/runtime/pipeline_state/E16.json",
            "runtime/runtime/pipeline_state/approvals/E16.APPROVED.json",
            "runtime/runtime/paid_runs/E16", "runtime/runtime/reviews/E16",
            "runtime/runtime/reports/E16_AUTHORING_GUIDANCE.json", "runtime/runtime/budget/E16_cost_plan.json",
            "runtime/deliverables/E16", "runtime/claude_code/E16"})

    def test_restart_archives_with_manifest_keeps_series_state_and_runs_once_per_pin(self):
        with tempfile.TemporaryDirectory() as d:
            f = Fixture(Path(d))
            with f.env(), mock.patch.object(er, "stop_episode", return_value={"stopped": [], "sigkill": []}):
                check = er.eligibility(f.engine, f.runtime, "E16", f.pin)
                self.assertTrue(check["eligible"], check)
                prep = er.prepare(f.engine, f.runtime, "E16", f.pin, device_sn="SN1")
                self.assertEqual(prep["phase"], "ARCHIVED")
                archive = Path(prep["archive"])
                self.assertTrue(archive.name.startswith("E16_abandoned_") and archive.name.endswith(f.old[:7]))
                manifest = json.loads((archive / "manifest.json").read_text())
                self.assertEqual(manifest["moved_count"], 12)
                self.assertTrue(all(row["status"] == "MOVED" for row in manifest["moved"]))
                # moved, never deleted
                self.assertTrue((archive / "engine/workflow/nalu/E16/preproduction/x.json").is_file())
                self.assertTrue((archive / "runtime/claude_code/E16/start_brief.md").is_file())
                self.assertFalse((f.runtime / "runtime/pipeline_state/E16.json").exists())
                # series-level state and earlier episodes stay
                for kept in ("engine/workflow/nalu/E15/keep.json", "engine/workflow/time_ledger/E16_time_ledger.json",
                             "runtime/runtime/E01_ASSET_LIBRARY_V1.json", "runtime/briefs/E16_DISPATCH.md",
                             "runtime/runtime/pipeline_state/E15.json", "runtime/deliverables/E15/E15_final_9x16.mp4",
                             "engine/workflow/claude_writer_agent/scripts/E160_NOT_OURS.md"):
                    self.assertTrue((Path(d) / kept).is_file(), kept)
                self.assertTrue((archive / "runtime/briefs/E16_DISPATCH.md").is_file())   # copy for the record
                # the plate the series library points at is back in place (and in the archive)
                self.assertEqual(f.plate.read_text(), "plate")
                self.assertIn(str(f.plate), manifest["restored_for_series_registries"])
                # ledger: history kept, abandoned attempt under its own key, episode reset to 0
                entries = json.loads((f.runtime / "runtime/budget/ledger.json").read_text())["entries"]
                self.assertEqual(len(entries), 5)
                self.assertEqual(entries[3]["episode"], prep["ledger"]["abandoned_key"])
                self.assertEqual(entries[3]["recorded_total_credits"], 230.5)
                self.assertEqual((entries[4]["episode"], entries[4]["recorded_total_credits"]), ("E16", 0))
                last = {}
                for row in entries:
                    last[row["episode"]] = row["recorded_total_credits"]
                self.assertEqual(sum(last.values()), 200 + 230.5)   # fleet total neither loses nor doubles it
                # setup moved the engine; the start uses the engine on disk
                _git(f.engine, "checkout", "-q", "--detach", f.pin)
                with mock.patch.object(er, "start_fresh", return_value={"status": "STARTED", "pid": 9}) as start:
                    fin = er.finish(f.engine, f.runtime, "E16", f.pin)
                self.assertEqual((fin["phase"], fin["new_engine"]), ("STARTED", f.pin))
                self.assertEqual(start.call_args[0][4], f.old)
                self.assertIn(f"E16 restarted on {f.pin[:7]} (owner rule: restart on major engine change)",
                              (f.runtime / "series/STATUS.md").read_text())
                # idempotent: at most once per (episode, pin), and an engine with the change never restarts
                _git(f.engine, "checkout", "-q", "--detach", f.old)
                _write(f.runtime / "claude_code/E16/session.json", "{}")
                again = er.prepare(f.engine, f.runtime, "E16", f.pin)
                self.assertEqual((again["phase"], again["reason"]), ("SKIPPED", "ALREADY_RESTARTED:STARTED"))
                self.assertEqual(er.finish(f.engine, f.runtime, "E16", f.pin)["phase"], "STARTED")  # no 2nd start
                start.assert_called_once()

    def test_restart_brief_keeps_the_dispatch_and_points_at_the_archive(self):
        with tempfile.TemporaryDirectory() as d:
            f = Fixture(Path(d))
            with f.env(), mock.patch.object(er, "stop_episode", return_value={"stopped": [], "sigkill": []}):
                prep = er.prepare(f.engine, f.runtime, "E16", f.pin)
                text = er.restart_brief(f.engine, f.runtime, "E16", Path(prep["archive"]), f.old, f.pin, "K")
        self.assertIn("从 S1 从头重做", text)
        self.assertIn(prep["archive"], text)
        self.assertIn("E16_DISPATCH.md", text)
        self.assertIn("按派单生产", text)   # the original start brief, for reference

    def test_eligibility_refuses_finished_foreign_and_already_upgraded_episodes(self):
        with tempfile.TemporaryDirectory() as d:
            f = Fixture(Path(d))
            with f.env():
                self.assertEqual(er.eligibility(f.engine, f.runtime, "E15", f.pin)["reason"],
                                 "NOT_CURRENT_EPISODE:E16")
                self.assertEqual(er.eligibility(f.engine, f.runtime, "E16", "nope")["reason"], "BAD_PIN")
                # the engine already contains the major commit (e.g. the episode started after it)
                self.assertEqual(er.eligibility(f.engine, f.runtime, "E16", f.pin, major=f.old)["reason"],
                                 "ENGINE_ALREADY_HAS_THE_CHANGE")
                log = f.runtime / "claude_code/E16/run_1.jsonl"
                log.write_text(json.dumps({"type": "result", "result": 'NALU_STATUS: {"state":"FINAL_CUT_READY"}'}))
                self.assertEqual(er.eligibility(f.engine, f.runtime, "E16", f.pin)["reason"],
                                 "EPISODE_DONE:FINAL_CUT_READY")

    def test_process_selection_is_the_episode_and_its_children_only(self):
        me = os.getpid()
        table = {
            1: (0, "/sbin/init"),
            me: (1, "python3 codex_production.py tick --system"),
            100: (1, "python3 codex_production.py _run --episode E16 --log x"),
            101: (100, "node /usr/bin/codex exec --json -o /h/nalu_runtime/claude_code/E16/run.last.txt -"),
            102: (101, "bash -lc sleep 5"),
            200: (1, "/bin/bash lines/nalu/runtime/tools/paid_stage.sh E16 S6 S8"),
            201: (200, "python nalu_pipeline.py run --episode E16"),
            300: (1, "/bin/bash lines/nalu/runtime/tools/paid_stage.sh E160 S6 S8"),   # another episode id
            301: (1, "python nalu_pipeline.py run --episode E15"),
            400: (1, "vim E16_notes.md"),                                             # no marker
            500: (1, "python3 /tmp/nalu_engine_restart.py run --episode E16 --apply"),  # ourselves
            600: (1, "sleep 100"),
        }
        self.assertEqual(er.episode_processes("E16", [600], table), [100, 101, 102, 200, 201, 600])


class FleetUpdateRestartTest(unittest.TestCase):
    def test_restart_flag_archives_before_setup_and_starts_after(self):
        pin, calls, sha = "b" * 40, [], ["a" * 40]

        def fake_run(argv, timeout):
            calls.append(Path(argv[1]).name)
            if Path(argv[1]).name == "setup_host.sh":
                sha[0] = pin
            return 0, "NALU_SETUP: {}"

        cp = SimpleNamespace(roots=lambda: (Path("/nonexistent"), Path("/nonexistent")), current_episode=lambda: "E16")
        with mock.patch.object(fleet_sync, "_run", fake_run), \
                mock.patch.object(fleet_sync, "_engine_sha", lambda e: sha[0]), \
                mock.patch.object(fleet_sync, "_restart_prepare",
                                  side_effect=lambda cp_, p, m: calls.append(("prepare", p, m)) or
                                  {"phase": "ARCHIVED", "episode": "E16", "archive": "/a"}), \
                mock.patch.object(fleet_sync, "_restart_finish",
                                  side_effect=lambda cp_, ep, p: calls.append(("finish", ep, p)) or
                                  {"phase": "STARTED", "new_engine": pin}):
            ok, res, _ = fleet_sync.run_command(cp, {"type": "update", "payload": {
                "pin": pin, "restart_in_flight": True, "major": "c" * 40}})
            self.assertTrue(ok)
            self.assertEqual(calls, ["self_update.sh", ("prepare", pin, "c" * 40), "setup_host.sh",
                                     ("finish", "E16", pin)])
            self.assertEqual(res["restart"]["phase"], "STARTED")
            # without the explicit flag (or with a truthy non-True value) nothing is restarted
            calls.clear()
            sha[0] = "a" * 40
            cp.status = lambda ep: {"status": "RUNNING", "codex": {"nalu_status": {}}}
            fleet_sync.run_command(cp, {"type": "update", "payload": {"pin": pin, "restart_in_flight": "yes"}})
            self.assertEqual(calls, ["self_update.sh", "setup_host.sh"])


if __name__ == "__main__":
    unittest.main()
