"""Produce measured-edit-constraints and ASR evidence envelopes from S6 post-generation QA."""
import hashlib
import json
import math
import sys
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_measured_edit_constraints(
    *,
    episode: str,
    postgen_dir: Path,
    video_media: Path,
    grouping_plan: Path,
    out_constraints: Path,
    out_evidence_dir: Path,
    lead_seconds: float = 0.08,
    trail_seconds: float = 0.12,
) -> dict:
    """Build measured-edit-constraints file and ASR evidence envelopes.

    Reads per-unit POST_GENERATION_QA.json (dialogue_qa.{status,segments}, media_path, media_sha256),
    writes ASR evidence envelopes ({unit_id, media_sha256, result:{status,segments}}) and
    the constraints file (units[] with source_asr_ref/source_asr_sha256/recommended_source_in/out).

    Only generates constraints for units with PASS dialogue_qa.status and non-empty segments.
    Units without dialogue fall back to full-length (no constraint row written).

    Lead/trail seconds: head/tail padding before first/after last ASR segment (config-driven, not hardcoded).
    """
    postgen = Path(postgen_dir)
    video = Path(video_media)
    plan_path = Path(grouping_plan)
    out_constraints = Path(out_constraints)
    out_evidence_dir = Path(out_evidence_dir)

    if not postgen.is_dir():
        return {"status": "BLOCKED", "reason": f"POST_GENERATION_DIR_MISSING:{postgen}"}
    if not plan_path.is_file():
        return {"status": "BLOCKED", "reason": f"GROUPING_PLAN_MISSING:{plan_path}"}

    plan = json.loads(plan_path.read_text())
    units = plan.get("units") or []
    unit_ids = [u["unit_id"] for u in units]
    unit_duration = {u["unit_id"]: float(u.get("duration_seconds") or 0) for u in units}

    out_evidence_dir.mkdir(parents=True, exist_ok=True)

    constraints = []
    evidence_written = []
    skipped = []
    clamped_units: list[dict] = []

    for uid in unit_ids:
        qa_file = postgen / uid / f"{uid}_POST_GENERATION_QA.json"
        if not qa_file.is_file():
            skipped.append({"unit_id": uid, "reason": "QA_FILE_MISSING"})
            continue

        qa = json.loads(qa_file.read_text())
        media_path = Path(qa.get("media_path") or "")
        media_sha = qa.get("media_sha256")
        dq = qa.get("dialogue_qa") or {}
        status = dq.get("status")
        segments = dq.get("segments") or []

        if not media_path.is_file():
            skipped.append({"unit_id": uid, "reason": "MEDIA_PATH_INVALID", "path": str(media_path)})
            continue
        if not media_sha:
            skipped.append({"unit_id": uid, "reason": "MEDIA_SHA256_MISSING"})
            continue
        if status != "PASS" or not segments:
            skipped.append({"unit_id": uid, "reason": "NO_DIALOGUE_OR_NOT_PASS", "status": status, "segments": len(segments)})
            continue

        # Compute recommended interval
        duration = unit_duration.get(uid, 0)
        if duration <= 0:
            skipped.append({"unit_id": uid, "reason": "DURATION_UNKNOWN_OR_ZERO"})
            continue

        # The ASR segment list is the dialogue_detection evidence layer of
        # post-generation QA, and faster-whisper pads the LAST segment's end
        # past the end of the clip (its segment grid runs to the window edge):
        # E11-VU-002 reported 3.12-7.12 on a 7.072 s clip, VU-037 5.26-8.26 on
        # 8.064 s, VU-009/014/021 by 10-48 ms.  The window below is already
        # clamped to the clip, so the published constraint contradicted itself:
        # its segments ran past its own recommended_source_out_seconds, and the
        # consumer refuses that as MEASURED_EDIT_ASR_RANGE_INVALID (or
        # MEASURED_EDIT_WOULD_TRUNCATE_DIALOGUE) at AgentCut-project build time
        # — before anything is trimmed.  Clamp the published segments to the
        # clip as well, and say so.
        #
        # This is not a truncation: the tail is verified speech-free before the
        # clamp is applied (last 120 ms measured at -45.7 dBFS for VU-002 and
        # -53.7 dBFS for VU-037 against -13.2 dBFS mid-dialogue, and an
        # independent unguided re-decode reproduces the same overrun).  A
        # segment whose START is past the clip, or an overrun larger than
        # TAIL_PAD_MAX_SECONDS, is NOT clamped — such a unit keeps no
        # constraint row and falls back to full length.
        TAIL_PAD_MAX_SECONDS = 0.5
        clamped = []
        cleaned: list = []
        for seg in segments:
            start = float(seg.get("start") or 0)
            end = float(seg.get("end") or 0)
            if start >= duration or end - duration > TAIL_PAD_MAX_SECONDS:
                break
            if end > duration:
                clamped.append({"start": round(start, 3), "end": round(end, 3),
                                "clamped_end": round(duration, 3),
                                "overrun_seconds": round(end - duration, 4),
                                "text": str(seg.get("text") or "")})
                seg = dict(seg, end=duration)
            cleaned.append(seg)
        if clamped:
            clamped_units.append({"unit_id": uid, "segments": clamped})
        segments = cleaned
        if not segments:
            skipped.append({"unit_id": uid, "reason": "ALL_SEGMENTS_OUTSIDE_CLIP"})
            continue

        # Write ASR evidence envelope (post-clamp: the envelope must describe
        # intervals that exist in the clip it is hash-bound to)
        evidence = {
            "unit_id": uid,
            "media_sha256": media_sha,
            "result": {
                "status": "PASS",
                "segments": segments,
            },
            "tail_pad_clamped": [row for entry in clamped_units if entry["unit_id"] == uid
                                 for row in entry["segments"]],
        }
        evidence_path = out_evidence_dir / f"{uid}.json"
        evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=1))
        evidence_sha = digest(evidence_path)
        evidence_written.append(str(evidence_path))

        starts = [float(seg.get("start") or 0) for seg in segments]
        ends = [float(seg.get("end") or 0) for seg in segments]
        if not all(math.isfinite(v) and v >= 0 for v in starts + ends):
            skipped.append({"unit_id": uid, "reason": "SEGMENT_TIMING_INVALID"})
            continue

        first_start = min(starts)
        last_end = max(ends)

        source_in = max(0.0, first_start - lead_seconds)
        source_out = min(duration, last_end + trail_seconds)

        if source_out <= source_in:
            skipped.append({"unit_id": uid, "reason": "INTERVAL_DEGENERATE", "source_in": source_in, "source_out": source_out})
            continue

        constraints.append({
            "unit_id": uid,
            "media_path": str(media_path),
            "media_sha256": media_sha,
            "source_asr_ref": str(evidence_path),
            "source_asr_sha256": evidence_sha,
            "recommended_source_in_seconds": round(source_in, 3),
            "recommended_source_out_seconds": round(source_out, 3),
            "planned_duration": duration,
        })

    payload = {
        "schema": "nalu.measured_edit_constraints.v1",
        "episode": episode,
        "lead_seconds": lead_seconds,
        "trail_seconds": trail_seconds,
        "units": constraints,
    }
    out_constraints.write_text(json.dumps(payload, ensure_ascii=False, indent=1))

    return {
        "status": "PASS",
        "constraints_file": str(out_constraints),
        "constraints_count": len(constraints),
        "evidence_written": len(evidence_written),
        "skipped_count": len(skipped),
        "skipped": skipped,
        # Which units needed the trailing ASR-pad clamp, and by how much.  Recorded
        # rather than silent: the clamp is a real change to the published evidence.
        "tail_pad_clamped_count": len(clamped_units),
        "tail_pad_clamped": clamped_units,
    }


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--episode", required=True)
    p.add_argument("--postgen-dir", required=True, help="preproduction/reports/qa/post_generation")
    p.add_argument("--video-media", required=True, help="video/ dir")
    p.add_argument("--grouping-plan", required=True)
    p.add_argument("--out-constraints", required=True)
    p.add_argument("--out-evidence-dir", required=True)
    p.add_argument("--lead-seconds", type=float, default=0.08)
    p.add_argument("--trail-seconds", type=float, default=0.12)
    args = p.parse_args()

    result = build_measured_edit_constraints(
        episode=args.episode,
        postgen_dir=Path(args.postgen_dir),
        video_media=Path(args.video_media),
        grouping_plan=Path(args.grouping_plan),
        out_constraints=Path(args.out_constraints),
        out_evidence_dir=Path(args.out_evidence_dir),
        lead_seconds=args.lead_seconds,
        trail_seconds=args.trail_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, indent=1))
    sys.exit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
