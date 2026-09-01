#!/usr/bin/env python3
"""Resolve the authoritative Writer run receipt for one episode version.

Why this exists (R431 F-R431-01, re-reported by R432):

`E51_V4_WRITER_RUN_RECEIPT.json` -- the customary filename that every
per-episode builder in `tools/` constructs by string format -- holds an
**ABORTED** receipt whose `authority_output` is null.  The authoritative
COMPLETED receipt for E51 v4 lives at
`E51_V4_WRITER_RUN_RECEIPT_ATTEMPT2.json`, because SUPERVISOR_ORDERS seq=53
conditions[1] ordered a new receipt path after the clean abort rather than an
overwrite (receipt terminal states are not overwritable).  E51 v4 is the next
episode cleared to enter pre-production, so the next builder that copies the
customary-path formatting from its predecessor will bind the wrong receipt.

This module is a **lookup, not a gate**.  It never refuses anything and is not
registered in the gate registry (铁律一: an unregistered criterion must not
block a workstation).  It answers one question -- "which receipt file is the
authority for E{NN} v{n}?" -- from the receipt payloads themselves, so callers
stop deriving that answer from a filename.

Resolution rule: among every receipt in the directory whose payload declares
this episode and version, the authority is the unique one with
`status == "COMPLETED"` and a well-formed `authority_output.sha256`.  Filenames
are used only to narrow the read set; the verdict comes from payload fields.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SHA256 = re.compile(r"^[0-9a-f]{64}$")
RECEIPT_GLOB = "*WRITER_RUN_RECEIPT*.json"

STATUS_RESOLVED = "RESOLVED"
STATUS_NONE = "NO_AUTHORITATIVE_RECEIPT"
STATUS_AMBIGUOUS = "AMBIGUOUS_AUTHORITATIVE_RECEIPTS"


EPISODE_FORM = re.compile(r"^[eE]?0*(\d+)$")
VERSION_FORM = re.compile(r"^[vV]?0*(\d+)$")


def normalize_episode(episode: Any) -> str:
    """`51`, `e51`, `E51`, `E051` all name the same episode.

    R437 F-R437-01 / R438 F-R438-02: `--episode 51` produced a false
    `NO_AUTHORITATIVE_RECEIPT` for an episode that has one, because the raw
    argument was compared against the receipt payload's `E51`.  Normalising on
    the way in removes the wrong-answer surface; nothing about the resolution
    rule changes -- the verdict still comes from payload fields only.
    Un-parseable input is passed through untouched rather than guessed at.
    """
    match = EPISODE_FORM.match(str(episode).strip())
    return f"E{match.group(1)}" if match else str(episode)


def normalize_version(version: Any) -> str:
    """`4`, `"4"`, `v4`, `V4`, `04` all name the same version.

    Same defect, other half: `_same_version` already accepted every one of
    these when matching payloads, but `customary_name` interpolated the raw
    argument, so `--version V4` looked for `E51_VV4_WRITER_RUN_RECEIPT.json`,
    found nothing, and answered `customary_is_authoritative=false` for an
    episode whose customary path is in fact the authority.
    """
    match = VERSION_FORM.match(str(version).strip())
    return match.group(1) if match else str(version)


def customary_name(episode: str, version: int | str) -> str:
    """The filename shape that ~80 call sites in tools/ format by hand."""
    return f"{normalize_episode(episode)}_V{normalize_version(version)}_WRITER_RUN_RECEIPT.json"


def _same_version(left: Any, right: Any) -> bool:
    """String and integer forms of the same number are the same value.

    Per erratum CLAUDE-SUP-20260829-E49V5-E50V5-VERSION-FIELD-NON-AUTHORITATIVE
    (CL2X-1291 (4)), which fixed the same string/int question for the manifest.
    """
    for text in ("v", "V"):
        left = str(left).lstrip(text) if isinstance(left, str) else left
        right = str(right).lstrip(text) if isinstance(right, str) else right
    try:
        return int(left) == int(right)
    except (TypeError, ValueError):
        return str(left) == str(right)


def is_authoritative(payload: dict[str, Any]) -> bool:
    if payload.get("status") != "COMPLETED":
        return False
    authority = payload.get("authority_output")
    if not isinstance(authority, dict):
        return False
    return bool(SHA256.fullmatch(str(authority.get("sha256") or "")))


def receipt_candidates(
    receipts_dir: Path, episode: str, version: int | str
) -> list[dict[str, Any]]:
    """Every readable receipt in the directory that declares this episode/version."""
    rows: list[dict[str, Any]] = []
    for path in sorted(receipts_dir.glob(RECEIPT_GLOB)):
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if normalize_episode(payload.get("episode") or "") != normalize_episode(episode):
            continue
        if not _same_version(payload.get("version"), version):
            continue
        rows.append(
            {
                "path": str(path),
                "status": payload.get("status"),
                "writer_run_id": payload.get("writer_run_id"),
                "authoritative": is_authoritative(payload),
                "authority_sha256": (payload.get("authority_output") or {}).get("sha256")
                if isinstance(payload.get("authority_output"), dict)
                else None,
            }
        )
    return rows


def resolve(receipts_dir: Path, episode: str, version: int | str) -> dict[str, Any]:
    receipts_dir = Path(receipts_dir).resolve()
    candidates = receipt_candidates(receipts_dir, episode, version)
    authoritative = [row for row in candidates if row["authoritative"]]
    customary = receipts_dir / customary_name(episode, version)

    if len(authoritative) == 1:
        status = STATUS_RESOLVED
        resolved_path: str | None = authoritative[0]["path"]
    elif not authoritative:
        status = STATUS_NONE
        resolved_path = None
    else:
        status = STATUS_AMBIGUOUS
        resolved_path = None

    return {
        "schema": "qingshan.writer_receipt_resolution.v1",
        "status": status,
        "episode": str(episode),
        "version": version,
        "episode_normalized": normalize_episode(episode),
        "version_normalized": normalize_version(version),
        "receipts_dir": str(receipts_dir),
        "authoritative_receipt": resolved_path,
        "customary_path": str(customary),
        "customary_exists": customary.is_file(),
        "customary_is_authoritative": bool(
            resolved_path is not None and Path(resolved_path) == customary
        ),
        "candidates": candidates,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--receipts-dir", required=True, type=Path)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args(argv)

    verdict = resolve(args.receipts_dir, args.episode, args.version)
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    # A non-zero exit reports "I could not answer", never "you may not proceed".
    return 0 if verdict["status"] == STATUS_RESOLVED else 3


if __name__ == "__main__":
    raise SystemExit(main())
