#!/usr/bin/env python3
"""Resumable full-depth chapter-facts state machine for the Writer Agent."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from tools.agent_task_journal import (
        append_task_record,
        atomic_json,
        recover_task_state,
        verify_sha_sidecar,
    )
except ModuleNotFoundError:  # Direct execution from the packaged tools directory.
    from agent_task_journal import (  # type: ignore[no-redef]
        append_task_record,
        atomic_json,
        recover_task_state,
        verify_sha_sidecar,
    )


AGENT_ID = "qingshan-claude-writer"
ACTIVE_PHASES = {
    "READ_EVIDENCE",
    "MERGE_EVIDENCE",
    "DRAFT_FULL_FACT",
    "VALIDATE",
    "APPEND_ATOMIC",
    "NEXT_CHAPTER",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def require_absolute(path: Path, field: str) -> Path:
    if not path.is_absolute():
        raise ValueError(f"{field} must be absolute: {path}")
    return path.resolve()


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    path.with_suffix(path.suffix + ".sha256").write_text(
        sha256_bytes(data) + "\n", encoding="ascii"
    )


def atomic_jsonl(path: Path, rows: list[dict]) -> None:
    data = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    ).encode("utf-8")
    atomic_bytes(path, data)


def active_job_path(shared_root: Path) -> Path:
    root = require_absolute(shared_root, "shared_root")
    return root / "factory/agents" / AGENT_ID / "active_job.json"


def read_verified_json(path: Path) -> dict:
    if not verify_sha_sidecar(path):
        raise ValueError(f"SHA sidecar verification failed: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def read_facts(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    seen: set[int] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid facts JSON at line {line_number}") from exc
        chapter = row.get("n")
        if not isinstance(chapter, int):
            raise ValueError(f"facts n must be int at line {line_number}")
        if chapter in seen:
            raise ValueError(f"duplicate facts chapter: {chapter}")
        seen.add(chapter)
        rows.append(row)
    numbers = [row["n"] for row in rows]
    if numbers and numbers != list(range(1, numbers[-1] + 1)):
        raise ValueError("facts chapters are not contiguous")
    return rows


def split_source(text: str, max_chars: int) -> list[str]:
    if max_chars < 500:
        raise ValueError("max_chars must be at least 500")
    fragments: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > max_chars:
            if current:
                fragments.append(current)
                current = ""
            fragments.append(line[:max_chars])
            line = line[max_chars:]
        if current and len(current) + len(line) > max_chars:
            fragments.append(current)
            current = ""
        current += line
        if not line.strip() and current:
            fragments.append(current)
            current = ""
    if current:
        fragments.append(current)
    if not fragments:
        fragments = [text]
    if "".join(fragments) != text:
        raise ValueError("source fragmentation changed source text")
    return fragments


def schema_signature(row: dict) -> dict[str, str]:
    return {key: type(value).__name__ for key, value in row.items()}


def validate_fact_row(candidate: dict, chapter: int, baseline: dict | None) -> dict:
    if not isinstance(candidate, dict):
        raise ValueError("fact draft must be a JSON object")
    if candidate.get("n") != chapter:
        raise ValueError(f"fact draft n must equal {chapter}")
    if baseline is not None:
        if set(candidate) != set(baseline):
            missing = sorted(set(baseline) - set(candidate))
            extra = sorted(set(candidate) - set(baseline))
            raise ValueError(f"fact schema mismatch missing={missing} extra={extra}")
        expected_types = schema_signature(baseline)
        observed_types = schema_signature(candidate)
        if observed_types != expected_types:
            raise ValueError(
                f"fact type mismatch expected={expected_types} observed={observed_types}"
            )
    if len(candidate) < 2:
        raise ValueError("fact draft is structurally empty")
    empty = [
        key
        for key, value in candidate.items()
        if key != "n" and value in (None, "", [], {})
    ]
    if empty:
        raise ValueError(f"fact draft contains empty required fields: {empty}")
    return {
        "chapter_n": chapter,
        "key_count": len(candidate),
        "schema_signature": schema_signature(candidate),
        "row_sha256": sha256_bytes(
            json.dumps(candidate, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        ),
    }


def chapter_artifact_root(job: dict) -> Path:
    return Path(job["artifact_root"]) / f"chapter_{int(job['chapter_n']):04d}"


def persist_job(shared_root: Path, job: dict, event: str, details: dict | None = None) -> dict:
    job["heartbeat_at"] = utc_now()
    if job.get("status") == "RUNNING" and job.get("phase") in ACTIVE_PHASES:
        job["next_phase_event"] = {
            "schema": "qingshan.factory.writer_next_phase_ready.v1",
            "target_agent_id": AGENT_ID,
            "job_id": job.get("job_id"),
            "chapter_n": job.get("chapter_n"),
            "phase": job.get("phase"),
            "event_key": (
                f"{job.get('job_id')}:{job.get('chapter_n')}:{job.get('phase')}:"
                f"{job.get('source_sha256', 'no-source')}"
            ),
            "ready_at": job["heartbeat_at"],
            "dispatch_owner_agent_id": "qingshan-producer-supervisor",
        }
    path = active_job_path(shared_root)
    atomic_json(path, job)
    append_task_record(
        require_absolute(shared_root, "shared_root"),
        AGENT_ID,
        job_id=str(job["job_id"]),
        status=str(job["status"]),
        event=event,
        details={
            "chapter_n": job.get("chapter_n"),
            "phase": job.get("phase"),
            "attempt": job.get("attempt", 1),
            "next_action": job.get("next_action"),
            **(details or {}),
        },
    )
    return job


def load_job(shared_root: Path) -> dict:
    path = active_job_path(shared_root)
    job = read_verified_json(path)
    if job.get("agent_id") != AGENT_ID:
        raise ValueError("active job is owned by another Agent")
    if job.get("status") != "RUNNING":
        raise ValueError(f"active job is not RUNNING: {job.get('status')}")
    if job.get("phase") not in ACTIVE_PHASES:
        raise ValueError(f"invalid active phase: {job.get('phase')}")
    for field in (
        "project_root",
        "project_facts_abs",
        "canonical_checkpoint_abs",
        "artifact_root",
        "source_path",
    ):
        require_absolute(Path(job[field]), field)
    return job


def bind_chapter(job: dict, source_path: Path, max_chars: int) -> dict:
    source = require_absolute(source_path, "source_path")
    project_root = Path(job["project_root"])
    if project_root not in source.parents:
        raise ValueError("source_path must be inside project_root")
    text = source.read_text(encoding="utf-8")
    source_sha = sha256_bytes(text.encode("utf-8"))
    fragments = split_source(text, max_chars)
    root = chapter_artifact_root(job)
    fragment_rows = []
    offset = 0
    for index, fragment in enumerate(fragments):
        fragment_rows.append(
            {
                "index": index,
                "char_start": offset,
                "char_end": offset + len(fragment),
                "text": fragment,
                "sha256": sha256_bytes(fragment.encode("utf-8")),
            }
        )
        offset += len(fragment)
    fragment_path = root / "evidence_fragments.jsonl"
    atomic_jsonl(fragment_path, fragment_rows)
    job.update(
        {
            "phase": "READ_EVIDENCE",
            "source_path": str(source),
            "source_sha256": source_sha,
            "evidence_fragments_path": str(fragment_path.resolve()),
            "evidence_fragments_sha256": sha256_file(fragment_path),
            "fragment_count": len(fragment_rows),
            "next_fragment_index": 0,
            "next_action": "record one evidence note for next_fragment_index",
        }
    )
    return job


def start_job(
    shared_root: Path,
    *,
    project_root: Path,
    facts: Path,
    checkpoint: Path,
    source: Path,
    chapter: int,
    target_last: int,
    job_id: str,
    lease_id: str,
    fence: int,
    cron_id: str,
    package_version: str,
    version_root: Path,
    runtime_root: Path,
    max_chars: int = 3000,
) -> dict:
    shared = require_absolute(shared_root, "shared_root")
    project = require_absolute(project_root, "project_root")
    facts_path = require_absolute(facts, "facts")
    checkpoint_path = require_absolute(checkpoint, "checkpoint")
    if project not in facts_path.parents or project not in checkpoint_path.parents:
        raise ValueError("facts and checkpoint must be inside project_root")
    if not lease_id or fence <= 0:
        raise ValueError("a valid Writer lease_id and positive fence are required")
    existing_path = active_job_path(shared)
    if existing_path.is_file():
        existing = read_verified_json(existing_path)
        if existing.get("status") in {"DISPATCHED", "CLAIMED", "RUNNING", "RETRYING"}:
            if existing.get("job_id") == job_id and existing.get("schema") == "qingshan.factory.writer_staged_facts_job.v1":
                return existing
            raise ValueError(
                f"another active Writer job must be migrated or completed first: {existing.get('job_id')}"
            )
    rows = read_facts(facts_path)
    last_n = rows[-1]["n"] if rows else 0
    if chapter != last_n + 1:
        raise ValueError(f"chapter compare-and-set failed: last_n={last_n} requested={chapter}")
    artifact_root = project / "factory_runtime_v3/writer_staged_facts" / job_id
    job = {
        "schema": "qingshan.factory.writer_staged_facts_job.v1",
        "agent_id": AGENT_ID,
        "job_id": job_id,
        "status": "RUNNING",
        "phase": "READ_EVIDENCE",
        "project_root": str(project),
        "project_facts_abs": str(facts_path),
        "canonical_checkpoint_abs": str(checkpoint_path),
        "artifact_root": str(artifact_root.resolve()),
        "chapter_n": chapter,
        "target_last": target_last,
        "last_completed": last_n,
        "facts_before_sha256": sha256_file(facts_path) if facts_path.is_file() else sha256_bytes(b""),
        "idempotency_key": f"chapter:{chapter}:pending-source-sha",
        "lease_id": lease_id,
        "fence": fence,
        "cron_id": cron_id,
        "package_version": package_version,
        "version_root": str(require_absolute(version_root, "version_root")),
        "runtime_root": str(require_absolute(runtime_root, "runtime_root")),
        "attempt": 1,
        "created_at": utc_now(),
    }
    bind_chapter(job, source, max_chars)
    job["idempotency_key"] = f"chapter:{chapter}:{job['source_sha256']}"
    return persist_job(shared, job, "STAGED_FACTS_STARTED")


def record_evidence_note(shared_root: Path, index: int, note_path: Path) -> dict:
    job = load_job(shared_root)
    if job["phase"] != "READ_EVIDENCE":
        raise ValueError(f"expected READ_EVIDENCE, got {job['phase']}")
    if index != int(job["next_fragment_index"]):
        raise ValueError(
            f"fragment compare-and-set failed: expected={job['next_fragment_index']} got={index}"
        )
    fragments_path = Path(job["evidence_fragments_path"])
    if not verify_sha_sidecar(fragments_path):
        raise ValueError("evidence fragments failed SHA verification")
    fragments = [json.loads(line) for line in fragments_path.read_text(encoding="utf-8").splitlines()]
    fragment = fragments[index]
    note = json.loads(require_absolute(note_path, "note_path").read_text(encoding="utf-8"))
    if not isinstance(note, dict) or not note:
        raise ValueError("evidence note must be a non-empty JSON object")
    payload = {
        "schema": "qingshan.factory.writer_evidence_note.v1",
        "chapter_n": job["chapter_n"],
        "fragment_index": index,
        "fragment_sha256": fragment["sha256"],
        "source_sha256": job["source_sha256"],
        "note": note,
    }
    output = chapter_artifact_root(job) / "evidence_notes" / f"{index:04d}.json"
    atomic_json(output, payload)
    job["next_fragment_index"] = index + 1
    if job["next_fragment_index"] >= job["fragment_count"]:
        job["phase"] = "MERGE_EVIDENCE"
        job["next_action"] = "merge all verified evidence notes"
    return persist_job(
        require_absolute(shared_root, "shared_root"),
        job,
        "EVIDENCE_FRAGMENT_RECORDED",
        {"fragment_index": index, "note_sha256": sha256_file(output)},
    )


def accept_merged_evidence(shared_root: Path, merged_path: Path) -> dict:
    job = load_job(shared_root)
    if job["phase"] != "MERGE_EVIDENCE":
        raise ValueError(f"expected MERGE_EVIDENCE, got {job['phase']}")
    merged = json.loads(require_absolute(merged_path, "merged_path").read_text(encoding="utf-8"))
    expected = list(range(int(job["fragment_count"])))
    if merged.get("chapter_n") != job["chapter_n"]:
        raise ValueError("merged evidence chapter mismatch")
    if merged.get("source_sha256") != job["source_sha256"]:
        raise ValueError("merged evidence source SHA mismatch")
    if merged.get("fragments_used") != expected:
        raise ValueError("merged evidence must account for every source fragment")
    output = chapter_artifact_root(job) / "merged_evidence.json"
    atomic_json(output, merged)
    job.update(
        {
            "phase": "DRAFT_FULL_FACT",
            "merged_evidence_path": str(output.resolve()),
            "merged_evidence_sha256": sha256_file(output),
            "next_action": "produce one full-depth fact draft from merged evidence",
        }
    )
    return persist_job(shared_root, job, "EVIDENCE_MERGED")


def accept_draft(shared_root: Path, draft_path: Path) -> dict:
    job = load_job(shared_root)
    if job["phase"] != "DRAFT_FULL_FACT":
        raise ValueError(f"expected DRAFT_FULL_FACT, got {job['phase']}")
    draft = json.loads(require_absolute(draft_path, "draft_path").read_text(encoding="utf-8"))
    facts = read_facts(Path(job["project_facts_abs"]))
    baseline = facts[-1] if facts else None
    validation = validate_fact_row(draft, int(job["chapter_n"]), baseline)
    output = chapter_artifact_root(job) / "draft_full_fact.json"
    atomic_json(output, draft)
    job.update(
        {
            "phase": "VALIDATE",
            "draft_path": str(output.resolve()),
            "draft_sha256": sha256_file(output),
            "draft_row_sha256": validation["row_sha256"],
            "next_action": "validate draft schema, artifacts, continuity and source binding",
        }
    )
    return persist_job(shared_root, job, "FULL_FACT_DRAFT_ACCEPTED", validation)


def validate_draft(shared_root: Path) -> dict:
    job = load_job(shared_root)
    if job["phase"] != "VALIDATE":
        raise ValueError(f"expected VALIDATE, got {job['phase']}")
    for field in ("evidence_fragments_path", "merged_evidence_path", "draft_path"):
        if not verify_sha_sidecar(Path(job[field])):
            raise ValueError(f"artifact SHA verification failed: {field}")
    if sha256_file(Path(job["source_path"])) != job["source_sha256"]:
        raise ValueError("source changed after READ_EVIDENCE")
    facts = read_facts(Path(job["project_facts_abs"]))
    last_n = facts[-1]["n"] if facts else 0
    if last_n != int(job["chapter_n"]) - 1:
        raise ValueError(f"facts continuity changed during draft: last_n={last_n}")
    draft = read_verified_json(Path(job["draft_path"]))
    validation = validate_fact_row(draft, int(job["chapter_n"]), facts[-1] if facts else None)
    receipt = {
        "schema": "qingshan.factory.writer_fact_validation_receipt.v1",
        "status": "PASS",
        "job_id": job["job_id"],
        "chapter_n": job["chapter_n"],
        "source_sha256": job["source_sha256"],
        "draft_sha256": job["draft_sha256"],
        "validation": validation,
        "validated_at": utc_now(),
    }
    output = chapter_artifact_root(job) / "validation_receipt.json"
    atomic_json(output, receipt)
    job.update(
        {
            "phase": "APPEND_ATOMIC",
            "validation_receipt_path": str(output.resolve()),
            "validation_receipt_sha256": sha256_file(output),
            "next_action": "append exactly once under Writer lease and fencing token",
        }
    )
    return persist_job(shared_root, job, "FULL_FACT_VALIDATED", validation)


def append_atomic(shared_root: Path) -> dict:
    job = load_job(shared_root)
    if job["phase"] != "APPEND_ATOMIC":
        raise ValueError(f"expected APPEND_ATOMIC, got {job['phase']}")
    if not job.get("lease_id") or int(job.get("fence", 0)) <= 0:
        raise ValueError("Writer lease/fence is missing")
    if not verify_sha_sidecar(Path(job["validation_receipt_path"])):
        raise ValueError("validation receipt failed SHA verification")
    facts_path = Path(job["project_facts_abs"])
    draft = read_verified_json(Path(job["draft_path"]))
    chapter = int(job["chapter_n"])
    row_text = json.dumps(draft, ensure_ascii=False, separators=(",", ":"))
    row_sha = sha256_bytes(row_text.encode("utf-8"))
    lock_path = facts_path.with_suffix(facts_path.suffix + ".writer.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deduped = False
    with lock_path.open("a+", encoding="ascii") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        facts = read_facts(facts_path)
        existing = next((row for row in facts if row["n"] == chapter), None)
        if existing is not None:
            existing_text = json.dumps(existing, ensure_ascii=False, separators=(",", ":"))
            if sha256_bytes(existing_text.encode("utf-8")) != row_sha:
                raise ValueError(f"chapter {chapter} already exists with different content")
            deduped = True
        else:
            last_n = facts[-1]["n"] if facts else 0
            if last_n != chapter - 1:
                raise ValueError(f"append compare-and-set failed: last_n={last_n}")
            facts_path.parent.mkdir(parents=True, exist_ok=True)
            with facts_path.open("a", encoding="utf-8") as stream:
                stream.write(row_text + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        verified = read_facts(facts_path)
        if not verified or verified[-1]["n"] != chapter:
            raise ValueError("post-append facts verification failed")
    receipt = {
        "schema": "qingshan.factory.writer_fact_append_receipt.v1",
        "status": "PASS",
        "job_id": job["job_id"],
        "chapter_n": chapter,
        "source_sha256": job["source_sha256"],
        "row_sha256": row_sha,
        "lease_id": job["lease_id"],
        "fence": job["fence"],
        "idempotency_key": job["idempotency_key"],
        "deduped": deduped,
        "facts_sha256": sha256_file(facts_path),
        "appended_at": utc_now(),
    }
    output = chapter_artifact_root(job) / "append_receipt.json"
    atomic_json(output, receipt)
    job["last_completed"] = chapter
    job["append_receipt_path"] = str(output.resolve())
    job["append_receipt_sha256"] = sha256_file(output)
    if chapter >= int(job["target_last"]):
        job.update(
            {
                "status": "PASS",
                "phase": "COMPLETE",
                "next_action": "FULL_CORPUS_COMPLETE",
            }
        )
        return persist_job(shared_root, job, "FULL_CORPUS_COMPLETE", receipt)
    job.update(
        {
            "phase": "NEXT_CHAPTER",
            "chapter_n": chapter + 1,
            "facts_before_sha256": sha256_file(facts_path),
            "next_action": "bind the canonical source file for the next chapter",
        }
    )
    return persist_job(shared_root, job, "CHAPTER_FACT_APPENDED", receipt)


def bind_next_chapter(shared_root: Path, source: Path, max_chars: int = 3000) -> dict:
    job = load_job(shared_root)
    if job["phase"] != "NEXT_CHAPTER":
        raise ValueError(f"expected NEXT_CHAPTER, got {job['phase']}")
    facts = read_facts(Path(job["project_facts_abs"]))
    last_n = facts[-1]["n"] if facts else 0
    if last_n + 1 != int(job["chapter_n"]):
        raise ValueError(f"next chapter compare-and-set failed: last_n={last_n}")
    bind_chapter(job, source, max_chars)
    job["idempotency_key"] = f"chapter:{job['chapter_n']}:{job['source_sha256']}"
    return persist_job(shared_root, job, "NEXT_CHAPTER_BOUND")


def record_dispatch(
    shared_root: Path,
    *,
    dispatch_id: str,
    pending_key: str,
    next_due: str,
    dispatch_mode: str,
    watchdog_id: str = "",
) -> dict:
    job = load_job(shared_root)
    if dispatch_mode not in {"completion_chained_one_shot", "watchdog_recovery"}:
        raise ValueError("invalid staged facts dispatch mode")
    if not dispatch_id or not pending_key or not next_due:
        raise ValueError("dispatch_id, pending_key and next_due are required")
    job.update(
        {
            "dispatch_mode": dispatch_mode,
            "chained_dispatch_id": dispatch_id,
            "watchdog_id": watchdog_id or job.get("watchdog_id", ""),
            "pending_key": pending_key,
            "next_due": next_due,
            "last_dispatch_receipt": {
                "dispatch_id": dispatch_id,
                "pending_key": pending_key,
                "next_due": next_due,
                "recorded_at": utc_now(),
            },
        }
    )
    return persist_job(shared_root, job, "NEXT_PHASE_DISPATCH_RECORDED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shared-root", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("--project-root", type=Path, required=True)
    start.add_argument("--facts", type=Path, required=True)
    start.add_argument("--checkpoint", type=Path, required=True)
    start.add_argument("--source", type=Path, required=True)
    start.add_argument("--chapter", type=int, required=True)
    start.add_argument("--target-last", type=int, default=763)
    start.add_argument("--job-id", required=True)
    start.add_argument("--lease-id", required=True)
    start.add_argument("--fence", type=int, required=True)
    start.add_argument("--cron-id", default="")
    start.add_argument("--package-version", required=True)
    start.add_argument("--version-root", type=Path, required=True)
    start.add_argument("--runtime-root", type=Path, required=True)
    start.add_argument("--max-chars", type=int, default=3000)
    note = sub.add_parser("record-note")
    note.add_argument("--index", type=int, required=True)
    note.add_argument("--note", type=Path, required=True)
    merged = sub.add_parser("accept-merged")
    merged.add_argument("--input", type=Path, required=True)
    draft = sub.add_parser("accept-draft")
    draft.add_argument("--input", type=Path, required=True)
    sub.add_parser("validate")
    sub.add_parser("append")
    next_parser = sub.add_parser("bind-next")
    next_parser.add_argument("--source", type=Path, required=True)
    next_parser.add_argument("--max-chars", type=int, default=3000)
    dispatch = sub.add_parser("record-dispatch")
    dispatch.add_argument("--dispatch-id", required=True)
    dispatch.add_argument("--pending-key", required=True)
    dispatch.add_argument("--next-due", required=True)
    dispatch.add_argument(
        "--dispatch-mode",
        choices=("completion_chained_one_shot", "watchdog_recovery"),
        required=True,
    )
    dispatch.add_argument("--watchdog-id", default="")
    sub.add_parser("recover")
    args = parser.parse_args()
    if args.command == "start":
        result = start_job(
            args.shared_root,
            project_root=args.project_root,
            facts=args.facts,
            checkpoint=args.checkpoint,
            source=args.source,
            chapter=args.chapter,
            target_last=args.target_last,
            job_id=args.job_id,
            lease_id=args.lease_id,
            fence=args.fence,
            cron_id=args.cron_id,
            package_version=args.package_version,
            version_root=args.version_root,
            runtime_root=args.runtime_root,
            max_chars=args.max_chars,
        )
    elif args.command == "record-note":
        result = record_evidence_note(args.shared_root, args.index, args.note)
    elif args.command == "accept-merged":
        result = accept_merged_evidence(args.shared_root, args.input)
    elif args.command == "accept-draft":
        result = accept_draft(args.shared_root, args.input)
    elif args.command == "validate":
        result = validate_draft(args.shared_root)
    elif args.command == "append":
        result = append_atomic(args.shared_root)
    elif args.command == "bind-next":
        result = bind_next_chapter(args.shared_root, args.source, args.max_chars)
    elif args.command == "record-dispatch":
        result = record_dispatch(
            args.shared_root,
            dispatch_id=args.dispatch_id,
            pending_key=args.pending_key,
            next_due=args.next_due,
            dispatch_mode=args.dispatch_mode,
            watchdog_id=args.watchdog_id,
        )
    else:
        result = recover_task_state(
            require_absolute(args.shared_root, "shared_root"), AGENT_ID
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
