#!/usr/bin/env python3
"""Bind a review to the provider request that is actually sent.

Plan §7.  Every earlier receipt binds a FILE — the prompt file, the reference
files — and later steps (H3 re-render, reference reordering, voice attachment,
send-time image compression) can change what the provider receives without
touching any bound sha.  This module defines one digest over the request as
the submitter is about to POST it, so a reviewer can bind to that, and the
submitter can refuse — before any intent record, with zero POSTs — when the two
no longer match.

What the digest covers (the semantic request):
  prompt text, model, duration, aspect ratio, resolution, the ORDERED list of
  reference images by on-disk sha256 (with their declared roles), and the
  ordered audio references.
What it deliberately does not cover: the base64 bytes of each image.  Oversized
references are re-encoded at send time on a temp copy (giggle_api_client); that
is transport, recorded separately as sent_reference_sha256, and reviewing it
would make every review depend on a JPEG encoder.

Off for every episode by default (configs/PROVIDER_REQUEST_REVIEW_BINDING_V1.json).
A task that carries reviewed_request_sha256 is always checked, policy or not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "qingshan.provider_request_digest.v1"
POLICY = Path(__file__).resolve().parents[1] / "configs" / "PROVIDER_REQUEST_REVIEW_BINDING_V1.json"


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request_digest(
    *,
    prompt_text: str,
    model: Any,
    duration: Any = None,
    aspect_ratio: Any = None,
    resolution: Any = None,
    reference_sha256: Iterable[str] = (),
    reference_roles: Iterable[Any] | None = None,
    audio: Iterable[Any] = (),
) -> str:
    refs = list(reference_sha256)
    roles = list(reference_roles or [None] * len(refs))
    if len(roles) != len(refs):
        roles = (roles + [None] * len(refs))[: len(refs)]
    canonical = {
        "schema": SCHEMA,
        "prompt_sha256": _sha_bytes(str(prompt_text).encode("utf-8")),
        "model": str(model or ""),
        "duration": duration if duration is None else float(duration),
        "aspect_ratio": str(aspect_ratio or ""),
        "resolution": str(resolution or ""),
        # Order is part of the request: the provider reads @Image1..N by position.
        "references": [{"index": i, "sha256": sha, "role": (str(role) if role else None)}
                       for i, (sha, role) in enumerate(zip(refs, roles), 1)],
        "audio": [str(value) for value in audio],
    }
    return _sha_bytes(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def reference_roles_of(task: dict[str, Any]) -> list[Any]:
    """Roles in transmission order, when the task records them; None otherwise."""
    sequence = task.get("reference_image_sequence") or []
    if sequence and len(sequence) == len(task.get("reference_images") or []):
        return [row.get("role") if isinstance(row, dict) else None for row in sequence]
    return [None] * len(task.get("reference_images") or [])


def task_request_digest(task: dict[str, Any], *, prompt_text: str, reference_paths: list[Path],
                        duration: Any = None, audio: Iterable[Any] = ()) -> dict[str, Any]:
    """Digest of the request built from the very values the submitter will send."""
    shas = [_sha_bytes(Path(p).read_bytes()) for p in reference_paths]
    digest = request_digest(
        prompt_text=prompt_text, model=task.get("model"), duration=duration,
        aspect_ratio=task.get("aspect_ratio", "9:16"), resolution=task.get("resolution"),
        reference_sha256=shas, reference_roles=reference_roles_of(task), audio=audio,
    )
    return {"request_sha256": digest, "reference_sha256_in_send_order": shas}


def sent_audio_references(task: dict[str, Any]) -> list[str]:
    """The audio list exactly as the video submitter sends it: asset ids win, else URLs."""
    asset_ids = [*(task.get("exact_dialogue_audio_asset_ids") or []), *(task.get("reference_audio_asset_ids") or [])]
    if asset_ids:
        return [f"asset_id:{v}" for v in asset_ids]
    urls = [*(task.get("exact_dialogue_audio_urls") or []), *(task.get("reference_audio_urls") or [])]
    return [f"url:{v}" for v in urls]


def sent_image_sha256(images: Iterable[Any]) -> list[str]:
    """sha256 of each image exactly as transmitted (after any send-time re-encode).

    Transport evidence, not part of the reviewed digest: it shows whether the
    bytes the provider received are the bytes on disk.
    """
    import base64
    out = []
    for row in images or []:
        if isinstance(row, dict) and row.get("base64"):
            out.append(_sha_bytes(base64.b64decode(row["base64"])))
        elif isinstance(row, dict) and (row.get("asset_id") or row.get("url")):
            out.append("ref:" + str(row.get("asset_id") or row.get("url")))
        else:
            out.append("unknown")
    return out


def binding_required(task: dict[str, Any]) -> bool:
    try:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    episode = str(task.get("episode") or "").upper()
    match = re.match(r"E(\d+)", episode)
    if not match:
        return False
    if episode[: match.end()] in {str(v).upper() for v in policy.get("enabled_episodes") or []}:
        return True
    start = policy.get("enabled_from_episode")
    return bool(isinstance(start, str) and re.fullmatch(r"E\d+", start.upper())
                and int(match.group(1)) >= int(start[1:]))


def require_reviewed_request(task: dict[str, Any], computed: str) -> dict[str, Any]:
    """Raise before any intent record when the sent request is not the reviewed one."""
    reviewed = str(task.get("reviewed_request_sha256") or "").strip()
    required = binding_required(task)
    if reviewed and reviewed != computed:
        raise ValueError(
            f"{task.get('task_key')} REVIEWED_REQUEST_MISMATCH: the request about to be sent "
            f"({computed[:16]}) is not the reviewed request ({reviewed[:16]}); something changed "
            "prompt text, model parameters, reference order or audio after review"
        )
    if required and not reviewed:
        raise ValueError(f"{task.get('task_key')} REVIEWED_REQUEST_NOT_BOUND: no review is bound to this request")
    return {"request_sha256": computed, "reviewed_request_sha256": reviewed or None,
            "binding_required": required,
            "status": "MATCH" if reviewed else ("NOT_REQUIRED" if not required else "MISSING")}


def bound_under_other_fingerprint(transaction_dir: Path, task_key: str, fingerprint: str) -> list[str]:
    """Transactions already bound to a provider task under a DIFFERENT fingerprint.

    The transaction store is keyed by task_key + fingerprint, so a recompile
    that changes any fingerprint input cannot see the earlier bound record and
    would POST again.  This finds those records.
    """
    hits = []
    for path in sorted(Path(transaction_dir).glob(f"{task_key}__*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(row.get("submission_fingerprint") or "") == fingerprint:
            continue
        if row.get("state") == "SUBMITTED_TASK_ID_BOUND" or row.get("task_id"):
            hits.append(str(row.get("submission_fingerprint") or path.name))
    return hits


def require_no_silent_resubmission(task: dict[str, Any], transaction_dir: Path, fingerprint: str) -> None:
    """Under the binding policy, a task_key already bound elsewhere needs an explicit supersede."""
    if not binding_required(task):
        return
    others = bound_under_other_fingerprint(transaction_dir, str(task.get("task_key")), fingerprint)
    declared = {str(v) for v in (task.get("supersedes_submission_fingerprints") or [])}
    undeclared = [fp for fp in others if fp not in declared]
    if undeclared:
        raise ValueError(
            f"{task.get('task_key')} BOUND_UNDER_OTHER_FINGERPRINT: already submitted as "
            f"{','.join(fp[:16] for fp in undeclared)}; a re-POST must declare "
            "supersedes_submission_fingerprints"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stamp reviewed_request_sha256 on each task of a manifest.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, help="defaults to overwriting --manifest")
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    def resolve(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else args.root / path

    stamped = []
    for task in manifest.get("tasks") or []:
        prompt = resolve(task["prompt_file"]).read_text(encoding="utf-8")
        refs = [resolve(p) for p in task.get("reference_images") or []]
        audio = sent_audio_references(task)
        duration = task.get("duration_seconds")
        result = task_request_digest(task, prompt_text=prompt, reference_paths=refs,
                                     duration=int(duration) if duration is not None else None, audio=audio)
        task["reviewed_request_sha256"] = result["request_sha256"]
        stamped.append(task["task_key"])
    (args.out or args.manifest).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")
    print(json.dumps({"stamped": len(stamped)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
