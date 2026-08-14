#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "qa/e40_production_20260814/u08_preprod_parallel_append_log_v1/E40_U08_PREPROD_PARALLEL_APPEND_LOG_V1.jsonl"
WORK_QUEUE = ROOT / "workflow/work_queue.json"
CODEX_LOG = ROOT / "workflow/CODEX_TO_CLAUDE.md"
UNITS = ("E40-U26", "E40-U27", "E40-U28", "E40-U29")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json_atomic(path: Path, data: dict) -> None:
    blob = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def verify_bound_files(record: dict) -> None:
    for key, value in record.items():
        if not key.endswith("_path") or not isinstance(value, str):
            continue
        sha_key = f"{key[:-5]}_sha256"
        if sha_key not in record:
            continue
        path = ROOT / value
        if not path.is_file():
            raise SystemExit(f"FAIL_MISSING_BOUND_FILE:{value}")
        if sha(path) != record[sha_key]:
            raise SystemExit(f"FAIL_BOUND_SHA:{value}")


def main() -> int:
    if not LOG.is_file():
        raise SystemExit("FAIL_MISSING_APPEND_LOG")
    latest: dict[str, dict] = {}
    for line in LOG.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        unit = record.get("unit_id")
        if unit in UNITS:
            latest[unit] = record
    if tuple(sorted(latest)) != UNITS:
        raise SystemExit(f"FAIL_MISSING_UNIT_RECORDS:{sorted(latest)}")
    for unit in UNITS:
        record = latest[unit]
        if record.get("provider_posts", 0) != 0 or record.get("paid_credits", 0) != 0:
            raise SystemExit(f"FAIL_NONZERO_COST:{unit}")
        verify_bound_files(record)

    queue = json.loads(WORK_QUEUE.read_text())
    for unit in UNITS:
        record = latest[unit]
        queue[f"latest_{unit.lower().replace('-', '_')}_parallel_preproduction"] = {
            "status": record["status"],
            "source_append_log": str(LOG.relative_to(ROOT)),
            "source_append_log_sha256": sha(LOG),
            "event": record["event"],
            "provider_posts": 0,
            "paid_credits": 0,
            "unique_next_action": record.get("unique_next_action"),
            "unique_blocker": record.get("unique_blocker"),
            "u28a_unique_blocker": record.get("u28a_unique_blocker"),
            "u28b_unique_blocker": record.get("u28b_unique_blocker"),
            "handoff_receipt_path": record.get("handoff_receipt_path"),
            "handoff_receipt_sha256": record.get("handoff_receipt_sha256"),
        }
    write_json_atomic(WORK_QUEUE, queue)

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    summary = "; ".join(f"{unit}={latest[unit]['status']}" for unit in UNITS)
    with CODEX_LOG.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n\n## E40 checkpoint {now} — U26-U29 independent preproduction integrated\n\n"
            f"- Verified SHA-bound zero-cost append-log records: {summary}. U29 reuses the existing QA-passed 8s/192f silent four-shot assembly; U26-U28 remain fail-closed on their stated exact-frame/upstream gates. Append log SHA=`{sha(LOG)}`. Provider posts/paid credits=0.\n"
        )
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({"status": "PASS_U26_U29_PARALLEL_PREPRODUCTION_INTEGRATED", "append_log_sha256": sha(LOG)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
