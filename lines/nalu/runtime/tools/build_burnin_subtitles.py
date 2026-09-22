#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_burnin_subtitles.py — burn the SCRIPT's dialogue lines into the rendered picture.

The engine's portable renderer rejects subtitleTracks (they belong to the full AgentCut
engine), so captions are burned after the picture render with ffmpeg's ASS filter.
Text = the generation contract's dialogue lines verbatim (never the ASR transcript);
timing = the unit clip's timeline start + the faster-whisper speech window of that line
inside the unit (segments matched to lines in order by CJK similarity; when fewer
segments than lines, the speech span is split by character count).  Style follows the
engine's add_agentcut_subtitle_track DEFAULT_STYLE (42 px, white, 3 px black outline,
bottom-centre, 170 px bottom margin, wrap at 15 chars, STHeiti Medium).

  build --episode EP --project <agentcut project> --asr <per-unit asr json> --contract <generation contract>
        --grouping <grouping plan> --source <picture_native.mp4> --out-ass <.ass> --out-video <subbed.mp4>
"""
from __future__ import annotations
import argparse, difflib, json, re, subprocess, sys
from pathlib import Path

FFMPEG = "/opt/homebrew/bin/ffmpeg"
FONT = "STHeiti Medium"
FONT_FILE = "/System/Library/Fonts/STHeiti Medium.ttc"
#: nalu D-74: a caption must clear the cut — it ends at least this many seconds before the unit's end,
#: otherwise the text disappears on the cut frame and the line reads as if it had been cut off.
TAIL_GUARD = 0.25

def cjk(text: str) -> str:
    return "".join(ch for ch in text if "一" <= ch <= "鿿")

def sim(a: str, b: str) -> float:
    a, b = cjk(a), cjk(b)
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0

def ass_time(t: float) -> str:
    t = max(0.0, t); h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"

def wrap(text: str, width: int = 15) -> str:
    text = text.strip()
    if len(text) <= width:
        return text
    # prefer a break at punctuation near the middle
    cut = None
    for i in range(min(len(text) - 1, width), max(1, len(text) // 3), -1):
        if text[i - 1] in "，。！？；：、":
            cut = i; break
    cut = cut or width
    return text[:cut] + "\\N" + wrap(text[cut:], width)

def assign(lines: list[dict], segs: list[dict], clip_dur: float) -> list[tuple[dict, float, float]]:
    """Return (line, local_start, local_end) per line."""
    segs = [s for s in segs if cjk(s["text"])]
    if not lines:
        return []
    if not segs:
        span = clip_dur / len(lines)
        return [(ln, i * span, (i + 1) * span) for i, ln in enumerate(lines)]
    n, m = len(lines), len(segs)
    if m >= n:
        # split segments into n consecutive groups maximising similarity (DP over boundaries)
        best = None
        import itertools
        for cuts in itertools.combinations(range(1, m), n - 1):
            bounds = [0, *cuts, m]
            score = 0.0
            for i in range(n):
                group = segs[bounds[i]:bounds[i + 1]]
                score += sim(lines[i]["text"], "".join(g["text"] for g in group))
            if best is None or score > best[0]:
                best = (score, bounds)
        bounds = best[1]
        out = []
        for i in range(n):
            group = segs[bounds[i]:bounds[i + 1]]
            out.append((lines[i], group[0]["start"], group[-1]["end"]))
        return out
    # fewer segments than lines: split the whole speech span by character count
    start, end = segs[0]["start"], segs[-1]["end"]
    total = sum(len(cjk(ln["text"])) or 1 for ln in lines)
    out, t = [], start
    for ln in lines:
        d = (end - start) * ((len(cjk(ln["text"])) or 1) / total)
        out.append((ln, t, t + d)); t += d
    return out

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--episode", required=True); ap.add_argument("--project", required=True, type=Path)
    ap.add_argument("--asr", required=True, type=Path); ap.add_argument("--contract", required=True, type=Path)
    ap.add_argument("--grouping", required=True, type=Path); ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--out-ass", required=True, type=Path); ap.add_argument("--out-video", required=True, type=Path)
    ap.add_argument("--out-report", type=Path); ap.add_argument("--pad", type=float, default=0.08)
    a = ap.parse_args()
    project = json.loads(a.project.read_text(encoding="utf-8"))
    asr = json.loads(a.asr.read_text(encoding="utf-8"))
    contract = json.loads(a.contract.read_text(encoding="utf-8"))
    grouping = json.loads(a.grouping.read_text(encoding="utf-8"))
    id2name = {e["character_id"]: e["canonical_name"] for e in contract["character_entities"]}
    shot2unit = {s: u["unit_id"] for u in grouping["units"] for s in u["editorial_shot_ids"]}
    lines_by_unit: dict[str, list[dict]] = {}
    for d in contract["audio_contract"]["dialogue_units"]:
        lines_by_unit.setdefault(shot2unit[d["shot_id"]], []).append(
            {"shot_id": d["shot_id"], "speaker": id2name[d["speaker_id"]], "text": d["text"]})
    clips = []
    for track in (project.get("timeline") or {}).get("videoTracks") or []:
        clips.extend(track.get("clips") or [])
    events, report = [], []
    for clip in sorted(clips, key=lambda c: float(c["start"])):
        uid = str((clip.get("metadata") or {}).get("source_id") or "")
        lines = lines_by_unit.get(uid) or []
        if not lines:
            continue
        cstart, cdur = float(clip["start"]), float(clip["duration"])
        for ln, ls, le in assign(lines, asr.get(uid) or [], cdur):
            # nalu D-74 (E07 1:44, Roger): the caption used to be clamped to the clip end, so the text was
            # still on screen on the cut frame and the line READ as cut off even though the voice had
            # finished 0.4 s earlier.  A caption now always clears TAIL_GUARD before the cut.
            tail_limit = max(0.3, cdur - TAIL_GUARD)
            s = max(0.0, ls - a.pad); e = min(tail_limit, le + a.pad)
            if e - s < 0.8:
                e = min(tail_limit, s + 0.8)
            if e <= s:
                e = min(cdur, s + 0.3)
            events.append((cstart + s, cstart + e, ln))
            report.append({"unit_id": uid, "shot_id": ln["shot_id"], "speaker": ln["speaker"], "text": ln["text"],
                           "start": round(cstart + s, 3), "end": round(cstart + e, 3)})
    # no overlaps: clamp each caption's end to the next start
    events.sort(key=lambda x: x[0])
    for i in range(len(events) - 1):
        if events[i][1] > events[i + 1][0]:
            events[i] = (events[i][0], events[i + 1][0], events[i][2])
    header = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
              "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
              f"Style: ZH,{FONT},42,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,0,2,72,72,170,1\n\n"
              "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    body = "".join(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},ZH,{ln['speaker']},0,0,0,,{wrap(ln['text'])}\n" for s, e, ln in events)
    a.out_ass.parent.mkdir(parents=True, exist_ok=True); a.out_ass.write_text(header + body, encoding="utf-8")
    a.out_video.parent.mkdir(parents=True, exist_ok=True)
    # this ffmpeg build has no libass/drawtext: render each caption to a transparent PNG (PIL,
    # STHeiti Medium, white with 3 px black outline) and overlay it time-gated.
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(FONT_FILE, 42)
    png_dir = a.out_ass.parent / "subtitle_png"; png_dir.mkdir(parents=True, exist_ok=True)
    inputs, chain = [], []
    W, H, MARGIN_BOTTOM, LINE_H = 720, 1280, 170, 54
    for i, (s_t, e_t, ln) in enumerate(events):
        rows = wrap(ln["text"]).split("\\N")
        img = Image.new("RGBA", (W, LINE_H * len(rows) + 24), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
        for r, row in enumerate(rows):
            tw = d.textlength(row, font=font)
            d.text(((W - tw) / 2, 8 + r * LINE_H), row, font=font, fill=(255, 255, 255, 255),
                   stroke_width=3, stroke_fill=(0, 0, 0, 255))
        png = png_dir / f"cap_{i + 1:03d}.png"; img.save(png)
        inputs += ["-i", str(png)]
        y = H - MARGIN_BOTTOM - img.height
        src = "[0:v]" if i == 0 else f"[v{i}]"
        chain.append(f"{src}[{i + 1}:v]overlay=x=0:y={y}:enable='between(t,{s_t:.3f},{e_t:.3f})'[v{i + 1}]")
    last = f"[v{len(events)}]" if events else "[0:v]"
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(a.source), *inputs,
           "-filter_complex", ";".join(chain) if chain else "null", "-map", last, "-map", "0:a",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy",
           "-movflags", "+faststart", str(a.out_video)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = {"schema": "nalu.burnin_subtitles.v1", "episode": a.episode, "captions": len(events), "ass": str(a.out_ass),
           "video": str(a.out_video), "ffmpeg_exit": proc.returncode, "stderr": proc.stderr[-800:], "rows": report,
           "text_source": "generation contract dialogue_units (verbatim)", "timing_source": str(a.asr), "font": FONT}
    if a.out_report:
        a.out_report.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("captions", "ffmpeg_exit", "video")}, ensure_ascii=False))
    return 0 if proc.returncode == 0 else 2

if __name__ == "__main__":
    sys.exit(main())
