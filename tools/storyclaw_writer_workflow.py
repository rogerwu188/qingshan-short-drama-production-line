#!/usr/bin/env python3
"""Private, provenance-bound StoryClaw writer handoff for a generic NALU project.

``begin`` binds the real StoryClaw model/task identity, private source receipts,
public writer rules, and exact output paths.  The language-model turn authors the
five private drafts.  ``finalize`` binds the completed receipt, materializes a
script-derived per-project lexicon, seals all four layers, and atomically selects
the active handoff.  ``verify`` is the S1 fail-closed gate.

No command copies source text or authored layers into the public engine tree.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import secrets
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import canonical_writer_dispatcher as _dispatcher  # noqa: E402
from tools.canonical_writer_provenance import (  # noqa: E402
    PROVENANCE_SCHEMA,
    RECEIPT_SCHEMA,
    combined_rules_sha,
    validate_writer_provenance,
)
from tools.storyclaw_project_intake import (  # noqa: E402
    INTAKE_SCHEMA,
    MODEL_PRIORITY,
    PROJECT_SCHEMA,
    load_private_project,
)
from tools.writer_production_field_gate import validate_generation_contract  # noqa: E402

INPUT_SCHEMA = "storyclaw.nalu.writer_input_bundle.v1"
LEXICON_DRAFT_SCHEMA = "storyclaw.nalu.project_lexicon_draft.v1"
ACTIVE_SCHEMA = "storyclaw.nalu.active_writer_handoff.v1"
VERIFY_SCHEMA = "storyclaw.nalu.writer_handoff_verification.v1"
SEAL_SCHEMA = "qingshan.canonical_writer_four_layer_seal.v1"
AGENT_ID = "ai-drama-factory"
PROVIDER = "storyclaw"
ACTIVE_NAME = "ACTIVE_WRITER_HANDOFF.json"
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
EPISODE_RE = re.compile(r"E[0-9]+\Z")

RULE_RELATIVE_PATHS = (
    "agent_factory/storyclaw_portable/WRITER_CONTRACT.md",
    "agent_factory/storyclaw_portable/SCRIPT_COUNCIL_CHECKLIST.md",
    "agent_factory/claude_writer_v2/schemas/generation_contract.schema.json",
    "agent_factory/claude_writer_v2/schemas/manifest.schema.json",
)
PERFORMANCE_LEXICON = (
    ROOT / "lines/nalu/runtime/configs/PERFORMANCE_EMOTION_LEXICON_v1.json"
)
MANIFEST_SCHEMA = ROOT / "agent_factory/claude_writer_v2/schemas/manifest.schema.json"


class WriterWorkflowBlocked(RuntimeError):
    """Fail-closed private writer workflow refusal."""


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WriterWorkflowBlocked(f"{code}:{path}:{exc}") from exc
    if not isinstance(value, dict):
        raise WriterWorkflowBlocked(f"{code}:{path}:NOT_OBJECT")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _private_file(path: Path, root: Path, code: str) -> Path:
    resolved = path.expanduser().resolve()
    if not _inside(resolved, root) or not resolved.is_file():
        raise WriterWorkflowBlocked(f"{code}:{resolved}")
    return resolved


def _checked_episode(value: str) -> str:
    episode = str(value or "").strip().upper()
    if not EPISODE_RE.fullmatch(episode):
        raise WriterWorkflowBlocked(f"EPISODE_INVALID:{episode!r}")
    return episode


def _checked_version(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise WriterWorkflowBlocked(f"WRITER_VERSION_INVALID:{value!r}")
    return value


def _project(project_root: Path | str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    try:
        root, marker = load_private_project(project_root)
    except Exception as exc:
        raise WriterWorkflowBlocked(str(exc)) from exc
    if marker.get("schema") != PROJECT_SCHEMA:
        raise WriterWorkflowBlocked("PRIVATE_PROJECT_SCHEMA_INVALID")
    config = _read_json(root / "qingshan.json", "PROJECT_CONFIG_INVALID")
    scope = str(marker.get("series_scope_id") or "")
    if str((config.get("storyclaw") or {}).get("series_scope_id") or "") != scope:
        raise WriterWorkflowBlocked("PROJECT_SCOPE_CONFIG_MISMATCH")
    return root, marker, config


def _engine(marker: dict[str, Any]) -> Path:
    engine = Path(str(marker.get("engine_root") or "")).expanduser().resolve()
    required = engine / "tools/canonical_writer_dispatcher.py"
    if not required.is_file():
        raise WriterWorkflowBlocked(f"PROJECT_ENGINE_WRITER_TOOL_MISSING:{required}")
    if engine != ROOT.resolve():
        raise WriterWorkflowBlocked(
            f"PROJECT_ENGINE_RELEASE_MISMATCH:{engine}!={ROOT.resolve()}"
        )
    return engine


def _rule_rows(engine: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative in RULE_RELATIVE_PATHS:
        path = (engine / relative).resolve()
        if not _inside(path, engine) or not path.is_file():
            raise WriterWorkflowBlocked(f"WRITER_RULE_MISSING:{path}")
        rows.append({"path": str(path), "sha256": _sha(path)})
    return rows


def _source_rows(
    root: Path,
    marker: dict[str, Any],
    requested: Iterable[Path | str] | None = None,
) -> list[dict[str, Any]]:
    receipt_root = root / "runtime/receipts/source_intake"
    paths = [Path(value).expanduser().resolve() for value in (requested or [])]
    if not paths:
        paths = sorted(receipt_root.glob("*.json"))
    if not paths:
        raise WriterWorkflowBlocked("PRIVATE_SOURCE_RECEIPT_REQUIRED")
    rows: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for raw_path in paths:
        path = _private_file(raw_path, root, "SOURCE_RECEIPT_NOT_PRIVATE_OR_MISSING")
        if not _inside(path, receipt_root):
            raise WriterWorkflowBlocked(f"SOURCE_RECEIPT_OUTSIDE_CANONICAL_ROOT:{path}")
        if path in seen:
            continue
        seen.add(path)
        receipt = _read_json(path, "SOURCE_RECEIPT_INVALID")
        if receipt.get("schema") != INTAKE_SCHEMA or receipt.get("status") != "INGESTED":
            raise WriterWorkflowBlocked(f"SOURCE_RECEIPT_NOT_INGESTED:{path}")
        if receipt.get("project_id") != marker.get("project_id"):
            raise WriterWorkflowBlocked(f"SOURCE_RECEIPT_PROJECT_MISMATCH:{path}")
        if receipt.get("series_scope_id") != marker.get("series_scope_id"):
            raise WriterWorkflowBlocked(f"SOURCE_RECEIPT_SCOPE_MISMATCH:{path}")
        artifacts: list[dict[str, Any]] = []
        for artifact in receipt.get("artifacts") or []:
            relative = str((artifact or {}).get("path") or "")
            artifact_path = _private_file(
                root / relative, root, "SOURCE_ARTIFACT_NOT_PRIVATE_OR_MISSING"
            )
            declared = str((artifact or {}).get("sha256") or "")
            if not SHA256_RE.fullmatch(declared) or _sha(artifact_path) != declared:
                raise WriterWorkflowBlocked(f"SOURCE_ARTIFACT_SHA_MISMATCH:{artifact_path}")
            artifacts.append({
                "name": str((artifact or {}).get("name") or artifact_path.name),
                "path": str(artifact_path),
                "sha256": declared,
                "size_bytes": artifact_path.stat().st_size,
            })
        if not artifacts:
            raise WriterWorkflowBlocked(f"SOURCE_RECEIPT_HAS_NO_ARTIFACTS:{path}")
        rows.append({
            "source_id": receipt.get("source_id"),
            "intake_kind": receipt.get("intake_kind"),
            "receipt_path": str(path),
            "receipt_sha256": _sha(path),
            "artifacts": artifacts,
        })
    return rows


def _validate_bound_sources(
    root: Path, marker: dict[str, Any], bundle: dict[str, Any]
) -> list[dict[str, Any]]:
    declared = bundle.get("source_receipts")
    if not isinstance(declared, list) or not declared:
        raise WriterWorkflowBlocked("WRITER_INPUT_SOURCE_BINDINGS_MISSING")
    current = _source_rows(
        root,
        marker,
        [Path(str((row or {}).get("receipt_path") or "")) for row in declared],
    )
    by_path = {str(row["receipt_path"]): row for row in current}
    for bound in declared:
        if not isinstance(bound, dict):
            raise WriterWorkflowBlocked("WRITER_INPUT_SOURCE_BINDING_INVALID")
        path = str(bound.get("receipt_path") or "")
        row = by_path.get(path)
        if row is None:
            raise WriterWorkflowBlocked(f"WRITER_INPUT_SOURCE_RECEIPT_MISSING:{path}")
        if bound.get("receipt_sha256") != row.get("receipt_sha256"):
            raise WriterWorkflowBlocked(f"WRITER_INPUT_SOURCE_RECEIPT_DRIFT:{path}")
        expected_artifacts = {
            (str(item.get("path") or ""), str(item.get("sha256") or ""))
            for item in bound.get("artifacts") or [] if isinstance(item, dict)
        }
        actual_artifacts = {
            (str(item.get("path") or ""), str(item.get("sha256") or ""))
            for item in row.get("artifacts") or []
        }
        if expected_artifacts != actual_artifacts:
            raise WriterWorkflowBlocked(f"WRITER_INPUT_SOURCE_ARTIFACT_DRIFT:{path}")
    return current


def _validate_bound_rules(
    engine: Path, bundle: dict[str, Any], receipt: dict[str, Any]
) -> list[dict[str, Any]]:
    """Require the exact portable writer rule set that ``begin`` observed."""
    current = _rule_rows(engine)
    bundled = bundle.get("writer_rules")
    declared = (receipt.get("writer_rules") or {}).get("files")
    if bundled != current:
        raise WriterWorkflowBlocked("WRITER_INPUT_RULE_BINDING_DRIFT")
    if declared != current:
        raise WriterWorkflowBlocked("WRITER_RECEIPT_RULE_BINDING_DRIFT")
    combined = (receipt.get("writer_rules") or {}).get("combined_sha256")
    if combined != combined_rules_sha(current):
        raise WriterWorkflowBlocked("WRITER_RECEIPT_RULE_COMBINED_SHA_MISMATCH")
    return current


def _paths(root: Path, scope: str, episode: str, version: int,
           writer_run_id: str | None = None) -> dict[str, Path]:
    layer_root = root / "writer_layers" / scope / episode
    result = {
        "layer_root": layer_root,
        "narrative_canonical": layer_root / f"{episode}_NARRATIVE_CANONICAL_v{version}.md",
        "directing_script": layer_root / f"{episode}_DIRECTING_SCRIPT_v{version}.md",
        "generation_contract": layer_root / f"{episode}_GENERATION_CONTRACT_v{version}.json",
        "writer_manifest": layer_root / f"{episode}_manifest_v{version}.json",
        "lexicon_draft": layer_root / f"{episode}_LEXICON_DRAFT_v{version}.json",
        "project_lexicon": layer_root / f"{episode}_PROJECT_LEXICON_v{version}.json",
        "active_handoff": layer_root / ACTIVE_NAME,
        "lock_dir": root / "runtime/writer_locks" / scope,
        "receipt_dir": root / "runtime/receipts/writer" / scope / episode,
        "input_dir": root / "runtime/writer_inputs" / scope / episode,
        "seal_dir": root / "runtime/writer_seals" / scope / episode,
    }
    if writer_run_id:
        result["receipt"] = result["receipt_dir"] / f"{writer_run_id}.json"
        result["input_bundle"] = result["input_dir"] / f"{writer_run_id}.json"
        result["seal"] = result["seal_dir"] / f"{writer_run_id}_FOUR_LAYER_SEAL.json"
    return result


def _allowed_models(config: dict[str, Any]) -> set[str]:
    configured = (config.get("storyclaw") or {}).get("model_allowlist")
    values = configured if isinstance(configured, list) else MODEL_PRIORITY
    return {str(value).strip() for value in values if str(value).strip()}


def begin_writer_run(
    project_root: Path | str,
    episode: str,
    version: int,
    *,
    session_or_task_id: str,
    model_id: str | None = None,
    source_receipts: Iterable[Path | str] | None = None,
) -> dict[str, Any]:
    root, marker, config = _project(project_root)
    engine = _engine(marker)
    episode = _checked_episode(episode)
    version = _checked_version(version)
    if episode not in set(marker.get("episodes") or []):
        raise WriterWorkflowBlocked(f"EPISODE_NOT_DECLARED_FOR_PROJECT:{episode}")
    host_model = str(os.environ.get("STORYCLAW_MODEL") or "").strip()
    supplied_model = str(model_id or "").strip()
    if not host_model:
        raise WriterWorkflowBlocked("STORYCLAW_MODEL_HOST_EVIDENCE_REQUIRED")
    if supplied_model and supplied_model != host_model:
        raise WriterWorkflowBlocked(
            f"STORYCLAW_MODEL_HOST_EVIDENCE_MISMATCH:{supplied_model}!={host_model}"
        )
    model_id = host_model
    if not model_id or model_id not in _allowed_models(config):
        raise WriterWorkflowBlocked(f"STORYCLAW_WRITER_MODEL_NOT_ALLOWED:{model_id or 'MISSING'}")
    session_or_task_id = str(session_or_task_id or "").strip()
    if not session_or_task_id:
        raise WriterWorkflowBlocked("STORYCLAW_SESSION_OR_TASK_ID_REQUIRED")
    scope = str(marker["series_scope_id"])
    writer_run_id = (
        f"WRITER-{episode}-V{version}-STORYCLAW-{secrets.token_hex(6).upper()}"
    )
    paths = _paths(root, scope, episode, version, writer_run_id)
    for key in ("layer_root", "lock_dir", "receipt_dir", "input_dir", "seal_dir"):
        paths[key].mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(paths[key], 0o700)
    for key in (
        "narrative_canonical", "directing_script", "generation_contract",
        "writer_manifest", "lexicon_draft",
    ):
        if paths[key].exists():
            raise WriterWorkflowBlocked(f"WRITER_OUTPUT_VERSION_ALREADY_EXISTS:{paths[key]}")

    rules = _rule_rows(engine)
    sources = _source_rows(root, marker, source_receipts)
    bundle = {
        "schema": INPUT_SCHEMA,
        "status": "BOUND_PRIVATE_INPUT",
        "project_id": marker["project_id"],
        "series_scope_id": scope,
        "episode": episode,
        "version": version,
        "writer_run_id": writer_run_id,
        "agent_id": AGENT_ID,
        "provider": PROVIDER,
        "model_id": model_id,
        "session_or_task_id": session_or_task_id,
        "source_receipts": sources,
        "writer_rules": rules,
        "outputs": {
            key: str(paths[key]) for key in (
                "narrative_canonical", "directing_script", "generation_contract",
                "writer_manifest", "lexicon_draft",
            )
        },
        "lexicon_draft_contract": {
            "schema": LEXICON_DRAFT_SCHEMA,
            "required": [
                "world_basis", "forbidden_terms_basis", "forbidden_terms", "address_terms"
            ],
            "canonical_names": "derived from generation_contract.character_entities",
        },
        "privacy": {
            "private_runtime_root": str(root),
            "public_engine_output_allowed": False,
            "source_text_embedded_in_bundle": False,
        },
    }
    _atomic_json(paths["input_bundle"], bundle)
    args = argparse.Namespace(
        episode=episode,
        version=version,
        writer_run_id=writer_run_id,
        agent_id=AGENT_ID,
        provider=PROVIDER,
        model_id=model_id,
        session_or_task_id=session_or_task_id,
        input_bundle=paths["input_bundle"],
        rule=[Path(row["path"]) for row in rules],
        receipt=paths["receipt"],
        lock_dir=paths["lock_dir"],
    )
    with contextlib.redirect_stdout(io.StringIO()):
        _dispatcher.start(args)
    return {
        "schema": "storyclaw.nalu.writer_task.v1",
        "status": "AUTHORING_REQUIRED",
        "project_id": marker["project_id"],
        "series_scope_id": scope,
        "episode": episode,
        "version": version,
        "writer_run_id": writer_run_id,
        "model_id": model_id,
        "session_or_task_id": session_or_task_id,
        "input_bundle": str(paths["input_bundle"]),
        "input_bundle_sha256": _sha(paths["input_bundle"]),
        "receipt": str(paths["receipt"]),
        "outputs": bundle["outputs"],
        "next_action": "Author all five private outputs, then run finalize for this writer_run_id.",
    }


def _validate_pre_manifest_outputs(
    paths: dict[str, Path], episode: str, version: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    for key in ("narrative_canonical", "directing_script"):
        path = paths[key]
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            raise WriterWorkflowBlocked(f"WRITER_LAYER_MISSING_OR_EMPTY:{key}:{path}")
    contract = _read_json(paths["generation_contract"], "GENERATION_CONTRACT_INVALID")
    if contract.get("schema") != "qingshan.generation_contract.v3":
        raise WriterWorkflowBlocked("GENERATION_CONTRACT_SCHEMA_INVALID")
    if str(contract.get("episode") or "") != episode:
        raise WriterWorkflowBlocked("GENERATION_CONTRACT_EPISODE_MISMATCH")
    if not isinstance(contract.get("writer_selfcheck_seq29"), dict) or \
            contract["writer_selfcheck_seq29"].get("enforced") is not True:
        raise WriterWorkflowBlocked("WRITER_SELFCHECK_SEQ29_MUST_BE_ENFORCED")
    production = validate_generation_contract(contract)
    if production["status"] != "PASS":
        raise WriterWorkflowBlocked(
            "WRITER_PRODUCTION_FIELDS_FAIL:" + ",".join(production["failures"][:12])
        )
    manifest = _read_json(paths["writer_manifest"], "WRITER_MANIFEST_INVALID")
    if str(manifest.get("episode") or "") != episode:
        raise WriterWorkflowBlocked("WRITER_MANIFEST_EPISODE_MISMATCH")
    declared_version = str(manifest.get("version") or "").lower().lstrip("v")
    if declared_version != str(version):
        raise WriterWorkflowBlocked("WRITER_MANIFEST_VERSION_MISMATCH")
    manifest_schema = _read_json(MANIFEST_SCHEMA, "WRITER_MANIFEST_SCHEMA_INVALID")
    for key in manifest_schema.get("required") or []:
        if key not in manifest:
            raise WriterWorkflowBlocked(f"WRITER_MANIFEST_FIELD_MISSING:{key}")
    return contract, manifest


def _completed_receipt(paths: dict[str, Path]) -> dict[str, Any]:
    receipt = _read_json(paths["receipt"], "WRITER_RECEIPT_INVALID")
    if receipt.get("status") == "RUNNING":
        args = argparse.Namespace(
            receipt=paths["receipt"],
            authority=paths["narrative_canonical"],
            layer=[
                paths["narrative_canonical"], paths["directing_script"],
                paths["generation_contract"],
            ],
        )
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            _dispatcher.finish(args)
        receipt = _read_json(paths["receipt"], "WRITER_RECEIPT_INVALID")
    if receipt.get("status") != "COMPLETED":
        raise WriterWorkflowBlocked(f"WRITER_RECEIPT_NOT_COMPLETED:{receipt.get('status')}")
    expected = {
        str(paths["narrative_canonical"].resolve()): _sha(paths["narrative_canonical"]),
        str(paths["directing_script"].resolve()): _sha(paths["directing_script"]),
        str(paths["generation_contract"].resolve()): _sha(paths["generation_contract"]),
    }
    declared = {
        str(row.get("path")): str(row.get("sha256"))
        for row in receipt.get("layers_at_finish") or [] if isinstance(row, dict)
    }
    if declared != expected:
        raise WriterWorkflowBlocked("WRITER_RECEIPT_LAYER_BINDING_MISMATCH")
    return receipt


def _materialize_manifest(
    paths: dict[str, Path], manifest: dict[str, Any], receipt: dict[str, Any]
) -> dict[str, Any]:
    receipt_sha = _sha(paths["receipt"])
    manifest = dict(manifest)
    manifest["canonical_script"] = str(paths["narrative_canonical"])
    manifest["script_sha256"] = _sha(paths["narrative_canonical"])
    narrative = dict(manifest.get("narrative_canonical") or {})
    narrative.update({
        "authority_path": str(paths["narrative_canonical"]),
        "authority_sha256": _sha(paths["narrative_canonical"]),
    })
    manifest["narrative_canonical"] = narrative
    manifest["directing_script"] = {
        "path": str(paths["directing_script"]),
        "sha256": _sha(paths["directing_script"]),
    }
    manifest["generation_contract"] = {
        "path": str(paths["generation_contract"]),
        "sha256": _sha(paths["generation_contract"]),
    }
    manifest["writer_provenance"] = {
        "schema": PROVENANCE_SCHEMA,
        "writer_run_id": receipt["writer_run_id"],
        "agent_id": receipt["agent_id"],
        "provider": receipt["provider"],
        "model_id": receipt["model_id"],
        "session_or_task_id": receipt["session_or_task_id"],
        "input_bundle_sha256": receipt["input_bundle"]["sha256"],
        "writer_rules_sha256": receipt["writer_rules"]["combined_sha256"],
        "authority_output_sha256": receipt["authority_output"]["sha256"],
        "receipt_path": str(paths["receipt"]),
        "receipt_sha256": receipt_sha,
        "started_at": receipt["started_at"],
        "completed_at": receipt["completed_at"],
    }
    _atomic_json(paths["writer_manifest"], manifest)
    return manifest


def _string_list(value: Any, code: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise WriterWorkflowBlocked(code)
    return list(dict.fromkeys(item.strip() for item in value if item.strip()))


def _materialize_lexicon(
    root: Path,
    marker: dict[str, Any],
    paths: dict[str, Path],
    contract: dict[str, Any],
    receipt: dict[str, Any],
    bundle: dict[str, Any],
) -> Path:
    draft = _read_json(paths["lexicon_draft"], "PROJECT_LEXICON_DRAFT_INVALID")
    if draft.get("schema") != LEXICON_DRAFT_SCHEMA:
        raise WriterWorkflowBlocked("PROJECT_LEXICON_DRAFT_SCHEMA_INVALID")
    for key in ("world_basis", "forbidden_terms_basis"):
        if not str(draft.get(key) or "").strip():
            raise WriterWorkflowBlocked(f"PROJECT_LEXICON_DRAFT_FIELD_MISSING:{key}")
    forbidden = _string_list(draft.get("forbidden_terms"), "FORBIDDEN_TERMS_MUST_BE_STRING_LIST")
    address_terms = draft.get("address_terms")
    if not isinstance(address_terms, dict):
        raise WriterWorkflowBlocked("ADDRESS_TERMS_MUST_BE_OBJECT")
    canonical_names: dict[str, list[str]] = {}
    all_names: dict[str, str] = {}
    for row in contract.get("character_entities") or []:
        canonical = str((row or {}).get("canonical_name") or "").strip()
        if not canonical:
            raise WriterWorkflowBlocked("CHARACTER_CANONICAL_NAME_MISSING")
        aliases = _string_list((row or {}).get("aliases") or [], "CHARACTER_ALIASES_INVALID")
        canonical_names[canonical] = aliases
        for value in [canonical, *aliases]:
            owner = all_names.get(value)
            if owner is not None and owner != canonical:
                raise WriterWorkflowBlocked(f"CHARACTER_NAME_OR_ALIAS_COLLISION:{value}")
            all_names[value] = canonical
    performance = _read_json(PERFORMANCE_LEXICON, "PERFORMANCE_LEXICON_INVALID")
    scope = str(marker["series_scope_id"])
    lexicon_path = paths["project_lexicon"]
    latest_mirror = root / "runtime/series" / scope / "lexicon.json"
    lexicon = {
        "schema": "qingshan.lexicon.v1",
        "status": "SCRIPT_DERIVED",
        "world": scope,
        "version": f"writer-v{receipt['version']}",
        "world_basis": str(draft["world_basis"]).strip(),
        "forbidden_terms_basis": str(draft["forbidden_terms_basis"]).strip(),
        "forbidden_terms": forbidden,
        "canonical_names": canonical_names,
        "address_terms": address_terms,
        "emotions": performance.get("emotions") or [],
        "conflict_emotions": performance.get("conflict_emotions") or [],
        "trivial_body_actions": performance.get("trivial_body_actions") or [],
        "hold_instructions": performance.get("hold_instructions") or [],
        "performance_lexicon": {
            "path": str(PERFORMANCE_LEXICON),
            "sha256": _sha(PERFORMANCE_LEXICON),
            "schema": performance.get("schema"),
        },
        "derivation": {
            "project_id": marker["project_id"],
            "series_scope_id": scope,
            "episode": receipt["episode"],
            "writer_run_id": receipt["writer_run_id"],
            "model_id": receipt["model_id"],
            "generation_contract_sha256": _sha(paths["generation_contract"]),
            "writer_manifest_sha256": _sha(paths["writer_manifest"]),
            "source_receipts": [
                {
                    "source_id": row.get("source_id"),
                    "receipt_path": row.get("receipt_path"),
                    "receipt_sha256": row.get("receipt_sha256"),
                }
                for row in bundle.get("source_receipts") or []
            ],
            "derived_at_utc": receipt["completed_at"],
        },
        "note": "Private project lexicon derived from this sealed writer version; no other series is inherited.",
    }
    _atomic_json(lexicon_path, lexicon)
    # The immutable per-writer snapshot is S1 authority.  This series-level file
    # is only the latest private mirror for onboarding/status displays; a later
    # episode may refresh it without invalidating an older episode's handoff.
    _atomic_json(latest_mirror, lexicon)
    return lexicon_path


def _write_or_check_seal(paths: dict[str, Path]) -> dict[str, Any]:
    already_sealed = paths["seal"].is_file()
    args = argparse.Namespace(
        receipt=paths["receipt"],
        manifest=paths["writer_manifest"],
        seal=paths["seal"],
        seal_dir=paths["seal_dir"],
        lock_dir=paths["lock_dir"],
        check=already_sealed,
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
        _dispatcher.seal(args)
    verdict = json.loads(output.getvalue().strip().splitlines()[-1])
    if verdict.get("status") != "SEALED":
        raise WriterWorkflowBlocked("FOUR_LAYER_SEAL_NOT_PASS")
    return (
        _read_json(paths["seal"], "WRITER_SEAL_INVALID")
        if already_sealed else verdict
    )


def finalize_writer_run(
    project_root: Path | str,
    episode: str,
    version: int,
    *,
    writer_run_id: str,
) -> dict[str, Any]:
    root, marker, config = _project(project_root)
    engine = _engine(marker)
    episode = _checked_episode(episode)
    version = _checked_version(version)
    scope = str(marker["series_scope_id"])
    paths = _paths(root, scope, episode, version, writer_run_id)
    if paths["active_handoff"].is_file():
        previous = _read_json(paths["active_handoff"], "ACTIVE_WRITER_HANDOFF_INVALID")
        previous_version = int(previous.get("version") or 0)
        if previous.get("writer_run_id") != writer_run_id and previous_version >= version:
            raise WriterWorkflowBlocked(
                f"ACTIVE_WRITER_VERSION_NOT_MONOTONIC:{previous_version}>={version}"
            )
    receipt = _read_json(paths["receipt"], "WRITER_RECEIPT_INVALID")
    if receipt.get("writer_run_id") != writer_run_id or receipt.get("episode") != episode or \
            int(receipt.get("version") or 0) != version:
        raise WriterWorkflowBlocked("WRITER_RECEIPT_RUN_BINDING_MISMATCH")
    if receipt.get("agent_id") != AGENT_ID or receipt.get("provider") != PROVIDER:
        raise WriterWorkflowBlocked("WRITER_RECEIPT_IDENTITY_MISMATCH")
    host_model = str(os.environ.get("STORYCLAW_MODEL") or "").strip()
    if not host_model:
        raise WriterWorkflowBlocked("STORYCLAW_MODEL_HOST_EVIDENCE_REQUIRED")
    if host_model != receipt.get("model_id"):
        raise WriterWorkflowBlocked(
            f"STORYCLAW_MODEL_CHANGED_DURING_WRITER_RUN:{receipt.get('model_id')}!={host_model}"
        )
    if host_model not in _allowed_models(config):
        raise WriterWorkflowBlocked(f"STORYCLAW_WRITER_MODEL_NOT_ALLOWED:{host_model}")
    bundle_path = _private_file(
        Path(str((receipt.get("input_bundle") or {}).get("path") or "")),
        root,
        "WRITER_INPUT_BUNDLE_NOT_PRIVATE_OR_MISSING",
    )
    if bundle_path != paths["input_bundle"].resolve() or \
            _sha(bundle_path) != (receipt.get("input_bundle") or {}).get("sha256"):
        raise WriterWorkflowBlocked("WRITER_INPUT_BUNDLE_BINDING_MISMATCH")
    bundle = _read_json(bundle_path, "WRITER_INPUT_BUNDLE_INVALID")
    if bundle.get("schema") != INPUT_SCHEMA or bundle.get("writer_run_id") != writer_run_id:
        raise WriterWorkflowBlocked("WRITER_INPUT_BUNDLE_RUN_MISMATCH")
    for key, expected in (
        ("project_id", marker["project_id"]),
        ("series_scope_id", scope),
        ("episode", episode),
        ("version", version),
        ("agent_id", AGENT_ID),
        ("provider", PROVIDER),
        ("model_id", host_model),
        ("session_or_task_id", receipt.get("session_or_task_id")),
    ):
        if bundle.get(key) != expected:
            raise WriterWorkflowBlocked(f"WRITER_INPUT_BUNDLE_FIELD_MISMATCH:{key}")
    _validate_bound_sources(root, marker, bundle)
    _validate_bound_rules(engine, bundle, receipt)
    contract, manifest = _validate_pre_manifest_outputs(paths, episode, version)
    receipt = _completed_receipt(paths)
    manifest = _materialize_manifest(paths, manifest, receipt)
    lexicon_path = _materialize_lexicon(root, marker, paths, contract, receipt, bundle)
    seal = _write_or_check_seal(paths)

    layers = {
        key: {"path": str(paths[key]), "sha256": _sha(paths[key])}
        for key in (
            "narrative_canonical", "directing_script", "generation_contract", "writer_manifest"
        )
    }
    active = {
        "schema": ACTIVE_SCHEMA,
        "status": "SEALED",
        "project_id": marker["project_id"],
        "series_scope_id": scope,
        "episode": episode,
        "version": version,
        "writer_run_id": writer_run_id,
        "agent_id": AGENT_ID,
        "provider": PROVIDER,
        "model_id": receipt["model_id"],
        "session_or_task_id": receipt["session_or_task_id"],
        "input_bundle": {"path": str(paths["input_bundle"]), "sha256": _sha(paths["input_bundle"])},
        "writer_receipt": {"path": str(paths["receipt"]), "sha256": _sha(paths["receipt"])},
        "four_layer_seal": {"path": str(paths["seal"]), "sha256": _sha(paths["seal"])},
        "project_lexicon": {"path": str(lexicon_path), "sha256": _sha(lexicon_path)},
        "layers": layers,
        "sealed_at_utc": seal.get("sealed_at"),
    }
    _atomic_json(paths["active_handoff"], active)
    report = verify_writer_handoff(root, episode)
    if report["status"] != "PASS":
        raise WriterWorkflowBlocked(
            "FINALIZED_WRITER_HANDOFF_VERIFY_FAIL:" + ",".join(report["failures"][:12])
        )
    return {**active, "verification": report}


def _binding_path(binding: Any, root: Path, code: str) -> Path:
    if not isinstance(binding, dict):
        raise WriterWorkflowBlocked(code)
    path = Path(str(binding.get("path") or "")).expanduser()
    return _private_file(path, root, code)


def verify_writer_handoff(
    project_root: Path | str,
    episode: str,
    *,
    expected_layers: dict[str, Path | str] | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    observed: dict[str, Any] = {}
    try:
        root, marker, config = _project(project_root)
        episode = _checked_episode(episode)
        scope = str(marker["series_scope_id"])
        layer_root = root / "writer_layers" / scope / episode
        active_path = layer_root / ACTIVE_NAME
        active = _read_json(active_path, "ACTIVE_WRITER_HANDOFF_INVALID")
        if active.get("schema") != ACTIVE_SCHEMA or active.get("status") != "SEALED":
            failures.append("ACTIVE_WRITER_HANDOFF_NOT_SEALED")
        for key, expected in (
            ("project_id", marker["project_id"]), ("series_scope_id", scope),
            ("episode", episode), ("agent_id", AGENT_ID), ("provider", PROVIDER),
        ):
            if active.get(key) != expected:
                failures.append(f"ACTIVE_WRITER_HANDOFF_{key.upper()}_MISMATCH")
        if active.get("model_id") not in _allowed_models(config):
            failures.append("ACTIVE_WRITER_MODEL_NOT_ALLOWED")
        layer_paths: dict[str, Path] = {}
        for key in (
            "narrative_canonical", "directing_script", "generation_contract", "writer_manifest"
        ):
            binding = (active.get("layers") or {}).get(key)
            try:
                path = _binding_path(binding, root, f"WRITER_LAYER_NOT_PRIVATE_OR_MISSING:{key}")
                layer_paths[key] = path
                if not _inside(path, layer_root):
                    failures.append(f"WRITER_LAYER_OUTSIDE_EPISODE_ROOT:{key}")
                if _sha(path) != str(binding.get("sha256") or ""):
                    failures.append(f"WRITER_LAYER_SHA_MISMATCH:{key}")
                if expected_layers and key in expected_layers and \
                        path != Path(expected_layers[key]).expanduser().resolve():
                    failures.append(f"WRITER_LAYER_ACTIVE_PATH_MISMATCH:{key}")
            except WriterWorkflowBlocked as exc:
                failures.append(str(exc))
        receipt_path = _binding_path(active.get("writer_receipt"), root, "WRITER_RECEIPT_NOT_PRIVATE")
        input_path = _binding_path(active.get("input_bundle"), root, "WRITER_INPUT_NOT_PRIVATE")
        seal_path = _binding_path(active.get("four_layer_seal"), root, "WRITER_SEAL_NOT_PRIVATE")
        lexicon_path = _binding_path(active.get("project_lexicon"), root, "WRITER_LEXICON_NOT_PRIVATE")
        for name, path, binding in (
            ("RECEIPT", receipt_path, active.get("writer_receipt")),
            ("INPUT", input_path, active.get("input_bundle")),
            ("SEAL", seal_path, active.get("four_layer_seal")),
            ("LEXICON", lexicon_path, active.get("project_lexicon")),
        ):
            if _sha(path) != str((binding or {}).get("sha256") or ""):
                failures.append(f"ACTIVE_WRITER_{name}_SHA_MISMATCH")
        receipt = _read_json(receipt_path, "WRITER_RECEIPT_INVALID")
        if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("status") != "COMPLETED":
            failures.append("WRITER_RECEIPT_NOT_COMPLETED")
        for key in ("writer_run_id", "agent_id", "provider", "model_id", "session_or_task_id"):
            if active.get(key) != receipt.get(key):
                failures.append(f"ACTIVE_WRITER_RECEIPT_BINDING_MISMATCH:{key}")
        bundle = _read_json(input_path, "WRITER_INPUT_BUNDLE_INVALID")
        if bundle.get("schema") != INPUT_SCHEMA or bundle.get("writer_run_id") != active.get("writer_run_id"):
            failures.append("WRITER_INPUT_BUNDLE_RUN_MISMATCH")
        for key, expected in (
            ("project_id", marker["project_id"]),
            ("series_scope_id", scope),
            ("episode", episode),
            ("version", active.get("version")),
            ("agent_id", AGENT_ID),
            ("provider", PROVIDER),
            ("model_id", active.get("model_id")),
            ("session_or_task_id", active.get("session_or_task_id")),
        ):
            if bundle.get(key) != expected:
                failures.append(f"WRITER_INPUT_BUNDLE_FIELD_MISMATCH:{key}")
        _validate_bound_sources(root, marker, bundle)
        _validate_bound_rules(_engine(marker), bundle, receipt)
        manifest = _read_json(layer_paths["writer_manifest"], "WRITER_MANIFEST_INVALID")
        provenance_failures, provenance = validate_writer_provenance(
            manifest,
            receipt=receipt,
            receipt_sha256=_sha(receipt_path),
            authority_sha256=_sha(layer_paths["narrative_canonical"]),
        )
        failures.extend(provenance_failures)
        seal = _read_json(seal_path, "WRITER_SEAL_INVALID")
        if seal.get("schema") != SEAL_SCHEMA or seal.get("status") != "SEALED":
            failures.append("WRITER_SEAL_NOT_SEALED")
        sealed = {str(row.get("layer")): row for row in seal.get("layers") or [] if isinstance(row, dict)}
        for key in (
            "narrative_canonical", "directing_script", "generation_contract", "manifest"
        ):
            active_key = "writer_manifest" if key == "manifest" else key
            row = sealed.get(key) or {}
            if Path(str(row.get("resolved_path") or "")).resolve() != layer_paths[active_key]:
                failures.append(f"WRITER_SEAL_LAYER_PATH_MISMATCH:{key}")
            if str(row.get("actual_sha256") or "") != _sha(layer_paths[active_key]):
                failures.append(f"WRITER_SEAL_LAYER_SHA_MISMATCH:{key}")
        lexicon = _read_json(lexicon_path, "WRITER_LEXICON_INVALID")
        derivation = lexicon.get("derivation") or {}
        if lexicon.get("schema") != "qingshan.lexicon.v1" or lexicon.get("status") != "SCRIPT_DERIVED":
            failures.append("PROJECT_LEXICON_NOT_SCRIPT_DERIVED")
        if lexicon.get("world") != scope or derivation.get("series_scope_id") != scope:
            failures.append("PROJECT_LEXICON_SCOPE_MISMATCH")
        if derivation.get("episode") != episode or derivation.get("writer_run_id") != active.get("writer_run_id"):
            failures.append("PROJECT_LEXICON_WRITER_BINDING_MISMATCH")
        if derivation.get("generation_contract_sha256") != _sha(layer_paths["generation_contract"]):
            failures.append("PROJECT_LEXICON_CONTRACT_SHA_MISMATCH")
        if derivation.get("writer_manifest_sha256") != _sha(layer_paths["writer_manifest"]):
            failures.append("PROJECT_LEXICON_MANIFEST_SHA_MISMATCH")
        if derivation.get("project_id") != marker["project_id"] or \
                derivation.get("model_id") != active.get("model_id"):
            failures.append("PROJECT_LEXICON_PROVENANCE_MISMATCH")
        expected_sources = [
            {
                "source_id": row.get("source_id"),
                "receipt_path": row.get("receipt_path"),
                "receipt_sha256": row.get("receipt_sha256"),
            }
            for row in bundle.get("source_receipts") or []
        ]
        if derivation.get("source_receipts") != expected_sources:
            failures.append("PROJECT_LEXICON_SOURCE_BINDING_MISMATCH")
        performance = lexicon.get("performance_lexicon") or {}
        if performance.get("path") != str(PERFORMANCE_LEXICON) or \
                performance.get("sha256") != _sha(PERFORMANCE_LEXICON):
            failures.append("PROJECT_LEXICON_PERFORMANCE_BINDING_MISMATCH")
        contract = _read_json(
            layer_paths["generation_contract"], "GENERATION_CONTRACT_INVALID"
        )
        expected_names = {
            str(row.get("canonical_name") or "").strip():
            _string_list(row.get("aliases") or [], "CHARACTER_ALIASES_INVALID")
            for row in contract.get("character_entities") or []
            if str((row or {}).get("canonical_name") or "").strip()
        }
        if lexicon.get("canonical_names") != expected_names:
            failures.append("PROJECT_LEXICON_CANONICAL_NAMES_MISMATCH")
        observed = {
            "active_handoff": str(active_path),
            "writer_run_id": active.get("writer_run_id"),
            "model_id": active.get("model_id"),
            "layers": {key: str(value) for key, value in layer_paths.items()},
            "writer_provenance": provenance,
            "lexicon": str(lexicon_path),
            "source_receipt_count": len(bundle.get("source_receipts") or []),
        }
    except (WriterWorkflowBlocked, KeyError, TypeError, ValueError, OSError) as exc:
        failures.append(str(exc))
    failures = list(dict.fromkeys(failure for failure in failures if failure))
    return {
        "schema": VERIFY_SCHEMA,
        "status": "PASS" if not failures else "BLOCKED",
        "episode": str(episode),
        "failures": failures,
        "observed": observed,
    }


def resolve_active_layers(
    project_root: Path | str, scope_id: str, episode: str
) -> dict[str, Path] | None:
    """Return selected version paths for the adapter; S1 performs full verification."""
    root = Path(project_root).expanduser().resolve()
    active_path = root / "writer_layers" / scope_id / episode / ACTIVE_NAME
    if not active_path.is_file():
        return None
    active = _read_json(active_path, "ACTIVE_WRITER_HANDOFF_INVALID")
    if active.get("schema") != ACTIVE_SCHEMA or active.get("status") != "SEALED" or \
            active.get("series_scope_id") != scope_id or active.get("episode") != episode:
        raise WriterWorkflowBlocked("ACTIVE_WRITER_HANDOFF_BINDING_INVALID")
    out: dict[str, Path] = {}
    for key in (
        "narrative_canonical", "directing_script", "generation_contract", "writer_manifest"
    ):
        out[key] = _binding_path((active.get("layers") or {}).get(key), root, f"ACTIVE_LAYER_INVALID:{key}")
    out["project_lexicon"] = _binding_path(
        active.get("project_lexicon"), root, "ACTIVE_PROJECT_LEXICON_INVALID"
    )
    return out


def _print(value: dict[str, Any], stream=sys.stdout) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2), file=stream)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    begin = sub.add_parser("begin")
    begin.add_argument("--project-root", required=True, type=Path)
    begin.add_argument("--episode", required=True)
    begin.add_argument("--version", type=int, default=1)
    begin.add_argument("--session-or-task-id", required=True)
    begin.add_argument("--source-receipt", action="append", type=Path, default=[])
    finalize = sub.add_parser("finalize")
    finalize.add_argument("--project-root", required=True, type=Path)
    finalize.add_argument("--episode", required=True)
    finalize.add_argument("--version", required=True, type=int)
    finalize.add_argument("--writer-run-id", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--project-root", required=True, type=Path)
    verify.add_argument("--episode", required=True)
    verify.add_argument("--narrative", type=Path)
    verify.add_argument("--directing", type=Path)
    verify.add_argument("--contract", type=Path)
    verify.add_argument("--manifest", type=Path)
    verify.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "begin":
            result = begin_writer_run(
                args.project_root, args.episode, args.version,
                session_or_task_id=args.session_or_task_id,
                source_receipts=args.source_receipt,
            )
        elif args.command == "finalize":
            result = finalize_writer_run(
                args.project_root, args.episode, args.version,
                writer_run_id=args.writer_run_id,
            )
        else:
            provided = {
                "narrative_canonical": args.narrative,
                "directing_script": args.directing,
                "generation_contract": args.contract,
                "writer_manifest": args.manifest,
            }
            if any(value is not None for value in provided.values()) and \
                    not all(value is not None for value in provided.values()):
                raise WriterWorkflowBlocked("VERIFY_REQUIRES_ALL_FOUR_LAYER_PATHS")
            expected = provided if all(value is not None for value in provided.values()) else None
            result = verify_writer_handoff(
                args.project_root, args.episode, expected_layers=expected
            )
            if args.out:
                _atomic_json(args.out, result)
        _print(result)
        return 0 if result.get("status") not in {"BLOCKED", "FAIL"} else 3
    except (WriterWorkflowBlocked, SystemExit) as exc:
        _print({"status": "BLOCKED", "reason": str(exc)}, sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
