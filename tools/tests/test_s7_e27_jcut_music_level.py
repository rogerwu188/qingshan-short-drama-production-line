"""Device 1101 E27 deep review (2026-11-25): queue-reading dialogue, dips at cuts, line loudness jumps, the
fallback-share metric, and the hand-written S6 default-acceptance orders.

* J-cut: the next speaker's line enters 0.1-0.2 s before the picture cut (dialogue_jcut + the build's in-point +
  render_portable_timeline's audio pre-roll), lip sync kept, the previous line never overlapped or cut;
* music level B: the duck merges only tiny gaps and releases fast; the cue volume follows the measured dialogue;
* per-line loudness on the mix (line_loudness): outlier lines pulled to the median, gaps untouched;
* craft metrics: SCREENPLAY_V1 contracts measured from field_sources (E27 69.5 % was LEGACY fields that do not exist);
* post-generation QA: a content reject whose one paid redo is spent is admitted on the §5 default terms by the engine.
"""
from __future__ import annotations

import importlib.util
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import bgm_cue_shaping as shape  # noqa: E402
from tools import craft_metrics as cm  # noqa: E402
from tools import dialogue_jcut as jcut  # noqa: E402
from tools import line_loudness as ll  # noqa: E402
from tools import performance_cut as perf_cut  # noqa: E402
from tools import render_portable_timeline as rpt  # noqa: E402
from tools import s7_audio_smoothing as smooth  # noqa: E402
from tools import s7_edit_invariants as inv  # noqa: E402

SR = 48000
FFMPEG = shutil.which("ffmpeg")


def _load_runner():
    spec = importlib.util.spec_from_file_location("post_generation_qa_runner_e27",
                                                  TOOLS / "post_generation_qa_runner.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _contract() -> dict:
    return {"episode": "E27", "character_entities": [{"character_id": "CHAR-A"}, {"character_id": "CHAR-B"}],
            "audio_contract": {"dialogue_units": [
                {"shot_id": "S1", "speaker_id": "CHAR-A", "text": "one"},
                {"shot_id": "S2", "speaker_id": "CHAR-B", "text": "two"},
                {"shot_id": "S3", "speaker_id": "CHAR-B", "text": "three"}]}}


def _grouping() -> dict:
    return {"units": [{"unit_id": "E27-VU-001", "editorial_shot_ids": ["S1"]},
                      {"unit_id": "E27-VU-002", "editorial_shot_ids": ["S2"]},
                      {"unit_id": "E27-VU-003", "editorial_shot_ids": ["S3"]}]}


def _speaking(uid: str, *, after_in: float, after_out: float, line_start: float, word_end: float,
              speech_end: float | None = None) -> dict:
    return {"unit_id": uid, "kind": "SPEAKING", "status": "MATCHED", "original_seconds": 4.0,
            "before_in": after_in, "before_out": after_out, "after_in": after_in, "after_out": after_out,
            "line_start_seconds": line_start, "line_end_seconds": word_end, "reasons": [], "warnings": [],
            "tail_guard": {"word_end": word_end, "speech_end": speech_end}}


def _perf() -> dict:
    return {"episode": "E27", "before_total_seconds": 9.0, "units": [
        # A: line ends (sound) at 2.6, cut at 2.9 -> 0.3 s of tail
        _speaking("E27-VU-001", after_in=0.0, after_out=2.9, line_start=0.15, word_end=2.5, speech_end=2.6),
        # B (other speaker): in 0.35, line starts 0.5; its own line sounds until the cut (no room for C)
        _speaking("E27-VU-002", after_in=0.35, after_out=3.4, line_start=0.5, word_end=3.3, speech_end=3.38),
        _speaking("E27-VU-003", after_in=0.2, after_out=3.0, line_start=0.35, word_end=2.7, speech_end=2.8)]}


class JcutPlanTest(unittest.TestCase):
    def test_applies_between_speakers_after_the_previous_line_ended(self) -> None:
        report = jcut.plan(_perf(), _contract(), _grouping(), environ={})
        first, second = report["rows"]
        self.assertEqual(first["status"], "APPLIED", first)
        self.assertEqual(first["overlap"], 0.15)
        self.assertEqual(first["after_in"], 0.65)          # line start 0.5 + 0.15 heard under the previous shot
        self.assertEqual(first["preroll"], 0.18)           # + the 30 ms fade-in in the pre-line silence
        self.assertEqual(first["shift"], 0.3)              # lead 0.15 + overlap 0.15
        # the incoming voice enters after the previous line's sound end + the voice gap: never two voices at once
        cut = first["cut_out"]
        self.assertGreaterEqual((cut - first["preroll"]) - first["sound_end"], jcut.MIN_VOICE_GAP_SECONDS - 1e-9)
        self.assertEqual(second["status"], "SKIPPED:SAME_SPEAKER")
        self.assertEqual(report["applied"], 1)

    def test_previous_line_still_sounding_is_never_overlapped(self) -> None:
        perf = _perf()
        perf["units"][0]["tail_guard"]["speech_end"] = 2.78   # 0.12 s to the cut: no room for 0.1 s + gap + fade
        row = jcut.plan(perf, _contract(), _grouping(), environ={})["rows"][0]
        self.assertEqual(row["status"], "SKIPPED:PREVIOUS_LINE_STILL_SOUNDING")
        perf["units"][0]["tail_guard"]["speech_end"] = None   # no measured decay: word end + 0.25 s assumed
        perf["units"][0]["tail_guard"]["word_end"] = 2.6
        row = jcut.plan(perf, _contract(), _grouping(), environ={})["rows"][0]
        self.assertEqual(row["status"], "SKIPPED:PREVIOUS_LINE_STILL_SOUNDING")

    def test_switch_range_and_exclusions(self) -> None:
        self.assertEqual(jcut.plan(_perf(), _contract(), _grouping(), environ={"NALU_S7_JCUT": "off"})["applied"], 0)
        self.assertEqual(jcut.overlap_seconds({"NALU_S7_JCUT_SECONDS": "0.5"}), 0.2)
        self.assertEqual(jcut.overlap_seconds({"NALU_S7_JCUT_SECONDS": "0.01"}), 0.1)
        report = jcut.plan(_perf(), _contract(), _grouping(), skip_units={"E27-VU-002"}, environ={})
        self.assertEqual(report["rows"][0]["status"], "SKIPPED:UNIT_EXCLUDED")

    def test_in_point_reaches_the_head_trim_report(self) -> None:
        perf = _perf()
        report = jcut.plan(perf, _contract(), _grouping(), environ={})
        self.assertEqual(jcut.apply_to_performance_cut(perf, report), ["E27-VU-002"])
        row = perf["units"][1]
        self.assertEqual(row["after_in"], 0.65)
        self.assertIn("JCUT_IN", row["reasons"])
        tail = {"units": [{"unit_id": r["unit_id"]} for r in perf["units"]]}
        head = {"units": [{"unit_id": r["unit_id"]} for r in perf["units"]]}
        _tail, head = perf_cut.merge(tail, head, perf)
        merged = {r["unit_id"]: r for r in head["units"]}
        self.assertEqual(merged["E27-VU-002"]["head_cut_seconds"], 0.65)
        self.assertTrue(merged["E27-VU-002"]["trimmed"])
        self.assertFalse(merged["E27-VU-001"].get("trimmed"))   # the previous unit's cut does not move


class JcutPipelineStepTest(unittest.TestCase):
    def test_step_writes_report_and_skips_vo_and_recut_units(self) -> None:
        import nalu_pipeline as npl  # noqa: PLC0415
        with tempfile.TemporaryDirectory() as td:
            ctx = mock.Mock(episode="E27", p=mock.Mock(assembly=Path(td)))
            res = mock.Mock(receipts=[], details={})
            perf = _perf()
            report = npl.s7_dialogue_jcut(ctx, res, perf, _contract(), _grouping(), {})
            self.assertEqual(report["applied"], 1)
            self.assertEqual(perf["units"][1]["after_in"], 0.65)
            self.assertTrue((Path(td) / "E27_DIALOGUE_JCUT.json").is_file())
            self.assertEqual(res.details["dialogue_jcut"]["applied"], 1)
            (Path(td) / "E27_UNIT_RECUT_PLAN.json").write_text(json.dumps({"units": {"E27-VU-002": {}}}))
            perf = _perf()
            self.assertEqual(npl.s7_dialogue_jcut(ctx, res, perf, _contract(), _grouping(), {})["applied"], 0)
            perf = _perf()
            (Path(td) / "E27_UNIT_RECUT_PLAN.json").unlink()
            self.assertEqual(npl.s7_dialogue_jcut(ctx, res, perf, _contract(), _grouping(),
                                                  {"E27-VU-001": [3.0]})["applied"], 0)


class JcutBuildTest(unittest.TestCase):
    """The AgentCut build registers the pre-roll only when the head-trim in-point is the J-cut's; else it restores it."""

    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(ROOT / "tools" / "tests"))
        import test_dialogue_tail_trim as tail_tests  # noqa: PLC0415
        cls._fixture = tail_tests.BuildTests._fixture
        cls._build = tail_tests.BuildTests._build

    def _reports(self, root: Path, head_in: float) -> tuple[Path, Path]:
        head = root / "head.json"
        head.write_text(json.dumps({"units": [{"unit_id": "E99-VU-002", "trimmed": True, "head_cut_seconds": head_in}]}))
        jc = root / "jcut.json"
        jc.write_text(json.dumps({"rows": [{"from_unit_id": "E99-VU-001", "to_unit_id": "E99-VU-002",
                                            "status": "APPLIED", "before_in": 0.35, "after_in": 0.65,
                                            "overlap": 0.15, "preroll": 0.18, "fade_in": 0.03, "fade_out": 0.03}]}))
        return head, jc

    def test_honoured_jcut_is_registered_for_the_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            head, jc = self._reports(root, 0.65)
            payload = json.loads(self._build(root, "j", dialogue_head_trim=head, dialogue_jcut=jc).read_text())
            cuts = payload["metadata"]["audio_jcut"]["cuts"]
            self.assertEqual([(c["index"], c["to_unit_id"], c["preroll_seconds"]) for c in cuts],
                             [(1, "E99-VU-002", 0.18)])
            video = payload["timeline"]["videoTracks"][0]["clips"]
            self.assertEqual(video[1]["in"], 0.65)

    def test_unhonoured_jcut_gets_its_in_point_back(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            head, jc = self._reports(root, 0.65)
            rows = json.loads(jc.read_text())
            rows["rows"][0]["from_unit_id"] = "E99-VU-000"          # not the clip before it on the timeline
            jc.write_text(json.dumps(rows))
            payload = json.loads(self._build(root, "r", dialogue_head_trim=head, dialogue_jcut=jc).read_text())
            video = payload["timeline"]["videoTracks"][0]["clips"]
            self.assertEqual(video[1]["in"], 0.35)                     # no syllable of the line is lost
            self.assertEqual(payload["metadata"]["audio_jcut"]["cuts"], [])
            self.assertEqual(payload["metadata"]["audio_jcut"]["reverted_units"], ["E99-VU-002"])


class PlacementPlanTest(unittest.TestCase):
    def test_jcut_preroll_and_short_fades(self) -> None:
        rows = [{"input": 0, "path": "a", "in": 0.0, "volume": 0.78, "duration": 2.0},
                {"input": 1, "path": "b", "in": 0.65, "volume": 0.78, "duration": 2.0},
                {"input": 2, "path": "c", "in": 0.0, "volume": 0.78, "duration": 2.0}]
        audios = [{"in": r["in"], "duration": r["duration"]} for r in rows]
        placed = rpt.audio_placement_plan(rows, audios, 0.04, [{"index": 1, "preroll_seconds": 0.18,
                                                               "fade_in_seconds": 0.03, "fade_out_seconds": 0.03}],
                                          [4.0, 4.0, 2.0])
        a, b, c = placed
        self.assertEqual(b["place"], round(2.0 - 0.18, 6))          # starts 0.18 s before its picture cut ...
        self.assertEqual(b["src_start"], round(0.65 - 0.18, 6))     # ... from its own source: lip sync kept
        self.assertEqual(b["fade_in"], 0.03)
        self.assertEqual(a["fade_out"], 0.03)                       # outgoing fades only at the cut
        self.assertAlmostEqual(a["place"] + a["length"], 2.015, places=6)   # 15 ms of its own tail handle
        self.assertEqual(c["cut_mode_in"], "CROSSFADE")              # an ordinary cut keeps its 40 ms crossfade
        self.assertEqual(c["fade_in"], 0.04)


def _tone(n: int, freq: float, amp: float) -> np.ndarray:
    t = np.arange(n) / SR
    return amp * np.sin(2 * np.pi * freq * t)


def _band_rms(x: np.ndarray, freq: float) -> float:
    t = np.arange(len(x)) / SR
    return float(abs(np.mean(x * np.exp(-2j * np.pi * freq * t))) * 2)


@unittest.skipUnless(FFMPEG, "ffmpeg required")
class JcutRenderTest(unittest.TestCase):
    """Synthetic clips: A (red, 440 Hz line 0.15-2.6 s), B (blue, 1000 Hz line from 0.5 s), real ffmpeg render."""

    def _clip(self, root: Path, name: str, color: str, line: tuple[float, float], freq: float) -> Path:
        n = int(4.0 * SR)
        audio = np.random.default_rng(1).normal(0, 0.002, n)            # room tone
        a, b = int(line[0] * SR), int(line[1] * SR)
        audio[a:b] += _tone(b - a, freq, 0.3)
        wav = root / f"{name}.wav"
        pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
        import wave
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
        out = root / f"{name}.mp4"
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=72x128:r=24:d=4",
                        "-i", str(wav), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                        str(out)], check=True)
        return out

    def test_line_enters_before_the_picture_cut_in_sync(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = self._clip(root, "a", "red", (0.15, 2.6), 440.0)
            b = self._clip(root, "b", "blue", (0.5, 3.8), 1000.0)
            clips_v = [{"source": str(a), "start": 0.0, "in": 0.0, "duration": 2.9, "metadata": {"source_id": "A"}},
                       {"source": str(b), "start": 2.9, "in": 0.65, "duration": 2.75, "metadata": {"source_id": "B"}}]
            clips_a = [{**c, "volume": 0.78} for c in clips_v]
            project = {"metadata": {"audio_cut_crossfade": {"seconds": 0.04, "curve": "qsin"},
                                    "audio_jcut": {"cuts": [{"index": 1, "preroll_seconds": 0.18, "overlap_seconds": 0.15,
                                                             "fade_in_seconds": 0.03, "fade_out_seconds": 0.03}]}},
                       "output": {"path": str(root / "out.mp4"), "width": 72, "height": 128},
                       "timeline": {"videoTracks": [{"clips": clips_v}], "audioTracks": [{"clips": clips_a}]}}
            path = root / "p.json"
            path.write_text(json.dumps(project), encoding="utf-8")
            subprocess.run(rpt.build_ffmpeg_command(path), check=True)
            dec = subprocess.run([FFMPEG, "-v", "error", "-i", str(root / "out.mp4"), "-ac", "1", "-ar", str(SR),
                                  "-f", "f32le", "-"], capture_output=True, check=True).stdout
            x = np.frombuffer(dec, dtype=np.float32)
            cut = 2.9

            def seg(t0: float, t1: float) -> np.ndarray:
                return x[int(t0 * SR):int(t1 * SR)]
            self.assertAlmostEqual(len(x) / SR, 5.65, delta=0.06)
            # 1000 Hz (B's line) is heard 0.15 s before the cut, under A's picture ...
            self.assertGreater(_band_rms(seg(cut - 0.13, cut - 0.01), 1000.0), 0.05)
            # ... and 440 Hz (A's line, ended at 2.6) is not: the two voices never overlap
            self.assertLess(_band_rms(seg(cut - 0.13, cut - 0.01), 440.0), 0.01)
            self.assertLess(_band_rms(seg(cut - 0.25, cut - 0.19), 1000.0), 0.02)   # nothing before the pre-roll
            # no dip at the cut: every 10 ms frame within +-60 ms carries B's line
            frames = [float(np.sqrt(np.mean(seg(t, t + 0.01) ** 2))) for t in np.arange(cut - 0.06, cut + 0.06, 0.01)]
            self.assertGreater(min(frames), 0.05)
            # lip sync: B's line keeps its source timing (source 0.5 s -> output cut - 0.15)
            env = np.array([_band_rms(seg(t, t + 0.01), 1000.0) for t in np.arange(cut - 0.3, cut, 0.01)])
            onset = cut - 0.3 + 0.01 * int(np.argmax(env > 0.1))
            self.assertAlmostEqual(onset, cut - 0.15, delta=0.03)
            # the picture cut stays on the frame after A's tail: red before, blue after
            for t, want in ((cut - 0.06, "red"), (cut + 0.06, "blue")):
                rgb = subprocess.run([FFMPEG, "-v", "error", "-ss", f"{t:.3f}", "-i", str(root / "out.mp4"),
                                      "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                     capture_output=True, check=True).stdout
                px = np.frombuffer(rgb, dtype=np.uint8).reshape(-1, 3).mean(axis=0)
                self.assertEqual("red" if px[0] > px[2] else "blue", want, (t, px))


class MusicLevelBTest(unittest.TestCase):
    def test_duck_releases_in_short_gaps(self) -> None:
        level = shape.music_level({})
        self.assertEqual(level["duck_db"], -10.0)
        windows = [{"start": 1.0, "end": 3.0}, {"start": 3.5, "end": 5.0}, {"start": 5.1, "end": 6.0}]
        legacy = smooth.duck_shape(windows)
        b = smooth.duck_shape(windows, level)
        self.assertEqual(len(legacy["windows"]), 1)                 # 2.5 s merge: the 0.5 s gap stayed ducked
        self.assertEqual([(w["start"], w["end"]) for w in b["windows"]], [(1.0, 3.0), (3.5, 6.0)])
        self.assertEqual(b["release_s"], 0.3)
        self.assertIsNone(shape.music_level({"NALU_S7_MUSIC_LEVEL": "legacy"}))

    def test_gap_level_comes_up_between_lines(self) -> None:
        level = shape.music_level({})
        cue = {"timeline_start": 0.0, "dialogue_duck_db": level["duck_db"],
               "duck_shape": smooth.duck_shape([{"start": 1.0, "end": 3.0}, {"start": 3.6, "end": 5.0}], level)}
        expr = smooth.smooth_duck_expr(cue)

        def gain(t: float) -> float:
            return eval(expr.replace("PI", "math.pi").replace("clip(", "_clip("),  # noqa: S307 - our own expression
                        {"math": math, "cos": math.cos, "max": max, "min": min, "t": t,
                         "_clip": lambda v, lo, hi: max(lo, min(hi, v))})
        self.assertAlmostEqual(20 * math.log10(gain(2.0)), -10.0, places=2)       # under a line: -10 dB
        self.assertGreater(20 * math.log10(gain(3.35)), -1.0)                     # 0.6 s gap: back up (no dip)

    def test_volume_sits_below_dialogue(self) -> None:
        level = shape.music_level({})
        volume, basis = shape.level_b_volume(-14.0, -16.0, level, 0.24)
        self.assertEqual(basis, "MUSIC_LEVEL_B")
        self.assertAlmostEqual(20 * math.log10(volume), -8.0, places=2)      # -14 -> -22 LUFS = 6 LU under -16
        self.assertEqual(shape.level_b_volume(None, -16.0, level, 0.24), (0.24, "AUTHORED_VOLUME_NOT_MEASURED"))


class LineLoudnessTest(unittest.TestCase):
    def test_outlier_lines_pulled_to_the_median_gaps_untouched(self) -> None:
        n = int(9.0 * SR)
        audio = np.random.default_rng(3).normal(0, 0.003, (n, 2)).astype(np.float32)
        amps = {(0.5, 2.5): 0.05, (3.0, 5.0): 0.1, (5.5, 7.5): 0.025}          # ~6 dB jumps line to line
        windows = []
        for (a, b), amp in amps.items():
            i, j = int(a * SR), int(b * SR)
            audio[i:j] += _tone(j - i, 300.0, amp)[:, None]
            windows.append({"start": a, "end": b})
        before = ll.measure_lines(audio, SR, windows)
        self.assertGreater(before[1]["lufs"] - before[2]["lufs"], 11.0)
        out, report = ll.level_lines(audio, SR, windows)
        after = [r["lufs"] for r in ll.measure_lines(out, SR, windows)]
        self.assertEqual(report["status"], "APPLIED")
        self.assertLess(max(after) - min(after), 2.0)                             # within +-1 LU of the median
        gap = slice(int(2.65 * SR), int(2.85 * SR))
        np.testing.assert_allclose(out[gap], audio[gap], rtol=1e-5, atol=1e-7)    # room tone in the gap unchanged


class FallbackShareTest(unittest.TestCase):
    def _shot(self, sources: dict, line: bool) -> dict:
        return {"shot_id": "x", "scene_id": "S1", "target_seconds": 3,
                "prompt_spec": {"dialogue": "A：hi" if line else "", "cast": [],
                                "action": {"field_sources": sources, "physical_causality": "由A的这一句引出"}}}

    def test_screenplay_contract_reads_field_sources(self) -> None:
        contract = {"writer_format": "SCREENPLAY_V1", "shots": [
            self._shot({"primary_action": "screenplay", "entry_state": "carried", "completion_state": "screenplay",
                        "body_action": "screenplay", "delivery": "screenplay"}, True),
            # a silent shot: no performance, so body_action / delivery "fallback" are not templates
            self._shot({"primary_action": "screenplay", "entry_state": "carried", "completion_state": "screenplay",
                        "body_action": "fallback", "delivery": "fallback"}, False),
            self._shot({"primary_action": "fallback", "entry_state": "fallback", "completion_state": "fallback",
                        "body_action": "fallback", "delivery": "fallback", "business_en": "fallback"}, True)]}
        got = cm.measure_contract(contract)
        self.assertEqual(got["fallback_basis"], "screenplay_field_sources")
        self.assertEqual(got["fallback_share_pct"], round(100 * 6 / 14, 1))
        legacy = cm.measure_contract({**contract, "writer_format": "LEGACY"})
        self.assertEqual(legacy["fallback_basis"], "legacy_action_fields")


class JcutEditInvariantTest(unittest.TestCase):
    def test_a_jcut_is_not_a_cut_inside_a_line(self) -> None:
        shots = [{"start_seconds": 0.0, "end_seconds": 2.9}, {"start_seconds": 2.9, "end_seconds": 5.6}]
        lines = [{"start": 0.15, "end": 2.6}, {"start": 2.75, "end": 5.4}]
        got = inv.measure_cut(shots=shots, lines=lines, s7_cuts=[2.9])
        self.assertEqual(got["counts"]["mid_line_cuts"], 0)
        got = inv.measure_cut(shots=shots, lines=[{"start": 2.3, "end": 5.4}], s7_cuts=[2.9])   # 0.6 s into a line: still flagged
        self.assertEqual(got["counts"]["mid_line_cuts"], 1)


class EngineDefaultAcceptanceTest(unittest.TestCase):
    def _row(self, uid: str, technical: str = "TECHNICAL_PASS_CONTENT_UNREVIEWED") -> dict:
        return {"unit_id": uid, "verdict": "REJECT", "media_sha256": "b" * 64, "media_path": f"/v/{uid}.mp4",
                "reasons": [f"voice:VOICE_OUT_OF_BAND:CHAR-A:{180.0}"], "primary_reason": "voice:VOICE_OUT_OF_BAND",
                "technical_qa": {"status": technical}}

    def _run(self, rows, used, environ=None, acceptance=None):
        qa = _load_runner()
        ledger = mock.Mock(reroll_number_for=lambda _l, _u: 1)
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(qa, "QaPaths", return_value=mock.Mock(reroll_ledger=Path(td) / "l.json")), \
                mock.patch.object(qa, "engine_module", return_value=ledger), \
                mock.patch.object(qa, "redo_already_used", side_effect=lambda _p, _e, uid, _n: used.get(uid)):
            out = qa.apply_engine_default_postgen_acceptance("E27", rows, Path(td), acceptance, environ=environ or {})
            written = {r["unit_id"]: json.loads((Path(td) / r["unit_id"] / f"{r['unit_id']}_POST_GENERATION_QA.json")
                                                .read_text(encoding="utf-8")) for r in rows if r["verdict"] == "ADMIT"}
        return out, written

    def test_redo_spent_content_reject_is_admitted_by_the_engine(self) -> None:
        rows = [self._row("E27-VU-005"), self._row("E27-VU-006"), self._row("E27-VU-007", "TECHNICAL_FAIL")]
        acceptance = {"orders_needed": [{"unit_id": u, "record_args": [f"--media {u}=x"]} for u in
                                        ("E27-VU-005", "E27-VU-006", "E27-VU-007")],
                      "still_rejected_unit_ids": ["E27-VU-005", "E27-VU-006", "E27-VU-007"], "record_hint": "x"}
        out, written = self._run(rows, {"E27-VU-005": "ONE_PAID_REDO_PER_UNIT_USED:SUPERSEDED_CLIP:x",
                                        "E27-VU-007": "ONE_PAID_REDO_PER_UNIT_USED:SUPERSEDED_CLIP:y"},
                                 acceptance=acceptance)
        self.assertEqual(out["accepted_unit_ids"], ["E27-VU-005"])
        rec = written["E27-VU-005"]
        self.assertEqual(rec["engine_verdict"], "REJECT")
        self.assertEqual(rec["engine_default_acceptance"]["approved_by"], "engine_default_terms")
        self.assertEqual(rec["engine_reasons"][0].split(":")[1], "VOICE_OUT_OF_BAND")
        self.assertEqual(rows[1]["verdict"], "REJECT")    # redo still available: the choice stays
        self.assertEqual(rows[2]["verdict"], "REJECT")    # technical failure: needs the owner's order
        self.assertEqual([n["unit_id"] for n in acceptance["orders_needed"]], ["E27-VU-006", "E27-VU-007"])
        self.assertNotIn("E27-VU-005", acceptance["record_hint"])

    def test_owner_review_or_switch_disables_it(self) -> None:
        for env in ({"NALU_OWNER_REVIEW_REQUIRED": "1"}, {"NALU_POSTGEN_ENGINE_DEFAULT_ACCEPT": "off"}):
            rows = [self._row("E27-VU-005")]
            out, _ = self._run(rows, {"E27-VU-005": "ONE_PAID_REDO_PER_UNIT_USED:x"}, environ=env)
            self.assertEqual(out["status"], "DISABLED")
            self.assertEqual(rows[0]["verdict"], "REJECT")


if __name__ == "__main__":
    unittest.main()
