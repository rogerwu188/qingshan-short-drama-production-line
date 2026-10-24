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
bottom-centre, 170 px bottom margin, wrap at 15 chars) with a resolved CJK font file.

--language en (English dialogue): similarity on lowercase letters+digits, word-count timing
weights, word-boundary wrap at ~42 chars and at most 2 lines, style "EN" at 36 px (shrunk per
caption to fit the frame width) with nalu_media_tools.resolve_latin_font (QINGSHAN_LATIN_FONT /
NALU_LATIN_FONT, common system paths, else the CJK font, which also carries Latin glyphs).

--split-long-captions (CAMERA_GRAMMAR_V1 episodes; lab E02 VU-001): a line whose wrapped rows do not
fit the frame at the normal font size (more than 2 rows, or a row wider than the frame) becomes
several sequential cues of at most 2 rows each, preferring clause punctuation as the break; the
line's speech window is divided between them by the ASR segment boundaries inside it (linear by
speech characters within each segment) — proportional to characters when the line has one
segment.  Captions are never shrunk below the normal size unless one word alone is too wide.
Without the flag every caption is built exactly as before.

--voice-over-placement (S7 V.O. narration): dialogue units spoken by a VOICE_ONLY_NO_PLATE narrator
are captioned at the placement's start/end (the mixed-in S4 wav), never ASR-assigned; every other
caption is built exactly as before.

  build --episode EP --project <agentcut project> --asr <per-unit asr json> --contract <generation contract>
        --grouping <grouping plan> --source <picture_native.mp4> --out-ass <.ass> --out-video <subbed.mp4>
        [--language zh|en] [--voice-over-placement <EP>_voice_over_placement.json]
"""
from __future__ import annotations
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))
import nalu_media_tools as _media

import argparse, difflib, json, math, re, subprocess, sys
from pathlib import Path

# Prefer clearing a cut only when the measured speech leaves room for it.
TAIL_GUARD = 0.25

EN_WRAP_CHARS = 42
EN_FONT_SIZE = 36
CAPTION_MAX_WIDTH = 720 - 40

def cjk(text: str) -> str:
    return "".join(ch for ch in text if "一" <= ch <= "鿿")

def latin(text: str) -> str:
    """English comparison form: lowercase letters and digits only."""
    return "".join(ch for ch in text.lower() if ("a" <= ch <= "z") or ch.isdigit())

def speech(text: str, language: str = "zh") -> str:
    return latin(text) if language == "en" else cjk(text)

def weight(text: str, language: str = "zh") -> int:
    """Timing weight of one line: CJK characters (zh) or words (en)."""
    if language == "en":
        return len(re.findall(r"[A-Za-z0-9]+(?:['\u2019][A-Za-z0-9]+)*", text))
    return len(cjk(text))

def sim(a: str, b: str, language: str = "zh") -> float:
    a, b = speech(a, language), speech(b, language)
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

def wrap_en(text: str, width: int = EN_WRAP_CHARS) -> str:
    """Word-boundary wrap, at most 2 lines: a line over ``width`` is split at the word
    boundary that best balances the two halves (never inside a word)."""
    text = " ".join(text.split())
    words = text.split(" ")
    if len(text) <= width or len(words) < 2:
        return text
    best = min(range(1, len(words)),
               key=lambda i: (max(len(" ".join(words[:i])), len(" ".join(words[i:]))),
                              -int(words[i - 1][-1:] in ",.;:!?")))
    return " ".join(words[:best]) + "\\N" + " ".join(words[best:])

CUE_BREAK_PUNCT = ",.;:!?—，。！？；：、"


def split_cues(text: str, fits, language: str = "zh") -> list[str]:
    """Split one dialogue line into sequential caption cues that each ``fits`` (normal size, <= 2 rows).

    Tokens are words (en) or characters (zh).  The cue count is the smallest that fits; among the
    splits with that count the one with the most even cue lengths wins, a break right after clause
    punctuation being preferred.  A line that already fits is returned unchanged as a single cue.
    """
    english = language == "en"
    text = " ".join(text.split()) if english else text.strip()
    if not text or fits(text):
        return [text] if text else []
    tokens = text.split(" ") if english else list(text)
    joiner = " " if english else ""
    T = len(tokens)
    cache: dict[tuple[int, int], bool] = {}

    def ok(i: int, j: int) -> bool:
        if (i, j) not in cache:
            cache[(i, j)] = j == i + 1 or fits(joiner.join(tokens[i:j]))
        return cache[(i, j)]

    # fewest cues: BFS layers over token boundaries
    reach, n = {0}, 0
    while T not in reach:
        reach = {j for i in reach for j in range(i + 1, T + 1) if ok(i, j)} - {0}
        n += 1
    target = len(text) / n

    def cost(i: int, j: int) -> float:
        c = ((len(joiner.join(tokens[i:j])) - target) / target) ** 2
        return c if j == T or tokens[j - 1][-1:] in CUE_BREAK_PUNCT else c + 0.5

    # best[k][j]: cheapest split of tokens[:j] into k cues
    INF = float("inf")
    best = [{0: (0.0, None)}] + [dict() for _ in range(n)]
    for k in range(1, n + 1):
        for i, (c0, _) in best[k - 1].items():
            for j in range(i + 1, T + 1):
                if not ok(i, j):
                    break
                c = c0 + cost(i, j)
                if c < best[k].get(j, (INF, None))[0]:
                    best[k][j] = (c, i)
    cuts, j = [], T
    for k in range(n, 0, -1):
        i = best[k][j][1]
        cuts.append((i, j))
        j = i
    return [joiner.join(tokens[i:j]) for i, j in reversed(cuts)]


def cue_boundaries(cues: list[str], start: float, end: float, segs: list[dict],
                   language: str = "zh") -> list[float]:
    """Source-time boundaries [start, b1, ..., end] of ``cues`` inside the line window [start, end].

    The ASR segments lying in the window are knots (cumulative speech characters -> segment end /
    next segment start), so a cue boundary follows the measured speech; inside a segment, and when
    the window holds a single segment, time is linear in speech characters.
    """
    weights = [max(1, len(speech(c, language))) for c in cues]
    total = float(sum(weights))
    inside = [s for s in segs if speech(s.get("text") or "", language)
              and float(s["start"]) >= start - 0.05 and float(s["end"]) <= end + 0.05]
    knots = [(0.0, start)]
    if len(inside) >= 2:
        seg_total = float(sum(len(speech(s["text"], language)) for s in inside)) or 1.0
        acc = 0.0
        for a, b in zip(inside, inside[1:]):
            acc += len(speech(a["text"], language))
            t = (max(start, min(end, float(a["end"]))) + max(start, min(end, float(b["start"])))) / 2
            knots.append((acc / seg_total, max(knots[-1][1], t)))
    knots.append((1.0, max(knots[-1][1], end)))

    def at(frac: float) -> float:
        for (f0, t0), (f1, t1) in zip(knots, knots[1:]):
            if frac <= f1:
                return t0 if f1 <= f0 else t0 + (t1 - t0) * (frac - f0) / (f1 - f0)
        return end

    out, acc = [start], 0.0
    for w in weights[:-1]:
        acc += w
        out.append(at(acc / total))
    out.append(end)
    return out


def assign(lines: list[dict], segs: list[dict], clip_dur: float,
           language: str = "zh") -> list[tuple[dict, float, float]]:
    """Return (line, local_start, local_end) per line."""
    segs = [s for s in segs if speech(s["text"], language)]
    joiner = " " if language == "en" else ""
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
                score += sim(lines[i]["text"], joiner.join(g["text"] for g in group), language)
            if best is None or score > best[0]:
                best = (score, bounds)
        bounds = best[1]
        out = []
        for i in range(n):
            group = segs[bounds[i]:bounds[i + 1]]
            out.append((lines[i], group[0]["start"], group[-1]["end"]))
        return out
    # fewer segments than lines: split the whole speech span by character (zh) / word (en) count
    start, end = segs[0]["start"], segs[-1]["end"]
    total = sum(weight(ln["text"], language) or 1 for ln in lines)
    out, t = [], start
    for ln in lines:
        d = (end - start) * ((weight(ln["text"], language) or 1) / total)
        out.append((ln, t, t + d)); t += d
    return out

def caption_window(clip: dict, source_start: float, source_end: float,
                   pad: float = 0.08, bridge_seconds: float = 0.0) -> tuple[float, float] | None:
    """Map source seconds to timeline seconds; never clip measured speech for styling.

    Match the portable renderer: constant 1x only. Unsupported retiming must
    be implemented in both consumers before it can be accepted here.
    ``bridge_seconds`` (CAMERA_GRAMMAR_V1 L-cut, clip metadata ``sound_bridge_out``): the clip's
    audio plays on that long over the next picture, so its captions may too.
    """
    start, duration, source_in = (float(clip.get(k, default)) for k, default in
                                  (("start", 0), ("duration", 0), ("in", 0)))
    values = (start, duration, source_in, source_start, source_end, pad)
    if not all(math.isfinite(v) and v >= 0 for v in values) or duration <= 0:
        raise ValueError("invalid caption/source time")
    if source_end <= source_start:
        raise ValueError("invalid speech interval")
    for key in ("speed", "playbackRate"):
        if key in clip and float(clip[key]) != 1:
            raise ValueError("subtitle timing requires supported 1x portable timeline")
    local_start, local_end = source_start - source_in, source_end - source_in
    if bridge_seconds > 0:
        duration += float(bridge_seconds)
    if local_end <= 0 or local_start >= duration:
        return None
    # Do not resurrect speech removed by a source trim using padding.
    s = max(0.0, local_start - pad)
    spoken_end = min(duration, local_end)
    tail_limit = max(spoken_end, duration - TAIL_GUARD)
    e = min(duration, tail_limit, max(local_end + pad, s + 0.8))
    return (start + s, start + e) if e > s else None


def voice_over_captions(contract: dict, placement: dict | None) -> dict[int, dict]:
    """dialogue_units index -> placement row for V.O. narration (speaker is VOICE_ONLY_NO_PLATE).

    Without a placement file nothing is treated as V.O., so every other caption is built exactly
    as before.  Rows are matched on shot id + normalized text, in authored order.
    """
    if not placement:
        return {}
    voice_only = {str(e.get("character_id")) for e in contract.get("character_entities") or []
                  if str((e.get("identity_source") or {}).get("mode") or "") == "VOICE_ONLY_NO_PLATE"}
    norm = lambda text: "".join(ch for ch in str(text).lower() if ch.isalnum())  # noqa: E731
    remaining = list(placement.get("rows") or [])
    out: dict[int, dict] = {}
    for index, d in enumerate((contract.get("audio_contract") or {}).get("dialogue_units") or []):
        if str(d.get("speaker_id") or "") not in voice_only:
            continue
        hit = next((row for row in remaining if str(row.get("shot_id")) == str(d.get("shot_id"))
                    and norm(row.get("text") or "") == norm(d.get("text") or "")), None)
        if hit is not None:
            remaining.remove(hit)
            out[index] = hit
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--episode", required=True); ap.add_argument("--project", required=True, type=Path)
    ap.add_argument("--asr", required=True, type=Path); ap.add_argument("--contract", required=True, type=Path)
    ap.add_argument("--grouping", required=True, type=Path); ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--out-ass", required=True, type=Path); ap.add_argument("--out-video", required=True, type=Path)
    ap.add_argument("--out-report", type=Path); ap.add_argument("--pad", type=float, default=0.08)
    ap.add_argument("--language", choices=("zh", "en"), default="zh")
    ap.add_argument("--voice-over-placement", type=Path,
                    help="<EP>_voice_over_placement.json: V.O. narration lines are timed from it, never ASR-assigned")
    ap.add_argument("--split-long-captions", action="store_true",
                    help="CAMERA_GRAMMAR_V1: a line too long for 2 normal-size rows becomes sequential cues")
    a = ap.parse_args()
    english = a.language == "en"
    style, font_size = ("EN", EN_FONT_SIZE) if english else ("ZH", 42)
    wrap_text = wrap_en if english else wrap
    font_file, font_source = _media.resolve_latin_font() if english else _media.resolve_cjk_font()
    font_name = Path(font_file).stem
    project = json.loads(a.project.read_text(encoding="utf-8"))
    asr = json.loads(a.asr.read_text(encoding="utf-8"))
    contract = json.loads(a.contract.read_text(encoding="utf-8"))
    grouping = json.loads(a.grouping.read_text(encoding="utf-8"))
    id2name = {e["character_id"]: e["canonical_name"] for e in contract["character_entities"]}
    shot2unit = {s: u["unit_id"] for u in grouping["units"] for s in u["editorial_shot_ids"]}
    lines_by_unit: dict[str, list[dict]] = {}
    voice_over = voice_over_captions(contract, json.loads(a.voice_over_placement.read_text(encoding="utf-8"))
                                     if a.voice_over_placement else None)
    for index, d in enumerate(contract["audio_contract"]["dialogue_units"]):
        if index in voice_over:
            continue  # V.O. narration: not in the unit's native audio, timed from the S7 placement below
        lines_by_unit.setdefault(shot2unit[d["shot_id"]], []).append(
            {"shot_id": d["shot_id"], "speaker": id2name[d["speaker_id"]], "text": d["text"]})
    clips = []
    for track in (project.get("timeline") or {}).get("videoTracks") or []:
        clips.extend(track.get("clips") or [])
    events, report = [], []
    fits = None
    if a.split_long_captions:
        from PIL import Image as _Image, ImageDraw as _ImageDraw, ImageFont as _ImageFont
        _measure = _ImageDraw.Draw(_Image.new("RGBA", (8, 8)))
        _font = _ImageFont.truetype(font_file, font_size)

        def fits(chunk: str) -> bool:
            rows = wrap_text(chunk).split("\\N")
            return len(rows) <= 2 and all(_measure.textlength(r, font=_font) <= CAPTION_MAX_WIDTH for r in rows)
    for clip in sorted(clips, key=lambda c: float(c["start"])):
        uid = str((clip.get("metadata") or {}).get("source_id") or "")
        lines = lines_by_unit.get(uid) or []
        if not lines:
            continue
        cstart, cdur = float(clip["start"]), float(clip["duration"])
        segs = asr.get(uid) or []
        valid_segs = [seg for seg in segs if speech(seg["text"], a.language)]
        timing_basis = ("ASR_SEGMENT_MATCH" if len(valid_segs) >= len(lines) else
                        "TEXT_WEIGHTED_ESTIMATE" if valid_segs else "CLIP_SPAN_ESTIMATE")
        source_in = float(clip.get("in", 0))
        for ln, ls, le in assign(lines, segs, cdur, a.language):
            if not valid_segs:
                ls, le = ls + source_in, le + source_in
            bridge = float(((clip.get("metadata") or {}).get("sound_bridge_out") or {}).get("seconds") or 0.0)
            window = caption_window(clip, ls, le, a.pad, bridge_seconds=bridge)
            if window is None:
                continue
            s, e = window
            cues = split_cues(ln["text"], fits, a.language) if fits is not None else [ln["text"]]
            if len(cues) <= 1:
                events.append((s, e, ln))
                report.append({"unit_id": uid, "shot_id": ln["shot_id"], "speaker": ln["speaker"], "text": ln["text"],
                               "start": round(s, 3), "end": round(e, 3),
                               "source_start": ls, "source_end": le, "source_in": source_in,
                               "timing_basis": timing_basis, "timing_verification": "NOT_VERIFIED"})
                continue
            # long line: sequential cues inside the line's caption window, split at the speech boundaries
            bounds = cue_boundaries(cues, ls, le, valid_segs, a.language)
            times = [s] + [min(e, max(s, cstart + b - source_in)) for b in bounds[1:-1]] + [e]
            for k, cue in enumerate(cues):
                cs, ce = times[k], times[k + 1]
                if ce <= cs:
                    continue
                events.append((cs, ce, dict(ln, text=cue)))
                report.append({"unit_id": uid, "shot_id": ln["shot_id"], "speaker": ln["speaker"], "text": cue,
                               "line_text": ln["text"], "cue": k + 1, "cues": len(cues),
                               "start": round(cs, 3), "end": round(ce, 3),
                               "source_start": ls, "source_end": le, "source_in": source_in,
                               "timing_basis": timing_basis, "cue_timing": "ASR_SEGMENT_KNOTS_CHAR_WEIGHTED",
                               "timing_verification": "NOT_VERIFIED"})
    for index, placed in sorted(voice_over.items()):
        d = contract["audio_contract"]["dialogue_units"][index]
        ln = {"shot_id": d["shot_id"], "speaker": id2name[d["speaker_id"]], "text": d["text"]}
        s, e = float(placed["start"]), float(placed["end"]) + a.pad
        events.append((s, e, ln))
        report.append({"unit_id": shot2unit.get(d["shot_id"]), "shot_id": d["shot_id"], "speaker": ln["speaker"],
                       "text": d["text"], "start": round(s, 3), "end": round(e, 3),
                       "timing_basis": "VOICE_OVER_PLACEMENT", "presence": "VOICE_OVER",
                       "timing_verification": "PLACED_FROM_S4_WAV_DURATION"})
    # no overlaps: clamp each caption's end to the next start
    events.sort(key=lambda x: x[0])
    report.sort(key=lambda row: row["start"])
    for i in range(len(events) - 1):
        if events[i][1] > events[i + 1][0]:
            events[i] = (events[i][0], events[i + 1][0], events[i][2])
            report[i]["end"] = round(events[i][1], 3)
    header = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
              "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
              f"Style: {style},{font_name},{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,0,2,72,72,170,1\n\n"
              "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    body = "".join(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},{style},{ln['speaker']},0,0,0,,{wrap_text(ln['text'])}\n" for s, e, ln in events)
    a.out_ass.parent.mkdir(parents=True, exist_ok=True); a.out_ass.write_text(header + body, encoding="utf-8")
    a.out_video.parent.mkdir(parents=True, exist_ok=True)
    # this ffmpeg build has no libass/drawtext: render each caption to a transparent PNG (PIL,
    # resolved CJK font, white with 3 px black outline) and overlay it time-gated.
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(font_file, font_size)
    png_dir = a.out_ass.parent / "subtitle_png"; png_dir.mkdir(parents=True, exist_ok=True)
    inputs, chain = [], []
    W, H, MARGIN_BOTTOM, LINE_H = 720, 1280, 170, 54
    for i, (s_t, e_t, ln) in enumerate(events):
        rows = wrap_text(ln["text"]).split("\\N")
        img = Image.new("RGBA", (W, LINE_H * len(rows) + 24), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
        cap_font = font
        if english:
            # Latin rows run wider than 15-char CJK rows: shrink this caption to fit the frame
            widest = max(d.textlength(row, font=font) for row in rows)
            if widest > W - 40:
                cap_font = ImageFont.truetype(font_file, max(22, int(font_size * (W - 40) / widest)))
        for r, row in enumerate(rows):
            tw = d.textlength(row, font=cap_font)
            d.text(((W - tw) / 2, 8 + r * LINE_H), row, font=cap_font, fill=(255, 255, 255, 255),
                   stroke_width=3, stroke_fill=(0, 0, 0, 255))
        png = png_dir / f"cap_{i + 1:03d}.png"; img.save(png)
        inputs += ["-i", str(png)]
        y = H - MARGIN_BOTTOM - img.height
        src = "[0:v]" if i == 0 else f"[v{i}]"
        chain.append(f"{src}[{i + 1}:v]overlay=x=0:y={y}:enable='between(t,{s_t:.3f},{e_t:.3f})'[v{i + 1}]")
    last = f"[v{len(events)}]" if events else "[0:v]"
    cmd = [_media.require_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(a.source), *inputs,
           "-filter_complex", ";".join(chain) if chain else "null", "-map", last, "-map", "0:a",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy",
           "-movflags", "+faststart", str(a.out_video)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = {"schema": "nalu.burnin_subtitles.v1", "episode": a.episode, "captions": len(events), "ass": str(a.out_ass),
           "video": str(a.out_video), "ffmpeg_exit": proc.returncode, "stderr": proc.stderr[-800:], "rows": report,
           "text_source": "generation contract dialogue_units (verbatim)", "timing_source": str(a.asr),
           "font": font_name, "font_file": font_file, "font_source": font_source}
    if english:
        out["language"] = a.language
    if a.out_report:
        a.out_report.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("captions", "ffmpeg_exit", "video")}, ensure_ascii=False))
    return 0 if proc.returncode == 0 else 2

if __name__ == "__main__":
    try:
        sys.exit(main())
    except _media.MediaToolBlocked as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(3)
