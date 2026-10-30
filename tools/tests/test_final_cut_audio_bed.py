"""lines/nalu/runtime/tools/final_cut_audio_bed.py — pure functions (Roger 2026-10-30 item 1b: whole-film bed,
no silence below −50 dBFS, no cut point in dead silence).  Synthetic audio only; no ffmpeg."""

from __future__ import annotations

import importlib.util
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "lines/nalu/runtime/tools/final_cut_audio_bed.py"


def _load():
    sys.path.insert(0, str(TOOL.parent))
    spec = importlib.util.spec_from_file_location("final_cut_audio_bed", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bed = _load()
SR = bed.SR


def tone(seconds: float, level_dbfs: float, freq: float = 220.0) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (np.sqrt(2.0) * bed.db_to_lin(level_dbfs) * np.sin(2 * math.pi * freq * t)).astype(np.float32)


class CutSilenceTests(unittest.TestCase):
    def test_cut_in_dead_silence_is_counted_under_both_readings(self):
        # 1 s tone, 1 s digital silence, 1 s tone; cuts at 1.0 (into silence) and 2.0 (out of silence)
        mono = np.concatenate([tone(1, -20), np.zeros(SR, dtype=np.float32), tone(1, -20)])
        stats = bed.cut_silence_stats(mono, [1.0, 2.0])
        self.assertEqual(stats["cuts"], 2)
        self.assertEqual(stats["dead_any_frame_count"], 2)
        self.assertEqual(stats["dead_mean_count"], 0)          # the tone side lifts the ±150 ms mean
        self.assertEqual(stats["dead_any_frame_share"], 1.0)

    def test_cut_between_two_tones_is_clean(self):
        mono = np.concatenate([tone(1, -20), tone(1, -22, 330.0)])
        stats = bed.cut_silence_stats(mono, [1.0])
        self.assertEqual(stats["dead_any_frame_count"], 0)
        self.assertEqual(stats["dead_mean_count"], 0)

    def test_bed_under_a_silent_cut_clears_it(self):
        mono = np.concatenate([tone(1, -20), np.zeros(SR, dtype=np.float32), tone(1, -20)])
        floor = tone(3, -44.0, 90.0)
        stats = bed.cut_silence_stats(mono + floor, [1.0, 2.0])
        self.assertEqual(stats["dead_any_frame_count"], 0)
        self.assertEqual(bed.silence_stats(mono + floor)["silence_runs"], 0)


class SilenceStatsTests(unittest.TestCase):
    def test_runs_and_share(self):
        mono = np.concatenate([tone(0.5, -20), np.zeros(SR // 2, dtype=np.float32), tone(0.5, -20)])
        stats = bed.silence_stats(mono)
        self.assertEqual(stats["silence_runs"], 1)
        self.assertAlmostEqual(stats["silence_seconds"], 0.5, places=2)
        self.assertAlmostEqual(stats["silent_frame_share"], 1 / 3, places=2)
        self.assertAlmostEqual(stats["digital_zero_seconds"], 0.5, places=2)


class WindowClipTests(unittest.TestCase):
    SEGS = [{"unit_id": "U1", "output_start": 0.0, "output_end": 5.0}, {"unit_id": "U2", "output_start": 5.0, "output_end": 9.0}]

    def test_partial_window_is_clipped_and_outside_window_dropped(self):
        rows = [{"start": 4.0, "end": 6.0, "unit_id": "U1"},   # spills into U2 → clipped to 4–5
                {"start": 6.0, "end": 7.0, "unit_id": "U1"},   # wholly in U2's span → dropped
                {"start": 5.5, "end": 6.5, "unit_id": "U2"},   # fine
                {"start": 1.0, "end": 2.0, "unit_id": "UNKNOWN"}]  # no span known → kept untouched
        out, stats = bed.clip_windows_to_units(rows, self.SEGS)
        self.assertEqual(stats, {"kept": 2, "clipped": 1, "dropped": 1})
        self.assertEqual([(r["start"], r["end"]) for r in out], [(4.0, 5.0), (5.5, 6.5), (1.0, 2.0)])
        self.assertEqual(out[0]["clipped_from"], [4.0, 6.0])


class BedPlanTests(unittest.TestCase):
    def test_location_classes(self):
        self.assertEqual(bed.classify_location("LOC-SNOW-ROAD-EXT"), "EXT_SNOW_WIND")
        self.assertEqual(bed.classify_location("LOC-YINTENG-STREET-EXT"), "EXT_STREET")
        self.assertEqual(bed.classify_location("LOC-YINTENG-BAR-INT"), "INT_HALL")
        self.assertEqual(bed.classify_location("LOC-YINTENG-BAR-ROOM-INT"), "INT_SMALL_ROOM")
        self.assertEqual(bed.classify_location(None), bed.DEFAULT_CLASS)
        self.assertEqual(bed.classify_location("LOC-UNNAMED-EXT"), "EXT_STREET")

    def test_consecutive_units_merge_and_tail_extends_to_file_end(self):
        segs = [{"unit_id": "A", "output_start": 0.0, "output_end": 4.0}, {"unit_id": "B", "output_start": 4.0, "output_end": 8.0},
                {"unit_id": "C", "output_start": 8.0, "output_end": 10.0}]
        plan = bed.plan_bed_classes(segs, {"A": "S1", "B": "S1", "C": "S2"}, {"S1": "LOC-SNOW-ROAD-EXT", "S2": "LOC-BAR-INT"}, 13.0)
        self.assertEqual([(p["class"], p["start"], p["end"]) for p in plan],
                         [("EXT_SNOW_WIND", 0.0, 8.0), ("INT_HALL", 8.0, 13.0)])
        self.assertEqual(plan[0]["units"], ["A", "B"])

    def test_bed_is_deterministic_and_above_the_silence_line(self):
        plan = [{"start": 0.0, "end": 1.5, "class": "EXT_SNOW_WIND", "location_id": "x", "units": ["A"]},
                {"start": 1.5, "end": 3.0, "class": "INT_SMALL_ROOM", "location_id": "y", "units": ["B"]}]
        n = 3 * SR
        one = bed.render_bed(plan, n, 7)
        two = bed.render_bed(plan, n, 7)
        other = bed.render_bed(plan, n, 8)
        self.assertTrue(np.array_equal(one, two))
        self.assertFalse(np.array_equal(one, other))
        frames = bed.frame_rms_db(one.mean(axis=1))
        self.assertGreater(float(frames.min()), bed.SILENCE_DBFS)       # the floor never dips below −50
        self.assertLess(float(frames.max()), -36.0)                       # and never becomes audible foreground


class PadAndDuckTests(unittest.TestCase):
    def test_pad_regions_fill_gaps_with_the_next_cue_and_run_to_file_end(self):
        cues = [{"cue_id": "C1", "source_key": "k1", "timeline_start": 0.0, "duration": 8.0},
                {"cue_id": "C2", "source_key": "k2", "timeline_start": 150.0, "duration": 30.0}]
        regions = bed.plan_pad_regions(cues, content_end=220.0, total_s=226.0)
        self.assertEqual([(r["start"], r["end"], r["source_key"]) for r in regions],
                         [(8.0, 150.0, "k2"), (180.0, 226.0, "k2")])
        self.assertEqual(regions[0]["before_cue"], "C2")
        self.assertIsNone(regions[1]["before_cue"])

    def test_duck_gain_follows_the_stated_law(self):
        env = np.array([-60.0, -30.0, -20.0, -16.0, 0.0])
        g = bed.duck_gain_db(env)
        self.assertEqual(list(np.round(g, 2)), [0.0, 0.0, -9.5, -13.3, -14.0])

    def test_envelope_attack_and_release_time_constants(self):
        mono = np.concatenate([np.zeros(SR, dtype=np.float32), tone(1, -12), np.zeros(SR, dtype=np.float32)])
        env_db, hop = bed.envelope_db(mono)
        blocks_per_s = SR // hop
        # 150 ms after onset the envelope has risen past −20 dBFS; 600 ms after offset it has fallen below −30
        self.assertGreater(env_db[blocks_per_s + int(0.15 * blocks_per_s)], -20.0)
        self.assertLess(env_db[2 * blocks_per_s + int(0.9 * blocks_per_s)], -30.0)

    def test_loop_to_length_has_no_gap_and_crossfades(self):
        x = tone(6.0, -20.0).reshape(-1, 1)
        x = np.concatenate([x, x], axis=1)
        y = bed.loop_to_length(x, 20 * SR)
        self.assertEqual(len(y), 20 * SR)
        frames = bed.frame_rms_db(y.mean(axis=1))
        self.assertGreater(float(frames.min()), -30.0)


class IdempotenceTests(unittest.TestCase):
    def test_existing_output_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "out.mp4"
            existing.write_bytes(b"x")
            with self.assertRaises(SystemExit) as ctx:
                bed.ensure_fresh_output(existing)
            self.assertIn("OUTPUT_EXISTS_REFUSING_TO_OVERWRITE", str(ctx.exception))
            bed.ensure_fresh_output(Path(tmp) / "fresh.mp4")   # no raise


if __name__ == "__main__":
    unittest.main()
