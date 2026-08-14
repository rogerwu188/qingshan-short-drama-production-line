#!/usr/bin/env python3
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
PROJECT = ROOT / "configs/e37_agentcut_v4_canonical_replacements_subtitled_outro_20260803.json"
OUT_DIR = ROOT / "exports/e37/agentcut_v4_canonical_replacements_subtitled_outro_20260803"
MAIN = OUT_DIR / "E37_V4_CANONICAL_REPLACEMENT_MAIN.mp4"
SUBBED = OUT_DIR / "E37_V4_CANONICAL_REPLACEMENT_SUBTITLED.mp4"
OUTRO = OUT_DIR / "E37_NALU_MOTION_OUTRO_V4.mp4"
FINAL = OUT_DIR / "E37_AGENTCUT_V4_CANONICAL_REPLACEMENTS_SUBTITLED_NALU_OUTRO_NOT_FINAL.mp4"
ASS = OUT_DIR / "E37_CANONICAL_31_OF_31.ass"

V1 = ROOT / "exports/e37/agentcut_v1_accepted_only_20260803/E37_AGENTCUT_V1_ACCEPTED_ONLY_PRODUCTION_CANDIDATE.mp4"
BOUND = ROOT / "working_assets/e37_agentcut_replacement_v4_20260803/bound_canonical_segments"
U02 = BOUND / "E37_U02_S1_CANONICAL_REPLACEMENT_V4.mp4"
U03 = BOUND / "E37_U03_S1_CANONICAL_REPLACEMENT_V4.mp4"
U03S4 = BOUND / "E37_U03_S4_CANONICAL_REPLACEMENT_V4.mp4"
ACTION = ROOT / "working_assets/e37_action_replacement_v5_20260803/accepted_action_sequence_v2/E37_ACCEPTED_ACTION_SEQUENCE_V5_TRIMMED_V2.mp4"
LOGO = ROOT / "libraries/brand/nalu_motion_cat_logo_v1.png"
CHIME = ROOT / "libraries/brand/nalu_motion_outro_chime_v1.wav"
FONT = Path("/System/Library/Fonts/STHeiti Medium.ttc")


def run(args):
    subprocess.run([str(x) for x in args], cwd=ROOT, check=True)


def ass_time(seconds: float) -> str:
    centis = int(round(seconds * 100))
    h, rem = divmod(centis, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def build_ass(project: dict) -> None:
    clips = project["timeline"]["subtitleTracks"][0]["clips"]
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 720",
        "PlayResY: 1280",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,STHeiti,34,&H00FFFFFF,&H000000FF,&H00101010,&H70000000,0,0,0,0,100,100,0,0,1,2.4,0.8,2,72,72,118,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for clip in clips:
        start = float(clip["start"])
        end = start + float(clip["duration"])
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{ass_escape(clip['text'])}")
    ASS.write_text("\n".join(lines) + "\n")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    project = json.loads(PROJECT.read_text())
    build_ass(project)
    required = (V1, U02, U03, U03S4, ACTION, LOGO, CHIME, FONT)
    for path in required:
        if not path.is_file():
            raise SystemExit(f"missing render input: {path}")

    run([
        FFMPEG, "-y", "-v", "error",
        "-i", V1, "-i", U02, "-i", U03, "-i", U03S4, "-i", ACTION,
        "-filter_complex",
        "[0:v]trim=0:10.04,setpts=PTS-STARTPTS[v0];[0:a]atrim=0:10.04,asetpts=PTS-STARTPTS[a0];"
        "[1:v]trim=0:8.04,setpts=PTS-STARTPTS[v1];[1:a]atrim=0:8.04,asetpts=PTS-STARTPTS[a1];"
        "[0:v]trim=18.08:28.12,setpts=PTS-STARTPTS[v2];[0:a]atrim=18.08:28.12,asetpts=PTS-STARTPTS[a2];"
        "[2:v]trim=0:8.04,setpts=PTS-STARTPTS[v3];[2:a]atrim=0:8.04,asetpts=PTS-STARTPTS[a3];"
        "[0:v]trim=36.16:55.24,setpts=PTS-STARTPTS[v4];[0:a]atrim=36.16:55.24,asetpts=PTS-STARTPTS[a4];"
        "[3:v]trim=0:7.04,setpts=PTS-STARTPTS[v5];[3:a]atrim=0:7.04,asetpts=PTS-STARTPTS[a5];"
        "[4:v]trim=0:31.16,setpts=PTS-STARTPTS[v6];[4:a]atrim=0:31.16,asetpts=PTS-STARTPTS[a6];"
        "[0:v]trim=93.44:176.085,setpts=PTS-STARTPTS[v7];[0:a]atrim=93.44:176.085,asetpts=PTS-STARTPTS[a7];"
        "[v0][a0][v1][a1][v2][a2][v3][a3][v4][a4][v5][a5][v6][a6][v7][a7]concat=n=8:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]", "-r", "24", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", MAIN,
    ])
    run([
        FFMPEG, "-y", "-v", "error", "-i", MAIN,
        "-vf", f"subtitles={ASS}:fontsdir={FONT.parent}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "copy", "-movflags", "+faststart", SUBBED,
    ])
    run([
        FFMPEG, "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=0x080808:s=720x1280:r=24:d=3",
        "-loop", "1", "-i", LOGO, "-i", CHIME,
        "-filter_complex",
        f"[1:v]scale=250:141,format=rgba[logo];[0:v][logo]overlay=235:570,"
        f"drawtext=fontfile='{FONT}':text='青山':fontcolor=white:fontsize=52:x=(w-text_w)/2:y=350,"
        f"drawtext=fontfile='{FONT}':text='敬请期待':fontcolor=white:fontsize=34:x=(w-text_w)/2:y=760,"
        f"drawtext=fontfile='{FONT}':text='NALU MOTION':fontcolor=white:fontsize=28:x=(w-text_w)/2:y=840[v]",
        "-map", "[v]", "-map", "2:a", "-t", "3", "-r", "24", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-shortest", OUTRO,
    ])
    run([
        FFMPEG, "-y", "-v", "error", "-i", SUBBED, "-i", OUTRO,
        "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]", "-r", "24", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", FINAL,
    ])
    print(json.dumps({"status": "PASS_RENDERED_NOT_FINAL", "media": str(FINAL), "subtitle_count": 31, "outro_seconds": 3.0}))


if __name__ == "__main__":
    main()
