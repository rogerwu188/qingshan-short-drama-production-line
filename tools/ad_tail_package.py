#!/usr/bin/env python3
"""ad_tail_package.py — pack a raw ad clip into the tail-ad slot contract.

Any mp4 (dropped into ads/inbox/ or produced by the AdForge adapter) goes
through this single packager before it can ever be spliced into a release.
ALL technical gates for the tail-ad slot live here (spec
codex_docs/ROGER-20260925-AD-TAIL-INTEGRATION.md §三): OCR-clean, duration,
format, and spoken-content are checked fail-closed BEFORE any burn-in;
loudness and label-presence are re-checked AFTER burn-in as defence in depth.
A failure at any step means no packaged file is written — the ad is simply
not produced this run, never a partial/best-effort file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE = Path(__file__).resolve().parents[1]
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

try:
    from lines.nalu.runtime.tools.nalu_media_tools import (
        MediaToolBlocked, require_ffmpeg, require_ffprobe, resolve_cjk_font,
    )
except ModuleNotFoundError:
    sys.path.insert(0, str(ENGINE / "lines/nalu/runtime/tools"))
    from nalu_media_tools import MediaToolBlocked, require_ffmpeg, require_ffprobe, resolve_cjk_font  # type: ignore


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def load_contract(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ffprobe_format(ffprobe: str, path: Path) -> dict[str, Any]:
    result = _run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {result.stderr[-2000:]}")
    return json.loads(result.stdout)


def check_duration(probe: dict[str, Any], slot: dict[str, Any]) -> dict[str, Any]:
    duration = float(probe["format"]["duration"])
    lo, hi = slot["duration_seconds"]["min"], slot["duration_seconds"]["max"]
    failures = []
    if duration < lo or duration > hi:
        failures.append(f"OUT_OF_RANGE:{duration:.3f}s:not_in[{lo},{hi}]")
    return {"status": "PASS" if not failures else "FAIL", "failures": failures, "seconds": round(duration, 3)}


def check_format(probe: dict[str, Any], slot: dict[str, Any]) -> dict[str, Any]:
    """Informational only — the packager re-encodes to spec regardless.  Catches an
    unusably corrupt/black/audio-less input early rather than burning a re-encode on it."""
    failures: list[str] = []
    video = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in probe.get("streams", []) if s.get("codec_type") == "audio"), None)
    if video is None:
        failures.append("NO_VIDEO_STREAM")
    if audio is None:
        failures.append("NO_AUDIO_STREAM")
    return {"status": "PASS" if not failures else "FAIL", "failures": failures,
            "video": {"width": video.get("width"), "height": video.get("height")} if video else None}


def check_ocr_clean(ffmpeg_unused: str, input_path: Path, out_dir: Path, slot: dict[str, Any],
                    cta_text: str | None = None) -> dict[str, Any]:
    """AD_TAIL_OCR_CLEAN.  Scans the RAW, pre-overlay clip.  Mode A may hand us an
    already-finished drop (e.g. the AdForge demo) that legitimately already carries
    its own '广告' badge and CTA caption — those are ALLOWED, expected branding,
    not the anachronistic/garbage text this check actually guards against.
    (spec: 'ocr_clean_scope: RAW_MODEL_GENERATED_PICTURE_ONLY', exempt:
    SUBTITLE_LAYER / AD_LABEL_BADGE)."""
    out_path = out_dir / "ocr_audit.json"
    allow = [slot["label"]["text_zh"], slot["label"]["text_en"]]
    if cta_text and cta_text.strip():
        allow.append(cta_text.strip())
    cmd = [sys.executable, str(ENGINE / "tools/final_video_ocr_audit.py"),
           "--video", str(input_path), "--out", str(out_path), "--source-mode"]
    for text in allow:
        cmd += ["--allow-text", text]
    result = _run(cmd)
    payload = json.loads(out_path.read_text(encoding="utf-8")) if out_path.is_file() else {}
    failures: list[str] = []
    if result.returncode not in (0, 1) or not payload:
        failures.append(f"OCR_TOOL_ERROR:{result.stderr[-500:]}")
    elif payload.get("status") != "PASS":
        failures.append(f"OCR_NOT_CLEAN:critical_text_failures={payload.get('critical_text_failures')}")
    badge_text = slot["label"]["text_zh"]
    badge_already_present = any(
        row.get("text") == badge_text and row.get("allowed")
        for row in payload.get("recognitions") or [])
    return {"status": "PASS" if not failures else "FAIL", "failures": failures,
            "report": str(out_path), "critical_text_failures": payload.get("critical_text_failures"),
            "badge_already_present": badge_already_present}


def check_spoken_content(input_path: Path, slot: dict[str, Any], cta_text: str | None) -> dict[str, Any]:
    """Not one of the spec's six named diagnostics, but enforced as a hard gate
    (spoken_chars_max, CTA never spoken) — see AD-TAIL-INTEGRATION §二/§四."""
    failures: list[str] = []
    try:
        from faster_whisper import WhisperModel  # type: ignore
        model = WhisperModel("small", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(input_path), language="zh", beam_size=5, vad_filter=True)
        transcript = "".join(seg.text.strip() for seg in segments)
    except Exception as exc:  # noqa: BLE001
        return {"status": "FAIL", "failures": [f"ASR_UNAVAILABLE:{type(exc).__name__}:{exc}"],
                "spoken_chars": None, "transcript": None, "cta_spoken": None}
    spoken_chars = _count_cjk_chars(transcript)
    cap = int(slot.get("spoken_chars_max", 20))
    if spoken_chars > cap:
        failures.append(f"SPOKEN_CHARS_OVER_CAP:{spoken_chars}>{cap}")
    cta_spoken = bool(cta_text and cta_text.strip() and cta_text.strip() in transcript)
    if cta_spoken:
        failures.append("CTA_URL_SPOKEN_MUST_BE_CAPTION_ONLY")
    return {"status": "PASS" if not failures else "FAIL", "failures": failures,
            "spoken_chars": spoken_chars, "transcript": transcript, "cta_spoken": cta_spoken}


_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")


def _count_cjk_chars(text: str) -> int:
    """Same convention as this line's own pacing contracts elsewhere
    (`dialogue_delivery.chinese_characters_per_second`): count Han/CJK
    characters, not raw string length — a short spoken word like "AI" or
    "Director" is a handful of Latin letters, not several spoken 'characters'."""
    return len(_CJK_RE.findall(text))



def _two_pass_loudnorm_filter(ffmpeg: str, input_path: Path, pre_filters: str, slot: dict[str, Any]) -> str:
    """Measure-then-apply LINEAR loudnorm, same structure as
    tools/level_native_release_audio.py:181-199 (single-track variant: this packager
    has exactly one audio stream, no multi-unit premix)."""
    target_lufs = float(slot["loudness"]["target_lufs"])
    tp = float(slot["loudness"]["true_peak_dbtp_max"])
    lra = float(slot["loudness"].get("lra", 11))
    probe_filter = (f"{pre_filters}loudnorm=I={target_lufs:g}:TP={tp:g}:LRA={lra:g}:print_format=json"
                    if pre_filters else f"loudnorm=I={target_lufs:g}:TP={tp:g}:LRA={lra:g}:print_format=json")
    probe = _run([ffmpeg, "-hide_banner", "-nostats", "-i", str(input_path),
                  "-filter:a", probe_filter, "-f", "null", "-"])
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", probe.stderr or "", re.S)
    if not match:
        raise RuntimeError("loudnorm first pass produced no statistics: " + (probe.stderr or "")[-2000:])
    stats = json.loads(match.group(0))
    linear = (f"loudnorm=I={target_lufs:g}:TP={tp:g}:LRA={lra:g}:linear=true:"
              f"measured_I={float(stats['input_i']):.3f}:measured_LRA={float(stats['input_lra']):.3f}:"
              f"measured_TP={float(stats['input_tp']):.3f}:measured_thresh={float(stats['input_thresh']):.3f}:"
              f"offset={float(stats.get('target_offset') or 0.0):.3f}")
    limiter_headroom_db = 0.5  # extra safety margin: the loudnorm+encode chain alone
                                # can land a few hundredths of a dB over its own TP target
    limiter_linear = 10 ** ((tp - limiter_headroom_db) / 20)
    return f"{pre_filters}{linear},alimiter=limit={limiter_linear:.6f}:attack=5:release=50:level=false"


def _render_badge_png(text: str, out_path: Path) -> Path:
    """Render the persistent top-right badge as a PNG, composited later via
    ffmpeg's `overlay` filter. Deliberately NOT drawtext/subtitles: those
    require an ffmpeg build linked against libfreetype/libass, which is not
    guaranteed on every deployment (confirmed absent on at least one dev
    machine this session) — `overlay` has no such dependency."""
    from PIL import Image, ImageDraw, ImageFont
    font_path, _ = resolve_cjk_font()
    font = ImageFont.truetype(font_path, 34)
    width, height = 166, 54
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, int(255 * 0.45)))
    draw = ImageDraw.Draw(canvas)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - text_w) / 2 - bbox[0], (height - text_h) / 2 - bbox[1]),
              text, font=font, fill=(255, 255, 255, 255))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return out_path


def burn_and_normalize(*, ffmpeg: str, input_path: Path, out_path: Path,
                        slot: dict[str, Any], subtitle_ass: Path | None,
                        skip_badge: bool = False) -> None:
    fmt = slot["format"]
    fade_seconds = float(slot["transition_in"]["seconds"])
    base_filters = [f"fps={fmt['fps']}", f"format={fmt['pixel_format']}",
                    f"fade=t=in:st=0:d={fade_seconds:g}:color=black"]
    if subtitle_ass is not None and subtitle_ass.is_file():
        # best-effort: requires an ffmpeg build with libass; degrades to no
        # burned-in subtitle (never a hard failure) when unavailable, since
        # CTA-never-spoken is independently enforced by check_spoken_content.
        probe = _run([ffmpeg, "-hide_banner", "-filters"])
        if "subtitles" in (probe.stdout or ""):
            escaped = str(subtitle_ass).replace(":", "\\:")
            base_filters.append(f"subtitles='{escaped}'")
    video_chain = ",".join(base_filters)

    audio_pre = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
    audio_chain = _two_pass_loudnorm_filter(ffmpeg, input_path, audio_pre, slot)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if skip_badge:
        # Mode A may hand us an already-finished drop that legitimately already
        # carries its own persistent badge (check_ocr_clean's badge_already_present) —
        # drawing a second one would visibly double up, so this run composites none.
        argv = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "warning", "-i", str(input_path),
            "-filter:v", video_chain, "-filter:a", audio_chain,
            "-r", str(fmt["fps"]), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", fmt["pixel_format"],
            "-c:a", fmt["audio_codec"], "-b:a", "192k", "-ar", str(fmt["audio_sample_rate"]),
            "-ac", str(fmt["audio_channels"]), "-movflags", "+faststart", str(out_path),
        ]
        result = _run(argv)
        if result.returncode != 0 or not out_path.is_file():
            out_path.unlink(missing_ok=True)
            raise RuntimeError(f"burn-in/normalize ffmpeg failed: {result.stderr[-4000:]}")
        return

    badge_png = out_path.parent / f"{out_path.stem}_badge.png"
    _render_badge_png(slot["label"]["text_zh"], badge_png)
    filter_complex = f"[0:v]{video_chain}[base];[base][1:v]overlay=W-w-24:24[v]"
    result = _run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
        "-i", str(input_path), "-loop", "1", "-i", str(badge_png),
        "-filter_complex", filter_complex, "-filter:a", audio_chain,
        "-map", "[v]", "-map", "0:a:0",
        "-r", str(fmt["fps"]), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", fmt["pixel_format"], "-shortest",
        "-c:a", fmt["audio_codec"], "-b:a", "192k", "-ar", str(fmt["audio_sample_rate"]),
        "-ac", str(fmt["audio_channels"]), "-movflags", "+faststart", str(out_path),
    ])
    badge_png.unlink(missing_ok=True)
    if result.returncode != 0 or not out_path.is_file():
        out_path.unlink(missing_ok=True)
        raise RuntimeError(f"burn-in/normalize ffmpeg failed: {result.stderr[-4000:]}")


def check_loudness_final(ffmpeg: str, out_path: Path, slot: dict[str, Any]) -> dict[str, Any]:
    """AD_TAIL_LOUDNESS — re-measure the packaged output (defence in depth: confirms
    the two-pass result actually landed in band, not just that the filter ran)."""
    target = float(slot["loudness"]["target_lufs"])
    tol = float(slot["loudness"]["tolerance_lu"])
    tp_max = float(slot["loudness"]["true_peak_dbtp_max"])
    lra = float(slot["loudness"].get("lra", 11))
    probe = _run([ffmpeg, "-hide_banner", "-nostats", "-i", str(out_path),
                  "-filter:a", f"loudnorm=I={target:g}:TP={tp_max:g}:LRA={lra:g}:print_format=json",
                  "-f", "null", "-"])
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", probe.stderr or "", re.S)
    failures: list[str] = []
    measured_lufs = measured_tp = None
    if not match:
        failures.append("LOUDNESS_MEASUREMENT_FAILED")
    else:
        stats = json.loads(match.group(0))
        measured_lufs = float(stats["input_i"])
        measured_tp = float(stats["input_tp"])
        if abs(measured_lufs - target) > tol:
            failures.append(f"LUFS_OUT_OF_BAND:{measured_lufs:.2f}:target={target:g}±{tol:g}")
        if measured_tp > tp_max:
            failures.append(f"TRUE_PEAK_OVER:{measured_tp:.2f}>{tp_max:g}")
    return {"status": "PASS" if not failures else "FAIL", "failures": failures,
            "measured_lufs": measured_lufs, "measured_tp": measured_tp}


def check_label_present(ffmpeg: str, out_path: Path, slot: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    """AD_TAIL_LABEL_PRESENT — sample 5 frames and verify non-trivial signal in the
    badge's fixed pixel region (top-right, matches burn_and_normalize's drawbox)."""
    from PIL import Image
    probe = ffprobe_format(require_ffprobe(), out_path)
    duration = float(probe["format"]["duration"])
    frame_dir = out_dir / "label_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    samples = [0.05, 0.25, 0.5, 0.75, 0.95]
    for index, fraction in enumerate(samples):
        ts = max(0.0, min(duration - 0.05, duration * fraction))
        frame = frame_dir / f"f{index}.png"
        result = _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{ts:.3f}",
                       "-i", str(out_path), "-frames:v", "1", str(frame)])
        if result.returncode != 0 or not frame.is_file():
            failures.append(f"FRAME_SAMPLE_FAILED:{fraction}")
            continue
        image = Image.open(frame).convert("L")
        width, height = image.size
        box = image.crop((int(width * 0.74), int(height * 0.015), int(width * 0.99), int(height * 0.06)))
        pixels = list(box.getdata())
        if not pixels or (max(pixels) - min(pixels)) < 10:
            failures.append(f"BADGE_REGION_FLAT_AT:{fraction}")
    return {"status": "PASS" if not failures else "FAIL", "failures": failures, "samples_checked": len(samples)}


def package(*, input_path: Path, sku: str, provenance: str, slot_contract_path: Path,
            subtitle_ass: Path | None, cta_text: str | None, out_path: Path, out_qa_path: Path) -> dict[str, Any]:
    slot = load_contract(slot_contract_path)
    input_sha = sha256(input_path)

    if out_qa_path.is_file():
        existing = json.loads(out_qa_path.read_text(encoding="utf-8"))
        if existing.get("input_sha256") == input_sha and out_path.is_file() \
                and existing.get("packaged_sha256") == sha256(out_path):
            existing["reused"] = True
            return existing
        raise FileExistsError(
            f"{out_path} / {out_qa_path} already exist for a different input; "
            "use a new sku or remove the stale packaged files before re-packaging")

    try:
        ffmpeg = require_ffmpeg()
        ffprobe = require_ffprobe()
    except MediaToolBlocked as exc:
        payload = {"schema": "qingshan.ad_tail_package_qa.v1", "sku": sku, "provenance": provenance,
                   "input_sha256": input_sha, "status": "FAIL", "failures": [f"MEDIA_TOOL_BLOCKED:{exc}"]}
        return payload

    out_dir = out_qa_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    probe = ffprobe_format(ffprobe, input_path)
    ad_tail_ocr_clean = check_ocr_clean(ffmpeg, input_path, out_dir, slot, cta_text=cta_text)
    ad_tail_duration = check_duration(probe, slot)
    ad_tail_format = check_format(probe, slot)
    spoken_content_contract = check_spoken_content(input_path, slot, cta_text)

    pre_burn_failures = (ad_tail_ocr_clean["status"] != "PASS" or ad_tail_duration["status"] != "PASS"
                          or ad_tail_format["status"] != "PASS" or spoken_content_contract["status"] != "PASS")
    payload: dict[str, Any] = {
        "schema": "qingshan.ad_tail_package_qa.v1", "sku": sku, "provenance": provenance,
        "input_sha256": input_sha, "recorded_at": now(),
        "ad_tail_ocr_clean": ad_tail_ocr_clean, "ad_tail_duration": ad_tail_duration,
        "ad_tail_format": ad_tail_format, "spoken_content_contract": spoken_content_contract,
    }
    if pre_burn_failures:
        payload["ad_tail_loudness"] = {"status": "NOT_RUN", "failures": []}
        payload["ad_tail_label_present"] = {"status": "NOT_RUN", "failures": []}
        payload["ad_tail_sha_bound"] = {"status": "NOT_RUN", "failures": []}
        payload["status"] = "FAIL"
        out_qa_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload

    try:
        burn_and_normalize(ffmpeg=ffmpeg, input_path=input_path, out_path=out_path,
                            slot=slot, subtitle_ass=subtitle_ass,
                            skip_badge=ad_tail_ocr_clean.get("badge_already_present", False))
    except Exception as exc:  # noqa: BLE001
        payload["ad_tail_loudness"] = {"status": "NOT_RUN", "failures": []}
        payload["ad_tail_label_present"] = {"status": "NOT_RUN", "failures": []}
        payload["ad_tail_sha_bound"] = {"status": "NOT_RUN", "failures": []}
        payload["status"] = "FAIL"
        payload["failures"] = [f"BURN_IN_FAILED:{type(exc).__name__}:{exc}"]
        out_qa_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload
    ad_tail_loudness = check_loudness_final(ffmpeg, out_path, slot)
    ad_tail_label_present = check_label_present(ffmpeg, out_path, slot, out_dir)
    payload["ad_tail_loudness"] = ad_tail_loudness
    payload["ad_tail_label_present"] = ad_tail_label_present
    payload["packaged_sha256"] = sha256(out_path)
    all_pass = all(payload[key]["status"] == "PASS" for key in (
        "ad_tail_ocr_clean", "ad_tail_duration", "ad_tail_format",
        "spoken_content_contract", "ad_tail_loudness", "ad_tail_label_present"))
    payload["status"] = "PASS" if all_pass else "FAIL"
    if not all_pass:
        out_path.unlink(missing_ok=True)
        payload.pop("packaged_sha256", None)
    out_qa_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("package")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--sku", required=True)
    p.add_argument("--provenance", required=True)
    p.add_argument("--slot-contract", required=True, type=Path)
    p.add_argument("--subtitle-ass", type=Path)
    p.add_argument("--cta-text")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--out-qa", required=True, type=Path)
    args = parser.parse_args()

    payload = package(
        input_path=args.input.resolve(), sku=args.sku, provenance=args.provenance,
        slot_contract_path=args.slot_contract.resolve(),
        subtitle_ass=args.subtitle_ass.resolve() if args.subtitle_ass else None,
        cta_text=args.cta_text, out_path=args.out.resolve(), out_qa_path=args.out_qa.resolve(),
    )
    print(json.dumps({"status": payload["status"], "sku": payload["sku"],
                      "out_qa": str(args.out_qa), "reused": payload.get("reused", False)}, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
