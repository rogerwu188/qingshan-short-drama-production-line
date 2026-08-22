import tempfile
import unittest
from pathlib import Path

from tools.gate_registry_v3_check import live_unregistered_blockers, validate, write_report


def coded_gate():
    return {
        "gate_id": "G1",
        "stage": "CI",
        "implementation_type": "CODED",
        "code_paths": ["code.py"],
        "test_paths": ["test.py"],
        "parameters": {},
        "authorization_ref": "AUTH",
        "last_backtest_date": "2026-07-16",
        "stage_runner_paths": ["runner.py"],
    }


class GateRegistryV3Tests(unittest.TestCase):
    def test_reverse_scan_rejects_live_unregistered_blocker(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "tools").mkdir()
            (base / "tools/example_guard.py").write_text(
                'def check():\n    return "FAIL_CLOSED"\n', encoding="utf-8"
            )
            (base / "tools/build_example.py").write_text(
                'from example_guard import check\ncheck()\n', encoding="utf-8"
            )
            failures = live_unregistered_blockers({"gates": []}, base)
            self.assertEqual(len(failures), 1)
            self.assertIn("UNREGISTERED_BLOCKER_IN_LIVE_PATH:tools/example_guard.py", failures[0])

    def test_reverse_scan_accepts_registered_live_blocker(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "tools").mkdir()
            (base / "tools/example_guard.py").write_text(
                'def check():\n    return "BLOCK_SUBMIT"\n', encoding="utf-8"
            )
            (base / "tools/submit_example.py").write_text(
                'from example_guard import check\ncheck()\n', encoding="utf-8"
            )
            registry = {"gates": [{"code_paths": ["tools/example_guard.py"]}]}
            self.assertEqual(live_unregistered_blockers(registry, base), [])

    def test_passes_coded_and_manual_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            for name in ("code.py", "test.py", "check.json"):
                (base / name).write_text("{}", encoding="utf-8")
            (base / "runner.py").write_text(
                'RUNTIME_GATE_IDS = frozenset({"G1"})\n'
                'RUNTIME_GATE_BINDINGS = {"G1": "run_g1"}\n'
                'def run_g1(): pass\n'
                'run_g1()\n',
                encoding="utf-8",
            )
            manual = {
                **coded_gate(),
                "gate_id": "G2",
                "implementation_type": "MANUAL_GATE",
                "code_paths": [],
                "test_paths": [],
                "manual_checklist_path": "check.json",
            }
            report = validate({"gates": [coded_gate(), manual]}, base)
            self.assertEqual(report["status"], "PASS")

    def test_rejects_missing_test_and_checklist(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "code.py").write_text("", encoding="utf-8")
            gate = coded_gate()
            report = validate({"gates": [gate]}, base)
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("missing_path:G1:test.py", report["failures"])

    def test_rejects_coded_gate_without_stage_runner(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            for name in ("code.py", "test.py"):
                (base / name).write_text("", encoding="utf-8")
            gate = coded_gate()
            gate.pop("stage_runner_paths")
            report = validate({"gates": [gate]}, base)
            self.assertEqual(report["status"], "FAIL")
            self.assertIn(
                "missing_coded_field:G1:stage_runner_paths", report["failures"]
            )
            self.assertIn("coded_gate_missing_stage_runner:G1", report["failures"])

    def test_rejects_declared_runner_that_does_not_execute_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            for name in ("code.py", "test.py"):
                (base / name).write_text("", encoding="utf-8")
            (base / "runner.py").write_text(
                'RUNTIME_GATE_IDS = frozenset({"SOME_OTHER_GATE"})\n', encoding="utf-8"
            )
            report = validate({"gates": [coded_gate()]}, base)
            self.assertEqual(report["status"], "FAIL")
            self.assertIn(
                "coded_gate_orphaned_from_runtime:G1", report["failures"]
            )

    def test_rejects_binding_name_that_is_never_called(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            for name in ("code.py", "test.py"):
                (base / name).write_text("", encoding="utf-8")
            (base / "runner.py").write_text(
                'RUNTIME_GATE_IDS = frozenset({"G1"})\n'
                'RUNTIME_GATE_BINDINGS = {"G1": "run_g1"}\n'
                'def run_g1(): pass\n',
                encoding="utf-8",
            )
            report = validate({"gates": [coded_gate()]}, base)
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("coded_gate_orphaned_from_runtime:G1", report["failures"])

    def test_report_writer_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "nested" / "report.json"
            write_report(path, {"status": "PASS"})
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
