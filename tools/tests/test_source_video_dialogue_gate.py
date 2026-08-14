#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "tools/source_video_dialogue_gate.py"
SPEC = importlib.util.spec_from_file_location("source_video_dialogue_gate", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def probe(*, audio: bool = True, duration: float = 5.0) -> dict:
    streams = [{"codec_type": "video"}]
    if audio:
        streams.append({"codec_type": "audio"})
    return {"streams": streams, "format": {"duration": str(duration)}}


class SourceVideoDialogueGateTests(unittest.TestCase):
    def test_transcription_prompt_strips_leading_ellipsis(self) -> None:
        self.assertEqual(
            MODULE.transcription_prompt("……却还在按笔掏银子，买这颗棋的命。"),
            "却还在按笔掏银子买这颗棋的命",
        )

    def test_exact_native_dialogue_passes(self) -> None:
        report = MODULE.evaluate(
            Path("clip.mp4"),
            [{"dia_id": "D01", "text": "把门打开"}],
            probe_payload=probe(),
            transcript="把门打开",
            segments=[{"start": 0.2, "end": 3.8, "text": "把门打开"}],
            minimum_recall=0.55,
        )
        self.assertEqual(report["status"], "PASS")

    def test_missing_audio_blocks_even_no_dialogue_clip(self) -> None:
        report = MODULE.evaluate(
            Path("clip.mp4"),
            [],
            probe_payload=probe(audio=False),
            transcript="",
            segments=[],
            minimum_recall=0.55,
        )
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("audio_stream_missing", report["failures"])

    def test_partial_or_clipped_dialogue_blocks(self) -> None:
        report = MODULE.evaluate(
            Path("clip.mp4"),
            [{"dia_id": "D01", "text": "把门打开，不要回头"}],
            probe_payload=probe(),
            transcript="把门打开",
            segments=[{"start": 0.1, "end": 4.98, "text": "把门打开"}],
            minimum_recall=0.75,
        )
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(
            any("dialogue_recall" in item for item in report["failures"])
        )
        self.assertIn("dialogue_tail_clipped_or_unverified", report["failures"])


if __name__ == "__main__":
    unittest.main()
