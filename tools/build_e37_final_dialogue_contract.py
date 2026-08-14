#!/usr/bin/env python3
"""Build the E37 final-audio dialogue contract directly from the canonical script."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E37剧本_ClaudeWriter_v2.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E37_manifest_v2.json"
OUT = ROOT / "qa/e37_agentcut_20260803/v1_accepted_only/E37_FINAL_31_LINE_DIALOGUE_CONTRACT.json"
LINE_RE = re.compile(r"^(陈迹|皎兔|云羊)：(?:（[^）]*）)?(.*)$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    rows = []
    for script_line, raw in enumerate(SCRIPT.read_text(encoding="utf-8").splitlines(), 1):
        match = LINE_RE.match(raw.strip())
        if not match:
            continue
        text = re.sub(r"[*\"“”]", "", match.group(2)).strip()
        rows.append({"line_id": len(rows) + 1, "script_line": script_line, "speaker": match.group(1), "spoken_text": text})
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = int(manifest["dialogue_lines"])
    if len(rows) != expected:
        raise RuntimeError(f"canonical dialogue count mismatch: {len(rows)} != {expected}")
    payload = {
        "schema": "qingshan.e37.final_dialogue_contract.v1",
        "episode": "E37",
        "status": "PASS_31_OF_31_CANONICAL_DIALOGUE_LINES",
        "canonical_script": str(SCRIPT.relative_to(ROOT)),
        "canonical_script_sha256": sha256(SCRIPT),
        "canonical_manifest": str(MANIFEST.relative_to(ROOT)),
        "canonical_manifest_sha256": sha256(MANIFEST),
        "dialogue": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "out": str(OUT.relative_to(ROOT)), "sha256": sha256(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
