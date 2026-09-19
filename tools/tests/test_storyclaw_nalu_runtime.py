import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import storyclaw_nalu_runtime as runtime


class StoryClawRuntimeTests(unittest.TestCase):
    def _root(self):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        (root / "qingshan_engine").mkdir()
        (root / "tools").mkdir()
        (root / "lines/nalu/runtime/tools").mkdir(parents=True)
        (root / "lines/nalu/runtime/tools/nalu_pipeline.py").write_text("", encoding="utf-8")
        (root / "lines/nalu/runtime/tools/nalu_paths.py").write_text("", encoding="utf-8")
        runtime_root = root / "runtime"
        runtime.init_runtime(root, runtime_root)
        return td, root, runtime_root

    def test_preflight_rejects_unapproved_model(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "qingshan_engine").mkdir()
            (root / "tools").mkdir()
            (root / "lines/nalu/runtime/tools").mkdir(parents=True)
            (root / "lines/nalu/runtime/tools/nalu_pipeline.py").write_text("", encoding="utf-8")
            (root / "lines/nalu/runtime/tools/nalu_paths.py").write_text("", encoding="utf-8")
            runtime_root = root / "runtime"
            runtime.init_runtime(root, runtime_root)
            cfg = runtime_root / "qingshan.json"
            data = json.loads(cfg.read_text())
            data["storyclaw"]["selected_model"] = "storyclaw/MiniMax-M2.7"
            cfg.write_text(json.dumps(data), encoding="utf-8")
            result = runtime.preflight(root, runtime_root)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("model", result["failures"])

    def test_paid_requires_two_config_locks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "qingshan_engine").mkdir()
            (root / "tools").mkdir()
            (root / "lines/nalu/runtime/tools").mkdir(parents=True)
            (root / "lines/nalu/runtime/tools/nalu_pipeline.py").write_text("", encoding="utf-8")
            (root / "lines/nalu/runtime/tools/nalu_paths.py").write_text("", encoding="utf-8")
            runtime_root = root / "runtime"
            runtime.init_runtime(root, runtime_root)
            with self.assertRaises(SystemExit) as ctx:
                runtime.run_episode(root, runtime_root, "E06", "S3", "S3", True, False)
            self.assertIn("paid requires both", str(ctx.exception))

    def test_run_rejects_unapproved_model_before_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "qingshan_engine").mkdir()
            (root / "tools").mkdir()
            (root / "lines/nalu/runtime/tools").mkdir(parents=True)
            (root / "lines/nalu/runtime/tools/nalu_pipeline.py").write_text("", encoding="utf-8")
            (root / "lines/nalu/runtime/tools/nalu_paths.py").write_text("", encoding="utf-8")
            runtime_root = root / "runtime"
            runtime.init_runtime(root, runtime_root)
            cfg = runtime_root / "qingshan.json"
            data = json.loads(cfg.read_text())
            data["storyclaw"]["selected_model"] = "storyclaw/MiniMax-M2.7"
            cfg.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(SystemExit) as ctx:
                runtime.run_episode(root, runtime_root, "E06", "S1", "S2", False, True)
            self.assertIn("GPT-6/Claude Opus allowlist", str(ctx.exception))

    def test_heartbeat_missing_state_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            result = runtime.heartbeat(Path(td), "E06")
            self.assertEqual(result["status"], "BLOCKED")

    def test_s3_requires_s1_pass(self):
        td, root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        with self.assertRaises(SystemExit) as ctx:
            runtime.run_episode(root, runtime_root, "E01", "S3", "S3", False, True)
        self.assertIn("S1 PASS", str(ctx.exception))

    def test_s3_requires_confirmed_asset_plan(self):
        td, root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        state = runtime_root / "runtime/pipeline_state/E01.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"stages": {"S1": {"status": "PASS"}}}), encoding="utf-8")
        with self.assertRaises(SystemExit) as ctx:
            runtime.run_episode(root, runtime_root, "E01", "S3", "S3", False, True)
        self.assertIn("confirmed script-derived asset matching plan", str(ctx.exception))

    def test_proposal_cannot_be_used_as_confirmation(self):
        td, root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        state = runtime_root / "runtime/pipeline_state/E01.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"stages": {"S1": {"status": "PASS"}}}), encoding="utf-8")
        source = runtime_root / "proposal.json"
        source.write_text(json.dumps({
            "character_matches": [],
            "unmatched_characters": [],
            "ai_generation_proposals": [],
        }), encoding="utf-8")
        path = runtime.record_asset_plan(runtime_root, "E01", source)
        self.assertEqual(json.loads(path.read_text())["status"], "PROPOSED")
        with self.assertRaises(SystemExit):
            runtime.run_episode(root, runtime_root, "E01", "S3", "S3", False, True)

    def test_confirmed_plan_allows_stage_guard_then_pipeline(self):
        td, root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        state = runtime_root / "runtime/pipeline_state/E01.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"stages": {"S1": {"status": "PASS"}}}), encoding="utf-8")
        source = runtime_root / "proposal.json"
        source.write_text(json.dumps({
            "character_matches": [],
            "unmatched_characters": [],
            "ai_generation_proposals": [],
        }), encoding="utf-8")
        runtime.record_asset_plan(runtime_root, "E01", source)
        receipt = runtime_root / "confirmation.json"
        receipt.write_text(json.dumps({"status": "CONFIRMED", "episode": "E01"}), encoding="utf-8")
        runtime.confirm_asset_plan(runtime_root, "E01", receipt)
        with patch.object(runtime.subprocess, "run") as run:
            run.return_value.returncode = 0
            result = runtime.run_episode(root, runtime_root, "E01", "S3", "S3", False, True)
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
