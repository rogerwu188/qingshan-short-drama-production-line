#!/usr/bin/env python3
"""tools/cross_shot_ahash_gate.py 单元测试(CL2X-1022)。

注意(承 CL2X-1021 §⑤ 教训):单测全绿 ≠ 能用。本文件只覆盖判决逻辑;
解码路径必须另有**真实素材回归**才算能力就位,回归证据见
qa/cl2x1022_cross_shot_ahash_gate_20260807/LIVE_REGRESSION.json。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cross_shot_ahash_gate as G  # noqa: E402


def frames_from_patterns(patterns: list[int], seed: int = 0) -> np.ndarray:
    """patterns[i] = 该帧的"内容 id";相同 id 生成同一张图,不同 id 生成差异极大的图。"""
    rng = np.random.default_rng(seed)
    bank: dict[int, np.ndarray] = {}
    out = []
    for pid in patterns:
        if pid not in bank:
            # 用低频块噪声保证 8x8 降采样后仍然区分得开
            block = rng.integers(0, 256, size=(8, 8), dtype=np.uint8)
            bank[pid] = np.kron(block, np.ones((4, 4), dtype=np.uint8))
        out.append(bank[pid])
    return np.stack(out).astype(np.uint8)


class TestAhashCore(unittest.TestCase):
    def test_identical_frames_distance_zero(self):
        f = frames_from_patterns([1, 1])
        d = G.hamming_matrix(G.ahash_bits(f))
        self.assertEqual(int(d[0, 1]), 0)

    def test_distinct_frames_distance_large(self):
        f = frames_from_patterns(list(range(12)), seed=7)
        d = G.hamming_matrix(G.ahash_bits(f))
        off = d[np.triu_indices(12, k=1)]
        self.assertGreater(off.min(), G.DEFAULT_MAX_DIST)

    def test_bits_shape_is_64(self):
        self.assertEqual(G.ahash_bits(frames_from_patterns([1, 2, 3])).shape, (3, 64))


def all_cuts(n: int) -> list[float]:
    """每秒一个切点 = 每个采样帧各属一镜(隔离出"跨镜"以外的变量)。"""
    return [float(t) + 0.5 for t in range(n)]


class TestShotBoundaryRule(unittest.TestCase):
    def test_same_shot_repeat_not_counted(self):
        """同一镜内 3 帧几乎一样(无切点)——本项目单镜 4-15s,这是正常的,不该判复用。"""
        pats = list(range(20))
        pats[10] = pats[11] = pats[12] = 100
        f = frames_from_patterns(pats, seed=3)
        r = G.evaluate(f, 1.0, 4.0, 5, duration_s=len(f), cuts=[5.5])  # 只有一个切点
        self.assertEqual(r["literal_reuse_frames"], 0)
        self.assertEqual(r["verdict"], "PASS")

    def test_time_gap_alone_is_not_enough(self):
        """隔了 16s 但仍在同一镜内 -> 不算跨镜(v1 校准错误的回归锁)。"""
        pats = list(range(20))
        pats[16], pats[17], pats[18] = pats[0], pats[1], pats[2]
        f = frames_from_patterns(pats, seed=5)
        r = G.evaluate(f, 1.0, 4.0, 5, duration_s=len(f), cuts=[19.5])
        self.assertEqual(r["literal_reuse_frames"], 0)


class TestLiteralReuseVsReturnToAngle(unittest.TestCase):
    def test_returning_to_same_angle_is_not_reuse(self):
        """同机位重拍:首帧像,但后续表演分叉 -> 不是复用,必须 PASS。
        校准依据=E38R 59s↔72s 眼检坐实(同一固定大远景,动作不同)。"""
        pats = list(range(30))
        pats[20] = pats[5]          # 只有锚点一帧相同,之后各走各的
        f = frames_from_patterns(pats, seed=13)
        r = G.evaluate(f, 1.0, 4.0, 5, duration_s=len(f), cuts=all_cuts(30))
        self.assertEqual(r["literal_reuse_frames"], 0)
        self.assertEqual(r["verdict"], "PASS")
        self.assertGreater(r["diagnostic_not_a_gate"]["single_frame_similar_pairs_total"], 0)

    def test_reused_clip_is_caught(self):
        """整段素材被剪进两处:连续轨迹逐帧吻合 -> 必须抓到。"""
        pats = list(range(30))
        pats[20], pats[21], pats[22] = pats[5], pats[6], pats[7]
        f = frames_from_patterns(pats, seed=13)
        r = G.evaluate(f, 1.0, 4.0, 5, duration_s=len(f), cuts=all_cuts(30))
        self.assertGreater(r["literal_reuse_frames"], 0)
        self.assertEqual(r["literal_reuse_pairs"][0]["matched_run_frames"], G.RUN_LEN_FRAMES)


class TestVerdictTiers(unittest.TestCase):
    def _case(self, n_reused_runs: int, total: int = 40):
        pats = list(range(total))
        for k in range(n_reused_runs):
            src, dst = k * 4, total - 4 - k * 4
            for j in range(3):
                pats[dst + j] = pats[src + j]
        f = frames_from_patterns(pats, seed=11)
        return G.evaluate(f, 1.0, 4.0, 5, duration_s=total, cuts=all_cuts(total))

    def test_clean_is_pass(self):
        r = self._case(0)
        self.assertEqual(r["verdict"], "PASS")
        self.assertEqual(r["literal_reuse_pct"], 0.0)

    def test_edge_band_is_advisory_not_block(self):
        r = self._case(1)   # 6/40 = 15.0% -> 不 >15,落 ADVISE 带
        self.assertEqual(r["literal_reuse_pct"], 15.0)
        self.assertEqual(r["verdict"], "PASS_WITH_ADVISORY")
        self.assertEqual(r["tier"], "ADVISE")

    def test_over_red_line_is_fail(self):
        r = self._case(2)   # 12/40 = 30% > 15%
        self.assertEqual(r["verdict"], "FAIL")
        self.assertEqual(r["tier"], "BLOCK")


class TestSamenessIsDiagnosticOnly(unittest.TestCase):
    def test_high_sameness_alone_does_not_fail(self):
        """整场戏共用一个固定主镜(雷同度极高)但没有一段被复用 -> PASS + 诊断提示。"""
        pats = [1 if i % 2 == 0 else 100 + i for i in range(40)]
        f = frames_from_patterns(pats, seed=21)
        r = G.evaluate(f, 1.0, 4.0, 5, duration_s=40, cuts=all_cuts(40))
        self.assertGreater(r["diagnostic_not_a_gate"]["single_frame_sameness_pct"], 40.0)
        self.assertEqual(r["verdict"], "PASS")
        self.assertTrue(any("诊断非门" in x for x in r["findings"]))


class TestMissingMeasurementIsFail(unittest.TestCase):
    def test_too_few_frames_fails(self):
        r = G.evaluate(frames_from_patterns([1, 2, 3]), 1.0, 4.0, 5, duration_s=3, cuts=[1.5])
        self.assertEqual(r["verdict"], "FAIL")
        self.assertEqual(r["fail_reason"], "MEASUREMENT_MISSING_TOO_FEW_FRAMES")

    def test_frame_count_mismatch_fails(self):
        """抽帧只拿到 20 帧但片长 149s —— 必须 FAIL,不能报"没查到重复"。"""
        r = G.evaluate(frames_from_patterns(list(range(20)), seed=2), 1.0, 4.0, 5,
                       duration_s=149.0)
        self.assertEqual(r["verdict"], "FAIL")
        self.assertEqual(r["fail_reason"], "MEASUREMENT_UNTRUSTWORTHY_FRAME_COUNT_MISMATCH")

    def test_missing_video_fails(self):
        r = G.run(Path("/nonexistent/x.mp4"), 1.0, 4.0, 5, "ahash_8x8_gray")
        self.assertEqual(r["verdict"], "FAIL")
        self.assertEqual(r["fail_reason"], "VIDEO_NOT_FOUND")


class TestRejectedMethods(unittest.TestCase):
    def test_brightness_substitute_rejected(self):
        r = G.run(Path("/tmp/whatever.mp4"), 1.0, 4.0, 5, "yavg_brightness_delta")
        self.assertEqual(r["verdict"], "FAIL")
        self.assertEqual(r["fail_reason"], "DISALLOWED_MEASUREMENT_METHOD")

    def test_rejected_list_is_declared_in_output(self):
        r = G.run(Path("/nonexistent/x.mp4"), 1.0, 4.0, 5, "ahash_8x8_gray")
        self.assertIn("yavg_brightness_delta", r["rejected_measurement_methods"])


class TestZeroDependency(unittest.TestCase):
    def test_no_third_party_imports_beyond_numpy(self):
        src = Path(G.__file__).read_text(encoding="utf-8")
        for banned in ("import imagehash", "from PIL", "import cv2", "import torch"):
            self.assertNotIn(banned, src, f"降级环境不可用的依赖: {banned}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
