#!/usr/bin/env python3
"""Build/verify the public engine inventory; runtime data is never included.

Building needs Git, verification works with an extracted GitHub source archive.
This proves file parity, not authenticity: obtain the manifest from a trusted tag.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "configs/DEPLOYMENT_CODE_SHA256.json"
SCHEMA = "qingshan.deployment_code_integrity.v1"


def included(name: str) -> bool:
    path = PurePosixPath(name)
    if name == MANIFEST or not path.parts:
        return False
    if path.parts[0] in {"tools", "qingshan_engine"}:
        return path.suffix in {".py", ".sh"}
    if path.parts[0] == "agent_factory":
        # Runtime state is private; skeletons/templates in the source archive
        # are installation resources, not files to overwrite on an active site.
        return ("state" not in path.parts and path.name != "SUPERVISOR_ORDERS.json"
                and path.suffix in {".py", ".sh", ".json", ".md", ".yaml", ".yml"})
    return name in {
        "pyproject.toml", "setup.py", "requirements.txt",
        "configs/PORTABLE_CORE_MANIFEST.json",
        "configs/GATE_REGISTRY_v3_20260716.json",
        "configs/VIDEO_MODEL_CAPABILITY_REGISTRY_v1.json",
        "configs/IMAGE_MODEL_CAPABILITY_REGISTRY_v1.json",
        "configs/PLATFORM_RELEASE_AUTOMATION_POLICY_V1.json",
    }


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def build(root: Path) -> dict:
    names = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=root
    ).decode().split("\0")
    files = []
    for name in sorted(set(filter(included, names))):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Non-regular source file: {name}")
        files.append({"path": name, "sha256": digest(path)})
    if not files:
        raise ValueError("Empty source inventory")
    return {"schema": SCHEMA, "scope": "PUBLIC_REUSABLE_ENGINE_NOT_PRIVATE_RUNTIME",
            "file_count": len(files), "files": files}


def verify(root: Path, manifest: dict) -> dict:
    rows = manifest.get("files")
    if (manifest.get("schema") != SCHEMA or not isinstance(rows, list) or not rows
            or type(manifest.get("file_count")) is not int
            or manifest["file_count"] != len(rows)):
        raise ValueError("Invalid or empty deployment manifest")
    seen, missing, changed = set(), [], []
    root = root.resolve()
    for row in rows:
        name = row.get("path", "")
        rel = PurePosixPath(name)
        sha = row.get("sha256", "")
        if (not name or rel.is_absolute() or ".." in rel.parts or "\\" in name
                or name in seen or not included(name) or len(sha) != 64
                or any(c not in "0123456789abcdef" for c in sha)):
            raise ValueError(f"Invalid or duplicate inventory entry: {name}")
        seen.add(name)
        path = root / name
        if path.is_symlink() or root not in path.resolve().parents:
            raise ValueError(f"Symlink/out-of-root engine file: {name}")
        if not path.is_file():
            missing.append(name)
        elif digest(path) != sha:
            changed.append(name)
    return {"schema": SCHEMA, "status": "PASS" if not missing and not changed else "FAIL",
            "file_count": len(rows), "missing": missing, "changed": changed,
            "scope": manifest.get("scope"), "unlisted_runtime_files": "NOT_COMPARED"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path, default=ROOT / MANIFEST)
    parser.add_argument("--build", action="store_true", help="Maintainer only; stage files first")
    parser.add_argument("--out", type=Path, help="Optional verification receipt")
    args = parser.parse_args()
    if args.build:
        payload = build(args.root.resolve())
        args.manifest.write_text(json.dumps(payload, indent=2) + "\n")
        print(json.dumps({"file_count": payload["file_count"], "manifest": str(args.manifest)}))
        return 0
    report = verify(args.root, json.loads(args.manifest.read_text()))
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
