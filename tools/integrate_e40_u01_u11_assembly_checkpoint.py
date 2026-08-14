#!/usr/bin/env python3
"""Persist the admitted U01-U11 assembly-prefix progression into shared handoff state."""
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

P9 = R / "working_assets/e40_assembly_20260814/u01_u09_parallel_prefix_v1/E40_U01_U09_LOCAL_PREVIEW_HARDCUT_720X1280_V1.mp4"
Q9 = R / "qa/e40_assembly_20260814/u01_u09_parallel_prefix_v1/E40_U01_U09_LOCAL_PREFIX_MACHINE_AND_HUMAN_QA_V1.json"
P10 = R / "working_assets/e40_assembly_20260814/u01_u10_parallel_prefix_v2/E40_U01_U10_LOCAL_PREVIEW_HARDCUT_720X1280_V2.mp4"
Q10 = R / "qa/e40_assembly_20260814/u01_u10_parallel_prefix_v2/E40_U01_U10_LOCAL_PREFIX_MACHINE_AND_HUMAN_QA_V2.json"
F10 = R / "qa/e40_assembly_20260814/u01_u10_parallel_prefix_v1/E40_U01_U10_V1_AUDIO_TAIL_FAILURE_MEMORY_AND_V2_REPAIR_CONTRACT_V1.json"
P11 = R / "working_assets/e40_assembly_20260814/u01_u11_parallel_prefix_v1/E40_U01_U11_LOCAL_PREVIEW_HARDCUT_720X1280_V1.mp4"
Q11 = R / "qa/e40_assembly_20260814/u01_u11_parallel_prefix_v1/E40_U01_U11_LOCAL_PREFIX_MACHINE_AND_HUMAN_QA_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(R))


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, payload: dict) -> None:
    blob = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(blob); handle.flush(); os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True); raise


def record(path: Path, qa: Path, duration: float, next_action: str) -> dict:
    payload = json.loads(qa.read_text())
    if not payload.get("status", "").startswith("PASS") or payload.get("failures"):
        raise SystemExit(f"FAIL_QA:{qa}")
    return {
        "status": payload["status"],
        "path": rel(path), "sha256": sha(path), "duration_seconds": duration,
        "qa": rel(qa), "qa_sha256": sha(qa),
        "provider_posts": 0, "credits": 0, "next_action": next_action,
    }


def main() -> int:
    for path in (W, X, P9, Q9, P10, Q10, F10, P11, Q11):
        if not path.is_file():
            raise SystemExit(f"FAIL_MISSING:{path}")
    work = json.loads(W.read_text())
    work["latest_e40_u01_u09_assembly_prefix"] = record(P9, Q9, 43.177, "Superseded by verified U01-U10 V2 prefix; preserve immutable source chain.")
    work["latest_e40_u01_u10_assembly_prefix"] = record(P10, Q10, 47.166667, "Superseded by verified U01-U11 prefix; preserve V1 failure memory and V2 only.")
    work["latest_e40_u01_u10_assembly_prefix"]["v1_failure_memory"] = rel(F10)
    work["latest_e40_u01_u10_assembly_prefix"]["v1_failure_memory_sha256"] = sha(F10)
    work["latest_e40_u01_u11_assembly_prefix"] = record(P11, Q11, 51.166667, "Append U12 only after U12 unit admission; preserve U01-U11 order and explicit U11 silence.")
    atomic_json(W, work)
    n = stamp()
    with X.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n\n## E40 checkpoint {n} — parallel assembly prefix advanced through admitted U11\n\n"
            f"- U01-U09 prefix `{rel(P9)}` SHA=`{sha(P9)}` passed full decode and human order/continuity QA SHA=`{sha(Q9)}`.\n"
            f"- Initial U01-U10 V1 exposed a 0.660667s short audio tail and was fail-closed; memory SHA=`{sha(F10)}`. Non-overwriting V2 `{rel(P10)}` SHA=`{sha(P10)}` materially pads/trims both audio segments and passes matched 47.166667s A/V, full decode and U09-to-U10 human boundary QA SHA=`{sha(Q10)}`.\n"
            f"- U01-U11 prefix `{rel(P11)}` SHA=`{sha(P11)}` appends admitted silent U11 once with an explicit 4s stereo silence segment. It is 51.166667s, 720x1280/24fps, AAC 48k stereo, full-decode PASS, and U10-to-U11 boundary HUMAN PASS; QA SHA=`{sha(Q11)}`. This is a local prefix, not episode-final or release.\n"
        )
        handle.flush(); os.fsync(handle.fileno())
    print(json.dumps({"status": "PASS_U01_U11_ASSEMBLY_CHECKPOINT", "u01_u11_sha256": sha(P11), "qa_sha256": sha(Q11)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
