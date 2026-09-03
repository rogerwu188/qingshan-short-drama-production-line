#!/usr/bin/env python3
"""Clean-clone CI for the supported reusable engine core.

Historical episode tests deliberately remain outside this contract because
their source media, paid-provider receipts and private runtime state are not
part of the MIT repository.
"""

from __future__ import annotations

import json
import py_compile
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "configs" / "PORTABLE_CORE_MANIFEST.json"
BANNED_PERSONAL_PATHS = ("/Users/rogerwu", "/private/tmp/", "/var/folders/")


def main() -> int:
    failures: list[str] = []
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    required = [ROOT / value for value in manifest.get("required_files") or []]
    for path in required:
        if not path.is_file():
            failures.append(f"MISSING_REQUIRED_FILE:{path.relative_to(ROOT)}")
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = ""
        for banned in BANNED_PERSONAL_PATHS:
            if banned in content:
                failures.append(
                    f"PERSONAL_PATH_IN_PORTABLE_CORE:{path.relative_to(ROOT)}:{banned}"
                )
        if path.suffix == ".py":
            try:
                py_compile.compile(str(path), doraise=True)
            except py_compile.PyCompileError as exc:
                failures.append(f"PY_COMPILE_FAILED:{path.relative_to(ROOT)}:{exc}")

    for relative in (
        "agent_factory/claude_writer/runtime_templates/SUPERVISOR_ORDERS.json",
        "agent_factory/claude_writer_v2/state/SUPERVISOR_ORDERS.json",
    ):
        state = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        if state.get("latest_order_seq") != 0 or state.get("orders") != []:
            failures.append(f"NONEMPTY_PUBLIC_WRITER_STATE:{relative}")

    audience_template = (
        ROOT / "agent_factory/claude_writer_v2/state/观众已知清单.md"
    ).read_text(encoding="utf-8")
    if "尚无已发行剧集" not in audience_template:
        failures.append("NONEMPTY_PUBLIC_AUDIENCE_KNOWLEDGE_STATE")

    for path in sorted((ROOT / "configs").rglob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"INVALID_JSON:{path.relative_to(ROOT)}:{exc}")

    for path in sorted((ROOT / "agent_factory" / "claude_writer_v2" / "schemas").glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"INVALID_SCHEMA_JSON:{path.relative_to(ROOT)}:{exc}")

    test_command = [sys.executable, "-m", "unittest", *(manifest.get("portable_test_modules") or [])]
    tests = subprocess.run(test_command, cwd=ROOT, check=False)
    if tests.returncode:
        failures.append(f"PORTABLE_TESTS_FAILED:{tests.returncode}")

    report = {
        "schema": "qingshan.portable_ci.v1",
        "status": "FAIL" if failures else "PASS",
        "required_file_count": len(required),
        "test_module_count": len(manifest.get("portable_test_modules") or []),
        "failures": failures,
        "note": "Legacy episode replay tests require separately supplied runtime evidence and are not clean-clone tests.",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
