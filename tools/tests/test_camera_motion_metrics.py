"""camera_motion_metrics pure functions: synthetic camera paths → reversal count and camera class
(Roger 2026-10-30, E12 成片审看 item 2: dialogue units default to a locked-off camera)."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import camera_motion_metrics as cmm  # noqa: E402

FPS = 24.0
WIDTH, HEIGHT = 768, 1344


def _tf(dx: list[float], dz: list[float] | None = None) -> dict:
    dz = dz or [0.0] * len(dx)
    return {"fps": FPS, "width": WIDTH, "height": HEIGHT, "frames": len(dx) + 1, "work_width": 384,
            "fallback_frames": 0,
            "deltas": [{"dx": x, "dy": 0.0, "dlogscale": z, "dtheta": 0.0, "inliers": 50, "fallback": False}
                       for x, z in zip(dx, dz)]}


class ReversalCount(unittest.TestCase):
    def test_monotonic_path_has_no_reversal(self):
        self.assertEqual(cmm.count_reversals([float(i) for i in range(100)], prominence=10.0), 0)

    def test_jitter_below_prominence_is_not_a_reversal(self):
        path = [0.3 * ((-1) ** i) for i in range(100)]   # ±0.3 px tracker noise
        self.assertEqual(cmm.count_reversals(path, prominence=11.5), 0)

    def test_visible_back_and_forth_counts_each_turn(self):
        # out 40 px, back 40 px, out 40 px: two turning points with >= prominence on both sides
        path = [i * 2.0 for i in range(21)] + [40 - i * 2.0 for i in range(1, 21)] + [i * 2.0 for i in range(1, 21)]
        self.assertEqual(cmm.count_reversals(path, prominence=11.5), 2)

    def test_single_small_correction_is_one_reversal(self):
        path = [i * 2.0 for i in range(21)] + [40 - i * 1.0 for i in range(1, 15)]
        self.assertEqual(cmm.count_reversals(path, prominence=11.5), 1)


class CameraClass(unittest.TestCase):
    def test_tripod_is_locked_off(self):
        # 0.02 px/frame drift (0.5 px/s), no zoom, 5 s
        row = cmm.summarise(Path("x.mp4"), _tf([0.02] * 120))
        self.assertTrue(row["locked_off"])
        self.assertEqual(row["camera_class"], "LOCKED_OFF")
        self.assertEqual(row["reversals"], 0)

    def test_slow_drift_is_slow_move_not_locked(self):
        # 0.15 px/frame = 3.6 px/s: above the 2 px/s lock threshold, below the 6 px/s moving floor
        row = cmm.summarise(Path("x.mp4"), _tf([0.15] * 120))
        self.assertFalse(row["locked_off"])
        self.assertEqual(row["camera_class"], "SLOW_MOVE")

    def test_dolly_push_in_is_moving(self):
        # 4 %/s zoom: log-scale 0.04/24 per frame over 5 s
        row = cmm.summarise(Path("x.mp4"), _tf([0.0] * 120, [math.log(1.04) / FPS] * 120))
        self.assertEqual(row["camera_class"], "MOVING")
        self.assertGreater(row["zoom_pct_per_s"], 3.0)
        self.assertEqual(row["reversals"], 0)

    def test_pendulum_camera_is_unstable(self):
        # 30 px out / 30 px back every 0.5 s for 5 s → ~10 turning points in 5 s ≥ 1 reversal/s
        dx = []
        for cycle in range(10):
            dx += [2.5] * 12 + [-2.5] * 12
        row = cmm.summarise(Path("x.mp4"), _tf(dx))
        self.assertTrue(row["unstable"])
        self.assertEqual(row["camera_class"], "UNSTABLE")
        self.assertGreaterEqual(row["reversals_per_s"], 1.0)

    def test_summary_counts_targets(self):
        rows = [{"locked_off": True, "unstable": False, "camera_class": "LOCKED_OFF"}] * 7 + \
               [{"locked_off": False, "unstable": False, "camera_class": "MOVING"}] * 3
        s = cmm.summary_counts(rows)
        self.assertEqual(s["locked_off_share"], 0.7)
        self.assertEqual(s["status"], "PASS")
        rows[0] = {"locked_off": False, "unstable": True, "camera_class": "UNSTABLE"}
        self.assertEqual(cmm.summary_counts(rows)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
