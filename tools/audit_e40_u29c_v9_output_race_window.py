#!/usr/bin/env python3
"""Audit the pinned U29C V9 output wrapper for local TOCTOU exposure.

This is a static, zero-side-effect production-safety audit.  It never invokes
the provider-facing toolchain and writes one immutable JSON result with an
exclusive create.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V9_INVOKER = ROOT / "tools/run_e40_u29c_v8_contained_capability_gate.py"
V9_INVOKER_SHA256 = "060af931b433227ab1afb7a14777f8f806f42fffe53bee68804c48bee8108ba3"
PINNED_V8_INVOKER = ROOT / "tools/run_e40_u29c_v6_pinned_capability_gate.py"
PINNED_V8_INVOKER_SHA256 = "5678c70075143cd86ea038e798720cff92b0fe28a5389214a23184c18c589964"
VALIDATOR = ROOT / "tools/validate_e40_u29c_v6_capability_contract.py"
VALIDATOR_SHA256 = "ebf2275931a09cd51dbb00af8268959faea62e1885b5b3a24be11d6c00fd87e5"
OUTPUT_ROOT = ROOT / "qa/e40_preproduction_20260808/u29c_v10_output_race_window_audit_v1"
DEFAULT_OUTPUT = OUTPUT_ROOT / "E40_U29C_V10_OUTPUT_RACE_WINDOW_AND_ATOMIC_RESERVATION_CONTRACT_V1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def call_name(node: ast.Call) -> str:
    parts: list[str] = []
    value: ast.AST = node.func
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def call_lines(tree: ast.AST, wanted: set[str]) -> dict[str, list[int]]:
    found = {name: [] for name in wanted}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = call_name(node)
            if name in found:
                found[name].append(node.lineno)
    return {name: sorted(lines) for name, lines in found.items()}


def write_exclusive(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    output = Path(args.out).expanduser()
    if not output.is_absolute():
        output = ROOT / output
    if output != DEFAULT_OUTPUT:
        raise SystemExit("OUTPUT_PATH_NOT_PINNED")

    actual_shas = {
        "v9_invoker": digest(V9_INVOKER),
        "pinned_v8_invoker": digest(PINNED_V8_INVOKER),
        "validator": digest(VALIDATOR),
    }
    expected_shas = {
        "v9_invoker": V9_INVOKER_SHA256,
        "pinned_v8_invoker": PINNED_V8_INVOKER_SHA256,
        "validator": VALIDATOR_SHA256,
    }
    pin_failures = [name for name in expected_shas if actual_shas[name] != expected_shas[name]]

    v9_source = V9_INVOKER.read_text(encoding="utf-8")
    validator_source = VALIDATOR.read_text(encoding="utf-8")
    v9_calls = call_lines(
        ast.parse(v9_source),
        {
            "output.exists",
            "output.is_symlink",
            "subprocess.run",
            "os.open",
            "os.replace",
        },
    )
    validator_calls = call_lines(
        ast.parse(validator_source),
        {
            "output.with_suffix",
            "temporary.write_text",
            "temporary.replace",
            "os.open",
        },
    )

    existence_lines = sorted(v9_calls["output.exists"] + v9_calls["output.is_symlink"])
    launch_lines = v9_calls["subprocess.run"]
    check_precedes_launch = bool(existence_lines and launch_lines and max(existence_lines) < min(launch_lines))
    has_atomic_reservation = bool(v9_calls["os.open"] and "O_EXCL" in v9_source and "O_NOFOLLOW" in v9_source)
    child_path_write = bool(
        validator_calls["output.with_suffix"]
        and validator_calls["temporary.write_text"]
        and validator_calls["temporary.replace"]
    )
    race_window_found = check_precedes_launch and not has_atomic_reservation and child_path_write

    failures: list[str] = []
    if pin_failures:
        failures.append("PINNED_INPUT_SHA_MISMATCH")
    if not race_window_found:
        failures.append("EXPECTED_CHECK_THEN_CREATE_RACE_NOT_PROVEN")

    status = "PASS_AUDIT_RACE_WINDOW_FOUND_FAIL_CLOSED_NO_SUBMIT" if not failures else "FAIL"
    report = {
        "schema": "qingshan.e40.u29c.v10.output_race_window_atomic_reservation_contract.v1",
        "episode": "E40",
        "unit_id": "U29C",
        "recorded_at": utc_now(),
        "status": status,
        "execution_permitted": False,
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "pinned_inputs": {
            "v9_invoker": {
                "path": str(V9_INVOKER.relative_to(ROOT)),
                "expected_sha256": V9_INVOKER_SHA256,
                "actual_sha256": actual_shas["v9_invoker"],
            },
            "pinned_v8_invoker": {
                "path": str(PINNED_V8_INVOKER.relative_to(ROOT)),
                "expected_sha256": PINNED_V8_INVOKER_SHA256,
                "actual_sha256": actual_shas["pinned_v8_invoker"],
            },
            "validator": {
                "path": str(VALIDATOR.relative_to(ROOT)),
                "expected_sha256": VALIDATOR_SHA256,
                "actual_sha256": actual_shas["validator"],
            },
        },
        "static_evidence": {
            "v9_output_exists_check_lines": v9_calls["output.exists"],
            "v9_output_symlink_check_lines": v9_calls["output.is_symlink"],
            "v9_subprocess_launch_lines": launch_lines,
            "v9_os_open_lines": v9_calls["os.open"],
            "v9_contains_o_excl": "O_EXCL" in v9_source,
            "v9_contains_o_nofollow": "O_NOFOLLOW" in v9_source,
            "validator_output_with_suffix_lines": validator_calls["output.with_suffix"],
            "validator_temporary_write_lines": validator_calls["temporary.write_text"],
            "validator_temporary_replace_lines": validator_calls["temporary.replace"],
            "check_precedes_child_launch": check_precedes_launch,
            "atomic_destination_reservation_present": has_atomic_reservation,
            "child_opens_and_replaces_path_after_parent_check": child_path_write,
            "race_window_found": race_window_found,
        },
        "finding": {
            "code": "OUTPUT_CHECK_TO_CREATE_TOCTOU",
            "severity": "HARD_FAIL_CLOSED",
            "description": (
                "V9 checks destination absence, then launches a child which later creates a sibling .part "
                "path and replaces the destination. A competing local process can change the destination or "
                "directory entry between the parent check and the child's path-based commit."
            ),
        },
        "atomic_reservation_contract": {
            "status": "REQUIRED_BEFORE_ANY_FUTURE_EXECUTION",
            "requirements": [
                "Open the fixed output root as a directory file descriptor with O_DIRECTORY and O_NOFOLLOW; bind and recheck its st_dev and st_ino.",
                "Reserve the final basename atomically with dir_fd plus O_CREAT|O_EXCL|O_NOFOLLOW and mode 0600; retain the open descriptor.",
                "Record a reservation ownership token from fstat (st_dev, st_ino) and require the lexical directory entry to match it without following symlinks.",
                "Run the pinned validator only in a newly created private 0700 staging directory; never pass the reserved final pathname to the child.",
                "After validator success, parse and verify the staged JSON, then write bytes through the retained reservation descriptor, fsync the file, and fsync the output-root directory.",
                "Never replace or reopen the reserved final path. On failure, unlink only when the directory entry still matches the retained ownership token.",
                "Reject output-root identity drift, destination hard links, pre-existing entries, symlinks, pin drift, parse failure, or any competing reservation.",
            ],
            "required_negative_tests": [
                "two concurrent invocations competing for the same basename: exactly one reserves and the other rejects before child execution",
                "destination substitution after reservation: token mismatch rejects without touching the substituted entry",
                "output-root swap or symlink replacement: directory identity mismatch rejects",
                "child failure or malformed JSON: reservation cleanup is ownership-token guarded and no completed gate is exposed",
            ],
        },
        "failures": failures,
        "side_effects": {
            "provider_calls": 0,
            "transactions": 0,
            "credits": 0,
            "retries": 0,
            "agentcut": 0,
            "assembly": 0,
        },
        "next_action": (
            "Keep execution closed. Implement a separately pinned hardened writer satisfying the atomic "
            "reservation contract, then run the required local competing-reservation negatives."
        ),
    }
    write_exclusive(output, report)
    print(json.dumps({"status": status, "out": str(output), "failures": failures}, ensure_ascii=False))
    return 0 if status.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
