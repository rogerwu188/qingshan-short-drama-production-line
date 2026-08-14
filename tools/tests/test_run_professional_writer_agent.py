import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tools/run_professional_writer_agent.sh"


class ProfessionalWriterAgentRunnerTest(unittest.TestCase):
    def _fake_runtime(self, root: Path) -> Path:
        runtime = root / "writer"
        runtime.write_text(
            "#!/bin/sh\n"
            "if [ \"${1:-}\" = health ]; then exit 0; fi\n"
            "printf '%s\\n' \"$@\"\n",
            encoding="utf-8",
        )
        runtime.chmod(0o755)
        return runtime

    def test_generate_injects_supported_default_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self._fake_runtime(Path(tmp))
            env = os.environ.copy()
            env["QINGSHAN_WRITER_AGENT_BIN"] = str(runtime)
            proc = subprocess.run(
                [str(RUNNER), "generate", "--input", "brief.json"],
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
        self.assertIn("gpt-5.6-sol", proc.stdout.splitlines())

    def test_generate_preserves_explicit_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self._fake_runtime(Path(tmp))
            env = os.environ.copy()
            env["QINGSHAN_WRITER_AGENT_BIN"] = str(runtime)
            proc = subprocess.run(
                [str(RUNNER), "generate", "--input", "brief.json", "--model", "explicit-model"],
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
        values = proc.stdout.splitlines()
        self.assertIn("explicit-model", values)
        self.assertNotIn("gpt-5.6-sol", values)

    def test_version_alias_uses_cli_version_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self._fake_runtime(Path(tmp))
            env = os.environ.copy()
            env["QINGSHAN_WRITER_AGENT_BIN"] = str(runtime)
            proc = subprocess.run(
                [str(RUNNER), "version"],
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
        self.assertEqual(proc.stdout.splitlines(), ["--version"])


if __name__ == "__main__":
    unittest.main()
