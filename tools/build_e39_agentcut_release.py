#!/usr/bin/env python3
"""Render the SHA-bound E39 release cut from admitted video sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
try:
    from tools.episode_stage_gate_runner import require_release_builder_gate_admission
except ModuleNotFoundError:
    from episode_stage_gate_runner import require_release_builder_gate_admission


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "workflow/agentcut/e39_r3_postproduction/E39_R3_EXACT_DIALOGUE_SUBTITLE_TEXT_PLATE_PLAN_V2.json"
OUT_DIR = ROOT / "exports/e39/agentcut_release_20260806"
WORK = OUT_DIR / "work"
OUTPUT = OUT_DIR / "E39_青山_借刀查案_FINAL.mp4"
PROJECT = OUT_DIR / "E39_AGENTCUT_RELEASE_PROJECT.json"
EDIT_GATE_EVIDENCE = ROOT / "workflow/agentcut/e39_r3_postproduction/E39_RELEASE_EDIT_GATE_EVIDENCE_BUNDLE.json"
EDIT_GATE_OUT = ROOT / "qa/e39_agentcut_release_20260806/unified_edit_gates"

SOURCES = [
    ("U01", "working_assets/e39_video_v1/independent_video_r4_u01/E39-U01-R4-SILENT-OFFSCREEN.mp4", "exact"),
    ("U02", "working_assets/e39_video_v1/independent_r2_audio_driven/E39-U02-R2.mp4", "native"),
    ("U03", "working_assets/e39_video_v1/independent_r2_audio_driven/E39-U03-R2.mp4", "native"),
    ("U04", "working_assets/e39_video_v1/independent_video_r4_u04/E39-U04-R4-INTERIOR-EVIDENCE.mp4", "exact"),
    ("U05", "working_assets/e39_video_v1/independent_r3_hybrid/E39-U05-R3-NATIVE-HYBRID.mp4", "exact_trim"),
    ("A01", "working_assets/e39_video_v1/E39-FS1-A01-R5_968135ab-5e35-4dfd-b565-f5a2bd86e5d6.mp4", "native"),
    ("A02", "working_assets/e39_video_v1/E39-FS1-A02-R3_83483a3a-d08d-4a01-998e-704784340519.mp4", "native"),
    ("A03", "working_assets/e39_video_v1/E39-FS1-A03-R1_b8a9a58b-daa6-476d-b8db-2c7ecca23dc4.mp4", "native"),
    ("A04", "working_assets/e39_video_v1/E39-FS1-A04-R1_6248cc19-89dc-4c3f-a77e-98b8e5700c1f.mp4", "native"),
    ("A05", "working_assets/e39_video_v1/E39-FS1-A05-R2_d56ab3b1-40f3-45ff-ad72-70a589b0c628.mp4", "native"),
    ("U10", "working_assets/e39_video_v1/independent_r3_hybrid/E39-U10-R3-SILENT-CUTAWAY.mp4", "exact"),
    ("U11", "working_assets/e39_video_v1/independent_r3_hybrid/E39-U11-R3-SILENT-CUTAWAY.mp4", "exact"),
    ("U12", "working_assets/e39_video_v1/independent_wave2/E39-U12-R1.mp4", "exact"),
    ("U13", "working_assets/e39_video_v1/independent_r3_hybrid/E39-U13-R3-NATIVE-HYBRID.mp4", "native"),
    ("U14", "working_assets/e39_video_v1/independent_r3_hybrid/E39-U14-R3-NATIVE-HYBRID.mp4", "exact"),
    ("U15", "working_assets/e39_video_v1/independent_r3_hybrid/E39-U15-R3-SILENT-CUTAWAY.mp4", "exact"),
]

PLATE_WINDOWS = {
    "U04": (3.8, 5.8),
    "U10": (2.5, 4.5),
    "U11": (4.2, 7.2),
}


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def duration(path: Path) -> float:
    return float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ], text=True).strip())


def has_audio(path: Path) -> bool:
    result = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
        "stream=index", "-of", "csv=p=0", str(path),
    ], text=True).strip()
    return bool(result)


def video_filter(unit: str, plate: str | None, trim: bool) -> tuple[str, float]:
    if trim:
        # Remove the accepted U05's long empty-street hold while keeping both action beats.
        base = "[0:v]split=2[v0][v1];[v0]trim=0:3.2,setpts=PTS-STARTPTS[a];[v1]trim=5.8:10.9,setpts=PTS-STARTPTS[b];[a][b]concat=n=2:v=1:a=0"
        expected = 8.3
    else:
        base = "[0:v]setpts=PTS-STARTPTS"
        expected = 0.0
    chain = base + ",scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,setsar=1[vbase]"
    if plate:
        start, end = PLATE_WINDOWS[unit]
        chain += f";[1:v]scale=1080:1920,setsar=1[plate];[vbase][plate]overlay=0:0:enable='between(t,{start},{end})'[vout]"
    else:
        chain += ";[vbase]null[vout]"
    return chain, expected


def subtitle_png(unit: str, index: int, text: str) -> Path:
    path = WORK / f"{unit}-SUB-{index:02d}.png"
    canvas = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 54)
    box = draw.textbbox((0, 0), text, font=font, stroke_width=3)
    draw.text(((1080 - (box[2] - box[0])) / 2, 1645), text, font=font, fill="white", stroke_width=3, stroke_fill="black")
    canvas.save(path)
    return path


def render_unit(unit: str, source: Path, mode: str, plan_by_unit: dict[str, dict]) -> dict:
    out = WORK / f"{unit}.mp4"
    row = plan_by_unit.get(unit)
    plate = row.get("text_plate") if row else None
    trim = mode == "exact_trim"
    vf, trim_duration = video_filter(unit, plate, trim)
    inputs = ["-i", str(source)]
    if plate:
        inputs += ["-loop", "1", "-i", str(ROOT / plate)]

    if mode == "native":
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", vf]
        if has_audio(source):
            cmd += ["-map", "[vout]", "-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"]
        else:
            d = duration(source)
            cmd += ["-f", "lavfi", "-t", str(d), "-i", "anullsrc=r=48000:cl=stereo", "-map", "[vout]", "-map", f"{2 if plate else 1}:a:0", "-c:a", "aac", "-b:a", "192k"]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-shortest", str(out)]
        run(cmd)
    else:
        if not row:
            raise ValueError(f"missing exact dialogue plan for {unit}")
        events = [dict(event) for event in row["dialogue_events"]]
        if unit == "U05":
            # The removed 2.6 seconds precede the line; move both exact audio and subtitle together.
            original_start = float(events[0]["start_seconds"])
            original_end = float(events[0]["end_seconds"])
            events[0]["start_seconds"] = 4.7
            events[0]["end_seconds"] = round(4.7 + original_end - original_start, 3)
        for event in events:
            inputs += ["-i", str(ROOT / event["wav_path"])]
        subtitle_paths = [subtitle_png(unit, i, event["text"]) for i, event in enumerate(events, 1)]
        for path in subtitle_paths:
            inputs += ["-loop", "1", "-i", str(path)]
        visual_duration = trim_duration or duration(source)
        audio_base_index = 2 if plate else 1
        audio_filters = [f"anullsrc=r=48000:cl=stereo:d={visual_duration}[sil]"]
        mix_inputs = ["[sil]"]
        for i, event in enumerate(events):
            delay = int(round(float(event["start_seconds"]) * 1000))
            input_index = audio_base_index + i
            audio_filters.append(f"[{input_index}:a]aresample=48000,adelay={delay}|{delay}[d{i}]")
            mix_inputs.append(f"[d{i}]")
        audio_filters.append("".join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:normalize=0:dropout_transition=0,alimiter=limit=0.95[aout]")
        subtitle_base_index = audio_base_index + len(events)
        visual_filters = []
        prior = "vout"
        for i, event in enumerate(events):
            current = f"vsub{i}"
            start = float(event["start_seconds"])
            end = float(event["end_seconds"])
            visual_filters.append(f"[{subtitle_base_index + i}:v]format=rgba[s{i}]")
            visual_filters.append(f"[{prior}][s{i}]overlay=0:0:enable='between(t,{start},{end})'[{current}]")
            prior = current
        filters = vf + ";" + ";".join(visual_filters) + f";[{prior}]null[vsub];" + ";".join(audio_filters)
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
            "-filter_complex", filters, "-map", "[vsub]", "-map", "[aout]",
            "-t", str(visual_duration), "-c:v", "libx264", "-preset", "medium",
            "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out),
        ]
        run(cmd)
    return {"unit_id": unit, "source": str(source.relative_to(ROOT)), "source_sha256": sha(source), "mode": mode, "rendered": str(out.relative_to(ROOT)), "rendered_sha256": sha(out), "duration_seconds": round(duration(out), 6)}


def build_outro() -> Path:
    logo = ROOT / "libraries/brand/nalu_motion_cat_logo_v1.png"
    chime = ROOT / "libraries/brand/nalu_motion_outro_chime_v1.wav"
    still = WORK / "NALU_OUTRO.png"
    canvas = Image.new("RGB", (1080, 1920), "#080808")
    mark = Image.open(logo).convert("RGBA")
    mark.thumbnail((420, 420), Image.Resampling.LANCZOS)
    canvas.paste(mark, ((1080 - mark.width) // 2, 600), mark)
    draw = ImageDraw.Draw(canvas)
    latin = ImageFont.truetype("/System/Library/Fonts/SFCompact.ttf", 52)
    han = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 42)
    for text, font, y in (("NALU MOTION", latin, 1130), ("青山", han, 1220)):
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((1080 - (box[2] - box[0])) / 2, y), text, font=font, fill="white")
    canvas.save(still)
    out = WORK / "NALU_OUTRO.mp4"
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-loop", "1", "-t", "3", "-i", str(still), "-i", str(chime),
        "-filter_complex", "[1:a]apad=pad_dur=3[a]",
        "-map", "0:v", "-map", "[a]", "-t", "3", "-r", "30", "-c:v", "libx264",
        "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out),
    ])
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edit-gate-evidence-bundle", type=Path, default=EDIT_GATE_EVIDENCE)
    parser.add_argument("--edit-gate-out-dir", type=Path, default=EDIT_GATE_OUT)
    args = parser.parse_args()
    require_release_builder_gate_admission(
        episode="E39",
        evidence_bundle=args.edit_gate_evidence_bundle,
        out_dir=args.edit_gate_out_dir,
    )
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    plan_by_unit = {row["unit_id"]: row for row in plan["units"]}
    missing = [str(ROOT / rel) for _, rel, _ in SOURCES if not (ROOT / rel).exists()]
    if missing:
        raise FileNotFoundError("missing admitted sources:\n" + "\n".join(missing))
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)
    rendered = [render_unit(unit, ROOT / rel, mode, plan_by_unit) for unit, rel, mode in SOURCES]
    outro = build_outro()
    concat = WORK / "concat.txt"
    paths = [ROOT / row["rendered"] for row in rendered] + [outro]
    concat.write_text("".join(f"file '{path}'\n" for path in paths), encoding="utf-8")
    visual = WORK / "E39_VISUAL_WITH_DIALOGUE.mp4"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(visual)])

    bgm = ROOT / "working_assets/e38_bgm_20260804/73973075-3a84-4d57-b79e-e7a813224f8a/bgm_candidate_1.mp3"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    total = duration(visual)
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(visual),
        "-stream_loop", "-1", "-i", str(bgm),
        "-filter_complex", f"[1:a]volume=0.075,atrim=0:{total},afade=t=out:st={max(0.0,total-2.5)}:d=2.5[bgm];[0:a][bgm]amix=inputs=2:weights='1 1':normalize=0,alimiter=limit=0.95[a]",
        "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(OUTPUT),
    ])
    project = {
        "schema": "qingshan.e39_agentcut_release_project.v1",
        "episode": "E39",
        "status": "RENDERED",
        "canonical_script_sha256": plan["source_script_sha256"],
        "canonical_manifest_sha256": plan["canonical_manifest_sha256"],
        "source_binding": "EXACT_SHA_ADMITTED_ONLY",
        "units": rendered,
        "action_chain_seal": "qa/e39_video_v1/E39_FS1_ACTION_CHAIN_FINAL_SEAL_V1.json",
        "subtitle_policy": "WHITE_HEITI_BLACK_OUTLINE_NO_BOX; U03/U13 retain one source subtitle layer only",
        "bgm": str(bgm.relative_to(ROOT)),
        "nalu_outro": str(outro.relative_to(ROOT)),
        "output": str(OUTPUT.relative_to(ROOT)),
        "output_sha256": sha(OUTPUT),
        "runtime_seconds": round(duration(OUTPUT), 6),
    }
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "output": str(OUTPUT), "sha256": sha(OUTPUT), "runtime_seconds": project["runtime_seconds"], "project": str(PROJECT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
