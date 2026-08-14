#!/usr/bin/env python3
"""Audit whether the latest E36 dialogue manifest covers the canonical contract."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
CONTRACT = PROD / "E36_DIALOGUE_NATIVE_VIDEO_CONTRACT_V1.json"
MANIFEST = PROD / "E36_DIALOGUE_MANIFEST_V12.json"
OUT = ROOT / "qa/e36_agentcut_20260730/E36_DIALOGUE_MANIFEST_V12_CANONICAL_COVERAGE_AUDIT_V1.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text: str) -> str:
    text = text.replace("**", "").replace("……", "")
    return "".join(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", text)).lower()


def main() -> int:
    contract = load(CONTRACT)
    manifest = load(MANIFEST)
    rows = manifest["rows"]
    manifest_stream = "".join(normalize(row.get("spoken_text", "")) for row in rows)

    results = []
    for index, line in enumerate(contract["lines"], start=1):
        normalized = normalize(line["text"])
        covered = bool(normalized) and normalized in manifest_stream
        results.append(
            {
                "contract_line_number": index,
                "speaker": line["speaker"],
                "text": line["text"],
                "normalized_text": normalized,
                "covered_by_manifest_v12": covered,
            }
        )

    covered_count = sum(row["covered_by_manifest_v12"] for row in results)
    omitted = [row for row in results if not row["covered_by_manifest_v12"]]
    payload = {
        "schema": "qingshan.e36_dialogue_manifest_canonical_coverage_audit.v1",
        "episode": "E36",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_cl2x": "CL2X-787",
        "source_mailbox_sha256": "f45fbf158922ab8eebc3651fb0fcae8f4b5cc5d3d9f237e564a1366aacc44387",
        "canonical_contract": {
            "path": str(CONTRACT.relative_to(ROOT)),
            "sha256": sha256(CONTRACT),
            "line_count": len(results),
            "source_script_sha256": contract["source_script_sha256"],
        },
        "latest_dialogue_manifest": {
            "path": str(MANIFEST.relative_to(ROOT)),
            "sha256": sha256(MANIFEST),
            "declared_status": manifest["status"],
            "row_count": len(rows),
            "source_script_sha256": manifest["source_script_sha256"],
        },
        "coverage": {
            "covered_canonical_lines": covered_count,
            "canonical_line_count": len(results),
            "omitted_canonical_lines": len(omitted),
            "coverage_ratio": round(covered_count / len(results), 6),
            "status": "FAIL_INCOMPLETE_CANONICAL_DIALOGUE_MANIFEST" if omitted else "PASS",
        },
        "line_results": results,
        "omitted_lines": omitted,
        "gate_results": {
            "script_sha_binding": "PASS" if contract["source_script_sha256"] == manifest["source_script_sha256"] else "FAIL",
            "manifest_declared_status": manifest["status"],
            "canonical_dialogue_coverage": f"FAIL_{covered_count}_OF_{len(results)}" if omitted else "PASS",
            "agentcut_dialogue_gate": "BLOCKED_REQUIRE_ACCEPTED_SOURCE_TRANSCRIPT_AUDIT",
        },
        "blocked_by": "CANONICAL_DIALOGUE_MANIFEST_INCOMPLETE_AND_ACCEPTED_SOURCE_TRANSCRIPT_COVERAGE_UNPROVEN",
        "next_action": "Do not treat V12 PASS as full dialogue coverage. Bind every canonical line to an accepted source transcript, then rerun this gate before AgentCut assembly or release.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "sha256": sha256(OUT), "coverage": payload["coverage"]}, ensure_ascii=False))
    return 1 if omitted else 0


if __name__ == "__main__":
    raise SystemExit(main())
