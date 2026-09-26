#!/usr/bin/env python3
"""nalu_tail_ad_opt_in.py — file-based per-episode tail-ad opt-in Q&A.

Imported directly into nalu_pipeline.py (not subprocessed via ctx.run(), which
buffers stdout until exit) so the question is visible on the live terminal
while polling.  Asked exactly once per episode, right before S1, from a fresh
run only.  No interactive input() — a headless heartbeat session must never
hang on this.

Spec: codex_docs/ROGER-20260925-AD-TAIL-INTEGRATION.md §五.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA_PROMPT = "qingshan.nalu_tail_ad_prompt.v1"
SCHEMA_LEDGER = "qingshan.nalu_ad_opt_in_ledger.v1"
QUESTION_ZH = "本集是否植入尾贴广告？"
OPTIONS = ("NONE", "INBOX:<sku>", "BRIEF:<sku>")


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def append_ledger(ledger_path: Path, entry: dict[str, Any]) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger = read_json(ledger_path) or {"schema": SCHEMA_LEDGER, "entries": []}
    ledger.setdefault("entries", []).append(entry)
    write_json(ledger_path, ledger)


def _valid_answer_value(value: str) -> bool:
    if value == "NONE":
        return True
    for prefix in ("INBOX:", "BRIEF:"):
        if value.startswith(prefix) and value[len(prefix):].strip():
            return True
    return False


def _load_policy(policy_path: Path) -> dict[str, Any]:
    return read_json(policy_path) or {"ask": True, "default": "NONE"}


def run_opt_in(
    episode: str,
    *,
    prompts_dir: Path,
    answer_dir: Path,
    policy_path: Path,
    ledger_path: Path,
    manifest_path: Path,
    say: Callable[[str], None],
    deadline_seconds: float = 60.0,
    poll_interval_seconds: float = 2.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    now_fn: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Ask (once) whether this episode carries a tail ad; write manifest.ad_slot
    exactly once.  Returns the resolved decision dict; always also appended to
    the append-only opt-in ledger."""
    policy = _load_policy(policy_path)
    asked_at = now()

    if policy.get("ask") is False:
        default = str(policy.get("default") or "NONE")
        decision = {"answer": default, "reason": "POLICY_SKIP_NO_ASK"}
        append_ledger(ledger_path, {
            "event": "POLICY_SKIP_NO_ASK", "episode": episode, "asked_at": asked_at,
            "default": default, "recorded_at_utc": now(),
        })
        _write_manifest_ad_slot(manifest_path, episode, decision, asked_at)
        return decision

    prompt_path = prompts_dir / f"{episode}_AD_PROMPT.json"
    answer_path = answer_dir / f"{episode}_AD_ANSWER.json"
    deadline = asked_at
    write_json(prompt_path, {
        "schema": SCHEMA_PROMPT, "episode": episode, "asked_at": asked_at,
        "deadline_seconds": deadline_seconds, "question": QUESTION_ZH,
        "options": list(OPTIONS), "answer_file": str(answer_path),
    })
    say(f"[tail-ad] {episode}: {QUESTION_ZH}  (answer at {answer_path}, {deadline_seconds:g}s)")

    deadline_clock = now_fn() + deadline_seconds
    raw_answer: dict[str, Any] | None = None
    while now_fn() < deadline_clock:
        raw_answer = read_json(answer_path)
        if raw_answer is not None:
            break
        sleep_fn(poll_interval_seconds)

    decision, ledger_event = _resolve_answer(episode, raw_answer, policy)
    append_ledger(ledger_path, {
        "event": ledger_event, "episode": episode, "asked_at": asked_at,
        "deadline_seconds": deadline_seconds, "raw_answer": raw_answer,
        "resolved": decision, "recorded_at_utc": now(),
    })
    say(f"[tail-ad] {episode}: resolved {decision['answer']} ({decision['reason']})")
    _write_manifest_ad_slot(manifest_path, episode, decision, asked_at)
    return decision


def _resolve_answer(episode: str, raw_answer: dict[str, Any] | None,
                     policy: dict[str, Any]) -> tuple[dict[str, Any], str]:
    default = str(policy.get("default") or "NONE")
    if raw_answer is None:
        return {"answer": default, "reason": "TIMEOUT_DEFAULT"}, "TIMEOUT_DEFAULT"
    if str(raw_answer.get("episode") or "") != episode:
        return {"answer": "NONE", "reason": "ANSWER_EPISODE_MISMATCH"}, "ANSWER_EPISODE_MISMATCH"
    value = str(raw_answer.get("answer") or "")
    if not _valid_answer_value(value):
        return {"answer": default, "reason": "TIMEOUT_DEFAULT"}, "INVALID_ANSWER_DEFAULTED"
    return {"answer": value, "reason": "ANSWERED"}, "ANSWERED"


def _write_manifest_ad_slot(manifest_path: Path, episode: str, decision: dict[str, Any], asked_at: str) -> None:
    """Written exactly once, pre-S1.  The writer manifest is fingerprint-pinned
    into every later stage's re-run check (nalu_pipeline.fp_s2 et al.), so this
    field must never change after S1 starts — the produced ad's sha/provenance
    lives in the mutable pipeline-state file instead (ctx.state["tail_ad"])."""
    manifest = read_json(manifest_path)
    if manifest is None or "ad_slot" in manifest:
        return
    sku = None
    for prefix in ("INBOX:", "BRIEF:"):
        if decision["answer"].startswith(prefix):
            sku = decision["answer"][len(prefix):]
    manifest["ad_slot"] = {
        "answer": decision["answer"], "reason": decision["reason"],
        "sku": sku, "asked_at": asked_at, "decided_at": now(),
    }
    write_json(manifest_path, manifest)


def recheck_before_s7(
    episode: str,
    *,
    answer_dir: Path,
    ledger_path: Path,
    current_decision: dict[str, Any],
    say: Callable[[str], None],
) -> dict[str, Any]:
    """One-shot, non-blocking re-check right before the S7 ad-splice step: a late
    answer (arriving after the original 60s window but before S7 starts) still
    counts.  Updates ctx.state only, never the manifest (see
    _write_manifest_ad_slot's docstring)."""
    if current_decision.get("reason") != "TIMEOUT_DEFAULT":
        return current_decision
    answer_path = answer_dir / f"{episode}_AD_ANSWER.json"
    raw_answer = read_json(answer_path)
    if raw_answer is None:
        return current_decision
    if str(raw_answer.get("episode") or "") != episode:
        append_ledger(ledger_path, {"event": "LATE_ANSWER_EPISODE_MISMATCH", "episode": episode,
                                    "raw_answer": raw_answer, "recorded_at_utc": now()})
        return current_decision
    value = str(raw_answer.get("answer") or "")
    if not _valid_answer_value(value):
        return current_decision
    decision = {"answer": value, "reason": "LATE_ANSWER_ACCEPTED_BEFORE_S7"}
    append_ledger(ledger_path, {"event": "LATE_ANSWER_ACCEPTED_BEFORE_S7", "episode": episode,
                                "raw_answer": raw_answer, "resolved": decision, "recorded_at_utc": now()})
    say(f"[tail-ad] {episode}: late answer accepted before S7 -> {value}")
    return decision
