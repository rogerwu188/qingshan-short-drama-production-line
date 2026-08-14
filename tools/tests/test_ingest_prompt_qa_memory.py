import json

import pytest

from tools.ingest_prompt_qa_memory import ingest_candidate


def candidate(root, sample_id="LORA-TEST-001", status="ACTIVE_REWRITE_PENDING_POSITIVE"):
    for name in ("qa.json", "failed.txt", "failed.mp4", "accepted.txt", "accepted.mp4"):
        (root / name).write_text(name, encoding="utf-8")
    row = {
        "sample_id": sample_id,
        "status": status,
        "episode": "TEST",
        "generation_mode": "storyboard",
        "applicable_modes": ["storyboard"],
        "failure_receipt": "qa.json",
        "failed_prompt": "failed.txt",
        "failed_asset": "failed.mp4",
        "root_cause": "the prompt omitted a visible actor action",
        "optimization": "assign every visible actor a path and terminal state",
        "compiler_guard_clause": "Every visible actor requires a motion ledger.",
        "admission_gate": "POSITIVE_REGEN_PASS",
        "tags": ["visible_actor_motion"],
    }
    if status == "ADMITTED":
        row.update({"accepted_prompt": "accepted.txt", "accepted_asset": "accepted.mp4"})
    return row


def test_ingests_evidence_bound_candidate_and_dedupes(tmp_path):
    memory = tmp_path / "memory.jsonl"
    first = ingest_candidate(candidate(tmp_path), memory, tmp_path)
    second = ingest_candidate(candidate(tmp_path), memory, tmp_path)
    assert first["status"] == "ACTIVE_REWRITE_PENDING_POSITIVE"
    assert second["status"] == "DEDUPED"
    rows = [json.loads(line) for line in memory.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["failed_asset_sha256"]


def test_admitted_candidate_requires_positive_pair(tmp_path):
    row = candidate(tmp_path, status="ADMITTED")
    row.pop("accepted_asset")
    with pytest.raises(ValueError, match="accepted_prompt and accepted_asset"):
        ingest_candidate(row, tmp_path / "memory.jsonl", tmp_path)


def test_rejects_missing_evidence(tmp_path):
    row = candidate(tmp_path)
    row["failure_receipt"] = "missing.json"
    with pytest.raises(ValueError, match="evidence file is missing"):
        ingest_candidate(row, tmp_path / "memory.jsonl", tmp_path)
