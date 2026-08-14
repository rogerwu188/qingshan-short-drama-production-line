#!/usr/bin/env python3
"""Inventory E37 local video sources before spending credits on action repairs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(ffprobe: Path, path: Path) -> dict | None:
    result = subprocess.run(
        [
            str(ffprobe), "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,codec_name,avg_frame_rate",
            "-show_entries", "format=duration", "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    if not streams:
        return None
    stream = streams[0]
    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "codec": stream.get("codec_name"),
        "avg_frame_rate": stream.get("avg_frame_rate"),
        "duration_seconds": round(float((payload.get("format") or {}).get("duration") or 0), 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffprobe", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    files = sorted(
        path for path in (ROOT / "working_assets").rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".mp4", ".mov"}
        and "e37" in str(path).lower()
    )
    decoded = []
    native = []
    for path in files:
        media = probe(args.ffprobe, path)
        if media is None:
            continue
        row = {"path": str(path.relative_to(ROOT)), **media}
        decoded.append(row)
        if media["width"] >= 1080 and media["height"] >= 1920:
            row["sha256"] = sha256(path)
            native.append(row)

    later_chain_candidates = [
        row for row in native
        if any(token in row["path"] for token in ("B04", "B05", "B06", "B07", "B08"))
    ]
    result = {
        "schema": "qingshan.e37_native1080_reuse_audit.v1",
        "episode": "E37",
        "search_root": "working_assets",
        "video_files_seen": len(files),
        "video_files_decoded": len(decoded),
        "native_portrait_1080_candidates": len(native),
        "later_chain_B04_B08_candidates": len(later_chain_candidates),
        "status": "PASS_REUSE_FOUND" if later_chain_candidates else "FAIL_NO_LATER_CHAIN_NATIVE1080_REUSE",
        "native_candidates": native,
        "later_chain_candidates": later_chain_candidates,
        "policy": {
            "cosmetic_upscale_forbidden": True,
            "minimum_formal_source": "1080x1920",
            "failed_unit_tail_binding_forbidden": True,
        },
    }
    out = args.out if args.out.is_absolute() else ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "seen": len(files),
        "decoded": len(decoded),
        "native1080": len(native),
        "later_chain": len(later_chain_candidates),
        "out": str(out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
