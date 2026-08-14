#!/usr/bin/env python3
"""Admit evidence-bound QA failures into prompt memory without duplicates."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MEMORY = ROOT / "workflow/local_lora/seedance2_prompt_failure_training.jsonl"
REQUIRED = (
    "sample_id", "episode", "generation_mode", "applicable_modes",
    "failure_receipt", "failed_prompt", "failed_asset", "root_cause",
    "optimization", "compiler_guard_clause", "admission_gate", "tags",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence_path(root: Path, value: str) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError(f"evidence path escapes project root: {value}")
    if not resolved.is_file():
        raise ValueError(f"evidence file is missing: {value}")
    return resolved


def ingest_candidate(candidate: dict, memory_path: Path = DEFAULT_MEMORY, root: Path = ROOT) -> dict:
    root = root.resolve()
    missing = [field for field in REQUIRED if not candidate.get(field)]
    if missing:
        raise ValueError("missing required fields: " + ", ".join(missing))
    status = candidate.get("status", "ACTIVE_REWRITE_PENDING_POSITIVE")
    if status not in {"ADMITTED", "ACTIVE_REWRITE_PENDING_POSITIVE"}:
        raise ValueError("status must be ADMITTED or ACTIVE_REWRITE_PENDING_POSITIVE")
    if status == "ADMITTED" and (not candidate.get("accepted_prompt") or not candidate.get("accepted_asset")):
        raise ValueError("ADMITTED samples require accepted_prompt and accepted_asset")

    row = {
        "schema": "qingshan.seedance_prompt_lora_training_sample.v1",
        **candidate,
        "status": status,
    }
    for field in ("failure_receipt", "failed_prompt", "failed_asset"):
        evidence = _evidence_path(root, str(row[field]))
        row[f"{field}_sha256"] = sha256(evidence)
    if status == "ADMITTED":
        for field in ("accepted_prompt", "accepted_asset"):
            evidence = _evidence_path(root, str(row[field]))
            row[f"{field}_sha256"] = sha256(evidence)

    fingerprint_source = "|".join((
        row["failed_prompt_sha256"], row["failed_asset_sha256"],
        str(row["root_cause"]), str(row["optimization"]),
    ))
    row["failure_fingerprint_sha256"] = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()

    memory_path = memory_path.resolve()
    existing: list[dict] = []
    if memory_path.is_file():
        existing = [json.loads(line) for line in memory_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for prior in existing:
        if prior.get("sample_id") == row["sample_id"]:
            if prior.get("failure_fingerprint_sha256") == row["failure_fingerprint_sha256"]:
                return {"ok": True, "status": "DEDUPED", "sample_id": row["sample_id"], "memory_path": str(memory_path)}
            raise ValueError(f"sample_id already exists with different evidence: {row['sample_id']}")
        if prior.get("failure_fingerprint_sha256") == row["failure_fingerprint_sha256"]:
            return {"ok": True, "status": "DEDUPED", "sample_id": prior["sample_id"], "memory_path": str(memory_path)}

    memory_path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in [*existing, row])
    fd, temporary = tempfile.mkstemp(prefix=f".{memory_path.name}.", dir=memory_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, memory_path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return {
        "ok": True,
        "status": "ADMITTED" if status == "ADMITTED" else "ACTIVE_REWRITE_PENDING_POSITIVE",
        "sample_id": row["sample_id"],
        "failure_fingerprint_sha256": row["failure_fingerprint_sha256"],
        "memory_path": str(memory_path),
        "memory_sha256": sha256(memory_path),
        "sample_count": len(existing) + 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--memory", default=str(DEFAULT_MEMORY))
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--receipt")
    args = parser.parse_args()
    candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    result = ingest_candidate(candidate, Path(args.memory), Path(args.root))
    if args.receipt:
        Path(args.receipt).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
