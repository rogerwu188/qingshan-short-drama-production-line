#!/usr/bin/env python3
"""Validate the U29C V6 changed-prompt capability contract without external calls."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    contract_path = resolve(args.contract)
    contract = load(contract_path)
    failures: list[str] = []

    memory_ref = contract.get("failure_memory") or {}
    memory_path = resolve(str(memory_ref.get("path") or ""))
    memory_sha = digest(memory_path) if memory_path.is_file() else None
    if memory_sha != memory_ref.get("sha256"):
        failures.append("FAILURE_MEMORY_SHA_MISMATCH")

    changed = contract.get("changed_prompt") or {}
    prompt_path = resolve(str(changed.get("path") or ""))
    prompt_sha = digest(prompt_path) if prompt_path.is_file() else None
    if prompt_sha != changed.get("sha256"):
        failures.append("CHANGED_PROMPT_SHA_MISMATCH")
    if prompt_sha == (contract.get("failed_v5") or {}).get("prompt_sha256"):
        failures.append("UNCHANGED_PROMPT_REPLAY")
    prompt_text = prompt_path.read_text(encoding="utf-8") if prompt_path.is_file() else ""
    required_clauses = [
        "地砖交点",
        "包围框中心位置不变",
        "像素高度变化不超过2%",
        "禁止迈步",
        "动作限定在颈部以上",
        "双唇物理闭合",
        "下颌不可开合",
    ]
    missing_clauses = [value for value in required_clauses if value not in prompt_text]
    if missing_clauses:
        failures.append("MATERIAL_PROMPT_CLAUSE_MISSING")

    evidence = contract.get("current_provider_evidence") or {}
    registry_path = resolve(str(evidence.get("registry_path") or ""))
    registry_sha = digest(registry_path) if registry_path.is_file() else None
    if registry_sha != evidence.get("registry_sha256"):
        failures.append("PROVIDER_REGISTRY_SHA_MISMATCH")
    registry = load(registry_path) if registry_path.is_file() else {}
    giggle = ((registry.get("providers") or {}).get("giggle") or {})
    transport = giggle.get("transport_capabilities") or {}
    image_to_video = transport.get("image_to_video") or {}
    fast = (giggle.get("model_capabilities") or {}).get("seedance-2.0-fast") or {}
    fast720 = "720p" in (fast.get("resolutions") or [])
    decoded_frame0_guaranteed = image_to_video.get("pixel_exact_output_guarantee") is True
    zero_audio_guaranteed = image_to_video.get("enforceable_zero_audio_output") is True

    future = contract.get("future_authorization_gate") or {}
    contract_closed = (
        future.get("status") == "CLOSED"
        and future.get("provider_post_allowed") is False
        and future.get("transaction_creation_allowed") is False
        and int(future.get("maximum_new_submissions", -1)) == 0
    )
    execution_permitted = bool(
        not failures
        and memory_sha
        and prompt_sha
        and fast720
        and decoded_frame0_guaranteed
        and zero_audio_guaranteed
    )
    if execution_permitted:
        failures.append("CURRENT_REGISTRY_UNEXPECTEDLY_SATISFIES_EXECUTION_CAPABILITIES")
    if not contract_closed:
        failures.append("CONTRACT_NOT_FAIL_CLOSED")

    status = "PASS_EXPECTED_FAIL_CLOSED_NO_SUBMIT" if not failures else "FAIL"
    report = {
        "schema": "qingshan.e40.u29c.v7.capability_contract_validator.v1",
        "episode": "E40",
        "unit_id": "U29C",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "contract": str(contract_path.relative_to(ROOT)),
        "contract_sha256": digest(contract_path),
        "failure_memory_sha256": memory_sha,
        "changed_prompt_sha256": prompt_sha,
        "failed_prompt_sha256": (contract.get("failed_v5") or {}).get("prompt_sha256"),
        "missing_material_prompt_clauses": missing_clauses,
        "provider_registry_sha256": registry_sha,
        "capabilities": {
            "seedance_2_0_fast_720p_supported": fast720,
            "decoded_frame0_pixel_authority_guaranteed": decoded_frame0_guaranteed,
            "enforceable_zero_audio_output_guaranteed": zero_audio_guaranteed,
        },
        "execution_permitted": execution_permitted,
        "contract_closed": contract_closed,
        "failures": failures,
        "side_effects": {
            "provider_calls": 0,
            "transactions": 0,
            "credits": 0,
            "retries": 0,
            "agentcut": 0,
            "assembly": 0,
        },
        "next_action": "Keep execution closed. No provider call is permitted until both enforceable capabilities have independent authority and a new explicit authorization exists.",
    }
    output = resolve(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".part")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"status": status, "out": str(output), "failures": failures}, ensure_ascii=False))
    return 0 if status.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
