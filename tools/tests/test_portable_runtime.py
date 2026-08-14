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
        with patch.dict(os.environ, {"QINGSHAN_WHISPER_MODEL": "medium"}, clear=False):
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
