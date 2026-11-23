#!/usr/bin/env python3
"""Device 1101 E24 full review (2026-11-23): S7 audio / edit / title fixes, all offline and free.

stray voices in silent units muted on the placed clip (VAD) + ambience only; H3 internal-cut fragments trimmed;
0.4 s sentence tail in the measured edit; per-line loudness match; BGM audible under dialogue; the opening title
moved off the faces."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
NALU_TOOLS = ROOT / "lines/nalu/runtime/tools"
for _p in (str(NALU_TOOLS), str(ROOT / "tools"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bgm_cue_shaping as shaping  # noqa: E402
import final_cut_audio_bed as bed  # noqa: E402
import final_fix_round as ffr  # noqa: E402
import h3_internal_cut_trim as ict  # noqa: E402
import nalu_opening_title as title  # noqa: E402
import performance_cut as pc  # noqa: E402
import s7_audio_smoothing as smooth  # noqa: E402
import silent_unit_stray_speech as stray  # noqa: E402
from build_measured_edit_constraints import build_measured_edit_constraints  # noqa: E402
from tools import final_cut_audience_detectors as det  # noqa: E402

SR = 16000
HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def synthetic_silent_unit(seconds: float = 4.0, voice: tuple[float, float] = (1.5, 2.3), seed: int = 3) -> np.ndarray:
    """Low rumble ambience (< 150 Hz) + a voiced murmur: a 140 Hz harmonic stack, 4 Hz syllable envelope."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    noise = rng.standard_normal(len(t))
    spec = np.fft.rfft(noise)
    spec[np.fft.rfftfreq(len(t), 1 / SR) > 150] = 0
    amb = np.fft.irfft(spec, len(t))
    amb = amb / np.sqrt(np.mean(amb ** 2)) * 10 ** (-38 / 20)
    voiced = sum(np.sin(2 * np.pi * 140 * k * t) / k for k in range(1, 20))
    env = (0.5 - 0.5 * np.cos(2 * np.pi * 4 * t)) * ((t >= voice[0]) & (t < voice[1]))
    return (amb + 0.08 * voiced * env).astype(np.float32)


def project(*clips: dict) -> dict:
    return {"timeline": {"audioTracks": [{"clips": list(clips)}]}}


def aclip(uid: str, start: float, source_in: float, duration: float, speaking: bool = False) -> dict:
    return {"source": f"/v/{uid}.mp4", "start": start, "in": source_in, "duration": duration,
            "metadata": {"source_id": uid, "dialogue_classification": "SPEAKING" if speaking else "NON_SPEAKING",
                         "expected_text": "你好" if speaking else ""}}


class StrayVoiceTests(unittest.TestCase):
    def test_energy_vad_finds_the_murmur_and_ignores_the_rumble(self):
        windows = stray.energy_vad(synthetic_silent_unit())
        self.assertEqual(len(windows), 1, windows)
        a, b = windows[0]
        self.assertTrue(1.4 <= a <= 1.7 and 2.1 <= b <= 2.4, windows)
        self.assertEqual(stray.energy_vad(synthetic_silent_unit(voice=(0.0, 0.0))), [])

    def test_plan_measures_the_placed_clip_and_never_touches_dialogue_units(self):
        calls = []

        def measure(src, a, d):
            calls.append((src, a, d))
            return {"method": "TEST", "windows": [[a + 0.5, a + 1.0], [a + d + 1.0, a + d + 2.0]]}

        rep = stray.plan(project(aclip("U1", 0.0, 0.0, 3.0, speaking=True), aclip("U2", 3.0, 0.4, 2.0),
                                 aclip("U3", 5.0, 0.0, 2.0)), measure, mode="ambience")
        self.assertEqual(calls, [("/v/U2.mp4", 0.4, 2.0), ("/v/U3.mp4", 0.0, 2.0)])   # placed in/duration
        rows = {r["unit_id"]: r for r in rep["units"]}
        self.assertEqual(rows["U1"]["reason"], "UNIT_HAS_DIALOGUE")
        self.assertEqual(rows["U2"]["vad_source_windows"], [[0.9, 1.4]])           # outside the placed part dropped
        self.assertTrue(rows["U2"]["flagged"])                                       # 0.5 s >= 0.3 s
        self.assertEqual(rep["mute_windows"][0], {"unit_id": "U2", "start_seconds": 3.5, "end_seconds": 4.0})
        self.assertEqual([w["unit_id"] for w in rep["ambience_windows"]], ["U2", "U3"])
        self.assertEqual(rep["ambience_windows"][0], {"unit_id": "U2", "start_seconds": 3.0, "end_seconds": 5.0})

    def test_contract_speaking_units_override_and_modes(self):
        measure = lambda src, a, d: {"method": "T", "windows": []}  # noqa: E731
        clips = project(aclip("U1", 0.0, 0.0, 2.0), aclip("U2", 2.0, 0.0, 2.0))
        rep = stray.plan(clips, measure, speaking_units={"U1"}, mode="ambience")
        self.assertEqual([w["unit_id"] for w in rep["ambience_windows"]], ["U2"])
        self.assertEqual(stray.plan(clips, measure, mode="speech_only")["ambience_windows"], [])
        self.assertEqual(stray.plan(clips, measure, mode="off")["ambience_units"], 0)
        self.assertEqual(stray.silent_audio_mode({stray.SILENT_AUDIO_ENV: "OFF"}), "off")
        self.assertEqual(stray.silent_audio_mode({}), "speech_only")   # default: full band kept (foley)
        self.assertEqual(stray.silent_audio_mode({stray.SILENT_AUDIO_ENV: "ambience"}), "ambience")

    def test_default_mode_mutes_speech_only_and_keeps_the_full_band(self):
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop(stray.SILENT_AUDIO_ENV, None)
            rep = stray.plan(project(aclip("U1", 0.0, 0.0, 2.0), aclip("U2", 2.0, 0.0, 2.0)),
                             lambda src, a, d: {"method": "T", "windows": [[0.5, 1.0]] if "U1" in src else []})
        self.assertEqual(rep["mode"], "speech_only")
        self.assertEqual(rep["ambience_windows"], [])
        self.assertEqual(rep["mute_windows"], [{"unit_id": "U1", "start_seconds": 0.5, "end_seconds": 1.0}])
        graph = stray.ambience_filter_complex(rep["mute_windows"], rep["ambience_windows"])
        self.assertIn("volume='0'", graph)           # no ambience path when nothing is replaced

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
    def test_filter_graph_mutes_the_voice_and_keeps_the_rumble(self):
        audio = np.concatenate([synthetic_silent_unit(voice=(0.5, 1.5)), synthetic_silent_unit(voice=(0.5, 1.5))])
        with tempfile.TemporaryDirectory() as td:
            raw, out = Path(td) / "in.f32", Path(td) / "out.f32"
            raw.write_bytes(audio.astype("<f4").tobytes())
            # unit 1 (0-4 s) is a dialogue unit (untouched), unit 2 (4-8 s) is silent: ambience only + mute window
            graph = stray.ambience_filter_complex([{"start_seconds": 4.5, "end_seconds": 5.5}],
                                                  [{"start_seconds": 4.0, "end_seconds": 8.0}])
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", str(raw),
                            "-filter_complex", graph, "-map", "[aout]", "-ac", "1", "-ar", str(SR), "-f", "f32le",
                            str(out)], check=True)
            got = np.frombuffer(out.read_bytes(), dtype="<f4")

        def db(x, a, b):
            seg = x[int(a * SR):int(b * SR)]
            return 20 * math.log10(math.sqrt(float(np.mean(seg ** 2))) + 1e-12)
        self.assertAlmostEqual(db(got, 0.6, 1.4), db(audio, 0.6, 1.4), delta=0.5)   # dialogue unit untouched
        self.assertLess(db(got, 4.6, 5.4), db(audio, 4.6, 5.4) - 40)                # murmur muted
        self.assertEqual(stray.energy_vad(got[int(4 * SR):]), [])                   # no voice left in unit 2
        self.assertAlmostEqual(db(got, 6.0, 7.5), db(audio, 6.0, 7.5), delta=3.0)    # rumble (ambience) kept
        self.assertEqual(len(got), len(audio))                                       # duration unchanged

    def test_s6_runner_flags_vad_speech_without_rejecting(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("pgqa_e24", NALU_TOOLS / "post_generation_qa_runner.py")
        qa = importlib.util.module_from_spec(spec)
        sys.modules["pgqa_e24"] = qa
        spec.loader.exec_module(qa)

        def fake_run(argv, *, timeout=1800):
            argv = [str(v) for v in argv]
            Path(argv[argv.index("--out") + 1]).write_text(json.dumps({"status": "PASS", "transcript": "",
                                                                        "duration_seconds": 4.0, "failures": []}))
            return types.SimpleNamespace(returncode=0, stderr="", stdout="")
        vad = {"type": "VAD_SPEECH_IN_SILENT_UNIT", "windows": [[1.5, 2.3]], "flagged_windows": [[1.5, 2.3]],
               "speech_seconds": 0.8, "flagged": True}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(qa, "_run", fake_run), \
                mock.patch.object(qa, "require_ffprobe", return_value="/bin/ffprobe"), \
                mock.patch.object(qa, "_vad_speech_in_silent_unit", lambda media: dict(vad)):
            result = qa.dialogue_check("E24-VU-010", Path(tmp) / "clip.mp4", [], Path(tmp), language="zh")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["advisories"], ["dialogue:vad_speech_in_silent_unit:MUTED_AT_S7:0.8s"])
        self.assertEqual(qa.LOW_CONFIDENCE_NO_SPEECH_MAX, 0.8)


class StrayVoicePipelineTests(unittest.TestCase):
    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
    def test_pipeline_step_mixes_the_native_cut_and_keeps_the_video_stream(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("nalu_pipeline_e24", NALU_TOOLS / "nalu_pipeline.py")
        npl = importlib.util.module_from_spec(spec)
        sys.modules["nalu_pipeline_e24"] = npl
        spec.loader.exec_module(npl)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clip = root / "E24-VU-010.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=160x284:r=24:d=4",
                            "-f", "lavfi", "-i", "sine=f=440:d=4:sample_rate=48000", "-shortest",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)], check=True)
            assembly = root / "assembly"; assembly.mkdir()
            agentcut = assembly / "E24_agentcut.json"
            agentcut.write_text(json.dumps(project(aclip("E24-VU-010", 0.0, 0.0, 4.0))))
            ctx = types.SimpleNamespace(episode="E24", p=types.SimpleNamespace(
                assembly=assembly, agentcut_project=agentcut, contract=root / "missing_contract.json"))
            res = types.SimpleNamespace(steps=[], receipts=[], details={})
            with mock.patch.dict("os.environ", {stray.SILENT_AUDIO_ENV: "ambience"}):
                out = npl.s7_silent_unit_stray_speech_mute(ctx, res, clip)
            report = json.loads((assembly / "E24_SILENT_UNIT_STRAY_SPEECH.json").read_text())
            self.assertEqual(report["status"], "APPLIED", report)
            self.assertEqual(report["ambience_units"], 1)
            self.assertNotEqual(out, clip)
            self.assertTrue(report["video_stream_bit_exact"])
            # the 440 Hz tone is in the speech band: the ambience-only unit drops it
            vol = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(out), "-af", "volumedetect", "-f", "null", "-"],
                                 capture_output=True, text=True).stderr
            self.assertLess(float(vol.split("mean_volume:")[1].split("dB")[0]), -45.0)


class InternalCutTests(unittest.TestCase):
    def test_e24_vu016_tail_flash_is_cut(self):
        # unit window 0-2.41 s, H3 cut at 2.13 s (0.28 s flash at the end), silent unit
        got = ict.choose_window((0.0, 2.41), [2.13], min_shot=1.2)
        self.assertEqual(got["status"], "TRIMMED")
        self.assertEqual(got["keep"], [0.0, 2.11])
        self.assertEqual(got["removed"], [[2.13, 2.41]])

    def test_e24_vu020_short_anchor_keeps_the_longer_side(self):
        got = ict.choose_window((0.0, 1.5), [1.13], min_shot=1.2)
        self.assertEqual((got["keep"], got["anchor_basis"]), ([0.0, 1.11], "LONGEST_SEGMENT"))
        self.assertEqual(got["left_fragments"], [])

    def test_the_line_picks_the_segment_and_is_never_cut(self):
        got = ict.choose_window((0.0, 2.13), [0.865], speech=[(1.0, 1.9)], min_shot=1.2)
        self.assertEqual(got["keep"], [0.865, 2.13])                      # head fragment removed
        self.assertEqual(got["anchor_basis"], "SCRIPTED_LINE")
        kept = ict.choose_window((0.0, 2.13), [0.865], speech=[(0.2, 1.3)], min_shot=1.2)
        self.assertEqual(kept["keep"], [0.0, 2.13])                       # the line crosses the cut: nothing cut
        self.assertEqual(kept["status"], "FRAGMENT_LEFT")
        self.assertEqual(kept["left_fragments"][0]["reason"], "CARRIES_THE_LINE")

    def test_designed_shots_stay_and_motion_peak_anchors_a_silent_unit(self):
        got = ict.choose_window((0.0, 5.0), [2.0, 4.6], min_shot=1.2)
        self.assertEqual(got["keep"], [0.0, 4.58])                         # 2.0 + 2.6 designed, 0.4 flash cut
        peak = ict.choose_window((0.0, 3.0), [0.5], anchor_time=0.3, min_shot=0.4)
        self.assertEqual(peak["anchor_basis"], "MOTION_PEAK")
        self.assertEqual(ict.choose_window((0.0, 3.0), [], min_shot=1.2)["status"], "NO_INTERNAL_CUT")

    def test_apply_tightens_the_performance_cut_row(self):
        perf = {"units": [
            {"unit_id": "U1", "kind": "SILENT", "original_seconds": 2.5, "after_in": 0.0, "after_out": 2.41,
             "reasons": []},
            {"unit_id": "U2", "kind": "SPEAKING", "original_seconds": 3.0, "after_in": 0.2, "after_out": 3.0,
             "line_start_seconds": 0.3, "line_end_seconds": 2.2, "reasons": ["TRIM_TAIL_TO_LINE"]},
            {"unit_id": "U3", "kind": "SILENT", "original_seconds": 3.0, "after_in": 0.0, "after_out": 3.0,
             "reasons": [], "vo_seconds": [2.0]}]}
        rep = ict.apply(perf, {"U1": [2.13], "U2": [2.3], "U3": [0.3]}, {}, skip_units={"U3"}, min_shot=1.2)
        u1, u2, u3 = perf["units"]
        self.assertEqual((u1["after_out"], u1["reasons"]), (2.11, [ict.REASON]))
        self.assertEqual((u2["after_in"], u2["after_out"]), (0.2, 3.0))     # 2.3 is inside the line's 0.25 s tail
        self.assertEqual(rep["left_fragments"][0]["unit_id"], "U2")
        self.assertEqual(u3["after_in"], 0.0)                               # V.O. hold untouched
        self.assertIn(ict.REASON, pc.REASONS)

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
    def test_scdet_finds_a_synthetic_internal_cut(self):
        with tempfile.TemporaryDirectory() as td:
            clip = Path(td) / "u.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=160x284:r=24:d=1.5",
                            "-f", "lavfi", "-i", "color=c=red:s=160x284:r=24:d=0.5", "-filter_complex",
                            "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-pix_fmt", "yuv420p", str(clip)],
                           check=True)
            cuts = ict.scene_cuts(clip)
        self.assertEqual(len(cuts), 1, cuts)
        self.assertAlmostEqual(cuts[0], 1.5, delta=0.05)

    def test_untrimmed_h3_fragment_is_a_p1_trigger(self):
        found = ffr.edit_measure_findings({"fragments": [
            {"start": 42.67, "end": 42.92, "seconds": 0.25, "speech_seconds": 0.0, "s7_cut": False}]})
        self.assertEqual((found[0]["severity"], found[0].get("trigger")), ("P1", True))
        mapped = ffr.map_findings(found, [{"unit_id": "U16", "output_start": 40.54, "output_end": 42.95}])
        self.assertTrue(ffr.triggered(False, mapped))
        s7 = ffr.edit_measure_findings({"fragments": [{"start": 1.0, "end": 1.5, "s7_cut": True}]})
        self.assertEqual((s7[0]["severity"], s7[0].get("trigger")), ("P2", None))


class TailTests(unittest.TestCase):
    def _build(self, dq: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "video"; video.mkdir()
            media = video / "U1.mp4"; media.write_bytes(b"x")
            pg = root / "pg" / "U1"; pg.mkdir(parents=True)
            (pg / "U1_POST_GENERATION_QA.json").write_text(json.dumps(
                {"unit_id": "U1", "media_path": str(media), "media_sha256": "a" * 64, "dialogue_qa": dq}))
            plan = root / "plan.json"
            plan.write_text(json.dumps({"units": [{"unit_id": "U1", "duration_seconds": 6.0}]}))
            out = root / "c.json"
            build_measured_edit_constraints(episode="E24", postgen_dir=root / "pg", video_media=video,
                                            grouping_plan=plan, out_constraints=out, out_evidence_dir=root / "ev")
            return json.loads(out.read_text())

    def test_sentence_tail_after_the_last_word(self):
        got = self._build({"status": "PASS", "recall_score": 1.0, "expected_line_count": 1, "segments": [
            {"start": 1.0, "end": 3.54, "text": "那就把他找出来",
             "words": [{"start": 1.0, "end": 3.14, "word": "那就把他找"}, {"start": 3.14, "end": 3.78, "word": "出来"}]}]})
        row = got["units"][0]
        self.assertAlmostEqual(row["recommended_source_out_seconds"], 4.18, places=2)   # 3.78 word end + 0.4
        self.assertEqual(row["trim_basis"], "PASS_DIALOGUE_QA_SEGMENTS")
        self.assertEqual(json.loads((ROOT / "configs/MEASURED_EDIT_POLICY_V1.json").read_text())
                         ["lines"]["nalu"]["trail_seconds"], 0.4)

    def test_non_pass_unit_uses_word_ends_tail_only(self):
        got = self._build({"status": "FAIL", "recall_score": 1.0, "expected_line_count": 1, "segments": [
            {"start": 1.2, "end": 2.0, "text": "消失", "words": [{"start": 1.2, "end": 2.1, "word": "消失"}]}]})
        row = got["units"][0]
        self.assertEqual((row["recommended_source_in_seconds"], row["recommended_source_out_seconds"]), (0.0, 2.5))
        self.assertEqual(row["trim_basis"], "ASR_WORD_ENDS_TAIL_ONLY")
        none = self._build({"status": "FAIL", "recall_score": 0.6, "expected_line_count": 1, "segments": [
            {"start": 1.2, "end": 2.0, "text": "x", "words": [{"start": 1.2, "end": 2.0, "word": "x"}]}]})
        self.assertEqual(none["units"], [])                                  # recall too low: full length


class LineLoudnessTests(unittest.TestCase):
    def test_line_gain_targets_minus_16_with_tolerance_and_clamp(self):
        self.assertEqual(smooth.plan_line_gain(-9.8)["gain_db"], -6.2)
        self.assertEqual(smooth.plan_line_gain(-15.0)["gain_db"], 0.0)        # within +-1.5 LU
        self.assertEqual(smooth.plan_line_gain(-30.0)["gain_db"], 9.0)        # clamped
        self.assertEqual(smooth.plan_line_gain(-60.0)["gain_db"], 0.0)        # no speech: never pumped
        self.assertEqual(smooth.MAX_UNIT_GAIN_DB, 9.0)

    def test_short_spans_join_a_neighbour(self):
        self.assertEqual(smooth.line_spans([(0.0, 1.0), (1.1, 1.3), (3.0, 4.0)]), [(0.0, 1.3), (3.0, 4.0)])

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
    def test_line_gain_expression_levels_two_lines(self):
        lines = [{"span": [0.0, 1.0], "gain_db": -6.0}, {"span": [1.5, 2.5], "gain_db": 3.0}]
        expr = smooth.line_gain_expression(lines)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "o.f32"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=2.5:sample_rate=16000",
                            "-af", f"asetnsamples=n=256:p=0,volume='{expr}':eval=frame", "-f", "f32le", str(out)],
                           check=True)
            x = np.frombuffer(out.read_bytes(), dtype="<f4")

        def db(a, b):
            seg = x[int(a * SR):int(b * SR)]
            return 20 * math.log10(math.sqrt(float(np.mean(seg ** 2))))
        ref = 20 * math.log10(0.125 / math.sqrt(2))   # lavfi sine amplitude 1/8
        self.assertAlmostEqual(db(0.1, 0.9) - ref, -6.0, delta=0.3)
        self.assertAlmostEqual(db(1.6, 2.4) - ref, 3.0, delta=0.3)

    def test_adjacent_delta_target_three_lu_records_and_six_blocks(self):
        self.assertEqual(det.DEFAULTS["adjacent_delta_max_lu"], 3.0)
        kw = dict(release_lufs=-16.0, tolerance=1.0, release_tp=-1.0, window_range=(-24, -10),
                  adjacent_delta_max=det.DEFAULTS["adjacent_delta_max_lu"],
                  adjacent_delta_block=det.DEFAULTS["adjacent_delta_block_lu"])
        rows = [{"start": 0.0, "end": 1.0, "lufs_window": -16.0}, {"start": 2.0, "end": 3.0, "lufs_window": -12.0}]
        got = det.decide_loudness(-16.0, -2.0, rows, **kw)
        self.assertEqual(got["status"], "PASS")
        self.assertEqual(len(got["evidence"]["adjacent_deltas_over_target"]), 1)
        rows[1]["lufs_window"] = -9.5
        self.assertEqual(det.decide_loudness(-16.0, -2.0, rows, **dict(kw, window_range=(-24, -9)))["status"], "FAIL")


class BgmLevelTests(unittest.TestCase):
    def test_pad_and_duck_levels(self):
        self.assertEqual(bed.PAD_LEVEL_DBFS, -30.0)
        self.assertEqual(bed.DUCK_MAX_DB, 10.0)                             # owner 2026-11-19: -10..-14 dB
        self.assertEqual(shaping.DUCK_DB, -10.0)
        self.assertEqual(smooth.STAMPED_DUCK_DB, -10.0)
        env = np.array([-60.0, -30.0, -20.0, -3.0])
        self.assertEqual(float(bed.duck_gain_db(env).min()), -10.0)         # never more than 10 dB under a line
        self.assertEqual(float(bed.duck_gain_db(env)[0]), 0.0)              # untouched in the gaps

    def test_pad_source_is_rendered_at_the_new_level(self):
        rng = np.random.default_rng(1)
        pad = bed.make_pad_source(rng.standard_normal((bed.SR * 2, 2)).astype(np.float32))
        rms_db = 20 * math.log10(math.sqrt(float(np.mean(pad.astype(np.float64) ** 2))))
        self.assertAlmostEqual(rms_db, -30.0, delta=0.1)


class TitlePlacementTests(unittest.TestCase):
    H = 1280

    def test_no_face_keeps_the_upper_third(self):
        got = title.choose_title_band(self.H, 200, [])
        self.assertEqual(got["band"], "UPPER_THIRD")
        self.assertEqual(got["top"], int(round(self.H / 3 - 100)))

    def test_face_in_the_upper_third_moves_the_title(self):
        eyes = [[220, 330, 500, 640]]          # E24: heroine's face at y 0.26-0.50
        got = title.choose_title_band(self.H, 200, eyes)
        self.assertTrue(got["clear_of_faces"])
        self.assertNotEqual(got["band"], "UPPER_THIRD")
        self.assertTrue(got["top"] + 200 <= 330 - title.FACE_MARGIN * self.H or got["top"] >= 640)

    def test_faces_top_and_middle_go_low_but_above_the_subtitles(self):
        got = title.choose_title_band(self.H, 200, [[200, 60, 520, 640]])
        self.assertEqual(got["band"], "LOWER")
        self.assertLessEqual(got["top"] + 200, title.SUBTITLE_BAND_TOP * self.H)
        full = title.choose_title_band(self.H, 200, [[0, 0, 720, 1280]])
        self.assertFalse(full["clear_of_faces"])

    def test_render_uses_the_placement(self):
        try:
            font, _src = title.resolve_font("en")
        except Exception:  # noqa: BLE001
            self.skipTest("no title font on this machine")
        with tempfile.TemporaryDirectory() as td:
            info = title.render_overlay_png("Twelve Gazes", "EPISODE 24", font, 720, 1280, Path(td) / "t.png",
                                            faces=[[220, 330, 500, 640]])
            from PIL import Image
            alpha = np.array(Image.open(info["png"]))[:, :, 3]
        rows = np.where(alpha.max(axis=1) > 0)[0]
        self.assertNotEqual(info["placement"]["band"], "UPPER_THIRD")
        self.assertTrue(rows.max() < 330 - 0.03 * 1280 or rows.min() > 640, (rows.min(), rows.max()))


if __name__ == "__main__":
    unittest.main()
