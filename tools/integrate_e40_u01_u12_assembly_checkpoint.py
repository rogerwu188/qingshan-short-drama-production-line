#!/usr/bin/env python3
"""Persist the verified U01-U12 local assembly-prefix checkpoint."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

R = Path(__file__).resolve().parents[1]
W = R / "workflow/work_queue.json"
X = R / "workflow/CODEX_TO_CLAUDE.md"
P = R / "working_assets/e40_assembly_20260814/u01_u12_parallel_prefix_v1/E40_U01_U12_LOCAL_PREVIEW_HARDCUT_720X1280_V1.mp4"
Q = R / "qa/e40_assembly_20260814/u01_u12_parallel_prefix_v1/E40_U01_U12_LOCAL_PREFIX_MACHINE_AND_HUMAN_QA_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(R))


def atomic_json(path: Path, payload: dict) -> None:
    blob = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
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


def main() -> int:
    for path in (W, X, P, Q):
        if not path.is_file():
            raise SystemExit(f"FAIL_MISSING:{path}")
    qa = json.loads(Q.read_text())
    if qa.get("status") != "PASS_IMMUTABLE_PREFIX_U01_U12" or qa.get("failures"):
        raise SystemExit("FAIL_QA_GATE")
    work = json.loads(W.read_text())
    work["latest_e40_u01_u12_assembly_prefix"] = {
        "status": qa["status"],
        "path": rel(P),
        "sha256": sha(P),
        "duration_seconds": 58.166667,
        "qa": rel(Q),
        "qa_sha256": sha(Q),
        "provider_posts": 0,
        "credits": 0,
        "next_action": "Append U13 only after U13 exact audiovisual admission; preserve U01-U12 order."
    }
    atomic_json(W, work)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with X.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n\n## E40 checkpoint {now} — parallel assembly prefix advanced through admitted U12\n\n"
            f"- U01-U12 prefix `{rel(P)}` SHA=`{sha(P)}` appends admitted U12 once after the verified U01-U11 source. It is 58.166667s, 720x1280/24fps, AAC 48k stereo, matched A/V and full-decode PASS.\n"
            f"- Human contact-sheet QA confirms the U11 cat warning to U12 rubbing-throw causal cut, unit order and period-hall continuity; QA `{rel(Q)}` SHA=`{sha(Q)}`.\n"
            "- No provider post or credit spend occurred. This remains a local prefix, not episode-final or release. Next dependent action is admitted U13 append.\n"
        )
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({"status": "PASS_U01_U12_ASSEMBLY_CHECKPOINT", "prefix_sha256": sha(P), "qa_sha256": sha(Q)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
