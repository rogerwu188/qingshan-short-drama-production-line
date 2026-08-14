#!/usr/bin/env python3
"""Select lowest-risk E27 video candidates and build exact-SHA visual review sheets."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
SELECTION = ROOT / "qa/e27_writer_agent_v040_video_ai_review_20260720/E27_WRITER_AGENT_V040_24_VIDEO_SELECTION.json"
COMPILED = Path("/Users/rogerwu/Documents/Codex/2026-07-20/qingshan-professional-writer-agent/outputs/qingshan-writer-agent/examples/e27.agent-native.compiled.json")
OUT = ROOT / "qa/e27_writer_agent_v040_video_visual_sheets_20260720"
ADJUDICATE = {"E27-N02", "E27-N12", "E27-N19", "E27-N21"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def count_value(value: object) -> int:
    if isinstance(value, list):
        return len(value)
    if value is None:
        return 0
    return int(value)


def run_audits(shot_id: str, video: Path) -> dict:
    task_id = video.stem.rsplit("_", 1)[-1]
    audit_dir = OUT / "candidate_audits" / shot_id / task_id
    audit_dir.mkdir(parents=True, exist_ok=True)
    cadence_path = audit_dir / "frame_cadence.json"
    ocr_path = audit_dir / "ocr.json"
    cadence_rc = subprocess.run([
        "python3", "tools/frame_cadence_audit.py", "--video", str(video), "--out", str(cadence_path)
    ], cwd=ROOT, capture_output=True).returncode
    ocr_rc = subprocess.run([
        "python3", "tools/final_video_ocr_audit.py", "--video", str(video), "--out", str(ocr_path),
        "--source-mode", "--allow-text", "__NO_TEXT_ALLOWED__", "--forbid-text", "__FORBIDDEN_TEXT__"
    ], cwd=ROOT, capture_output=True).returncode
    cadence = load(cadence_path)
    ocr = load(ocr_path)
    duplicate_events = sum(row.get("event_count", 0) for row in cadence.get("periodic_duplicates", {}).get("periodic_chains", []))
    critical_text = count_value(ocr.get("critical_text_failures", 0))
    unlisted_chinese = count_value(ocr.get("unlisted_chinese_hits", 0))
    critical_latin = count_value(ocr.get("critical_latin_chars", 0))
    risk_score = critical_text * 1000 + unlisted_chinese * 100 + critical_latin * 10 + duplicate_events
    return {
        "path": str(video),
        "sha256": sha256(video),
        "task_id": task_id,
        "cadence_status": "PASS" if cadence_rc == 0 else "FAIL",
        "ocr_status": "PASS" if ocr_rc == 0 else "FAIL",
        "critical_text_failures": critical_text,
        "unlisted_chinese_hits": unlisted_chinese,
        "critical_latin_chars": critical_latin,
        "periodic_duplicate_events": duplicate_events,
        "risk_score": risk_score,
        "cadence_report": str(cadence_path),
        "ocr_report": str(ocr_path),
    }


def candidate_paths(shot_id: str) -> list[Path]:
    return sorted(ROOT.glob(f"working_assets/e27_writer_agent_v040_video_v1*20260720/candidates/*{shot_id}*.mp4"))


def duration(path: Path) -> float:
    return float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)
    ], text=True).strip())


def make_sheet(shot_id: str, video: Path) -> Path:
    sheet_dir = OUT / "sheets"
    frame_dir = OUT / "frames" / shot_id
    sheet_dir.mkdir(parents=True, exist_ok=True)
    frame_dir.mkdir(parents=True, exist_ok=True)
    total = duration(video)
    frames = []
    for index, ratio in enumerate((0.15, 0.50, 0.85), 1):
        frame = frame_dir / f"frame_{index}.png"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{total * ratio:.3f}",
            "-i", str(video), "-frames:v", "1", "-vf", "scale=360:-2", str(frame)
        ], check=True)
        frames.append(frame)
    sheet = sheet_dir / f"{shot_id}_15_50_85.png"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(frames[0]), "-i", str(frames[1]), "-i", str(frames[2]),
        "-filter_complex", "[0:v][1:v][2:v]hstack=inputs=3[out]", "-map", "[out]", str(sheet)
    ], check=True)
    return sheet


def main() -> int:
    base = {row["shot_id"]: row for row in load(SELECTION)["items"]}
    compiled = load(COMPILED)
    shots = {row["shot_id"]: row for row in compiled["shot_contracts"]}
    adjudications = []
    for shot_id in sorted(ADJUDICATE):
        candidates = [run_audits(shot_id, path) for path in candidate_paths(shot_id)]
        if len(candidates) < 2:
            raise SystemExit(f"expected at least two candidates for {shot_id}")
        selected = min(candidates, key=lambda row: (row["risk_score"], row["task_id"]))
        base[shot_id] = {
            "shot_id": shot_id,
            "path": selected["path"],
            "sha256": selected["sha256"],
            "task_id": selected["task_id"],
            "objective_qa_status": (
                "PASS" if selected["cadence_status"] == selected["ocr_status"] == "PASS"
                else "CONDITIONAL_MACHINE_ADMISSION_PENDING_VISUAL_SHEET_REVIEW"
            ),
            "objective_qa": selected,
        }
        adjudications.append({
            "shot_id": shot_id,
            "status": "LOWEST_RISK_CANDIDATE_SELECTED_PENDING_VISUAL_SHEET_REVIEW",
            "selected": selected,
            "candidates": candidates,
            "selection_reason": "Lowest deterministic risk score after exact-candidate cadence and full-motion OCR rerun.",
            "rollback": [row["path"] for row in candidates if row["path"] != selected["path"]],
        })

    items = []
    final_selection = []
    for shot in sorted(shots.values(), key=lambda row: row["global_order"]):
        selected = base[shot["shot_id"]]
        video = Path(selected["path"])
        if sha256(video) != selected["sha256"]:
            raise SystemExit(f"selection SHA drift: {shot['shot_id']}")
        sheet = make_sheet(shot["shot_id"], video)
        sheet_sha = sha256(sheet)
        final_selection.append({**selected, "visual_sheet": str(sheet), "visual_sheet_sha256": sheet_sha})
        items.append({
            "path": str(sheet),
            "scope": "shot",
            "kind": "image",
            "importance": "critical",
            "pass_score": 4.5,
            "clip_id": shot["shot_id"],
            "metadata": {
                "episode": "E27",
                "scene_id": shot["scene_id"],
                "candidate_video_path": str(video),
                "candidate_video_sha256": selected["sha256"],
                "candidate_sheet_sha256": sheet_sha,
                "frame_sample_ratios": [0.15, 0.50, 0.85],
                "review_focus": [
                    f"Across the three chronological frames, the event must remain exactly: {shot['action']}",
                    f"The intended result must remain: {shot['visual']}",
                    f"Shot scale and geography must remain {shot['shot_scale']} in {shot['scene_id']}",
                    "character identity, age, gender, costume, prop ownership and screen direction stay stable across frames",
                    "Jiaotu remains female, including female facial identity and rabbit-ear silhouette motif in spirit form",
                    "motion progression is causal rather than looping, time-stretched or generic camera drift",
                    "no readable or pseudo-readable generated text, subtitle, watermark, logo, duplicate person or malformed anatomy",
                ],
            },
            "required_capabilities": ["image_analysis", "ocr"],
            "run_regression_ci": True,
            "use_existing_tools": True,
        })

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "E27_FOUR_FAILED_CANDIDATE_ADJUDICATION.json").write_text(
        json.dumps({"schema": "qingshan.conditional_machine_admission.v1", "episode": "E27", "items": adjudications}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUT / "E27_24_VIDEO_FINAL_SELECTION_WITH_SHEETS.json").write_text(
        json.dumps({"schema": "qingshan.e27.video_selection.v2", "episode": "E27", "count": 24, "items": final_selection}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    request = OUT / "E27_24_VIDEO_VISUAL_SHEET_AI_REVIEW_REQUEST.json"
    request.write_text(json.dumps({"items": items, "workers": 4}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "sheets": len(items), "request": str(request), "request_sha256": sha256(request)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
