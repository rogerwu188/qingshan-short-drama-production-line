#!/usr/bin/env python3
"""Tests for the import triage (CL2X-1039).

The case that matters is the one that started it: a module whose failure is a
failed assert, sitting in the same list as seventeen missing-package errors.
If those two ever come out the same again, one of these fails.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.test_import_triage import (  # noqa: E402
    CLASS_BROKEN,
    CLASS_OK,
    CLASS_OPTIONAL,
    CLASS_PROJECT_RUNTIME_ABSENT,
    classify,
    run,
)


ABSENT_OPTIONAL = "qs_definitely_not_installed"


class TestImportTriage(unittest.TestCase):
    def _fixture_dir(self, files: dict[str, str]) -> Path:
        import importlib
        import tempfile

        temp = Path(tempfile.mkdtemp())
        (temp / "__init__.py").write_text("", encoding="utf-8")
        for name, body in files.items():
            (temp / name).write_text(textwrap.dedent(body), encoding="utf-8")
        sys.path.insert(0, str(temp.parent))
        # Every fixture lands in the same tempdir root, and the import system
        # caches that directory's listing. Without this, the second test in a
        # run cannot see its own fixture package and every module in it comes
        # back PRODUCTION_IMPORT_BROKEN — a harness artefact that reads exactly
        # like the defect this file exists to detect. Caught only when the
        # module was run alongside others; alone it passed.
        importlib.invalidate_caches()
        return temp

    # A name guaranteed absent, so this file's verdict never depends on whether
    # the sandbox happened to be provisioned. Using a real optional package here
    # made the test flip with the environment — precisely the confusion the tool
    # under test exists to remove.
    ABSENT_OPTIONAL = ABSENT_OPTIONAL

    def test_the_two_states_do_not_render_the_same(self):
        temp = self._fixture_dir(
            {
                # Seventeen of these existed. They are noise.
                "test_needs_optional.py": f"import {ABSENT_OPTIONAL}\n",
                # One of these existed. It was a four-day production outage.
                "test_broken_assert.py": (
                    "RUNTIME = {'A'}\n"
                    "EXECUTORS = {'A': 1, 'B': 2}\n"
                    "assert RUNTIME == set(EXECUTORS), 'runtime gate list must match'\n"
                ),
                "test_fine.py": "VALUE = 1\n",
            }
        )
        report = run(temp, temp.name, optional=frozenset({self.ABSENT_OPTIONAL}))
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["counts"][CLASS_BROKEN], 1)
        self.assertEqual(report["counts"][CLASS_OPTIONAL], 1)
        self.assertEqual(report["counts"][CLASS_OK], 1)
        broken = report["production_import_broken"][0]
        self.assertTrue(broken["module"].endswith("test_broken_assert"))
        self.assertEqual(broken["error_type"], "AssertionError")
        # The distinguishing detail has to survive into the report.
        self.assertIn("runtime gate list must match", broken["detail"])
        self.assertEqual(report["missing_optional_deps"], [self.ABSENT_OPTIONAL])

    def test_missing_optional_dep_alone_is_pass(self):
        temp = self._fixture_dir({"test_only_optional.py": f"import {ABSENT_OPTIONAL}\n"})
        report = run(temp, temp.name, optional=frozenset({self.ABSENT_OPTIONAL}))
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["counts"][CLASS_BROKEN], 0)

    def test_unlisted_missing_module_is_a_code_defect_not_noise(self):
        """A typo'd import must not hide behind the optional-dep allowance."""
        temp = self._fixture_dir({"test_typo.py": "import tolls.nonexistent_thing\n"})
        report = run(temp, temp.name)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["production_import_broken"][0]["missing_package"], "tolls")

    def test_chained_optional_import_is_still_recognised(self):
        temp = self._fixture_dir(
            {
                "helper_mod.py": f"import {ABSENT_OPTIONAL}\n",
                "test_chained.py": "from . import helper_mod\n",
            }
        )
        report = run(temp, temp.name, optional=frozenset({self.ABSENT_OPTIONAL}))
        self.assertEqual(report["status"], "PASS")

    def test_real_repo_stage_gate_runner_imports(self):
        """The regression itself. Fails on the pre-1039 tree."""
        result = classify("tools.episode_stage_gate_runner")
        self.assertEqual(result["classification"], CLASS_OK, result)

    def test_project_built_runtime_is_its_own_state(self):
        """agentcut absent = unrun, not broken and not benign noise."""
        temp = self._fixture_dir({"test_agentcut_thing.py": "from agentcut import bgm\n"})
        report = run(temp, temp.name)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["counts"][CLASS_PROJECT_RUNTIME_ABSENT], 1)
        self.assertEqual(report["counts"][CLASS_BROKEN], 0)
        self.assertEqual(len(report["project_runtime_not_installed"]), 1)
        # It must not be silently folded into the ignorable dep list.
        self.assertEqual(report["missing_optional_deps"], [])

    def test_cli_exit_code_is_nonzero_only_for_broken(self):
        temp = self._fixture_dir({"test_broken2.py": "assert False, 'nope'\n"})
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "test_import_triage.py"),
             "--test-dir", str(temp), "--package", temp.name],
            capture_output=True, text=True, cwd=str(temp.parent),
        )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
