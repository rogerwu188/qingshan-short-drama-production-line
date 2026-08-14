#!/usr/bin/env python3
"""Fail-closed paid preflight for the one authorized E40 U12 Fast720 visual."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUBMITTER = Path("/Users/rogerwu/.local/share/backlotos/share/pipeline-tools/submit_giggle_video_manifest_v2.py")
INSTALLED_VERSION = Path("/Users/rogerwu/.local/share/backlotos/source/version")
EXPECTED_CANONICAL = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
EXPECTED_CANONICAL_MANIFEST = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"
EXPECTED_SOURCE_MANIFEST = "9198fe219f10e153dd68e0a73444f7251570b88d97ac820bdac8850296588306"
EXPECTED_FRAME = "da04eeec8c6b89910fb222699ecc8259175dc2b0fe683a0b330437dd78023f98"
EXPECTED_TTS = "36e1ab9a6955d1b821346b572f5b5a731253b406bb72d920bb8c98708d07e842"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_submitter():
    sys.path.insert(0, str(SUBMITTER.parent))
    spec = importlib.util.spec_from_file_location("e40_u12_installed_submitter", SUBMITTER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load installed submitter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--precheck", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    manifest_path = ROOT / args.manifest
    precheck_path = ROOT / args.precheck
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    precheck = json.loads(precheck_path.read_text(encoding="utf-8"))
    task = manifest["tasks"][0]
    submitter = load_submitter()
    submitter.ROOT = ROOT
    fingerprint = submitter.task_fingerprint(task)
    transaction_path = ROOT / "workflow/tasks/giggle_video_submit_transactions/E40" / f"{task['task_key']}__{fingerprint[:16]}.json"
    ledger = json.loads((ROOT / "workflow/work_queue.json").read_text(encoding="utf-8"))["e40_credits"]
    projected_charge = int(task["duration_seconds"]) * 16
    projected_net = int(ledger["net"]) + projected_charge

    historical_price_evidence = []
    for value in (
        "workflow/tasks/E40_U27_FAST720_SILENT_VISUAL_SUBMIT_20260809.json",
        "workflow/tasks/E40_U29A_V3_FAST720_EXACTLY_ONE_SUBMIT.json",
    ):
        path = ROOT / value
        data = json.loads(path.read_text(encoding="utf-8"))
        row = data["credit_reconciliation"]
        historical_price_evidence.append({
            "path": value,
            "sha256": sha256(path),
            "charged_credits": row["charged_credits"],
            "task_id": row["statement_rows"][0]["project_id"],
            "model": row["model"],
        })

    checks = {
        "installed_backlotos_v0_2_49": INSTALLED_VERSION.read_text(encoding="utf-8").strip() == "0.2.49",
        "api_key_present": bool(os.environ.get("GIGGLE_API_KEY", "").strip()),
        "canonical_script_sha": sha256(ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md") == EXPECTED_CANONICAL,
        "canonical_manifest_sha": sha256(ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json") == EXPECTED_CANONICAL_MANIFEST,
        "source_no_submit_manifest_sha": sha256(ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_nonvisible_mouth_transport_audit_v1/E40_U12_FAST720_SCENE_PRESERVING_NONVISIBLE_MOUTH_NO_SUBMIT_MANIFEST_V1.json") == EXPECTED_SOURCE_MANIFEST,
        "exact_first_frame_sha": sha256(ROOT / task["reference_images"][0]) == EXPECTED_FRAME,
        "accepted_tts_future_binding_sha": sha256(ROOT / task["post_exact_audio_contract"]["accepted_audio_path"]) == EXPECTED_TTS,
        "model_fast_only": task["model"] == "seedance-2.0-fast" and manifest["allowed_video_models"] == ["seedance-2.0-fast"],
        "native_720p": task["resolution"] == "720p",
        "silent_request": not task["reference_audio_asset_ids"] and not task["exact_dialogue_audio_asset_ids"] and not task["dialogue_lines"],
        "tts_attachment_closed": task["post_exact_audio_contract"]["attachment_allowed_now"] is False,
        "exactly_one_authorized": manifest["authorization"] is True and manifest["maximum_new_submissions"] == 1 and task["submission_authorization"]["maximum_new_submissions"] == 1,
        "installed_precheck_pass_zero_submit": precheck["status"] == "PASS" and precheck["submitted"] == 0 and precheck["precheck_pass"] == 1,
        "transaction_fingerprint_collision_zero": not transaction_path.exists(),
        "projected_net_within_cap": projected_net <= int(ledger["cap"]),
        "historical_fast_price_consistent_16_per_second": historical_price_evidence[0]["charged_credits"] == 112 and historical_price_evidence[1]["charged_credits"] == 64,
    }
    report = {
        "schema": "qingshan.e40.u12.fast720_paid_preflight.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS" if all(checks.values()) else "FAIL",
        "manifest": args.manifest,
        "manifest_sha256": sha256(manifest_path),
        "precheck": args.precheck,
        "precheck_sha256": sha256(precheck_path),
        "task_key": task["task_key"],
        "task_fingerprint": fingerprint,
        "transport_fingerprint": submitter.transport_fingerprint(task),
        "expected_transaction_path": str(transaction_path.relative_to(ROOT)),
        "transaction_exists_before_submit": transaction_path.exists(),
        "checks": checks,
        "ledger_before": ledger,
        "pricing": {
            "fast720_credits_per_second": 16,
            "duration_seconds": task["duration_seconds"],
            "projected_charge": projected_charge,
            "projected_net": projected_net,
            "projected_remaining": int(ledger["cap"]) - projected_net,
            "evidence": historical_price_evidence,
        },
        "request_audio_contract": task["video_audio_contract"],
        "future_tts_binding": task["post_exact_audio_contract"],
        "policy": "Fail closed before provider POST. Exactly one POST may follow only when this report is PASS and an explicit authorization receipt binds these exact SHAs and fingerprints.",
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "task_fingerprint": fingerprint, "transaction_exists": transaction_path.exists(), "projected_charge": projected_charge}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
