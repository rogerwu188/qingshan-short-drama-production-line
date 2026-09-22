#!/usr/bin/env python3
"""final_cut_shot_plan_parity.py — S7 final-cut vs shot-table machine comparison (SUPERVISOR_ORDERS seq=27 §六).

Diagnostic only (no gate_id, never blocks).  Runs after the S7 final render and before the S8 line-owner
screening, writes ``assembly/<EP>_FINAL_CUT_SHOT_PLAN_PARITY.json`` and a short block for CHECKPOINT.md:

  * scdet cut count vs shot-table shot count            → SHOT_COUNT_DRIFT      (|drift| > 20 %)
  * any real segment > 8 s whose planned shot is ≤ 7 s   → SHOT_STRETCHED        (lists shot ids by timeline position)
  * two consecutive cuts with near-static luma and > 5 s → STATIC_HOLD_IN_DIALOGUE
  * luma YAVG > 85 % or < 15 % of range for > 2 s        → BLANK_SCREEN

Measurements come from ffmpeg (``scdet`` scene-change detection and ``signalstats`` YAVG sampled at 5 fps).
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


def luma_samples(path: Path, until: float, fps: int = 5) -> list[tuple[float, float]]:
    out = run([_media.require_ffmpeg(), "-hide_banner", "-nostats", "-i", str(path), "-t", f"{until:.3f}",
               "-vf", f"fps={fps},signalstats,metadata=print:key=lavfi.signalstats.YAVG", "-an", "-f", "null", "-"])
    rows: list[tuple[float, float]] = []
    t = None
    for line in out.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r"lavfi\.signalstats\.YAVG=([0-9.]+)", line)
        if m and t is not None:
            rows.append((t, float(m.group(1))))
    return rows


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
             grouping_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    total = probe_duration(final)
    body = max(0.0, total - end_card_seconds)
    plan = planned_timeline(contract)
    cuts = scene_cuts(final, scene_threshold, body)
    segs = segments_from_cuts(cuts, body)
    lumas = luma_samples(final, body)
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
        ys = [y for t, y in lumas if a <= t < b]
        if len(ys) >= 3 and (max(ys) - min(ys)) < static_yavg_delta:
            static.append({"segment": [round(a, 2), round(b, 2)], "seconds": round(b - a, 2), "yavg_range": round(max(ys) - min(ys), 2),
                           "planned_shot_ids": [row["shot_id"] for row in shots_overlapping(plan, a, b)]})
    if static:
        findings.append({"code": "STATIC_HOLD_IN_DIALOGUE", "segments": static})

    blank = []
    run_start = None
    run_kind = None
    prev_t = None
    for t, y in lumas + [(body, None)]:
        kind = None if y is None else ("HIGH" if y > blank_high else ("LOW" if y < blank_low else None))
        if kind and kind == run_kind:
            prev_t = t
            continue
        if run_kind and run_start is not None and prev_t is not None and (prev_t - run_start) + 0.2 > 2.0:
            blank.append({"kind": run_kind, "segment": [round(run_start, 2), round(prev_t + 0.2, 2)], "seconds": round(prev_t + 0.2 - run_start, 2),
                          "planned_shot_ids": [row["shot_id"] for row in shots_overlapping(plan, run_start, prev_t + 0.2)]})
        run_kind, run_start, prev_t = kind, (t if kind else None), t
    if blank:
        findings.append({"code": "BLANK_SCREEN", "segments": blank})

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
        "method": {"cuts": f"ffmpeg scdet threshold={scene_threshold}", "luma": "ffmpeg signalstats YAVG @5fps",
                   "static_yavg_delta": static_yavg_delta, "blank_high": blank_high, "blank_low": blank_low},
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
