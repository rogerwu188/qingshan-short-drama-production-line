#!/usr/bin/env python3
"""final_cut_shot_plan_parity.py — S7 final-cut vs shot-table machine comparison (SUPERVISOR_ORDERS seq=27 §六).

Diagnostic only (no gate_id, never blocks).  Runs after the S7 final render and before the S8 line-owner
screening, writes ``assembly/<EP>_FINAL_CUT_SHOT_PLAN_PARITY.json`` and a short block for CHECKPOINT.md:

  * scdet cut count vs shot-table shot count            → SHOT_COUNT_DRIFT      (|drift| > 20 %)
  * any real segment > 8 s whose planned shot is ≤ 7 s   → SHOT_STRETCHED        (lists shot ids by timeline position)
  * two consecutive cuts with near-static luma and > 5 s → STATIC_HOLD_IN_DIALOGUE
  * blank frame run > 2 s                                → BLANK_SCREEN
      a frame is blank only when it is BOTH extreme in mean luma (YAVG > 85 % or < 15 % of range) AND
      tonally uniform (signalstats 10th–90th percentile spread YHIGH−YLOW < --blank-max-spread, default 8
      of 255).  Roger 2026-10-30 (E12 screening): the YAVG-only rule flagged 14 runs / 80 s of night
      scenes whose 10–90 % spread measured 24–74 levels and YMAX ≥ 135 — dark, textured, not blank.
  * frozen frame run ≥ 1 s                               → FROZEN_FRAME
      consecutive 5 fps samples whose temporal difference YDIF < --frozen-ydif (default 0.5) — a held
      still, not a dark scene.

Measurements come from ffmpeg (``scdet`` scene-change detection and ``signalstats`` YAVG/YLOW/YHIGH/YDIF
sampled at 5 fps).
The planned timeline is the generation contract's shot order and target_seconds; the end card (if any) is
trimmed by ``--end-card-seconds``.
"""
from __future__ import annotations

import sys as _sys
import pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))
import nalu_media_tools as _media

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


def run(argv: list[str]) -> str:
    proc = subprocess.run(argv, capture_output=True, text=True)
    return (proc.stdout or "") + (proc.stderr or "")


def probe_duration(path: Path) -> float:
    out = run([_media.require_ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    try:
        return float(out.strip().splitlines()[0])
    except (IndexError, ValueError):
        return 0.0


def scene_cuts(path: Path, threshold: float, until: float) -> list[float]:
    out = run([_media.require_ffmpeg(), "-hide_banner", "-nostats", "-i", str(path), "-t", f"{until:.3f}",
               "-vf", f"scdet=threshold={threshold}:sc_pass=0", "-an", "-f", "null", "-"])
    cuts = [float(m.group(1)) for m in re.finditer(r"lavfi\.scd\.time:\s*([0-9.]+)", out)]
    if not cuts:  # older ffmpeg builds print "scene_score" lines
        cuts = [float(m.group(1)) for m in re.finditer(r"time:([0-9.]+)", out)]
    return sorted(set(round(c, 3) for c in cuts if c < until))


def luma_samples(path: Path, until: float, fps: int = 5) -> list[dict[str, float]]:
    """Per-sample luma statistics: {t, yavg, ylow, yhigh, ydif} (signalstats, 8-bit range)."""
    keys = ("YAVG", "YLOW", "YHIGH", "YDIF")
    meta = ",".join(f"metadata=print:key=lavfi.signalstats.{k}" for k in keys)
    out = run([_media.require_ffmpeg(), "-hide_banner", "-nostats", "-i", str(path), "-t", f"{until:.3f}",
               "-vf", f"fps={fps},signalstats,{meta}", "-an", "-f", "null", "-"])
    by_t: dict[float, dict[str, float]] = {}
    t: float | None = None
    for line in out.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            t = round(float(m.group(1)), 3)
            by_t.setdefault(t, {"t": t})
            continue
        m = re.search(r"lavfi\.signalstats\.(YAVG|YLOW|YHIGH|YDIF)=([0-9.]+)", line)
        if m and t is not None:
            by_t[t][m.group(1).lower()] = float(m.group(2))
    return [row for _, row in sorted(by_t.items()) if "yavg" in row]


def _luma_row(sample: Any) -> dict[str, Any]:
    """Accept the dict rows of luma_samples() and the legacy (t, yavg) tuples (spread/ydif unknown)."""
    if isinstance(sample, dict):
        return sample
    t, y = sample
    return {"t": float(t), "yavg": float(y), "ylow": None, "yhigh": None, "ydif": None}


def is_blank_frame(row: dict[str, Any], *, blank_high: float, blank_low: float, max_spread: float) -> str | None:
    """"HIGH" / "LOW" when the frame is extreme in mean luma AND tonally uniform; else None.

    Uniformity is the criterion that separates a card/fade from a dark scene: a textured night frame keeps a
    10–90 % spread of tens of levels however dark its mean is.  A sample without spread data is never blank
    (unverifiable, not assumed)."""
    y = row.get("yavg")
    lo, hi = row.get("ylow"), row.get("yhigh")
    if y is None or lo is None or hi is None:
        return None
    if (float(hi) - float(lo)) >= max_spread:
        return None
    if float(y) > blank_high:
        return "HIGH"
    if float(y) < blank_low:
        return "LOW"
    return None

def segments_from_cuts(cuts: list[float], total: float) -> list[tuple[float, float]]:
    bounds = [0.0] + [c for c in cuts if 0.0 < c < total] + [total]
    return [(a, b) for a, b in zip(bounds, bounds[1:]) if b - a > 0.05]


def planned_timeline(contract: dict[str, Any]) -> list[dict[str, Any]]:
    t = 0.0
    rows = []
    for shot in contract.get("shots") or []:
        sec = float(shot.get("target_seconds") or 0)
        rows.append({"shot_id": shot.get("shot_id"), "start": t, "end": t + sec, "seconds": sec})
        t += sec
    return rows


def shots_overlapping(plan: list[dict[str, Any]], a: float, b: float) -> list[dict[str, Any]]:
    return [row for row in plan if row["end"] > a and row["start"] < b]


def same_subject_boundaries(contract: dict[str, Any], grouping_plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Consecutive same-scene units: last shot of A vs first shot of B with equal shot_size and equal cast."""
    if not grouping_plan:
        return []
    by_shot = {str(s.get("shot_id")): s for s in contract.get("shots") or []}
    def cast(shot: dict[str, Any]) -> set[str]:
        return {str(c.get("character_id") or c.get("character")) for c in ((shot.get("prompt_spec") or {}).get("cast") or [])}
    rows, prev, t = [], None, 0.0
    for unit in grouping_plan.get("units") or []:
        ids = unit.get("editorial_shot_ids") or []
        if prev and unit.get("scene_id") == prev.get("scene_id") and ids and prev.get("editorial_shot_ids"):
            a, b = by_shot.get(str(prev["editorial_shot_ids"][-1])), by_shot.get(str(ids[0]))
            if a and b and a.get("shot_size") == b.get("shot_size") and cast(a) and cast(a) == cast(b):
                rows.append({"at_seconds": round(t, 2), "from_unit": prev.get("unit_id"), "to_unit": unit.get("unit_id"),
                             "shot_size": a.get("shot_size"), "cast": sorted(cast(a))})
        t += float(unit.get("duration_seconds") or 0)
        prev = unit
    return rows


def evaluate(final: Path, contract: dict[str, Any], *, end_card_seconds: float, scene_threshold: float,
             static_yavg_delta: float, blank_high: float, blank_low: float,
             grouping_plan: dict[str, Any] | None = None, blank_max_spread: float = 8.0,
             frozen_ydif: float = 0.5, frozen_min_seconds: float = 1.0) -> dict[str, Any]:
    total = probe_duration(final)
    body = max(0.0, total - end_card_seconds)
    plan = planned_timeline(contract)
    cuts = scene_cuts(final, scene_threshold, body)
    segs = segments_from_cuts(cuts, body)
    lumas = [_luma_row(r) for r in luma_samples(final, body)]
    findings: list[dict[str, Any]] = []

    planned_count = len(plan)
    drift = (len(segs) - planned_count) / planned_count if planned_count else 0.0
    if abs(drift) > 0.20:
        findings.append({"code": "SHOT_COUNT_DRIFT", "detected_segments": len(segs), "planned_shots": planned_count,
                         "drift": round(drift, 3)})

    stretched = []
    for a, b in segs:
        if b - a > 8.0:
            over = shots_overlapping(plan, a, b)
            short = [row["shot_id"] for row in over if row["seconds"] <= 7.0]
            if short:
                stretched.append({"segment": [round(a, 2), round(b, 2)], "seconds": round(b - a, 2), "planned_shot_ids": short})
    if stretched:
        findings.append({"code": "SHOT_STRETCHED", "segments": stretched})

    static = []
    for a, b in segs:
        if b - a <= 5.0:
            continue
        ys = [r["yavg"] for r in lumas if a <= r["t"] < b]
        if len(ys) >= 3 and (max(ys) - min(ys)) < static_yavg_delta:
            static.append({"segment": [round(a, 2), round(b, 2)], "seconds": round(b - a, 2), "yavg_range": round(max(ys) - min(ys), 2),
                           "planned_shot_ids": [row["shot_id"] for row in shots_overlapping(plan, a, b)]})
    if static:
        findings.append({"code": "STATIC_HOLD_IN_DIALOGUE", "segments": static})

    blank = []
    run_start = None
    run_kind = None
    prev_t = None
    for row in lumas + [{"t": body, "yavg": None}]:
        t = row["t"]
        kind = None if row.get("yavg") is None else is_blank_frame(
            row, blank_high=blank_high, blank_low=blank_low, max_spread=blank_max_spread)
        if kind and kind == run_kind:
            prev_t = t
            continue
        if run_kind and run_start is not None and prev_t is not None and (prev_t - run_start) + 0.2 > 2.0:
            blank.append({"kind": run_kind, "segment": [round(run_start, 2), round(prev_t + 0.2, 2)], "seconds": round(prev_t + 0.2 - run_start, 2),
                          "planned_shot_ids": [row["shot_id"] for row in shots_overlapping(plan, run_start, prev_t + 0.2)]})
        run_kind, run_start, prev_t = kind, (t if kind else None), t
    if blank:
        findings.append({"code": "BLANK_SCREEN", "segments": blank})

    # frozen frames: consecutive samples with (near) zero temporal difference for >= frozen_min_seconds
    frozen = []
    f_start = None
    f_prev = None
    step = 1.0 / 5
    for row in lumas + [{"t": body, "ydif": None}]:
        ydif = row.get("ydif")
        if ydif is not None and float(ydif) < frozen_ydif:
            f_start = row["t"] if f_start is None else f_start
            f_prev = row["t"]
            continue
        if f_start is not None and f_prev is not None and (f_prev - f_start) + step >= frozen_min_seconds:
            frozen.append({"segment": [round(f_start, 2), round(f_prev + step, 2)], "seconds": round(f_prev + step - f_start, 2),
                           "planned_shot_ids": [r["shot_id"] for r in shots_overlapping(plan, f_start, f_prev + step)]})
        f_start, f_prev = None, None
    if frozen:
        findings.append({"code": "FROZEN_FRAME", "segments": frozen})
    dark_textured = sum(1 for r in lumas if r.get("yavg") is not None and r["yavg"] < blank_low
                        and r.get("ylow") is not None and (r["yhigh"] - r["ylow"]) >= blank_max_spread)

    # D-68 (Roger seq=36): same-scene unit boundaries whose two sides share shot size AND cast read as
    # jump cuts to a viewer (E06: 7.0 s, 15.2 s, 21.2 s, 35.4 s, 151.7 s).  Diagnostic only.
    boundary_rows = same_subject_boundaries(contract, grouping_plan)
    if boundary_rows:
        findings.append({"code": "SAME_SIZE_SAME_SUBJECT_BOUNDARY", "boundaries": boundary_rows})

    return {
        "schema": "nalu.final_cut_shot_plan_parity.v1",
        "authority": "SUPERVISOR_ORDERS seq=27 §六 (diagnostic, non-blocking)",
        "episode": contract.get("episode"),
        "final": str(final), "final_duration_seconds": round(total, 3), "body_seconds": round(body, 3),
        "end_card_seconds": end_card_seconds,
        "method": {"cuts": f"ffmpeg scdet threshold={scene_threshold}", "luma": "ffmpeg signalstats YAVG/YLOW/YHIGH/YDIF @5fps",
                   "static_yavg_delta": static_yavg_delta, "blank_high": blank_high, "blank_low": blank_low,
                   "blank_criterion": "extreme YAVG AND (YHIGH-YLOW) < blank_max_spread (Roger 2026-10-30)",
                   "blank_max_spread": blank_max_spread, "frozen_ydif": frozen_ydif, "frozen_min_seconds": frozen_min_seconds,
                   "dark_textured_samples_not_blank": dark_textured, "luma_samples": len(lumas)},
        "planned_shots": planned_count, "detected_cuts": len(cuts), "detected_segments": len(segs),
        "average_segment_seconds": round(body / len(segs), 2) if segs else None,
        "average_planned_shot_seconds": round(sum(r["seconds"] for r in plan) / planned_count, 2) if planned_count else None,
        "findings": findings,
        "status": "CLEAN" if not findings else "FINDINGS",
        "segments": [[round(a, 2), round(b, 2)] for a, b in segs],
    }


def checkpoint_block(report: dict[str, Any]) -> str:
    lines = [f"## 成片对镜头表机器比对（seq=27 §六，诊断，不阻断）",
             f"- 成片 {report['final_duration_seconds']} s（正片 {report['body_seconds']} s）；镜头表 {report['planned_shots']} 镜，"
             f"scdet 切出 {report['detected_segments']} 段；平均实际镜长 {report['average_segment_seconds']} s vs 计划 {report['average_planned_shot_seconds']} s",
             f"- 结果：{report['status']}"]
    for f in report["findings"]:
        if f["code"] == "SHOT_COUNT_DRIFT":
            lines.append(f"  - SHOT_COUNT_DRIFT：{f['detected_segments']} 段 vs {f['planned_shots']} 镜（偏差 {f['drift']:+.0%}）")
        elif f["code"] == "SAME_SIZE_SAME_SUBJECT_BOUNDARY":
            for row in f.get("boundaries", []):
                lines.append(f"  - 同景别同主体边界（观众读作跳切）：{row['at_seconds']} s {row['from_unit']}→{row['to_unit']} {row['shot_size']}")
        else:
            for seg in f.get("segments", []):
                lines.append(f"  - {f['code']}：{seg['segment'][0]}–{seg['segment'][1]} s（{seg['seconds']} s）镜 {', '.join(seg.get('planned_shot_ids') or [])}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--episode", required=True)
    ap.add_argument("--final", required=True)
    ap.add_argument("--contract", required=True)
    ap.add_argument("--grouping-plan", default=None, help="video unit grouping plan (D-68 same-subject boundary diagnostic)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--checkpoint-block-out", default=None)
    ap.add_argument("--end-card-seconds", type=float, default=3.0)
    ap.add_argument("--scene-threshold", type=float, default=8.0, help="scdet threshold (0-100; 8 = sensitive)")
    ap.add_argument("--static-yavg-delta", type=float, default=2.0)
    ap.add_argument("--blank-high", type=float, default=85.0 * 2.55)
    ap.add_argument("--blank-low", type=float, default=15.0 * 2.55)
    ap.add_argument("--blank-max-spread", type=float, default=8.0,
                    help="a frame is blank only if its 10-90 %% luma spread (YHIGH-YLOW) is below this (uniformity)")
    ap.add_argument("--frozen-ydif", type=float, default=0.5, help="signalstats YDIF below this = no motion between 5 fps samples")
    ap.add_argument("--frozen-min-seconds", type=float, default=1.0)
    a = ap.parse_args()
    contract = json.loads(Path(a.contract).read_text(encoding="utf-8"))
    grouping = json.loads(Path(a.grouping_plan).read_text(encoding="utf-8")) if a.grouping_plan and Path(a.grouping_plan).is_file() else None
    report = evaluate(Path(a.final), contract, end_card_seconds=a.end_card_seconds, scene_threshold=a.scene_threshold,
                      static_yavg_delta=a.static_yavg_delta, blank_high=a.blank_high, blank_low=a.blank_low,
                      grouping_plan=grouping)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    block = checkpoint_block(report)
    if a.checkpoint_block_out:
        Path(a.checkpoint_block_out).write_text(block, encoding="utf-8")
    print(json.dumps({"status": report["status"], "findings": [f["code"] for f in report["findings"]], "out": a.out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except _media.MediaToolBlocked as exc:
        print(str(exc), file=_sys.stderr)
        raise SystemExit(3) from None
