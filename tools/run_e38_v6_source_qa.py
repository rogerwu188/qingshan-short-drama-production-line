#!/usr/bin/env python3
"""Build an evidence-first source QA report for the E38 V6 videos."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path("/Users/rogerwu/qingshan_short_drama")
PLAN = ROOT / "workflow/claude_writer_agent/production/e38_claude_writer_v2_3f08265c_20260804/E38_PRO_V6_AUDIO_DRIVEN_NO_GLYPHS_RUN_PLAN.json"
AUDIO_RECEIPT = ROOT / "workflow/tasks/E38_V6_EXACT_EXPRESSIVE_AUDIO_ASSETS_20260805.json"
OUT_DIR = ROOT / "qa/e38_v6_audio_driven_no_glyphs_20260805"
REPORT = OUT_DIR / "E38_V6_SOURCE_QA_EVIDENCE.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(text: str) -> str:
    return re.sub(r"[^\u3400-\u9fffA-Za-z0-9]", "", text)


def media_info(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def make_contact_sheet(video: Path, out: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
            "-vf", "fps=1,scale=360:-1,tile=4x3:padding=4:margin=4:color=black",
            "-frames:v", "1", str(out),
        ],
        check=True,
    )


def run_ocr(video: Path, out: Path) -> dict:
    completed = subprocess.run(
        [
            "python3", str(ROOT / "tools/final_video_ocr_audit.py"),
            "--video", str(video), "--out", str(out), "--source-mode",
        ],
        check=False,
    )
    if completed.returncode not in (0, 1) or not out.exists():
        raise RuntimeError(f"OCR audit failed to produce evidence for {video}")
    return json.loads(out.read_text(encoding="utf-8"))


def transcribe(video: Path, out: Path) -> dict:
    subprocess.run(
        [
            "python3", str(ROOT / "tools/transcribe_media_for_qa.py"),
            "--media", str(video), "--out", str(out),
        ],
        check=True,
    )
    return json.loads(out.read_text(encoding="utf-8"))


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    audio = json.loads(AUDIO_RECEIPT.read_text(encoding="utf-8"))
    lines = {item["line_id"]: item for item in audio["results"]}
    results = []

    for unit in plan:
        shot_id = unit["shot_id"]
        video = Path(unit["out_dir"]) / "result_01.mp4"
        sheet_path = OUT_DIR / f"{shot_id}_CONTACT_SHEET.jpg"
        transcript_path = OUT_DIR / f"{shot_id}_ASR.json"
        asr = transcribe(video, transcript_path)
        transcript_segments = asr["segments"]
        transcript = "".join(item["text"] for item in transcript_segments)
        expected = "".join(lines[line_id]["text"] for line_id in unit["audio_line_ids"])
        make_contact_sheet(video, sheet_path)
        results.append(
            {
                "shot_id": shot_id,
                "video": str(video),
                "video_sha256": sha256(video),
                "media_info": media_info(video),
                "expected_dialogue": expected,
                "asr_transcript": transcript,
                "asr_segments": transcript_segments,
                "asr_similarity": round(
                    SequenceMatcher(None, normalize(expected), normalize(transcript)).ratio(), 4
                ),
                "asr_duration": asr["duration"],
                "contact_sheet": str(sheet_path),
                "manual_visual_qa": "PENDING",
            }
        )

    for result in results:
        shot_id = result["shot_id"]
        video = Path(result["video"])
        ocr_path = OUT_DIR / f"{shot_id}_OCR.json"
        ocr = run_ocr(video, ocr_path)
        result["ocr_evidence"] = {
            "path": str(ocr_path),
            "status_is_not_automatic_verdict": True,
            "recognitions": ocr["recognitions"],
            "critical_text_failures": ocr["critical_text_failures"],
        }

    payload = {
        "schema": "qingshan.e38.v6_source_qa_evidence.v1",
        "episode": "E38",
        "status": "PENDING_MANUAL_VISUAL_AND_AUDIO_ADJUDICATION",
        "text_policy": {
            "approved_exact_story_prop_text": "ALLOWED",
            "story_motivated_bound_brush_writing": "ALLOWED",
            "invented_pseudotext_or_misspelling": "FAIL",
            "provider_burned_dialogue_caption": "FAIL",
            "agentcut_final_subtitles": "REQUIRED_ALLOWED",
        },
        "results": results,
    }
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(REPORT), "units": len(results)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
