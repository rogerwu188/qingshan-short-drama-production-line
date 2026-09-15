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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# F-R530-01：`os.replace`／`O_EXCL` 建件之后连目录项一起落盘。单一实现在
# tools/durable_rename.py，写手线五处原子写共用。
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from durable_rename import durable_replace, fsync_directory  # noqa: E402

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


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK_DIR = ROOT / "workflow/claude_writer_agent/locks"
DEFAULT_SEAL_DIR = ROOT / "workflow/claude_writer_agent/seals"
SEAL_SCHEMA = "qingshan.canonical_writer_four_layer_seal.v1"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _discard_temporary(temporary: Path) -> None:
    """Best-effort disposal of a half-written temporary, which NEVER raises.

    Same three-step ladder as `release_lease` (F-R523-01) and the singleflight
    gate's `_discard_quietly` (F-R525-01):

      1. unlink -- the normal path;
      2. this mount refuses unlink, so rename the residue out of the way;
      3. if both fail, leave it. The name now carries a random token, so the
         residue blocks nobody. Staying silent beats masking the real error.
    """
    try:
        temporary.unlink(missing_ok=True)
        return
    except OSError:
        pass
    try:
        temporary.replace(temporary.with_name(temporary.name + ".discarded"))
    except OSError:
        pass


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """Write `payload` to `path` atomically, leaving no permanent residue.

    F-R526-01.  Two defects, both MEASURED on this mount, both permanent:

    1. The temporary was named `.{name}.{pid}.tmp` -- pid alone.  This sandbox
       hands fresh `python3` processes tiny sequential pids (measured: 4,5,...,
       13 across ten consecutive calls), so pid reuse across rounds is close to
       certain rather than theoretical.  A residue from a crashed run makes the
       `open("x")` here raise FileExistsError.  And because unlink is refused on
       this mount, NOTHING can clear it: probed three consecutive retries, all
       three FileExistsError.  Every `start`/`finish`/`abort`/`seal` targeting
       that receipt path is then bricked forever -- the same permanent-brick
       shape as F-R525-01, but sitting on the writer's own authority chain.
    2. There was no rollback at all.  A payload that fails to serialise midway
       (probed with a non-JSON-able value: TypeError) left the temporary on disk
       permanently, which is how defect 1 gets armed in the first place.

    Fix: a per-attempt unique temporary name (pid + uuid4), so a residue can
    never collide with a later attempt; and disposal routed through the
    non-raising ladder so the caller still sees the ORIGINAL exception.

    Unchanged on purpose: the rename stays last, so `path` holds either the
    complete old bytes or the complete new bytes -- never a half-written state.

    F-R530-01: the rename now goes through `durable_replace`, which fsyncs the
    parent directory afterwards. Until then the receipt's *contents* survived a
    machine crash but the directory entry pointing at them did not, so a crash
    could roll a finished receipt back to its previous state. The directory
    fsync never raises and never changes this function's control flow.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        durable_replace(temporary, path)
    except BaseException:
        _discard_temporary(temporary)
        raise


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
    """Take the exclusive per-episode/version write lease.

    F-R530-01: the lease is a freshly *created* file, so its directory entry is
    exactly what makes the lease exist. Fsyncing the file contents alone left a
    crash window in which the lease's bytes were durable but the entry naming
    them was not -- i.e. after a machine crash the exclusive lease could look as
    though it had never been taken, which is the one thing it exists to prevent.
    The directory fsync runs only after a fully successful create-and-write, and
    never raises (see `durable_rename`).
    """
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
        # F-R524-01.  This rollback used to be a bare `unlink(missing_ok=True)`.
        # On this mount `unlink` raises PermissionError, so the rollback itself
        # threw: the caller received PermissionError instead of the real failure
        # (demoted to __context__), AND the half-written lease stayed at the
        # customary path, blocking every later `start` for that episode/version.
        # Route it through the same ladder `finish`/`abort` use, which never
        # raises, so the original exception reaches the caller intact.
        release_lease(path, str(payload.get("writer_run_id") or "unknown"), "acquire_rollback")
        raise
    # Success only. A lease whose creation was rolled back above must not have
    # its directory entry made durable.
    fsync_directory(path.parent)


def release_lease(lease: Path, run_id: str, stage: str) -> dict[str, Any]:
    """Release a write lease, surviving mounts where `unlink` is not permitted.

    F-R523-01.  `finish`/`abort` released the lease with a bare `unlink()` placed
    AFTER the terminal receipt had already been written.  On this mount `unlink`
    raises PermissionError (R522 hit it again on PROGRESS.json.bak_*; an in-place
    probe showed rename and write both succeed, so the restriction is on that one
    syscall, not on the directory).  The consequence was not theoretical: the run
    ended terminal-and-correct on disk but the process died on the very next line,
    the caller saw a traceback, and the lease stayed behind.  That is exactly the
    shape of the 72 residual leases R430 had to sweep up by hand, and it is why the
    charter carries a MANUAL fallback ("rename the lock to *.released").  This puts
    the documented fallback inside the tool:

      1. unlink -- the normal path, unchanged;
      2. on PermissionError, rename to `<lease>.released_by_<run_id>_<stage>`,
         the convention already on disk (e.g. `E96_V1.writer.lock.json
         .released_by_r500_finish`).  The customary path is then free, so a later
         `start` can re-acquire and `seal` no longer sees a held lease;
      3. if both fail, RECORD the failure and return -- never raise.  Once the
         receipt is terminal, crashing here destroys the caller's exit status
         while changing nothing on disk; the residue is better reported than
         thrown.

    The returned record is written into the receipt so the method used is legible
    from the run's own bytes rather than from a stderr line nobody kept.
    """
    record: dict[str, Any] = {"lease": str(lease), "stage": stage}
    # `Path("")` normalises to `Path(".")`, which exists and is a directory -- an
    # abort on a receipt with no `write_lease` used to reach `unlink` on the CWD.
    if str(lease) in {"", "."} or lease.is_dir() or not lease.exists():
        record["method"] = "ALREADY_ABSENT"
        record["released"] = True
        return record
    try:
        lease.unlink()
    except OSError as error:
        released = lease.with_name(f"{lease.name}.released_by_{run_id}_{stage}")
        try:
            lease.rename(released)
        except OSError as rename_error:
            record["method"] = "FAILED"
            record["released"] = False
            record["unlink_error"] = f"{type(error).__name__}:{error}"
            record["rename_error"] = f"{type(rename_error).__name__}:{rename_error}"
            record["note"] = (
                "WRITER_LEASE_RESIDUE_NOT_RELEASED;terminal receipt is still valid;"
                "sweep by hand per charter line 65"
            )
            return record
        record["method"] = "RENAMED_UNLINK_REFUSED"
        record["released"] = True
        record["released_path"] = str(released)
        record["unlink_error"] = f"{type(error).__name__}:{error}"
        return record
    record["method"] = "UNLINK"
    record["released"] = True
    return record


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


def sealed_manifest_declaration(seal_file: Path) -> str | None:
    """Read back the manifest SHA that an already-written seal declared.

    Returns None when there is no seal yet, when the file cannot be read, or
    when it predates the manifest self-declaration (declared_sha256 null).  All
    three mean "nothing to compare against", never "drift".  This function is
    read-only and must never raise: a seal that cannot be parsed is a reason to
    stay silent, not a reason to block a workstation (铁律一).
    """

    if not seal_file.is_file():
        return None
    try:
        payload = read_json(seal_file)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    for row in payload.get("layers") or []:
        if isinstance(row, dict) and row.get("layer") == "manifest":
            declared = row.get("declared_sha256")
            return str(declared) if declared else None
    return None


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
        # F-R524-01, same family as the acquire rollback above: a bare unlink
        # here masked the receipt-write failure with PermissionError and left the
        # lease held with no RUNNING receipt to explain it -- the worst residue
        # shape, because `seal` reads it as "somebody else is writing".
        release_lease(lease, args.writer_run_id, "start_rollback")
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
    # F-R523-01: terminal state is written FIRST and the lease released after, so a
    # release failure can never leave a finished run looking un-finished.  The
    # release record is then patched in; this second write happens before the
    # manifest exists, so nothing downstream has bound these bytes yet.
    release = release_lease(lease, str(payload.get("writer_run_id") or "unknown"), "finish")
    payload["lease_release"] = release
    atomic_json(receipt, payload)
    if not release.get("released"):
        finish_warnings.append(f"WRITER_FINISH_LEASE_NOT_RELEASED:{lease}")
        payload["finish_warnings"] = finish_warnings
        atomic_json(receipt, payload)
    elif release.get("method") == "RENAMED_UNLINK_REFUSED":
        print(
            f"WRITER_FINISH_LEASE_RENAMED_NOT_UNLINKED:{release.get('released_path')}",
            file=sys.stderr,
        )
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

    # The manifest row used to carry `actual_sha256` only, with
    # `declared_sha256=None` -- the one layer of the four-layer record that
    # declared nothing about itself.  The supervisor logged it as P2
    # "请封印工具补填" on ten consecutive episodes (E65/E66 … E95/E96), and
    # F-R491-04 named the concrete cost: the manifest embeds a build timestamp,
    # so re-running the builder after sealing changes its bytes while
    # `seal --check` still reported SEALED -- post-seal manifest drift was
    # invisible because there was nothing to compare against.
    #
    # Fix, in two halves: at WRITE time the seal declares the manifest SHA it
    # sealed (the seal file is the declaring artefact -- a manifest cannot
    # contain its own SHA, so the declaration has to live one level out); at
    # CHECK time that declaration is read back from the seal already on disk and
    # compared with the manifest's current bytes.
    #
    # A mismatch is a WARNING, never a refusal.  Drift detection is not a
    # registered criterion, and an unregistered criterion must never block a
    # workstation (铁律一) -- same disposition as the version warning and the
    # receipt-path warning above.  Seals written before this change declare
    # nothing, so they compare against nothing and stay silent.
    seal_file = args.seal or (args.seal_dir.resolve() / f"{episode}_V{version}_FOUR_LAYER_SEAL.json")
    seal_file = Path(seal_file).resolve()
    manifest_actual = sha256_file(manifest)
    if args.check:
        manifest_declared = sealed_manifest_declaration(seal_file)
        if manifest_declared and manifest_declared != manifest_actual:
            warnings.append(
                "WRITER_SEAL_MANIFEST_DRIFT_SINCE_SEAL:"
                f"{manifest_declared}->{manifest_actual}"
            )
    else:
        manifest_declared = manifest_actual

    rows.append({
        "layer": "manifest",
        "path": str(manifest),
        "resolved_path": str(manifest),
        "declared_sha256": manifest_declared,
        "actual_sha256": manifest_actual,
        "present": True,
    })

    # Cross-layer field parity (F-R542-01).
    #
    # R540 found four FS-1 segment-ledger fields had left the manifest layer at
    # E87 and stayed gone for ten episodes while the contract layer kept three
    # of them -- and closed with the actual defect: "no code has ever compared
    # the two layers."  The four-layer record is built by per-episode ad-hoc
    # builders, so a field disappears the moment one builder is copied from a
    # sibling that lacked it, and nothing notices.  E87 was caught by eye, on
    # its tenth repetition.
    #
    # Seal time is the one point every episode passes through, so the
    # comparison belongs here.  Same disposition as every other unregistered
    # criterion above: WARNING, never a refusal (铁律一).  Nothing in this block
    # may touch `failures`, and any error in it is swallowed into a warning --
    # a parity check that could break sealing would be worse than the drift it
    # reports.
    try:
        import re as _re

        import writer_cross_layer_field_parity as _parity

        _manifests = _parity.discover(manifest.parent, _parity.MANIFEST_RE)
        _contracts = _parity.discover(manifest.parent, _parity.CONTRACT_RE)
        _episode_number = int(_re.sub(r"^[Ee]", "", str(episode)))
        _reading = _parity.parity_for_episode(_episode_number, _manifests, _contracts)
        warnings.extend(_parity.warnings_for_episode(_reading))
    except Exception as exc:  # never let the parity check affect sealing
        warnings.append(f"WRITER_CROSS_LAYER_FIELD_PARITY_UNAVAILABLE:{type(exc).__name__}:{exc}")

    # Manifest-only key presence (F-R543-01) -- the blind spot of the check
    # immediately above.
    #
    # F-R542-01 reports a dropped field only when this episode's CONTRACT still
    # carries it.  That third condition is what keeps it from firing on every
    # incidental key, but it also means a key living in the manifest and nowhere
    # else can vanish without any code ever saying a word.  `beat_disposition`
    # is exactly that shape, and it is the one the charter calls 必填: the only
    # machine-readable evidence that Roger's seq=37/38 compression authorization
    # was exercised on purpose rather than by omission.  It left the manifest at
    # E90 and was still gone at E96 -- seven episodes, silently.
    #
    # The two checks partition the space by construction (one requires the key
    # IN the contract, the other requires it NOT IN the contract), so this adds
    # coverage without adding duplicate noise.
    #
    # Same disposition as every unregistered criterion here: WARNING, never a
    # refusal (铁律一).  This block may not touch `failures`, and any error in it
    # degrades to a warning -- a presence check that could break sealing would
    # be worse than the drift it reports.
    try:
        import re as _re

        import writer_manifest_only_key_presence as _presence

        _p_manifests = _presence.discover(manifest.parent, _presence.MANIFEST_RE)
        _p_contracts = _presence.discover(manifest.parent, _presence.CONTRACT_RE)
        _p_episode = int(_re.sub(r"^[Ee]", "", str(episode)))
        _p_reading = _presence.reading_for_episode(_p_episode, _p_manifests, _p_contracts)
        warnings.extend(_presence.warnings_for_episode(_p_reading))
    except Exception as exc:  # never let the presence check affect sealing
        warnings.append(
            f"WRITER_MANIFEST_ONLY_KEY_PRESENCE_UNAVAILABLE:{type(exc).__name__}:{exc}"
        )

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
    # F-R523-01: same ordering and same fallback as `finish`.
    release = release_lease(lease, str(payload.get("writer_run_id") or "unknown"), "abort")
    payload["lease_release"] = release
    atomic_json(receipt, payload)
    if not release.get("released"):
        print(f"WRITER_ABORT_LEASE_NOT_RELEASED:{lease}", file=sys.stderr)
    elif release.get("method") == "RENAMED_UNLINK_REFUSED":
        print(
            f"WRITER_ABORT_LEASE_RENAMED_NOT_UNLINKED:{release.get('released_path')}",
            file=sys.stderr,
        )
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
