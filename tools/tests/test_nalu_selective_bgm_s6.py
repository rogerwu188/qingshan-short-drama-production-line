"""Offline regression tests for the S6-only selective-BGM provider boundary."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parents[2]
NALU_TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
BGM_TOOL = NALU_TOOLS / "nalu_selective_bgm.py"
PIPELINE = NALU_TOOLS / "nalu_pipeline.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SelectiveBgmS6Test(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.contract = root / "layers" / "E01_GENERATION_CONTRACT_v1.json"
        self.assembly = root / "work" / "assembly"
        self.grouping = root / "work" / "preproduction" / "E01_VIDEO_UNIT_GROUPING_PLAN_V1.json"
        self.project = self.assembly / "E01_agentcut_project.json"
        self.work = root / "work" / "preproduction" / "bgm"
        self.contract.parent.mkdir(parents=True)
        self.assembly.mkdir(parents=True)
        self.grouping.parent.mkdir(parents=True)
        self.work.mkdir(parents=True)
        self.contract.write_text(json.dumps({
            "audio_contract": {"bgm": {"mode": "SELECTIVE", "cues": [{
                "cue_id": "OPENING_DREAD",
                "shots": ["E01-S01-01"],
                "narrative_function": "OPENING_DREAD",
                "brief": "instrumental low strings, sparse percussion, no vocals",
                "volume": 0.14,
                "dialogue_duck_db": -8,
            }]}},
            "shots": [
                {"shot_id": "E01-S01-01", "scene_id": "E01-S01", "target_seconds": 5},
                {"shot_id": "E01-S01-02", "scene_id": "E01-S01", "target_seconds": 5},
                {"shot_id": "E01-S01-03", "scene_id": "E01-S01", "target_seconds": 5},
            ],
        }, ensure_ascii=False), encoding="utf-8")
        self.grouping.write_text(json.dumps({"units": [{
            "unit_id": "E01-VU-001",
            "editorial_shot_ids": ["E01-S01-01", "E01-S01-02", "E01-S01-03"],
        }]}), encoding="utf-8")
        (self.assembly / "E01_release_timeline.json").write_text(json.dumps({
            "content_runtime_seconds": 30,
            "segments": [{"unit_id": "E01-VU-001", "output_start": 0, "output_end": 15}],
        }), encoding="utf-8")
        (self.assembly / "E01_unit_asr.json").write_text("{}", encoding="utf-8")
        self.env = dict(os.environ)
        self.env.update({
            "NALU_ENGINE_ROOT": str(REPO),
            "NALU_RUNTIME_ROOT": str(root / "runtime"),
            "NALU_VENV_PYTHON": sys.executable,
        })
        self.env.pop("GIGGLE_API_KEY", None)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def argv(self, command: str, *extra: str) -> list[str]:
        return [sys.executable, str(BGM_TOOL), command, "--episode", "E01",
                "--contract", str(self.contract), "--assembly", str(self.assembly),
                "--grouping", str(self.grouping), "--project", str(self.project),
                "--work", str(self.work), *extra]

    def run_tool(self, command: str, *extra: str, check: bool = True) -> tuple[subprocess.CompletedProcess[str], dict]:
        run = subprocess.run(self.argv(command, *extra), env=self.env, capture_output=True, text=True)
        if check and run.returncode != 0:
            self.fail(f"{command} failed: stdout={run.stdout!r} stderr={run.stderr!r}")
        payload = json.loads(run.stdout.strip().splitlines()[-1]) if run.stdout.strip() else {}
        return run, payload

    def source_plan(self) -> dict:
        _, payload = self.run_tool("source-plan")
        self.assertEqual(payload["status"], "PASS")
        return json.loads((self.work / "E01_BGM_SOURCE_PLAN.json").read_text(encoding="utf-8"))

    def write_completed_transaction(self, plan: dict, tx_dir: Path | None = None) -> Path:
        generation = plan["generations"][0]
        candidate = self.work / generation["source_key"] / "bgm_candidate_1.mp3"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(b"offline-candidate")
        tx_path = (tx_dir or (self.work / "_transactions")) / f"{generation['source_key']}.json"
        tx_path.parent.mkdir(parents=True, exist_ok=True)
        tx_path.write_text(json.dumps({
            "schema": "qingshan.storyclaw_audio_transaction.v1",
            "state": "TERMINAL_COMPLETED",
            "task_id": "task-offline",
            "intent_recorded_at": "2026-09-20T00:00:00.100000Z",
            "task_id_bound_at": "2026-09-20T00:00:01.100000Z",
            "finished_at": "2026-09-20T00:01:00.100000Z",
            "request": {"prompt_sha256": generation["prompt_sha256"], "instrumental": True},
            "paid_authority": {"config_lock": "1", "authorization_ref": "order-7",
                               "order_seq": "7", "orders_sha256": "a" * 64},
            "result": {"status": "completed", "files": [{"path": str(candidate),
                                                               "sha256": sha(candidate),
                                                               "size": candidate.stat().st_size}]},
        }), encoding="utf-8")
        return tx_path

    def test_source_plan_and_dry_generate_need_no_timeline_or_network(self) -> None:
        (self.assembly / "E01_release_timeline.json").unlink()
        plan = self.source_plan()
        self.assertEqual(plan["timeline_dependency"], "NONE_S6_SOURCE_GENERATION")
        _, pending = self.run_tool("pending")
        self.assertEqual(pending["planned_credits"], 8)
        _, dry = self.run_tool("generate")
        self.assertEqual(dry["status"], "DRY_RUN")
        self.assertEqual(dry["planned_credits"], 8)
        self.assertFalse(any((self.work / "_transactions").glob("*.json")))

    def test_verify_and_timeline_plan_reuse_completed_provider_transaction(self) -> None:
        plan = self.source_plan()
        self.write_completed_transaction(plan)
        _, verified = self.run_tool("verify")
        self.assertEqual(verified["status"], "PASS")
        _, pending = self.run_tool("pending")
        self.assertEqual(pending["planned_credits"], 0)
        _, timeline_plan = self.run_tool("plan")
        self.assertEqual(timeline_plan["status"], "PASS")
        output = json.loads((self.assembly / "E01_BGM_PLAN.json").read_text(encoding="utf-8"))
        self.assertEqual(output["actual_cue_seconds"], 5)
        self.assertEqual(output["generations"][0]["coverage_seconds_required"], 5)
        self.assertEqual(output["source_plan_sha256"], sha(self.work / "E01_BGM_SOURCE_PLAN.json"))

    def test_verify_fails_closed_on_candidate_sha_or_stale_contract(self) -> None:
        plan = self.source_plan()
        tx_path = self.write_completed_transaction(plan)
        tx = json.loads(tx_path.read_text(encoding="utf-8"))
        Path(tx["result"]["files"][0]["path"]).write_bytes(b"tampered")
        run, payload = self.run_tool("verify", check=False)
        self.assertEqual(run.returncode, 2)
        self.assertEqual(payload["status"], "FAIL")
        self.assertIn("CANDIDATE_SHA256_MISMATCH", " ".join(payload["rows"][0]["failures"]))

        contract = json.loads(self.contract.read_text(encoding="utf-8"))
        contract["shots"][0]["target_seconds"] = 6
        self.contract.write_text(json.dumps(contract), encoding="utf-8")
        stale = subprocess.run(self.argv("pending"), env=self.env, capture_output=True, text=True)
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("source plan is stale", stale.stderr)

    def test_pending_counts_only_new_posts_and_blocks_unbound_response_loss(self) -> None:
        plan = self.source_plan()
        generation = plan["generations"][0]
        tx_path = self.work / "_transactions" / f"{generation['source_key']}.json"
        tx_path.parent.mkdir(parents=True, exist_ok=True)
        base = {
            "schema": "qingshan.storyclaw_audio_transaction.v1",
            "request": {"prompt_sha256": generation["prompt_sha256"], "instrumental": True},
            "paid_authority": {"config_lock": "1", "authorization_ref": "order-7",
                               "order_seq": "7", "orders_sha256": "a" * 64},
        }
        tx_path.write_text(json.dumps({**base, "state": "TASK_ID_BOUND_QUERY_PENDING",
                                       "task_id": "bound-task"}), encoding="utf-8")
        _, resumable = self.run_tool("pending")
        self.assertEqual(resumable["planned_credits"], 0)
        self.assertEqual(resumable["resume_without_post"], [generation["source_key"]])
        self.assertEqual(resumable["new_post_candidates"], [])

        tx_path.write_text(json.dumps({**base, "state": "RESPONSE_LOST"}), encoding="utf-8")
        blocked_run, blocked = self.run_tool("pending", check=False)
        self.assertEqual(blocked_run.returncode, 2)
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertIn("REQUIRES_RECONCILIATION", " ".join(blocked["blocked"][0]["failures"]))

    def test_same_e01_in_two_scopes_has_isolated_transactions_and_budget(self) -> None:
        plan = self.source_plan()
        root = Path(self.tmp.name) / "private" / "giggle_bgm_transactions"
        scope_a = (root / "SERIES_A" / "E01").resolve()
        scope_b = (root / "SERIES_B" / "E01").resolve()
        tx_a = self.write_completed_transaction(plan, scope_a)
        tx_payload = json.loads(tx_a.read_text(encoding="utf-8"))
        tx_payload["credit"] = {"net_charged_credits": 8, "statement_status": "PASS_CHARGED",
                                "isolation": "EXACT_PROJECT_ID"}
        tx_a.write_text(json.dumps(tx_payload), encoding="utf-8")

        _, pending_a = self.run_tool("pending", "--bgm-transactions-dir", str(scope_a))
        _, pending_b = self.run_tool("pending", "--bgm-transactions-dir", str(scope_b))
        self.assertEqual(pending_a["planned_credits"], 0)
        self.assertEqual(pending_b["planned_credits"], 8)
        self.assertEqual(pending_a["completed"], [plan["generations"][0]["source_key"]])
        self.assertEqual(pending_b["completed"], [])

        sys.path.insert(0, str(NALU_TOOLS))
        try:
            ledger = importlib.import_module("nalu_budget_ledger")
            a_spend = ledger.scan_non_video_spend("E01", bgm_transactions_dir=scope_a)
            b_spend = ledger.scan_non_video_spend("E01", bgm_transactions_dir=scope_b)
            self.assertEqual(a_spend["bgm_credits"], 8)
            self.assertEqual(b_spend["bgm_credits"], 0)
            self.assertEqual(a_spend["bgm_transactions_dir"], str(scope_a))
            self.assertEqual(b_spend["bgm_transactions_dir"], str(scope_b))
        finally:
            sys.path.remove(str(NALU_TOOLS))

    def test_submit_window_reconciliation_accepts_provider_fractional_timestamps(self) -> None:
        sys.path.insert(0, str(NALU_TOOLS))
        try:
            bgm = importlib.import_module("nalu_selective_bgm")
            report = bgm._window_isolated_ledger(
                {"source_key": "one", "task_id": "task-one",
                 "intent_recorded_at": "2026-09-20T00:00:00.100000Z",
                 "finished_at": "2026-09-20T00:00:10.900000Z"},
                [{"source_key": "one", "intent_recorded_at": "2026-09-20T00:00:00.100000Z",
                  "finished_at": "2026-09-20T00:00:10.900000Z"}],
                [{"created_at": "2026-09-20 00:00:00", "event_description": "Balance", "event_type": "Info",
                  "credit": 0},
                 {"created_at": "2026-09-20 00:00:02", "event_description": "GenerateMusic",
                  "event_type": "Pay", "credit": -8}],
            )
            self.assertEqual(report["status"], "PASS_CHARGED")
            self.assertEqual(report["net_charged_credits"], 8)
        finally:
            sys.path.remove(str(NALU_TOOLS))

    def test_paid_batch_stops_before_second_prompt_after_uncertain_first_result(self) -> None:
        contract = json.loads(self.contract.read_text(encoding="utf-8"))
        contract["audio_contract"]["bgm"]["cues"].append({
            "cue_id": "SECOND",
            "shots": ["E01-S01-02"],
            "narrative_function": "SECOND",
            "brief": "instrumental sparse wooden percussion, no vocals",
            "volume": 0.12,
            "dialogue_duck_db": -8,
        })
        self.contract.write_text(json.dumps(contract), encoding="utf-8")
        self.source_plan()
        tx_dir = (Path(self.tmp.name) / "private" / "SERIES_A" / "E01").resolve()
        sys.path.insert(0, str(NALU_TOOLS))
        try:
            bgm = importlib.import_module("nalu_selective_bgm")
            args = Namespace(
                episode="E01", contract=self.contract, assembly=self.assembly,
                grouping=self.grouping, project=self.project, work=self.work,
                bgm_transactions_dir=tx_dir, paid=True,
            )
            uncertain = subprocess.CompletedProcess(
                args=["provider"], returncode=2,
                stdout=json.dumps({"ok": False, "error": "provider response was lost"}) + "\n",
                stderr="",
            )
            with mock.patch.object(bgm.subprocess, "run", return_value=uncertain) as run:
                self.assertEqual(bgm.cmd_generate(args), 2)
            self.assertEqual(run.call_count, 1)
        finally:
            sys.path.remove(str(NALU_TOOLS))

    def test_pipeline_has_no_s7_generation_route(self) -> None:
        source = PIPELINE.read_text(encoding="utf-8")
        s6 = source.index("def s6_selective_bgm_sources")
        s7 = source.index("def stage_s7")
        end_s7 = source.index("# S7.qa", s7)
        self.assertIn('SELECTIVE_BGM, "generate"', source[s6:s7])
        self.assertNotIn('SELECTIVE_BGM, "generate"', source[s7:end_s7])
        self.assertNotIn("s7_bgm_generate", source)
        budget = source[source.index("def budget_check"):source.index("def planned_credits")]
        self.assertIn('"--bgm-transactions-dir", bgm_transactions', budget)

    def test_pipeline_current_policy_scopes_bgm_store_and_legacy_replay_does_not(self) -> None:
        sys.path.insert(0, str(NALU_TOOLS))
        previous = os.environ.get("NALU_POLICY_PROFILE")
        try:
            pipeline = importlib.import_module("nalu_pipeline")

            class FakePaths:
                scope = {"scope_id": "SERIES_A"}

            class FakeContext:
                episode = "E01"
                p = FakePaths()

            os.environ["NALU_POLICY_PROFILE"] = "CURRENT_PORTABLE"
            current = pipeline.selective_bgm_transaction_dir(FakeContext())
            self.assertEqual(current.parts[-3:], ("giggle_bgm_transactions", "SERIES_A", "E01"))
            self.assertEqual(current.parent.name, "SERIES_A")
            os.environ["NALU_POLICY_PROFILE"] = "LEGACY_EPISODE_COMPAT"
            legacy = pipeline.selective_bgm_transaction_dir(FakeContext())
            self.assertEqual(legacy.name, "E01")
            self.assertEqual(legacy.parent.name, "giggle_bgm_transactions")
        finally:
            if previous is None:
                os.environ.pop("NALU_POLICY_PROFILE", None)
            else:
                os.environ["NALU_POLICY_PROFILE"] = previous
            sys.path.remove(str(NALU_TOOLS))

    def test_budget_ledger_accepts_only_old_and_portable_completed_bgm_states(self) -> None:
        sys.path.insert(0, str(NALU_TOOLS))
        try:
            ledger = importlib.import_module("nalu_budget_ledger")
            original = ledger.ENGINE_ROOT
            engine = Path(self.tmp.name) / "ledger-engine"
            ledger.ENGINE_ROOT = engine
            tx_dir = engine / "workflow" / "tasks" / "giggle_bgm_transactions" / "E01"
            tx_dir.mkdir(parents=True)
            rows = {
                "legacy.json": {"state": "COMPLETED", "task_id": "old", "credit": {"net_charged_credits": 3}},
                "portable.json": {"state": "TERMINAL_COMPLETED", "task_id": "new", "credit": {"net_charged_credits": 8}},
                "pending.json": {"state": "TASK_ID_BOUND_QUERY_PENDING", "task_id": "wait",
                                 "credit": {"net_charged_credits": 99}},
            }
            for name, value in rows.items():
                (tx_dir / name).write_text(json.dumps(value), encoding="utf-8")
            report = ledger.scan_non_video_spend("E01")
            self.assertEqual(report["bgm_credits"], 11)
            self.assertEqual({row["task_id"] for row in report["bgm_rows"]}, {"old", "new"})
            self.assertEqual(report["bgm_provisional_credits"], 8)
            self.assertEqual({row["task_id"] for row in report["bgm_provisional_rows"]}, {"wait"})
            (tx_dir / "lost.json").write_text(
                json.dumps({"state": "RESPONSE_LOST"}), encoding="utf-8"
            )
            unresolved = ledger.scan_non_video_spend("E01")
            self.assertEqual(len(unresolved["bgm_unresolved_transactions"]), 1)
            self.assertEqual(unresolved["bgm_unresolved_transactions"][0]["state"], "RESPONSE_LOST")
        finally:
            ledger.ENGINE_ROOT = original
            sys.path.remove(str(NALU_TOOLS))


if __name__ == "__main__":
    unittest.main()
