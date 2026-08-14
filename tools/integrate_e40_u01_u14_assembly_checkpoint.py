#!/usr/bin/env python3
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
P = R / "working_assets/e40_assembly_20260814/u01_u14_parallel_prefix_v1/E40_U01_U14_LOCAL_PREVIEW_HARDCUT_720X1280_V1.mp4"
Q = R / "qa/e40_assembly_20260814/u01_u14_parallel_prefix_v1/E40_U01_U14_LOCAL_PREFIX_MACHINE_AND_HUMAN_QA_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(R))


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


def main() -> int:
    for path in (W, X, P, Q):
        if not path.is_file():
            raise SystemExit(f"FAIL_MISSING:{path}")
    qa = json.loads(Q.read_text())
    if qa.get("status") != "PASS_IMMUTABLE_PREFIX_U01_U14" or qa.get("failures"):
        raise SystemExit("FAIL_QA_GATE")
    if sha(P) != qa["output"]["sha256"]:
        raise SystemExit("FAIL_PREFIX_SHA")
    queue = json.loads(W.read_text())
    queue["latest_e40_u01_u14_assembly_prefix"] = {
        "status": qa["status"],
        "path": rel(P),
        "sha256": sha(P),
        "duration_seconds": 70.166667,
        "qa": rel(Q),
        "qa_sha256": sha(Q),
        "provider_posts": 0,
        "credits": 0,
        "next_action": "Append U15 after its exact two-dialogue audiovisual admission; preserve U01-U14 order."
    }
    write_json_atomic(W, queue)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with X.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n\n## E40 checkpoint {now} — parallel assembly prefix advanced through admitted U14\n\n"
            f"- U01-U14 prefix `{rel(P)}` SHA=`{sha(P)}` is 70.166667s, 720x1280/24fps, AAC 48k stereo, matched A/V and full-decode PASS. Human QA confirms the U13 denial to U14 hidden-hand pressure causal cut and period-hall continuity; QA SHA=`{sha(Q)}`. Provider posts/credits=0; not final or released.\n"
        )
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({"status": "PASS_U01_U14_ASSEMBLY_CHECKPOINT", "prefix_sha256": sha(P), "qa_sha256": sha(Q)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
