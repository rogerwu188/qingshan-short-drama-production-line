#!/usr/bin/env python3
"""Create and close an exclusive, provenance-bound canonical Writer run.

This dispatcher owns the write lease and receipt boundary.  Claude/Cowork or
StoryClaw performs the actual language-model turn, but no E41+ output can pass
the script gate unless it was bracketed by this tool and bound to its receipt.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

try:
    from tools.writer_production_field_gate import validate_generation_contract
except ModuleNotFoundError:
    from writer_production_field_gate import validate_generation_contract

try:
    from canonical_writer_provenance import (
        ALLOWED_AGENT_IDS,
        GENERIC_MODEL_ALIASES,
        RECEIPT_SCHEMA,
        combined_rules_sha,
        sha256_bytes,
    )
except ModuleNotFoundError:
    from tools.canonical_writer_provenance import (
        ALLOWED_AGENT_IDS,
        GENERIC_MODEL_ALIASES,
        RECEIPT_SCHEMA,
        combined_rules_sha,
        sha256_bytes,
    )

try:
    from writer_receipt_resolver import resolve as resolve_receipt
except ModuleNotFoundError:
    from tools.writer_receipt_resolver import resolve as resolve_receipt


ROOT = REPOSITORY_ROOT
DEFAULT_LOCK_DIR = ROOT / "workflow/claude_writer_agent/locks"
DEFAULT_SEAL_DIR = ROOT / "workflow/claude_writer_agent/seals"
SEAL_SCHEMA = "qingshan.canonical_writer_four_layer_seal.v1"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def lock_path(lock_dir: Path, episode: str, version: int) -> Path:
    return lock_dir / f"{episode}_V{version}.writer.lock.json"


def _same_version(left: Any, right: Any) -> bool:
    """Compare two declared version values the way CL2X-1291 ④ ruled they compare.

    That ruling treats the string and integer forms of the same number as the
    same value, so `"5"`, `5` and `"v5"` are one version, not three.  Used only
    to decide whether the seal emits its NON-AUTHORITATIVE version warning; it
    never authenticates lineage on its own.
    """

    def normalise(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip().lstrip("vV")
        try:
            return str(int(text))
        except ValueError:
            return text or None

    return normalise(left) == normalise(right)


def acquire_lock(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def declared_layers(manifest: dict[str, Any]) -> list[dict[str, str]]:
    """Extract the three pre-manifest authority layers a manifest declares.

    The manifest is the only place that names all of narrative/directing/contract
    together, so the seal reads them from there rather than taking them on the
    command line: a seal that trusted CLI paths could be pointed at any file.
    Raises SystemExit with a named error when a layer cannot be located.
    """

    rows: list[dict[str, str]] = []

    narrative = manifest.get("narrative_canonical")
    if isinstance(narrative, dict) and narrative.get("authority_path"):
        rows.append({
            "layer": "narrative_canonical",
            "path": str(narrative["authority_path"]),
            "declared_sha256": str(narrative.get("authority_sha256") or ""),
        })
    elif manifest.get("canonical_script"):
        rows.append({
            "layer": "narrative_canonical",
            "path": str(manifest["canonical_script"]),
            "declared_sha256": str(manifest.get("script_sha256") or ""),
        })
    else:
        raise SystemExit("WRITER_SEAL_LAYER_NOT_DECLARED:narrative_canonical")

    for layer, key in (("directing_script", "directing_script"), ("generation_contract", "generation_contract")):
        section = manifest.get(key)
        if not isinstance(section, dict) or not section.get("path"):
            raise SystemExit(f"WRITER_SEAL_LAYER_NOT_DECLARED:{layer}")
        rows.append({
            "layer": layer,
            "path": str(section["path"]),
            "declared_sha256": str(section.get("sha256") or ""),
        })

    for row in rows:
        if not row["declared_sha256"]:
            raise SystemExit(f"WRITER_SEAL_LAYER_SHA_NOT_DECLARED:{row['layer']}")
    return rows


def resolve_layer(path_text: str, manifest_path: Path) -> Path:
    candidate = Path(path_text)
    if candidate.is_absolute():
        return candidate
    for base in (ROOT, manifest_path.parent, Path.cwd()):
        resolved = (base / candidate)
        if resolved.is_file():
            return resolved.resolve()
    return (ROOT / candidate).resolve()


def start(args: argparse.Namespace) -> int:
    if args.agent_id not in ALLOWED_AGENT_IDS:
        raise SystemExit("WRITER_AGENT_NOT_AUTHORIZED")
    if args.model_id.strip().lower() in GENERIC_MODEL_ALIASES:
        raise SystemExit("WRITER_MODEL_ID_NOT_EXACT")
    if not args.provider.strip() or not args.session_or_task_id.strip():
        raise SystemExit("WRITER_RUNTIME_IDENTITY_INCOMPLETE")
    input_bundle = args.input_bundle.resolve()
    if not input_bundle.is_file():
        raise SystemExit("WRITER_INPUT_BUNDLE_MISSING")
    rules: list[dict[str, str]] = []
    for rule_path in args.rule:
        resolved = rule_path.resolve()
        if not resolved.is_file():
            raise SystemExit(f"WRITER_RULE_MISSING:{resolved}")
        rules.append({"path": str(resolved), "sha256": sha256_file(resolved)})
    if not rules:
        raise SystemExit("WRITER_RULES_MISSING")

    expected = f"WRITER-{args.episode}-V{args.version}-"
    if not args.writer_run_id.startswith(expected):
        raise SystemExit("WRITER_RUN_ID_EPISODE_VERSION_MISMATCH")
    receipt = args.receipt.resolve()
    if receipt.exists():
        raise SystemExit("WRITER_RECEIPT_ALREADY_EXISTS")
    lease = lock_path(args.lock_dir.resolve(), args.episode, args.version)
    started_at = now()
    acquire_lock(lease, {
        "schema": "qingshan.canonical_writer_write_lease.v1",
        "writer_run_id": args.writer_run_id,
        "episode": args.episode,
        "version": args.version,
        "receipt": str(receipt),
        "acquired_at": started_at,
    })
    payload = {
        "schema": RECEIPT_SCHEMA,
        "status": "RUNNING",
        "writer_run_id": args.writer_run_id,
        "episode": args.episode,
        "version": args.version,
        "agent_id": args.agent_id,
        "provider": args.provider,
        "model_id": args.model_id,
        "session_or_task_id": args.session_or_task_id,
        "input_bundle": {"path": str(input_bundle), "sha256": sha256_file(input_bundle)},
        "writer_rules": {"files": rules, "combined_sha256": combined_rules_sha(rules)},
        "authority_output": None,
        "started_at": started_at,
        "completed_at": None,
        "write_lease": str(lease),
    }
    try:
        atomic_json(receipt, payload)
    except BaseException:
        lease.unlink(missing_ok=True)
        raise
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def finish(args: argparse.Namespace) -> int:
    receipt = args.receipt.resolve()
    authority = args.authority.resolve()
    if not receipt.is_file() or not authority.is_file():
        raise SystemExit("WRITER_RECEIPT_OR_AUTHORITY_MISSING")
    payload = read_json(receipt)
    if payload.get("status") != "RUNNING":
        raise SystemExit("WRITER_RUN_NOT_RUNNING")
    lease = Path(str(payload.get("write_lease") or ""))
    if not lease.is_file():
        raise SystemExit("WRITER_WRITE_LEASE_MISSING")
    lease_payload = read_json(lease)
    if lease_payload.get("writer_run_id") != payload.get("writer_run_id"):
        raise SystemExit("WRITER_WRITE_LEASE_OWNER_MISMATCH")

    # SUPERVISOR_ORDERS seq=54 conditions[5] / seq=55 conditions[5]:
    # a COMPLETED receipt did not prove the authority layers existed.  Every
    # layer that CAN land inside the lease (narrative / directing / contract)
    # is now existence- and emptiness-checked here and recorded by SHA.  The
    # manifest cannot be checked here -- it must bind this receipt's SHA, which
    # does not exist until these bytes are written; see `seal`.
    layers: list[dict[str, str]] = []
    for declared in args.layer:
        resolved = declared.resolve()
        if not resolved.is_file():
            raise SystemExit(f"WRITER_FINISH_LAYER_MISSING:{resolved}")
        if resolved.stat().st_size == 0:
            raise SystemExit(f"WRITER_FINISH_LAYER_EMPTY:{resolved}")
        layers.append({"path": str(resolved), "sha256": sha256_file(resolved)})

    # SUPERVISOR_ORDERS seq=56 conditions[4]: whether --layer becomes mandatory is
    # the writer's own routine engineering choice (Roger 2026-08-14 self-decision
    # authority).  Decision taken this round: NOT mandatory yet, because the cloud
    # StoryClaw instance still calls `finish` by hand from an older package and a
    # hard requirement would fail it at the worst possible moment -- mid-run, with
    # the lease held and the authority bytes already on disk.  Instead the omission
    # is warned about AND written into the receipt, so a run that skipped the layer
    # declaration is self-evident from its own bytes rather than only from a stderr
    # line nobody kept.  Tighten to mandatory once the cloud package is rebuilt.
    finish_warnings: list[str] = []
    if not layers:
        finish_warnings.append(
            "WRITER_FINISH_NO_LAYER_DECLARATION"
            ";layers_at_finish=null;NOT_A_REFUSAL_PER_SUPERVISOR_ORDERS_SEQ56_C4"
        )

    payload["status"] = "COMPLETED"
    payload["authority_output"] = {"path": str(authority), "sha256": sha256_file(authority)}
    payload["layers_at_finish"] = layers or None
    payload["finish_warnings"] = finish_warnings or None
    payload["completed_at"] = now()
    atomic_json(receipt, payload)
    lease.unlink()
    for warning in finish_warnings:
        print(warning, file=sys.stderr)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def seal(args: argparse.Namespace) -> int:
    """Close the four-layer chain after `finish`, without touching the receipt.

    seq=55 conditions[5] offered two fixes: write the receipt terminal state after
    all four layers land, or extend the terminal guard to all four layers.  Neither
    is satisfiable for the manifest: charter line 22 requires the manifest to bind
    the COMPLETED receipt, so the manifest's bytes depend on the receipt's bytes.
    Putting the manifest SHA into the receipt would change the receipt SHA and
    invalidate the manifest's declaration -- a SHA-256 fixed point across two files.
    So closure moves to a third artefact that is written last and binds all four.
    """

    receipt = args.receipt.resolve()
    manifest = args.manifest.resolve()
    failures: list[str] = []
    if not receipt.is_file():
        raise SystemExit("WRITER_SEAL_RECEIPT_MISSING")
    if not manifest.is_file():
        raise SystemExit("WRITER_SEAL_MANIFEST_MISSING")

    receipt_payload = read_json(receipt)
    manifest_payload = read_json(manifest)
    receipt_sha = sha256_file(receipt)

    if receipt_payload.get("status") != "COMPLETED":
        failures.append(f"WRITER_SEAL_RECEIPT_NOT_COMPLETED:{receipt_payload.get('status')}")

    episode = str(receipt_payload.get("episode") or "")
    version = receipt_payload.get("version")
    warnings: list[str] = []
    if str(manifest_payload.get("episode") or "") != episode:
        failures.append("WRITER_SEAL_EPISODE_MISMATCH")
    # SUPERVISOR_ORDERS seq=56 conditions[2]: the manifest's own `$.version` field
    # was already ruled NON-AUTHORITATIVE for lineage on 2026-08-29T04:52Z
    # (erratum CLAUDE-SUP-20260829-E49V5-E50V5-VERSION-FIELD-NON-AUTHORITATIVE,
    # CL2X-1291 ④).  Lineage is authenticated by filename + receipt
    # authority_output.sha256 + manifest SHA, never by this field.  Refusing the
    # seal on it was an unregistered criterion blocking a workstation (铁律一),
    # so it is recorded as a warning: visible, logged, never a refusal.  String
    # and integer forms of the same number are the same value per that ruling.
    if not _same_version(manifest_payload.get("version"), version):
        warnings.append(
            "WRITER_SEAL_VERSION_FIELD_MISMATCH:"
            f"manifest={manifest_payload.get('version')!r},receipt={version!r}"
            ";NON_AUTHORITATIVE_PER_ERRATUM="
            "CLAUDE-SUP-20260829-E49V5-E50V5-VERSION-FIELD-NON-AUTHORITATIVE"
            " (CL2X-1291 ④, workflow/tasks/E49_V5_E50_V5_VERSION_FIELD_ERRATUM_V1.json)"
            ";LINEAGE_KEY=filename+receipt.authority_output.sha256+manifest_sha"
        )

    # R431 F-R431-01 / R432: the customary receipt filename is not always the
    # authority.  E51 v4's customary path holds an ABORTED receipt with a null
    # authority_output because seq=53 conditions[1] ordered a new path after the
    # clean abort, while ~80 call sites in tools/ still format that filename by
    # hand.  Report the divergence so the next builder binds by lookup instead of
    # by filename.  Warning only, never a refusal: this criterion is not
    # registered and must not block a workstation (铁律一), and the seal's own
    # binding checks below already prove the passed receipt is the right one.
    try:
        resolution = resolve_receipt(receipt.parent, episode, version)
    except OSError:
        resolution = None
    if resolution is not None:
        resolved_receipt = resolution.get("authoritative_receipt")
        if resolved_receipt and Path(resolved_receipt) != receipt:
            warnings.append(
                "WRITER_SEAL_RECEIPT_IS_NOT_THE_RESOLVED_AUTHORITY:"
                f"passed={receipt},resolved={resolved_receipt}"
                ";LOOKUP=tools/writer_receipt_resolver.py"
            )
        elif (
            resolved_receipt
            and resolution.get("customary_exists")
            and not resolution.get("customary_is_authoritative")
        ):
            warnings.append(
                "WRITER_SEAL_AUTHORITY_RECEIPT_NOT_AT_CUSTOMARY_PATH:"
                f"authority={receipt},customary={resolution.get('customary_path')}"
                ";BUILDERS_MUST_RESOLVE_NOT_FORMAT"
                ";LOOKUP=tools/writer_receipt_resolver.py"
            )

    provenance = manifest_payload.get("writer_provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    if provenance.get("receipt_sha256") != receipt_sha:
        failures.append("WRITER_SEAL_RECEIPT_SHA_MISMATCH")
    if provenance.get("writer_run_id") != receipt_payload.get("writer_run_id"):
        failures.append("WRITER_SEAL_RUN_ID_MISMATCH")

    # A lease file on disk normally means someone else is mid-write.  But
    # `finish`/`abort` raise PermissionError on unlink under some mounts (charter
    # line 65), which leaves the finished run's own lease behind.  A lease whose
    # writer_run_id equals this COMPLETED receipt's run is provably that orphan,
    # not a competing writer, so it is recorded and not treated as a refusal.
    lease = lock_path(args.lock_dir.resolve(), episode, int(version or 0))
    if lease.exists():
        try:
            lease_run_id = read_json(lease).get("writer_run_id")
        except (OSError, ValueError):
            lease_run_id = None
        same_run = (
            lease_run_id is not None
            and lease_run_id == receipt_payload.get("writer_run_id")
            and receipt_payload.get("status") == "COMPLETED"
        )
        if same_run:
            warnings.append(f"WRITER_SEAL_ORPHAN_LEASE_OF_THIS_RUN:{lease}")
        else:
            failures.append(f"WRITER_SEAL_LEASE_STILL_HELD:{lease}")

    rows: list[dict[str, Any]] = []
    for declared in declared_layers(manifest_payload):
        resolved = resolve_layer(declared["path"], manifest)
        row = {
            "layer": declared["layer"],
            "path": declared["path"],
            "resolved_path": str(resolved),
            "declared_sha256": declared["declared_sha256"],
            "actual_sha256": None,
            "present": resolved.is_file(),
        }
        if not row["present"]:
            failures.append(f"WRITER_SEAL_LAYER_MISSING:{declared['layer']}")
        elif resolved.stat().st_size == 0:
            failures.append(f"WRITER_SEAL_LAYER_EMPTY:{declared['layer']}")
        else:
            row["actual_sha256"] = sha256_file(resolved)
            if row["actual_sha256"] != declared["declared_sha256"]:
                failures.append(f"WRITER_SEAL_LAYER_SHA_MISMATCH:{declared['layer']}")
        rows.append(row)

    authority_output = receipt_payload.get("authority_output") or {}
    narrative_row = next((row for row in rows if row["layer"] == "narrative_canonical"), None)
    if narrative_row and narrative_row["actual_sha256"] != authority_output.get("sha256"):
        failures.append("WRITER_SEAL_AUTHORITY_SHA_MISMATCH")

    generation_row = next((row for row in rows if row["layer"] == "generation_contract"), None)
    production_field_gate: dict[str, Any] | None = None
    if generation_row and generation_row.get("present") and generation_row.get("actual_sha256"):
        try:
            generation_payload = read_json(Path(generation_row["resolved_path"]))
            # The non-bypass production-field contract is versioned and only
            # applies to actual generation-contract artifacts.  Generic seal
            # fixtures and historical non-production JSON remain readable.
            if str(generation_payload.get("schema") or "").startswith("qingshan.generation_contract."):
                production_field_gate = validate_generation_contract(generation_payload)
                failures.extend(
                    f"WRITER_PRODUCTION_FIELD_GATE:{failure}"
                    for failure in production_field_gate["failures"]
                )
        except (OSError, ValueError, TypeError) as exc:
            failures.append(f"WRITER_PRODUCTION_FIELD_GATE_UNREADABLE:{exc}")

    rows.append({
        "layer": "manifest",
        "path": str(manifest),
        "resolved_path": str(manifest),
        "declared_sha256": None,
        "actual_sha256": sha256_file(manifest),
        "present": True,
    })

    verdict = {
        "schema": SEAL_SCHEMA,
        "status": "SEALED" if not failures else "SEAL_REFUSED",
        "mode": "CHECK" if args.check else "WRITE",
        "episode": episode,
        "version": version,
        "writer_run_id": receipt_payload.get("writer_run_id"),
        "receipt": {"path": str(receipt), "sha256": receipt_sha},
        "layers": rows,
        "production_field_gate": production_field_gate,
        "failures": failures,
        "warnings": warnings,
        "sealed_at": now(),
    }

    if failures:
        print(json.dumps(verdict, ensure_ascii=False))
        raise SystemExit("WRITER_SEAL_REFUSED:" + ",".join(failures))

    if args.check:
        print(json.dumps(verdict, ensure_ascii=False))
        return 0

    seal_file = args.seal or (args.seal_dir.resolve() / f"{episode}_V{version}_FOUR_LAYER_SEAL.json")
    seal_file = Path(seal_file).resolve()
    if seal_file.exists():
        raise SystemExit("WRITER_SEAL_ALREADY_EXISTS")
    verdict["seal_path"] = str(seal_file)
    atomic_json(seal_file, verdict)
    print(json.dumps(verdict, ensure_ascii=False))
    return 0


def abort(args: argparse.Namespace) -> int:
    receipt = args.receipt.resolve()
    if not receipt.is_file():
        raise SystemExit("WRITER_RECEIPT_MISSING")
    payload = read_json(receipt)
    # SUPERVISOR_ORDERS seq=53 conditions[4]: a terminal receipt is a provenance credential.
    # ABORTED was previously unguarded, so a second abort could silently rewrite
    # abort_reason/completed_at on an already-terminal run.  Both terminal states are sealed now.
    if payload.get("status") in {"COMPLETED", "ABORTED"}:
        raise SystemExit(f"TERMINAL_WRITER_RUN_CANNOT_BE_ABORTED:{payload.get('status')}")
    lease = Path(str(payload.get("write_lease") or ""))
    payload["status"] = "ABORTED"
    payload["completed_at"] = now()
    payload["abort_reason"] = args.reason
    atomic_json(receipt, payload)
    lease.unlink(missing_ok=True)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("--episode", required=True)
    start_parser.add_argument("--version", required=True, type=int)
    start_parser.add_argument("--writer-run-id", required=True)
    start_parser.add_argument("--agent-id", required=True)
    start_parser.add_argument("--provider", required=True)
    start_parser.add_argument("--model-id", required=True)
    start_parser.add_argument("--session-or-task-id", required=True)
    start_parser.add_argument("--input-bundle", required=True, type=Path)
    start_parser.add_argument("--rule", action="append", default=[], type=Path)
    start_parser.add_argument("--receipt", required=True, type=Path)
    start_parser.add_argument("--lock-dir", type=Path, default=DEFAULT_LOCK_DIR)
    start_parser.set_defaults(func=start)

    finish_parser = subparsers.add_parser("finish")
    finish_parser.add_argument("--receipt", required=True, type=Path)
    finish_parser.add_argument("--authority", required=True, type=Path)
    finish_parser.add_argument(
        "--layer",
        action="append",
        default=[],
        type=Path,
        help="Authority layer that must exist and be non-empty at finish time "
             "(pass narrative/directing/contract; the manifest cannot be passed here).",
    )
    finish_parser.set_defaults(func=finish)

    seal_parser = subparsers.add_parser("seal")
    seal_parser.add_argument("--receipt", required=True, type=Path)
    seal_parser.add_argument("--manifest", required=True, type=Path)
    seal_parser.add_argument("--seal", type=Path, default=None)
    seal_parser.add_argument("--seal-dir", type=Path, default=DEFAULT_SEAL_DIR)
    seal_parser.add_argument("--lock-dir", type=Path, default=DEFAULT_LOCK_DIR)
    seal_parser.add_argument("--check", action="store_true")
    seal_parser.set_defaults(func=seal)

    abort_parser = subparsers.add_parser("abort")
    abort_parser.add_argument("--receipt", required=True, type=Path)
    abort_parser.add_argument("--reason", required=True)
    abort_parser.set_defaults(func=abort)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
