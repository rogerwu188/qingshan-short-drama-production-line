from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "agent_factory" / "claude_writer" / "install.py"
SPEC = importlib.util.spec_from_file_location("claude_writer_install", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class ClaudeWriterPortableInstallTest(unittest.TestCase):
    def make_clone(self, base: Path) -> Path:
        clone = base / "clone"
        manifest = MODULE.load_manifest()
        paths = set(manifest["required_repository_files"])
        paths.add(manifest["source_skill"])
        paths.update(manifest["runtime_templates"].values())
        paths.add("agent_factory/claude_writer/package_manifest.json")
        for rel in paths:
            source = ROOT / rel
            destination = clone / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        return clone

    def test_clean_clone_install_and_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            clone = self.make_clone(base)
            scheduled = base / "Scheduled"
            result = MODULE.install(clone, scheduled)
            self.assertEqual(result["status"], "INSTALLED")
            report = MODULE.doctor(clone, scheduled)
            self.assertEqual(report["status"], "PASS", report)
            self.assertEqual(report["source_skill_sha256"], report["deployed_skill_sha256"])

    def test_install_preserves_existing_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            clone = self.make_clone(base)
            progress = clone / "workflow/claude_writer_agent/PROGRESS.json"
            progress.parent.mkdir(parents=True, exist_ok=True)
            progress.write_text('{"existing": true}\n', encoding="utf-8")
            result = MODULE.install(clone, base / "Scheduled")
            self.assertIn("workflow/claude_writer_agent/PROGRESS.json", result["runtime_preserved"])
            self.assertEqual(json.loads(progress.read_text(encoding="utf-8")), {"existing": True})

    def test_doctor_detects_skill_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            clone = self.make_clone(base)
            scheduled = base / "Scheduled"
            MODULE.install(clone, scheduled)
            deployed = scheduled / "qingshan-claude-writer-agent/SKILL.md"
            deployed.write_text("drift\n", encoding="utf-8")
            report = MODULE.doctor(clone, scheduled)
            self.assertIn("SCHEDULED_SKILL_SHA_MISMATCH", report["issues"])


if __name__ == "__main__":
    unittest.main()
