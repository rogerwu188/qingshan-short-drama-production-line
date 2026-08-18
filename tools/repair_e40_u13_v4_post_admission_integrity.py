#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QA_DIR = ROOT / "qa/e40_production_20260814/u13_v4_local_authority_half_rise_denial_exact_dialogue_v1"
VIDEO = ROOT / "working_assets/e40_production_20260814/u13_v4_local_authority_half_rise_denial_exact_dialogue_v1/E40-U13-V4-LOCAL-AUTHORITY-EXACT-DIA011-HALF-RISE-DENIAL-PROP-LOCKED.mp4"
MACHINE_QA = QA_DIR / "E40_U13_V4_LOCAL_AUTHORITY_MACHINE_QA_V1.json"
HUMAN_QA = QA_DIR / "E40_U13_V4_ORIGINAL_RESOLUTION_HUMAN_VISUAL_QA_V1.json"
FINAL_RECEIPT = QA_DIR / "E40_U13_V4_FINAL_ADMISSION_READY_RECEIPT_V1.json"
ASSET_RECEIPT = QA_DIR / "E40_U13_V4_ASSET_SHA256_RECEIPT_V1.json"
PRECHECK = QA_DIR / "E40_U13_V4_INSTALLED_PRECHECK_V1.json"
ADMISSION = ROOT / "workflow/releases/E40_U13_V4_RIGHTS_CLEARED_EXACT_DIALOGUE_UNIT_ADMISSION_20260814.json"
OUTPUT = QA_DIR / "E40_U13_V4_POST_ADMISSION_INTEGRITY_REPAIR_V1.json"
WORK_QUEUE = ROOT / "workflow/work_queue.json"
CODEX_LOG = ROOT / "workflow/CODEX_TO_CLAUDE.md"

PINNED = {
    VIDEO: "0ed501d2123c7c4f5a9f2dcf1c38add3eb6ad939917457d37bef48e035fed1fd",
    MACHINE_QA: "97581b0935f185e88e8b3c26dee13727d8da6d08b43e748877f3f61fd7ade689",
    HUMAN_QA: "000a2f80051a6edf4bc86cb14d4bfecc4d93e1e40f6d2e565fabbea96f025cf0",
    FINAL_RECEIPT: "66b0ffc2f31ee975bca0f0eb69071f0b98d0bf1c2a6ebf2b8f45d9097440b1a6",
    ASSET_RECEIPT: "62f2d737b53df5bacaab63b3b17b460beecf012bda9661f738c7fbc9155f9c81",
    ADMISSION: "389a8411478993543ca6304a475349721be23f9a1e4f303dc0ec9d6c3fe78046",
}
ORIGINAL_PRECHECK_SHA = "a9facc49ff090d534350545d4cd092b26ed372362a918ef49e1b75a62dea1ded"
COLLISION_PRECHECK_SHA = "99afc77930a839594b574d6b65a7101ba809d52aee2339704f722f1d64141e3e"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    for path, expected in PINNED.items():
        if not path.is_file() or sha(path) != expected:
            raise SystemExit(f"FAIL_PINNED_CORE:{rel(path)}")
    if sha(PRECHECK) != COLLISION_PRECHECK_SHA:
        raise SystemExit("FAIL_UNKNOWN_PRECHECK_STATE")
    collision = json.loads(PRECHECK.read_text())
    if collision.get("status") != "FAIL" or "FAIL_CLOSED_OUTPUT_COLLISION" not in collision.get("failures", []):
        raise SystemExit("FAIL_COLLISION_NOT_CLASSIFIED")
    machine = json.loads(MACHINE_QA.read_text())
    human = json.loads(HUMAN_QA.read_text())
    admission = json.loads(ADMISSION.read_text())
    if not str(machine.get("status", "")).startswith("PASS") or machine.get("failures"):
        raise SystemExit("FAIL_MACHINE_QA")
    if not str(human.get("status", "")).startswith("PASS") or human.get("failures"):
        raise SystemExit("FAIL_HUMAN_QA")
    if admission.get("status") != "PASS_U13_V4_ADMITTED_FOR_EPISODE_ASSEMBLY":
        raise SystemExit("FAIL_ADMISSION")

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    repair = {
        "schema": "qingshan.e40.u13.v4.post_admission_integrity_repair.v1",
        "episode": "E40",
        "unit": "U13",
        "status": "PASS_APPEND_ONLY_REPAIR_PINNED_CORE_UNCHANGED",
        "created_at": now,
        "incident": {
            "type": "POST_ADMISSION_PRECHECK_PATH_COLLISION",
            "original_precheck_sha256_recorded_in_asset_receipt": ORIGINAL_PRECHECK_SHA,
            "current_collision_precheck_path": rel(PRECHECK),
            "current_collision_precheck_sha256": COLLISION_PRECHECK_SHA,
            "classification": "A later U14 dry-run wrote a fail-closed collision precheck into the U13 QA path. No admitted U13 video, machine QA, human QA, final receipt, asset receipt, or admission file changed.",
        },
        "repair_policy": {
            "append_only": True,
            "u13_admission_rewritten": False,
            "historical_asset_receipt_rewritten": False,
            "collision_precheck_authority": "REVOKED_NON_AUTHORITATIVE_POST_ADMISSION_ARTIFACT",
            "authority_reanchored_directly_to_pinned_core": True,
        },
        "pinned_core": [
            {"path": rel(path), "sha256": expected, "verified": True}
            for path, expected in PINNED.items()
        ],
        "gates": {
            "video_immutable": True,
            "machine_qa_immutable_pass": True,
            "human_qa_immutable_pass": True,
            "final_receipt_immutable": True,
            "unit_admission_immutable_pass": True,
            "collision_fail_closed_and_classified": True,
        },
        "provider_posts": 0,
        "credits": 0,
        "release_status": "NOT_RELEASED_UNIT_ONLY",
    }
    write_json_atomic(OUTPUT, repair)

    queue = json.loads(WORK_QUEUE.read_text())
    queue["e40_u13_v4_post_admission_integrity"] = {
        "status": repair["status"],
        "repair_receipt": rel(OUTPUT),
        "repair_receipt_sha256": sha(OUTPUT),
        "video_sha256": PINNED[VIDEO],
        "admission_sha256": PINNED[ADMISSION],
        "provider_posts": 0,
        "credits": 0,
    }
    write_json_atomic(WORK_QUEUE, queue)
    with CODEX_LOG.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n\n## E40 integrity repair {now} — U13 post-admission precheck collision classified\n\n"
            f"- Append-only repair `{rel(OUTPUT)}` SHA=`{sha(OUTPUT)}` re-pins the unchanged U13 V4 video, machine QA, human QA, final receipt, asset receipt and unit admission. The later fail-closed precheck collision is explicitly non-authoritative; no U13 admission file was rewritten. Provider posts/credits=0.\n"
        )
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({"status": repair["status"], "repair_receipt": rel(OUTPUT), "sha256": sha(OUTPUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
