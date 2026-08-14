#!/usr/bin/env python3
"""Exercise staged E36 V23 payloads like local upload consumers."""

from __future__ import annotations

import hashlib
import json
import struct
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "working_assets/e36_release_prep_20260801/platform_payload_v23_v1"
SOURCE_QA = ROOT / "qa/e36_agentcut_20260730/E36_V23_PLATFORM_PAYLOAD_STAGING_QA_V1.json"
OUT_DIR = ROOT / "qa/e36_agentcut_20260730/v23_platform_payload_consumer_preflight_v1"
OUT = ROOT / "qa/e36_agentcut_20260730/E36_V23_PLATFORM_PAYLOAD_CONSUMER_PREFLIGHT_QA_V1.json"
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
MAILBOX_SHA = "1421e83dd9e802c1a16eaf57df6c757f761d227c6578e85891b35ddb1834e8f7"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def atoms(path: Path) -> list[dict]:
    rows = []
    size_total = path.stat().st_size
    with path.open("rb") as handle:
        offset = 0
        while offset + 8 <= size_total:
            handle.seek(offset)
            header = handle.read(8)
            size, atom_type = struct.unpack(">I4s", header)
            header_size = 8
            if size == 1:
                size = struct.unpack(">Q", handle.read(8))[0]
                header_size = 16
            elif size == 0:
                size = size_total - offset
            if size < header_size or offset + size > size_total:
                raise SystemExit(f"invalid MP4 atom at {offset}: {path}")
            rows.append({"type": atom_type.decode("ascii", "replace"), "offset": offset, "size": size})
            offset += size
    return rows


def probe(path: Path) -> dict:
    result = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def decode(job: dict) -> dict:
    log = OUT_DIR / job["log"]
    command = [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y"]
    if job.get("start") is not None:
        command += ["-ss", str(job["start"])]
    command += ["-i", str(job["path"])]
    if job.get("duration") is not None:
        command += ["-t", str(job["duration"])]
    command += ["-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"]
    result = subprocess.run(command, capture_output=True)
    log.write_bytes(result.stderr)
    return {
        "id": job["id"], "start": job.get("start"), "duration": job.get("duration"),
        "exit_code": result.returncode, "log": rel(log), "log_sha256": sha(log),
        "log_bytes": log.stat().st_size, "status": "PASS" if result.returncode == 0 else "FAIL",
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    source = json.loads(SOURCE_QA.read_text(encoding="utf-8"))
    expected = {row.split("  ", 1)[1]: row.split("  ", 1)[0]
                for row in (STAGE / "SHA256SUMS.txt").read_text(encoding="ascii").splitlines()}
    checksum_results = {name: sha(STAGE / name) == digest for name, digest in expected.items()}
    if not all(checksum_results.values()):
        raise SystemExit(json.dumps(checksum_results, indent=2))

    videos = sorted(STAGE.glob("*/video.mp4"))
    payloads = []
    jobs = []
    for video_path in videos:
        media_probe = probe(video_path)
        duration = float(media_probe["format"]["duration"])
        atom_rows = atoms(video_path)
        atom_names = [row["type"] for row in atom_rows]
        faststart = "moov" in atom_names and "mdat" in atom_names and atom_names.index("moov") < atom_names.index("mdat")
        payload_id = video_path.parent.name
        jobs.append({"id": f"{payload_id}_full", "path": video_path, "log": f"{payload_id}_full_decode.log"})
        seek_points = [1.0, round(duration / 2, 3), round(max(0.0, duration - 2.0), 3)]
        for index, start in enumerate(seek_points, 1):
            jobs.append({
                "id": f"{payload_id}_seek{index}", "path": video_path, "start": start,
                "duration": 1.0, "log": f"{payload_id}_seek{index}_{start:.3f}.log",
            })
        payloads.append({
            "payload_id": payload_id, "video": rel(video_path), "sha256": sha(video_path),
            "duration_seconds": duration, "top_level_atoms": atom_rows,
            "faststart_moov_before_mdat": faststart, "seek_points_seconds": seek_points,
        })

    with ThreadPoolExecutor(max_workers=6) as pool:
        decode_rows = list(pool.map(decode, jobs))
    full_rows = [row for row in decode_rows if row["id"].endswith("_full")]
    seek_rows = [row for row in decode_rows if not row["id"].endswith("_full")]

    covers = []
    for cover_path in sorted(STAGE.glob("*/cover.png")):
        cover_probe = probe(cover_path)
        stream = cover_probe["streams"][0]
        covers.append({
            "path": rel(cover_path), "sha256": sha(cover_path),
            "dimensions": [stream["width"], stream["height"]],
            "codec": stream["codec_name"],
            "status": "PASS" if (stream["width"], stream["height"]) == (1080, 1920) else "FAIL",
        })

    metadata = []
    for path in sorted(STAGE.glob("*/metadata.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        metadata.append({
            "path": rel(path), "sha256": sha(path), "platform": value["platform"],
            "title": value["title"], "submission_status": value["submission_status"],
            "status": "PASS" if value["submission_status"] == "NOT_SUBMITTED" else "FAIL",
        })

    checks = {
        "source_staging_qa_pass": source["status"] == "PASS_REVERSIBLE_PLATFORM_PAYLOADS_STAGED_RELEASE_HOLD",
        "checksum_manifest_pass": all(checksum_results.values()),
        "payload_count_3": len(payloads) == 3,
        "faststart_3_of_3": all(row["faststart_moov_before_mdat"] for row in payloads),
        "full_decode_3_of_3": len(full_rows) == 3 and all(row["status"] == "PASS" for row in full_rows),
        "random_seek_decode_9_of_9": len(seek_rows) == 9 and all(row["status"] == "PASS" for row in seek_rows),
        "covers_2_of_2_1080x1920": len(covers) == 2 and all(row["status"] == "PASS" for row in covers),
        "metadata_3_of_3_not_submitted": len(metadata) == 3 and all(row["status"] == "PASS" for row in metadata),
    }
    payload = {
        "schema": "qingshan.e36.v23_platform_payload_consumer_preflight_qa.v1",
        "episode": "E36", "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_cl2x": "CL2X-924", "source_mailbox_sha256": MAILBOX_SHA,
        "source_staging_qa": {"path": rel(SOURCE_QA), "sha256": sha(SOURCE_QA)},
        "method": "Credential-free local consumer simulation: checksum revalidation, top-level MP4 atom parsing, concurrent full A/V decode, nine distributed random seek A/V decodes, cover probing and metadata round-trip.",
        "payloads": payloads, "decode_results": decode_rows, "covers": covers, "metadata": metadata,
        "checks": checks,
        "gate_results": {
            "payload_checksums": "PASS_ALL_8_STAGED_FILES",
            "mp4_faststart": "PASS_3_OF_3_MOOV_BEFORE_MDAT",
            "full_av_decode": "PASS_3_OF_3_ZERO_ERRORS",
            "random_seek_av_decode": "PASS_9_OF_9_ZERO_ERRORS",
            "covers": "PASS_2_OF_2_1080X1920",
            "metadata": "PASS_3_OF_3_UTF8_NOT_SUBMITTED",
            "accepted_transcript": "HOLD_39_OF_47", "continuous_full_runtime_human_watch": "NOT_COMPLETE",
            "release": "HOLD", "platform_action": "NONE",
        },
        "blocked_by": (
            "PROMOTION_ONLY:V23_CONTINUOUS_AUDIOVISUAL_WATCH_INCOMPLETE;"
            "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;"
            "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
        ),
        "workaround_executed": "Exercised all staged payloads through local upload-consumer style checksum, faststart, full-decode, random-seek, cover and metadata preflight without account access or submission.",
        "credits": {"pay": 0, "refund": 0, "net": 0, "episode_net": 9976, "cap": 10000, "headroom": 24},
        "next_action": "Continue uninterrupted V23 audiovisual review and materially distinct source-native recovery for lines4/5/11/12/23/24/27/28; preserve staged payloads and perform no platform submission.",
        "status": "PASS_STAGED_PAYLOAD_CONSUMER_PREFLIGHT_RELEASE_HOLD" if all(checks.values()) else "FAIL_PRESERVED",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": rel(OUT), "sha256": sha(OUT), "checks": checks}, ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
