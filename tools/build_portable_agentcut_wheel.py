#!/usr/bin/env python3
"""Build a deterministic, pure-Python AgentCut wheel for cloud workers."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import os
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT
    / "workflow/cloud_factory_migration_v1_20260724/runtime_wheels_portable"
    / "agentcut-0.9.16-py3-none-any.whl"
)
VERSION = "0.9.16"
DIST_INFO = f"agentcut-{VERSION}.dist-info"
FIXED_ZIP_TIME = (2026, 7, 24, 0, 0, 0)


def find_source_package(root: Path = ROOT) -> Path:
    candidates = sorted(root.glob(".agentcut_env/lib/python*/site-packages/agentcut"))
    for candidate in reversed(candidates):
        if (candidate / "release_gate.py").is_file():
            return candidate
    raise FileNotFoundError("Complete AgentCut source package with release_gate.py was not found")


def wheel_files(source_package: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for source in sorted(source_package.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(source_package)
        if "__pycache__" in relative.parts or "vendor" in relative.parts:
            continue
        if source.suffix in {".pyc", ".pyo"}:
            continue
        files[(Path("agentcut") / relative).as_posix()] = source.read_bytes()

    required = {
        "agentcut/__init__.py",
        "agentcut/__main__.py",
        "agentcut/cli.py",
        "agentcut/engine.py",
        "agentcut/release_gate.py",
    }
    missing = sorted(required - files.keys())
    if missing:
        raise FileNotFoundError(f"Portable wheel source is incomplete: {missing}")

    files[f"{DIST_INFO}/METADATA"] = (
        "Metadata-Version: 2.4\n"
        "Name: agentcut\n"
        f"Version: {VERSION}\n"
        "Summary: Headless, JSON-driven FFmpeg editing engine for AI agents\n"
        "License: MIT\n"
        "Requires-Python: >=3.10\n"
        "Requires-Dist: requests>=2.31\n"
    ).encode("utf-8")
    files[f"{DIST_INFO}/WHEEL"] = (
        "Wheel-Version: 1.0\n"
        "Generator: qingshan-portable-wheel\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    ).encode("utf-8")
    files[f"{DIST_INFO}/entry_points.txt"] = (
        "[console_scripts]\nagentcut = agentcut.cli:main\n"
    ).encode("utf-8")
    files[f"{DIST_INFO}/top_level.txt"] = b"agentcut\n"
    return files


def _record_digest(data: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return f"sha256={encoded.decode('ascii')}"


def record_bytes(files: dict[str, bytes]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    for name in sorted(files):
        data = files[name]
        writer.writerow((name, _record_digest(data), len(data)))
    writer.writerow((f"{DIST_INFO}/RECORD", "", ""))
    return stream.getvalue().encode("utf-8")


def build_wheel(source_package: Path, output: Path) -> Path:
    files = wheel_files(source_package)
    files[f"{DIST_INFO}/RECORD"] = record_bytes(files)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + ".partial")
    if partial.exists():
        partial.unlink()
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as wheel:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            wheel.writestr(info, files[name])
    os.replace(partial, output)
    return output


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-package", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    source = (args.source_package or find_source_package()).resolve()
    output = build_wheel(source, args.output.resolve())
    print(f"{output} {sha256(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
