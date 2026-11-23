"""BGM cue shaping (owner 2026-11-19: music played for one or two shots and stopped, which sounds broken).

Music may change or stop at a scene / mood change, never abruptly and never as a fragment.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NALU_TOOLS = ROOT / "lines/nalu/runtime/tools"
sys.path.insert(0, str(NALU_TOOLS))
sys.path.insert(0, str(ROOT / "tools"))

import bgm_cue_shaping as sh  # noqa: E402


def load_bgm():
    spec = importlib.util.spec_from_file_location("nalu_selective_bgm_shaping_test", NALU_TOOLS / "nalu_selective_bgm.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def timeline(*scenes, payoff_after=None):
    """Shots of 4 s each; ``scenes`` = shot counts per scene.  ``payoff_after``: index of a PAYOFF shot."""
    rows, t, i = [], 0.0, 0
    for n, count in enumerate(scenes):
        for _ in range(count):
            shot = {"shot_id": f"S{i}", "scene_id": f"SC{n}"}
            if payoff_after == i:
                shot["prompt_spec"] = {"beat_role": "PAYOFF"}
            rows.append({"shot_id": f"S{i}", "t0": t, "t1": t + 4.0, "scene_id": f"SC{n}", "shot": shot})
            t += 4.0
            i += 1
    return rows, t


def cue(cid, t0, t1, key="K1", **kw):
    return {"cue_id": cid, "source_key": key, "t0": t0, "t1": t1, **kw}


class ShapeTests(unittest.TestCase):
    def check_invariants(self, out, tl, content):
        b = sh.boundaries(tl, content)
        for c in out["cues"]:
            self.assertIn(c["end_type"], sh.END_TYPES)
            self.assertIn(c["entry_type"], sh.ENTRY_TYPES)
            if not c["sting"]:
                self.assertGreaterEqual(c["t1"] - c["t0"], out["rule"]["min_cue_seconds"] - 1e-6, c)
            if c["end_type"] == "HIT_STOP":
                self.assertTrue(c["sting"] or any(abs(c["hit_at"] - h) < 1e-6 for h in b["hits"]))
                self.assertGreaterEqual(c["fade_out_s"], 0.3 - 1e-6)       # decay tail, never a dead cut
            elif c["end_type"] == "FADE_OUT":
                self.assertGreaterEqual(c["fade_out_s"], 2.0)
            else:
                self.assertGreaterEqual(c["fade_out_s"], 1.0)
            if not c["sting"]:  # a sting is a short marked accent; underscore fades in over >= 1 s
                self.assertGreaterEqual(c["fade_in_s"], 1.0 if c["entry_type"] != "HIT_ENTRY" else 0.0)

    def test_one_shot_cue_is_never_a_fragment(self):
        # the published defect: a cue on one 4 s shot mid-scene
        tl, content = timeline(5, 5, 5)
        out = sh.shape([cue("C", 24.0, 28.0)], tl, content, {"K1": 120.0}, min_cue=12.0)
        self.check_invariants(out, tl, content)
        (c,) = out["cues"]
        self.assertGreaterEqual(c["t1"] - c["t0"], 12.0)
        self.assertTrue(c["end_at_boundary"])
        self.assertAlmostEqual(c["t1"], 40.0)                 # runs to the scene's end

    def test_short_cue_the_source_cannot_extend_is_dropped(self):
        tl, content = timeline(5, 5, 5)
        out = sh.shape([cue("C", 24.0, 28.0)], tl, content, {"K1": 5.0}, min_cue=12.0)
        self.assertEqual(out["cues"], [])
        self.assertEqual(out["dropped"][0]["reason"], "FRAGMENT_SHORTER_THAN_MIN_CUE")

    def test_marked_sting_may_be_short_and_hit_stops_with_a_decay_tail(self):
        tl, content = timeline(5, 5)
        out = sh.shape([cue("HIT", 18.0, 20.0, sting=True)], tl, content, {"K1": 30.0}, min_cue=12.0)
        self.check_invariants(out, tl, content)
        (c,) = out["cues"]
        self.assertEqual(c["end_type"], "HIT_STOP")
        self.assertAlmostEqual(c["t1"] - c["hit_at"], sh.HIT_DECAY_SECONDS)

    def test_hit_stop_on_a_payoff_end(self):
        tl, content = timeline(6, 4, payoff_after=3)          # payoff shot S3 ends at 16 s
        out = sh.shape([cue("C", 0.0, 16.4)], tl, content, {"K1": 60.0}, min_cue=12.0)
        (c,) = out["cues"]
        self.assertEqual(c["end_type"], "HIT_STOP")
        self.assertAlmostEqual(c["hit_at"], 16.0)

    def test_end_off_a_boundary_fades_out_at_the_scene_end(self):
        tl, content = timeline(5, 5, 5)
        out = sh.shape([cue("C", 0.0, 13.0)], tl, content, {"K1": 120.0}, min_cue=12.0)
        (c,) = out["cues"]
        self.assertEqual(c["end_type"], "FADE_OUT")
        self.assertAlmostEqual(c["t1"], 20.0)
        self.assertGreaterEqual(c["fade_out_s"], 2.0)

    def test_entry_on_a_scene_cut_pre_laps(self):
        tl, content = timeline(5, 5, 5)
        out = sh.shape([cue("C", 20.0, 40.0)], tl, content, {"K1": 120.0}, min_cue=12.0)
        (c,) = out["cues"]
        self.assertEqual(c["entry_type"], "PRELAP")
        self.assertAlmostEqual(20.0 - c["t0"], sh.PRELAP_SECONDS)
        self.assertTrue(0.5 <= sh.PRELAP_SECONDS <= 1.0)

    def test_cues_close_together_crossfade_no_flicker(self):
        tl, content = timeline(5, 5, 5, 5)
        out = sh.shape([cue("A", 0.0, 20.0, "K1"), cue("B", 22.0, 40.0, "K2")], tl, content,
                       {"K1": 120.0, "K2": 120.0}, min_cue=12.0)
        self.check_invariants(out, tl, content)
        a, b = out["cues"]
        self.assertEqual(a["end_type"], "CROSSFADE")
        self.assertEqual(b["entry_type"], "CROSSFADE_IN")
        overlap = a["t1"] - b["t0"]
        self.assertTrue(1.0 <= overlap <= 2.0 + 1e-6, overlap)
        self.assertEqual(a.get("fade_curve"), "qsin")

    def test_same_source_music_gap_music_is_one_cue(self):
        tl, content = timeline(10)
        out = sh.shape([cue("A", 0.0, 12.0), cue("B", 15.0, 28.0)], tl, content, {"K1": 120.0}, min_cue=12.0)
        self.assertEqual(len(out["cues"]), 1)
        self.assertEqual(out["merged"], [["A", "B"]])

    def test_no_flicker_anywhere(self):
        tl, content = timeline(3, 3, 3, 3, 3)
        cues = [cue("A", 0.0, 6.0, "K1"), cue("B", 9.0, 15.0, "K2"), cue("C", 30.0, 34.0, "K3"),
                cue("D", 40.0, 52.0, "K4")]
        out = sh.shape(cues, tl, content, {k: 200.0 for k in ("K1", "K2", "K3", "K4")}, min_cue=12.0)
        self.check_invariants(out, tl, content)
        for a, b in zip(out["cues"], out["cues"][1:]):
            gap = b["t0"] - a["t1"]
            self.assertTrue(gap >= sh.FLICKER_GAP_SECONDS or a["end_type"] in ("CROSSFADE", "HIT_STOP"), (a, b))

    def test_min_cue_is_configurable(self):
        self.assertEqual(sh.min_cue_seconds({}), sh.MIN_CUE_SECONDS)
        self.assertEqual(sh.min_cue_seconds({sh.MIN_CUE_ENV: "15"}), 15.0)
        self.assertTrue(10.0 <= sh.MIN_CUE_SECONDS <= 15.0)


class DuckAndMixTests(unittest.TestCase):
    def test_duck_is_ten_db_and_never_mutes(self):
        bgm = load_bgm()
        self.assertTrue(-14.0 <= sh.DUCK_DB <= -10.0)
        self.assertTrue(bgm.DUCK_RANGE_DB[0] <= sh.DUCK_DB <= bgm.DUCK_RANGE_DB[1])   # authenticity gate range
        c = {"timeline_start": 0.0, "dialogue_duck_db": sh.DUCK_DB,
             "dialogue_windows": [{"start": 2.0, "end": 5.0}]}
        expr = bgm.duck_expr(c)
        floor = 10 ** (sh.DUCK_DB / 20)
        self.assertIn(f"{floor:.4f}", expr)
        self.assertGreater(floor, 0.25)

    def test_mix_defaults_are_soft_fades(self):
        bgm = load_bgm()
        self.assertGreaterEqual(bgm.FADE_IN_S, 1.0)
        self.assertGreaterEqual(bgm.FADE_OUT_S, 2.0)
        self.assertEqual(bgm._curve({"fade_curve": "qsin"}), "qsin")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_ducked_music_under_speech_keeps_level_in_range(self):
        """Render a 10 s tone cue with the planned duck and fades: under speech it drops ~10 dB, not to silence."""
        bgm = load_bgm()
        cue_ = {"timeline_start": 0.0, "dialogue_duck_db": sh.DUCK_DB, "dialogue_windows": [{"start": 4.0, "end": 7.0}]}
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "c.wav"
            af = (f"afade=t=in:st=0:d=1.5:curve=hsin,afade=t=out:st=7.5:d=2.5:curve=hsin,"
                  f"volume='{bgm.duck_expr(cue_)}':eval=frame")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=330:d=10:sample_rate=16000",
                            "-af", af, "-ac", "1", "-f", "s16le", str(out)], check=True)
            import array
            import math
            pcm = array.array("h"); pcm.frombytes(out.read_bytes())

            def db(a, b):
                block = pcm[int(a * 16000):int(b * 16000)]
                return 20 * math.log10(math.sqrt(sum(v * v for v in block) / len(block)) / 32768.0)
            open_level, ducked = db(2.5, 3.2), db(5.0, 6.5)
            self.assertAlmostEqual(open_level - ducked, -sh.DUCK_DB, delta=1.5)
            self.assertGreater(ducked, -60.0)                     # ducked, not muted
            self.assertLess(db(0.0, 0.2), open_level - 10)        # fades in
            self.assertLess(db(9.8, 10.0), open_level - 10)       # fades out


if __name__ == "__main__":
    unittest.main()
