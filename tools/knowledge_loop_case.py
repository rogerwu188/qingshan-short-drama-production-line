#!/usr/bin/env python3
"""Knowledge-loop case 001 (line owner 2026-11-01, item 5): one real production problem, end to end.

    record fact -> attribute cause -> state the rule -> verify the rule -> hand the rule to a
    later real build -> show what changed

This does not add a second state machine.  It drives ``adoption.py``'s existing
AVAILABLE -> SELECTED -> APPLIED -> VERIFIED -> OUTCOME_OBSERVED chain and attaches the four real
inputs the chain never carried (``contracts.validate_case_provenance``):

    fact          the measured value and the artefact + sha256 it was measured from
    cause         the claim AND the evidence artefacts behind it
    rule_source   the rule's exact clause text at ``path:line``
    verification  a before/after pair of measured values, each side from a recorded artefact

Two honesty constraints are enforced in code, not in prose:

* The "without the rule" arm is the **earlier real code**, loaded from git at the revision the
  rule landed on (``disabled_variant.kind = "git_revision"``).  It is not a re-implementation and
  not string surgery on the new file.  Its output must reproduce the recorded pre-rule artefact.
* It cannot claim production adoption.  ``real_run_consumption.status`` is
  ``NOT_YET_CONSUMED_BY_REAL_RUN`` unless a later real run's own output carries the clause; a free
  replay is ``CONSUMED_BY_REPLAY_ONLY`` and says so.  ``production_adoption`` is always False.

Everything is offline and free: no provider POST, no network, no paid stage.

    python3 tools/knowledge_loop_case.py check  --spec <case.json> --state-root <dir>
    python3 tools/knowledge_loop_case.py run    --spec <case.json> --state-root <dir>
    python3 tools/knowledge_loop_case.py verify --spec <case.json> --state-root <dir>
    python3 tools/knowledge_loop_case.py replay --spec <case.json> --state-root <dir>
    python3 tools/knowledge_loop_case.py status --spec <case.json> --state-root <dir>
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.collective_learning import adoption, contracts as c  # noqa: E402

CASE_SCHEMA = "qingshan.knowledge_loop_case.v1"
RECEIPT_SCHEMA = "qingshan.knowledge_loop_consumer_receipt.v1"
STATE_FILE = "KNOWLEDGE_LOOP_CASE.json"


class CaseError(ValueError):
    """The spec or the artefact it names does not support the claim being made."""


# --------------------------------------------------------------------------- locators
def resolve(locator: dict[str, Any], roots: dict[str, Path]) -> Path:
    """``{root, path}`` -> a real file.  Roots are supplied by the caller, never recorded."""
    root = str(locator.get("root") or "")
    if root not in roots:
        raise CaseError(f"CASE_ROOT_UNKNOWN:{root}")
    path = Path(roots[root]) / str(locator.get("path") or "")
    if not path.is_file():
        raise CaseError(f"CASE_ARTEFACT_NOT_FOUND:{root}:{locator.get('path')}")
    return path


def sha256_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- spec checks
def check_spec(spec: dict[str, Any], roots: dict[str, Path]) -> dict[str, Any]:
    """Every named artefact exists AND still hashes to the sha the spec claims.

    Drift is a finding, not a warning: the point of the case is that a third party can re-open
    the same bytes and re-derive the same numbers.
    """
    if spec.get("schema") != CASE_SCHEMA:
        raise CaseError("CASE_SCHEMA_INVALID")
    if "demo" not in str(spec.get("kind") or "").lower() and spec.get("demo_fixtures"):
        raise CaseError("CASE_SPEC_CARRIES_DEMO_FIXTURES:a real case never embeds demo fixtures")
    provenance = spec.get("provenance") or {}
    c.validate_case_provenance(provenance)  # same authority as a receipt

    drift: list[dict[str, str]] = []
    checked = 0

    def expect(locator: dict[str, Any], claimed: str | None, label: str) -> None:
        nonlocal checked
        path = resolve(locator, roots)
        actual = sha256_file(path)
        checked += 1
        if claimed and actual != claimed:
            drift.append({"part": label, "path": str(locator.get("path")), "claimed": claimed, "actual": actual})

    fact = provenance["fact"]
    expect(fact["artefact"], fact.get("artefact_sha256"), "fact")
    for index, row in enumerate(provenance["cause"]["evidence"]):
        if row.get("artefact"):
            expect(row["artefact"], row.get("artefact_sha256"), f"cause[{index}]")
    for side in ("before", "after"):
        row = provenance["verification"][side]
        if row.get("artefact"):
            expect(row["artefact"], row.get("artefact_sha256"), f"verification.{side}")

    rule_file = resolve({"root": "ENGINE", "path": provenance["rule_source"]["file"]}, roots)
    clause = provenance["rule_source"]["clause"]
    lines = rule_file.read_text(encoding="utf-8").splitlines()
    line_no = provenance["rule_source"]["line"]
    if clause not in rule_file.read_text(encoding="utf-8"):
        raise CaseError("CASE_RULE_CLAUSE_NOT_IN_NAMED_FILE")
    if line_no > len(lines) or clause not in "\n".join(lines[max(0, line_no - 3):line_no + 2]):
        raise CaseError(f"CASE_RULE_CLAUSE_NOT_AT_DECLARED_LINE:{line_no}")
    return {"status": "PASS" if not drift else "FAIL", "drift": drift, "artefacts_checked": checked,
            "rule_clause_at_declared_line": True}


# --------------------------------------------------------------------------- the real gate, both arms
def load_gate(spec: dict[str, Any], roots: dict[str, Path], *, with_rule: bool) -> ModuleType:
    """Import the production module that owns the rule -- or the code as it was before the rule."""
    gate = spec["replay"]["gate"]
    module_path = gate["module"]
    if with_rule:
        return _import_module(module_path, (Path(roots["ENGINE"]) / module_path).read_text("utf-8"), "rule_on")
    variant = gate.get("disabled_variant") or {}
    if variant.get("kind") != "git_revision":
        raise CaseError(f"CASE_DISABLED_VARIANT_UNSUPPORTED:{variant.get('kind')}")
    source = _git_show(Path(roots["ENGINE"]), f"{variant['commit']}:{module_path}")
    return _import_module(module_path, source, f"rev_{variant['commit']}")


def _import_module(module_path: str, source: str, label: str) -> ModuleType:
    """Compile ``source`` with the module's REAL ``__file__``.

    A module that resolves a shipped config relative to ``__file__`` (``POLICY_PATH`` ->
    ``configs/``) must see the same path in both arms, or the comparison would be between two
    different configurations instead of between two revisions of one rule.
    """
    filename = str((ROOT / module_path).resolve())
    name = f"case_gate_{Path(module_path).stem}_{label}"
    spec = importlib.util.spec_from_loader(name, loader=None)
    if spec is None:
        raise CaseError(f"CASE_GATE_IMPORT_FAILED:{module_path}")
    module = importlib.util.module_from_spec(spec)
    module.__file__ = filename
    exec(compile(source, filename, "exec"), module.__dict__)  # noqa: S102 -- loading the module IS the point
    return module


def _git_show(engine: Path, spec_rev: str) -> str:
    try:
        return subprocess.run(["git", "show", spec_rev], cwd=engine, check=True,
                              capture_output=True, text=True).stdout
    except subprocess.CalledProcessError as exc:
        raise CaseError(f"CASE_GIT_REVISION_UNAVAILABLE:{spec_rev}:{exc.stderr.strip()[:200]}") from exc


def replay_inputs(spec: dict[str, Any], roots: dict[str, Path]) -> tuple[list, list]:
    """The gate's own recorded input, re-read from the artefacts the real run wrote."""
    replay = spec["replay"]
    report = _load_json(resolve(replay["hit_source"], roots))
    captions = _load_json(resolve(replay["captions"], roots))
    hits = [(row["t"], row["text"], float(replay.get("confidence", 0.9)),
             row["box"][0], row["box"][1], row["box"][2], row["box"][3])
            for row in report[replay.get("hit_key", "ignored_non_dialogue_text")]]
    return hits, captions.get("rows") or []


def run_gate(spec: dict[str, Any], roots: dict[str, Path], *, with_rule: bool) -> dict[str, Any]:
    """Call the REAL gate function over the REAL recorded input."""
    gate = spec["replay"]["gate"]
    module = load_gate(spec, roots, with_rule=with_rule)
    hits, captions = replay_inputs(spec, roots)
    cfg = module.policy() if gate.get("config_from_policy", True) else gate["config"]
    return getattr(module, gate["function"])(hits, captions, cfg)


def assert_restores_earlier_output(spec: dict[str, Any], roots: dict[str, Path], without: dict[str, Any]) -> None:
    """The pre-rule code must reproduce the recorded pre-rule artefact, not merely differ."""
    expected = spec["provenance"]["verification"]["before"]
    if without.get("status") != expected["value"]:
        raise CaseError(f"CASE_WITHOUT_RULE_STATUS_MISMATCH:{without.get('status')}!={expected['value']}")
    wanted = expected.get("expected_failing_rows")
    if wanted is not None:
        got = sorted(row["text"] for row in without.get("text_outside_bar") or [])
        if got != sorted(wanted):
            raise CaseError(f"CASE_WITHOUT_RULE_ROWS_MISMATCH:got={got}:expected={sorted(wanted)}")


# --------------------------------------------------------------------------- states
def record_states(spec: dict[str, Any], roots: dict[str, Path], state_root: Path) -> dict[str, Any]:
    """AVAILABLE -> SELECTED -> APPLIED, each receipt carrying the four provenance inputs."""
    check = check_spec(spec, roots)
    if check["status"] != "PASS":
        raise CaseError(f"CASE_ARTEFACTS_DRIFTED:{check['drift']}")
    identity = {k: spec["identity"][k] for k in ("tenant_id", "line_id", "device_id", "run_id")}
    rule = {"rule_id": spec["rule"]["rule_id"], "rule_version": int(spec["rule"].get("rule_version", 1))}
    bundle_digest, stage, units = spec["bundle_digest"], spec["stage"], spec.get("unit_ids") or []
    provenance = copy.deepcopy(spec["provenance"])

    with_rule = run_gate(spec, roots, with_rule=True)
    without_rule = run_gate(spec, roots, with_rule=False)
    assert_restores_earlier_output(spec, roots, without_rule)

    available = {"schema": c.ADOPTION_SCHEMA, "schema_version": c.SCHEMA_VERSION, "receipt_id": c.new_uuid(),
                 **identity, "rule_id": rule["rule_id"], "rule_version": rule["rule_version"],
                 "bundle_digest": bundle_digest, "stage": stage, "unit_ids": units,
                 "state": "AVAILABLE", "entrypoint": "knowledge_loop_case.record_states",
                 "recorded_at": c.now_iso(), "provenance": provenance,
                 "rule_source_sha256": sha256_file(
                     resolve({"root": "ENGINE", "path": provenance["rule_source"]["file"]}, roots))}
    c.validate_adoption(available)

    selected = adoption.selected(identity=identity, rule=rule, stage=stage, unit_ids=units,
                                 entrypoint="knowledge_loop_case.record_states", bundle_digest=bundle_digest)
    selected["provenance"] = provenance
    c.validate_adoption(selected)

    # APPLIED's existing contract is unchanged: the clause is in the output WITH the rule and absent
    # from the output of the same unit WITHOUT it (here: the pre-rule code, same recorded input).
    applied = adoption.applied(
        identity=identity, rule=rule, stage=stage, unit_ids=units,
        entrypoint="knowledge_loop_case.record_states", bundle_digest=bundle_digest,
        clause=provenance["rule_source"]["clause"],
        source_contract={"case_id": spec["case_id"], "rule_key": spec["rule"].get("key"),
                         "input": spec["replay"]["hit_source"]},
        compiled_with=canonical(with_rule), compiled_without=canonical(without_rule),
        evidence_scope="COMPILED_REQUEST", carrier_fields=["rule", "ignored_non_dialogue_text"])
    applied["provenance"] = provenance
    c.validate_adoption(applied)

    payload = {"schema": CASE_SCHEMA, "case_id": spec["case_id"], "rule_id": rule["rule_id"],
               "spec_check": check, "receipts": [available, selected, applied]}
    _write(state_root / STATE_FILE, payload)
    return payload


def verify(spec: dict[str, Any], roots: dict[str, Path], state_root: Path) -> dict[str, Any]:
    """Re-run both arms and promote APPLIED -> VERIFIED only if the evidence still holds."""
    state = _read(state_root / STATE_FILE)
    applied = next(r for r in state["receipts"] if r["state"] == "APPLIED")
    after = run_gate(spec, roots, with_rule=True)
    before = run_gate(spec, roots, with_rule=False)
    assert_restores_earlier_output(spec, roots, before)

    expected = spec["provenance"]["verification"]
    if after.get("status") != expected["after"]["value"]:
        raise CaseError(f"CASE_WITH_RULE_STATUS_MISMATCH:{after.get('status')}!={expected['after']['value']}")
    digest = c.sha256_bytes(canonical(after).encode("utf-8"))
    if digest != applied["compiled_output_digest"]:
        raise CaseError("CASE_VERIFIED_NOT_OVER_THE_APPLIED_OUTPUT")
    clause = spec["provenance"]["rule_source"]["clause"]
    if clause not in canonical(after) or clause in canonical(before):
        raise CaseError("CASE_CLAUSE_NOT_SWITCHED_BY_THE_RULE")

    receipt = adoption.verified(applied, test_name=spec["verification"]["test_name"],
                                assertion=spec["verification"]["assertion"], passed=True,
                                checked_output_digest=applied["compiled_output_digest"])
    receipt["provenance"] = applied["provenance"]
    receipt["replay"] = {"with_rule_status": after.get("status"), "without_rule_status": before.get("status"),
                         "with_rule_output_sha256": digest,
                         "without_rule_output_sha256": c.sha256_bytes(canonical(before).encode("utf-8")),
                         "without_rule_restores_recorded_artifact": True,
                         "disabled_variant": spec["replay"]["gate"]["disabled_variant"],
                         "gate_module": spec["replay"]["gate"]["module"],
                         "gate_function": spec["replay"]["gate"]["function"]}
    c.validate_adoption(receipt)
    state["receipts"].append(receipt)
    _write(state_root / STATE_FILE, state)
    return receipt


def consumer_receipt(spec: dict[str, Any], roots: dict[str, Path], state_root: Path) -> dict[str, Any]:
    """The honest consumer receipt: replay proof plus the status nobody may round up."""
    state = _read(state_root / STATE_FILE)
    verified = next(r for r in state["receipts"] if r["state"] == "VERIFIED")
    after = run_gate(spec, roots, with_rule=True)
    before = run_gate(spec, roots, with_rule=False)
    clause = spec["provenance"]["rule_source"]["clause"]
    with_text, without_text = canonical(after), canonical(before)
    receipt = {
        "schema": RECEIPT_SCHEMA, "case_id": spec["case_id"], "rule_id": spec["rule"]["rule_id"],
        "recorded_at": c.now_iso(),
        "consumer": {"entrypoint": spec["replay"]["gate"]["function"],
                     "module": spec["replay"]["gate"]["module"],
                     "input_artefact": spec["replay"]["hit_source"],
                     "input_artefact_sha256": sha256_file(resolve(spec["replay"]["hit_source"], roots))},
        "with_rule": {"status": after.get("status"), "output_sha256": c.sha256_bytes(with_text.encode("utf-8")),
                      "clause_present": clause in with_text},
        "without_rule": {"status": before.get("status"),
                         "output_sha256": c.sha256_bytes(without_text.encode("utf-8")),
                         "clause_present": clause in without_text},
        "real_run_consumption": spec["real_run_consumption"],
        "production_adoption": False,
    }
    if receipt["without_rule"]["clause_present"]:
        raise CaseError("CASE_CLAUSE_PRESENT_WITHOUT_RULE")
    if not receipt["with_rule"]["clause_present"]:
        raise CaseError("CASE_CLAUSE_ABSENT_WITH_RULE")
    merged = {**verified, "receipt_id": c.new_uuid(), "recorded_at": c.now_iso(),
              "supersedes_receipt_id": verified["receipt_id"],
              "real_run_consumption": receipt["real_run_consumption"], "consumer_receipt": receipt}
    c.validate_adoption(merged)
    state["receipts"].append(merged)
    state["consumer_receipt"] = receipt
    _write(state_root / STATE_FILE, state)
    return receipt


# --------------------------------------------------------------------------- io
def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise CaseError(f"CASE_STATE_MISSING:{path.name}")
    return _load_json(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("cmd", choices=("check", "run", "verify", "replay", "status"))
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--engine-root", type=Path, default=ROOT)
    parser.add_argument("--workflow-root", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    args = parser.parse_args(argv)
    roots = {"ENGINE": args.engine_root.resolve()}
    if args.workflow_root:
        roots["WORKFLOW"] = args.workflow_root.resolve()
    if args.runtime_root:
        roots["RUNTIME"] = args.runtime_root.resolve()
    spec = _load_json(args.spec)
    try:
        if args.cmd == "check":
            out = check_spec(spec, roots)
        elif args.cmd == "run":
            out = record_states(spec, roots, args.state_root)
        elif args.cmd == "verify":
            out = verify(spec, roots, args.state_root)
        elif args.cmd == "replay":
            out = consumer_receipt(spec, roots, args.state_root)
        else:
            state = _read(args.state_root / STATE_FILE)
            out = {"case_id": state["case_id"], "rule_id": state["rule_id"],
                   "states": [r["state"] for r in state["receipts"]],
                   "strongest": adoption.strongest_state(state["receipts"], state["rule_id"]),
                   "consumption": (state.get("consumer_receipt") or {}).get("real_run_consumption")}
    except (CaseError, c.ContractError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)[:800]}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({k: v for k, v in out.items() if k != "receipts"}, ensure_ascii=False, indent=2)[:6000])
    return 0 if out.get("status", "PASS") != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
