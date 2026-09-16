#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""post_generation_qa_runner.py — D-6: the post-generation QA measurer.

``tools/post_generation_qa_scope_gate.py`` only CLASSIFIES which checks are
allowed after generation (12 technical, 5 basic-plot, 16 explicitly forbidden).
It measures nothing.  This runner performs the measurements, strictly inside
that scope:

  technical (all 12 allowed names, every one a real measurement)
    decode, duration, resolution, aspect_ratio, codec, audio_stream, av_sync,
    black_frame, freeze, corruption, frame_rate, sample_rate
      · ffprobe (streams + format) → decode / duration / resolution /
        aspect_ratio / codec / audio_stream / frame_rate / sample_rate /
        corruption
      · run_regression_ci.pure_black_frame_stats  → black_frame
        (ffmpeg blackframe=amount=95:threshold=32)
      · run_regression_ci.adjacent_motion_values + freeze_stats +
        static_hold_stats → freeze
      · tools/frame_cadence_audit.py            → frame_rate cadence evidence
      · tools/source_brightness_jump_audit.py   → recorded as supporting
        evidence under black_frame/freeze, never as a new check name (a name
        outside the allowed list would trip the scope gate)
      · tools/media_boundary_acceptance.py      → episode-level boundary
        acceptance across the downloaded units
    ASR dialogue presence
      · tools/source_video_dialogue_gate.py (faster-whisper) per unit, driven by
        runtime/configs/BASIC_DIALOGUE_QA_POLICY.json.  A homophone or
        orthographic variant is RECORDED as a machine adjudication and never
        rejected — see ``adjudicate_homophones``.

  basic plot (all 5 allowed names, and no sixth)
    episode_scene_correspondence, principal_character_presence,
    major_event_presence, major_dialogue_presence, chronological_unit_order
      · a ``post_gen_plot`` VLM review over an ffmpeg 2-fps contact sheet.

Forbidden checks are never computed and never named.  Note the trap: ``freeze``
is allowed but ``freeze_ratio`` is forbidden, and ``motion_energy`` /
``optical_flow`` are forbidden — the YAVG motion values the freeze measurement
needs are internal to it and are not surfaced as a check.

Output per unit: ADMIT / REJECT with reasons, plus a reroll request list in the
shape ``tools/reroll_cost_guard.py`` consumes (a ledger of ``events`` and one
guard invocation per rejected unit).

CLI
---
  scope        --episode EP                       (run the engine scope gate)
  contact-sheet --episode EP [--unit U]           (ffmpeg 2 fps sheets)
  technical    --episode EP [--unit U]            (deterministic measurers)
  run          --episode EP [--review <submitted post_gen_plot review>]
  status       --episode EP
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nalu_qa_common import (  # noqa: E402
    DIALOGUE_QA_POLICY, ENGINE, FFMPEG, FFPROBE, REROLL_POLICY, REVIEWER_ID,
    REVIEW_METHOD, VENV, Expectations, QaPaths, engine_module, now, read_json,
    sha256_file, write_json,
)

TOOL_ID = "post_generation_qa_runner.v1"

ALLOWED_TECHNICAL = ("decode", "duration", "resolution", "aspect_ratio", "codec",
                     "audio_stream", "av_sync", "black_frame", "freeze", "corruption",
                     "frame_rate", "sample_rate")
ALLOWED_BASIC_PLOT = ("episode_scene_correspondence", "principal_character_presence",
                      "major_event_presence", "major_dialogue_presence",
                      "chronological_unit_order")
TARGET = {"width": 720, "height": 1280, "aspect_ratio": "9:16",
          "video_codec": {"h264", "hevc"}, "audio_sample_rate": 48000}
ACCEPTED_UNIT_SAMPLE_RATES = {44100, 48000}   # nalu D-18: provider-native unit audio
#: whisper hallucinations on non-speech audio (wind, room tone) — well-known boilerplate
#: strings the model emits when there is no speech; never treated as Mandarin dialogue
ASR_HALLUCINATION_PATTERNS = ("字幕", "by索", "索兰娅", "独播", "YoYo", "Television",
                              "Exclusive", "订阅", "点赞", "转发", "明镜", "Amara",
                              "subtitle", "谢谢观看", "请不吝")
DURATION_TOLERANCE_SECONDS = 0.35
AV_SYNC_TOLERANCE_SECONDS = 0.25
#: bounded per-unit parallelism for the FREE measurers (ffmpeg/ffprobe subprocesses, the
#: faster-whisper gate subprocess, the contact sheet).  Every unit's work is independent and
#: writes only under its own <postgen_dir>/<unit_id>/; results are collected and written in
#: the original (sorted) unit order so the JSON output is byte-for-byte the sequential one.
DEFAULT_UNIT_WORKERS = 4


def unit_workers(default: int = DEFAULT_UNIT_WORKERS) -> int:
    """NALU_QA_WORKERS=1 restores strictly sequential execution."""
    try:
        return max(1, int(os.environ.get("NALU_QA_WORKERS") or default))
    except ValueError:
        return default


def parallel_map(fn: Callable[[str], Any], keys: Iterable[str],
                 workers: int | None = None) -> dict[str, Any]:
    """fn(key) for every key on a bounded thread pool; results keyed so the caller emits
    them in its own order.  An exception in any unit propagates exactly as it would have
    sequentially (the run fails)."""
    keys = list(keys)
    workers = unit_workers() if workers is None else workers
    if workers <= 1 or len(keys) <= 1:
        return {key: fn(key) for key in keys}
    with ThreadPoolExecutor(max_workers=min(workers, len(keys))) as pool:
        futures = {key: pool.submit(fn, key) for key in keys}
        return {key: future.result() for key, future in futures.items()}


def _run(argv: list[Any], *, timeout: int = 1800) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("GIGGLE_API_KEY", None)
    env["PYTHONPATH"] = os.pathsep.join([str(ENGINE), str(ENGINE / "tools")])
    return subprocess.run([str(item) for item in argv], cwd=str(ENGINE), env=env,
                          capture_output=True, text=True, timeout=timeout)


# --------------------------------------------------------------------------- #
# deterministic technical measurement
# --------------------------------------------------------------------------- #
_PROBE_CACHE: dict[tuple[str, int, int], dict[str, Any]] = {}
_PROBE_LOCK = threading.Lock()


def ffprobe(media: Path) -> dict[str, Any]:
    """ffprobe streams+format; a successful probe is cached per (path, mtime, size) for the
    life of the process (technical_checks and contact_sheet both probe the same file)."""
    try:
        stat = media.stat()
        key: tuple[str, int, int] | None = (str(media), stat.st_mtime_ns, stat.st_size)
    except OSError:
        key = None
    if key is not None:
        with _PROBE_LOCK:
            cached = _PROBE_CACHE.get(key)
        if cached is not None:
            return copy.deepcopy(cached)
    completed = _run([FFPROBE, "-v", "error", "-print_format", "json",
                      "-show_format", "-show_streams", str(media)], timeout=300)
    if completed.returncode != 0:
        return {"ok": False, "error": (completed.stderr or "")[-1500:]}
    try:
        result = {"ok": True, **json.loads(completed.stdout)}
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"ffprobe_json_unreadable:{exc}"}
    if key is not None:
        with _PROBE_LOCK:
            _PROBE_CACHE[key] = copy.deepcopy(result)
    return result


def _fraction(value: str | None) -> float | None:
    if not value or "/" not in str(value):
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
    num, _, den = str(value).partition("/")
    try:
        den_f = float(den)
        return float(num) / den_f if den_f else None
    except ValueError:
        return None


# seq=7 condition 3 (Roger 2026-09-13, E02+): a no-dialogue static hold longer than 2.0 s is a
# REJECT, not the D-18 advisory.  E01 keeps D-18 (delivered under the old rules).
PACING_POLICY_DEFAULT = {"static_hold_seconds_max": 2.0, "static_hold_motion_max": 1.5, "static_hold_reject": True,
                         "authority": "SUPERVISOR_ORDERS seq=7 PACING_E02_PLUS"}
PACING_POLICY_BY_EPISODE = {"E01": {"static_hold_seconds_max": 4.0, "static_hold_motion_max": 1.5,
                                    "static_hold_reject": False, "authority": "D-18 advisory (E01 as delivered)"}}


def pacing_policy(episode: str) -> dict[str, Any]:
    return dict(PACING_POLICY_BY_EPISODE.get(episode) or PACING_POLICY_DEFAULT)


def technical_checks(unit_id: str, media: Path, planned_duration: float | None,
                     out_dir: Path, designed_shot_count: int = 1,
                     pacing: dict[str, Any] | None = None,
                     asr_segments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The 12 allowed technical checks, each from a real measurement.

    asr_segments — the unit's measured speech segments (dialogue_check runs FIRST in measure()
    and hands them over, nalu D-28); static_hold_stats then knows which holds carry dialogue
    instead of treating every unit as silent (has_speech was always False before)."""
    checks: dict[str, dict[str, Any]] = {}
    supporting: dict[str, Any] = {}

    def record(name: str, status: str, **detail: Any) -> None:
        checks[name] = {"check": name, "status": status, **detail}

    if not media.is_file():
        for name in ALLOWED_TECHNICAL:
            record(name, "FAIL", reason=f"MEDIA_MISSING:{media}")
        return {"checks": checks, "supporting": supporting,
                "status": "FAIL", "failures": [f"MEDIA_MISSING:{media}"]}

    probe = ffprobe(media)
    if not probe.get("ok"):
        for name in ALLOWED_TECHNICAL:
            record(name, "FAIL", reason="DECODE_FAILED")
        record("decode", "FAIL", reason=probe.get("error"))
        return {"checks": checks, "supporting": {"ffprobe": probe},
                "status": "FAIL", "failures": ["DECODE_FAILED"]}

    streams = probe.get("streams") or []
    video = next((row for row in streams if row.get("codec_type") == "video"), None)
    audio = next((row for row in streams if row.get("codec_type") == "audio"), None)
    fmt = probe.get("format") or {}
    duration = float(fmt.get("duration") or 0.0)

    record("decode", "PASS", ffprobe_exit=0, stream_count=len(streams))
    record("corruption", "PASS" if video and duration > 0 else "FAIL",
           reason=None if video and duration > 0 else "NO_DECODABLE_VIDEO_STREAM",
           format_name=fmt.get("format_name"), size_bytes=fmt.get("size"))

    if planned_duration is None:
        record("duration", "PASS", measured_seconds=round(duration, 3),
               planned_seconds=None, note="no planned duration declared for this unit")
    else:
        delta = abs(duration - float(planned_duration))
        record("duration", "PASS" if delta <= DURATION_TOLERANCE_SECONDS else "FAIL",
               measured_seconds=round(duration, 3),
               planned_seconds=float(planned_duration),
               delta_seconds=round(delta, 3), tolerance_seconds=DURATION_TOLERANCE_SECONDS)

    width = int(video.get("width") or 0) if video else 0
    height = int(video.get("height") or 0) if video else 0
    record("resolution", "PASS" if (width, height) == (TARGET["width"], TARGET["height"])
           else "FAIL", measured=f"{width}x{height}",
           expected=f"{TARGET['width']}x{TARGET['height']}")
    ratio = (width / height) if height else 0.0
    expected_ratio = TARGET["width"] / TARGET["height"]
    record("aspect_ratio", "PASS" if abs(ratio - expected_ratio) < 0.01 else "FAIL",
           measured=round(ratio, 5), expected=TARGET["aspect_ratio"],
           expected_ratio=round(expected_ratio, 5))
    v_codec = str((video or {}).get("codec_name") or "")
    record("codec", "PASS" if v_codec in TARGET["video_codec"] else "FAIL",
           video_codec=v_codec, audio_codec=(audio or {}).get("codec_name"),
           accepted=sorted(TARGET["video_codec"]))
    record("audio_stream", "PASS" if audio else "FAIL",
           channels=(audio or {}).get("channels"),
           codec=(audio or {}).get("codec_name"),
           reason=None if audio else "AUDIO_STREAM_MISSING")
    sample_rate = int((audio or {}).get("sample_rate") or 0)
    # nalu D-18 (2026-09-13): Giggle SD2 delivers 44.1 kHz AAC on every unit (27/27 measured);
    # the 48 kHz target is the ASSEMBLY deliverable and S7 resamples.  Accepting the
    # provider-native rate here is a policy decision, the measurement stays verbatim.
    record("sample_rate", "PASS" if sample_rate in ACCEPTED_UNIT_SAMPLE_RATES else "FAIL",
           measured_hz=sample_rate, expected_hz=TARGET["audio_sample_rate"],
           accepted_unit_hz=sorted(ACCEPTED_UNIT_SAMPLE_RATES),
           assembly_resample_target_hz=TARGET["audio_sample_rate"])
    fps = _fraction((video or {}).get("avg_frame_rate")) or 0.0
    record("frame_rate", "PASS" if fps > 0 else "FAIL", measured_fps=round(fps, 4),
           r_frame_rate=(video or {}).get("r_frame_rate"))
    a_duration = float((audio or {}).get("duration") or 0.0) if audio else 0.0
    v_duration = float((video or {}).get("duration") or duration) if video else 0.0
    drift = abs(a_duration - v_duration) if (a_duration and v_duration) else 0.0
    record("av_sync", "PASS" if audio and drift <= AV_SYNC_TOLERANCE_SECONDS else "FAIL",
           audio_seconds=round(a_duration, 3), video_seconds=round(v_duration, 3),
           drift_seconds=round(drift, 3), tolerance_seconds=AV_SYNC_TOLERANCE_SECONDS,
           reason=None if audio else "AUDIO_STREAM_MISSING")

    # black_frame + freeze — the engine's own library functions
    try:
        ci = engine_module("run_regression_ci")
        black = ci.pure_black_frame_stats(FFMPEG, media)
        record("black_frame", black.get("status", "FAIL"),
               frames=black.get("frames"), policy=black.get("policy"),
               failures=black.get("failures"))
        metadata = out_dir / f"{unit_id}_motion.txt"
        metadata.parent.mkdir(parents=True, exist_ok=True)
        motion = ci.adjacent_motion_values(FFMPEG, media, metadata)
        thresholds = getattr(ci, "FROZEN_THRESHOLDS", {})
        freeze = ci.freeze_stats(motion, fps or 24.0,
                                float(thresholds.get("freeze_motion", 0.15)),
                                float(thresholds.get("min_freeze_seconds", 1.5)),
                                duration)
        cuts = ci.scene_cut_times(FFMPEG, media)
        pacing = dict(pacing or PACING_POLICY_DEFAULT)
        asr_payload = {"segments": [seg for seg in (asr_segments or []) if isinstance(seg, dict)]} \
            if asr_segments else None
        static = ci.static_hold_stats(motion, fps or 24.0, cuts, duration, asr_payload,
                                      float(pacing.get("static_hold_motion_max", thresholds.get("static_hold_motion_max", 1.5))),
                                      float(pacing.get("static_hold_seconds_max", thresholds.get("static_hold_seconds_max", 4.0))))
        frozen_runs = freeze.get("frozen_runs") or []
        # nalu D-18: static_hold_stats (run_regression_ci) rates every cut-segment of an
        # ASSEMBLED episode; a single continuous 4-10 s provider unit is one segment and a calm
        # night shot (mean adjacent-frame motion 0.4-1.5) trips "unmotivated_static_hold"
        # although nothing is frozen (frozen_runs empty).  True freezes still FAIL; a
        # static-hold-only finding is an advisory that the basic-plot review must confirm the
        # beat actually happens (major_event_presence).
        # a provider unit's internal cuts are its own designed editorial shots (each a
        # continuous take); the assembled-episode static-hold rule is advisory for them too
        static_only = (not frozen_runs and static.get("status") != "PASS"
                       and len(cuts) + 1 <= max(int(designed_shot_count or 1), 1)
                       and not bool(pacing.get("static_hold_reject")))
        record("freeze", "PASS" if not frozen_runs and (static.get("status") == "PASS" or static_only)
               else "FAIL",
               static_hold_advisory=("SINGLE_SHOT_STATIC_HOLD_ADVISORY_CONFIRM_BEAT_IN_PLOT_REVIEW"
                                     if static_only else None),
               frozen_runs=frozen_runs,
               frozen_total_seconds=freeze.get("frozen_total_seconds"),
               freeze_motion_threshold=freeze.get("freeze_motion_threshold"),
               min_freeze_seconds=freeze.get("min_freeze_seconds"),
               static_hold_status=static.get("status"),
               static_hold_failures=static.get("failures"),
               pacing_policy=pacing)
        supporting["freeze_stats"] = freeze
        supporting["static_hold_stats"] = static
        supporting["static_hold_speech_segments"] = len((asr_payload or {}).get("segments") or [])
        supporting["scene_cut_count"] = len(cuts)
    except Exception as exc:  # noqa: BLE001 — an unmeasurable check is a FAIL
        record("black_frame", "FAIL", reason=f"MEASURER_ERROR:{type(exc).__name__}:{exc}")
        record("freeze", "FAIL", reason=f"MEASURER_ERROR:{type(exc).__name__}:{exc}")

    # supporting-only measurers (never surfaced as a check name)
    cadence_out = out_dir / f"{unit_id}_frame_cadence_audit.json"
    cadence = _run([VENV, ENGINE / "tools/frame_cadence_audit.py", "--video", media,
                    "--out", cadence_out, "--ffmpeg", FFMPEG,
                    "--audit-scope", "VIDEO_ONLY_DIAGNOSTIC"])
    cadence_report = read_json(cadence_out, {}) or {}
    supporting["frame_cadence_audit"] = {
        "exit_code": cadence.returncode, "report": str(cadence_out),
        "status": cadence_report.get("status"),
        "failures": cadence_report.get("failures"),
    }
    brightness_out = out_dir / f"{unit_id}_source_brightness_jump_audit.json"
    brightness = _run([VENV, ENGINE / "tools/source_brightness_jump_audit.py",
                       "--video", media, "--ffmpeg", FFMPEG, "--out", brightness_out])
    brightness_report = read_json(brightness_out, {}) or {}
    supporting["source_brightness_jump_audit"] = {
        "exit_code": brightness.returncode, "report": str(brightness_out),
        "status": brightness_report.get("status"),
        "max_adjacent_jump": brightness_report.get("max_adjacent_jump"),
    }
    if supporting["frame_cadence_audit"]["status"] == "FAIL":
        # nalu D-18: the engine runs this audit as VIDEO_ONLY_DIAGNOSTIC; a periodic duplicate
        # cadence in a provider clip is recorded as an advisory (P2, judder) on the frame_rate
        # check, not promoted to a technical FAIL.
        checks["frame_rate"]["cadence_advisory"] = supporting["frame_cadence_audit"]["failures"]
        checks["frame_rate"]["cadence_severity"] = "P2_ADVISORY"
    if supporting["source_brightness_jump_audit"]["status"] not in (None, "PASS"):
        checks["black_frame"].setdefault("supporting_failures", []).append(
            f"SOURCE_BRIGHTNESS_JUMP:{supporting['source_brightness_jump_audit']['status']}")

    failures = [f"{name}:{row.get('reason') or row['status']}"
                for name, row in checks.items() if row["status"] != "PASS"]
    return {"checks": checks, "supporting": supporting,
            "status": "PASS" if not failures else "FAIL", "failures": failures,
            "ffprobe": {"format": fmt, "video": video, "audio": audio}}


# --------------------------------------------------------------------------- #
# ASR dialogue presence, with homophones recorded and never rejected
# --------------------------------------------------------------------------- #
def _pinyin(text: str) -> list[str]:
    from pypinyin import Style, lazy_pinyin
    return lazy_pinyin(text, style=Style.NORMAL, errors="ignore")


def adjudicate_homophones(expected: str, transcript: str,
                          variants: dict[str, str]) -> dict[str, Any]:
    """Decide whether a divergence is only a homophone / orthographic variant.

    Recorded, never rejected — the policy's central rule.
    """
    def normalise(text: str) -> str:
        for source, target in (variants or {}).items():
            text = text.replace(source, target)
        return "".join(ch for ch in text if "一" <= ch <= "鿿")

    exp_n, got_n = normalise(expected), normalise(transcript)
    if not exp_n:
        return {"applicable": False}
    if exp_n in got_n:
        return {"applicable": True, "type": "EXACT_AFTER_ORTHOGRAPHIC_NORMALISATION",
                "homophone_only": True, "confidence": 1.0}
    exp_p, got_p = _pinyin(exp_n), _pinyin(got_n)
    if not exp_p:
        return {"applicable": False}
    joined = "".join(got_p)
    homophone_only = "".join(exp_p) in joined
    matched = sum(1 for syllable in exp_p if syllable in got_p)
    return {
        "applicable": True,
        "type": "HOMOPHONE_OR_SCRIPT_VARIANT",
        "homophone_only": homophone_only,
        "pinyin_recall": round(matched / len(exp_p), 4),
        "expected_pinyin": exp_p,
        "observed_pinyin_contains_expected": homophone_only,
        "confidence": 1.0 if homophone_only else round(matched / len(exp_p), 4),
        "rule": "recorded, never a rejection cause "
                "(BASIC_DIALOGUE_QA_POLICY.homophone_handling)",
    }



_OPENCC = None
_OPENCC_LOCK = threading.Lock()


def _t2s(text: str) -> str:
    global _OPENCC
    try:
        with _OPENCC_LOCK:
            if _OPENCC is None:
                import opencc  # type: ignore
                _OPENCC = opencc.OpenCC("t2s")
            return _OPENCC.convert(text)
    except Exception:  # noqa: BLE001
        return text


#: ASR is strictly serialised: one faster-whisper process/model at a time.  Measured with
#: four concurrent whisper subprocesses on the 8-core box: the summed ASR time rose from
#: 88 s to 200 s (no gain, ctranslate2 already uses every core) and one subprocess hit the
#: known ctranslate2/libomp exit-time abort (recursive_mutex lock failed, exit -6, report
#: already written) — a recorded gate_exit_code that must not vary run to run.
_ASR_LOCK = threading.RLock()
_WHISPER = None


def _whisper_model_locked():
    """The in-process faster-whisper model, loaded once.  Call with _ASR_LOCK held; the
    model is used from that lock only (the transcribe generator does its work on iteration)."""
    global _WHISPER
    if _WHISPER is None:
        from faster_whisper import WhisperModel  # type: ignore
        _WHISPER = WhisperModel("small", device="cpu", compute_type="int8")
    return _WHISPER


def _has_chinese(value: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in value)


def _verify_no_speech(media: Path) -> dict[str, Any]:
    """Second faster-whisper pass exposing per-segment no_speech_prob / avg_logprob."""
    try:
        rows = []
        with _ASR_LOCK:
            model = _whisper_model_locked()
            segments, _info = model.transcribe(str(media), language="zh", beam_size=5, vad_filter=True)
            for seg in segments:
                text = seg.text.strip()
                hallucination = any(pat.lower() in text.lower() for pat in ASR_HALLUCINATION_PATTERNS)
                rows.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": text,
                             "no_speech_prob": round(float(seg.no_speech_prob), 3),
                             "avg_logprob": round(float(seg.avg_logprob), 3),
                             "known_hallucination_pattern": hallucination})
        real = [r for r in rows if not r["known_hallucination_pattern"]
                and r["no_speech_prob"] < 0.5 and r["avg_logprob"] > -1.0
                and any("一" <= ch <= "鿿" for ch in r["text"])]
        return {"type": "ASR_NO_SPEECH_VERIFICATION", "segments": rows, "real_speech_segments": real,
                "rule": "known whisper boilerplate on non-speech audio, or no_speech_prob>=0.5, or "
                        "avg_logprob<=-1.0 is not Mandarin dialogue"}
    except Exception as exc:  # noqa: BLE001
        return {"type": "ASR_NO_SPEECH_VERIFICATION", "error": f"{type(exc).__name__}: {exc}",
                "real_speech_segments": None}


def _measure_tail(media: Path, segments: list[dict[str, Any]]) -> dict[str, Any]:
    """RMS of the final 120 ms versus the last speech segment's RMS (ffmpeg astats)."""
    import re as _re
    def rms(start: float, dur: float) -> float | None:
        proc = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-ss", f"{max(start, 0):.3f}", "-t", f"{dur:.3f}",
                               "-i", str(media), "-vn", "-af", "astats=measure_overall=RMS_level:measure_perchannel=none",
                               "-f", "null", "-"], capture_output=True, text=True, check=False)
        m = _re.findall(r"RMS level dB:\s*(-?[0-9.]+|-inf)", proc.stderr)
        if not m:
            return None
        value = m[-1]
        return -120.0 if value == "-inf" else float(value)
    try:
        probe = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(media)],
                               capture_output=True, text=True, check=False)
        duration = float(probe.stdout.strip() or 0)
    except Exception:  # noqa: BLE001
        duration = 0.0
    last = segments[-1] if segments else {}
    seg_start = float(last.get("start") or 0.0)
    seg_end = min(float(last.get("end") or duration), duration)
    speech_db = rms(seg_start, max(seg_end - seg_start - 0.12, 0.2))
    tail_db = rms(max(duration - 0.12, 0.0), 0.12)
    if speech_db is None or tail_db is None:
        return {"type": "DIALOGUE_TAIL_MEASUREMENT", "status": "UNMEASURABLE"}
    drop = speech_db - tail_db
    status = "TAIL_DECAYED_NOT_CLIPPED" if drop >= 6.0 else "TAIL_STILL_AT_SPEECH_LEVEL_POSSIBLY_CLIPPED"
    return {"type": "DIALOGUE_TAIL_MEASUREMENT", "status": status, "duration_seconds": round(duration, 3),
            "last_segment": last, "speech_rms_db": speech_db, "final_120ms_rms_db": tail_db,
            "drop_db": round(drop, 2), "rule": "final 120 ms at least 6 dB below the last speech segment = decayed"}

def _reverify_dialogue(media: Path, expected_texts: list[str]) -> dict[str, Any]:
    """In-process faster-whisper (small, int8) with vad_filter + beam 1; character recall of the
    expected spoken text after t2s normalisation.  Never rejects on its own — only rescues a
    recall miss whose gate transcript was known hallucination boilerplate."""
    import re as _re
    try:
        with _ASR_LOCK:
            model = _whisper_model_locked()
            segments, _info = model.transcribe(str(media), language="zh", beam_size=1, vad_filter=True)
            rows = [{"start": round(float(seg.start), 2), "end": round(float(seg.end), 2), "text": _t2s(str(seg.text).strip())}
                    for seg in segments]
    except Exception as exc:  # noqa: BLE001
        return {"status": "REVERIFY_FAILED", "error": f"{type(exc).__name__}: {exc}", "recall": None}
    transcript = "".join(r["text"] for r in rows)
    if any(pat.lower() in transcript.lower() for pat in ASR_HALLUCINATION_PATTERNS):
        return {"status": "STILL_HALLUCINATION", "transcript": transcript, "segments": rows, "recall": 0.0}
    clean = lambda t: _re.sub(r"[^\u4e00-\u9fff0-9a-zA-Z]", "", _t2s(str(t)))
    exp = clean("".join(expected_texts)); got = clean(transcript)
    if not exp:
        return {"status": "NO_EXPECTED_TEXT", "transcript": transcript, "segments": rows, "recall": None}
    from collections import Counter
    ce, cg = Counter(exp), Counter(got)
    hit = sum(min(n, cg.get(ch, 0)) for ch, n in ce.items())
    recall = round(hit / max(1, len(exp)), 3)
    return {"status": "REVERIFIED", "method": "faster-whisper small int8, language=zh, beam_size=1, vad_filter=True; character recall after t2s",
            "transcript": transcript, "segments": rows, "recall": recall}


def dialogue_check(unit_id: str, media: Path, expected_dialogue: list[dict[str, Any]],
                   out_dir: Path) -> dict[str, Any]:
    policy = read_json(DIALOGUE_QA_POLICY, {}) or {}
    rules = policy.get("rules") or {}
    asr = policy.get("asr") or {}
    minimum_recall = float(rules.get("minimum_recall", 0.55))
    variants = (policy.get("homophone_handling") or {}).get("orthographic_variants") or {}
    out_dir.mkdir(parents=True, exist_ok=True)
    dialogue_json = out_dir / f"{unit_id}_dialogue_contract.json"
    # the plot expectations carry "speaker：text"; only the spoken text is a recall target
    # (2026-09-13: "秦铭：陆哥。" vs transcript "陆哥" scored 0.5 and rejected E01-VU-011)
    def spoken_only(value: Any) -> str:
        text = str(value or "")
        return text.split("：", 1)[1] if "：" in text[:8] else text
    write_json(dialogue_json, {"dialogue": [
        {"dia_id": f"{row.get('shot_id')}-D-{index}", "spoken_text": spoken_only(row.get("spoken_text"))}
        for index, row in enumerate(expected_dialogue, 1)]})
    report = out_dir / f"{unit_id}_source_video_dialogue_gate.json"
    argv = [VENV, ENGINE / "tools/source_video_dialogue_gate.py",
            "--video", media, "--dialogue-json", dialogue_json, "--out", report,
            "--minimum-recall", minimum_recall, "--ffprobe", FFPROBE]
    if asr.get("model"):
        argv += ["--model", asr["model"]]
    if not expected_dialogue:
        argv += ["--require-no-dialogue"]
    with _ASR_LOCK:
        completed = _run(argv, timeout=3600)
    payload = read_json(report, {}) or {}
    failures = list(payload.get("failures") or [])
    adjudications: list[dict[str, Any]] = []
    machine_adjudications: list[dict[str, Any]] = []
    # nalu D-18a: whisper emits traditional characters at times (陸哥 / 讓我看一看); an
    # orthographic variant is RECORDED, never rejected (policy) — normalise t2s first.
    t2s = _t2s(str(payload.get("transcript") or ""))
    if t2s != str(payload.get("transcript") or ""):
        payload["transcript_t2s"] = t2s
        machine_adjudications.append({"type": "ORTHOGRAPHIC_VARIANT_TRADITIONAL_TO_SIMPLIFIED",
                                      "original": payload.get("transcript"), "normalised": t2s})
        payload["transcript"] = t2s
    # nalu D-18b: a "no dialogue" unit whose only transcript is a known whisper hallucination
    # on non-speech audio is re-verified with a second faster-whisper pass that exposes
    # no_speech_prob / avg_logprob per segment; only real speech keeps the failure.
    if not expected_dialogue and "unexpected_native_mandarin_speech_present" in failures:
        verify = _verify_no_speech(media)
        machine_adjudications.append(verify)
        if verify.get("real_speech_segments") == []:
            failures = [v for v in failures if v != "unexpected_native_mandarin_speech_present"]
    # nalu D-18d (E04 VU-012): the engine gate primes whisper with initial_prompt=<expected text>;
    # on some clips that primed decode degenerates to a single replacement char ("\ufffd") and the
    # gate reports native_mandarin_speech_missing although the line is spoken.  Re-verify with an
    # UNPRIMED pass (same model, vad on); the failure is cleared only when the expected line is
    # actually recalled (>= minimum_recall) and every segment is real speech.
    if expected_dialogue and "native_mandarin_speech_missing" in failures \
            and not _has_chinese(str(payload.get("transcript") or "")):
        verify = _verify_no_speech(media)
        gate = engine_module("source_video_dialogue_gate")
        expected_join = "".join(spoken_only(row.get("spoken_text")) for row in expected_dialogue)
        second = "".join(r["text"] for r in (verify.get("segments") or []))
        second_recall = gate.recall(expected_join, _t2s(second)) if second else 0.0
        verify = dict(verify, type="ASR_DEGENERATE_PRIMED_DECODE_REVERIFIED",
                      primed_transcript=payload.get("transcript"), unprimed_transcript=second,
                      unprimed_recall=round(second_recall, 3), minimum_recall=minimum_recall,
                      rule="primed decode returned no Chinese; an unprimed pass that recalls the expected "
                           "line at >= minimum_recall with real-speech segments only proves the line is spoken")
        machine_adjudications.append(verify)
        if second and second_recall >= minimum_recall and verify.get("real_speech_segments") \
                and len(verify["real_speech_segments"]) == len(verify.get("segments") or []):
            failures = [v for v in failures if v != "native_mandarin_speech_missing"]
            payload["transcript_unprimed"] = second
    # nalu D-18c: "tail clipped or unverified" is VERIFIED by measuring the audio envelope of
    # the last 120 ms against the last speech segment; a decayed tail is not clipped.
    if "dialogue_tail_clipped_or_unverified" in failures:
        tail = _measure_tail(media, payload.get("segments") or [])
        machine_adjudications.append(tail)
        if tail.get("status") == "TAIL_DECAYED_NOT_CLIPPED":
            failures = [v for v in failures if v != "dialogue_tail_clipped_or_unverified"]
    if expected_dialogue and payload:
        transcript = str(payload.get("transcript") or "")
        for row in expected_dialogue:
            verdict = adjudicate_homophones(spoken_only(row.get("spoken_text")),
                                            transcript, variants)
            verdict["shot_id"] = row.get("shot_id")
            verdict["expected"] = row.get("spoken_text")
            adjudications.append(verdict)
        # a recall miss that is only a homophone/script variant is recorded, not rejected
        if all(row.get("homophone_only") for row in adjudications if row.get("applicable")) \
                and adjudications:
            failures = [value for value in failures
                        if not str(value).startswith("dialogue_recall_below_threshold")]
    # nalu D-28 (2026-09-14): the engine gate's whisper pass can emit a known boilerplate
    # hallucination ("优优独播剧场 / YoYo Television Series Exclusive") or a stray name on real
    # dialogue audio.  When recall failed AND the transcript is such boilerplate (or empty),
    # re-transcribe in-process with VAD + greedy decoding (the parameters that recovered the
    # lines by hand) and re-score character recall against the expected spoken text.
    recall_failed = any(str(v).startswith("dialogue_recall_below_threshold") for v in failures)
    transcript_now = str(payload.get("transcript") or "")
    boilerplate = (not transcript_now.strip()) or any(pat.lower() in transcript_now.lower() for pat in ASR_HALLUCINATION_PATTERNS)
    # (2026-09-14, E02-VU-024) a stray name ("陆泽") in place of a 4-character line is the same
    # decoding failure without the boilerplate signature — every recall miss gets the second
    # pass; both transcripts are recorded, and only a measured recall >= minimum rescues it.
    if expected_dialogue and recall_failed:
        payload["transcript_gate_pass"] = transcript_now
        payload["gate_transcript_was_hallucination_boilerplate"] = boilerplate
        rv = _reverify_dialogue(media, [spoken_only(r.get("spoken_text")) for r in expected_dialogue])
        machine_adjudications.append({"type": "ASR_HALLUCINATION_REVERIFIED_WITH_VAD", **rv})
        if rv.get("recall") is not None and rv["recall"] >= minimum_recall:
            failures = [v for v in failures if not str(v).startswith("dialogue_recall_below_threshold")]
            payload["transcript"] = rv["transcript"]
            payload["recall_score"] = rv["recall"]
            payload["segments"] = rv["segments"]
            # nalu D-28b (E04 VU-012): a hallucinating primed pass also invents segment TIMES
            # (26 s of segments on a 5 s clip), so the gate's "tail clipped" verdict was computed
            # on phantom timing (D-18c then reports UNMEASURABLE).  Re-measure the tail on the
            # reverified real-speech segments; only a measured decay clears the failure.
            if "dialogue_tail_clipped_or_unverified" in failures and rv.get("segments"):
                tail2 = _measure_tail(media, rv["segments"])
                tail2["type"] = "DIALOGUE_TAIL_REMEASURED_ON_REVERIFIED_SEGMENTS"
                machine_adjudications.append(tail2)
                if tail2.get("status") == "TAIL_DECAYED_NOT_CLIPPED":
                    failures = [v for v in failures if v != "dialogue_tail_clipped_or_unverified"]
    status = "PASS" if completed.returncode == 0 or not failures else "FAIL"
    return {
        "check": "major_dialogue_presence_asr_support",
        "status": status,
        "policy": str(DIALOGUE_QA_POLICY),
        "expected_line_count": len(expected_dialogue),
        "recall_score": payload.get("recall_score"),
        "minimum_recall": minimum_recall,
        "transcript": payload.get("transcript"),
        "segments": payload.get("segments"),
        "gate_exit_code": completed.returncode,
        "gate_report": str(report),
        "gate_status": payload.get("status"),
        "failures": failures,
        "machine_adjudications": machine_adjudications,
        "homophone_adjudications": adjudications,
        "homophone_rule": "RECORDED_NOT_REJECTED",
        "stderr_tail": (completed.stderr or "")[-800:],
    }


# --------------------------------------------------------------------------- #
# contact sheets for the basic-plot VLM review
# --------------------------------------------------------------------------- #
def contact_sheet(unit_id: str, media: Path, out_dir: Path,
                  fps: float = 2.0, columns: int = 6) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = out_dir / "contact_sheet_2fps.png"
    if not media.is_file():
        return {"status": "MEDIA_MISSING", "path": str(sheet), "media": str(media)}
    # ffmpeg's tile filter needs an explicit row count, so derive it from the real
    # duration: every sampled frame must land on the sheet the reviewer looks at.
    probe = ffprobe(media)
    duration = float((probe.get("format") or {}).get("duration") or 0.0) if probe.get("ok") else 0.0
    frames = max(1, int(math.ceil(duration * fps)))
    rows = max(1, int(math.ceil(frames / columns)))
    argv = [FFMPEG, "-y", "-i", str(media),
            "-vf", f"fps={fps},scale=240:-1,tile={columns}x{rows}",
            "-frames:v", "1", str(sheet)]
    completed = _run(argv, timeout=900)
    return {
        "status": "OK" if completed.returncode == 0 and sheet.is_file() else "FFMPEG_FAILED",
        "path": str(sheet), "sha256": sha256_file(sheet), "fps": fps, "columns": columns,
        "rows": rows, "sampled_frames": frames, "duration_seconds": round(duration, 3),
        "exit_code": completed.returncode, "stderr_tail": (completed.stderr or "")[-600:],
        "argv": [str(item) for item in argv],
    }


# --------------------------------------------------------------------------- #
# reroll requests in the shape tools/reroll_cost_guard.py consumes
# --------------------------------------------------------------------------- #
def build_reroll_requests(episode: str, rejected: list[dict[str, Any]],
                          total_paid_tasks: int) -> dict[str, Any]:
    p = QaPaths(episode)
    ledger = read_json(p.reroll_ledger, {"schema": "nalu.reroll_ledger.v1",
                                         "episode": episode, "events": []})
    events = ledger.setdefault("events", [])
    requests: list[dict[str, Any]] = []
    for row in rejected:
        unit_id = row["unit_id"]
        reason = row["primary_reason"]
        prior = sum(1 for event in events
                    if event.get("shot_id") == unit_id
                    and str(event.get("outcome")) in {"SUBMITTED", "COMPLETED"})
        reroll_number = prior + 1
        out = p.qa_root / "reroll" / f"{unit_id}_reroll_cost_guard.json"
        argv = [str(VENV), str(ENGINE / "tools/reroll_cost_guard.py"),
                "--policy", str(REROLL_POLICY), "--ledger", str(p.reroll_ledger),
                "--shot-id", unit_id, "--reroll-number", str(reroll_number),
                "--failure-tier", "BLOCK",
                "--failure-reason", reason,
                "--failure-class", row.get("failure_class", "CANDIDATE_QA_FAILURE"),
                "--total-paid-tasks", str(total_paid_tasks),
                "--out", str(out)]
        requests.append({
            "shot_id": unit_id,
            "unit_id": unit_id,
            "reroll_number": reroll_number,
            "failure_tier": "BLOCK",
            "failure_reason": reason,
            "failure_class": row.get("failure_class", "CANDIDATE_QA_FAILURE"),
            "total_paid_tasks": total_paid_tasks,
            "all_reasons": row.get("reasons") or [],
            "guard_argv": argv,
            "guard_command": " ".join(argv),
            "guard_out": str(out),
            "policy": str(REROLL_POLICY),
            "rule": "a reroll runs only on a PASS_* status from this guard AND a fresh "
                    "nalu_budget_ledger.py --check inside the 8000-credit cap",
        })
    payload = {
        "schema": "nalu.reroll_request_list.v1",
        "episode": episode,
        "recorded_at": now(),
        "recorded_by": TOOL_ID,
        "gate_id": "GIGGLE-REROLL-COST-GUARD",
        "guard": str(ENGINE / "tools/reroll_cost_guard.py"),
        "policy": str(REROLL_POLICY),
        "ledger": str(p.reroll_ledger),
        "total_paid_tasks": total_paid_tasks,
        "request_count": len(requests),
        "requests": requests,
    }
    write_json(p.reroll_requests, payload)
    write_json(p.reroll_ledger, ledger)
    return payload


# --------------------------------------------------------------------------- #
# the runner
# --------------------------------------------------------------------------- #
def run_scope_gate(episode: str, out: Path) -> dict[str, Any]:
    argv = [VENV, ENGINE / "tools/post_generation_qa_scope_gate.py",
            "--episode", episode, "--out", out]
    for check in (*ALLOWED_TECHNICAL, *ALLOWED_BASIC_PLOT):
        argv += ["--check", check]
    completed = _run(argv, timeout=300)
    return {"exit_code": completed.returncode, "report": str(out),
            "status": (read_json(out, {}) or {}).get("status"),
            "stdout": (completed.stdout or "").strip()[-800:]}


def unit_media(episode: str, unit_id: str) -> Path:
    p = QaPaths(episode)
    for candidate in (p.video_media / f"{unit_id}.mp4",
                      p.video_media / f"{episode}-{unit_id}.mp4"):
        if candidate.is_file():
            return candidate
    matches = sorted(p.video_media.glob(f"*{unit_id}*.mp4")) if p.video_media.is_dir() else []
    return matches[0] if matches else p.video_media / f"{unit_id}.mp4"


def run(episode: str, *, review_path: Path | None = None,
        units: list[str] | None = None) -> dict[str, Any]:
    p = QaPaths(episode)
    exp = Expectations(episode)
    plot_items = {row["unit_id"]: row for row in exp.unit_plot_items()}
    wanted = [uid for uid in sorted(plot_items) if not units or uid in set(units)]

    scope = run_scope_gate(episode, p.postgen_dir / f"{episode}_POST_GENERATION_QA_SCOPE.json")

    plot_by_unit: dict[str, dict[str, Any]] = {}
    submitted = read_json(review_path) if review_path else None
    if submitted:
        if submitted.get("kind") != "post_gen_plot":
            raise SystemExit(f"not a post_gen_plot review: {review_path}")
        if (submitted.get("validation") or {}).get("status") != "PASS":
            raise SystemExit(f"review did not validate: {review_path}")
        for item in submitted.get("items") or []:
            plot_by_unit[item["item_id"]] = item

    def measure(unit_id: str) -> dict[str, Any]:
        """The three free measurers of ONE unit — independent of every other unit."""
        item = plot_items[unit_id]
        expectations = item["expectations"]
        media = unit_media(episode, unit_id)
        out_dir = p.postgen_dir / unit_id
        out_dir.mkdir(parents=True, exist_ok=True)
        # nalu D-28: dialogue first — its speech segments make the static-hold measurement
        # speech-aware (a held frame under a spoken line is not an unmotivated static hold).
        dialogue = dialogue_check(unit_id, media,
                                  expectations.get("expected_dialogue") or [], out_dir)
        technical = technical_checks(unit_id, media,
                                     expectations.get("duration_seconds"), out_dir,
                                     designed_shot_count=len(expectations.get("editorial_shot_ids") or []) or 1,
                                     pacing=pacing_policy(episode),
                                     asr_segments=dialogue.get("segments") or None)
        sheet = contact_sheet(unit_id, media, out_dir)
        return {"media": media, "media_sha256": sha256_file(media),
                "technical": technical, "dialogue": dialogue, "sheet": sheet}

    try:
        engine_module("run_regression_ci")   # import once, before the pool
    except Exception:  # noqa: BLE001 — technical_checks records the failure per unit
        pass
    measured = parallel_map(measure, wanted)
    review_sha = sha256_file(review_path) if review_path else None

    rows: list[dict[str, Any]] = []
    for unit_id in wanted:
        media = measured[unit_id]["media"]
        media_sha = measured[unit_id]["media_sha256"]
        technical = measured[unit_id]["technical"]
        dialogue = measured[unit_id]["dialogue"]
        sheet = measured[unit_id]["sheet"]
        out_dir = p.postgen_dir / unit_id

        plot = plot_by_unit.get(unit_id)
        plot_checks: dict[str, Any] = {}
        plot_failures: list[str] = []
        if plot is None:
            for name in ALLOWED_BASIC_PLOT:
                plot_checks[name] = {"check": name, "status": "REVIEW_REQUIRED"}
            plot_failures.append("BASIC_PLOT_VLM_REVIEW_REQUIRED")
        else:
            answers = plot.get("answers") or {}
            for name in ALLOWED_BASIC_PLOT:
                answer = str(answers.get(name) or "MISSING")
                ok = answer in {"PASS", "NOT_APPLICABLE"}
                plot_checks[name] = {
                    "check": name, "status": "PASS" if ok else "FAIL",
                    "reviewer_answer": answer, "reviewer": REVIEWER_ID,
                    "review_method": REVIEW_METHOD}
                if not ok:
                    plot_failures.append(f"{name}:{answer}")
            for defect in plot.get("defects") or []:
                if str(defect.get("severity")) in {"P0", "P1"}:
                    plot_failures.append(f"PLOT_DEFECT_{defect.get('severity')}:"
                                         f"{defect.get('code')}")

        reasons = list(technical["failures"])
        if dialogue["status"] != "PASS":
            reasons.extend(f"dialogue:{value}" for value in dialogue["failures"])
        reasons.extend(plot_failures)
        verdict = "ADMIT" if not reasons else "REJECT"
        failure_class = ("CANDIDATE_TECHNICAL_FAILURE" if technical["failures"]
                         else "CANDIDATE_QA_FAILURE")

        record = {
            "schema": "nalu.post_generation_unit_qa.v1",
            "episode": episode, "unit_id": unit_id,
            "media_path": str(media), "media_sha256": media_sha,
            "verdict": verdict,
            "reasons": reasons,
            "primary_reason": reasons[0] if reasons else None,
            "failure_class": failure_class,
            "technical_qa": {
                # the honest status name the Q2 admission gate demands of a video:
                # technical measurement is never a content pass.
                "status": ("TECHNICAL_PASS_CONTENT_UNREVIEWED"
                           if technical["status"] == "PASS" else "TECHNICAL_FAIL"),
                "reviewed_asset_sha256": media_sha,
                "measured_by": TOOL_ID,
                "allowed_scope": "TECHNICAL_AND_BASIC_PLOT_ONLY",
                "checks": technical["checks"],
                "supporting_measurements": technical["supporting"],
                "failures": technical["failures"],
            },
            "dialogue_qa": dialogue,
            "basic_plot_qa": {
                "checks": plot_checks, "failures": plot_failures,
                "reviewer": REVIEWER_ID if plot else None,
                "review_method": REVIEW_METHOD if plot else None,
                "review_file": str(review_path) if review_path else None,
                "review_file_sha256": review_sha,
                "contact_sheet": sheet,
                "observation": (plot or {}).get("observation"),
                "defects": (plot or {}).get("defects") or [],
            },
            "recorded_at": now(), "recorded_by": TOOL_ID,
        }
        write_json(out_dir / f"{unit_id}_POST_GENERATION_QA.json", record)
        rows.append(record)

    # episode-level boundary acceptance across the downloaded units
    boundary = run_media_boundary(episode, rows)

    rejected = [{"unit_id": row["unit_id"], "primary_reason": row["primary_reason"],
                 "reasons": row["reasons"], "failure_class": row["failure_class"]}
                for row in rows if row["verdict"] == "REJECT"]
    rerolls = build_reroll_requests(episode, rejected, total_paid_tasks=len(plot_items))

    admitted = [row for row in rows if row["verdict"] == "ADMIT"]
    summary = {
        "schema": "nalu.post_generation_qa_summary.v1",
        "episode": episode,
        "recorded_at": now(), "recorded_by": TOOL_ID,
        "scope_gate": scope,
        "allowed_technical_checks": list(ALLOWED_TECHNICAL),
        "allowed_basic_plot_checks": list(ALLOWED_BASIC_PLOT),
        "forbidden_checks_computed": [],
        "basic_plot_review": {
            "required": True,
            "review_file": str(review_path) if review_path else None,
            "reviewer": REVIEWER_ID,
            "review_method": REVIEW_METHOD,
            "present": bool(submitted),
        },
        "media_boundary_acceptance": boundary,
        "unit_count": len(rows),
        "admitted_count": len(admitted),
        "rejected_count": len(rejected),
        "status": ("ADMIT_ALL" if rows and not rejected
                   else f"PARTIAL_{len(admitted)}_OF_{len(rows)}" if rows else "NO_UNITS"),
        "admitted_unit_ids": [row["unit_id"] for row in admitted],
        "rejected_unit_ids": [row["unit_id"] for row in rejected],
        "units": [{"unit_id": row["unit_id"], "verdict": row["verdict"],
                   "reasons": row["reasons"][:6],
                   "technical_status": row["technical_qa"]["status"],
                   "dialogue_status": row["dialogue_qa"]["status"],
                   "record": str(p.postgen_dir / row["unit_id"]
                                 / f"{row['unit_id']}_POST_GENERATION_QA.json")}
                  for row in rows],
        "reroll_requests": str(p.reroll_requests),
        "reroll_request_count": rerolls["request_count"],
    }
    out = write_json(p.postgen_dir / f"{episode}_POST_GENERATION_QA_SUMMARY.json", summary)
    summary["_written_to"] = str(out)
    return summary


def run_media_boundary(episode: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """tools/media_boundary_acceptance.py over the downloaded units."""
    p = QaPaths(episode)
    exp = Expectations(episode)
    grouped = p.preprod / f"{episode}_GROUPED_SEEDANCE_MANIFEST_V1.json"
    present = [row for row in rows if Path(row["media_path"]).is_file()]
    if not present or not grouped.is_file():
        return {"status": "NOT_RUN",
                "reason": ("NO_DOWNLOADED_MEDIA" if not present
                           else f"GROUPED_MANIFEST_MISSING:{grouped}"),
                "tool": str(ENGINE / "tools/media_boundary_acceptance.py")}
    media_map = p.postgen_dir / f"{episode}_MEDIA_MAP.json"
    units = {row["unit_id"]: row for row in exp.grouping_units.values()}
    write_json(media_map, {"schema": "qingshan.media_map.v1", "episode": episode,
                           "rows": [{"unit_id": row["unit_id"],
                                     "media_path": row["media_path"],
                                     "planned_duration_seconds":
                                         (units.get(row["unit_id"]) or {}).get("duration_seconds")}
                                    for row in present]})
    out_dir = p.postgen_dir / "media_boundary"
    completed = _run([VENV, ENGINE / "tools/media_boundary_acceptance.py",
                      "--media-map", media_map, "--grouped-manifest", grouped,
                      "--out-dir", out_dir])
    report = read_json(out_dir / "MEDIA_BOUNDARY_ACCEPTANCE_REPORT.json", {}) or {}
    return {"status": report.get("status", "NOT_RUN"), "exit_code": completed.returncode,
            "report": str(out_dir / "MEDIA_BOUNDARY_ACCEPTANCE_REPORT.json"),
            "boundary_count": report.get("boundary_count"),
            "failures": (report.get("failures") or [])[:8],
            "stderr_tail": (completed.stderr or "")[-600:]}


def materialise_plot(episode: str, submitted: dict[str, Any],
                     submitted_path: Path) -> dict[str, Any]:
    """Called by vlm_review_protocol.submit for kind=post_gen_plot."""
    return run(episode, review_path=submitted_path)


def route_status(episode: str) -> dict[str, Any]:
    p = QaPaths(episode)
    exp = Expectations(episode)
    media = sorted(p.video_media.glob("*.mp4")) if p.video_media.is_dir() else []
    try:
        __import__("faster_whisper")
        asr = True
    except Exception:  # noqa: BLE001
        asr = False
    return {
        "runner": f"{__file__} run --episode {episode} [--review <submitted review>]",
        "scope_gate": str(ENGINE / "tools/post_generation_qa_scope_gate.py"),
        "allowed_technical_checks": list(ALLOWED_TECHNICAL),
        "allowed_basic_plot_checks": list(ALLOWED_BASIC_PLOT),
        "measurers": {
            "ffprobe": FFPROBE, "ffmpeg": FFMPEG,
            "black_frame": "run_regression_ci.pure_black_frame_stats",
            "freeze": "run_regression_ci.freeze_stats + static_hold_stats",
            "frame_rate_cadence": str(ENGINE / "tools/frame_cadence_audit.py"),
            "source_brightness_jump": str(ENGINE / "tools/source_brightness_jump_audit.py"),
            "media_boundary_acceptance": str(ENGINE / "tools/media_boundary_acceptance.py"),
            "asr_dialogue": str(ENGINE / "tools/source_video_dialogue_gate.py"),
        },
        "dialogue_policy": str(DIALOGUE_QA_POLICY),
        "dialogue_policy_present": DIALOGUE_QA_POLICY.is_file(),
        "faster_whisper_available": asr,
        "ffmpeg_present": Path(FFMPEG).is_file(),
        "ffprobe_present": Path(FFPROBE).is_file(),
        "units_expected": len(exp.grouping_units),
        "unit_media_on_disk": len(media),
        "reroll_guard": str(ENGINE / "tools/reroll_cost_guard.py"),
        "reroll_policy": str(REROLL_POLICY),
        "summary": str(p.postgen_dir / f"{episode}_POST_GENERATION_QA_SUMMARY.json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("scope", "status"):
        sp = sub.add_parser(name)
        sp.add_argument("--episode", required=True)
    for name in ("contact-sheet", "technical"):
        sp = sub.add_parser(name)
        sp.add_argument("--episode", required=True)
        sp.add_argument("--unit", action="append", default=[])
    rn = sub.add_parser("run")
    rn.add_argument("--episode", required=True)
    rn.add_argument("--review", type=Path)
    rn.add_argument("--unit", action="append", default=[])
    args = parser.parse_args()

    if args.command == "status":
        print(json.dumps(route_status(args.episode), ensure_ascii=False, indent=2))
        return 0
    if args.command == "scope":
        p = QaPaths(args.episode)
        record = run_scope_gate(args.episode,
                                p.postgen_dir / f"{args.episode}_POST_GENERATION_QA_SCOPE.json")
        print(json.dumps(record, ensure_ascii=False))
        return record["exit_code"]
    if args.command == "contact-sheet":
        p = QaPaths(args.episode)
        exp = Expectations(args.episode)
        wanted = [unit_id for unit_id in sorted(exp.grouping_units)
                  if not args.unit or unit_id in set(args.unit)]
        sheets = parallel_map(lambda unit_id: contact_sheet(
            unit_id, unit_media(args.episode, unit_id), p.postgen_dir / unit_id), wanted)
        out = [{"unit_id": unit_id, **sheets[unit_id]} for unit_id in wanted]
        print(json.dumps({"sheets": out}, ensure_ascii=False, indent=2)[:4000])
        return 0
    if args.command == "technical":
        p = QaPaths(args.episode)
        exp = Expectations(args.episode)
        units = {row["unit_id"]: row for row in exp.unit_plot_items()}
        wanted = [unit_id for unit_id in sorted(units)
                  if not args.unit or unit_id in set(args.unit)]
        try:
            engine_module("run_regression_ci")   # import once, before the pool
        except Exception:  # noqa: BLE001
            pass
        measured = parallel_map(lambda unit_id: technical_checks(
            unit_id, unit_media(args.episode, unit_id),
            units[unit_id]["expectations"].get("duration_seconds"),
            p.postgen_dir / unit_id), wanted)
        out = [{"unit_id": unit_id, **measured[unit_id]} for unit_id in wanted]
        print(json.dumps({"units": [{"unit_id": row["unit_id"], "status": row["status"],
                                     "failures": row["failures"][:6]} for row in out]},
                         ensure_ascii=False, indent=2)[:4000])
        return 0

    summary = run(args.episode, review_path=args.review, units=args.unit or None)
    print(json.dumps({"status": summary["status"], "units": summary["unit_count"],
                      "admitted": summary["admitted_count"],
                      "rejected": summary["rejected_count"],
                      "rerolls": summary["reroll_request_count"],
                      "out": summary["_written_to"]}, ensure_ascii=False))
    return 0 if summary["status"] == "ADMIT_ALL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
