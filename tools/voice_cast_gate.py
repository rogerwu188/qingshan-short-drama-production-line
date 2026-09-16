#!/usr/bin/env python3
"""Character -> voice binding gate for the nalu line (report C1 / C2).

Inputs
  * ``voice_cast.json`` ``{schema: "qingshan.voice_cast.v1", characters: {character_id:
    {voice_id, f0_band_hz: [lo, hi], rate_cps_baseline, timbre_brief}}}``;
  * a per-scene co-presence list ``[[character_id, ...], ...]`` (pre-generation);
  * measured lines from ``tools/dialogue_voice_metrics.py`` carrying ``speaker`` (and
    optionally ``scene`` / ``emotion``) (post-generation).

Checks
  precheck   VOICE_ID_SHARED_IN_SCENE:<a>:<b>           -> FAIL
             F0_BAND_OVERLAP_REQUIRES_HUMAN:<a>:<b>     -> REQUIRES_HUMAN (overlap > 50 % of the narrower band)
  postcheck  VOICE_OUT_OF_BAND:<speaker>:<start>       -> FAIL (line F0 outside the character band)
             VOICE_COLLISION:<a>:<b>                    -> FAIL (two speakers in one scene, median F0 within 15 %)
  emotion    FLAT_EMOTION:<speaker>:<start>             -> FAIL (plead|fear|threat line < 6 dB above the speaker's calm baseline)
             NO_CALM_BASELINE:<speaker>                 -> UNVERIFIED (never a silent PASS)

Anything the gate cannot decide is reported under ``unverified``; the overall status is
FAIL > REQUIRES_HUMAN > UNVERIFIED > PASS.
"""

from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Sequence

CAST_SCHEMA = "qingshan.voice_cast.v1"
OUTPUT_SCHEMA = "qingshan.voice_cast_gate.v1"

BAND_HALF_WIDTH = 0.15          # build_f0_band: reference median +-15 %
OVERLAP_HUMAN_RATIO = 0.5       # precheck: overlap > 50 % of the narrower band needs a human
COLLISION_RATIO = 0.15          # postcheck: two speakers whose median F0 differ by < 15 %
EMOTION_DELTA_DB = 6.0          # plead|fear|threat must sit >= 6 dB above the calm baseline
EMOTIVE = frozenset({"plead", "fear", "threat"})
EMOTIONS = frozenset({"calm", "plead", "threat", "mock", "joy", "fear"})

STATUS_ORDER = {"PASS": 0, "UNVERIFIED": 1, "REQUIRES_HUMAN": 2, "FAIL": 3}


def _worst(statuses: Iterable[str]) -> str:
    worst = "PASS"
    for status in statuses:
        if STATUS_ORDER.get(status, 0) > STATUS_ORDER[worst]:
            worst = status
    return worst


def build_f0_band(reference_f0_median: float, half_width: float = BAND_HALF_WIDTH) -> list[float]:
    """[0.85x, 1.15x] of a measured reference-audio F0 median."""
    ref = float(reference_f0_median)
    if ref <= 0:
        raise ValueError("reference F0 must be positive")
    return [round(ref * (1.0 - half_width), 2), round(ref * (1.0 + half_width), 2)]


def band_overlap_ratio(a: Sequence[float], b: Sequence[float]) -> float:
    """Overlap of two [lo, hi] bands expressed as a fraction of the narrower band's width."""
    lo = max(float(a[0]), float(b[0]))
    hi = min(float(a[1]), float(b[1]))
    if hi <= lo:
        return 0.0
    narrower = min(float(a[1]) - float(a[0]), float(b[1]) - float(b[0]))
    if narrower <= 0:
        return 1.0
    return round((hi - lo) / narrower, 4)


def validate_cast(cast: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(cast, dict) or cast.get("schema") != CAST_SCHEMA:
        errors.append(f"CAST_SCHEMA_MISMATCH:{(cast or {}).get('schema') if isinstance(cast, dict) else None}")
        return errors
    characters = cast.get("characters")
    if not isinstance(characters, dict) or not characters:
        errors.append("CAST_EMPTY")
        return errors
    for cid, row in characters.items():
        if not isinstance(row, dict):
            errors.append(f"CAST_ROW_INVALID:{cid}")
            continue
        if not row.get("voice_id"):
            errors.append(f"CAST_VOICE_ID_MISSING:{cid}")
        band = row.get("f0_band_hz")
        if not (isinstance(band, (list, tuple)) and len(band) == 2 and all(isinstance(v, (int, float)) for v in band)
                and 0 < float(band[0]) < float(band[1])):
            errors.append(f"CAST_F0_BAND_INVALID:{cid}")
    return errors


def _characters(cast: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return dict((cast or {}).get("characters") or {})


# --------------------------------------------------------------------------- precheck

def precheck(cast: dict[str, Any], scene_copresence: Sequence[Sequence[str]]) -> dict[str, Any]:
    errors = validate_cast(cast)
    if errors:
        return {"status": "FAIL", "failures": errors, "requires_human": [], "unverified": [], "pairs": []}
    characters = _characters(cast)
    failures: list[str] = []
    requires_human: list[str] = []
    unverified: list[str] = []
    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for scene_index, scene in enumerate(scene_copresence or []):
        ids = [str(c) for c in scene]
        for cid in ids:
            if cid not in characters:
                unverified.append(f"CHARACTER_NOT_IN_CAST:{cid}:scene{scene_index}")
        present = sorted({c for c in ids if c in characters})
        for a, b in combinations(present, 2):
            key = (a, b)
            ra, rb = characters[a], characters[b]
            same_voice = str(ra.get("voice_id")) == str(rb.get("voice_id"))
            overlap = band_overlap_ratio(ra["f0_band_hz"], rb["f0_band_hz"])
            pairs.append({"scene_index": scene_index, "a": a, "b": b, "same_voice_id": same_voice,
                          "band_overlap_ratio": overlap})
            if key in seen:
                continue
            seen.add(key)
            if same_voice:
                failures.append(f"VOICE_ID_SHARED_IN_SCENE:{a}:{b}")
            if overlap > OVERLAP_HUMAN_RATIO:
                requires_human.append(f"F0_BAND_OVERLAP_REQUIRES_HUMAN:{a}:{b}")
    status = "FAIL" if failures else ("REQUIRES_HUMAN" if requires_human else ("UNVERIFIED" if unverified else "PASS"))
    return {"status": status, "failures": failures, "requires_human": requires_human,
            "unverified": unverified, "pairs": pairs}


# --------------------------------------------------------------------------- postcheck

def _fmt_start(seg: dict[str, Any]) -> str:
    try:
        return f"{float(seg.get('start', 0.0)):.1f}"
    except (TypeError, ValueError):
        return str(seg.get("start"))


def postcheck(cast: dict[str, Any], segments: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Line-level band check + per-scene speaker F0 collision check."""
    errors = validate_cast(cast)
    if errors:
        return {"status": "FAIL", "failures": errors, "unverified": [], "measurements": {}}
    characters = _characters(cast)
    failures: list[str] = []
    unverified: list[str] = []
    attributed = [seg for seg in segments if seg.get("speaker")]
    if not attributed:
        return {"status": "UNVERIFIED", "failures": [], "unverified": ["NO_SPEAKER_ATTRIBUTION"],
                "measurements": {"lines_total": len(segments), "lines_attributed": 0}}
    per_speaker_scene: dict[tuple[str, str], list[float]] = {}
    line_rows: list[dict[str, Any]] = []
    for seg in attributed:
        speaker = str(seg["speaker"])
        start = _fmt_start(seg)
        f0 = seg.get("f0_median_hz")
        if speaker not in characters:
            unverified.append(f"SPEAKER_NOT_IN_CAST:{speaker}:{start}")
            continue
        if f0 is None:
            unverified.append(f"F0_UNAVAILABLE:{speaker}:{start}")
            continue
        lo, hi = (float(v) for v in characters[speaker]["f0_band_hz"])
        in_band = lo <= float(f0) <= hi
        line_rows.append({"start": seg.get("start"), "speaker": speaker, "f0_median_hz": f0,
                          "band": [lo, hi], "in_band": in_band})
        if not in_band:
            failures.append(f"VOICE_OUT_OF_BAND:{speaker}:{start}")
        scene = str(seg.get("scene") or "ALL")
        per_speaker_scene.setdefault((scene, speaker), []).append(float(f0))
    scene_medians: dict[str, dict[str, float]] = {}
    for (scene, speaker), values in per_speaker_scene.items():
        scene_medians.setdefault(scene, {})[speaker] = round(median(values), 2)
    collisions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for scene, medians in sorted(scene_medians.items()):
        for a, b in combinations(sorted(medians), 2):
            fa, fb = medians[a], medians[b]
            ratio = abs(fa - fb) / max(fa, fb)
            if ratio < COLLISION_RATIO:
                collisions.append({"scene": scene, "a": a, "b": b, "f0_a": fa, "f0_b": fb, "ratio": round(ratio, 4)})
                if (a, b) not in seen:
                    seen.add((a, b))
                    failures.append(f"VOICE_COLLISION:{a}:{b}")
    status = "FAIL" if failures else ("UNVERIFIED" if unverified else "PASS")
    return {
        "status": status,
        "failures": failures,
        "unverified": unverified,
        "measurements": {
            "lines_total": len(segments),
            "lines_attributed": len(attributed),
            "lines": line_rows,
            "scene_speaker_f0_median": scene_medians,
            "collisions": collisions,
        },
    }


# --------------------------------------------------------------------------- emotion dynamics

def emotion_dynamics(segments: Sequence[dict[str, Any]], *, delta_db: float = EMOTION_DELTA_DB) -> dict[str, Any]:
    """plead|fear|threat lines must be >= ``delta_db`` above the same speaker's calm RMS baseline."""
    failures: list[str] = []
    unverified: list[str] = []
    annotated = [seg for seg in segments if seg.get("speaker") and seg.get("emotion")]
    if not annotated:
        return {"status": "UNVERIFIED", "failures": [], "unverified": ["NO_EMOTION_ANNOTATION"], "measurements": {}}
    by_speaker: dict[str, list[dict[str, Any]]] = {}
    for seg in annotated:
        emotion = str(seg["emotion"]).lower()
        if emotion not in EMOTIONS:
            unverified.append(f"EMOTION_UNKNOWN:{seg['speaker']}:{_fmt_start(seg)}:{emotion}")
            continue
        by_speaker.setdefault(str(seg["speaker"]), []).append(seg)
    baselines: dict[str, float | None] = {}
    lines: list[dict[str, Any]] = []
    for speaker, rows in sorted(by_speaker.items()):
        calm = [float(r["rms_dbfs"]) for r in rows if str(r["emotion"]).lower() == "calm" and r.get("rms_dbfs") is not None]
        baseline = round(median(calm), 3) if calm else None
        baselines[speaker] = baseline
        if baseline is None:
            unverified.append(f"NO_CALM_BASELINE:{speaker}")
        for row in rows:
            emotion = str(row["emotion"]).lower()
            if emotion not in EMOTIVE:
                continue
            start = _fmt_start(row)
            rms = row.get("rms_dbfs")
            if rms is None:
                unverified.append(f"RMS_UNAVAILABLE:{speaker}:{start}")
                continue
            if baseline is None:
                continue  # already UNVERIFIED for this speaker
            delta = round(float(rms) - baseline, 3)
            ok = delta >= delta_db
            lines.append({"start": row.get("start"), "speaker": speaker, "emotion": emotion,
                          "rms_dbfs": rms, "calm_baseline_dbfs": baseline, "delta_db": delta, "pass": ok})
            if not ok:
                failures.append(f"FLAT_EMOTION:{speaker}:{start}")
    status = "FAIL" if failures else ("UNVERIFIED" if unverified else "PASS")
    return {"status": status, "failures": failures, "unverified": unverified,
            "measurements": {"calm_baseline_dbfs": baselines, "emotive_lines": lines, "threshold_db": delta_db}}


# --------------------------------------------------------------------------- CLI

def evaluate(cast: dict[str, Any], segments: Sequence[dict[str, Any]] | None,
             scene_copresence: Sequence[Sequence[str]] | None) -> dict[str, Any]:
    report: dict[str, Any] = {"schema": OUTPUT_SCHEMA, "checks": {}}
    if scene_copresence is not None:
        report["checks"]["precheck"] = precheck(cast, scene_copresence)
    if segments is not None:
        report["checks"]["postcheck"] = postcheck(cast, segments)
        report["checks"]["emotion_dynamics"] = emotion_dynamics(segments)
    if not report["checks"]:
        report["checks"]["inputs"] = {"status": "UNVERIFIED", "failures": [], "unverified": ["NO_INPUTS"], "measurements": {}}
    report["status"] = _worst(c["status"] for c in report["checks"].values())
    report["failures"] = [f for c in report["checks"].values() for f in c.get("failures", [])]
    report["requires_human"] = [f for c in report["checks"].values() for f in c.get("requires_human", [])]
    report["unverified"] = [f for c in report["checks"].values() for f in c.get("unverified", [])]
    report["measurements"] = {name: c.get("measurements") or c.get("pairs") for name, c in report["checks"].items()}
    return report


def _load_segments(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("segments") or []
    return [seg for seg in payload if isinstance(seg, dict)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Voice cast gate: precheck (co-presence) and postcheck (measured lines).")
    parser.add_argument("--cast", required=True, type=Path, help="voice_cast.json (qingshan.voice_cast.v1)")
    parser.add_argument("--segments-json", type=Path, help="dialogue_voice_metrics output with speaker/emotion per line")
    parser.add_argument("--copresence-json", type=Path, help="per-scene co-presence: [[character_id, ...], ...]")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    cast = json.loads(args.cast.read_text(encoding="utf-8"))
    segments = _load_segments(args.segments_json) if args.segments_json else None
    copresence = None
    if args.copresence_json:
        payload = json.loads(args.copresence_json.read_text(encoding="utf-8"))
        copresence = payload.get("scenes") if isinstance(payload, dict) else payload
    report = evaluate(cast, segments, copresence)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "failures": report["failures"],
                      "requires_human": report["requires_human"], "unverified": report["unverified"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
