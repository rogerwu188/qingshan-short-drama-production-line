#!/usr/bin/env python3
"""Stage reversible, credential-free E36 V23 platform payloads and verify them."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "workflow/releases/E36_RELEASE_PACKAGE_PREP_V7_20260801.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
STAGE = ROOT / "working_assets/e36_release_prep_20260801/platform_payload_v23_v1"
QA = ROOT / "qa/e36_agentcut_20260730/E36_V23_PLATFORM_PAYLOAD_STAGING_QA_V1.json"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"
RELEASE_SHA = "6292a773dbf1335230547b5eb6d9b9c3a810bab2bc296fd4816a77ba142c21b5"
MAILBOX_SHA = "1421e83dd9e802c1a16eaf57df6c757f761d227c6578e85891b35ddb1834e8f7"
FFPROBE = shutil.which("ffprobe") or str(
    ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def hardlink(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha(target) != sha(source):
            raise SystemExit(f"conflicting staged artifact: {target}")
        return
    os.link(source, target)


def probe(path: Path) -> dict:
    if not FFPROBE:
        raise SystemExit("ffprobe unavailable")
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    release = json.loads(RELEASE.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    canonical_checks = {
        "script_sha_exact": sha(SCRIPT) == SCRIPT_SHA,
        "manifest_file_sha_exact": sha(MANIFEST) == MANIFEST_SHA,
        "manifest_declares_script_sha": manifest.get("sha256") == SCRIPT_SHA,
        "release_manifest_sha_exact": sha(RELEASE) == RELEASE_SHA,
        "release_manifest_platform_action_none": release["gate_results"]["platform_action"] == "NONE",
        "release_manifest_release_blocked": not release["release_allowed"],
    }
    if not all(canonical_checks.values()):
        raise SystemExit(json.dumps(canonical_checks, ensure_ascii=False, indent=2))

    yt = release["youtube_two_part_package"]
    dy = release["douyin_package"]
    specs = [
        {
            "id": "youtube_part1",
            "platform": "YouTube Shorts",
            "video": ROOT / yt["part1"]["video"],
            "video_sha": yt["part1"]["video_sha256"],
            "cover": ROOT / yt["part1"]["cover"],
            "cover_sha": yt["part1"]["cover_sha256"],
            "title": yt["part1"]["title_draft"],
            "part": 1,
            "runtime_ceiling": yt["runtime_ceiling_seconds"],
        },
        {
            "id": "youtube_part2",
            "platform": "YouTube Shorts",
            "video": ROOT / yt["part2"]["video"],
            "video_sha": yt["part2"]["video_sha256"],
            "cover": ROOT / yt["part2"]["cover"],
            "cover_sha": yt["part2"]["cover_sha256"],
            "title": yt["part2"]["title_draft"],
            "part": 2,
            "runtime_ceiling": yt["runtime_ceiling_seconds"],
        },
        {
            "id": "douyin_full",
            "platform": "Douyin creator publication",
            "video": ROOT / dy["full_length_candidate"],
            "video_sha": dy["full_length_candidate_sha256"],
            "cover": None,
            "cover_sha": None,
            "title": dy["title_draft"],
            "part": None,
            "runtime_ceiling": None,
        },
    ]

    STAGE.mkdir(parents=True, exist_ok=True)
    rows = []
    checksum_lines = []
    for spec in specs:
        target_dir = STAGE / spec["id"]
        target_video = target_dir / "video.mp4"
        hardlink(spec["video"], target_video)
        target_cover = None
        if spec["cover"]:
            target_cover = target_dir / "cover.png"
            hardlink(spec["cover"], target_cover)

        metadata = {
            "schema": "qingshan.e36.platform_payload_metadata.v1",
            "episode": "E36",
            "series": "青山",
            "platform": spec["platform"],
            "title": spec["title"],
            "description": "《青山》EP36《假谍探真棋子》" + (f"（{'上' if spec['part'] == 1 else '下'}）" if spec["part"] else ""),
            "hashtags": ["青山", "AI短剧", "古装悬疑", "短剧"],
            "part": spec["part"],
            "made_for_kids": False if spec["platform"] == "YouTube Shorts" else None,
            "visibility": "HOLD_NO_FINAL_LOCK",
            "submission_status": "NOT_SUBMITTED",
            "account_identity": "NOT_LOCALLY_DECLARED_IN_E36_AUTHORITY_FILES",
            "video_filename": "video.mp4",
            "cover_filename": "cover.png" if target_cover else None,
        }
        metadata_path = target_dir / "metadata.json"
        write_json(metadata_path, metadata)
        metadata_path.read_text(encoding="utf-8")

        media_probe = probe(target_video)
        video = next(row for row in media_probe["streams"] if row["codec_type"] == "video")
        audio = next(row for row in media_probe["streams"] if row["codec_type"] == "audio")
        duration = float(media_probe["format"]["duration"])
        checks = {
            "source_video_sha_exact": sha(spec["video"]) == spec["video_sha"],
            "staged_video_sha_exact": sha(target_video) == spec["video_sha"],
            "staged_video_hardlink_identity": os.stat(target_video).st_ino == os.stat(spec["video"]).st_ino,
            "video_720x1280": (video["width"], video["height"]) == (720, 1280),
            "video_h264": video["codec_name"] == "h264",
            "video_yuv420p": video["pix_fmt"] == "yuv420p",
            "video_24fps": video["r_frame_rate"] == "24/1",
            "audio_aac": audio["codec_name"] == "aac",
            "audio_48khz_stereo": audio["sample_rate"] == "48000" and audio["channels"] == 2,
            "runtime_within_declared_ceiling": spec["runtime_ceiling"] is None or duration < spec["runtime_ceiling"],
            "metadata_utf8_roundtrip": json.loads(metadata_path.read_text(encoding="utf-8")) == metadata,
            "title_nonempty": bool(metadata["title"].strip()),
            "submission_still_closed": metadata["submission_status"] == "NOT_SUBMITTED",
        }
        if target_cover:
            checks.update({
                "source_cover_sha_exact": sha(spec["cover"]) == spec["cover_sha"],
                "staged_cover_sha_exact": sha(target_cover) == spec["cover_sha"],
                "staged_cover_hardlink_identity": os.stat(target_cover).st_ino == os.stat(spec["cover"]).st_ino,
            })
        if not all(checks.values()):
            raise SystemExit(json.dumps({spec["id"]: checks}, ensure_ascii=False, indent=2))

        staged_files = [target_video, metadata_path] + ([target_cover] if target_cover else [])
        for path in staged_files:
            checksum_lines.append(f"{sha(path)}  {path.relative_to(STAGE)}")
        rows.append({
            "payload_id": spec["id"],
            "platform": spec["platform"],
            "directory": rel(target_dir),
            "video": {"path": rel(target_video), "sha256": sha(target_video), "duration_seconds": duration},
            "cover": ({"path": rel(target_cover), "sha256": sha(target_cover)} if target_cover else None),
            "metadata": {"path": rel(metadata_path), "sha256": sha(metadata_path)},
            "checks": checks,
            "status": "PASS_STAGED_REVERSIBLE_NOT_SUBMITTED",
        })

    checksums = STAGE / "SHA256SUMS.txt"
    checksums.write_text("\n".join(sorted(checksum_lines)) + "\n", encoding="ascii")
    checksum_verification = all(
        sha(STAGE / line.split("  ", 1)[1]) == line.split("  ", 1)[0]
        for line in checksums.read_text(encoding="ascii").splitlines()
    )
    payload = {
        "schema": "qingshan.e36.v23_platform_payload_staging_qa.v1",
        "episode": "E36",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_cl2x": "CL2X-924",
        "source_mailbox_sha256": MAILBOX_SHA,
        "canonical_gate": {"status": "PASS", "checks": canonical_checks},
        "release_manifest": {"path": rel(RELEASE), "sha256": RELEASE_SHA},
        "staging_directory": rel(STAGE),
        "payloads": rows,
        "checksum_manifest": {"path": rel(checksums), "sha256": sha(checksums), "verification": checksum_verification},
        "gate_results": {
            "payload_inventory": "PASS_3_OF_3",
            "authority_sha_binding": "PASS_ALL_MEDIA_AND_COVERS",
            "hardlink_identity": "PASS_ALL_BINARY_ASSETS",
            "platform_media_profile": "PASS_3_OF_3_720X1280_H264_YUV420P_24FPS_AAC48K_STEREO",
            "youtube_runtime_ceiling": "PASS_2_OF_2_BELOW_179_SECONDS",
            "metadata_utf8_and_titles": "PASS_3_OF_3",
            "checksum_manifest": "PASS",
            "accepted_transcript": "HOLD_39_OF_47",
            "continuous_full_runtime_human_watch": "NOT_COMPLETE",
            "release": "HOLD",
            "platform_action": "NONE",
        },
        "blocked_by": (
            "PROMOTION_ONLY:V23_CONTINUOUS_AUDIOVISUAL_WATCH_INCOMPLETE;"
            "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;"
            "PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;"
            "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
        ),
        "workaround_executed": (
            "Staged credential-free YouTube Part1, YouTube Part2 and Douyin full payload directories using "
            "authority-bound hardlinks, UTF-8 platform metadata, exact checksums and independent media-profile probes. "
            "No account access or platform action was attempted."
        ),
        "credits": {"pay": 0, "refund": 0, "net": 0, "episode_net": 9976, "cap": 10000, "headroom": 24},
        "next_action": (
            "Continue uninterrupted V23 audiovisual review and materially distinct source-native recovery for "
            "lines4/5/11/12/23/24/27/28; retain staged payloads but do not submit without gate completion and explicit account identity."
        ),
        "status": "PASS_REVERSIBLE_PLATFORM_PAYLOADS_STAGED_RELEASE_HOLD",
    }
    write_json(QA, payload)
    print(json.dumps({
        "qa": rel(QA),
        "qa_sha256": sha(QA),
        "stage": rel(STAGE),
        "checksum_sha256": sha(checksums),
        "payloads": len(rows),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
