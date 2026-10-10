"""Every nalu tool resolves the same roots whichever shell starts it.

E11 (2026-10-09/10): without NALU_RUNTIME_ROOT the runtime root fell back to the engine
checkout's own lines/nalu (which ships another work's character registry) and Q1 recorded 26
identity P0s; three tools defaulted the work root to <runtime>/workflow/nalu while the pipeline
used <engine>/workflow/nalu.  A deployment now pins its roots once.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATHS = ROOT / "lines/nalu/runtime/tools/nalu_paths.py"


def _describe(env: dict) -> dict:
    out = subprocess.run([sys.executable, str(PATHS)], env=env, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


class DeploymentPinTests(unittest.TestCase):
    def _env(self, engine: Path) -> dict:
        env = {k: v for k, v in os.environ.items()
               if k not in ("NALU_RUNTIME_ROOT", "RUNTIME_ROOT", "NALU_WORK_ROOT", "QINGSHAN_VOICE_REGISTRY")}
        env["NALU_ENGINE_ROOT"] = str(engine)
        return env

    def test_the_pin_is_used_when_the_environment_is_silent(self):
        with tempfile.TemporaryDirectory() as e, tempfile.TemporaryDirectory() as r:
            engine, runtime = Path(e), Path(r)
            (runtime / "runtime").mkdir()
            env = self._env(engine)
            subprocess.run([sys.executable, str(PATHS), "pin", "--runtime-root", str(runtime)],
                           env=env, capture_output=True, text=True, check=True)
            info = _describe(env)
        self.assertEqual(info["RUNTIME_ROOT_SOURCE"], "deployment_pin")
        self.assertEqual(Path(info["RUNTIME_ROOT"]).resolve(), runtime.resolve())
        self.assertEqual(Path(info["WORK_ROOT"]), engine / "workflow" / "nalu")
        self.assertEqual(Path(info["VOICE_REGISTRY"]).resolve(),
                         (runtime / "runtime" / "voice_registry.json").resolve())

    def test_the_environment_still_wins_over_the_pin(self):
        with tempfile.TemporaryDirectory() as e, tempfile.TemporaryDirectory() as r, \
                tempfile.TemporaryDirectory() as other:
            engine, runtime = Path(e), Path(r)
            (runtime / "runtime").mkdir()
            env = self._env(engine)
            subprocess.run([sys.executable, str(PATHS), "pin", "--runtime-root", str(runtime)],
                           env=env, capture_output=True, text=True, check=True)
            info = _describe({**env, "NALU_RUNTIME_ROOT": other})
        self.assertEqual(info["RUNTIME_ROOT_SOURCE"], "environment")
        self.assertEqual(Path(info["RUNTIME_ROOT"]), Path(other))

    def test_pin_refuses_a_directory_that_is_not_a_runtime_root(self):
        with tempfile.TemporaryDirectory() as e, tempfile.TemporaryDirectory() as r:
            env = self._env(Path(e))
            out = subprocess.run([sys.executable, str(PATHS), "pin", "--runtime-root", r],
                                 env=env, capture_output=True, text=True)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("not a nalu runtime root", out.stderr + out.stdout)
        self.assertFalse((Path(e) / ".nalu_deployment.json").exists())


if __name__ == "__main__":
    unittest.main()
