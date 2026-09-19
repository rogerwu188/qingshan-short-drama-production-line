import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import storyclaw_nalu_runtime as runtime


class StoryClawRuntimeTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
