#!/usr/bin/env python3
"""Measure the encoded release master and enforce YouTube Shorts runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "configs/youtube_shorts_runtime_policy_v1.json"
FFPROBE_CANDIDATES = (
    ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe",
    Path("/usr/bin/ffprobe"),
    Path("/opt/homebrew/bin/ffprobe"),
    Path("/usr/local/bin/ffprobe"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ffprobe_path() -> Path:
    configured = os.environ.get("FFPROBE")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return candidate
    for candidate in FFPROBE_CANDIDATES:
        if candidate.is_file():
            return candidate
    discovered = shutil.which("ffprobe")
    return Path(discovered) if discovered else Path("ffprobe")


def duration_seconds(video: Path) -> float:
    proc = subprocess.run(
        [
            str(ffprobe_path()),
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(proc.stdout.strip())


def evaluate(duration: float, target: float, hard: float) -> tuple[str, bool]:
    if duration <= target:
        return "PASS", True
    if duration <= hard:
        return "PASS_WITH_MARGIN_WARNING", True
    return "FAIL_YOUTUBE_SHORTS_RUNTIME", False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    video = Path(args.video).expanduser().resolve()
    policy_path = Path(args.policy).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    if not video.is_file():
        raise SystemExit(f"release master missing: {video}")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    target = float(policy["target_max_seconds"])
    hard = float(policy["hard_max_seconds"])
    measured = duration_seconds(video)
    status, eligible = evaluate(measured, target, hard)
    result = {
        "schema": "qingshan.youtube_shorts_runtime_gate.v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "youtube_shorts_runtime_eligible": eligible,
        "video": str(video),
        "video_sha256": sha256(video),
        "duration_seconds": round(measured, 6),
        "target_max_seconds": target,
        "hard_max_seconds": hard,
        "measurement_scope": policy["measurement_scope"],
        "reason": policy["reason"],
        "allowed_repairs": policy["allowed_repairs"] if not eligible else [],
        "forbidden_repairs": policy["forbidden_repairs"],
        "platform_status": "YOUTUBE_SHORTS_READY" if eligible else policy["over_limit_platform_status"],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if eligible else 2


if __name__ == "__main__":
    raise SystemExit(main())
