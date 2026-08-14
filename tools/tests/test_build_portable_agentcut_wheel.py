import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools/build_portable_agentcut_wheel.py"
SPEC = importlib.util.spec_from_file_location("portable_agentcut_wheel", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class PortableAgentCutWheelTest(unittest.TestCase):
    def test_wheel_contains_complete_importable_runtime(self):
        source = MODULE.find_source_package(ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / "agentcut-0.9.16-py3-none-any.whl"
            MODULE.build_wheel(source, wheel)
            with zipfile.ZipFile(wheel) as archive:
                names = set(archive.namelist())
            self.assertIn("agentcut/release_gate.py", names)
            self.assertIn("agentcut/engine.py", names)

            env = os.environ.copy()
            env["PYTHONPATH"] = str(wheel)
            runtime_python = source.parents[3] / "bin/python3"
            self.assertTrue(runtime_python.is_file())
            subprocess.run(
                [
                    str(runtime_python),
                    "-c",
                    "import agentcut; "
                    "from agentcut.release_gate import validate_release_output; "
                    "from agentcut.engine import AgentCutEngine",
                ],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [str(runtime_python), "-m", "agentcut", "--help"],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

    def test_bootstrap_verifies_import_and_cli(self):
        script = (ROOT / "tools/bootstrap_cloud_agentcut_runtime.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("--system-site-packages", script)
        self.assertIn("candidate\" -c 'import requests'", script)
        self.assertIn("from agentcut.release_gate import validate_release_output", script)
        self.assertIn("-m agentcut --help", script)


if __name__ == "__main__":
    unittest.main()
