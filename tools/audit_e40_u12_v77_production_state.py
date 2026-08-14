#!/usr/bin/env python3
"""Snapshot current E40 local production state without external side effects."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
QUEUE = ROOT / "workflow/work_queue.json"
STATE = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
SCRIPT_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
MANIFEST_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    queue = json.loads(QUEUE.read_text())
    scheduler = json.loads(STATE.read_text())
    credits = queue.get("e40_credits", {})
    full25 = queue.get("latest_e40_full25_next_unit_audit", {})
    u12 = queue.get("latest_e40_u12_v4_new_plate_fast720_terminal_quarantine", {})
    u29c = queue.get("latest_e40_u29c_fast720_terminal_quarantine", {})
    final_chain = queue.get("latest_e40_u29b_independent_material_admission_final_chain_hold", {})
    checks = {
        "canonical_script_exact": sha256(SCRIPT) == SCRIPT_SHA,
        "canonical_manifest_exact": sha256(MANIFEST) == MANIFEST_SHA,
        "queue_canonical_exact": queue.get("canonical", {}).get("script_sha256") == SCRIPT_SHA and queue.get("canonical", {}).get("manifest_sha256") == MANIFEST_SHA,
        "credits_exact": (credits.get("gross_pay"), credits.get("refund"), credits.get("net")) == (1437, 128, 1309),
        "active_remote_pay_zero": credits.get("active_remote_image_pay") == 0 and credits.get("active_remote_video_pay") == 0,
        "only_fast_model": queue.get("rules", {}).get("only_video_model") == "seedance-2.0-fast" and set(queue.get("rules", {}).get("forbidden_video_models", [])) == {"seedance-2.0-pro", "seedance-2.0-mini", "seedance-2.0"},
        "generation_gate_fail_closed": full25.get("status") == "PASS_25_OF_25_NO_FOURTH_FAST720_CANDIDATE",
        "u12_qa_quarantined": u12.get("status") == "QUARANTINED_NO_RETRY",
        "u29c_qa_quarantined": u29c.get("status") == "FAIL_HARD_FRAME0_AUDIO_ACTION_MOUTH_QUARANTINED_NO_RETRY",
        "asset_final_chain_disabled": final_chain.get("status") == "PASS_EXACT_U29A_TO_U29B_READINESS_BINDING_FINAL_CHAIN_SLOT_DISABLED_NO_ASSEMBLY",
        "episode_not_terminal": scheduler.get("heartbeat_integration", {}).get("episode_terminal") is False,
    }
    ok = all(checks.values())
    result = {
        "schema": "qingshan.e40.u12.v77.production_state.v1",
        "status": "PASS_CURRENT_STATE_EXACT_EPISODE_NONTERMINAL_FAIL_CLOSED" if ok else "FAIL",
        "checks": checks,
        "canonical": {"script_sha256": sha256(SCRIPT), "manifest_sha256": sha256(MANIFEST)},
        "work_queue": {"sha256": sha256(QUEUE), "status": queue.get("status"), "mode": queue.get("mode")},
        "credits": {k: credits.get(k) for k in ("gross_pay", "refund", "net", "remaining", "active_remote_image_pay", "active_remote_video_pay")},
        "gates": {"generation": full25.get("status"), "u12_qa": u12.get("status"), "u29c_qa": u29c.get("status"), "assets_final_chain": final_chain.get("status")},
        "episode_terminal": False,
        "authorization": False,
        "maximum_new_submissions": 0,
        "provider_calls": 0,
        "transactions": 0,
        "credits_spent": 0,
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
