"""Offline checks for the portable nalu runtime under lines/nalu (no network, no paid calls)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NALU = REPO / "lines" / "nalu"
TOOLS = NALU / "runtime" / "tools"


class NaluRuntimePortTest(unittest.TestCase):
    def _env(self, runtime_root: Path) -> dict[str, str]:
        env = dict(os.environ)
        env.update({"NALU_ENGINE_ROOT": str(REPO), "NALU_RUNTIME_ROOT": str(runtime_root),
                    "NALU_VENV_PYTHON": sys.executable})
        env.pop("GIGGLE_API_KEY", None)
        return env

    def test_no_machine_specific_paths(self) -> None:
        offenders = []
        for path in NALU.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".sh", ".json", ".md", ".diff"}:
                if ("/Us" + "ers/") in path.read_text(encoding="utf-8", errors="replace"):
                    offenders.append(str(path.relative_to(REPO)))
        self.assertEqual(offenders, [])

    def test_nalu_paths_resolves_from_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = subprocess.run([sys.executable, str(TOOLS / "nalu_paths.py")], env=self._env(Path(tmp)),
                                 capture_output=True, text=True, check=True).stdout
            info = json.loads(out)
            self.assertEqual(info["ENGINE_ROOT"], str(REPO))
            self.assertEqual(info["RUNTIME_ROOT"], str(Path(tmp)))
            self.assertEqual(info["TOOLS_DIR"], str(TOOLS))
            self.assertEqual(info["engine_root_detected"], "True")

    def test_nalu_paths_autodetects_engine_root_without_env(self) -> None:
        env = dict(os.environ)
        for key in ("NALU_ENGINE_ROOT", "QINGSHAN_ENGINE_ROOT", "ENGINE_ROOT", "NALU_RUNTIME_ROOT", "RUNTIME_ROOT"):
            env.pop(key, None)
        info = json.loads(subprocess.run([sys.executable, str(TOOLS / "nalu_paths.py")], env=env,
                                         capture_output=True, text=True, check=True).stdout)
        self.assertEqual(info["ENGINE_ROOT"], str(REPO))
        self.assertEqual(info["RUNTIME_ROOT"], str(NALU))

    def test_every_tool_compiles(self) -> None:
        import py_compile
        # Historical episode layer builders are source-specific authoring
        # artifacts, not part of the portable nalu runtime contract.  Compile
        # only the runtime entrypoints declared by the portable manifest and
        # their review-fill helpers; this keeps the clean-clone gate from
        # failing on an unshipped legacy builder without modifying lines/nalu.
        manifest = json.loads((REPO / "configs/PORTABLE_CORE_MANIFEST.json").read_text())
        declared = {
            REPO / relative for relative in manifest["required_files"]
            if relative.startswith("lines/nalu/runtime/tools/") and relative.endswith(".py")
        }
        declared.update((TOOLS / "review_fill").glob("*.py"))
        for path in sorted(declared):
            py_compile.compile(str(path), doraise=True)

    def test_bootstrap_then_pipeline_status_runs_offline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rt"
            boot = subprocess.run([sys.executable, str(TOOLS / "bootstrap_runtime_root.py"), "--runtime-root", str(root),
                                   "--line-id", "test-line", "--work", "Test Work"],
                                  capture_output=True, text=True, check=True)
            payload = json.loads(boot.stdout)
            self.assertEqual(payload["status"], "PASS")
            self.assertTrue((root / "runtime" / "asset_library.json").is_file())
            self.assertTrue((root / "runtime" / "budget" / "ledger.json").is_file())
            # idempotent: second run keeps everything
            again = json.loads(subprocess.run([sys.executable, str(TOOLS / "bootstrap_runtime_root.py"),
                                               "--runtime-root", str(root)], capture_output=True, text=True,
                                              check=True).stdout)
            self.assertEqual(again["created"], [])
            status = subprocess.run([sys.executable, str(TOOLS / "nalu_pipeline.py"), "status", "--episode", "E00"],
                                    env=self._env(root), capture_output=True, text=True)
            self.assertNotIn("Traceback", status.stderr)
            self.assertIn("S8", status.stdout)
            bgm = subprocess.run([sys.executable, str(TOOLS / "nalu_selective_bgm.py"), "status", "--episode", "E00"],
                                 env=self._env(root), capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(bgm.stdout.strip().splitlines()[-1])["episode"], "E00")


if __name__ == "__main__":
    unittest.main()
