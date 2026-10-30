#!/usr/bin/env python3
"""unit_recut.py — render editorial re-cuts of already-generated unit clips (free, no provider call).

Roger 2026-10-30 (E12 成片审看 item 3): the conflict block must cut faster than the setup, threat actions
need 起手—动作—反应 on screen, and hallucinated inserts (黑甲武士) must go.  Several of those fixes cannot
be expressed as one in/out per unit (the AgentCut builder's only editing primitive): dropping a stretch
of H3 babble in the middle of a unit, covering a join with a reaction cutaway taken from frames of a
neighbouring unit that the cut does not use, or keeping a unit's voice while swapping its picture.

A *recut plan* (``nalu.unit_recut_plan.v1``, authored by the editor, one entry per unit) describes each
recut unit as an ordered list of segments; every segment names a picture source ``[unit, in, out]`` and an
audio source ``[unit, in, out]`` of equal length (source-clip seconds).  This tool renders ONE derived
clip per planned unit (ffmpeg trim/atrim + concat, libx264 crf 16, 10 ms audio fades at the joins) and
writes a *recut report* (``nalu.unit_recut_report.v1``) in the shape the AgentCut builder's derived-clip
hooks already understand (``--push-in-compensation`` precedent)::

    units[uid] = {status: "APPLIED", source, source_sha256, output, output_sha256, in: 0.0, duration,
                  segments, internal_cuts_s, sources_sha256: {unit: sha}}

The builder (``--unit-recut <report>``) then uses the derived clip for the unit's picture AND sound with
``in = 0`` and the report's duration, and skips the measured-edit / head / tail trims for that unit —
the editor's cut list overrides the measured interval (E12: the MEC trimmed the slap's reaction and hand
print off VU-045 on the strength of a whisper hallucination on a non-speech unit).

Rules
  * Idempotent: an output whose sha matches the report is not re-rendered; a plan change (segment list
    sha) re-renders and supersedes the row.  Outputs never overwrite source clips.
  * Every source clip's sha is recorded; the builder re-checks the unit's own source sha before use.
  * No frame may be used twice across the cut — the plan author checks it; this tool records
    ``frames_borrowed_from`` so a later audit can.
  * Only the units listed in the plan are touched; everything else keeps its AgentCut row.

Subtitles: a plan unit may carry ``"subtitles": {"drop": [shot_id, ...], "override": {shot_id: text}}`` for
contract lines whose audio the re-cut removed (H3 babble) or truncated; the row copies it and
``build_burnin_subtitles.py --unit-recut <report>`` applies it (a dropped line is never burned in).

Sources: ``--source-dir`` holds the admitted unit clips; ``--overlay-dir`` (optional) holds derived clips
that should be preferred when present (e.g. lock-off-stabilised units), so a re-cut reads the stabilised
frames and the builder sees one derived file per unit.

Usage
  unit_recut.py --plan <recut_plan.json> --source-dir <dir with <UID>.mp4> [--overlay-dir <dir>]
                --out-dir <dir> --report <json> [--variant B] [--ffmpeg ffmpeg] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PLAN_SCHEMA = "nalu.unit_recut_plan.v1"
REPORT_SCHEMA = "nalu.unit_recut_report.v1"
FFMPEG = os.environ.get("NALU_FFMPEG", "ffmpeg")
FPS = 24
TOLERANCE_S = 0.002


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def segments_of(plan_unit: dict[str, Any], variant: str | None) -> list[dict[str, Any]]:
    if variant and plan_unit.get(f"variant_{variant}_segments"):
        return list(plan_unit[f"variant_{variant}_segments"])
    return list(plan_unit["segments"])


def validate_segments(uid: str, segs: list[dict[str, Any]]) -> list[str]:
    """Shape and arithmetic checks; returns a list of problems (empty = valid)."""
    problems: list[str] = []
    if not segs:
        return [f"{uid}: no segments"]
    for i, seg in enumerate(segs):
        try:
            vu, vi, vo = seg["video"]
            au, ai, ao = seg["audio"]
        except (KeyError, TypeError, ValueError):
            problems.append(f"{uid}[{i}]: segment needs video=[unit,in,out] and audio=[unit,in,out]")
            continue
        if not (float(vo) > float(vi) >= 0 and float(ao) > float(ai) >= 0):
            problems.append(f"{uid}[{i}]: in/out must satisfy 0 <= in < out")
        if abs((float(vo) - float(vi)) - (float(ao) - float(ai))) > TOLERANCE_S:
            problems.append(f"{uid}[{i}]: picture and sound segments differ in length")
    return problems


def plan_digest(segs: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(segs, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def internal_cuts(segs: list[dict[str, Any]]) -> list[float]:
    """Output-time positions where the picture source changes (a visible cut inside the derived clip)."""
    cuts: list[float] = []
    t = 0.0
    prev = None
    for seg in segs:
        vu, vi, vo = seg["video"]
        if prev is not None and (vu != prev[0] or abs(float(vi) - prev[1]) > TOLERANCE_S):
            cuts.append(round(t, 3))
        t += float(vo) - float(vi)
        prev = (vu, float(vo))
    return cuts


def clip_path(unit: str, source_dir: Path, overlay_dir: Path | None = None) -> Path:
    """The clip a unit's frames come from: the overlay (derived, e.g. stabilised) when present, else the source."""
    if overlay_dir is not None and (overlay_dir / f"{unit}.mp4").is_file():
        return overlay_dir / f"{unit}.mp4"
    return source_dir / f"{unit}.mp4"


def render(uid: str, segs: list[dict[str, Any]], source_dir: Path, out: Path, ffmpeg: str = FFMPEG,
           overlay_dir: Path | None = None) -> float:
    inputs: list[Path] = []
    index: dict[str, int] = {}
    fc: list[str] = []
    vlab: list[str] = []
    alab: list[str] = []

    def src(unit: str) -> int:
        if unit not in index:
            path = clip_path(unit, source_dir, overlay_dir)
            if not path.is_file():
                raise FileNotFoundError(str(path))
            index[unit] = len(inputs)
            inputs.append(path)
        return index[unit]

    for i, seg in enumerate(segs):
        vu, vi, vo = seg["video"]
        au, ai, ao = seg["audio"]
        vi, vo, ai, ao = float(vi), float(vo), float(ai), float(ao)
        fc.append(f"[{src(vu)}:v]trim=start={vi}:end={vo},setpts=PTS-STARTPTS,fps={FPS},format=yuv420p[v{i}]")
        fc.append(f"[{src(au)}:a]atrim=start={ai}:end={ao},asetpts=PTS-STARTPTS,aresample=48000,"
                  f"afade=t=in:d=0.01,afade=t=out:st={max(0.0, ao - ai - 0.01):.3f}:d=0.01[a{i}]")
        vlab.append(f"[v{i}]")
        alab.append(f"[a{i}]")
    fc.append("".join(f"{v}{a}" for v, a in zip(vlab, alab)) + f"concat=n={len(segs)}:v=1:a=1[vo][ao]")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".rendering.mp4")
    cmd = [ffmpeg, "-v", "error", "-y"]
    for path in inputs:
        cmd += ["-i", str(path)]
    cmd += ["-filter_complex", ";".join(fc), "-map", "[vo]", "-map", "[ao]",
            "-c:v", "libx264", "-crf", "16", "-preset", "fast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(tmp)]
    subprocess.run(cmd, check=True)
    tmp.replace(out)
    return round(sum(float(s["video"][2]) - float(s["video"][1]) for s in segs), 3)


def run(plan_path: Path, source_dir: Path, out_dir: Path, report_path: Path, *, variant: str | None = None,
        dry_run: bool = False, ffmpeg: str = FFMPEG, overlay_dir: Path | None = None) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("schema") != PLAN_SCHEMA:
        raise SystemExit(f"UNIT_RECUT_PLAN_SCHEMA:{plan.get('schema')}")
    previous = {}
    if report_path.is_file():
        try:
            previous = (json.loads(report_path.read_text(encoding="utf-8")) or {}).get("units") or {}
        except ValueError:
            previous = {}
    units_out: dict[str, Any] = {}
    problems: list[str] = []
    for uid, plan_unit in sorted((plan.get("units") or {}).items()):
        segs = segments_of(plan_unit, variant)
        bad = validate_segments(uid, segs)
        if bad:
            problems.extend(bad)
            units_out[uid] = {"status": "INVALID", "problems": bad}
            continue
        source = source_dir / f"{uid}.mp4"
        if not source.is_file():
            problems.append(f"{uid}: source clip missing {source}")
            units_out[uid] = {"status": "SOURCE_MISSING", "source": str(source)}
            continue
        used_units = sorted({str(s["video"][0]) for s in segs} | {str(s["audio"][0]) for s in segs})
        missing = [u for u in used_units if not clip_path(u, source_dir, overlay_dir).is_file()]
        if missing:
            problems.append(f"{uid}: borrowed source clip(s) missing {missing}")
            units_out[uid] = {"status": "SOURCE_MISSING", "missing": missing}
            continue
        digest = plan_digest(segs)
        output = out_dir / f"{uid}.mp4"
        prev = previous.get(uid) or {}
        row: dict[str, Any] = {
            "status": "PLANNED", "source": str(source), "source_sha256": sha256_file(source),
            "output": str(output), "in": 0.0,
            "duration": round(sum(float(s["video"][2]) - float(s["video"][1]) for s in segs), 3),
            "segments": segs, "plan_digest": digest, "internal_cuts_s": internal_cuts(segs),
            "frames_borrowed_from": [u for u in used_units if u != uid],
            "sources_sha256": {u: sha256_file(clip_path(u, source_dir, overlay_dir)) for u in used_units},
            "source_files": {u: str(clip_path(u, source_dir, overlay_dir)) for u in used_units},
            "subtitles": plan_unit.get("subtitles") or {},
            "reason": plan_unit.get("reason"),
        }
        if (prev.get("status") == "APPLIED" and prev.get("plan_digest") == digest and output.is_file()
                and sha256_file(output) == prev.get("output_sha256")
                and prev.get("sources_sha256") == row["sources_sha256"]):
            row.update({"status": "APPLIED", "output_sha256": prev["output_sha256"], "rendered_at": prev.get("rendered_at"),
                        "reused": True})
        elif dry_run:
            row["status"] = "DRY_RUN"
        else:
            if output.is_file():
                # parked under _superseded/ so the unit-ASR glob (<EP>-VU-*.mp4) never picks it up again
                parked_dir = out_dir / "_superseded"
                parked_dir.mkdir(parents=True, exist_ok=True)
                stale = parked_dir / f"{output.stem}__{(sha256_file(output))[:12]}{output.suffix}"
                output.replace(stale)
                row["superseded_output"] = str(stale)
            rendered = render(uid, segs, source_dir, output, ffmpeg=ffmpeg, overlay_dir=overlay_dir)
            row.update({"status": "APPLIED", "output_sha256": sha256_file(output), "rendered_at": now(),
                        "rendered_duration": rendered})
        units_out[uid] = row
    report = {
        "schema": REPORT_SCHEMA, "episode": plan.get("episode"), "recorded_at": now(),
        "plan": str(plan_path), "plan_sha256": sha256_file(plan_path), "variant": variant,
        "source_dir": str(source_dir), "overlay_dir": str(overlay_dir) if overlay_dir else None, "out_dir": str(out_dir),
        "applied": sorted(u for u, r in units_out.items() if r.get("status") == "APPLIED"),
        "problems": problems, "status": "FAIL" if problems else ("DRY_RUN" if dry_run else "PASS"),
        "units": units_out,
        "builder_hook": "build_agentcut_from_admitted_storyboard_sources.py --unit-recut <this report>",
        "method": "ffmpeg trim/atrim + concat per unit, libx264 crf16 fps24 yuv420p, aac 192k 48k, 10 ms audio fades at joins; "
                  "picture+audio of a unit come from ONE derived file (MEASURED_EDIT_REQUIRES_SAME_NATIVE_AV_SOURCE)",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def applied_sources(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """unit -> APPLIED row whose output still exists with the recorded sha (for the AgentCut build)."""
    out: dict[str, dict[str, Any]] = {}
    for uid, row in (report.get("units") or {}).items():
        if row.get("status") != "APPLIED":
            continue
        target = Path(str(row.get("output") or ""))
        if target.is_file() and sha256_file(target) == row.get("output_sha256"):
            out[str(uid)] = row
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--plan", required=True, type=Path)
    ap.add_argument("--source-dir", required=True, type=Path)
    ap.add_argument("--overlay-dir", type=Path, default=None,
                    help="derived clips (e.g. lock-off stabilised) preferred over --source-dir when present")
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--report", required=True, type=Path)
    ap.add_argument("--variant", default=None, help="use variant_<X>_segments where a unit defines them")
    ap.add_argument("--ffmpeg", default=FFMPEG)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    report = run(args.plan, args.source_dir, args.out_dir, args.report, variant=args.variant,
                 dry_run=args.dry_run, ffmpeg=args.ffmpeg, overlay_dir=args.overlay_dir)
    print(json.dumps({"status": report["status"], "applied": report["applied"], "problems": report["problems"],
                      "report": str(args.report)}, ensure_ascii=False))
    return 0 if report["status"] in ("PASS", "DRY_RUN") else 1


if __name__ == "__main__":
    sys.exit(main())
