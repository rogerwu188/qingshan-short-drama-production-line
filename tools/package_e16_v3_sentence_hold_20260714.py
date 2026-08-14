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
EDL = BASE / "configs/e16_ordered_edit_decision_list_speech_windows_rm_v21_d04rm2_d49rm2_d51rm1_bboost_candidate_20260714.json"
ROUGH_DIR = BASE / "exports/e16/rough_cut_20260714/speech_window_assembly_v26_sentence_hold_d51full_periodfix"
SEG_DIR = ROUGH_DIR / "segments"
ROUGH = ROUGH_DIR / "qingshan_E16_speech_window_assembly_v26_sentence_hold_20260714.mp4"

FINAL_DIR = BASE / "exports/e16/final_package_v3_sentence_hold_20260714"
QA_DIR = BASE / "qa/e16_final_package_v3_sentence_hold_20260714"
SUBTITLE_TEXT_DIR = FINAL_DIR / "subtitle_texts_clean_20260714"
LOGO = BASE / "libraries/brand/nalu_motion_cat_logo_v1.png"
TAIL = FINAL_DIR / "qingshan_E16_v3_nalu_tail_20260714.mp4"
TAILED = FINAL_DIR / "qingshan_E16_v3_tailed_nalu_20260714.mp4"
FINAL = FINAL_DIR / "qingshan_E16_v3_sentence_hold_final_subtitled_nalu_20260714.mp4"

D51_A = BASE / "working_assets/e16_api_20260711/a_coverage_tasks_20260713/D51_RM1/D51_RM1_giggle_output.mp4"
D52_B = BASE / "working_assets/e16_api_20260711/ui_fallback/b_coverage/E16-B20/result_r2_reframed_muted.mp4"
D53_B = BASE / "working_assets/e16_api_20260711/ui_fallback/b_coverage/E16-B34/result_r3_muted.mp4"
D51_A_IN = 1.05
D51_DURATION = 2.90
TAIL_DURATION = 3.00
FONT = "/System/Library/Fonts/STHeiti Medium.ttc"

SCALE_FILTER = (
    "scale=720:1280:force_original_aspect_ratio=decrease,"
    "pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,format=yuv420p"
)

SHOT_BRIGHTNESS_BIAS = {
    "D09": -0.10,
    "D11": 0.10,
    "D20": 0.10,
    "D50": -0.02,
    "D51": 0.06,
    "D52": -0.04,
    "D57": -0.08,
    "D61": 0.12,
}


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
    return proc


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def duration(path: Path) -> float:
    proc = run([str(FFMPEG), "-hide_banner", "-i", str(path)], capture=True, check=False)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if not m:
        raise SystemExit(f"Cannot read duration: {path}")
    h, mnt, sec = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(sec)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def shot_filter(dialogue_id: str) -> str:
    bias = SHOT_BRIGHTNESS_BIAS.get(dialogue_id)
    if bias is None:
        return SCALE_FILTER
    return f"eq=brightness={bias:.3f},{SCALE_FILTER}"


def build_a_sentence_segment(seg: dict[str, Any], out: Path, *, a_path: Path | None = None, a_in: float | None = None, target_duration: float | None = None) -> dict[str, Any]:
    dialogue_id = seg["dialogue_id"]
    source = a_path or Path(seg["a_video_path"])
    start = float(seg["a_in"] if a_in is None else a_in)
    dur = float(seg["target_duration"] if target_duration is None else target_duration)
    filters = (
        f"[0:v]trim=start={start:.3f}:duration={dur:.3f},setpts=PTS-STARTPTS,{shot_filter(dialogue_id)}[v];"
        f"[0:a]atrim=start={start:.3f}:duration={dur:.3f},asetpts=PTS-STARTPTS,"
        "aresample=48000,aformat=channel_layouts=stereo[a]"
    )
    run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-filter_complex",
            filters,
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
        "segment_path": str(out),
        "target_duration": dur,
        "visual_plan": {"sentence_hold_a_source": round(dur, 3), "b": 0.0},
        "audio_policy": "A_NATIVE_DIALOGUE_AUDIO_SENTENCE_HOLD",
    }


def build_audio_a_visual_b_segment(seg: dict[str, Any], visual_b: Path, out: Path, reason: str) -> dict[str, Any]:
    a_path = Path(seg["a_video_path"])
    a_in = float(seg["a_in"])
    dur = float(seg["target_duration"])
    filters = (
        f"[1:v]trim=start=0.15:duration={dur:.3f},setpts=PTS-STARTPTS,{SCALE_FILTER}[v];"
        f"[0:a]atrim=start={a_in:.3f}:duration={dur:.3f},asetpts=PTS-STARTPTS,"
        "aresample=48000,aformat=channel_layouts=stereo[a]"
    )
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
            filters,
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
        "segment_path": str(out),
        "target_duration": dur,
        "visual_plan": {"full_line_b_visual_replacement": round(dur, 3), "b": dur},
        "audio_policy": "A_NATIVE_DIALOGUE_AUDIO_B_VISUAL_FULL_LINE",
        "period_lock_visual_fix": {
            "reason": reason,
            "audio_source": str(a_path),
            "visual_source": str(visual_b),
        },
    }


def build_rough() -> dict[str, Any]:
    reset_dir(ROUGH_DIR)
    reset_dir(SEG_DIR)
    edl = json.loads(EDL.read_text(encoding="utf-8"))
    built: list[dict[str, Any]] = []
    for idx, seg in enumerate(edl["segments"], start=1):
        dialogue_id = seg["dialogue_id"]
        out = SEG_DIR / f"{idx:03d}_{dialogue_id}_{seg['a_source_id']}_sentence_hold.mp4"
        if dialogue_id == "D51":
            info = build_a_sentence_segment(seg, out, a_path=D51_A, a_in=D51_A_IN, target_duration=D51_DURATION)
            info["d51_full_line_fix"] = {
                "a_in": D51_A_IN,
                "target_duration": D51_DURATION,
                "reason": "Keep full sentence in one shot: 人先死，刀后补。",
            }
        elif dialogue_id == "D52":
            info = build_audio_a_visual_b_segment(
                seg,
                D52_B,
                out,
                "Full-line visual replacement removes glass chimney/kerosene lamp risk without cutting inside the line.",
            )
        elif dialogue_id == "D53":
            info = build_audio_a_visual_b_segment(
                seg,
                D53_B,
                out,
                "Full-line visual replacement removes glass chimney/kerosene lamp risk without cutting inside the line.",
            )
        else:
            info = build_a_sentence_segment(seg, out)
        built.append(
            {
                "kind": "dialogue",
                "index": idx,
                "dialogue_id": dialogue_id,
                "a_source_id": seg["a_source_id"],
                "speaker": seg.get("speaker"),
                "text": seg.get("text"),
                **info,
            }
        )

    concat_file = ROUGH_DIR / "concat_v26.txt"
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
            str(ROUGH),
        ]
    )
    plan = {
        "schema": "qingshan.e16.rough_cut_v26_sentence_hold.v1",
        "episode": "E16",
        "status": "BUILT_PENDING_FINAL_QA",
        "edl": str(EDL),
        "output": str(ROUGH),
        "segment_count": len(built),
        "dialogue_segment_count": len(built),
        "visual_bridge_count": 0,
        "coverage_policy": {
            "mode": "sentence_hold_default",
            "rule": "No B insert inside a spoken line. Listener/reaction coverage is allowed only as a full-line replacement for a known visual fix or later as a separate paragraph beat.",
            "reason": "Roger rejected v2 because A/B inserts made dialogue tiring: a sentence could switch shots before the sentence ended.",
        },
        "segments": built,
        "target_runtime_seconds": round(sum(float(x["target_duration"]) for x in built), 3),
    }
    (ROUGH_DIR / "build_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def make_tail() -> None:
    filters = (
        f"[0:v]drawtext=fontfile='{FONT}':text='青山':fontcolor=white:fontsize=58:x=(w-text_w)/2:y=420,"
        f"drawtext=fontfile='{FONT}':text='第17集继续':fontcolor=white:fontsize=38:x=(w-text_w)/2:y=512,"
        f"drawtext=fontfile='{FONT}':text='NALU MOTION':fontcolor=white@0.86:fontsize=24:x=(w-text_w)/2:y=905[card];"
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
            filters,
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


def concat_tail() -> None:
    concat_file = FINAL_DIR / "concat_rough_tail_v3.txt"
    concat_file.write_text(f"file '{ROUGH}'\nfile '{TAIL}'\n", encoding="utf-8")
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


def burn_subtitles(plan: dict[str, Any]) -> list[dict[str, Any]]:
    reset_dir(SUBTITLE_TEXT_DIR)
    filters: list[str] = []
    events: list[dict[str, Any]] = []
    cursor = 0.0
    for idx, seg in enumerate(plan["segments"], start=1):
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
            events.append({"index": idx, "dialogue_id": seg["dialogue_id"], "start": round(start, 3), "end": round(end, 3), "text": text})
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
    return events


def extract_frame(video: Path, timestamp: float, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{timestamp:.3f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out)])


def make_contact_sheet(video: Path, out: Path) -> None:
    frame_dir = out.parent / f"{out.stem}_frames"
    reset_dir(frame_dir)
    dur = duration(video)
    times = [5, 25, 45, 65, 85, 105, 125, 145, min(165, dur - 6)]
    for idx, t in enumerate(times, start=1):
        extract_frame(video, t, frame_dir / f"frame_{idx:03d}.jpg")
    run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-pattern_type",
            "glob",
            "-i",
            str(frame_dir / "*.jpg"),
            "-vf",
            "scale=240:426,tile=3x3:margin=8:padding=4:color=black",
            "-frames:v",
            "1",
            str(out),
        ]
    )


def write_reports(plan: dict[str, Any], events: list[dict[str, Any]]) -> None:
    QA_DIR.mkdir(parents=True, exist_ok=True)
    final_dur = duration(FINAL)
    proof_dir = QA_DIR / "subtitle_tail_proof_frames"
    reset_dir(proof_dir)
    for t, name in [(5, "subtitle_005.jpg"), (60, "subtitle_060.jpg"), (145.4, "subtitle_d51.jpg"), (150.2, "d52_period_lock.jpg"), (154.1, "d53_period_lock.jpg"), (final_dur - 1.5, "tail_nalu.jpg")]:
        extract_frame(FINAL, t, proof_dir / name)
    contact = QA_DIR / "qingshan_E16_v3_sentence_hold_contact_20260714.jpg"
    make_contact_sheet(FINAL, contact)
    report = {
        "schema": "qingshan.e16.final_package_v3_sentence_hold.report.v1",
        "episode": "E16",
        "status": "PACKAGED_PENDING_QA",
        "final_mp4": str(FINAL),
        "final_sha256": sha256(FINAL),
        "runtime_seconds": round(final_dur, 3),
        "rough_mp4": str(ROUGH),
        "rough_build_plan": str(ROUGH_DIR / "build_plan.json"),
        "subtitle_event_count": len(events),
        "contact_sheet": str(contact),
        "proof_frames": str(proof_dir),
        "supersedes": {
            "v2": "/Users/rogerwu/qingshan_short_drama/exports/e16/final_package_v2_20260714/qingshan_E16_v2_final_subtitled_nalu_20260714.mp4",
            "reason": "Roger rejected v2 as still too fast; too many shot changes inside a spoken sentence.",
        },
        "sentence_hold_policy": {
            "dialogue_segments": len(plan["segments"]),
            "inside_line_b_inserts": 0,
            "full_line_visual_replacements": ["D52", "D53"],
            "d51_full_line_single_shot": True,
        },
    }
    (QA_DIR / "E16_V3_SENTENCE_HOLD_PACKAGE_REPORT_20260714.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    reset_dir(FINAL_DIR)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    plan = build_rough()
    make_tail()
    concat_tail()
    events = burn_subtitles(plan)
    write_reports(plan, events)
    print(json.dumps({"status": "PACKAGED_PENDING_QA", "final": str(FINAL), "sha256": sha256(FINAL), "runtime": round(duration(FINAL), 3)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
