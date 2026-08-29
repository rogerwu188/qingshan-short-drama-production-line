#!/usr/bin/env python3
"""Media-level safe-cut and real adjacent-boundary acceptance gate.

The gate intentionally separates machine checks from visual adjudication.  It
creates four-frame evidence for every boundary and refuses PASS until the
declared continuity domains have explicit decisions bound to that evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

try:
    from tools.dialogue_cut_safety import compile_dialogue_windows, evaluate_cut
except ModuleNotFoundError:
    from dialogue_cut_safety import compile_dialogue_windows, evaluate_cut


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "qingshan.media_boundary_acceptance.v1_safe_cut_and_real_transition"
DECISION_DOMAINS = (
    "plot_continuity",
    "identity_and_wardrobe_continuity",
    "pose_and_blocking_continuity",
    "map_and_axis_continuity",
    "prop_continuity",
    "sound_continuity",
    "transition_motivation",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _probe_duration(path: Path) -> float:
    return float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ], text=True).strip())


def _tail_max_volume(path: Path, start: float, end: float) -> float | None:
    if end - start <= 0.05:
        return None
    process = subprocess.run([
        "ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.6f}", "-to", f"{end:.6f}",
        "-i", str(path), "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-",
    ], capture_output=True, text=True, check=False)
    match = re.search(r"max_volume:\s*(-?inf|-?\d+(?:\.\d+)?) dB", process.stderr)
    if not match or match.group(1) == "-inf":
        return None
    return float(match.group(1))


def _frame(path: Path, second: float, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{max(second, 0):.6f}",
        "-i", str(path), "-frames:v", "1", "-vf", "scale=270:-2", str(out),
    ], check=True)


def _mean_luma(path: Path) -> float:
    image = Image.open(path).convert("L")
    pixels = list(image.getdata())
    return sum(pixels) / len(pixels)


def _motion_delta(left: Path, right: Path) -> float:
    a = Image.open(left).convert("L").resize((96, 160))
    b = Image.open(right).convert("L").resize((96, 160))
    return sum(abs(x - y) for x, y in zip(a.getdata(), b.getdata())) / (96 * 160)


def _contact_sheet(boundary_id: str, frames: list[Path], labels: list[str], out: Path) -> None:
    images = [Image.open(path).convert("RGB") for path in frames]
    width = max(image.width for image in images)
    height = max(image.height for image in images)
    canvas = Image.new("RGB", (width * 4, height + 70), "black")
    draw = ImageDraw.Draw(canvas)
    for index, (image, label) in enumerate(zip(images, labels)):
        canvas.paste(image, (index * width, 40))
        draw.text((index * width + 8, 12), label, fill="white")
    draw.text((8, height + 48), boundary_id, fill="white")
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=92)


def evaluate_boundary_decision(decision: dict[str, Any] | None) -> list[str]:
    if not decision:
        return ["REAL_MEDIA_VISUAL_DECISION_MISSING"]
    failures = []
    for domain in DECISION_DOMAINS:
        if decision.get(domain) != "PASS":
            failures.append(f"REAL_MEDIA_DOMAIN_NOT_PASS:{domain}:{decision.get(domain)}")
    if not str(decision.get("reviewer") or "").strip():
        failures.append("REAL_MEDIA_REVIEWER_MISSING")
    return failures


def run(media_map: dict[str, Any], grouped: dict[str, Any], out_dir: Path, decisions: dict[str, Any]) -> dict[str, Any]:
    media_rows = media_map.get("rows") or []
    units = grouped.get("units") or []
    if len(media_rows) != len(units):
        raise ValueError("media map and grouped manifest unit counts differ")
    media_by_id = {str(row["unit_id"]): row for row in media_rows}
    rows: list[dict[str, Any]] = []
    all_failures: list[str] = []
    for index, (left_unit, right_unit) in enumerate(zip(units, units[1:]), start=1):
        left_id, right_id = str(left_unit["unit_id"]), str(right_unit["unit_id"])
        contract = right_unit.get("incoming_transition_contract") or left_unit.get("outgoing_transition_contract") or {}
        boundary_id = str(contract.get("boundary_id") or f"BND-{left_id}-{right_id}")
        left_row, right_row = media_by_id[left_id], media_by_id[right_id]
        left_media, right_media = ROOT / left_row["media_path"], ROOT / right_row["media_path"]
        left_actual, right_actual = _probe_duration(left_media), _probe_duration(right_media)
        cut = float(left_row["planned_duration_seconds"])
        dialogue_contract_failures: list[str] = []
        try:
            windows = compile_dialogue_windows(left_unit)
            dialogue_end = max((float(row["end_seconds"]) for row in windows), default=None)
        except ValueError as error:
            windows = []
            dialogue_end = None
            dialogue_contract_failures.append(f"PREGEN_DIALOGUE_WINDOW_INVALID:{error}")
        tail_volume = _tail_max_volume(left_media, cut, left_actual) if cut < left_actual else None
        cut_report = evaluate_cut(
            planned_cut_seconds=cut,
            actual_duration_seconds=left_actual,
            dialogue_end_seconds=dialogue_end,
            trimmed_tail_max_volume_db=tail_volume,
        )
        frame_dir = out_dir / "frames" / boundary_id
        frame_paths = [
            frame_dir / "01_tail_pre.jpg", frame_dir / "02_tail_edge.jpg",
            frame_dir / "03_head_edge.jpg", frame_dir / "04_head_post.jpg",
        ]
        _frame(left_media, max(0.0, min(cut, left_actual) - 0.72), frame_paths[0])
        _frame(left_media, max(0.0, min(cut, left_actual) - 0.08), frame_paths[1])
        _frame(right_media, min(0.08, max(0.0, right_actual - 0.04)), frame_paths[2])
        _frame(right_media, min(0.72, max(0.0, right_actual - 0.04)), frame_paths[3])
        sheet = out_dir / "contact_sheets" / f"{index:02d}_{boundary_id}.jpg"
        _contact_sheet(boundary_id, frame_paths, ["tail -0.72s", "tail -0.08s", "head +0.08s", "head +0.72s"], sheet)
        machine_failures = dialogue_contract_failures + list(cut_report["failures"])
        lumas = [_mean_luma(path) for path in frame_paths]
        if min(lumas) < 4.0:
            machine_failures.append("BOUNDARY_CONTAINS_NEAR_BLACK_FRAME")
        tail_motion = _motion_delta(frame_paths[0], frame_paths[1])
        head_motion = _motion_delta(frame_paths[2], frame_paths[3])
        if tail_motion < 0.12:
            machine_failures.append("TAIL_HANDLE_EFFECTIVELY_FROZEN")
        if head_motion < 0.12:
            machine_failures.append("HEAD_HANDLE_EFFECTIVELY_FROZEN")
        decision = (decisions.get("boundaries") or {}).get(boundary_id)
        visual_failures = evaluate_boundary_decision(decision)
        failures = machine_failures + visual_failures
        row = {
            "boundary_id": boundary_id,
            "from_unit_id": left_id,
            "to_unit_id": right_id,
            "transition_contract": contract,
            "safe_cut": cut_report,
            "machine_evidence": {
                "tail_motion_delta": round(tail_motion, 4),
                "head_motion_delta": round(head_motion, 4),
                "frame_mean_luma": [round(value, 3) for value in lumas],
                "contact_sheet": str(sheet.relative_to(ROOT)),
                "contact_sheet_sha256": _sha(sheet),
            },
            "real_media_visual_decision": decision,
            "status": "PASS" if not failures else "FAIL",
            "failures": failures,
        }
        rows.append(row)
        all_failures.extend(f"{boundary_id}:{failure}" for failure in failures)
    return {
        "schema": SCHEMA,
        "status": "PASS" if not all_failures else "FAIL",
        "boundary_count": len(rows),
        "required_decision_domains": list(DECISION_DOMAINS),
        "rows": rows,
        "failures": all_failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-map", type=Path, required=True)
    parser.add_argument("--grouped-manifest", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--decisions", type=Path)
    args = parser.parse_args()
    args.out_dir = args.out_dir.resolve()
    args.media_map = args.media_map.resolve()
    args.grouped_manifest = args.grouped_manifest.resolve()
    if args.decisions:
        args.decisions = args.decisions.resolve()
    media_map = json.loads(args.media_map.read_text(encoding="utf-8"))
    grouped = json.loads(args.grouped_manifest.read_text(encoding="utf-8"))
    decisions = json.loads(args.decisions.read_text(encoding="utf-8")) if args.decisions else {}
    report = run(media_map, grouped, args.out_dir, decisions)
    report["source_media_map"] = str(args.media_map.resolve().relative_to(ROOT))
    report["source_media_map_sha256"] = _sha(args.media_map)
    report["source_grouped_manifest"] = str(args.grouped_manifest.resolve().relative_to(ROOT))
    report["source_grouped_manifest_sha256"] = _sha(args.grouped_manifest)
    out = args.out_dir / "MEDIA_BOUNDARY_ACCEPTANCE_REPORT.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "boundaries": report["boundary_count"], "failures": len(report["failures"]), "report": str(out)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
