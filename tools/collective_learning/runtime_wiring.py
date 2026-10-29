"""Hooks that connect a run's knowledge lock to the real compile and submit entry points.

Inert unless the run opted in: every hook returns ``None`` when the environment carries
no run lock, so in-flight episodes that never ran a collective preflight are byte-
for-byte unaffected.  The pipeline exports these variables to its child processes from
the episode's preflight receipt (``nalu_pipeline.Ctx.child_env``):

    QINGSHAN_KNOWLEDGE_RUN_LOCK          path of the run's knowledge lock
    QINGSHAN_KNOWLEDGE_RUN_LOCK_SHA256   sha256 the lock had when it was bound
    QINGSHAN_KNOWLEDGE_CACHE             verified bundle cache directory
    QINGSHAN_KNOWLEDGE_TRUST             trust store (pinned publisher keys)
    QINGSHAN_ENGINE_API_VERSION          engine API version used for scope matching
    QINGSHAN_COLLECTIVE_STORE            optional device store (adoption receipts are queued there)
    QINGSHAN_COLLECTIVE_TENANT / _LINE   identity for that store

Entry points wired (see tools/tests/test_collective_real_entry_wiring.py):
  * SD2  compile_grouped_seedance_manifest.write_preflight_artifacts -> ``apply_to_grouped_unit``
  * H3   build_nalu_preproduction.render_h3_final_prompts          -> ``apply_to_h3_task``
  * POST submit_giggle_video_manifest_v2.submit_one (both families) -> ``check_before_send`` /
         ``record_provider_request``; resume paths return before this and never re-POST.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Callable

from . import adoption, bundles, contracts as c, selection

ENV_LOCK = "QINGSHAN_KNOWLEDGE_RUN_LOCK"
ENV_LOCK_SHA = "QINGSHAN_KNOWLEDGE_RUN_LOCK_SHA256"
ENV_CACHE = "QINGSHAN_KNOWLEDGE_CACHE"
ENV_TRUST = "QINGSHAN_KNOWLEDGE_TRUST"
ENV_API = "QINGSHAN_ENGINE_API_VERSION"
ENV_STORE = "QINGSHAN_COLLECTIVE_STORE"
ENV_TENANT = "QINGSHAN_COLLECTIVE_TENANT"
ENV_LINE = "QINGSHAN_COLLECTIVE_LINE"
ENV_NAMES = (ENV_LOCK, ENV_LOCK_SHA, ENV_CACHE, ENV_TRUST, ENV_API, ENV_STORE, ENV_TENANT, ENV_LINE)

COMPILE_STAGE = "VIDEO_COMPILE"


class KnowledgeLockRefused(RuntimeError):
    """The run's locked knowledge no longer verifies: this unit's NEW post is refused."""


def child_env(lock: dict[str, Any], *, cache_dir: Path, trust_path: Path, engine_api_version: str,
              store_path: Path | None = None, tenant_id: str | None = None,
              line_id: str | None = None) -> dict[str, str]:
    env = {ENV_LOCK: str(lock["lock_path"]), ENV_LOCK_SHA: str(lock["lock_sha256"]),
           ENV_CACHE: str(cache_dir), ENV_TRUST: str(trust_path), ENV_API: engine_api_version}
    if store_path and tenant_id and line_id:
        env.update({ENV_STORE: str(store_path), ENV_TENANT: tenant_id, ENV_LINE: line_id})
    return env


class _Run:
    def __init__(self, env: dict[str, str]):
        self.lock_path = Path(env[ENV_LOCK])
        self.lock_sha = env.get(ENV_LOCK_SHA, "")
        self.trust = bundles.load_trust_store(Path(env[ENV_TRUST]))
        self.cache = bundles.BundleCache(Path(env[ENV_CACHE]), self.trust)
        self.api = env.get(ENV_API) or c.UNKNOWN
        self.store_path = env.get(ENV_STORE)
        self.tenant = env.get(ENV_TENANT) or c.UNKNOWN
        self.line = env.get(ENV_LINE) or c.UNKNOWN
        self.lock = json.loads(self.lock_path.read_text(encoding="utf-8"))

    @property
    def ref(self) -> dict[str, Any]:
        return {"path": str(self.lock_path), "sha256": self.lock_sha, "run_id": self.lock["run_id"],
                "knowledge_bundle_digest": self.lock.get("knowledge_bundle_digest")}

    def verify(self) -> dict[str, Any]:
        return bundles.verify_lock_for_send(self.ref, self.cache)

    def rules(self) -> list[dict[str, Any]]:
        return bundles.locked_rules(self.lock_path, self.cache)

    def identity(self) -> dict[str, str]:
        device = c.UNKNOWN
        if self.store_path and Path(self.store_path).is_file():
            import sqlite3
            db = sqlite3.connect(f"file:{self.store_path}?mode=ro", uri=True)
            try:
                row = db.execute("SELECT value FROM meta WHERE key='device_id'").fetchone()
                device = row[0] if row else c.UNKNOWN
            finally:
                db.close()
        return {"tenant_id": self.tenant, "line_id": self.line, "device_id": device, "run_id": self.lock["run_id"]}

    def record(self, receipts: list[dict[str, Any]]) -> None:
        """Receipts go to a JSONL beside the lock, and to the device store's outbox if configured."""
        if not receipts:
            return
        sidecar = self.lock_path.with_suffix(".adoption.jsonl")
        with sidecar.open("a", encoding="utf-8") as handle:
            for row in receipts:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        if self.store_path:
            from .device_store import DeviceStore
            store = DeviceStore(Path(self.store_path), tenant_id=self.tenant, line_id=self.line)
            for row in receipts:
                store.record_receipt("ADOPTION", row)


def active(env: dict[str, str] | None = None) -> _Run | None:
    env = dict(os.environ if env is None else env)
    if not env.get(ENV_LOCK):
        return None
    return _Run(env)


def _decide(run: _Run, unit: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    status = run.verify()
    if status["status"] != "PASS":
        raise KnowledgeLockRefused(";".join(status["failures"]))
    return selection.select_for_unit(unit, run.rules(), stage=COMPILE_STAGE, engine_api_version=run.api), []


def _unit_ids(target: dict[str, Any]) -> list[str]:
    return [str(target.get("unit_id") or target.get("task_key") or c.UNKNOWN)]


def _record_compile(run: _Run, target: dict[str, Any], decision: dict[str, Any], applied_rows: list[dict[str, Any]],
                    deferred: list[dict[str, Any]], *, source: Any, with_text: str, without_text: str,
                    entrypoint: str) -> dict[str, Any]:
    ident = run.identity()
    receipts: list[dict[str, Any]] = []
    for row in decision["decisions"]:
        rule = {"rule_id": row["rule_id"], "rule_version": row["rule_version"]}
        if row["state"] in ("NOT_APPLICABLE", "DEFERRED", "FAILED"):
            receipts.append(adoption.not_adopted(identity=ident, rule=rule, stage=COMPILE_STAGE,
                                                 unit_ids=_unit_ids(target), entrypoint=entrypoint,
                                                 bundle_digest=row.get("bundle_digest") or "NONE",
                                                 state=row["state"], reason=row["reason"]))
    for row in deferred:
        receipts.append(adoption.not_adopted(identity=ident, rule=row, stage=COMPILE_STAGE,
                                             unit_ids=_unit_ids(target), entrypoint=entrypoint,
                                             bundle_digest=row.get("bundle_digest") or "NONE",
                                             state="DEFERRED", reason=row["reason"]))
    applied_ids = []
    for row in applied_rows:
        rule = {"rule_id": row["rule_id"], "rule_version": row["rule_version"]}
        try:
            receipt = adoption.applied(identity=ident, rule=rule, stage=COMPILE_STAGE, unit_ids=_unit_ids(target),
                                       entrypoint=entrypoint, bundle_digest=row.get("bundle_digest") or "NONE",
                                       clause=row["clause"], source_contract=source, compiled_with=with_text,
                                       compiled_without=without_text, carrier_fields=row.get("carrier_fields"))
            applied_ids.append({"rule_id": row["rule_id"], "rule_version": row["rule_version"],
                                "clause_sha256": receipt["change_evidence"]["clause_sha256"],
                                "compiled_receipt_id": receipt["receipt_id"]})
        except c.ContractError as exc:
            receipt = adoption.not_adopted(identity=ident, rule=rule, stage=COMPILE_STAGE, unit_ids=_unit_ids(target),
                                           entrypoint=entrypoint, bundle_digest=row.get("bundle_digest") or "NONE",
                                           state="FAILED", reason=";".join(exc.codes))
        receipts.append(receipt)
    for row in decision["checks"]:
        receipts.append(adoption.selected(identity=ident, rule=row, stage=COMPILE_STAGE, unit_ids=_unit_ids(target),
                                          entrypoint=entrypoint, bundle_digest=row.get("bundle_digest") or "NONE"))
    run.record(receipts)
    return {"lock": run.ref, "applied_rules": applied_ids,
            "compiled_output_digest": c.sha256_bytes(with_text.encode("utf-8")),
            "checks": [row["check_id"] for row in decision["checks"] if row.get("check_id")],
            "conflicts": decision["conflicts"], "receipt_ids": [r["receipt_id"] for r in receipts]}


def apply_to_grouped_unit(unit: dict[str, Any], compile_fn: Callable[[dict[str, Any]], str], *,
                          entrypoint: str = "compile_grouped_seedance_manifest.write_preflight_artifacts",
                          env: dict[str, str] | None = None) -> dict[str, Any] | None:
    """SD2 source-contract application before the strict compile.  Mutates ``unit`` in place.

    H3 units are left alone here: their English contract is bound later, and amending the
    Chinese source would stale that binding.  They are handled by :func:`apply_to_h3_task`.
    """
    run = active(env)
    if run is None:
        return None
    if selection.model_family(unit.get("model")) == "h3":
        unit["knowledge_lock"] = run.ref
        return {"lock": run.ref, "deferred_to": "render_h3_final_prompts"}
    pristine = (unit.get("knowledge_adoption") or {}).get("pristine_ordered_prompt_specs")
    if pristine is not None:
        unit["ordered_prompt_specs"] = copy.deepcopy(pristine)
    original = copy.deepcopy({k: v for k, v in unit.items() if k not in ("knowledge_adoption", "knowledge_lock")})
    decision, _ = _decide(run, original)
    result = selection.apply_to_unit(original, decision)
    without_text = compile_fn(copy.deepcopy(original))
    with_text = compile_fn(copy.deepcopy(result["unit"]))
    record = _record_compile(run, unit, decision, result["applied"], result["deferred"], source=result["unit"],
                             with_text=with_text, without_text=without_text, entrypoint=entrypoint)
    unit["ordered_prompt_specs"] = result["unit"]["ordered_prompt_specs"]
    unit["knowledge_lock"] = run.ref
    unit["knowledge_adoption"] = {**record, "pristine_ordered_prompt_specs": original.get("ordered_prompt_specs")}
    return record


def apply_to_h3_task(task: dict[str, Any], compile_fn: Callable[[dict[str, Any]], str], *,
                     capability_unit: dict[str, Any] | None = None,
                     entrypoint: str = "build_nalu_preproduction.render_h3_final_prompts",
                     env: dict[str, str] | None = None) -> dict[str, Any] | None:
    """H3: amend the bound English contract(s) the paid boundary reads.  Mutates ``task``.

    The pristine English contracts are kept on the task so a re-render (every S6 re-entry)
    restores them before applying again: application is idempotent and the "without rule"
    compile is always the genuine baseline.
    """
    run = active(env)
    if run is None:
        return None
    adoption_state = task.get("knowledge_adoption") or {}
    pristine = adoption_state.get("pristine_h3_english")
    machine = task.get("machine_contract") if isinstance(task.get("machine_contract"), dict) else None
    if pristine is not None:
        if pristine.get("task") is not None:
            task["h3_provider_english_contract"] = copy.deepcopy(pristine["task"])
        if machine is not None and pristine.get("machine") is not None:
            machine["h3_provider_english_contract"] = copy.deepcopy(pristine["machine"])
    else:
        pristine = {"task": copy.deepcopy(task.get("h3_provider_english_contract")),
                    "machine": copy.deepcopy((machine or {}).get("h3_provider_english_contract"))}
    baseline_task = copy.deepcopy({k: v for k, v in task.items() if k not in ("knowledge_adoption",)})
    # Capabilities come from the compiler input the boundary itself uses (provider_prompt_unit).
    decision, _ = _decide(run, capability_unit if capability_unit is not None else baseline_task)
    result = selection.apply_to_unit(baseline_task, decision)
    without_text = compile_fn(copy.deepcopy(baseline_task))
    with_text = compile_fn(copy.deepcopy(result["unit"]))
    record = _record_compile(run, task, decision, result["applied"], result["deferred"],
                             source=result["unit"].get("h3_provider_english_contract"),
                             with_text=with_text, without_text=without_text, entrypoint=entrypoint)
    task["h3_provider_english_contract"] = result["unit"].get("h3_provider_english_contract")
    if machine is not None and isinstance(result["unit"].get("machine_contract"), dict):
        machine["h3_provider_english_contract"] = result["unit"]["machine_contract"].get("h3_provider_english_contract")
    task["knowledge_lock"] = run.ref
    task["knowledge_adoption"] = {**record, "pristine_h3_english": pristine}
    return record


# --------------------------------------------------------------------------- submit boundary
def check_before_send(task: dict[str, Any], *, env: dict[str, str] | None = None) -> dict[str, Any] | None:
    """Re-verify the lock and every locked bundle immediately before a NEW post.

    Only for tasks that carry ``knowledge_lock``; everything else returns None untouched.
    The task's own bound lock ref is authoritative (not the environment), so a lock
    replaced on disk after binding is detected even if the env was re-pointed.
    """
    ref = task.get("knowledge_lock")
    if not isinstance(ref, dict):
        return None
    env = dict(os.environ if env is None else env)
    if not env.get(ENV_CACHE) or not env.get(ENV_TRUST):
        raise KnowledgeLockRefused("KNOWLEDGE_CACHE_OR_TRUST_NOT_CONFIGURED_FOR_LOCKED_TASK")
    trust = bundles.load_trust_store(Path(env[ENV_TRUST]))
    cache = bundles.BundleCache(Path(env[ENV_CACHE]), trust)
    status = bundles.verify_lock_for_send(ref, cache)
    if status["status"] != "PASS":
        raise KnowledgeLockRefused(";".join(status["failures"]))
    return status


def provider_request_digest(payload: dict[str, Any]) -> str:
    return c.digest(payload)


def record_provider_request(task: dict[str, Any], payload: dict[str, Any], *,
                            env: dict[str, str] | None = None,
                            entrypoint: str = "submit_giggle_video_manifest_v2.submit_one") -> list[dict[str, Any]]:
    """PROVIDER_REQUEST receipts for the rules applied at compile, from the exact payload sent.

    A receipt is written only if the sent prompt is byte-identical to the compiled output the
    compile-time APPLIED receipt bound -- that receipt already proved the clause is in exactly
    those bytes, so what was verified is what was sent.  Otherwise a FAILED receipt records
    the divergence.
    """
    record = task.get("knowledge_adoption") or {}
    if not isinstance(task.get("knowledge_lock"), dict) or not record:
        return []
    env = dict(os.environ if env is None else env)
    run = active({**env, ENV_LOCK: task["knowledge_lock"]["path"], ENV_LOCK_SHA: task["knowledge_lock"]["sha256"]}) \
        if env.get(ENV_CACHE) and env.get(ENV_TRUST) else None
    ident = run.identity() if run else {"tenant_id": c.UNKNOWN, "line_id": c.UNKNOWN, "device_id": c.UNKNOWN,
                                        "run_id": task["knowledge_lock"].get("run_id") or c.UNKNOWN}
    sent = str(payload.get("prompt") or "")
    sent_sha = c.sha256_bytes(sent.encode("utf-8"))
    request_digest = provider_request_digest(payload)
    receipts = []
    for row in record.get("applied_rules") or []:
        rule = {"rule_id": row["rule_id"], "rule_version": row["rule_version"]}
        base = dict(identity=ident, rule=rule, stage="VIDEO_SUBMIT", unit_ids=_unit_ids(task), entrypoint=entrypoint,
                    bundle_digest=task["knowledge_lock"].get("knowledge_bundle_digest") or "NONE")
        if sent_sha != record.get("compiled_output_digest"):
            receipts.append(adoption.not_adopted(**base, state="FAILED",
                                                 reason="SENT_PROMPT_DIFFERS_FROM_APPLIED_COMPILE"))
            continue
        receipt = {**adoption.selected(**base), "state": "APPLIED", "evidence_scope": "PROVIDER_REQUEST",
                   "source_contract_digest": c.digest(task.get("h3_provider_english_contract")
                                                      or task.get("ordered_prompt_specs") or task.get("task_key")),
                   "compiled_output_digest": sent_sha, "provider_request_digest": request_digest,
                   "change_evidence": {"clause_sha256": row["clause_sha256"],
                                       "compiled_receipt_id": row["compiled_receipt_id"],
                                       "sent_prompt_equals_applied_compile": True},
                   "outcome_observed": False}
        receipts.append(c.validate_adoption(receipt))
    if run:
        run.record(receipts)
    return receipts
