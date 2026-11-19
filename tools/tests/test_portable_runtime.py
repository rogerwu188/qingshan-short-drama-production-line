import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.portable_runtime import resolve_media_binary, resolve_whisper_model


class PortableRuntimeTests(unittest.TestCase):
    def test_explicit_media_binary_wins(self):
        with tempfile.TemporaryDirectory() as td:
            binary = Path(td) / "ffmpeg"
            binary.write_bytes(b"")
            path, source = resolve_media_binary("ffmpeg", explicit=binary)
            self.assertEqual(path, binary.resolve())
            self.assertEqual(source, "explicit")

    def test_whisper_env_accepts_model_identifier(self):
        # a host that has the model cached (Japanese lines fetch "medium", 2026-11-18) resolves the snapshot path
        with patch.dict(os.environ, {"QINGSHAN_WHISPER_MODEL": "medium"}, clear=False), \
                patch("tools.portable_runtime._cached_whisper_snapshot", return_value=None):
            model, source = resolve_whisper_model()
        self.assertEqual(model, "medium")
        self.assertEqual(source, "model_identifier")

    def test_whisper_explicit_local_path(self):
        with tempfile.TemporaryDirectory() as td:
            model, source = resolve_whisper_model(td)
            self.assertEqual(model, str(Path(td).resolve()))
            self.assertEqual(source, "explicit_or_env_path")


if __name__ == "__main__":
    unittest.main()
