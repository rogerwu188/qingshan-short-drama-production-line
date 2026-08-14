#!/usr/bin/env python3
"""Read PNG and JPEG dimensions without external media binaries."""

from __future__ import annotations

import struct
from pathlib import Path


JPEG_SOF_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


def _png_dimensions(handle) -> tuple[int, int]:
    header = handle.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError("invalid_png_header")
    width, height = struct.unpack(">II", header[16:24])
    if width <= 0 or height <= 0:
        raise ValueError("invalid_png_dimensions")
    return width, height


def _jpeg_dimensions(handle) -> tuple[int, int]:
    if handle.read(2) != b"\xff\xd8":
        raise ValueError("invalid_jpeg_header")

    while True:
        prefix = handle.read(1)
        if not prefix:
            raise ValueError("jpeg_sof_marker_not_found")
        if prefix != b"\xff":
            continue

        marker_byte = handle.read(1)
        while marker_byte == b"\xff":
            marker_byte = handle.read(1)
        if not marker_byte:
            raise ValueError("truncated_jpeg_marker")
        marker = marker_byte[0]

        if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
            continue

        raw_length = handle.read(2)
        if len(raw_length) != 2:
            raise ValueError("truncated_jpeg_segment_length")
        segment_length = struct.unpack(">H", raw_length)[0]
        if segment_length < 2:
            raise ValueError("invalid_jpeg_segment_length")

        if marker in JPEG_SOF_MARKERS:
            payload = handle.read(5)
            if len(payload) != 5:
                raise ValueError("truncated_jpeg_sof")
            height, width = struct.unpack(">HH", payload[1:5])
            if width <= 0 or height <= 0:
                raise ValueError("invalid_jpeg_dimensions")
            return width, height

        handle.seek(segment_length - 2, 1)


def read_image_dimensions(path: str | Path) -> tuple[int, int]:
    """Return ``(width, height)`` for a PNG or JPEG file."""
    image_path = Path(path)
    with image_path.open("rb") as handle:
        signature = handle.read(8)
        handle.seek(0)
        if signature == b"\x89PNG\r\n\x1a\n":
            return _png_dimensions(handle)
        if signature[:2] == b"\xff\xd8":
            return _jpeg_dimensions(handle)
    raise ValueError("unsupported_or_invalid_image_format")
