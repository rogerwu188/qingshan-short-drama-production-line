#!/usr/bin/env python3
"""Bridge qingshan-review image requests to the authenticated Codex vision runtime."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
SCHEMA_PATH = ROOT / "tools" / "schemas" / "qingshan_image_visual_adjudication_v1.schema.json"
CACHE_ROOT = ROOT / "workflow" / "runtime_cache" / "image_visual_v2"
REQUIRED_CHECKS = (
    "canonical_identity_continuity",
    "scene_authority",
    "story_action_clarity",
    "no_text_or_pseudotext",
    "no_extra_or_duplicated_bodies",
    "native_anatomy",
)


def continuity_evidence_paths(request: dict, candidate: Path) -> list[Path]:
    """Return only episode-scoped continuity evidence declared by this item."""
    metadata = request.get("metadata") or {}
    raw = metadata.get("continuity_evidence_paths") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise SystemExit("continuity_evidence_paths must be a string or list")

    evidence: list[Path] = []
    for value in raw:
        path = Path(str(value)).expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"continuity evidence missing: {path}")
        if path != candidate and path not in evidence:
            evidence.append(path)
    return evidence


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_prompt(request: dict) -> str:
    metadata = request.get("metadata") or {}
    focus = request.get("review_focus") or metadata.get("review_focus") or []
    return (
        "You are the machine visual QA runtime for the Qingshan short-drama factory. "
        "Inspect the attached full-resolution candidate image itself. Do not use tools, "
        "do not edit files, and do not infer a PASS from filenames or prior reports. "
        "Judge every required check as PASS or FAIL against the supplied production authority. "
        "The first image is the exact candidate. Any later attached images are continuity evidence "
        "explicitly declared by this request for the same episode; use them only for cross-shot identity "
        "continuity. Judge identity from explicit age/gender/species/spirit-form/costume cues. Do not fail "
        "merely because no external portrait reference or continuity sheet was supplied. "
        "Pseudo-text, malformed lettering, subtitles, logos, and watermarks fail no_text_or_pseudotext. "
        "Return only JSON matching the provided schema.\n\n"
        f"Exact candidate SHA-256: {request['candidate_sha256']}\n"
        f"Metadata: {json.dumps(metadata, ensure_ascii=False)}\n"
        f"Review focus: {json.dumps(focus, ensure_ascii=False)}\n"
        "Required checks: " + ", ".join(REQUIRED_CHECKS)
    )


def main() -> int:
    request = json.load(sys.stdin)
    if request.get("schema") != "qingshan.image_visual_runtime.request.v1":
        raise SystemExit("unsupported request schema")
    path = Path(request["path"]).expanduser().resolve()
    digest = sha256(path)
    if digest != request.get("candidate_sha256"):
        raise SystemExit("candidate SHA mismatch")

    cache_path = CACHE_ROOT / f"{digest}.json"
    if cache_path.is_file():
        cached = json.loads(cache_path.read_text())
        if cached.get("candidate_sha256") == digest:
            print(json.dumps(cached, ensure_ascii=False))
            return 0 if cached.get("status") == "PASS" else 1

    with tempfile.TemporaryDirectory(prefix="qingshan-codex-vision-") as temp_dir:
        output_path = Path(temp_dir) / "result.json"
        codex_command = os.environ.get("QINGSHAN_CODEX_COMMAND", "codex").strip()
        command = [
            *shlex.split(codex_command),
            "exec",
            "--model",
            "gpt-5.4",
            "--ephemeral",
            "--skip-git-repo-check",
            "--ignore-rules",
            "--sandbox",
            "read-only",
            "--cd",
            str(ROOT),
            "--image",
            str(path),
        ]
        for evidence_path in continuity_evidence_paths(request, path):
            command.extend(["--image", str(evidence_path)])
        command.extend(
            [
                "--output-schema",
                str(SCHEMA_PATH),
                "--output-last-message",
                str(output_path),
                build_prompt(request),
            ]
        )
        completed = subprocess.run(command, capture_output=True, text=True, timeout=165)
        if completed.returncode != 0 or not output_path.is_file():
            sys.stderr.write((completed.stderr or completed.stdout)[-4000:])
            return 2
        result = json.loads(output_path.read_text())

    result["schema"] = "qingshan.image_visual_adjudication.v1"
    result["candidate_sha256"] = digest
    evidence = result.get("evidence") or []
    if len(evidence) != 1:
        raise SystemExit("runtime must return exactly one evidence row")
    evidence[0]["sha256"] = digest
    evidence[0]["source_id"] = (request.get("metadata") or {}).get("source_id") or (
        request.get("metadata") or {}
    ).get("clip_id") or path.stem
    regions = evidence[0].get("regions") or []
    if isinstance(regions, list):
        description = "; ".join(
            str(row.get("description", "")) for row in regions if isinstance(row, dict)
        ) or "full-frame visual inspection"
        evidence[0]["regions"] = {
            check: {"label": "full_frame", "description": description}
            for check in REQUIRED_CHECKS
        }
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
