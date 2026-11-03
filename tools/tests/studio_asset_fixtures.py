"""Shared synthetic fixtures for the studio asset library tests (no real media, no story text)."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path


def png_bytes(width: int = 8, height: int = 8, seed: int = 0) -> bytes:
    """A valid, tiny PNG whose bytes depend on ``seed`` (so different seeds are different originals)."""
    raw = b"".join(b"\x00" + bytes([(seed * 7 + x * 3 + y) % 256 for x in range(width * 3)]) for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def write_png(path: Path, seed: int = 0, width: int = 8, height: int = 8) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes(width, height, seed))
    return path


REVIEW_REF = {"kind": "TEST_REVIEW_RECEIPT", "sha256": "a" * 64, "label": "fixture review"}
