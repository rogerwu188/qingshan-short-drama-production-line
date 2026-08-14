#!/usr/bin/env python3
"""Build the E18/E19 candidate lock map while ASR rerolls are pending."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BASE = Path("/Users/rogerwu/qingshan_short_drama")
PACKAGE = BASE / "configs/e18_e19_final_omni_multimodal_candidate_package_v1_20260715.json"
QUEUE = BASE / "qa/e18_e19_final_omni_multimodal_candidates_v1_20260715/E18_E19_POST_OMNI_DOWNLOAD_QA_QUEUE_20260715.json"
ASR = BASE / "qa/e18_e19_final_omni_multimodal_candidates_v1_20260715/E18_E19_ASR_SENTENCE_COMPLETENESS_20260715.json"
REROLL = BASE / "workflow/generation/e18_e19/asr_reroll_v2_20260715/E18_E19_ASR_REROLL_V2_REMOTE_STATUS_20260715.json"
OUT_JSON = BASE / "workflow/generation/e18_e19/E18_E19_CANDIDATE_LOCK_MAP_20260715.json"
OUT_MD = BASE / "workflow/generation/e18_e19/E18_E19_CANDIDATE_LOCK_MAP_20260715.md"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    package = read_json(PACKAGE)
    queue = read_json(QUEUE)
    asr = read_json(ASR)
    reroll = read_json(REROLL) if REROLL.exists() else {"results": []}
    queue_by_source = {item["source_id"]: item for item in queue["items"]}
    asr_by_source = {item["source_id"]: item for item in asr["results"]}
    reroll_by_source = {item["source_id"]: item for item in reroll.get("results", [])}
    items = []
    counts: dict[str, int] = {}
    for group in package["candidate_groups"]:
        source_id = group["source_id"]
        queue_item = queue_by_source.get(source_id, {})
        asr_item = asr_by_source.get(source_id, {})
        reroll_item = reroll_by_source.get(source_id)
        status = "READY_FOR_MANUAL_WATCH_AND_EDL_PREP"
        selected_video = queue_item.get("video")
        blocking_reason = None
        replacement_task_id = None
        replacement_status = None
        if asr_item.get("status") == "FAIL":
            status = "BLOCKED_WAITING_TARGETED_REROLL"
            blocking_reason = ",".join(asr_item.get("failures") or [])
            if reroll_item:
                replacement_task_id = reroll_item.get("task_id")
                replacement_status = reroll_item.get("remote_status")
                if reroll_item.get("downloaded_files"):
                    selected_video = reroll_item["downloaded_files"][0]
                    status = "REROLL_DOWNLOADED_PENDING_QA"
        item = {
            "episode": group["episode"],
            "timeline_order": group["timeline_order"],
            "source_id": source_id,
            "dialogue_ids": group.get("dialogue_ids", []),
            "selected_video": selected_video,
            "ocr_status": queue_item.get("ocr_status"),
            "asr_status": asr_item.get("status"),
            "lock_status": status,
            "blocking_reason": blocking_reason,
            "replacement_task_id": replacement_task_id,
            "replacement_status": replacement_status,
        }
        items.append(item)
        counts[status] = counts.get(status, 0) + 1
    payload = {
        "schema": "qingshan.e18_e19_candidate_lock_map.v1",
        "status": "WAITING_TARGETED_REROLL" if any(i["lock_status"] == "BLOCKED_WAITING_TARGETED_REROLL" for i in items) else "READY_FOR_WATCH",
        "package": str(PACKAGE),
        "queue": str(QUEUE),
        "asr": str(ASR),
        "reroll": str(REROLL),
        "counts": counts,
        "items": items,
        "rule": "Do not final-lock or edit with ASR-failed sources. Use reroll replacement only after OCR/ASR/watch pass.",
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# E18/E19 Candidate Lock Map",
        "",
        f"Status: `{payload['status']}`",
        f"Counts: `{counts}`",
        "",
        "Rule: do not final-lock or edit with ASR-failed sources. Use reroll replacement only after OCR/ASR/watch pass.",
        "",
        "## Items",
        "",
    ]
    for item in items:
        lines.append(
            f"- `{item['episode']} {item['timeline_order']} {item['source_id']}`: `{item['lock_status']}`"
            + (f" replacement `{item['replacement_task_id']}` `{item['replacement_status']}`" if item["replacement_task_id"] else "")
        )
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "counts": counts, "out": str(OUT_JSON)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
