"""S7 caption timing: every unit clip is transcribed concurrently, keyed by stem.

stage_s7 used to run one whisper pass per unit in a serial loop before burning in
subtitles.  The clips are independent, and the subtitle builder consumes a
dict keyed by clip stem, so completion order carries no meaning.

The model is shared on purpose: faster-whisper wraps ctranslate2, which accepts
concurrent calls on one model, and one model per worker would multiply memory.
"""

from __future__ import annotations

import sys
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
NALU_TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
for _path in (str(REPO), str(NALU_TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import nalu_pipeline  # noqa: E402


class _Segment:
    def __init__(self, start: float, end: float, text: str):
        self.start, self.end, self.text = start, end, text


class _FakeModel:
    def __init__(self, on_transcribe=None):
        self.on_transcribe = on_transcribe or (lambda _path: None)
        self.calls: list[str] = []

    def transcribe(self, path, **_kwargs):
        self.calls.append(str(path))
        self.on_transcribe(path)
        return iter([_Segment(0.1, 1.9, " 台词 ")]), {"language": "zh"}


class TranscribeUnitsConcurrencyTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.media = Path(self.tmp.name)
        for index in range(4):
            (self.media / f"E99-VU-{index:03d}.mp4").write_bytes(b"mp4")

    def _run(self, model: _FakeModel, *, env=None):
        fake_module = types.SimpleNamespace(WhisperModel=lambda *a, **k: model)
        with mock.patch.dict("os.environ", env or {}), \
             mock.patch.dict(sys.modules, {"faster_whisper": fake_module}):
            return nalu_pipeline.transcribe_units(mock.Mock(), self.media, "E99")

    def test_units_are_transcribed_concurrently(self):
        barrier = threading.Barrier(4, timeout=4.0)
        model = _FakeModel(on_transcribe=lambda _p: barrier.wait())
        result = self._run(model, env={"NALU_S7_ASR_WORKERS": "4"})
        self.assertEqual(len(result), 4)

    def test_results_are_keyed_by_clip_stem(self):
        model = _FakeModel()
        result = self._run(model)
        self.assertEqual(sorted(result), [f"E99-VU-{i:03d}" for i in range(4)])
        self.assertEqual(result["E99-VU-000"], [{"start": 0.1, "end": 1.9, "text": "台词"}])

    def test_one_failing_unit_fails_the_step(self):
        def boom(path):
            if str(path).endswith("E99-VU-002.mp4"):
                raise RuntimeError("whisper decode failed")

        model = _FakeModel(on_transcribe=boom)
        with self.assertRaisesRegex(RuntimeError, "whisper decode failed"):
            self._run(model, env={"NALU_S7_ASR_WORKERS": "2"})


class WhisperModelConstructionTest(unittest.TestCase):
    """The model is constructed once and shared by every transcribing worker."""

    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.media = Path(self.tmp.name)
        for index in range(3):
            (self.media / f"E99-VU-{index:03d}.mp4").write_bytes(b"mp4")

    def test_model_is_constructed_once_per_run(self):
        constructions: list[int] = []

        class _CountingModel(_FakeModel):
            def __init__(self, *args, **kwargs):
                constructions.append(1)
                super().__init__()

        fake_module = types.SimpleNamespace(WhisperModel=lambda *a, **k: _CountingModel())
        with mock.patch.dict("os.environ", {"NALU_S7_ASR_WORKERS": "3"}), \
             mock.patch.dict(sys.modules, {"faster_whisper": fake_module}):
            nalu_pipeline.transcribe_units(mock.Mock(), self.media, "E99")
        self.assertEqual(len(constructions), 1,
                         "MODEL_PER_WORKER: whisper was loaded once per worker; the model "
                         "wraps ctranslate2 and is meant to be shared")

    def test_worker_bound_defaults_and_falls_back_on_a_bad_value(self):
        seen: list[int | None] = []

        class _CountingModel(_FakeModel):
            pass

        fake_module = types.SimpleNamespace(WhisperModel=lambda *a, **k: _CountingModel())
        with mock.patch("concurrent.futures.ThreadPoolExecutor") as pool:
            pool.return_value.__enter__.return_value.submit.side_effect = (
                lambda fn, *a, **k: types.SimpleNamespace(result=lambda: fn(*a, **k)))
            for value in ("3", "not-a-number"):
                with mock.patch.dict("os.environ", {"NALU_S7_ASR_WORKERS": value}), \
                     mock.patch.dict(sys.modules, {"faster_whisper": fake_module}):
                    nalu_pipeline.transcribe_units(mock.Mock(), self.media, "E99")
                seen.append(pool.call_args.kwargs.get("max_workers"))
        self.assertEqual(seen, [3, 2],
                         "an unparsable NALU_S7_ASR_WORKERS must fall back to the default of 2")

    def test_empty_media_dir_returns_empty_without_loading_a_model(self):
        constructed: list[int] = []
        fake_module = types.SimpleNamespace(
            WhisperModel=lambda *a, **k: constructed.append(1))
        empty = self.media / "empty"
        empty.mkdir()
        with mock.patch.dict(sys.modules, {"faster_whisper": fake_module}):
            result = nalu_pipeline.transcribe_units(mock.Mock(), empty, "E99")
        self.assertEqual(result, {})
        self.assertEqual(constructed, [], "no clip means no model load")


if __name__ == "__main__":
    unittest.main()
