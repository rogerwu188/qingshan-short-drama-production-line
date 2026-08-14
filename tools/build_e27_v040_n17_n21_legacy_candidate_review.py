#!/usr/bin/env python3
"""Build exact-SHA visual and objective review evidence for E27 N17/N21 candidates."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
COMPILED = Path(
    "/Users/rogerwu/Documents/Codex/2026-07-20/"
    "qingshan-professional-writer-agent/outputs/qingshan-writer-agent/"
    "examples/e27.agent-native.compiled.json"
)
OUT = ROOT / "qa/e27_writer_agent_v040_n17_n21_legacy_candidate_review_20260720"
CANDIDATES = {
    "E27-N17": [
        ROOT / "working_assets/e27_writer_agent_v030_video_v1_20260720/candidates/E27_E27-N17-WRITER-AGENT-V030-VIDEO-V1_684b2803-b106-40e7-b170-847902466683.mp4",
        ROOT / "working_assets/e27_writer_agent_v040_video_v1_20260720/candidates/E27_E27-N17-WRITER-AGENT-V040-VIDEO-V1_a8b99671-2862-43bd-8ac4-f78e585eef1d.mp4",
        ROOT / "working_assets/e27_writer_agent_v040_video_visualfix_r1_20260720/candidates/E27_E27-N17-WRITER-AGENT-V040-VIDEO-VISUALFIX-R1_579a3fbb-1122-4e68-b35f-51d58faad543.mp4",
    ],
    "E27-N21": [
        ROOT / "working_assets/e27_writer_agent_v030_video_v1_20260720/candidates/E27_E27-N21-WRITER-AGENT-V030-VIDEO-V1_a24513bb-92f8-4158-a7f8-2c9c52dce5bd.mp4",
        ROOT / "working_assets/e27_writer_agent_v040_video_v1_20260720/candidates/E27_E27-N21-WRITER-AGENT-V040-VIDEO-V1_9228badd-e805-403c-b314-0709b68256e1.mp4",
        ROOT / "working_assets/e27_writer_agent_v040_video_v1_20260720/candidates/E27_E27-N21-WRITER-AGENT-V040-VIDEO-V1_a0c394e3-801c-4d8d-8c4d-54d7cca03eda.mp4",
        ROOT / "working_assets/e27_writer_agent_v040_video_visualfix_r1_20260720/candidates/E27_E27-N21-WRITER-AGENT-V040-VIDEO-VISUALFIX-R1_b4354526-5f4b-4f4f-a1bc-11e67c9b9301.mp4",
    ],
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def duration(path: Path) -> float:
    return float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ], text=True).strip())


def candidate_id(path: Path) -> str:
    if "v030" in str(path):
        version = "V030"
    elif "visualfix_r1" in str(path):
        version = "V040-R1"
    else:
        version = "V040"
    return f"{version}-{path.stem.rsplit('_', 1)[-1][:8]}"


def run_objective_audits(shot_id: str, cid: str, video: Path) -> dict:
    audit_dir = OUT / "objective" / shot_id / cid
    audit_dir.mkdir(parents=True, exist_ok=True)
    cadence = audit_dir / "frame_cadence.json"
    ocr = audit_dir / "ocr.json"
    cadence_run = subprocess.run([
        "python3", "tools/frame_cadence_audit.py", "--video", str(video), "--out", str(cadence),
    ], cwd=ROOT, capture_output=True, text=True)
    ocr_run = subprocess.run([
        "python3", "tools/final_video_ocr_audit.py", "--video", str(video), "--out", str(ocr),
        "--source-mode", "--allow-text", "__NO_TEXT_ALLOWED__", "--forbid-text", "__FORBIDDEN_TEXT__",
    ], cwd=ROOT, capture_output=True, text=True)
    return {
        "cadence_status": "PASS" if cadence_run.returncode == 0 else "FAIL",
        "ocr_status": "PASS" if ocr_run.returncode == 0 else "FAIL",
        "cadence_report": str(cadence),
        "ocr_report": str(ocr),
        "cadence_stderr": cadence_run.stderr.strip(),
        "ocr_stderr": ocr_run.stderr.strip(),
    }


def make_sheet(shot_id: str, cid: str, video: Path) -> Path:
    frame_dir = OUT / "frames" / shot_id / cid
    sheet_dir = OUT / "sheets"
    frame_dir.mkdir(parents=True, exist_ok=True)
    sheet_dir.mkdir(parents=True, exist_ok=True)
    total = duration(video)
    frames = []
    for index, ratio in enumerate((0.15, 0.50, 0.85), 1):
        frame = frame_dir / f"frame_{index}.png"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{total * ratio:.3f}", "-i", str(video), "-frames:v", "1",
            "-vf", "scale=360:-2", str(frame),
        ], check=True)
        frames.append(frame)
    sheet = sheet_dir / f"{shot_id}_{cid}_15_50_85.png"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(frames[0]), "-i", str(frames[1]), "-i", str(frames[2]),
        "-filter_complex", "[0:v][1:v][2:v]hstack=inputs=3[out]",
        "-map", "[out]", str(sheet),
    ], check=True)
    return sheet


def main() -> int:
    shots = {row["shot_id"]: row for row in load(COMPILED)["shot_contracts"]}
    items = []
    inventory = []
    for shot_id, paths in CANDIDATES.items():
        shot = shots[shot_id]
        for path in paths:
            if not path.is_file():
                raise SystemExit(f"missing candidate: {path}")
            cid = candidate_id(path)
            video_sha = sha256(path)
            sheet = make_sheet(shot_id, cid, path)
            objective = run_objective_audits(shot_id, cid, path)
            inventory.append({
                "shot_id": shot_id,
                "candidate_id": cid,
                "path": str(path),
                "sha256": video_sha,
                "sheet": str(sheet),
                "sheet_sha256": sha256(sheet),
                "objective": objective,
            })
            items.append({
                "path": str(sheet),
                "scope": "shot",
                "kind": "image",
                "importance": "critical",
                "pass_score": 4.5,
                "clip_id": f"{shot_id}::{cid}",
                "metadata": {
                    "episode": "E27",
                    "scene_id": shot["scene_id"],
                    "candidate_video_path": str(path),
                    "candidate_video_sha256": video_sha,
                    "candidate_sheet_sha256": sha256(sheet),
                    "frame_sample_ratios": [0.15, 0.50, 0.85],
                    "review_focus": [
                        f"Across all three frames, the exact action remains: {shot['action']}",
                        f"The exact visual result remains: {shot['visual']}",
                        f"The scale/geography remain {shot['shot_scale']} / {shot['scene_id']}",
                        "canonical identity, gender, costume, cast count, anatomy, prop ownership and screen direction remain stable",
                        "Jiaotu remains female, with a female facial identity and rabbit-ear silhouette motif in spirit form",
                        "no duplicate body, malformed anatomy, readable or pseudo-readable text, subtitle, watermark or logo",
                    ],
                },
                "required_capabilities": ["image_analysis", "ocr"],
                "run_regression_ci": True,
                "use_existing_tools": True,
            })
    if len(items) != 7:
        raise SystemExit(f"expected 7 candidates, got {len(items)}")
    OUT.mkdir(parents=True, exist_ok=True)
    request = OUT / "E27_N17_N21_7_CANDIDATE_AI_REVIEW_REQUEST.json"
    inventory_path = OUT / "E27_N17_N21_7_CANDIDATE_INVENTORY.json"
    request.write_text(json.dumps({"items": items, "workers": 4}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    inventory_path.write_text(json.dumps({"episode": "E27", "items": inventory}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "count": len(items),
        "request": str(request),
        "request_sha256": sha256(request),
        "inventory": str(inventory_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
