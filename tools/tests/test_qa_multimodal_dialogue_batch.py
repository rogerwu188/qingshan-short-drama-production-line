#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "tools/qa_multimodal_dialogue_batch.py"
SPEC = importlib.util.spec_from_file_location("qa_multimodal_dialogue_batch", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeModel:
    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(self, *_args, **_kwargs):
        return [SimpleNamespace(start=0.2, end=3.6, text=self.text)], None


def fake_probe(_path: Path, _ffprobe: Path) -> dict:
    return {
        "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
        "format": {"duration": "5.0"},
    }


class MultimodalDialogueBatchTests(unittest.TestCase):
    def test_chinese_recall_normalizes_traditional_variant(self) -> None:
        self.assertEqual(MODULE.recall("开门", "請開門"), 1.0)

    def test_missing_audio_or_dialogue_is_a_real_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            clip = Path(temporary) / "clip.mp4"
            clip.write_bytes(b"video")
            row = MODULE.review_dialogue(
                "D01",
                {"dialogue_id": "D01", "text": "打开门", "duration": 5},
                {"downloaded_files": [str(clip)]},
                model=FakeModel(""),
                ffprobe=Path("ffprobe"),
                minimum_recall=0.55,
                probe_fn=fake_probe,
            )
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("no_recognized_chinese_speech", row["failures"])

    def test_exact_mandarin_dialogue_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            clip = Path(temporary) / "clip.mp4"
            clip.write_bytes(b"video")
            row = MODULE.review_dialogue(
                "D01",
                {"dialogue_id": "D01", "text": "打开门", "duration": 5},
                {"downloaded_files": [str(clip)]},
                model=FakeModel("打开门"),
                ffprobe=Path("ffprobe"),
                minimum_recall=0.55,
                probe_fn=fake_probe,
            )
        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["recall_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
