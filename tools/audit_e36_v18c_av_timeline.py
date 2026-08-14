#!/usr/bin/env python3
"""Audit full-file audio/video packet timing without changing media."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import statistics
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FFPROBE = (
    ROOT
    / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ffprobe_json(path: Path) -> dict:
    command = [
        str(FFPROBE),
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=index,codec_type,time_base,start_time,duration,nb_frames:packet=stream_index,pts_time,dts_time,duration_time,flags",
        "-of",
        "json",
        str(path),
    ]
    return json.loads(subprocess.check_output(command, text=True))


def packet_summary(packets: list[dict]) -> dict:
    pts = [float(packet["pts_time"]) for packet in packets if "pts_time" in packet]
    dts = [float(packet["dts_time"]) for packet in packets if "dts_time" in packet]
    durations = [
        float(packet["duration_time"])
        for packet in packets
        if float(packet.get("duration_time", 0.0)) > 0.0
    ]
    packet_order_pts_gaps = [right - left for left, right in zip(pts, pts[1:])]
    dts_gaps = [right - left for left, right in zip(dts, dts[1:])]
    sorted_pts = sorted(pts)
    presentation_gaps = [
        right - left for left, right in zip(sorted_pts, sorted_pts[1:])
    ]
    positive_gaps = [gap for gap in presentation_gaps if gap > 0.0]
    median_gap = statistics.median(positive_gaps) if positive_gaps else 0.0
    expected_limit = median_gap * 3.5 if median_gap else 0.0
    return {
        "packet_count": len(packets),
        "pts_count": len(pts),
        "pts_start_seconds": min(pts) if pts else None,
        "pts_end_seconds": max(pts) if pts else None,
        "packet_end_seconds": (
            max(
                float(packet["pts_time"])
                + float(packet.get("duration_time", 0.0))
                for packet in packets
                if "pts_time" in packet
            )
            if pts
            else None
        ),
        "packet_order_pts_monotonic": all(
            gap >= 0.0 for gap in packet_order_pts_gaps
        ),
        "packet_order_pts_negative_gap_count": sum(
            gap < 0.0 for gap in packet_order_pts_gaps
        ),
        "dts_monotonic_non_decreasing": all(gap >= 0.0 for gap in dts_gaps),
        "dts_negative_gap_count": sum(gap < 0.0 for gap in dts_gaps),
        "presentation_pts_duplicate_count": len(sorted_pts) - len(set(sorted_pts)),
        "presentation_median_positive_gap_seconds": median_gap,
        "presentation_max_positive_gap_seconds": max(positive_gaps, default=0.0),
        "presentation_gap_over_3p5x_median_count": sum(
            gap > expected_limit for gap in positive_gaps
        ),
        "median_packet_duration_seconds": (
            statistics.median(durations) if durations else 0.0
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("media", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    payload = ffprobe_json(args.media)
    streams = {stream["codec_type"]: stream for stream in payload["streams"]}
    by_index: dict[int, list[dict]] = {}
    for packet in payload["packets"]:
        by_index.setdefault(int(packet["stream_index"]), []).append(packet)

    video_packets = by_index[int(streams["video"]["index"])]
    audio_packets = by_index[int(streams["audio"]["index"])]
    video_summary = packet_summary(video_packets)
    audio_summary = packet_summary(audio_packets)

    audio_pts = [
        float(packet["pts_time"])
        for packet in audio_packets
        if "pts_time" in packet
    ]
    video_pts = [
        float(packet["pts_time"])
        for packet in video_packets
        if "pts_time" in packet
    ]
    nearest_audio_offsets = []
    for timestamp in video_pts:
        position = bisect.bisect_left(audio_pts, timestamp)
        choices = audio_pts[max(0, position - 1) : min(len(audio_pts), position + 1)]
        if choices:
            nearest_audio_offsets.append(min(abs(timestamp - item) for item in choices))

    format_duration = float(payload["format"]["duration"])
    endpoint_delta = abs(
        float(video_summary["packet_end_seconds"])
        - float(audio_summary["packet_end_seconds"])
    )
    max_nearest_audio_offset = max(nearest_audio_offsets, default=0.0)
    report = {
        "schema": "qingshan.e36.av_timeline_audit.v1",
        "media": str(args.media.resolve()),
        "media_sha256": sha256(args.media),
        "format_duration_seconds": format_duration,
        "video_stream": streams["video"],
        "audio_stream": streams["audio"],
        "video_packets": video_summary,
        "audio_packets": audio_summary,
        "av_endpoint_delta_seconds": endpoint_delta,
        "video_to_nearest_audio_pts_offset_seconds": {
            "median": statistics.median(nearest_audio_offsets),
            "p95": sorted(nearest_audio_offsets)[
                min(len(nearest_audio_offsets) - 1, int(len(nearest_audio_offsets) * 0.95))
            ],
            "max": max_nearest_audio_offset,
        },
        "gate_results": {
            "video_decode_timestamps_monotonic": (
                "PASS" if video_summary["dts_monotonic_non_decreasing"] else "FAIL"
            ),
            "video_presentation_timeline_contiguous": (
                "PASS"
                if video_summary["presentation_gap_over_3p5x_median_count"] == 0
                else "FAIL"
            ),
            "audio_decode_timestamps_monotonic": (
                "PASS" if audio_summary["dts_monotonic_non_decreasing"] else "FAIL"
            ),
            "audio_presentation_timeline_contiguous": (
                "PASS"
                if audio_summary["presentation_gap_over_3p5x_median_count"] == 0
                else "FAIL"
            ),
            "av_endpoint_alignment": "PASS" if endpoint_delta <= 0.1 else "FAIL",
            "packet_interleave_alignment": (
                "PASS" if max_nearest_audio_offset <= 0.05 else "FAIL"
            ),
            "continuous_realtime_human_audiovisual_watch": "NOT_COMPLETE",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
