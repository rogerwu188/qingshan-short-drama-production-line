"""Consume hash-bound observed dialogue timings without silently clipping speech."""
import hashlib
import json
import math
import subprocess
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_constraints(path):
    if path is None:
        return {}
    payload = json.loads(Path(path).read_text())
    rows = payload.get("units", [])
    result = {}
    for row in rows:
        unit = row["unit_id"]
        if unit in result:
            raise ValueError("DUPLICATE_MEASURED_EDIT_UNIT: " + unit)
        result[unit] = row
    return result


def resolve_source_interval(row, source, planned_duration):
    """Return an explicit native A/V interval, plus an auditable timeline delta."""
    source = Path(source).resolve()
    if source != Path(row["media_path"]).resolve() or digest(source) != row["media_sha256"]:
        raise ValueError("MEASURED_EDIT_MEDIA_MISMATCH")
    evidence_path = Path(row["source_asr_ref"])
    if digest(evidence_path) != row["source_asr_sha256"]:
        raise ValueError("MEASURED_EDIT_ASR_SHA_MISMATCH")
    evidence = json.loads(evidence_path.read_text())
    if evidence.get("media_sha256") != row["media_sha256"]:
        raise ValueError("MEASURED_EDIT_ASR_MEDIA_MISMATCH")
    if evidence.get("unit_id") != row["unit_id"] or evidence.get("result", {}).get("status") != "PASS":
        raise ValueError("MEASURED_EDIT_ASR_NOT_VERIFIED")
    segments = evidence["result"].get("segments", [])
    if not segments:
        raise ValueError("MEASURED_EDIT_NO_OBSERVED_DIALOGUE")
    start = float(row["recommended_source_in_seconds"])
    end = float(row["recommended_source_out_seconds"])
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "json", str(source)], capture_output=True, text=True, check=True)
    duration = float(json.loads(probe.stdout)["format"]["duration"])
    if not all(math.isfinite(x) for x in (start, end, duration)) or not 0 <= start < end <= duration + 0.001:
        raise ValueError("MEASURED_EDIT_SOURCE_RANGE_INVALID")
    for segment in segments:
        a, b = float(segment["start"]), float(segment["end"])
        if not all(math.isfinite(x) for x in (a, b)) or not 0 <= a < b <= duration + 0.001:
            raise ValueError("MEASURED_EDIT_ASR_RANGE_INVALID")
        if a < start or b > end:
            raise ValueError("MEASURED_EDIT_WOULD_TRUNCATE_DIALOGUE")
    return start, end - start, {
        "source_asr_ref": str(evidence_path), "source_asr_sha256": row["source_asr_sha256"],
        "media_sha256": row["media_sha256"], "planned_duration": planned_duration,
        "source_in_seconds": start, "source_out_seconds": end,
        "timeline_delta_seconds": round(end - start - planned_duration, 6),
        "interval_validated": True, "applied_to_project": False, "render_verified": False,
    }


def yield_to_performance_cut(payload, performance_cut):
    """Drop the constraint rows of units that carry no on-screen scripted line.

    A measured edit trims a unit to the speech the S6 dialogue QA heard in it.  That is only right
    when the speech is the unit's scripted on-screen line.  In a unit with no on-screen line (the
    performance cut's kind SILENT: ambience, or a unit that only carries V.O. narration) whatever
    was heard is unscripted speech or the video model voicing the narration, which the performance
    cut removes -- and when the unit carries V.O. it keeps the unit long enough for that narration
    (VO_HOLD).  The measured interval used to win in the AgentCut build: E13-VU-013 held 0-4.796 s
    for a 4.296 s narration, the measured in-point 3.74 s turned that into a 1.056 s clip, and S7
    stopped on VOICE_OVER_OVERLAPS_DIALOGUE with no way out.  Such a unit follows the performance
    cut alone; the dropped rows stay in the payload under ``yielded_to_performance_cut``.

    Returns (payload, dropped unit ids).  ``performance_cut`` is the <EP>_PERFORMANCE_CUT.json report.
    """
    silent = {str(row.get("unit_id")) for row in (performance_cut or {}).get("units") or []
              if row.get("kind") == "SILENT"}
    rows = list((payload or {}).get("units") or [])
    dropped = [row for row in rows if str(row.get("unit_id")) in silent]
    if not dropped:
        return payload, []
    out = dict(payload)
    out["units"] = [row for row in rows if str(row.get("unit_id")) not in silent]
    out["yielded_to_performance_cut"] = list(payload.get("yielded_to_performance_cut") or []) + [
        dict(row, reason="NO_ON_SCREEN_SCRIPTED_LINE") for row in dropped]
    return out, [str(row["unit_id"]) for row in dropped]
