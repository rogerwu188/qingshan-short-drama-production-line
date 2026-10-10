#!/usr/bin/env python3
"""Reference images are compressed before upload, and nothing else about them changes.

Roger 2026-10-01 (SUPERVISOR_ORDERS seq=21): 「参考图请求体过大时提交前自动压缩」 — written
after E10-VU-020 lost two responses at HTTP 524 with ~51 MB of base64.  E11-S02-01 hit the
same wall at ~22 MB (broken pipe, NOT_CHARGED_RETRYABLE).

The load-bearing property is the second one: compression must happen at ENCODE time on a copy.
Every prompt_contract/reference_bindings sha256 in the pipeline describes the file on disk, so
rewriting the file in place to shrink the body would invalidate the batch gate (K041) and every
downstream admission that binds those bytes.
"""
from __future__ import annotations

import base64
import io
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.giggle_api_client import (  # noqa: E402
    REFERENCE_COMPRESS_THRESHOLD_BYTES, REFERENCE_MAX_EDGE_PX, _image_list,
    reference_encoding_notes,
)

Image = None
try:
    from PIL import Image  # noqa: E402
except ImportError:  # pragma: no cover
    pass


def _noisy_png(path: Path, size=(2400, 3200)) -> Path:
    """A large, poorly-compressible PNG so the threshold is genuinely crossed."""
    import random
    random.seed(7)
    image = Image.new("RGB", size)
    pixels = image.load()
    for y in range(0, size[1], 4):
        for x in range(0, size[0], 4):
            value = (random.randrange(256), random.randrange(256), random.randrange(256))
            for dy in range(4):
                for dx in range(4):
                    if x + dx < size[0] and y + dy < size[1]:
                        pixels[x + dx, y + dy] = value
    image.save(path, format="PNG")
    return path


@unittest.skipIf(Image is None, "PIL unavailable")
class ReferenceCompressionTest(unittest.TestCase):
    def test_a_large_reference_is_compressed_and_shrinks_the_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _noisy_png(Path(tmp) / "big.png")
            self.assertGreater(path.stat().st_size, REFERENCE_COMPRESS_THRESHOLD_BYTES)
            out = _image_list([str(path)])
            note = reference_encoding_notes()[0]
            self.assertTrue(note["compressed"], note)
            self.assertLess(len(out[0]["base64"]), len(path.read_bytes()))
            self.assertLessEqual(max(note["final_size"]), REFERENCE_MAX_EDGE_PX)

    def test_the_source_file_is_never_rewritten(self):
        # this is what keeps reference_bindings sha256 honest
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            path = _noisy_png(Path(tmp) / "big.png")
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            _image_list([str(path)])
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(path.suffix, ".png")

    def test_a_small_reference_is_passed_through_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            small = Path(tmp) / "small.png"
            Image.new("RGB", (64, 64), (10, 20, 30)).save(small, format="PNG")
            raw = small.read_bytes()
            out = _image_list([str(small)])
            note = reference_encoding_notes()[0]
            self.assertFalse(note["compressed"])
            self.assertEqual(note["reason"], "BELOW_THRESHOLD")
            self.assertEqual(base64.b64decode(out[0]["base64"]), raw)

    def test_an_unreadable_file_is_passed_through_not_dropped(self):
        # a corrupt reference must surface as the submitter's error, not vanish into a smaller body
        with tempfile.TemporaryDirectory() as tmp:
            junk = Path(tmp) / "junk.png"
            junk.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * (REFERENCE_COMPRESS_THRESHOLD_BYTES + 10))
            out = _image_list([str(junk)])
            note = reference_encoding_notes()[0]
            self.assertFalse(note["compressed"])
            self.assertTrue(str(note["reason"]).startswith("COMPRESSION_FAILED"))
            self.assertEqual(base64.b64decode(out[0]["base64"]), junk.read_bytes())

    def test_notes_are_reset_per_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            small = Path(tmp) / "small.png"
            Image.new("RGB", (32, 32)).save(small, format="PNG")
            _image_list([str(small), str(small)])
            self.assertEqual(len(reference_encoding_notes()), 2)
            _image_list([str(small)])
            self.assertEqual(len(reference_encoding_notes()), 1)


if __name__ == "__main__":
    unittest.main()
