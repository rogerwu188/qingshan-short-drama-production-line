#!/usr/bin/env python3
"""Install or verify the portable Claude Writer Scheduled Agent definition."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import py_compile
import shutil
import tempfile
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = PACKAGE_ROOT / "package_manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def default_scheduled_root() -> Path:
    return Path.home() / "Documents" / "Claude" / "Scheduled"


def deploy_path(scheduled_root: Path, manifest: dict) -> Path:
    return scheduled_root / manifest["agent_name"] / "SKILL.md"


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        shutil.copy2(source, temp_path)
        os.replace(temp_path, destination)
    finally:
        temp_path.unlink(missing_ok=True)


def install(project_root: Path, scheduled_root: Path) -> dict:
    manifest = load_manifest()
    source_skill = project_root / manifest["source_skill"]
    destination = deploy_path(scheduled_root, manifest)
    backup = None
    if destination.exists() and sha256(destination) != sha256(source_skill):
        backup = destination.with_name("SKILL.md.previous")
        atomic_copy(destination, backup)
    atomic_copy(source_skill, destination)

    initialized: list[str] = []
    preserved: list[str] = []
    for runtime_rel, template_rel in manifest["runtime_templates"].items():
        runtime_path = project_root / runtime_rel
        if runtime_path.exists():
            preserved.append(runtime_rel)
            continue
        atomic_copy(project_root / template_rel, runtime_path)
        initialized.append(runtime_rel)
    return {
        "status": "INSTALLED",
        "destination": str(destination),
        "skill_sha256": sha256(destination),
        "backup": str(backup) if backup else None,
        "runtime_initialized": initialized,
        "runtime_preserved": preserved,
    }


def doctor(project_root: Path, scheduled_root: Path) -> dict:
    manifest = load_manifest()
    missing = [
        rel for rel in manifest["required_repository_files"]
        if not (project_root / rel).is_file()
    ]
    source_skill = project_root / manifest["source_skill"]
    destination = deploy_path(scheduled_root, manifest)
    runtime_errors: list[str] = []
    for runtime_rel in manifest["runtime_templates"]:
        path = project_root / runtime_rel
        if not path.exists():
            runtime_errors.append(f"MISSING:{runtime_rel}")
        elif path.suffix == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # pragma: no cover - diagnostic detail
                runtime_errors.append(f"INVALID_JSON:{runtime_rel}:{exc}")

    compile_errors: list[str] = []
    for rel in (
        "tools/canonical_writer_dispatcher.py",
        "tools/canonical_writer_provenance.py",
        "tools/episode_stage_gate_runner.py",
    ):
        path = project_root / rel
        if not path.exists():
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            compile_errors.append(f"{rel}:{exc}")

    source_sha = sha256(source_skill) if source_skill.exists() else None
    deployed_sha = sha256(destination) if destination.exists() else None
    issues = []
    issues.extend(f"MISSING_REPOSITORY_FILE:{rel}" for rel in missing)
    issues.extend(runtime_errors)
    issues.extend(f"PY_COMPILE:{item}" for item in compile_errors)
    if not destination.exists():
        issues.append("SCHEDULED_SKILL_NOT_INSTALLED")
    elif source_sha != deployed_sha:
        issues.append("SCHEDULED_SKILL_SHA_MISMATCH")
    if source_skill.exists() and "{{" in source_skill.read_text(encoding="utf-8"):
        issues.append("UNRESOLVED_TEMPLATE_PLACEHOLDER")
    return {
        "status": "PASS" if not issues else "FAIL",
        "project_root": str(project_root),
        "scheduled_skill": str(destination),
        "source_skill_sha256": source_sha,
        "deployed_skill_sha256": deployed_sha,
        "issues": issues,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("install", "doctor"))
    parser.add_argument("--project-root", type=Path, default=PACKAGE_ROOT.parents[1])
    parser.add_argument("--scheduled-root", type=Path, default=default_scheduled_root())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = args.project_root.expanduser().resolve()
    scheduled_root = args.scheduled_root.expanduser().resolve()
    result = install(project_root, scheduled_root) if args.mode == "install" else doctor(project_root, scheduled_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "INSTALLED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
