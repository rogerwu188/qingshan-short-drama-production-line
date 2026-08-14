#!/usr/bin/env python3
"""Bounded recovery/reader/contention matrix for the U29C V20 writer."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as base  # noqa: E402
import run_e40_u29c_v20_post_link_recovery_publish_gate as writer  # noqa: E402


WRITER = ROOT / "tools/run_e40_u29c_v20_post_link_recovery_publish_gate.py"
WRITER_SHA256 = "6b61cf37134e1a3a2fa16f95140db82efaf5fe164a52e5373ed324890cde227e"
V19_AUDIT = ROOT / "qa/e40_preproduction_20260808/u29c_v19_atomic_link_exception_safety_audit_v1/E40_U29C_V19_ATOMIC_LINK_EXCEPTION_SAFETY_AUDIT_V1.json"
V19_AUDIT_SHA256 = "5b872fe948e6516bbfa571dd135fd8e02216800658a87a0c9f2ade8155b76ca5"
V20_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v20_post_link_recovery_writer_v1/E40_U29C_V20_POST_LINK_OUTCOME_RECOVERY_WRITER_SPEC_V1.json"
V20_SPEC_SHA256 = "576a3eef1621100fe656c9aba2ca79781ddfc8bc41ae160d9379a33eda116bbd"
REPORT = ROOT / "qa/e40_preproduction_20260808/u29c_v20_post_link_recovery_writer_v1/E40_U29C_V20_POST_LINK_RECOVERY_BOUNDED_MATRIX_V1.json"
CANONICAL = writer.FINAL_ROOT / "E40_U29C_V20_CANONICAL_RECOVERY_GATE_V1.json"
READER_NAME = "E40_U29C_V20_READER_SAFE_GATE_V1.json"
SHARED_NAME = "E40_U29C_V20_SHARED_RECOVERY_CONTENTION_GATE_V1.json"
CONTENDERS = 8
MAX_WORKERS = 4


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def valid_public(path: Path) -> bool:
    try:
        payload = path.read_bytes()
        report = base.validate_report_bytes(payload)
        value = os.stat(path, follow_symlinks=False)
    except (OSError, base.GateError):
        return False
    return bool(payload) and stat.S_ISREG(value.st_mode) and value.st_nlink == 1 and report.get("execution_permitted") is False


def root_identity(path: Path) -> list[int]:
    value = os.stat(path, follow_symlinks=False)
    return [value.st_dev, value.st_ino, stat.S_IMODE(value.st_mode)]


def stage_entries() -> list[str]:
    return sorted(path.name for path in writer.STAGING_ROOT.iterdir())


def hidden_entries() -> list[str]:
    return sorted(path.name for path in writer.FINAL_ROOT.iterdir() if path.name.startswith(".u29c-v20-hidden-"))


def reader_case() -> dict[str, Any]:
    target = writer.FINAL_ROOT / READER_NAME
    process = subprocess.Popen([sys.executable, str(WRITER), "--output-name", READER_NAME], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, close_fds=True)
    observations: list[bool] = []
    while process.poll() is None:
        if target.exists() or target.is_symlink():
            observations.append(valid_public(target))
        time.sleep(0.001)
    stdout, stderr = process.communicate()
    observations.append(valid_public(target))
    result = json.loads(stdout) if process.returncode == 0 else {}
    return {
        "case_id": "READER_ONLY_OBSERVES_COMPLETE_PUBLICATION",
        "passed": process.returncode == 0 and observations and all(observations) and valid_public(target) and result.get("post_link_recovered") is False,
        "returncode": process.returncode,
        "stderr": stderr.strip(),
        "observation_count": len(observations),
        "all_observations_valid": all(observations),
    }


def fixture_case(base_path: Path, name: str, action: Callable[[base.RootBinding, Path], dict[str, Any]]) -> dict[str, Any]:
    path = base_path / name
    binding = base.open_bound_root(path)
    try:
        return action(binding, path)
    finally:
        os.close(binding.fd)


def malformed_case(binding: base.RootBinding, path: Path) -> dict[str, Any]:
    error = None
    try:
        writer.publish_complete_payload(binding, "public.json", b"{bad-json")
    except base.GateError as exc:
        error = str(exc)
    entries = sorted(item.name for item in path.iterdir())
    return {"case_id": "MALFORMED_PRE_LINK_NO_PUBLICATION", "passed": error == "STAGED_REPORT_INVALID_JSON" and entries == [], "error": error, "entries_after": entries}


def write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        size = os.write(fd, view)
        if size <= 0:
            raise RuntimeError("FIXTURE_WRITE_FAILED")
        view = view[size:]


def competitor_case(binding: base.RootBinding, path: Path, payload: bytes) -> dict[str, Any]:
    sentinel = b"COMPETITOR_PRESERVED\n"
    fd = os.open("public.json", base.create_flags(), 0o600, dir_fd=binding.fd)
    try:
        write_all(fd, sentinel)
        os.fsync(fd)
    finally:
        os.close(fd)
    error = None
    try:
        writer.publish_complete_payload(binding, "public.json", payload)
    except base.GateError as exc:
        error = str(exc)
    entries = sorted(item.name for item in path.iterdir())
    preserved = (path / "public.json").read_bytes() == sentinel
    return {"case_id": "COMPETING_PUBLIC_PRESERVED_NOT_RECOVERED", "passed": error == "PUBLICATION_TARGET_EXISTS" and preserved and entries == ["public.json"], "error": error, "competitor_preserved": preserved, "entries_after": entries}


def post_link_fsync_case(binding: base.RootBinding, path: Path, payload: bytes) -> dict[str, Any]:
    original = writer.os.fsync
    fired = False
    def inject(fd: int) -> None:
        nonlocal fired
        if fd == binding.fd and not fired:
            fired = True
            raise OSError("INJECTED_POST_LINK_FSYNC")
        original(fd)
    writer.os.fsync = inject
    try:
        report, recovered, cause = writer.publish_complete_payload(binding, "public.json", payload)
    finally:
        writer.os.fsync = original
    entries = sorted(item.name for item in path.iterdir())
    return {"case_id": "POST_LINK_FSYNC_FAILURE_RECOVERED_EXACT_OWNED_INODE", "passed": fired and recovered and cause == "OSError" and report.get("execution_permitted") is False and valid_public(path / "public.json") and entries == ["public.json"], "injected": fired, "recovered": recovered, "recovery_cause": cause, "entries_after": entries}


def cleanup_interrupt_case(binding: base.RootBinding, path: Path, payload: bytes) -> dict[str, Any]:
    original = writer.cleanup_owned_hidden
    calls = 0
    def inject(hidden: base.HiddenInode) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("INJECTED_CLEANUP_INTERRUPT")
        return original(hidden)
    writer.cleanup_owned_hidden = inject
    try:
        report, recovered, cause = writer.publish_complete_payload(binding, "public.json", payload)
    finally:
        writer.cleanup_owned_hidden = original
    entries = sorted(item.name for item in path.iterdir())
    return {"case_id": "OWNED_HIDDEN_CLEANUP_INTERRUPT_RECOVERED", "passed": calls == 2 and recovered and cause == "OSError" and report.get("execution_permitted") is False and valid_public(path / "public.json") and entries == ["public.json"], "cleanup_calls": calls, "recovered": recovered, "recovery_cause": cause, "entries_after": entries}


def run_contender(index: int) -> dict[str, Any]:
    completed = subprocess.run([sys.executable, str(WRITER), "--output-name", SHARED_NAME], cwd=ROOT, capture_output=True, text=True, close_fds=True, check=False)
    return {"contender": index, "returncode": completed.returncode, "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()}


def contention_case() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="u29c-v20") as executor:
        futures = [executor.submit(run_contender, index) for index in range(1, CONTENDERS + 1)]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item["contender"])
    winners = [item for item in results if item["returncode"] == 0]
    losers = [item for item in results if item["returncode"] == 1 and item["stderr"] == "PUBLICATION_TARGET_EXISTS"]
    target = writer.FINAL_ROOT / SHARED_NAME
    return ({"case_id": "EIGHT_SAME_BASENAME_ONE_WINNER_SEVEN_PRESERVED_LOSERS", "passed": len(winners) == 1 and len(losers) == 7 and valid_public(target), "winner_count": len(winners), "publication_target_exists_loser_count": len(losers), "public_valid": valid_public(target)}, results)


def substitution_case() -> dict[str, Any]:
    results = []
    for flag in ["--validator", "--contract", "--final-root", "--staging-root"]:
        name = f"E40_U29C_V20_REJECT_{flag[2:].replace('-', '_').upper()}.json"
        completed = subprocess.run([sys.executable, str(WRITER), "--output-name", name, flag, "/tmp/forbidden"], cwd=ROOT, capture_output=True, text=True, close_fds=True, check=False)
        results.append({"flag": flag, "returncode": completed.returncode, "output_absent": not (writer.FINAL_ROOT / name).exists()})
    return {"case_id": "CALLER_SUBSTITUTIONS_REJECTED_BEFORE_CHILD", "passed": all(item["returncode"] == 2 and item["output_absent"] for item in results), "results": results}


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, base.create_flags(), 0o600)
    try:
        data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
        write_all(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> int:
    if REPORT.exists() or REPORT.is_symlink():
        raise SystemExit("REPORT_ALREADY_EXISTS")
    if not valid_public(CANONICAL):
        raise SystemExit("CANONICAL_OUTPUT_INVALID")
    for name in [READER_NAME, SHARED_NAME]:
        if (writer.FINAL_ROOT / name).exists() or (writer.FINAL_ROOT / name).is_symlink():
            raise SystemExit(f"OUTPUT_ALREADY_EXISTS_{name}")
    pins = [WRITER, V19_AUDIT, V20_SPEC]
    expected = {str(WRITER.relative_to(ROOT)): WRITER_SHA256, str(V19_AUDIT.relative_to(ROOT)): V19_AUDIT_SHA256, str(V20_SPEC.relative_to(ROOT)): V20_SPEC_SHA256}
    pins_before = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    roots_before = {"final": root_identity(writer.FINAL_ROOT), "staging": root_identity(writer.STAGING_ROOT)}
    stage_before, hidden_before = stage_entries(), hidden_entries()
    payload = CANONICAL.read_bytes()
    with tempfile.TemporaryDirectory(prefix=".u29c-v20-matrix-", dir=writer.QA_EPISODE_ROOT) as temporary:
        fixture = Path(temporary)
        cases = [
            {"case_id": "NORMAL_CANONICAL_COMPLETE", "passed": valid_public(CANONICAL), "sha256": digest(CANONICAL)},
            reader_case(),
            fixture_case(fixture, "malformed", malformed_case),
            fixture_case(fixture, "competitor", lambda binding, path: competitor_case(binding, path, payload)),
            fixture_case(fixture, "post-link-fsync", lambda binding, path: post_link_fsync_case(binding, path, payload)),
            fixture_case(fixture, "cleanup-interrupt", lambda binding, path: cleanup_interrupt_case(binding, path, payload)),
        ]
    contention, contention_results = contention_case()
    cases.extend([contention, substitution_case()])
    pins_after = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    roots_after = {"final": root_identity(writer.FINAL_ROOT), "staging": root_identity(writer.STAGING_ROOT)}
    stage_after, hidden_after = stage_entries(), hidden_entries()
    failures = [case["case_id"] for case in cases if not case["passed"]]
    failures.extend(name for name, value in expected.items() if pins_before.get(name) != value)
    if pins_before != pins_after: failures.append("PINNED_INPUT_MUTATION")
    if roots_before != roots_after: failures.append("ROOT_IDENTITY_OR_MODE_DRIFT")
    if stage_before or stage_after or hidden_before or hidden_after: failures.append("HIDDEN_OR_STAGE_RESIDUE_NONZERO")
    status = "PASS_POST_LINK_OWNED_INODE_RECOVERY_READER_CONTENTION_ZERO_RESIDUE_NO_SUBMIT" if not failures else "FAIL"
    report = {"schema":"qingshan.e40.u29c.v20.post_link_recovery_bounded_matrix.v1","episode":"E40","unit_id":"U29C","recorded_at":stamp(),"status":status,"execution_permitted":False,"provider_post_allowed":False,"maximum_new_submissions":0,"bounded_load":{"contenders":CONTENDERS,"maximum_workers":MAX_WORKERS},"pins_before":pins_before,"pins_after":pins_after,"roots_before":roots_before,"roots_after":roots_after,"staging_entries_before":stage_before,"staging_entries_after":stage_after,"hidden_entries_before":hidden_before,"hidden_entries_after":hidden_after,"cases":cases,"contention_results":contention_results,"failures":failures,"side_effects":{"provider_calls":0,"transactions":0,"credits":0,"retries":0,"agentcut":0,"assembly":0},"next_action":"Keep execution closed. Register an exact-SHA pinned V21 recovery writer invoker and repeat bounded outcome classification locally."}
    write_report(REPORT, report)
    print(json.dumps({"status":status,"report":str(REPORT),"failures":failures}, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
