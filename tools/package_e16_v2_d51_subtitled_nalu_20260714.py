#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
V24_DIR = BASE / "exports/e16/rough_cut_20260714/speech_window_assembly_v24_luma_d04rm2_d49rm2_d51rm1_bboost"
V24_PLAN = V24_DIR / "build_plan.json"
V25_DIR = BASE / "exports/e16/rough_cut_20260714/speech_window_assembly_v25_d51full_luma_d04rm2_d49rm2_bboost"
V25_SEG_DIR = V25_DIR / "segments"
V25_ROUGH = V25_DIR / "qingshan_E16_speech_window_assembly_v25_20260714.mp4"

FINAL_DIR = BASE / "exports/e16/final_package_v2_20260714"
QA_DIR = BASE / "qa/e16_final_package_v2_20260714"
SUBTITLE_TEXT_DIR = FINAL_DIR / "subtitle_texts_clean_20260714"
LOGO = BASE / "libraries/brand/nalu_motion_cat_logo_v1.png"
TAIL = FINAL_DIR / "qingshan_E16_v2_nalu_tail_20260714.mp4"
TAILED = FINAL_DIR / "qingshan_E16_v2_tailed_nalu_20260714.mp4"
FINAL = FINAL_DIR / "qingshan_E16_v2_final_subtitled_nalu_20260714.mp4"
OLD_FINAL = BASE / "exports/e16/final_package_20260714/qingshan_E16_final_subtitled_nalu_20260714.mp4"

D51_A = BASE / "working_assets/e16_api_20260711/a_coverage_tasks_20260713/D51_RM1/D51_RM1_giggle_output.mp4"
D51_B = BASE / "working_assets/e16_api_20260711/ui_fallback/b_coverage/E16-B24/result_r2_muted.mp4"
D52_B = BASE / "working_assets/e16_api_20260711/ui_fallback/b_coverage/E16-B20/result_r2_reframed_muted.mp4"
D53_B = BASE / "working_assets/e16_api_20260711/ui_fallback/b_coverage/E16-B34/result_r3_muted.mp4"
D51_A_IN = 1.05
D51_DURATION = 2.90
D51_B_DURATION = 0.50
TAIL_DURATION = 3.00

SCALE_FILTER = (
    "scale=720:1280:force_original_aspect_ratio=decrease,"
    "pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,format=yuv420p"
)
FONT = "/System/Library/Fonts/STHeiti Medium.ttc"


def run(cmd: list[str], *, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=BASE, text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise SystemExit(
            "Command failed:\n"
            + " ".join(cmd)
            + "\nSTDOUT:\n"
            + proc.stdout[-2000:]
            + "\nSTDERR:\n"
            + proc.stderr[-4000:]
        )
    if capture:
        return proc
    if proc.stdout:
        print(proc.stdout.strip())
    if proc.stderr:
        print(proc.stderr.strip())
    return proc


def duration(path: Path) -> float:
    proc = run([str(FFMPEG), "-hide_banner", "-i", str(path)], capture=True, check=False)
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if not match:
        raise SystemExit(f"Cannot read duration: {path}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def reset_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def build_d51_segment(out: Path) -> dict[str, Any]:
    before = D51_DURATION - D51_B_DURATION - 0.15
    after = 0.15
    labels = [
        f"[0:v]trim=start={D51_A_IN}:duration={before:.3f},setpts=PTS-STARTPTS,{SCALE_FILTER}[av1]",
        f"[1:v]trim=start=0.15:duration={D51_B_DURATION:.3f},setpts=PTS-STARTPTS,{SCALE_FILTER}[bv]",
        f"[0:v]trim=start={D51_A_IN + before + D51_B_DURATION:.3f}:duration={after:.3f},"
        f"setpts=PTS-STARTPTS,{SCALE_FILTER}[av2]",
        "[av1][bv][av2]concat=n=3:v=1:a=0[v]",
        f"[0:a]atrim=start={D51_A_IN}:duration={D51_DURATION:.3f},asetpts=PTS-STARTPTS,"
        "aresample=48000,aformat=channel_layouts=stereo[a]",
    ]
    run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(D51_A),
            "-i",
            str(D51_B),
            "-filter_complex",
            ";".join(labels),
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(out),
        ]
    )
    return {
        "a_in": D51_A_IN,
        "target_duration": D51_DURATION,
        "visual_plan": {"before": round(before, 3), "b": D51_B_DURATION, "after": after},
        "fix_reason": "D51 old 2.10s window cut off the second phrase; v2 keeps full line: 人先死，刀后补。",
    }


def build_audio_a_visual_b_segment(seg: dict[str, Any], visual_b: Path, out: Path, reason: str) -> dict[str, Any]:
    a_path = Path(seg["a_video_path"])
    a_in = float(seg["a_in"])
    duration = float(seg["target_duration"])
    b_dur = duration
    labels = [
        f"[1:v]trim=start=0.15:duration={b_dur:.3f},setpts=PTS-STARTPTS,{SCALE_FILTER}[v]",
        f"[0:a]atrim=start={a_in:.3f}:duration={duration:.3f},asetpts=PTS-STARTPTS,"
        "aresample=48000,aformat=channel_layouts=stereo[a]",
    ]
    run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(a_path),
            "-i",
            str(visual_b),
            "-filter_complex",
            ";".join(labels),
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(out),
        ]
    )
    return {
        "target_duration": duration,
        "visual_plan": {"b_visual_full_duration": round(b_dur, 3)},
        "fix_reason": reason,
        "audio_source": str(a_path),
        "visual_source": str(visual_b),
    }


def build_v25_rough() -> dict[str, Any]:
    plan = json.loads(V24_PLAN.read_text(encoding="utf-8"))
    edl_path = BASE / "configs/e16_ordered_edit_decision_list_speech_windows_20260713.json"
    edl = json.loads(edl_path.read_text(encoding="utf-8"))
    edl_by_id = {item["dialogue_id"]: item for item in edl["segments"]}
    reset_dir(V25_DIR)
    reset_dir(V25_SEG_DIR)
    d51_out = V25_SEG_DIR / "051_D51_D51_RM1_FULL_ab.mp4"
    d51_fix = build_d51_segment(d51_out)
    d52_out = V25_SEG_DIR / "052_D52_B20_VISUAL_A_AUDIO_ab.mp4"
    d52_fix = build_audio_a_visual_b_segment(
        edl_by_id["D52"],
        D52_B,
        d52_out,
        "CL2X-131: replace D52 visual window with approved B20 reaction source to avoid glass chimney/kerosene lamp risk while preserving A native dialogue audio.",
    )
    d53_out = V25_SEG_DIR / "053_D53_B34_VISUAL_A_AUDIO_ab.mp4"
    d53_fix = build_audio_a_visual_b_segment(
        edl_by_id["D53"],
        D53_B,
        d53_out,
        "CL2X-131: replace D53_R3 visual window containing glass chimney/kerosene lamp with approved B34 reaction source while preserving A native dialogue audio.",
    )

    built: list[dict[str, Any]] = []
    for item in plan["segments"]:
        next_item = dict(item)
        edl_item = edl_by_id.get(str(item.get("dialogue_id")))
        if edl_item:
            next_item["speaker"] = edl_item.get("speaker")
            next_item["text"] = edl_item.get("text")
        if item.get("dialogue_id") == "D51":
            next_item.update(
                {
                    "a_source_id": "D51_RM1_FULL",
                    "segment_path": str(d51_out),
                    "target_duration": D51_DURATION,
                    "visual_plan": d51_fix["visual_plan"],
                    "d51_full_line_fix": d51_fix,
                }
            )
        elif item.get("dialogue_id") == "D52":
            next_item.update(
                {
                    "a_source_id": "D52_AUDIO_B20_VISUAL",
                    "b_source_id": "E16-B20_FULL_VISUAL",
                    "segment_path": str(d52_out),
                    "visual_plan": d52_fix["visual_plan"],
                    "period_lock_visual_fix": d52_fix,
                    "audio_policy": "A_NATIVE_DIALOGUE_AUDIO_ONLY_B20_VISUAL_FULL_DURATION",
                }
            )
        elif item.get("dialogue_id") == "D53":
            next_item.update(
                {
                    "a_source_id": "D53_R3_AUDIO_B34_VISUAL",
                    "b_source_id": "E16-B34_FULL_VISUAL",
                    "segment_path": str(d53_out),
                    "visual_plan": d53_fix["visual_plan"],
                    "period_lock_visual_fix": d53_fix,
                    "audio_policy": "A_NATIVE_DIALOGUE_AUDIO_ONLY_B34_VISUAL_FULL_DURATION",
                }
            )
        built.append(next_item)

    concat_file = V25_DIR / "concat_v25.txt"
    concat_file.write_text("".join(f"file '{item['segment_path']}'\n" for item in built), encoding="utf-8")
    run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(V25_ROUGH),
        ]
    )

    out_plan = {
        **{k: v for k, v in plan.items() if k != "segments"},
        "schema": "qingshan.e16.rough_cut_v25_d51full_build_plan.v1",
        "status": "BUILT_PENDING_FINAL_PACKAGE_QA",
        "source_plan": str(V24_PLAN),
        "output": str(V25_ROUGH),
        "d51_fix": d51_fix,
        "d52_visual_fix": d52_fix,
        "d53_visual_fix": d53_fix,
        "segments": built,
        "target_runtime_seconds": round(sum(float(x["target_duration"]) for x in built), 3),
    }
    (V25_DIR / "build_plan.json").write_text(json.dumps(out_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_plan


def make_tail() -> None:
    filter_complex = (
        f"[0:v]drawtext=fontfile='{FONT}':text='青山':fontcolor=white:fontsize=58:"
        "x=(w-text_w)/2:y=420,"
        f"drawtext=fontfile='{FONT}':text='第17集继续':fontcolor=white:fontsize=38:"
        "x=(w-text_w)/2:y=512,"
        f"drawtext=fontfile='{FONT}':text='NALU MOTION':fontcolor=white@0.86:fontsize=24:"
        "x=(w-text_w)/2:y=905[card];"
        "[2:v]scale=250:-1[logo];[card][logo]overlay=(W-w)/2:610:format=auto[v]"
    )
    run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s=720x1280:r=30:d={TAIL_DURATION}",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-loop",
            "1",
            "-t",
            str(TAIL_DURATION),
            "-i",
            str(LOGO),
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "1:a",
            "-t",
            str(TAIL_DURATION),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            str(TAIL),
        ]
    )


def concat_rough_and_tail() -> None:
    concat_file = FINAL_DIR / "concat_rough_tail.txt"
    concat_file.write_text(f"file '{V25_ROUGH}'\nfile '{TAIL}'\n", encoding="utf-8")
    run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(TAILED),
        ]
    )


def burn_subtitles(v25_plan: dict[str, Any]) -> list[dict[str, Any]]:
    reset_dir(SUBTITLE_TEXT_DIR)
    for old in SUBTITLE_TEXT_DIR.glob("*.txt"):
        old.unlink()

    subtitle_events: list[dict[str, Any]] = []
    filters: list[str] = []
    cursor = 0.0
    for idx, seg in enumerate(v25_plan["segments"], start=1):
        dur = float(seg["target_duration"])
        text = str(seg.get("text") or "").strip()
        if text:
            text_file = SUBTITLE_TEXT_DIR / f"{idx:03d}_{seg['dialogue_id']}.txt"
            text_file.write_text(text, encoding="utf-8")
            start = cursor + 0.08
            end = cursor + dur - 0.08
            filters.append(
                f"drawtext=fontfile='{FONT}':textfile='{text_file}':fontcolor=white:fontsize=34:"
                "bordercolor=black@0.95:borderw=3:shadowcolor=black@0.70:shadowx=1:shadowy=1:"
                f"x=(w-text_w)/2:y=1104:enable='between(t,{start:.3f},{end:.3f})'"
            )
            subtitle_events.append(
                {
                    "index": idx,
                    "dialogue_id": seg["dialogue_id"],
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": text,
                }
            )
        cursor += dur

    run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(TAILED),
            "-vf",
            ",".join(filters) if filters else "null",
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-r",
            "30",
            "-fps_mode",
            "cfr",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(FINAL),
        ]
    )
    return subtitle_events


def extract_frame(video: Path, timestamp: float, out: Path) -> None:
    reset_dir(out.parent)
    run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(out),
        ]
    )


def make_contact_sheet(video: Path, sample_times: list[float], out: Path) -> None:
    frame_dir = out.parent / f"{out.stem}_frames"
    if frame_dir.exists():
        shutil.rmtree(frame_dir)
    frame_dir.mkdir(parents=True)
    for idx, t in enumerate(sample_times, start=1):
        extract_frame(video, t, frame_dir / f"frame_{idx:03d}.jpg")
    run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            "1",
            "-pattern_type",
            "glob",
            "-i",
            str(frame_dir / "frame_*.jpg"),
            "-vf",
            "scale=180:-1,tile=4x2:padding=6:margin=6:color=white",
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(out),
        ]
    )


def write_report(v25_plan: dict[str, Any], subtitle_events: list[dict[str, Any]]) -> dict[str, Any]:
    d51_event = next(e for e in subtitle_events if e["dialogue_id"] == "D51")
    final_duration = duration(FINAL)
    tail_sample_t = final_duration - 1.5
    sample_times = [2.0, 30.0, 60.0, 90.0, 120.0, d51_event["start"] + 1.0, 160.0, tail_sample_t]
    make_contact_sheet(FINAL, sample_times, QA_DIR / "qingshan_E16_v2_final_contact_20260714.jpg")
    proof_dir = QA_DIR / "subtitle_tail_proof_frames"
    for label, t in {
        "subtitle_005": 5.0,
        "subtitle_060": 60.0,
        "subtitle_d51": d51_event["start"] + 1.0,
        "subtitle_160": 160.0,
        "tail_nalu": tail_sample_t,
    }.items():
        extract_frame(FINAL, t, proof_dir / f"{label}.jpg")

    report = {
        "schema": "qingshan.e16.final_package_v2_report.v1",
        "episode": "E16",
        "status": "PACKAGED_PENDING_FINAL_QA",
        "supersedes": str(OLD_FINAL),
        "old_final_sha256": sha256(OLD_FINAL) if OLD_FINAL.exists() else None,
        "v25_rough": str(V25_ROUGH),
        "tailed_nalu": str(TAILED),
        "final_subtitled_nalu": str(FINAL),
        "final_sha256": sha256(FINAL),
        "duration_seconds": round(final_duration, 3),
        "d51_fix": v25_plan["d51_fix"],
        "d51_subtitle_event": d51_event,
        "subtitle_event_count": len(subtitle_events),
        "tail_duration_seconds": TAIL_DURATION,
        "tail_sample_timestamp": round(tail_sample_t, 3),
        "contact_sheet": str(QA_DIR / "qingshan_E16_v2_final_contact_20260714.jpg"),
        "proof_frames": str(proof_dir),
        "package_name_content_assertions": {
            "filename_contains_subtitled": True,
            "subtitle_text_files_created": len(list(SUBTITLE_TEXT_DIR.glob("*.txt"))),
            "filename_contains_nalu": True,
            "tail_file_created": TAIL.exists(),
        },
    }
    (QA_DIR / "E16_V2_PACKAGE_REPORT_20260714.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> int:
    for required in [FFMPEG, V24_PLAN, D51_A, D51_B, D52_B, D53_B, LOGO]:
        if not required.exists():
            raise SystemExit(f"Missing required file: {required}")
    reset_dir(V25_DIR)
    reset_dir(V25_SEG_DIR)
    reset_dir(FINAL_DIR)
    reset_dir(QA_DIR)

    v25_plan = build_v25_rough()
    make_tail()
    concat_rough_and_tail()
    subtitle_events = burn_subtitles(v25_plan)
    report = write_report(v25_plan, subtitle_events)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
