#!/usr/bin/env python3
"""Select a fast H.264 release encoder with a deterministic quality fallback."""

from __future__ import annotations

import subprocess


def available_encoders() -> str:
    return subprocess.check_output(
        ["ffmpeg", "-hide_banner", "-encoders"], stderr=subprocess.STDOUT, text=True
    )


def select_h264_encoder(encoders_text: str | None = None) -> dict[str, object]:
    text = encoders_text if encoders_text is not None else available_encoders()
    if "h264_videotoolbox" in text:
        return {
            "name": "h264_videotoolbox",
            "hardware_accelerated": True,
            "args": [
                "-c:v", "h264_videotoolbox", "-b:v", "18M", "-maxrate", "24M",
                "-bufsize", "36M", "-pix_fmt", "yuv420p", "-realtime", "false",
            ],
        }
    return {
        "name": "libx264",
        "hardware_accelerated": False,
        "args": ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"],
    }
