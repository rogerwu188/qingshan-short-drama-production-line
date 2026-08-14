#!/usr/bin/env python3
"""Record parallel assembly-prefix and U08 preproduction artifacts in shared E40 state."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WQ = ROOT / "workflow/work_queue.json"
X2CL = ROOT / "workflow/CODEX_TO_CLAUDE.md"
FILES = {
    "inventory": ROOT / "working_assets/e40_assembly_20260814/u01_u06_parallel_inventory_v1/E40_U01_U06_ASSEMBLY_INPUT_INVENTORY_V1.json",
    "timeline": ROOT / "working_assets/e40_assembly_20260814/u01_u06_parallel_inventory_v1/E40_U01_U06_EXECUTABLE_TIMELINE_PRECOMPILE_V1.json",
    "preview": ROOT / "working_assets/e40_assembly_20260814/u01_u06_parallel_inventory_v1/E40_U01_U06_LOCAL_PREVIEW_HARDCUT_720X1280_V1.mp4",
    "assembly_qa": ROOT / "qa/e40_assembly_20260814/u01_u06_parallel_inventory_v1/E40_U01_U06_PARALLEL_ASSEMBLY_PRECOMPILE_QA_V1.json",
    "continuity_qa": ROOT / "qa/e40_assembly_20260814/u01_u06_parallel_inventory_v1/E40_U01_U06_LOCAL_PREVIEW_HUMAN_CONTINUITY_QA_V1.json",
    "u01_audit": ROOT / "qa/e40_assembly_20260814/u01_u06_parallel_inventory_v1/E40_U01_ADMISSION_AUTHORITY_CHAIN_AUDIT_V1.json",
    "u08_frame": ROOT / "working_assets/e40_preproduction_20260814/u08_parallel_exact_start_frame_v1/E40_U08_PARALLEL_EXACT_START_FRAME_720X1280_V2.png",
    "u08_prompt": ROOT / "working_assets/e40_preproduction_20260814/u08_parallel_exact_start_frame_v1/E40_U08_FAST720_BOUND_CANDIDATE_PROMPT_V1.txt",
    "u08_gate": ROOT / "qa/e40_preproduction_20260814/u08_parallel_exact_start_frame_v1/E40_U08_FAST720_BOUND_CANDIDATE_STATIC_GATE_V1.json",
    "u08_receipt": ROOT / "qa/e40_preproduction_20260814/u08_parallel_exact_start_frame_v1/E40_U08_PARALLEL_PREPRODUCTION_RECEIPT_V1.json",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def atomic_json(path: Path, payload: dict) -> None:
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def main() -> int:
    for path in FILES.values():
        if not path.is_file():
            raise SystemExit(f"FAIL_MISSING:{path}")
    moment = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    work = json.loads(WQ.read_text(encoding="utf-8"))
    work["latest_e40_u01_u06_assembly_prefix"] = {
        "status": "PASS_PREVIEW_AND_ALL_SIX_INPUTS_IMMUTABLE_PREFIX",
        "inventory": rel(FILES["inventory"]),
        "inventory_sha256": sha(FILES["inventory"]),
        "timeline": rel(FILES["timeline"]),
        "timeline_sha256": sha(FILES["timeline"]),
        "preview": rel(FILES["preview"]),
        "preview_sha256": sha(FILES["preview"]),
        "duration_seconds": 31.141,
        "machine_qa": rel(FILES["assembly_qa"]),
        "machine_qa_sha256": sha(FILES["assembly_qa"]),
        "human_continuity_qa": rel(FILES["continuity_qa"]),
        "human_continuity_qa_sha256": sha(FILES["continuity_qa"]),
        "u01_authority_chain_audit": rel(FILES["u01_audit"]),
        "u01_authority_chain_audit_sha256": sha(FILES["u01_audit"]),
        "next_action": "Append U07 only after U07 unit admission; preserve U01-U06 prefix SHA chain.",
    }
    work["latest_e40_u08_parallel_preproduction"] = {
        "status": "PASS_HUMAN92_OCR0_STATIC_GATE_CONTINUITY_BINDING_PENDING",
        "canonical_line": "他不是证人，是饵。",
        "frame": rel(FILES["u08_frame"]),
        "frame_sha256": sha(FILES["u08_frame"]),
        "prompt": rel(FILES["u08_prompt"]),
        "prompt_sha256": sha(FILES["u08_prompt"]),
        "static_gate": rel(FILES["u08_gate"]),
        "static_gate_sha256": sha(FILES["u08_gate"]),
        "receipt": rel(FILES["u08_receipt"]),
        "receipt_sha256": sha(FILES["u08_receipt"]),
        "provider_posts": 0,
        "credits": 0,
        "blocked_by": "U07_ADMITTED_TAIL_TO_U08_FRAME_CONTINUITY_COMPARISON_PENDING",
        "next_action": "When U07 is admitted, compare its decoded tail with the U08 frame; admit only on continuity PASS.",
    }
    atomic_json(WQ, work)
    with X2CL.open("a", encoding="utf-8") as stream:
        stream.write(
            f"\n\n## E40 checkpoint {moment} — parallel assembly prefix and U08 preproduction persisted\n\n"
            f"- U01-U06 immutable assembly prefix passed all six input SHA/QA checks. Local 31.141s preview `{rel(FILES['preview'])}` SHA=`{sha(FILES['preview'])}` passed full decode and human continuity QA; inventory SHA=`{sha(FILES['inventory'])}`, timeline SHA=`{sha(FILES['timeline'])}`.\n"
            f"- U08 DIA007 `他不是证人，是饵。` preproduction frame `{rel(FILES['u08_frame'])}` SHA=`{sha(FILES['u08_frame'])}` passed original-resolution HUMAN92 and OCR0; Fast720 prompt/static gate are precompiled with zero provider posts/credits. Formal admission remains blocked only on the U07 admitted-tail to U08 frame continuity comparison.\n"
            f"- Active dependency-chain owner remains U07 V3 local render/QA; these parallel artifacts do not bypass that gate or authorize a provider submit.\n"
        )
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"status": "PASS_PARALLEL_CHECKPOINT_PERSISTED", "preview_sha256": sha(FILES["preview"]), "u08_frame_sha256": sha(FILES["u08_frame"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
