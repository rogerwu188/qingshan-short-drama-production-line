#!/usr/bin/env python3
"""Verify chapter raw files against one explicitly authoritative checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_checkpoint(path: Path) -> dict[int, str]:
    records: dict[int, str] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = [field.strip() for field in line.split("\t")]
        chapter = next(
            (int(field) for field in fields if field.isdigit()),
            None,
        )
        digest = next(
            (field.lower() for field in fields if SHA256_RE.fullmatch(field)),
            None,
        )
        if chapter is None or digest is None:
            if line_number == 1:
                continue
            raise ValueError(f"invalid checkpoint line {line_number}")
        existing = records.get(chapter)
        if existing and existing != digest:
            raise ValueError(f"conflicting canonical SHA for chapter {chapter}")
        records[chapter] = digest
    if not records:
        raise ValueError("canonical checkpoint is empty")
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--canonical-checkpoint", type=Path)
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--start", type=int)
    parser.add_argument("--end", type=int)
    args = parser.parse_args()

    project_root = args.project_root.expanduser().resolve()
    checkpoint = (
        args.canonical_checkpoint.expanduser().resolve()
        if args.canonical_checkpoint
        else project_root / "source/corpus/checkpoint.tsv"
    )
    raw_dir = (
        args.raw_dir.expanduser().resolve()
        if args.raw_dir
        else project_root / "source/corpus/raw"
    )
    records = load_checkpoint(checkpoint)
    start = args.start if args.start is not None else min(records)
    end = args.end if args.end is not None else max(records)
    selected = {
        chapter: digest
        for chapter, digest in records.items()
        if start <= chapter <= end
    }
    if not selected:
        raise ValueError("requested chapter range is absent from canonical checkpoint")

    mismatches: list[dict[str, object]] = []
    for chapter, expected in sorted(selected.items()):
        raw = raw_dir / f"chapter-{chapter}.html"
        actual = sha256(raw) if raw.is_file() else None
        if actual != expected:
            mismatches.append(
                {
                    "chapter": chapter,
                    "raw": str(raw),
                    "expected": expected,
                    "actual": actual,
                }
            )

    secondary = sorted(
        str(path)
        for path in checkpoint.parent.glob("checkpoint*.tsv")
        if path.resolve() != checkpoint
    )
    result = {
        "schema": "qingshan.writer.checkpoint_guard.v1",
        "status": "PASS" if not mismatches else "FAIL",
        "project_root": str(project_root),
        "canonical_checkpoint": str(checkpoint),
        "canonical_checkpoint_sha256": sha256(checkpoint),
        "secondary_checkpoints_ignored": secondary,
        "verified_start": start,
        "verified_end": end,
        "verified_count": len(selected) - len(mismatches),
        "mismatches": mismatches,
        "merge_policy": "EXACT_CANONICAL_ONLY_NEVER_GLOB_MERGE",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
