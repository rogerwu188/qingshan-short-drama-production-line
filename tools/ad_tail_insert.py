#!/usr/bin/env python3
"""ad_tail_insert.py — splice a packaged ad into the episode's final release.

By the time ``--content`` (``p.final_mp4``) exists, the 3s end-card is already
baked into it (nalu_pipeline.py stage_s7: subtitles -> end-card concat ->
loudness leveling, all before final_mp4 is written).  So this tool trims the
single leveled file back into ``content`` and ``endcard`` at
``total - endcard_seconds``, and re-concats
``content | packaged_ad | endcard`` — the ad sits strictly between the story
and the end-card, per the slot contract.  ``--content`` is never modified in
place; the spliced result is always a new file.  Any failure here means no
``*_AD.mp4`` is produced — it must never affect the original final video.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE = Path(__file__).resolve().parents[1]
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

try:
    from lines.nalu.runtime.tools.nalu_media_tools import MediaToolBlocked, require_ffmpeg, require_ffprobe
except ModuleNotFoundError:
    sys.path.insert(0, str(ENGINE / "lines/nalu/runtime/tools"))
    from nalu_media_tools import MediaToolBlocked, require_ffmpeg, require_ffprobe  # type: ignore


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def _probe_duration(ffprobe: str, path: Path) -> float:
    result = _run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                   "-of", "default=nw=1:nk=1", str(path)])
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {result.stderr[-2000:]}")
    return float(result.stdout.strip())


def append_ledger(ledger_path: Path, entry: dict[str, Any]) -> None:
    """Same seed-then-append + atomic_json shape as
    lines/nalu/runtime/tools/nalu_budget_ledger.py:118-122,676-706 — a SEPARATE
    ledger, never merged into the episode's own credit ledger."""
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if ledger_path.is_file():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    else:
        ledger = {"schema": "qingshan.ad_tail_transaction_ledger.v1", "entries": []}
    ledger.setdefault("entries", []).append(entry)
    temporary = ledger_path.with_suffix(ledger_path.suffix + ".part")
    temporary.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(ledger_path)


def insert(*, content: Path, endcard_seconds: float, packaged_ad: Path, packaged_ad_qa: Path,
           expected_packaged_sha256: str, sku: str, provenance: str, episode: str,
           out_path: Path, out_qa_path: Path, ledger_path: Path) -> dict[str, Any]:
    if out_path.exists() or out_qa_path.exists():
        raise FileExistsError(f"{out_path} / {out_qa_path} already exist; use a new run, "
                              "existing ad-tail evidence is immutable")

    ad_tail_sha_bound: dict[str, Any] = {"status": "PASS", "failures": []}
    actual_sha = sha256(packaged_ad)
    if actual_sha != expected_packaged_sha256:
        ad_tail_sha_bound = {"status": "FAIL",
                             "failures": [f"PACKAGED_AD_SHA_MISMATCH:{actual_sha}!={expected_packaged_sha256}"]}

    packaged_qa = json.loads(packaged_ad_qa.read_text(encoding="utf-8")) if packaged_ad_qa.is_file() else {}
    carried = {key: packaged_qa.get(key, {"status": "MISSING", "failures": ["missing_from_packaged_qa"]})
               for key in ("ad_tail_format", "ad_tail_duration", "ad_tail_loudness",
                          "ad_tail_label_present", "ad_tail_ocr_clean")}

    if ad_tail_sha_bound["status"] != "PASS" or any(v["status"] != "PASS" for v in carried.values()):
        payload = {"schema": "qingshan.ad_tail_insert_qa.v1", "episode": episode, "sku": sku,
                  "provenance": provenance, "recorded_at": now(),
                  "ad_tail_sha_bound": ad_tail_sha_bound, **carried, "status": "FAIL"}
        return payload

    try:
        ffmpeg = require_ffmpeg()
        ffprobe = require_ffprobe()
    except MediaToolBlocked as exc:
        return {"schema": "qingshan.ad_tail_insert_qa.v1", "episode": episode, "sku": sku,
                "provenance": provenance, "status": "FAIL",
                "ad_tail_sha_bound": ad_tail_sha_bound, **carried,
                "failures": [f"MEDIA_TOOL_BLOCKED:{exc}"]}

    total_duration = _probe_duration(ffprobe, content)
    content_end = total_duration - endcard_seconds
    if content_end <= 0:
        return {"schema": "qingshan.ad_tail_insert_qa.v1", "episode": episode, "sku": sku,
                "provenance": provenance, "status": "FAIL",
                "ad_tail_sha_bound": ad_tail_sha_bound, **carried,
                "failures": [f"CONTENT_SHORTER_THAN_ENDCARD:{total_duration}<={endcard_seconds}"]}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    filter_complex = (
        f"[0:v]trim=start=0:end={content_end:.6f},setpts=PTS-STARTPTS,fps=24,format=yuv420p[v0];"
        f"[0:a]atrim=start=0:end={content_end:.6f},asetpts=PTS-STARTPTS,"
        "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a0];"
        "[1:v]fps=24,format=yuv420p[v1];"
        "[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a1];"
        f"[0:v]trim=start={content_end:.6f}:end={total_duration:.6f},setpts=PTS-STARTPTS,fps=24,format=yuv420p[v2];"
        f"[0:a]atrim=start={content_end:.6f}:end={total_duration:.6f},asetpts=PTS-STARTPTS,"
        "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a2];"
        "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[v][a]"
    )
    result = _run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(content), "-i", str(packaged_ad),
        "-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "24",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out_path),
    ])
    if result.returncode != 0 or not out_path.is_file():
        out_path.unlink(missing_ok=True)
        return {"schema": "qingshan.ad_tail_insert_qa.v1", "episode": episode, "sku": sku,
                "provenance": provenance, "status": "FAIL",
                "ad_tail_sha_bound": ad_tail_sha_bound, **carried,
                "failures": [f"SPLICE_FFMPEG_FAILED:{result.stderr[-4000:]}"]}

    payload = {
        "schema": "qingshan.ad_tail_insert_qa.v1", "episode": episode, "sku": sku, "provenance": provenance,
        "recorded_at": now(), "content_source_sha256": sha256(content), "packaged_ad_sha256": actual_sha,
        "output_sha256": sha256(out_path), "content_end_seconds": round(content_end, 3),
        "endcard_seconds": endcard_seconds, "total_duration_seconds": round(total_duration, 3),
        "ad_tail_sha_bound": ad_tail_sha_bound, **carried, "status": "PASS",
    }
    out_qa_path.parent.mkdir(parents=True, exist_ok=True)
    out_qa_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    append_ledger(ledger_path, {
        "recorded_at_utc": now(), "episode": episode, "sku": sku, "provenance": provenance,
        "packaged_ad_sha256": actual_sha, "output": str(out_path), "output_sha256": payload["output_sha256"],
        "status": "PASS",
    })
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("insert")
    p.add_argument("--content", required=True, type=Path)
    p.add_argument("--endcard-seconds", required=True, type=float)
    p.add_argument("--packaged-ad", required=True, type=Path)
    p.add_argument("--packaged-ad-qa", required=True, type=Path)
    p.add_argument("--expected-packaged-sha256", required=True)
    p.add_argument("--sku", required=True)
    p.add_argument("--provenance", required=True)
    p.add_argument("--episode", required=True)
    p.add_argument("--slot-contract", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--out-qa", required=True, type=Path)
    p.add_argument("--ledger", type=Path)
    args = parser.parse_args()

    slot = json.loads(args.slot_contract.read_text(encoding="utf-8"))
    ledger_path = (args.ledger or Path(slot.get("ledger_dir", "ads/transactions")) / "insert_ledger.json").resolve()

    payload = insert(
        content=args.content.resolve(), endcard_seconds=args.endcard_seconds,
        packaged_ad=args.packaged_ad.resolve(), packaged_ad_qa=args.packaged_ad_qa.resolve(),
        expected_packaged_sha256=args.expected_packaged_sha256, sku=args.sku, provenance=args.provenance,
        episode=args.episode, out_path=args.out.resolve(), out_qa_path=args.out_qa.resolve(),
        ledger_path=ledger_path,
    )
    print(json.dumps({"status": payload["status"], "out": str(args.out),
                      "out_qa": str(args.out_qa)}, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
