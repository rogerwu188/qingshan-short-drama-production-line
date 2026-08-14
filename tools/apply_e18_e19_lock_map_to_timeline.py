#!/usr/bin/env python3
"""Apply the current E18/E19 lock map to timeline drafts for EDL prep."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BASE = Path("/Users/rogerwu/qingshan_short_drama")
LOCK_MAP = BASE / "workflow/generation/e18_e19/E18_E19_CANDIDATE_LOCK_MAP_20260715.json"
TIMELINES = {
    "E18": BASE / "configs/e18_timeline_draft_v1_20260715.json",
    "E19": BASE / "configs/e19_timeline_draft_v2_20260715.json",
}
OUT_DIR = BASE / "workflow/generation/e18_e19/edl_prep_20260715"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    lock = read_json(LOCK_MAP)
    locked_by_episode_source = {
        (item["episode"], item["source_id"]): item
        for item in lock["items"]
        if item.get("selected_video")
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []
    for episode, timeline_path in TIMELINES.items():
        timeline = read_json(timeline_path)
        segments = []
        replacements = []
        missing = []
        cursor = 0.0
        for segment in timeline["segments"]:
            updated = dict(segment)
            lock_item = locked_by_episode_source.get((episode, segment["source_id"]))
            if lock_item:
                old_path = updated["path"]
                updated["path"] = lock_item["selected_video"]
                updated["machine_lock_status"] = lock_item["lock_status"]
                updated["machine_ocr_status"] = lock_item["ocr_status"]
                updated["machine_asr_status"] = lock_item["asr_status"]
                if old_path != updated["path"]:
                    replacements.append(
                        {
                            "source_id": segment["source_id"],
                            "old_path": old_path,
                            "new_path": updated["path"],
                            "reason": "candidate lock map selected machine-gate-passed source",
                        }
                    )
            elif segment.get("dialogue_ids"):
                missing.append(segment["source_id"])
            path = Path(updated["path"])
            if not path.exists():
                missing.append(segment["source_id"])
            duration = float(updated["duration_sec"])
            updated["start_sec"] = round(cursor, 2)
            updated["end_sec"] = round(cursor + duration, 2)
            cursor += duration
            segments.append(updated)
        payload = {
            "schema": f"qingshan.{episode.lower()}.edl_prep_locked_sources.v1",
            "episode": episode,
            "status": "READY_FOR_MANUAL_WATCH_AND_EDL_PREP" if not missing else "MISSING_SOURCES",
            "source_timeline": str(timeline_path),
            "lock_map": str(LOCK_MAP),
            "runtime_sec": round(cursor, 2),
            "runtime_target_sec": timeline.get("runtime_target_sec"),
            "segments": segments,
            "replacements": replacements,
            "missing_sources": sorted(set(missing)),
            "rule": "Machine lock only. Manual watch, full assembly QA, continuity, OCR and ASR are still required before final lock.",
        }
        out_json = OUT_DIR / f"{episode}_LOCKED_SOURCE_EDL_PREP_20260715.json"
        out_md = OUT_DIR / f"{episode}_LOCKED_SOURCE_EDL_PREP_20260715.md"
        concat = OUT_DIR / f"{episode}_concat_sources_20260715.txt"
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        concat.write_text("".join(f"file '{seg['path']}'\n" for seg in segments), encoding="utf-8")
        lines = [
            f"# {episode} Locked Source EDL Prep",
            "",
            f"Status: `{payload['status']}`",
            f"Runtime: `{payload['runtime_sec']}s`",
            f"Replacements: `{len(replacements)}`",
            f"Missing sources: `{len(payload['missing_sources'])}`",
            "",
            "Rule: machine lock only; manual watch and assembly QA still required before final lock.",
            "",
            "## Segments",
            "",
        ]
        for seg in segments:
            lines.append(
                f"- `{seg['start_sec']:06.2f}-{seg['end_sec']:06.2f}` `{seg['source_id']}` "
                f"`{seg.get('machine_lock_status', seg.get('visual_status'))}` `{seg['path']}`"
            )
        out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        summaries.append(
            {
                "episode": episode,
                "status": payload["status"],
                "runtime_sec": payload["runtime_sec"],
                "edl": str(out_json),
                "summary": str(out_md),
                "concat": str(concat),
                "replacement_count": len(replacements),
                "missing_sources": payload["missing_sources"],
            }
        )
    index = {
        "schema": "qingshan.e18_e19.locked_source_edl_prep_index.v1",
        "status": "READY_FOR_MANUAL_WATCH_AND_EDL_PREP" if all(s["status"] == "READY_FOR_MANUAL_WATCH_AND_EDL_PREP" for s in summaries) else "NEEDS_ATTENTION",
        "items": summaries,
    }
    index_path = OUT_DIR / "E18_E19_LOCKED_SOURCE_EDL_PREP_INDEX_20260715.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": index["status"], "index": str(index_path), "items": summaries}, ensure_ascii=False))
    return 0 if index["status"] == "READY_FOR_MANUAL_WATCH_AND_EDL_PREP" else 1


if __name__ == "__main__":
    raise SystemExit(main())
