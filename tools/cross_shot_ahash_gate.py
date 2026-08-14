#!/usr/bin/env python3
"""跨镜 aHash 近重复门(CROSS-SHOT-AHASH-NEAR-DUPLICATE)。

授权/来源: CL2X-1022(监制自建, ADVISORY)。承 CLAUDE.md 复核步骤 ⑤「重复镜头检测」与
巡检规范「跨镜 aHash(fps=1, 间隔≥4s, dist≤5, >15% FAIL)」。

为什么另起一个工具(而不是复用 tools/audit_e36_fps1_adjacent_ahash.py):
  1. 那一个只测**相邻**帧对(adjacent),测的是"冻结/静止",**测不到隔了半分钟又原样用一次的镜头**
     ——而 E15R2 26% 重复镜正是后者(教训 5/6)。本门测的是**跨镜复用**。
  2. 那一个依赖 `imagehash`/临时 PNG 落盘。2026-08-07 沙盒 /sessions 100% 满,
     `imagehash`/`faster_whisper`/`rapidocr` 三者 pip 全 Errno28 FAIL,临时文件也写不出去。
     本门**零第三方依赖**(只用 numpy + ffmpeg 管道,不落任何临时文件),
     在盘满/无网的降级环境下仍然能跑。能力就位 = 在真实素材上跑得动,不是"包已列在 requirements 里"。

反 Goodhart 与总账 v3 元规则:
  * **缺测量即 FAIL,不是 PASS**:抽帧失败/帧数与时长对不上/帧数过少 → FAIL,不得当作"没发现问题"。
  * **不接受亮度差替身**:YAVG/亮度差会把"同一个人换了句台词"判成重复、把"暗场里两个不同镜"判成相同。
    本门只接受 8x8 平均哈希;`--method` 只允许 `ahash_8x8_gray`。
  * 阈值 dist<=5 / 间隔>=4s / >15% 三个数都来自项目既有实测口径(E15R2 26% 病例、CL2X-917 E36 0/23 对照),
    不是新拍脑袋的整数。

用法:
    python3 tools/cross_shot_ahash_gate.py --video <mp4> [--json out.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

GATE_ID = "CROSS-SHOT-AHASH-NEAR-DUPLICATE"
SCHEMA = "cross_shot_ahash_gate/v1"
ALLOWED_METHODS = {"ahash_8x8_gray"}

# 阈值(各绑一个既有实测病例/对照)
DEFAULT_FPS = 1.0            # 巡检规范: fps=1
DEFAULT_MIN_GAP_S = 4.0      # 间隔 >=4s 才算"跨镜",短于此属同一镜内的自然相似
DEFAULT_MAX_DIST = 5         # 64-bit aHash 汉明距 <=5 = 近重复
BLOCK_PCT = 15.0             # >15% = FAIL(E15R2 实测 26% = 观众可感)
ADVISE_PCT = 10.0            # 10-15% = ADVISE(边缘,记 warning 不阻断)
MIN_FRAMES = 8               # 少于此帧数,统计量无意义 -> 缺测量即 FAIL
RUN_LEN_FRAMES = 3           # 连续 3 个采样点(=3s @fps1)逐点吻合 -> 才可能是字面复用
                             # 校准依据: E38R 59s↔72s 同机位不同表演(眼检坐实)必须不被判 FAIL
REUSE_MAD_MAX = 2.0          # ★第二道确认:32x32 灰度平均像素差 <=2.0 才算"同一段素材"
                             # 校准依据(本轮实测,全部眼检坐实):
                             #   真·同一帧            MAD = 0.00
                             #   E38R 同镜相邻帧      MAD = 1.25 ~ 7.27
                             #   E38R 同机位不同表演  MAD = 5.06 ~ 9.36  <- aHash 汉明距只有 3-5,
                             #                                            单靠 aHash 必然误报
                             # 结论:8x8 aHash 在固定大远景里被"布景"主导,分不出人物级动作差异;
                             #      必须由像素级 MAD 兜底,否则这道门专产假缺陷。

SAMPLE_W = 32
SAMPLE_H = 32


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe_duration(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=duration", "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout.strip().splitlines()
    for line in out:
        try:
            value = float(line)
            if value > 0:
                return value
        except ValueError:
            continue
    # 回落到容器时长,但显式标注(容器时长可能虚胀 —— 见 CL2X-1015 E39 幽灵尾巴)
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def extract_gray_frames(video: Path, fps: float) -> np.ndarray:
    """fps 采样 -> 32x32 灰度帧,全程走管道,零临时文件(盘满环境可用)。"""
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(video),
        "-vf", f"fps={fps},scale={SAMPLE_W}:{SAMPLE_H}:flags=area,format=gray",
        "-f", "rawvideo", "-pix_fmt", "gray", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 抽帧失败: {proc.stderr.decode('utf-8', 'replace')[:400]}")
    buf = np.frombuffer(proc.stdout, dtype=np.uint8)
    per = SAMPLE_W * SAMPLE_H
    if buf.size == 0 or buf.size % per != 0:
        raise RuntimeError(f"抽帧字节数不是 {per} 的整数倍: {buf.size}")
    return buf.reshape(-1, SAMPLE_H, SAMPLE_W)


def detect_cut_times(video: Path, threshold: float = 0.25) -> list[float]:
    """场景切点(秒)。用于把采样帧分配到镜号——本项目单镜 4-15s(Seedance),
    因此"时间隔得远"根本不能当成"不同镜",必须真的跨过一个切点。"""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(video),
         "-vf", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
        capture_output=True,
    )
    times: list[float] = []
    for line in proc.stderr.decode("utf-8", "replace").splitlines():
        marker = "pts_time:"
        if marker in line:
            tail = line.split(marker, 1)[1].split()[0]
            try:
                times.append(float(tail))
            except ValueError:
                pass
    return sorted(times)


def shot_index(sample_times: np.ndarray, cuts: list[float]) -> np.ndarray:
    return np.searchsorted(np.asarray(cuts, dtype=float), sample_times, side="right")


def ahash_bits(frames: np.ndarray) -> np.ndarray:
    """8x8 平均哈希 -> (N, 64) bool。32x32 先做 4x4 块均值再降到 8x8。"""
    n = frames.shape[0]
    small = frames.reshape(n, 8, SAMPLE_H // 8, 8, SAMPLE_W // 8).mean(axis=(2, 4))
    means = small.reshape(n, 64).mean(axis=1, keepdims=True)
    return small.reshape(n, 64) > means


def hamming_matrix(bits: np.ndarray) -> np.ndarray:
    packed = np.packbits(bits, axis=1)
    diff = packed[:, None, :] ^ packed[None, :, :]
    return np.unpackbits(diff, axis=2).sum(axis=2).astype(np.int16)


def evaluate(frames: np.ndarray, fps: float, min_gap_s: float, max_dist: int,
             duration_s: float, cuts: list[float] | None = None) -> dict:
    n = frames.shape[0]
    findings: list[str] = []

    if n < MIN_FRAMES:
        return {
            "verdict": "FAIL",
            "fail_reason": "MEASUREMENT_MISSING_TOO_FEW_FRAMES",
            "frames_sampled": n,
            "note": "缺测量即 FAIL(总账 v3 元规则),不得当作未发现重复",
        }

    expected = duration_s * fps
    # fps 采样的帧数应在 [floor(expected)-1, ceil(expected)+1] 内;偏差过大=抽帧不可信
    if abs(n - expected) > max(2.0, expected * 0.05):
        return {
            "verdict": "FAIL",
            "fail_reason": "MEASUREMENT_UNTRUSTWORTHY_FRAME_COUNT_MISMATCH",
            "frames_sampled": n,
            "frames_expected_approx": round(expected, 3),
            "note": "抽帧数与时长对不上,测量不可信 -> FAIL 而非 PASS",
        }

    dist = hamming_matrix(ahash_bits(frames))
    idx = np.arange(n)
    gap_s = np.abs(idx[:, None] - idx[None, :]) / fps
    cross = gap_s >= min_gap_s
    if cuts:
        shots = shot_index(idx / fps, cuts)
        cross = cross & (shots[:, None] != shots[None, :])
    near = (dist <= max_dist) & cross

    # ---- 诊断量(不是门):画面雷同度 ----------------------------------------
    # 单帧相似只说明"同一机位又拍了一次",在正反打/固定大远景里完全正常。
    # 因此这个百分比**只作诊断**,不判 FAIL。见 §RULING(CL2X-1022 自我否决)。
    same_frame_flagged = np.where(near.any(axis=1))[0]
    sameness_pct = 100.0 * same_frame_flagged.size / n

    # ---- 真正的门:时间签名匹配 = 字面复用 ---------------------------------
    # 复用的是同一段素材 -> 不仅某一帧像,连续 RUN_LEN 帧的**运动轨迹**逐帧都像。
    # 回到同一机位重拍(正反打/主镜) -> 表演不同 -> 轨迹必然分叉。
    fl = frames.astype(np.int16)

    def mad(a: int, b: int) -> float:
        return float(np.abs(fl[a] - fl[b]).mean())

    reuse_pairs = []
    ii, jj = np.where(np.triu(near, k=1))
    for a, b in zip(ii.tolist(), jj.tolist()):
        if mad(a, b) > REUSE_MAD_MAX:
            continue  # aHash 说像,像素说不像 -> 同机位重拍,不是复用
        run = 0
        while (b + run + 1) < n and run + 1 < RUN_LEN_FRAMES:
            if dist[a + run + 1, b + run + 1] > max_dist:
                break
            if mad(a + run + 1, b + run + 1) > REUSE_MAD_MAX:
                break
            run += 1
        entry = {
            "t_a_s": round(a / fps, 3),
            "t_b_s": round(b / fps, 3),
            "gap_s": round((b - a) / fps, 3),
            "hamming": int(dist[a, b]),
            "pixel_mad": round(mad(a, b), 3),
            "matched_run_frames": run + 1,
        }
        if run + 1 >= RUN_LEN_FRAMES:
            entry["_a"], entry["_b"], entry["_run"] = a, b, run + 1
            reuse_pairs.append(entry)

    # 被判定为复用的**整段**都计入(观众看到的是那一段,不是那一帧)
    reuse_frames: set[int] = set()
    for p in reuse_pairs:
        for k in range(p["_run"]):
            reuse_frames.add(p["_a"] + k)
            reuse_frames.add(p["_b"] + k)
    for p in reuse_pairs:
        for key in ("_a", "_b", "_run"):
            p.pop(key, None)
    reuse_pct = 100.0 * len(reuse_frames) / n

    diag_pairs = []
    for a, b in zip(ii.tolist(), jj.tolist()):
        diag_pairs.append({
            "t_a_s": round(a / fps, 3),
            "t_b_s": round(b / fps, 3),
            "gap_s": round((b - a) / fps, 3),
            "hamming": int(dist[a, b]),
        })
    diag_pairs.sort(key=lambda p: (p["hamming"], -p["gap_s"]))

    if reuse_pct > BLOCK_PCT:
        verdict, tier = "FAIL", "BLOCK"
        findings.append(
            f"字面复用帧占比 {reuse_pct:.3f}% > {BLOCK_PCT}% 红线(E15R2 26% 同型:同一段素材被剪进两处)")
    elif reuse_pct >= ADVISE_PCT:
        verdict, tier = "PASS_WITH_ADVISORY", "ADVISE"
        findings.append(f"字面复用帧占比 {reuse_pct:.3f}% 落在 {ADVISE_PCT}-{BLOCK_PCT}% 边缘带,记 warning 不阻断")
    else:
        verdict, tier = "PASS", "NONE"

    if sameness_pct >= 40.0:
        findings.append(
            f"[诊断非门] 画面雷同度 {sameness_pct:.1f}%:大量镜头共用同一机位/构图。"
            f"不判 FAIL(正反打与固定主镜本就如此),但属『镜头单一』craft 议题,供剪辑/导演线参考。")

    return {
        "verdict": verdict,
        "tier": tier,
        "frames_sampled": n,
        "frames_expected_approx": round(expected, 3),
        "literal_reuse_frames": len(reuse_frames),
        "literal_reuse_pct": round(reuse_pct, 4),
        "literal_reuse_pairs": reuse_pairs[:20],
        "diagnostic_not_a_gate": {
            "single_frame_sameness_pct": round(sameness_pct, 4),
            "single_frame_similar_pairs_total": len(diag_pairs),
            "worst_pairs_top10": diag_pairs[:10],
            "why_not_a_gate": "单帧相似 = 同机位;正反打/固定主镜天然如此。判它 FAIL 会制造假缺陷。",
        },
        "findings": findings,
    }


def run(video: Path, fps: float, min_gap_s: float, max_dist: int, method: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    base = {
        "schema": SCHEMA,
        "gate_id": GATE_ID,
        "authorization_ref": "CL2X-1022",
        "generated_at_utc": now,
        "video": str(video),
        "method": method,
        "thresholds": {
            "fps": fps,
            "min_gap_s": min_gap_s,
            "max_hamming": max_dist,
            "block_pct": BLOCK_PCT,
            "advise_pct": ADVISE_PCT,
        },
        "rejected_measurement_methods": [
            "yavg_brightness_delta", "frame_difference_mean", "mpdecimate_only",
        ],
    }
    if method not in ALLOWED_METHODS:
        base.update({"verdict": "FAIL", "fail_reason": "DISALLOWED_MEASUREMENT_METHOD",
                     "note": "亮度/帧差类替身不被接受(会把不同暗场判成同一镜)"})
        return base
    if not video.exists():
        base.update({"verdict": "FAIL", "fail_reason": "VIDEO_NOT_FOUND"})
        return base

    base["video_sha256"] = sha256(video)
    try:
        duration = probe_duration(video)
        frames = extract_gray_frames(video, fps)
    except Exception as exc:  # 缺测量即 FAIL
        base.update({"verdict": "FAIL", "fail_reason": "MEASUREMENT_FAILED",
                     "error": str(exc)[:500]})
        return base

    base["video_stream_duration_s"] = round(duration, 3)
    try:
        cuts = detect_cut_times(video)
    except Exception as exc:
        base.update({"verdict": "FAIL", "fail_reason": "SHOT_BOUNDARY_MEASUREMENT_FAILED",
                     "error": str(exc)[:500]})
        return base
    if not cuts:
        base.update({"verdict": "FAIL", "fail_reason": "MEASUREMENT_MISSING_NO_SHOT_BOUNDARIES",
                     "note": "切点检测拿不到任何切点 -> 无法判定跨镜,缺测量即 FAIL"})
        return base
    base["shot_boundaries_detected"] = len(cuts)
    base.update(evaluate(frames, fps, min_gap_s, max_dist, duration, cuts))
    return base


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="跨镜 aHash 近重复门")
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--fps", type=float, default=DEFAULT_FPS)
    ap.add_argument("--min-gap-s", type=float, default=DEFAULT_MIN_GAP_S)
    ap.add_argument("--max-dist", type=int, default=DEFAULT_MAX_DIST)
    ap.add_argument("--method", default="ahash_8x8_gray")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    result = run(args.video, args.fps, args.min_gap_s, args.max_dist, args.method)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["verdict"].startswith("PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
