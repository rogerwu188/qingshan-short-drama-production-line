"""Dialogue tail guard + post-line beat (owner 2026-11-19, published 《摄政王她又来找茬了》 episodes).

The last character of a line was cut mid-syllable at the jump to the next shot (the cut sat on the ASR word end,
which runs early on the final syllable), and lines ended with no beat before the cut.
"""
from __future__ import annotations

import math
import shutil
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import dialogue_tail_guard as tg  # noqa: E402
import dialogue_tail_trim as trim  # noqa: E402
import performance_cut as pc  # noqa: E402


def synth_frames(speech_until: float, total: float = 4.0, hop: float = 0.02, *, loud=-14.0, decay_db_per_s=40.0,
                 floor=-70.0, gap=None):
    """dBFS frames: speech to ``speech_until`` (a final syllable decaying after it), then near-silence; optional
    ``gap`` = (start, end) of further loud speech (babble)."""
    out = []
    for i in range(int(total / hop)):
        t = i * hop
        v = loud if t < speech_until else max(floor, loud - decay_db_per_s * (t - speech_until) * 10)
        if gap and gap[0] <= t < gap[1]:
            v = loud
        out.append(v)
    return out


def write_wav(path: Path, segments: list[tuple[float, float, float]], total: float, rate: int = 16000) -> None:
    """Sine-tone 'speech' (start, end, amplitude) segments in silence, 16-bit mono."""
    frames = bytearray()
    for i in range(int(total * rate)):
        t = i / rate
        amp = next((a for s, e, a in segments if s <= t < e), 0.0)
        frames += struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * 220 * t)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(bytes(frames))


class GuardTests(unittest.TestCase):
    def test_guard_is_at_least_word_end_plus_quarter_second(self):
        g = tg.guard(2.0, None)
        self.assertAlmostEqual(g["guard"], 2.0 + tg.TAIL_GUARD_SECONDS)

    def test_trailing_syllable_after_the_asr_end_moves_the_guard(self):
        # ASR says the line ends at 2.0 s; the final syllable really sounds until 2.4 s
        frames = synth_frames(2.4)
        end = tg.speech_end(frames, 2.0, line_start=0.5)
        self.assertIsNotNone(end)
        self.assertGreaterEqual(end, 2.4)
        g = tg.guard(2.0, frames, line_start=0.5)
        self.assertGreaterEqual(g["guard"], 2.4 + tg.SPEECH_END_PAD_SECONDS)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_real_audio_measured_like_s7(self):
        import nalu_pipeline
        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "u.wav"
            write_wav(wav, [(0.3, 2.45, 0.3)], 3.5)        # speech to 2.45 s; Whisper says the word ended at 2.1
            frames = nalu_pipeline._unit_energy_db(wav, tg.HOP)
            g = tg.guard(2.1, frames, line_start=0.3)
            self.assertGreaterEqual(g["guard"], 2.45 + tg.SPEECH_END_PAD_SECONDS - 0.02)
            self.assertLess(g["guard"], 2.8)

    def test_speech_running_straight_on_falls_back_to_word_end_guard(self):
        frames = synth_frames(4.0)                           # never quiet in the search window
        self.assertIsNone(tg.speech_end(frames, 2.0, line_start=0.5))
        self.assertAlmostEqual(tg.guard(2.0, frames)["guard"], 2.0 + tg.TAIL_GUARD_SECONDS)


class BeatTests(unittest.TestCase):
    def test_default_beat_and_configuration(self):
        self.assertEqual(tg.post_line_beat({}, {}), tg.POST_LINE_BEAT_SECONDS)
        self.assertGreaterEqual(tg.POST_LINE_BEAT_SECONDS, 0.4)
        self.assertLessEqual(tg.POST_LINE_BEAT_SECONDS, 0.6)
        self.assertEqual(tg.post_line_beat({tg.BEAT_FIELD: 0.6}, {}), 0.6)
        self.assertEqual(tg.post_line_beat({tg.BEAT_FIELD: 0.6}, {tg.BEAT_ENV: "0.45"}), 0.45)
        self.assertEqual(tg.post_line_beat({}, {}, reaction=True), tg.REACTION_BEAT_SECONDS)

    def test_tail_cut_holds_the_beat_but_never_goes_below_the_guard(self):
        c = tg.tail_cut(2.0, 6.0, beat=0.5)
        self.assertAlmostEqual(c["cut"], 2.5)
        c = tg.tail_cut(2.0, 6.0, beat=0.0)                  # even a zero beat keeps the guard
        self.assertAlmostEqual(c["cut"], 2.0 + tg.TAIL_GUARD_SECONDS)
        c = tg.tail_cut(2.0, 6.0, beat=0.5, next_speech_start=2.05)   # babble right after the line
        self.assertAlmostEqual(c["cut"], 2.0 + tg.TAIL_GUARD_SECONDS)
        self.assertTrue(c["capped_by_next_speech"] and c["guard_applied"])
        self.assertAlmostEqual(tg.tail_cut(2.0, 2.1, beat=0.5)["cut"], 2.1)   # never past the clip


def contract(lines_by_shot, shots=None):
    rows = [{"shot_id": sid, "speaker_id": "A", "text": text} for sid, text in lines_by_shot.items()]
    return {"episode": "E01", "dialogue_language": "zh", "shots": shots or [],
            "audio_contract": {"dialogue_units": rows}}


def seg_chars(start, text, step=0.16):
    words = [{"start": round(start + i * step, 3), "end": round(start + (i + 1) * step, 3), "word": ch}
             for i, ch in enumerate(text)]
    return {"start": words[0]["start"], "end": words[-1]["end"], "text": text, "words": words}


class PerformanceCutTests(unittest.TestCase):
    LINE = "她有别的任务先让你们长个记性"   # 14 chars from 0.5 s -> ASR end 2.74 s

    def plan(self, units, lines, asr, seconds, energy=None, shots=None):
        grouping = {"units": [{"unit_id": u, "editorial_shot_ids": s} for u, s in units]}
        return pc.plan(contract(lines, shots), grouping, asr, seconds, energy)

    def test_line_gets_the_post_line_beat(self):
        rep = self.plan([("U1", ["S1"])], {"S1": self.LINE}, {"U1": [seg_chars(0.5, self.LINE)]}, {"U1": 6.0})
        r = rep["units"][0]
        self.assertAlmostEqual(r["after_out"], 2.74 + tg.POST_LINE_BEAT_SECONDS, places=3)
        self.assertIn("tail_guard", r)

    def test_trailing_syllable_after_asr_end_is_never_clipped(self):
        # babble starts 0.05 s after the ASR end, but the final syllable rings until 3.0 s: the cut waits for it
        asr = [seg_chars(0.5, self.LINE), seg_chars(2.79, "还有一件事")]
        frames = synth_frames(3.0, total=6.0, gap=(3.15, 3.6))
        rep = self.plan([("U1", ["S1"])], {"S1": self.LINE}, {"U1": asr}, {"U1": 6.0}, {"U1": frames})
        r = rep["units"][0]
        self.assertGreaterEqual(r["after_out"], 3.0 + tg.SPEECH_END_PAD_SECONDS)
        self.assertGreaterEqual(r["after_out"], 2.74 + tg.TAIL_GUARD_SECONDS)

    def test_reaction_next_gets_the_shorter_beat_but_not_below_the_guard(self):
        shots = [{"shot_id": "S1"}, {"shot_id": "S2", "prompt_spec": {"beat_role": "REACTION"}}]
        rep = self.plan([("U1", ["S1"]), ("U2", ["S2"])], {"S1": self.LINE}, {"U1": [seg_chars(0.5, self.LINE)]},
                        {"U1": 6.0, "U2": 4.0}, shots=shots)
        r = rep["units"][0]
        self.assertAlmostEqual(r["after_out"], 2.74 + max(tg.REACTION_BEAT_SECONDS, tg.TAIL_GUARD_SECONDS), places=3)

    def test_min_length_hold_never_cuts_into_the_tail(self):
        rep = self.plan([("U1", ["S1"])], {"S1": "不练了"}, {"U1": [seg_chars(1.0, "不练了", 0.3)]}, {"U1": 6.0},
                        {"U1": synth_frames(2.3, total=6.0)})
        r = rep["units"][0]
        self.assertGreaterEqual(r["after_out"], 2.3 + tg.SPEECH_END_PAD_SECONDS)


class SpeakingUnitsNeverTrimmedIntoSpeechTests(unittest.TestCase):
    """Regression: the craft-standard peak-window trim (PR #260) and the runtime budget act on silent units only."""

    def test_peak_trim_never_touches_a_speaking_unit(self):
        line = "她有别的任务先让你们长个记性"
        c = contract({"S1": line}, shots=[{"shot_id": "S1", "target_seconds": 2.0}, {"shot_id": "S2", "target_seconds": 2.0},
                                          {"shot_id": "S3", "target_seconds": 2.0}])
        grouping = {"units": [{"unit_id": "U1", "editorial_shot_ids": ["S1"]},
                              {"unit_id": "U2", "editorial_shot_ids": ["S2"]},
                              {"unit_id": "U3", "editorial_shot_ids": ["S3"]}]}
        rep = pc.plan(c, grouping, {"U1": [seg_chars(0.5, line)]}, {"U1": 6.0, "U2": 6.0, "U3": 6.0})
        speaking_before = dict(rep["units"][0])
        motion = {"U1": [0.5] * 100, "U2": [0.5] * 40 + [9.0] * 5 + [0.5] * 55}
        summary = pc.apply_peak_windows(rep, c, grouping, motion, runtime_floor_seconds=0.0)
        self.assertEqual(summary["status"], "APPLIED")
        self.assertEqual([u["unit_id"] for u in summary["units"]], ["U2"])
        r = rep["units"][0]
        self.assertEqual((r["after_in"], r["after_out"]), (speaking_before["after_in"], speaking_before["after_out"]))
        self.assertGreaterEqual(r["after_out"], r["tail_guard"]["guard"])
        self.assertTrue(all(c_["unit_id"] != "U1" for c_ in pc.peak_candidates(rep, c, grouping)))

    def test_tail_trim_plan_cut_is_never_before_the_guard(self):
        c = {"episode": "E01", "dialogue_language": "zh", "shots": [],
             "audio_contract": {"dialogue_units": [{"shot_id": "S1", "speaker_id": "A", "text": "我不知道"}]}}
        segs = [{"start": 0.3, "end": 1.2, "text": "我不知道"}, {"start": 1.2, "end": 3.0, "text": "啊啊啊乱说一通"}]
        rep = trim.plan(c, {"units": [{"unit_id": "U1", "editorial_shot_ids": ["S1"]}]}, {"U1": segs}, {"U1": 5.0},
                        unit_energy={"U1": synth_frames(1.55, total=5.0)})
        r = rep["units"][0]
        self.assertTrue(r["trimmed"])
        self.assertGreaterEqual(r["kept_seconds"], 1.55 + tg.SPEECH_END_PAD_SECONDS)


if __name__ == "__main__":
    unittest.main()
