#!/usr/bin/env python3
"""Stable public CLI for a clean Qingshan engine clone."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from qingshan_engine import __version__


def _engine_root() -> Path:
    configured = os.environ.get("QINGSHAN_ENGINE_ROOT", "").strip()
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.extend((Path.cwd(), Path(__file__).resolve().parents[1]))
    for candidate in candidates:
        resolved = candidate.resolve()
        if (resolved / "configs" / "PORTABLE_CORE_MANIFEST.json").is_file() and (resolved / "tools").is_dir():
            return resolved
    return Path(__file__).resolve().parents[1]


ROOT = _engine_root()
EXAMPLE_CONFIG = ROOT / "configs" / "pipeline.example.json"
CORE_MANIFEST = ROOT / "configs" / "PORTABLE_CORE_MANIFEST.json"


def _run(command: list[str]) -> int:
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def command_init(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    for name in ("sources", "runtime", "working_assets", "qa", "deliverables", "receipts"):
        (workspace / name).mkdir(exist_ok=True)
    target = workspace / "qingshan.json"
    if not target.exists():
        shutil.copy2(EXAMPLE_CONFIG, target)
    print(json.dumps({
        "status": "PASS",
        "workspace": str(workspace),
        "config": str(target),
        "next": f"qingshan doctor --profile all --config {target}",
    }, ensure_ascii=False, indent=2))
    return 0


def _check(name: str, passed: bool, detail: str, required: bool = True) -> dict:
    return {"name": name, "status": "PASS" if passed else ("FAIL" if required else "WARN"), "detail": detail}


def command_doctor(args: argparse.Namespace) -> int:
    checks: list[dict] = []
    checks.append(_check("python", sys.version_info >= (3, 9), sys.version.split()[0]))
    for executable in ("ffmpeg", "ffprobe"):
        value = os.environ.get(executable.upper()) or shutil.which(executable)
        checks.append(_check(executable, bool(value), value or "not found", required=args.profile in {"media", "all"}))
    for path in (ROOT / "LICENSE", ROOT / "README.md", CORE_MANIFEST, EXAMPLE_CONFIG):
        checks.append(_check(f"file:{path.name}", path.is_file(), str(path)))
    try:
        manifest = _load_json(CORE_MANIFEST)
        missing = [value for value in manifest["required_files"] if not (ROOT / value).is_file()]
        checks.append(_check("portable-core", not missing, "complete" if not missing else ", ".join(missing)))
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        checks.append(_check("portable-core", False, str(exc)))
    if args.config:
        path = Path(args.config).expanduser().resolve()
        try:
            config = _load_json(path)
            valid = config.get("schema") == "qingshan.pipeline.config.v1" and bool(config.get("workspace"))
            checks.append(_check("config", valid, str(path)))
        except (OSError, json.JSONDecodeError) as exc:
            checks.append(_check("config", False, str(exc)))
    if args.profile in {"generation", "all"}:
        checks.append(_check("GIGGLE_API_KEY", bool(os.environ.get("GIGGLE_API_KEY")), "set" if os.environ.get("GIGGLE_API_KEY") else "not set"))
    if args.profile in {"release", "all"}:
        checks.append(_check("interactive-release", True, "YouTube Studio and Douyin Creator Center use operator-authenticated browser sessions"))
        checks.append(_check("youtube-api-credentials", bool(os.environ.get("YOUTUBE_CLIENT_SECRETS")), "configured" if os.environ.get("YOUTUBE_CLIENT_SECRETS") else "optional; interactive release remains available", required=False))
    failed = [row for row in checks if row["status"] == "FAIL"]
    report = {"schema": "qingshan.doctor.v1", "version": __version__, "profile": args.profile, "status": "FAIL" if failed else "PASS", "checks": checks}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if failed else 0


def command_test(_: argparse.Namespace) -> int:
    return _run([sys.executable, "tools/run_portable_ci.py"])


def command_writer_doctor(_: argparse.Namespace) -> int:
    return _run([sys.executable, "-m", "unittest", "agent_factory.claude_writer_v2.tests.test_smoke"])


def command_video_preflight(args: argparse.Namespace) -> int:
    command = [sys.executable, "tools/submit_giggle_video_manifest_v2.py", "--manifest", args.manifest, "--out", args.out, "--precheck-only"]
    if args.project_root:
        command.extend(["--project-root", args.project_root])
    return _run(command)


def command_release_preflight(args: argparse.Namespace) -> int:
    command = [sys.executable, "tools/platform_release_preflight.py", *args.arguments]
    return _run(command)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qingshan", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create a safe external runtime workspace")
    init.add_argument("--workspace", required=True)
    init.set_defaults(func=command_init)
    doctor = sub.add_parser("doctor", help="validate a clean-clone deployment")
    doctor.add_argument("--profile", choices=("core", "media", "generation", "release", "all"), default="core")
    doctor.add_argument("--config")
    doctor.set_defaults(func=command_doctor)
    test = sub.add_parser("test", help="run the portable-core CI contract")
    test.set_defaults(func=command_test)
    writer = sub.add_parser("writer-doctor", help="run Writer Agent v2 smoke tests")
    writer.set_defaults(func=command_writer_doctor)
    video = sub.add_parser("video-preflight", help="validate a video manifest without a paid POST")
    video.add_argument("--manifest", required=True)
    video.add_argument("--out", required=True)
    video.add_argument("--project-root")
    video.set_defaults(func=command_video_preflight)
    release = sub.add_parser("release-preflight", help="run the fail-closed platform release gate")
    release.add_argument("arguments", nargs=argparse.REMAINDER)
    release.set_defaults(func=command_release_preflight)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
