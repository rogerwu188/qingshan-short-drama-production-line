#!/usr/bin/env python3
"""Validate that every registered production gate has executable evidence."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path


REQUIRED = {
    "gate_id",
    "stage",
    "implementation_type",
    "code_paths",
    "test_paths",
    "parameters",
    "authorization_ref",
    "last_backtest_date",
}

CODED_REQUIRED = {
    "stage_runner_paths",
}

LIVE_PREFIXES = ("build_", "compile_", "episode_", "submit_")
BLOCKING_MARKERS = ("BLOCK_SUBMIT", "FAIL_CLOSED", "FAIL_HARD")


def declared_runtime_gate_ids(path: Path) -> set[str]:
    """Read the runner's literal runtime contract without importing production code."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return set()
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "RUNTIME_GATE_IDS" for target in targets):
            continue
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "frozenset" and value.args:
            value = value.args[0]
        if not isinstance(value, (ast.Set, ast.List, ast.Tuple)):
            return set()
        return {
            item.value
            for item in value.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
    return set()


def declared_runtime_gate_bindings(path: Path) -> dict[str, str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "RUNTIME_GATE_BINDINGS" for target in targets):
            continue
        if not isinstance(node.value, ast.Dict):
            return {}
        result: dict[str, str] = {}
        for key, value in zip(node.value.keys, node.value.values):
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                result[key.value] = value.value
        return result
    return {}


def called_function_names(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def imported_tool_modules(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[-1])
        elif isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[-1] for alias in node.names)
    return modules


def live_unregistered_blockers(registry: dict, base: Path) -> list[str]:
    """Find gate/guard modules that can block live builders but lack registry authority."""
    declared = {
        path
        for gate in registry.get("gates", [])
        for path in (gate.get("code_paths") or [])
    }
    tools_dir = base / "tools"
    live_callers = [
        path for path in tools_dir.glob("*.py")
        if path.name.startswith(LIVE_PREFIXES)
    ]
    imported_by_live: dict[str, list[str]] = {}
    for caller in live_callers:
        for module in imported_tool_modules(caller):
            imported_by_live.setdefault(module, []).append(str(caller.relative_to(base)))
    failures: list[str] = []
    for path in sorted(tools_dir.glob("*.py")):
        if not (path.stem.endswith("_gate") or path.stem.endswith("_guard")):
            continue
        callers = imported_by_live.get(path.stem) or []
        if not callers:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not any(marker in text for marker in BLOCKING_MARKERS):
            continue
        relative = str(path.relative_to(base))
        if relative not in declared:
            failures.append(
                f"UNREGISTERED_BLOCKER_IN_LIVE_PATH:{relative}:callers={','.join(sorted(callers))}"
            )
    return failures


def executable_runtime_gate_ids(path: Path) -> set[str]:
    declared = declared_runtime_gate_ids(path)
    calls = called_function_names(path)
    if path.name == "episode_stage_gate_runner.py":
        return declared if "execute_gate" in calls else set()
    bindings = declared_runtime_gate_bindings(path)
    return {
        gate_id
        for gate_id in declared
        if bindings.get(gate_id) in calls
    }


def validate(registry: dict, base: Path) -> dict:
    failures: list[str] = []
    seen: set[str] = set()
    gates = registry.get("gates", [])
    runner_contracts: dict[str, set[str]] = {}
    if not gates:
        failures.append("registry_has_no_gates")
    for gate in gates:
        gate_id = gate.get("gate_id", "UNKNOWN")
        missing = sorted(REQUIRED - set(gate))
        failures.extend(f"missing_field:{gate_id}:{field}" for field in missing)
        if gate_id in seen:
            failures.append(f"duplicate_gate_id:{gate_id}")
        seen.add(gate_id)
        gate_type = gate.get("implementation_type")
        if gate_type == "CODED":
            coded_missing = sorted(CODED_REQUIRED - set(gate))
            failures.extend(
                f"missing_coded_field:{gate_id}:{field}" for field in coded_missing
            )
            if not gate.get("code_paths"):
                failures.append(f"coded_gate_missing_code:{gate_id}")
            if not gate.get("test_paths"):
                failures.append(f"coded_gate_missing_tests:{gate_id}")
            runners = gate.get("stage_runner_paths") or []
            if not runners:
                failures.append(f"coded_gate_missing_stage_runner:{gate_id}")
            for path in gate.get("code_paths", []) + gate.get("test_paths", []) + runners:
                if not (base / path).is_file():
                    failures.append(f"missing_path:{gate_id}:{path}")
            actual_runners = []
            for runner in runners:
                runner_path = base / runner
                ids = runner_contracts.setdefault(
                    runner, executable_runtime_gate_ids(runner_path)
                )
                if gate_id in ids:
                    actual_runners.append(runner)
            if not actual_runners:
                failures.append(f"coded_gate_orphaned_from_runtime:{gate_id}")
        elif gate_type == "MANUAL_GATE":
            checklist = gate.get("manual_checklist_path")
            if not checklist:
                failures.append(f"manual_gate_missing_checklist:{gate_id}")
            elif not (base / checklist).is_file():
                failures.append(f"missing_path:{gate_id}:{checklist}")
        else:
            failures.append(f"invalid_implementation_type:{gate_id}:{gate_type}")
    runtime_bindings = {
        gate.get("gate_id", "UNKNOWN"): [
            runner
            for runner in gate.get("stage_runner_paths") or []
            if gate.get("gate_id") in runner_contracts.get(runner, set())
        ]
        for gate in gates
        if gate.get("implementation_type") == "CODED"
    }
    failures.extend(live_unregistered_blockers(registry, base))
    return {
        "schema": "qingshan.gate_registry_integrity_report.v1",
        "status": "PASS" if not failures else "FAIL",
        "gate_count": len(gates),
        "coded_gate_count": len(runtime_bindings),
        "runtime_bindings": runtime_bindings,
        "runtime_bound_count": sum(bool(value) for value in runtime_bindings.values()),
        "failures": failures,
    }


def run_registered_tests(registry: dict, base: Path) -> list[str]:
    failures: list[str] = []
    paths = sorted(
        {
            path
            for gate in registry.get("gates", [])
            for path in gate.get("test_paths", [])
        }
    )
    for path in paths:
        module = path[:-3].replace("/", ".") if path.endswith(".py") else path
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", module],
            cwd=base,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            failures.append(f"registered_test_failed:{path}")
    return failures


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--run-tests", action="store_true")
    args = parser.parse_args()
    registry_path = Path(args.registry).resolve()
    base = Path(__file__).resolve().parents[1]
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    report = validate(registry, base)
    if args.run_tests and report["status"] == "PASS":
        report["failures"].extend(run_registered_tests(registry, base))
        report["status"] = "PASS" if not report["failures"] else "FAIL"
    write_report(Path(args.out), report)
    print(json.dumps({"status": report["status"], "failures": report["failures"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
