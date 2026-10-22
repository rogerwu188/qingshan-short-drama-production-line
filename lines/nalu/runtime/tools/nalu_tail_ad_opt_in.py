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
#: The repo-shipped default policy (configs/ads/AD_POLICY_DEFAULT.json, line owner 2026-10-22: every
#: episode ends with the tail ad) is passed in by the pipeline as ``default_policy_path``; a runtime
#: ``ads/policy.json`` still overrides it per machine.
#: Decision reasons that only reflect a policy default (nobody answered); S7 re-resolves
#: these against the current policy + episode language.  Explicit answers are never touched.
DEFAULTED_REASONS = frozenset({"TIMEOUT_DEFAULT", "POLICY_SKIP_NO_ASK", "NO_OPT_IN_RECORDED",
                               "NO_OPT_IN_RECORDED_POLICY_DEFAULT", "POLICY_DEFAULT_AT_S7"})


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


def _load_policy(policy_path: Path, default_policy_path: Path | None = None) -> dict[str, Any]:
    """Runtime ads/policy.json if present, else the repo default policy (when given), else ask/NONE."""
    return (read_json(policy_path)
            or (read_json(default_policy_path) if default_policy_path else None)
            or {"ask": True, "default": "NONE"})


def policy_default(policy: dict[str, Any], language: str = "zh") -> str:
    """The policy's default answer for an episode of this dialogue language:
    ``default_by_language[language]`` -> ``default`` -> NONE."""
    by_language = policy.get("default_by_language")
    if isinstance(by_language, dict) and str(by_language.get(language) or "").strip():
        value = str(by_language[language]).strip()
    else:
        value = str(policy.get("default") or "NONE").strip()
    return value if _valid_answer_value(value) else "NONE"


def default_decision_at_s7(current: dict[str, Any] | None, *, policy_path: Path, language: str,
                           default_policy_path: Path | None = None) -> dict[str, Any]:
    """Decision S7 uses: an explicit recorded answer as-is; otherwise (no record, or a record that
    only holds a policy default) the current policy default for the episode's language."""
    if current and str(current.get("reason") or "") not in DEFAULTED_REASONS:
        return current
    answer = policy_default(_load_policy(policy_path, default_policy_path), language)
    if current and current.get("answer") == answer:
        return current
    reason = "NO_OPT_IN_RECORDED_POLICY_DEFAULT" if not current else "POLICY_DEFAULT_AT_S7"
    decision = {"answer": answer, "reason": reason, "language": language}
    if current:
        decision["previous"] = {"answer": current.get("answer"), "reason": current.get("reason")}
    return decision


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
    language: str = "zh",
    default_policy_path: Path | None = None,
    poll_interval_seconds: float = 2.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    now_fn: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Ask (once) whether this episode carries a tail ad; write manifest.ad_slot
    exactly once.  Returns the resolved decision dict; always also appended to
    the append-only opt-in ledger."""
    policy = _load_policy(policy_path, default_policy_path)
    asked_at = now()

    if policy.get("ask") is False:
        default = policy_default(policy, language)
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

    decision, ledger_event = _resolve_answer(episode, raw_answer, policy, language)
    append_ledger(ledger_path, {
        "event": ledger_event, "episode": episode, "asked_at": asked_at,
        "deadline_seconds": deadline_seconds, "raw_answer": raw_answer,
        "resolved": decision, "recorded_at_utc": now(),
    })
    say(f"[tail-ad] {episode}: resolved {decision['answer']} ({decision['reason']})")
    _write_manifest_ad_slot(manifest_path, episode, decision, asked_at)
    return decision


def _resolve_answer(episode: str, raw_answer: dict[str, Any] | None,
                     policy: dict[str, Any], language: str = "zh") -> tuple[dict[str, Any], str]:
    default = policy_default(policy, language)
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
    if current_decision.get("reason") not in DEFAULTED_REASONS:
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
