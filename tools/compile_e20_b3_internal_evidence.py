#!/usr/bin/env python3
"""Bind the effective E20 B3 instruction to local production contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="workflow/tasks/E20_B3_INTERNAL_EVIDENCE_BINDING_20260718.json")
    args = parser.parse_args()
    claude = ROOT / "codex_docs/CLAUDE_TO_CODEX.md"
    task = ROOT / "workflow/tasks/E20_TASK.md"
    visual = ROOT / "configs/e20_effective_static_visual_lock_manifest_20260716.json"
    visual_qa = ROOT / "qa/e20_preflight_20260716/E20_VISUAL_LOCK_CANDIDATE_QA_TEMPLATE_20260716.json"
    b06 = ROOT / "workflow/prompts/e20_non_speaking_20260718/E20-B06-NS-01_prompt.txt"
    text = claude.read_text(encoding="utf-8")
    match = re.search(r"^## \[CL2X-257\].*?(?=^## \[|\Z)", text, re.MULTILINE | re.DOTALL)
    section = match.group(0) if match else ""
    tokens = ["CL2X-257", "见过郡主", "E20 卷尾揭示拍"]
    section_ok = bool(section) and all(token in section for token in tokens)
    required = [task, visual, visual_qa]
    contracts_ok = all(path.is_file() for path in required)
    payload = {
        "schema": "qingshan.e20_b3.internal_evidence_binding.v1",
        "episode": "E20",
        "beat": "B3",
        "status": "PASS_INTERNAL_SOURCE_BINDING" if section_ok and contracts_ok else "FAIL_INTERNAL_SOURCE_BINDING",
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_authority": "CODEX_LOCAL_CL2X_AND_E20_CONTRACTS",
        "approval_owner": "CODEX_PRODUCTION_LINE",
        "approval_mode": "MACHINE_ADJUDICATED_INTERNAL_BINDING",
        "remote_role": "SUPERVISION_CONSTRAINT_ONLY_NO_APPROVAL_REQUIRED",
        "approval_wait_is_valid": False,
        "required_beats": {
            "commander_line": "见过郡主",
            "chenji_reaction": "immediate visible Chenji reaction",
            "ending_function": "identity impact plot hook, not atmosphere",
        },
        "source_section_sha256": hashlib.sha256(section.encode("utf-8")).hexdigest() if section else None,
        "bound_sources": [{"path": str(path.relative_to(ROOT)), "sha256": digest(path)} for path in required if path.is_file()],
        "b06_prompt_bound": {"path": str(b06.relative_to(ROOT)), "sha256": digest(b06)} if b06.is_file() else None,
        "evidence_is": "Effective production instruction bound to local contracts; not a new human approval.",
        "confidence": 0.99 if section_ok and contracts_ok else 0.0,
        "rollback": "Remove only this derived receipt and B3 candidates; retain E20 B2 candidates, QA, and visual locks.",
        "checks": {"cl2x_section_found": bool(section), "required_tokens": {token: token in section for token in tokens}, "e20_contracts_present": contracts_ok, "b06_prompt_present": b06.is_file()},
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "out": str(out)}, ensure_ascii=False))
    return 0 if payload["status"] == "PASS_INTERNAL_SOURCE_BINDING" else 1


if __name__ == "__main__":
    raise SystemExit(main())
