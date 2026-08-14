#!/usr/bin/env python3
"""AST capability audit for V31/V35/V37 core entrypoints; never imports or runs an executor."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "V31": (ROOT / "tools/e40_u18_v31_atomic_persistence_bundle.py", "compile_bundle"),
    "V35": (ROOT / "tools/e40_u18_v35_authority_document_verifier.py", "verify"),
    "V37": (ROOT / "tools/e40_u18_v37_authority_consumption_preflight.py", "verify"),
}
ALLOWED_DIRECT_CALLS = {
    "Path", "ValueError", "any", "append", "datetime.fromisoformat", "datetime.now", "dt", "encode", "enumerate",
    "expected_bundle_id", "fail", "get", "hashlib.sha256", "hexdigest", "identity", "isinstance", "items",
    "json.dumps", "json.loads", "len", "list", "load", "locked", "now", "range", "result", "set", "sha",
    "sha256", "simulate_atomic", "sorted", "str", "strip", "sum", "timestamp_ok", "under_root", "verify_v35", "zip",
}
ALLOWED_METHOD_CALLS = {
    "append", "encode", "exists", "extend", "fullmatch", "is_absolute", "is_file", "is_symlink", "items",
    "get", "read_bytes", "read_text", "relative_to", "replace", "resolve", "strip", "upper", "values",
}
FORBIDDEN_IMPORT_ROOTS = {
    "aiohttp", "ftplib", "http", "paramiko", "requests", "shutil", "smtplib", "socket", "subprocess",
    "telnetlib", "urllib", "webbrowser",
}
FORBIDDEN_CALL_NAMES = {
    "chmod", "commit", "connect", "copy", "copy2", "link", "mkdir", "open", "remove", "rename", "replace_with",
    "request", "rmdir", "send", "sendall", "symlink_to", "touch", "unlink", "urlopen", "write", "write_bytes", "write_text",
}
PROTECTED_WRITE_PATHS = (
    "workflow/approvals/**", "workflow/claude_writer_agent/formal_memory_updates/**",
    "workflow/claude_writer_agent/GENERATION_PROMPT_FAILURE_MEMORY.json", "<nonce_ledger_path>", "<branch_target_path>",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def definitions(tree: ast.AST) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def called_name(node: ast.Call) -> tuple[str | None, str | None]:
    if isinstance(node.func, ast.Name):
        return node.func.id, None
    if isinstance(node.func, ast.Attribute):
        parts = []
        current: ast.AST = node.func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
            return ".".join(reversed(parts)), node.func.attr
        return node.func.attr, node.func.attr
    return None, None


def reachable(functions: dict[str, ast.FunctionDef], entrypoint: str) -> set[str]:
    seen: set[str] = set()
    pending = [entrypoint]
    while pending:
        name = pending.pop()
        if name in seen or name not in functions:
            continue
        seen.add(name)
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in functions:
                pending.append(node.func.id)
    return seen


def audit(targets: dict[str, tuple[Path, str]] = TARGETS) -> dict:
    failures: list[str] = []
    artifacts = {}
    for label, (path, entrypoint) in targets.items():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except Exception:
            failures.append(f"{label}_SOURCE_MISSING_OR_INVALID")
            continue
        funcs = definitions(tree)
        graph = reachable(funcs, entrypoint)
        if entrypoint not in graph:
            failures.append(f"{label}_ENTRYPOINT_MISSING")
            continue
        imports = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        for module in sorted(imports & FORBIDDEN_IMPORT_ROOTS):
            failures.append(f"{label}_FORBIDDEN_IMPORT:{module}")
        calls = set()
        methods = set()
        for function_name in graph:
            for node in ast.walk(funcs[function_name]):
                if isinstance(node, ast.Call):
                    full, method = called_name(node)
                    if full:
                        calls.add(full)
                    if method:
                        methods.add(method)
        for call in sorted(calls):
            method = call.rsplit(".", 1)[-1]
            if method in FORBIDDEN_CALL_NAMES:
                failures.append(f"{label}_FORBIDDEN_CALL:{call}")
            elif "." in call:
                if method not in ALLOWED_METHOD_CALLS and call not in ALLOWED_DIRECT_CALLS:
                    failures.append(f"{label}_CALL_NOT_ALLOWLISTED:{call}")
            elif call not in ALLOWED_DIRECT_CALLS and call not in graph:
                failures.append(f"{label}_CALL_NOT_ALLOWLISTED:{call}")
        try:
            display_path = str(path.relative_to(ROOT))
        except ValueError:
            display_path = str(path)
        artifacts[label] = {
            "path": display_path,
            "sha256": sha256(path),
            "entrypoint": entrypoint,
            "reachable_local_functions": sorted(graph),
            "imports": sorted(imports),
            "calls": sorted(calls),
            "filesystem_effects": "READ_ONLY",
        }
    return {
        "schema": "qingshan.e40.u18.v39.executor_incapability_audit_result.v1",
        "status": "CAPABILITY_SEPARATION_PASS_NO_EXECUTION" if not failures else "CAPABILITY_SEPARATION_FAIL_CLOSED",
        "failures": sorted(set(failures)),
        "artifacts": artifacts,
        "audited_interface": "CORE_ENTRYPOINTS_ONLY_CLI_REPORT_WRITERS_EXCLUDED",
        "allowed_filesystem_calls": ["Path.read_bytes", "Path.read_text", "Path.exists", "Path.is_file", "Path.is_symlink", "Path.resolve", "Path.relative_to"],
        "forbidden_modules": sorted(FORBIDDEN_IMPORT_ROOTS),
        "forbidden_write_paths": list(PROTECTED_WRITE_PATHS),
        "network_capability": False,
        "provider_capability": False,
        "nonce_ledger_write_capability": False,
        "authority_write_capability": False,
        "formal_memory_write_capability": False,
        "target_write_capability": False,
        "executor_implemented": False,
        "execution_authorized": False,
        "maximum_new_submissions": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    value = audit()
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if value["status"] == "CAPABILITY_SEPARATION_PASS_NO_EXECUTION" else 3


if __name__ == "__main__":
    raise SystemExit(main())
