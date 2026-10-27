"""Lab urban E03 fixes (line owner 2026-10-23), CAMERA_GRAMMAR_V1 episodes only:
leading vocal burst mute at S7, objective Q2 face count, per-episode end card.  Unstamped
episodes see no change."""

from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
NALU_TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
for _path in (str(REPO), str(REPO / "tools"), str(NALU_TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import dialogue_leading_burst as burst  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
STAMPED = {"episode": "E99", "camera_grammar_policy": "CAMERA_GRAMMAR_V1"}
UNSTAMPED = {"episode": "E99"}


def envelope(burst_windows=10, burst_db=-12.0, silence_windows=150, silence_db=-80.0, speech_db=-20.0,
             speech_windows=100):
    return [burst_db] * burst_windows + [silence_db] * silence_windows + [speech_db] * speech_windows


def write_clip(path: Path, segments: list[tuple[float, float]], rate: int = 48000) -> Path:
    """Mono wav of (seconds, amplitude) sine segments muxed under a black 720x1280 picture."""
    wav = path.with_suffix(".wav")
    frames = bytearray()
    t = 0
    for seconds, amp in segments:
        for _ in range(int(seconds * rate)):
            frames += struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * 220 * t / rate)))
            t += 1
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    total = sum(s for s, _ in segments)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=black:s=720x1280:r=24:d={total}",
                    "-i", str(wav), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000",
                    "-shortest", str(path)], check=True)
    return path


def rms_db(path: Path, start: float, seconds: float) -> float:
    pcm = subprocess.run([FFMPEG, "-v", "error", "-ss", str(start), "-t", str(seconds), "-i", str(path),
                          "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    vals = struct.unpack(f"<{len(pcm) // 4}f", pcm[:len(pcm) // 4 * 4])
    return 20 * math.log10(math.sqrt(sum(v * v for v in vals) / max(1, len(vals))) + 1e-9)


class LeadingBurstPlanTests(unittest.TestCase):
    def test_detects_burst_then_silence(self):
        found = burst.detect(envelope())
        self.assertEqual(found["burst_end_seconds"], 0.1)
        self.assertEqual(found["silence_end_seconds"], 1.6)
        self.assertEqual(found["speech_onset_seconds"], 1.6)

    def test_no_burst_when_quiet_start_or_no_silence(self):
        self.assertIsNone(burst.detect(envelope(burst_db=-45.0)))
        self.assertIsNone(burst.detect(envelope(silence_db=-50.0)))      # pause not near-silent
        self.assertIsNone(burst.detect(envelope(silence_windows=20)))    # silence shorter than 0.25 s
        self.assertIsNone(burst.detect(envelope(burst_windows=30)))      # loud for 0.3 s = a real word

    def test_line_starting_at_frame_zero_is_untouched(self):
        found = burst.detect(envelope())
        # ASR line wholly inside the burst + silence: it IS the start of the line -> keep
        self.assertEqual(burst.judge(found, [{"start": 0.0, "end": 0.4, "text": "嗯"}]),
                         (False, "LINE_STARTS_AT_UNIT_START"))
        self.assertEqual(burst.judge(found, [{"start": 1.6, "end": 4.0, "text": "客户"}])[0], True)
        # whisper snaps the first segment to 0.0 though speech resumes after the silence (E03-VU-007)
        self.assertEqual(burst.judge(found, [{"start": 0.0, "end": 5.0, "text": "出了问题"}]),
                         (True, "MUTED_ASR_START_SNAPPED_SPEECH_RESUMES_AFTER_SILENCE"))
        self.assertEqual(burst.judge(None, []), (False, "NO_LEADING_BURST"))

    def test_timeline_windows_follow_audio_clips(self):
        report = {"units": [{"unit_id": "U2", "muted": True, "mute_source_seconds": [0.0, 0.12]},
                            {"unit_id": "U3", "muted": False}]}
        project = {"timeline": {"audioTracks": [{"clips": [
            {"start": 0.0, "in": 0.0, "metadata": {"source_id": "U1"}},
            {"start": 4.458, "in": 0.0, "metadata": {"source_id": "U2"}},
            {"start": 9.0, "in": 0.0, "metadata": {"source_id": "U3"}}]}]}}
        self.assertEqual(burst.timeline_windows(report, project),
                         [{"unit_id": "U2", "start_seconds": 4.458, "end_seconds": 4.578}])
        expr = burst.gain_expression(burst.timeline_windows(report, project))
        self.assertIn("4.458000", expr)
        self.assertIn("4.578000", expr)
        self.assertEqual(burst.gain_expression([]), "1")


@unittest.skipUnless(FFMPEG, "ffmpeg required")
class LeadingBurstS7Tests(unittest.TestCase):
    def _ctx(self, root: Path, contract: dict):
        (root / "video").mkdir()
        (root / "assembly").mkdir()
        c = root / "contract.json"
        c.write_text(json.dumps(contract))
        write_clip(root / "video" / "E99-VU-001.mp4", [(2.0, 0.3)])
        write_clip(root / "video" / "E99-VU-002.mp4", [(0.1, 0.5), (1.2, 0.0), (1.2, 0.3)])
        picture = write_clip(root / "native.mp4", [(2.0, 0.3), (0.1, 0.5), (1.2, 0.0), (1.2, 0.3)])
        project = root / "project.json"
        project.write_text(json.dumps({"timeline": {"audioTracks": [{"clips": [
            {"start": 0.0, "in": 0.0, "duration": 2.0, "metadata": {"source_id": "E99-VU-001"}},
            {"start": 2.0, "in": 0.0, "duration": 2.5, "metadata": {"source_id": "E99-VU-002"}}]}]}}))
        ctx = mock.Mock(episode="E99")
        ctx.p = mock.Mock(contract=c, video_media=root / "video", assembly=root / "assembly",
                          agentcut_project=project)
        return ctx, picture

    def test_stamped_mutes_burst_keeps_video_and_line(self):
        import nalu_pipeline
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ctx, picture = self._ctx(root, STAMPED)
            res = nalu_pipeline.StageResult(nalu_pipeline.BLOCKED)
            asr = {"E99-VU-001": [{"start": 0.0, "end": 2.0, "text": "一"}],
                   "E99-VU-002": [{"start": 0.0, "end": 2.5, "text": "二"}]}
            out = nalu_pipeline.s7_leading_burst_mute(ctx, res, picture, asr)
            self.assertEqual(out.name, "E99_picture_native_burstmute.mp4")
            report = json.loads((root / "assembly" / "E99_DIALOGUE_LEADING_BURST.json").read_text())
            self.assertEqual([r["unit_id"] for r in report["units"] if r["muted"]], ["E99-VU-002"])
            self.assertEqual(report["status"], "APPLIED")
            self.assertGreater(rms_db(picture, 2.0, 0.08), -20)
            self.assertLess(rms_db(out, 2.0, 0.08), -60)
            self.assertAlmostEqual(rms_db(out, 3.5, 0.5), rms_db(picture, 3.5, 0.5), delta=0.5)
            self.assertAlmostEqual(rms_db(out, 0.5, 1.0), rms_db(picture, 0.5, 1.0), delta=0.5)
            self.assertEqual(nalu_pipeline._video_stream_hash(out), nalu_pipeline._video_stream_hash(picture))

    def test_unstamped_untouched_and_writes_nothing(self):
        import nalu_pipeline
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ctx, picture = self._ctx(root, UNSTAMPED)
            res = nalu_pipeline.StageResult(nalu_pipeline.BLOCKED)
            self.assertEqual(nalu_pipeline.s7_leading_burst_mute(ctx, res, picture, None), picture)
            self.assertEqual(nalu_pipeline.s7_leading_burst_mute(ctx, res, picture, {"E99-VU-002": []}), picture)
            self.assertEqual(list((root / "assembly").iterdir()), [])
            self.assertNotIn("dialogue_leading_burst", res.details)


class FaceCountTests(unittest.TestCase):
    EXP = {"cast": [{"character_id": "CHAR-A", "face_visibility": "FRONT_VISIBLE"},
                    {"character_id": "CHAR-A", "face_visibility": "FRONT_VISIBLE"},
                    {"character_id": "CHAR-B", "face_visibility": "OVER_THE_SHOULDER_BACK"},
                    {"character_id": "CHAR-V", "face_visibility": "OFFSCREEN_VOICE_ONLY"},
                    {"character_id": "CRE-CAT", "face_visibility": "VISIBLE_PER_FRAME_CONTENT"}],
           "creature_cards": {"CRE-CAT": {}}}

    @staticmethod
    def frames(counts):
        return [{"frame_index": i + 1, "at_seconds": i, "faces": n} for i, n in enumerate(counts)]

    def test_budget_counts_humans_who_can_show_a_face(self):
        import video_q2_builder as q2
        self.assertEqual(q2.declared_face_budget(self.EXP), (2, ["CHAR-A", "CHAR-B"]))

    def test_two_frames_over_budget_fail(self):
        import video_q2_builder as q2
        exp = {"cast": [{"character_id": "CHAR-A", "face_visibility": "FRONT_VISIBLE"}]}
        self.assertEqual(q2.face_count_verdict(exp, self.frames([1, 2, 1, 1, 1, 1]))["status"], "PASS")
        v = q2.face_count_verdict(exp, self.frames([1, 2, 1, 1, 2, 2]))
        self.assertEqual(v["status"], "FAIL")
        self.assertEqual(v["failure"], "OBJECTIVE_FACE_COUNT_EXCEEDS_DECLARED:f2=2>1,f5=2>1,f6=2>1")
        crowd = {**exp, "group_counts": {"S1": {"crowd": 12}}}
        self.assertEqual(q2.face_count_verdict(crowd, self.frames([5] * 6))["status"], "NOT_APPLICABLE")

    def test_objective_fail_overrides_reviewer_pass(self):
        import video_q2_builder as q2
        checks = [{"question_id": "cast_exactly_as_declared", "answer": "PASS", "reviewer_answer": "PASS"}]
        failures: list = []
        fail = {"status": "FAIL", "failure": "OBJECTIVE_FACE_COUNT_EXCEEDS_DECLARED:f2=2>1", "frames_over": []}
        self.assertTrue(q2.apply_face_count(fail, checks, failures))
        self.assertEqual(checks[0]["answer"], "FAIL")
        self.assertEqual(checks[0]["reviewer_answer"], "PASS")
        self.assertEqual(failures[0], "cast_exactly_as_declared")
        self.assertFalse(q2.apply_face_count({"status": "PASS"}, [], []))
        self.assertFalse(q2.apply_face_count(None, [], []))

    def test_measure_on_synthetic_frames(self):
        import numpy as np
        import video_q2_builder as q2
        from PIL import Image

        class Face:
            def __init__(self, h, score):
                self.bbox = np.array([10.0, 100.0, 110.0, 100.0 + h])
                self.det_score = score

        per_frame = iter([[Face(200, 0.9), Face(200, 0.8)], [Face(200, 0.9), Face(20, 0.9)],
                          [Face(200, 0.9), Face(200, 0.5)], [Face(200, 0.9), Face(190, 0.7)]])
        backend = mock.Mock()
        backend._app.get.side_effect = lambda image: next(per_frame)
        exp = {"cast": [{"character_id": "CHAR-A", "face_visibility": "FRONT_VISIBLE"}]}
        with tempfile.TemporaryDirectory() as td:
            rows = []
            for i in range(4):
                path = Path(td) / f"f{i}.png"
                Image.new("RGB", (72, 128)).resize((720, 1280)).save(path)
                rows.append({"path": str(path), "at_seconds": i * 1.0})
            with mock.patch.object(q2, "_insightface_backend", return_value=backend), \
                    mock.patch.object(q2, "engine_module"):
                v = q2.measure_face_count(exp, rows)
        # frame 2: tiny face dropped; frame 3: low det score dropped -> only frames 1 and 4 over
        self.assertEqual([r["faces"] for r in v["per_frame"]], [2, 1, 1, 2])
        self.assertEqual(v["status"], "FAIL")
        self.assertEqual([r["frame_index"] for r in v["frames_over"]], [1, 4])


class EndCardTests(unittest.TestCase):
    def test_display_number_from_brief(self):
        import nalu_opening_title as title
        self.assertEqual(title.title_lines({"title": "T", "episode_title": "X", "episode_display_number": 2},
                                           "E03", "zh"), ("T", "第二集 · X"))
        self.assertEqual(title.title_lines({"title": "T", "episode_title": "X"}, "E03", "zh"), ("T", "第三集 · X"))
        self.assertEqual(title.title_lines({"title": "T", "episode_display_number": 2}, "E03", "en"),
                         ("T", "EPISODE 02"))

    def _ctx(self, root: Path, contract: dict):
        (root / "assembly").mkdir()
        (root / "briefs").mkdir()
        (root / "briefs" / "E99_PRODUCTION_BRIEF.json").write_text(json.dumps(
            {"title": "Twelve Gazes", "episode_title": "The Door", "episode_display_number": 2}))
        c = root / "contract.json"
        c.write_text(json.dumps(contract))
        ctx = mock.Mock(episode="E99", language="en")
        ctx.p = mock.Mock(contract=c, assembly=root / "assembly")
        return ctx

    def test_unstamped_uses_global_card(self):
        import nalu_pipeline
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ctx = self._ctx(root, UNSTAMPED)
            res = nalu_pipeline.StageResult(nalu_pipeline.BLOCKED)
            with mock.patch.object(nalu_pipeline._np, "RUNTIME_ROOT", root):
                self.assertIsNone(nalu_pipeline.s7_episode_endcard(ctx, res))
            self.assertEqual(list((root / "assembly").iterdir()), [])
            self.assertNotIn("episode_endcard", res.details)

    @unittest.skipUnless(FFMPEG, "ffmpeg required")
    def test_stamped_renders_episode_card(self):
        import nalu_pipeline
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ctx = self._ctx(root, STAMPED)
            res = nalu_pipeline.StageResult(nalu_pipeline.BLOCKED)
            with mock.patch.object(nalu_pipeline._np, "RUNTIME_ROOT", root):
                out = nalu_pipeline.s7_episode_endcard(ctx, res)
            self.assertEqual(out, root / "assembly" / "E99_endcard_3s_9x16.mp4")
            self.assertTrue(out.is_file())
            self.assertEqual(res.details["episode_endcard"]["subtitle"], "EPISODE 02 · The Door")
            self.assertFalse((root / "brand").exists())

    def test_render_failure_falls_back(self):
        import nalu_pipeline
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ctx = self._ctx(root, STAMPED)
            res = nalu_pipeline.StageResult(nalu_pipeline.BLOCKED)
            with mock.patch.object(nalu_pipeline._np, "RUNTIME_ROOT", root), \
                    mock.patch.object(nalu_pipeline._media, "require_ffmpeg", side_effect=RuntimeError("x")):
                self.assertIsNone(nalu_pipeline.s7_episode_endcard(ctx, res))
            self.assertEqual(res.details["episode_endcard"]["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
