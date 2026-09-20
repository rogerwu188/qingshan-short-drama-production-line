#!/usr/bin/env python3
"""Create isolated StoryClaw/NALU projects and ingest private source text.

This module is intentionally independent from ``storyclaw_nalu_runtime.py`` so
the TalentHub adapter can call it without duplicating project/bootstrap or URL
security logic.  It never writes source material into the engine checkout.

The URL fetcher is fail closed.  It accepts only HTTP(S), rejects credentials,
resolves every redirect target, rejects any non-public address, and connects to
the exact public address that was checked.  A failed intake raises
``IntakeBlocked`` and never emits an INGESTED receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import ssl
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

PROJECT_SCHEMA = "storyclaw.nalu.private_project.v1"
INTAKE_SCHEMA = "storyclaw.nalu.source_intake.v1"
SERIES_SCOPES_SCHEMA = "nalu.series_scopes.v1"
ORDERS_SCHEMA = "supervisor_orders_v1"
POLICY_PROFILE = "CURRENT_PORTABLE"
DEFAULT_EPISODE = "E01"
DEFAULT_MAX_BYTES = 32 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_REDIRECTS = 5

MODEL_PRIORITY = [
    "storyclaw/gpt-6-astra",
    "storyclaw/claude-opus-5",
    "storyclaw/gpt-5.6-sol",
]

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_EPISODE = re.compile(r"E[1-9][0-9]{0,3}\Z|E0[1-9][0-9]{0,2}\Z")
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_TEXT_CONTENT_TYPES = {
    "application/json",
    "application/xhtml+xml",
    "application/xml",
    "application/rss+xml",
    "application/atom+xml",
}


class IntakeBlocked(RuntimeError):
    """A fail-closed project or source-intake refusal."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_bytes(path: Path, payload: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_json(path: Path, payload: Any) -> None:
    _atomic_bytes(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntakeBlocked(f"PRIVATE_PROJECT_METADATA_INVALID:{path}:{exc}") from exc


def _checked_id(value: str, label: str) -> str:
    value = str(value or "").strip()
    if not _SAFE_ID.fullmatch(value) or value in {".", ".."}:
        raise IntakeBlocked(f"{label}_INVALID:{value!r}")
    return value


def _checked_episode(value: str) -> str:
    value = str(value or "").strip().upper()
    if not _EPISODE.fullmatch(value):
        raise IntakeBlocked(f"EPISODE_INVALID:{value!r}")
    return value


def derive_project_id(title: str) -> str:
    """Return a readable, collision-resistant project id."""
    ascii_title = unicodedata.normalize("NFKD", str(title or "")).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")[:40]
    slug = slug or "project"
    return f"{slug}-{secrets.token_hex(4)}"


def derive_scope_id(project_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", project_id).strip("_").upper()
    return _checked_id((value or "PROJECT")[:64], "SERIES_SCOPE_ID")


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _scope_paths(scope_id: str) -> dict[str, Any]:
    relative_root = f"runtime/series/{scope_id}"
    return {
        "series_id": scope_id,
        "series_root": relative_root,
        "asset_library": f"{relative_root}/asset_library.json",
        "asset_library_seed": f"{relative_root}/asset_library_seed.json",
        "voice_registry": f"{relative_root}/voice_registry.json",
        "voice_catalog": f"{relative_root}/voice_catalog.json",
        "voice_cast": f"{relative_root}/voice_cast.json",
        "entity_registry": f"{relative_root}/entity_registry.json",
        "agentcut_voice_policy": f"{relative_root}/agentcut_character_voice_reference_policy.json",
        "character_registry": f"{relative_root}/character_registry.json",
        "character_sources": f"{relative_root}/character_sources",
        "voice_refs": f"{relative_root}/voice_refs",
        "lexicon": f"{relative_root}/lexicon.json",
        "charter": None,
        "isolation": "private project scope; no registry may fall back to another project",
    }


def _empty_asset_library(scope_id: str) -> dict[str, Any]:
    return {
        "schema": "ai_drama.production_asset_library.v1",
        "project_id": scope_id,
        "library_version": 1,
        "assets": {
            "characters": {}, "wardrobe": {}, "scenes": {}, "props": {},
            "voices": {}, "accents": {}, "music": {}, "ambience": {},
            "sfx": {}, "reference_materials": {},
        },
        "note": "Empty private project library. Only admission tools may create LOCKED/PASS rows.",
    }


def _create_project_tree(
    staging: Path,
    final_root: Path,
    engine_root: Path,
    *,
    project_id: str,
    scope_id: str,
    title: str,
    episodes: list[str],
    language: str,
    aspect_ratio: str,
    budget_cap: int,
) -> dict[str, Any]:
    scope_root = staging / "runtime" / "series" / scope_id
    directories = [
        "runtime/pipeline_state/approvals",
        "runtime/pipeline_logs",
        "runtime/reports",
        "runtime/storyclaw_runs",
        "runtime/budget",
        "runtime/receipts/source_intake",
        "runtime/receipts/asset_confirmation",
        "runtime/receipts/supervisor",
        "runtime/orders",
        "runtime/reviews",
        "runtime/voice",
        "runtime/storyclaw_storage/workflow/nalu",
        "runtime/storyclaw_storage/workflow/tasks",
        f"runtime/series/{scope_id}/character_sources",
        f"runtime/series/{scope_id}/voice_refs",
        f"sources/{scope_id}/intake",
        "brand",
        "working_assets",
    ]
    for episode in episodes:
        directories.extend([
            f"writer_layers/{scope_id}/{episode}",
            f"runtime/reviews/{scope_id}/{episode}",
            f"preproduction/{episode}",
            f"deliverables/{episode}",
        ])
    for relative in directories:
        path = staging / relative
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)

    storage_root = final_root / "runtime" / "storyclaw_storage" / "workflow"
    orders_path = final_root / "runtime" / "orders" / "SUPERVISOR_ORDERS.json"
    created_at = utc_now()
    project_manifest = {
        "schema": PROJECT_SCHEMA,
        "status": "INITIALIZED_PRIVATE",
        "created_at_utc": created_at,
        "project_id": project_id,
        "series_scope_id": scope_id,
        "title": title,
        "episodes": episodes,
        "private_runtime_root": str(final_root),
        "engine_root": str(engine_root),
        "source_material_publication_allowed": False,
        "automatic_platform_upload_allowed": False,
        "paid_requests_enabled": False,
    }
    config = {
        "schema": "qingshan.pipeline.config.v1",
        "workspace": str(final_root),
        "project": {
            "id": project_id,
            "title": title,
            "language": language,
            "aspect_ratio": aspect_ratio,
        },
        "generation": {
            "provider": "giggle",
            "video_profile": "SD2_STANDARD_720P_9X16",
            "paid_requests_enabled": False,
            "max_parallel_tasks": 1,
            "budget_cap_credits_per_episode": budget_cap,
        },
        "authorization": {
            "supervisor_orders_path": str(orders_path),
            "confirmation_receipts_root": str(
                final_root / "runtime" / "receipts" / "asset_confirmation"
            ),
            "paid_order_seq": 0,
            "latest_order_seq": 0,
            "line_owner_id": "",
            "status": "NOT_AUTHORIZED",
        },
        "quality": {
            "prompt_preflight_required": True,
            "post_generation_scope": "TECHNICAL_AND_BASIC_PLOT",
            "release_fail_closed": True,
        },
        "release": {"automatic_platform_upload_enabled": False},
        "storyclaw": {
            "project_id": project_id,
            "series_scope_id": scope_id,
            "policy_profile": POLICY_PROFILE,
            "model_priority": MODEL_PRIORITY,
            "model_allowlist": MODEL_PRIORITY,
            "onboarding_status": "SOURCE_REQUIRED",
            "workflow_policy": {
                "script_first": True,
                "asset_matching_after_s1": True,
                "single_confirmation_before_generation": True,
                "confirmation_required_from_stage": "S3",
            },
            "storage": {
                "mode": "READ_ONLY_ENGINE_WITH_PRIVATE_WRITABLE_MOUNTS",
                "engine_root": str(engine_root),
                "workspace_mount_target": str(engine_root / "workflow" / "nalu"),
                "workspace_backing_path": str(storage_root / "nalu"),
                "transactions_mount_target": str(engine_root / "workflow" / "tasks"),
                "transactions_backing_path": str(storage_root / "tasks"),
                "writer_layers_root": str(final_root / "writer_layers"),
            },
        },
    }
    series_scopes = {
        "schema": SERIES_SCOPES_SCHEMA,
        "default_scope": scope_id,
        "episodes": {episode: scope_id for episode in episodes},
        "scopes": {scope_id: _scope_paths(scope_id)},
    }
    empty_library = _empty_asset_library(scope_id)
    private_documents: dict[Path, Any] = {
        staging / ".qingshan-private-runtime.json": project_manifest,
        staging / "runtime" / "project.json": project_manifest,
        staging / "qingshan.json": config,
        staging / "runtime" / "series_scopes.json": series_scopes,
        staging / "runtime" / "orders" / "SUPERVISOR_ORDERS.json": {
            "_schema": ORDERS_SCHEMA,
            "latest_order_seq": 0,
            "orders": [],
        },
        staging / "runtime" / "budget" / "ledger.json": {
            "schema": "nalu.episode_credit_budget_ledger_log.v1",
            "cap_credits_per_episode": budget_cap,
            "authority": "NOT_AUTHORIZED; paid work requires a source-receipted line-owner order",
            "money_rules": "No paid request is enabled by project initialization.",
            "entries": [],
            "latest_balance_snapshot": None,
            "updated_at_utc": created_at,
        },
        scope_root / "asset_library.json": empty_library,
        scope_root / "asset_library_seed.json": empty_library,
        scope_root / "voice_registry.json": {
            "schema": "qingshan.voice_reference_registry.v1",
            "status": "EMPTY_NOT_CAST",
            "line": scope_id,
            "voices": [],
        },
        scope_root / "voice_catalog.json": {
            "schema": "nalu.voice_catalog.v1",
            "status": "EMPTY_NOT_CAST",
            "voices": {},
        },
        scope_root / "voice_cast.json": {
            "schema": "qingshan.voice_cast.v1",
            "status": "EMPTY_NOT_CAST",
            "characters": {},
        },
        scope_root / "entity_registry.json": {
            "schema": "nalu.entity_registry.v1",
            "line": scope_id,
            "entity_aliases": {},
        },
        scope_root / "lexicon.json": {
            "schema": "qingshan.lexicon.v1",
            "world": scope_id,
            "version": "project-v1",
            "forbidden_terms": [],
            "canonical_names": {},
            "address_terms": {},
            "status": "EMPTY_PENDING_SCRIPT_DERIVATION",
            "note": (
                "Private project lexicon. The writing agent derives canonical names, "
                "address terms, and any setting-specific forbidden terms from this "
                "project's approved script before S1; no rules are inherited from "
                "another production."
            ),
        },
        scope_root / "agentcut_character_voice_reference_policy.json": {
            "schema": "agentcut.character_voice_reference_policy.v1",
            "line": scope_id,
            "status": "EMPTY_NOT_CAST",
            "roles": [],
        },
        scope_root / "character_registry.json": {
            "schema": "nalu.character_asset_registry.v1",
            "line": scope_id,
            "project_id": scope_id,
            "character_count": 0,
        },
    }
    for path, payload in private_documents.items():
        _atomic_json(path, payload)
    return project_manifest


def initialize_project(
    projects_root: Path | str,
    engine_root: Path | str,
    *,
    title: str,
    project_id: str | None = None,
    series_scope_id: str | None = None,
    episodes: Iterable[str] = (DEFAULT_EPISODE,),
    language: str = "zh-CN",
    aspect_ratio: str = "9:16",
    budget_cap: int = 8000,
) -> dict[str, Any]:
    """Atomically create one private runtime root below ``projects_root``."""
    title = str(title or "").strip()
    if not title:
        raise IntakeBlocked("PROJECT_TITLE_REQUIRED")
    project_id = _checked_id(project_id or derive_project_id(title), "PROJECT_ID")
    scope_id = _checked_id(series_scope_id or derive_scope_id(project_id), "SERIES_SCOPE_ID")
    checked_episodes = sorted({_checked_episode(value) for value in episodes})
    if not checked_episodes:
        raise IntakeBlocked("AT_LEAST_ONE_EPISODE_REQUIRED")
    if isinstance(budget_cap, bool) or not isinstance(budget_cap, int) or budget_cap <= 0:
        raise IntakeBlocked("BUDGET_CAP_MUST_BE_POSITIVE_INTEGER")

    base = Path(projects_root).expanduser().resolve()
    engine = Path(engine_root).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(base, 0o700)
    final_root = base / project_id
    if _inside(final_root, engine) or _inside(engine, final_root):
        raise IntakeBlocked(f"PRIVATE_RUNTIME_OVERLAPS_ENGINE:{final_root}:{engine}")
    if final_root.is_symlink():
        raise IntakeBlocked(f"PRIVATE_RUNTIME_SYMLINK_REFUSED:{final_root}")

    if final_root.exists():
        marker = _read_json(final_root / "runtime" / "project.json")
        expected = (project_id, scope_id, title, checked_episodes)
        actual = (
            marker.get("project_id"), marker.get("series_scope_id"), marker.get("title"),
            sorted(marker.get("episodes") or []),
        )
        if marker.get("schema") != PROJECT_SCHEMA or actual != expected:
            raise IntakeBlocked(f"PROJECT_ID_COLLISION_OR_CONFIGURATION_MISMATCH:{final_root}")
        return {**marker, "status": "EXISTS_UNCHANGED"}

    staging = Path(tempfile.mkdtemp(prefix=f".{project_id}.init-", dir=base))
    try:
        os.chmod(staging, 0o700)
        manifest = _create_project_tree(
            staging, final_root, engine,
            project_id=project_id,
            scope_id=scope_id,
            title=title,
            episodes=checked_episodes,
            language=language,
            aspect_ratio=aspect_ratio,
            budget_cap=budget_cap,
        )
        os.replace(staging, final_root)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def load_private_project(project_root: Path | str) -> tuple[Path, dict[str, Any]]:
    root = Path(project_root).expanduser().resolve()
    marker = _read_json(root / "runtime" / "project.json")
    if marker.get("schema") != PROJECT_SCHEMA or marker.get("status") != "INITIALIZED_PRIVATE":
        raise IntakeBlocked(f"NOT_AN_INITIALIZED_PRIVATE_PROJECT:{root}")
    if Path(str(marker.get("private_runtime_root") or "")).resolve() != root:
        raise IntakeBlocked(f"PRIVATE_RUNTIME_ROOT_BINDING_MISMATCH:{root}")
    return root, marker


def _decode_text(raw: bytes, declared_charset: str | None = None) -> tuple[str, str]:
    if b"\x00" in raw:
        raise IntakeBlocked("SOURCE_IS_NOT_TEXT:NUL_BYTE")
    candidates = [declared_charset, "utf-8-sig", "utf-8", "gb18030"]
    seen: set[str] = set()
    for encoding in candidates:
        if not encoding:
            continue
        normalized = encoding.strip().lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            text = raw.decode(normalized)
        except (LookupError, UnicodeDecodeError):
            continue
        if not text.strip():
            raise IntakeBlocked("SOURCE_TEXT_EMPTY")
        return text, normalized
    raise IntakeBlocked("SOURCE_TEXT_ENCODING_UNSUPPORTED")


def _commit_intake(
    root: Path,
    marker: dict[str, Any],
    *,
    source_id: str,
    files: Mapping[str, bytes],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    scope_id = str(marker["series_scope_id"])
    intake_root = root / "sources" / scope_id / "intake"
    intake_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = intake_root / _checked_id(source_id, "SOURCE_ID")
    receipt_path = destination / "SOURCE_INTAKE.json"
    if destination.exists():
        existing = _read_json(receipt_path)
        if existing.get("schema") != INTAKE_SCHEMA or existing.get("source_id") != source_id:
            raise IntakeBlocked(f"SOURCE_ID_COLLISION:{source_id}")
        if existing.get("intake_kind") != receipt.get("intake_kind") or \
                existing.get("rights_statement") != receipt.get("rights_statement"):
            raise IntakeBlocked(f"SOURCE_ID_COLLISION_PROVENANCE_MISMATCH:{source_id}")
        expected_hashes = {name: sha256_bytes(payload) for name, payload in files.items()}
        actual_hashes = {row.get("name"): row.get("sha256") for row in existing.get("artifacts") or []}
        if expected_hashes != actual_hashes:
            raise IntakeBlocked(f"SOURCE_ID_COLLISION_CONTENT_MISMATCH:{source_id}")
        receipt_copy = root / "runtime" / "receipts" / "source_intake" / f"{source_id}.json"
        if receipt_copy.is_file() and _read_json(receipt_copy) != existing:
            raise IntakeBlocked(f"SOURCE_RECEIPT_COPY_MISMATCH:{source_id}")
        if not receipt_copy.is_file():
            _atomic_json(receipt_copy, existing)
        return {**existing, "status": "EXISTS_UNCHANGED"}

    staging = Path(tempfile.mkdtemp(prefix=f".{source_id}.", dir=intake_root))
    try:
        os.chmod(staging, 0o700)
        artifacts = []
        for name, payload in files.items():
            safe_name = Path(name).name
            if safe_name != name or safe_name in {"", ".", "..", "SOURCE_INTAKE.json"}:
                raise IntakeBlocked(f"SOURCE_ARTIFACT_NAME_INVALID:{name!r}")
            _atomic_bytes(staging / safe_name, payload)
            artifacts.append({
                "name": safe_name,
                "path": str((Path("sources") / scope_id / "intake" / source_id / safe_name)),
                "sha256": sha256_bytes(payload),
                "size_bytes": len(payload),
            })
        full_receipt = {
            "schema": INTAKE_SCHEMA,
            "status": "INGESTED",
            "recorded_at_utc": utc_now(),
            "private_runtime": True,
            "project_id": marker["project_id"],
            "series_scope_id": scope_id,
            "source_id": source_id,
            **receipt,
            "artifacts": artifacts,
            "publication_allowed": False,
            "note": "Rights are recorded from the deployer; the engine does not verify them.",
        }
        _atomic_json(staging / "SOURCE_INTAKE.json", full_receipt)
        os.replace(staging, destination)
        receipt_copy = root / "runtime" / "receipts" / "source_intake" / f"{source_id}.json"
        _atomic_json(receipt_copy, full_receipt)
        return full_receipt
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def intake_local_text(
    project_root: Path | str,
    source_file: Path | str,
    *,
    rights_statement: str = "",
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    root, marker = load_private_project(project_root)
    source = Path(source_file).expanduser().resolve()
    if not source.is_file():
        raise IntakeBlocked(f"LOCAL_SOURCE_FILE_MISSING:{source}")
    size = source.stat().st_size
    if size <= 0 or size > max_bytes:
        raise IntakeBlocked(f"LOCAL_SOURCE_SIZE_REFUSED:{size}:MAX={max_bytes}")
    raw = source.read_bytes()
    text, encoding = _decode_text(raw)
    digest = sha256_bytes(raw)
    suffix = source.suffix.lower() if re.fullmatch(r"\.[a-z0-9]{1,8}", source.suffix.lower()) else ".txt"
    artifact_name = f"source{suffix}"
    return _commit_intake(
        root, marker,
        source_id=f"local-{digest[:16]}",
        files={artifact_name: raw},
        receipt={
            "intake_kind": "LOCAL_TEXT",
            "rights_statement": str(rights_statement or ""),
            "origin": {
                "path": str(source),
                "file_name": source.name,
                "media_type": mimetypes.guess_type(source.name)[0] or "text/plain",
                "sha256": digest,
                "size_bytes": size,
                "detected_encoding": encoding,
                "decoded_character_count": len(text),
            },
        },
    )


def intake_pasted_text(
    project_root: Path | str,
    text: str,
    *,
    rights_statement: str = "",
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Store text pasted into StoryClaw without exposing it in public state.

    The caller passes the text in memory.  The receipt records only private
    provenance metadata and a content digest; it never copies the text into an
    engine checkout or echoes it in the return value.
    """
    root, marker = load_private_project(project_root)
    if not isinstance(text, str) or not text.strip():
        raise IntakeBlocked("PASTED_SOURCE_TEXT_EMPTY")
    raw = text.encode("utf-8")
    if len(raw) > max_bytes:
        raise IntakeBlocked(f"PASTED_SOURCE_SIZE_REFUSED:{len(raw)}:MAX={max_bytes}")
    digest = sha256_bytes(raw)
    return _commit_intake(
        root, marker,
        source_id=f"pasted-{digest[:16]}",
        files={"source.txt": raw},
        receipt={
            "intake_kind": "PASTED_TEXT",
            "rights_statement": str(rights_statement or ""),
            "origin": {
                "transport": "STORYCLAW_PRIVATE_CONVERSATION",
                "sha256": digest,
                "size_bytes": len(raw),
                "detected_encoding": "utf-8",
                "decoded_character_count": len(text),
            },
        },
    )


def _canonical_url(parsed: SplitResult) -> str:
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, ""))


def _public_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError as exc:
        raise IntakeBlocked(f"URL_DNS_RETURNED_INVALID_IP:{value}") from exc
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if not address.is_global:
        raise IntakeBlocked(f"URL_TARGET_NOT_PUBLIC:{address}")
    return address


def _resolve_public_addresses(host: str, port: int) -> list[str]:
    try:
        rows = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise IntakeBlocked(f"URL_DNS_RESOLUTION_FAILED:{host}:{exc}") from exc
    addresses: list[str] = []
    for row in rows:
        value = str(row[4][0])
        normalized = str(_public_ip(value))
        if normalized not in addresses:
            addresses.append(normalized)
    if not addresses:
        raise IntakeBlocked(f"URL_DNS_NO_ADDRESSES:{host}")
    return addresses


@dataclass(frozen=True)
class ValidatedURL:
    url: str
    parsed: SplitResult
    host: str
    port: int
    addresses: tuple[str, ...]


def validate_public_url(
    url: str,
    *,
    resolver: Callable[[str, int], list[str]] = _resolve_public_addresses,
) -> ValidatedURL:
    try:
        parsed = urlsplit(str(url or "").strip())
        port = parsed.port
    except ValueError as exc:
        raise IntakeBlocked(f"URL_INVALID:{url!r}:{exc}") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise IntakeBlocked(f"URL_SCHEME_REFUSED:{parsed.scheme or 'missing'}")
    if parsed.username is not None or parsed.password is not None:
        raise IntakeBlocked("URL_CREDENTIALS_REFUSED")
    if not parsed.hostname:
        raise IntakeBlocked("URL_HOST_REQUIRED")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise IntakeBlocked(f"URL_LOCALHOST_REFUSED:{host}")
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise IntakeBlocked(f"URL_HOST_INVALID:{host}") from exc
    port = port or (443 if parsed.scheme.lower() == "https" else 80)
    if not 1 <= port <= 65535:
        raise IntakeBlocked(f"URL_PORT_INVALID:{port}")
    addresses = resolver(ascii_host, port)
    # Resolver injection is useful to the adapter/tests; the security invariant
    # is still enforced here even if a resolver returns an unchecked address.
    checked = tuple(str(_public_ip(value)) for value in addresses)
    if not checked:
        raise IntakeBlocked(f"URL_DNS_NO_ADDRESSES:{ascii_host}")
    canonical = _canonical_url(parsed)
    return ValidatedURL(canonical, parsed, ascii_host, port, checked)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, connect_ip: str, timeout: float):
        self._connect_ip = connect_ip
        super().__init__(host, port, timeout=timeout)

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._connect_ip, self.port), self.timeout, self.source_address,
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, connect_ip: str, timeout: float):
        self._connect_ip = connect_ip
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())

    def connect(self) -> None:
        raw = socket.create_connection(
            (self._connect_ip, self.port), self.timeout, self.source_address,
        )
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


@dataclass(frozen=True)
class HTTPResult:
    status: int
    reason: str
    headers: dict[str, str]
    body: bytes
    peer_ip: str


def _request_once(target: ValidatedURL, *, timeout: float, max_bytes: int) -> HTTPResult:
    errors: list[str] = []
    path = target.parsed.path or "/"
    if target.parsed.query:
        path += "?" + target.parsed.query
    host_header = target.host
    if ":" in host_header:
        host_header = f"[{host_header}]"
    default_port = 443 if target.parsed.scheme.lower() == "https" else 80
    if target.port != default_port:
        host_header += f":{target.port}"
    for address in target.addresses:
        connection_cls = (
            _PinnedHTTPSConnection if target.parsed.scheme.lower() == "https"
            else _PinnedHTTPConnection
        )
        connection = connection_cls(target.host, target.port, address, timeout)
        try:
            connection.request("GET", path, headers={
                "Host": host_header,
                "User-Agent": "StoryClaw-NALU-Source-Intake/1.0",
                "Accept": "text/plain,text/html,application/xhtml+xml,application/json;q=0.8",
                "Accept-Encoding": "identity",
                "Connection": "close",
            })
            response = connection.getresponse()
            headers = {key.lower(): value for key, value in response.getheaders()}
            if headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                raise IntakeBlocked(f"URL_CONTENT_ENCODING_REFUSED:{headers['content-encoding']}")
            try:
                declared_length = int(headers.get("content-length", "0"))
            except ValueError:
                declared_length = 0
            if declared_length > max_bytes:
                raise IntakeBlocked(f"URL_CONTENT_TOO_LARGE:{declared_length}:MAX={max_bytes}")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise IntakeBlocked(f"URL_CONTENT_TOO_LARGE:>{max_bytes}")
            peer_ip = str(_public_ip(str(connection.sock.getpeername()[0]))) if connection.sock else address
            if ipaddress.ip_address(peer_ip) != ipaddress.ip_address(address):
                raise IntakeBlocked(f"URL_PEER_IP_MISMATCH:{peer_ip}!={address}")
            return HTTPResult(response.status, response.reason, headers, body, peer_ip)
        except IntakeBlocked:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            errors.append(f"{address}:{type(exc).__name__}")
        finally:
            connection.close()
    raise IntakeBlocked(f"URL_FETCH_FAILED:{target.host}:{','.join(errors) or 'no_address'}")


def _content_type(headers: Mapping[str, str]) -> tuple[str, str | None]:
    raw = str(headers.get("content-type") or "").strip()
    parts = [part.strip() for part in raw.split(";")]
    media_type = parts[0].lower() if parts and parts[0] else ""
    charset = None
    for part in parts[1:]:
        if part.lower().startswith("charset="):
            charset = part.split("=", 1)[1].strip().strip('"\'')
    return media_type, charset


class _VisibleHTMLText(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "canvas", "template"}
    _BREAK = {"p", "div", "br", "li", "article", "section", "h1", "h2", "h3", "h4", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._SKIP:
            self.skip_depth += 1
        elif not self.skip_depth and tag in self._BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and tag in self._BREAK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line).strip() + "\n"


def _html_to_text(value: str) -> str:
    parser = _VisibleHTMLText()
    parser.feed(value)
    parser.close()
    text = parser.text()
    if not text.strip():
        raise IntakeBlocked("URL_HTML_HAS_NO_VISIBLE_TEXT")
    return text


def _fetch_url(
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    resolver: Callable[[str, int], list[str]] = _resolve_public_addresses,
    requester: Callable[..., HTTPResult] = _request_once,
) -> tuple[ValidatedURL, HTTPResult, list[dict[str, Any]]]:
    current = str(url or "").strip()
    redirects: list[dict[str, Any]] = []
    seen: set[str] = set()
    for redirect_count in range(MAX_REDIRECTS + 1):
        target = validate_public_url(current, resolver=resolver)
        if target.url in seen:
            raise IntakeBlocked(f"URL_REDIRECT_LOOP:{target.url}")
        seen.add(target.url)
        response = requester(target, timeout=timeout, max_bytes=max_bytes)
        peer_ip = str(_public_ip(response.peer_ip))
        if peer_ip not in target.addresses:
            raise IntakeBlocked(
                f"URL_PEER_IP_MISMATCH:{peer_ip}!={','.join(target.addresses)}"
            )
        if response.status in _REDIRECT_STATUSES:
            if redirect_count >= MAX_REDIRECTS:
                raise IntakeBlocked(f"URL_TOO_MANY_REDIRECTS:MAX={MAX_REDIRECTS}")
            location = response.headers.get("location")
            if not location:
                raise IntakeBlocked(f"URL_REDIRECT_WITHOUT_LOCATION:{response.status}")
            next_url = urljoin(target.url, location)
            redirects.append({"status": response.status, "from": target.url, "to": next_url})
            current = next_url
            continue
        if not 200 <= response.status < 300:
            raise IntakeBlocked(f"URL_HTTP_STATUS_BLOCKED:{response.status}:{response.reason}")
        return target, response, redirects
    raise IntakeBlocked(f"URL_TOO_MANY_REDIRECTS:MAX={MAX_REDIRECTS}")


def intake_url(
    project_root: Path | str,
    url: str,
    *,
    rights_statement: str = "",
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    resolver: Callable[[str, int], list[str]] = _resolve_public_addresses,
    requester: Callable[..., HTTPResult] = _request_once,
) -> dict[str, Any]:
    root, marker = load_private_project(project_root)
    if max_bytes <= 0 or timeout <= 0:
        raise IntakeBlocked("URL_FETCH_LIMITS_MUST_BE_POSITIVE")
    target, response, redirects = _fetch_url(
        url, timeout=timeout, max_bytes=max_bytes, resolver=resolver, requester=requester,
    )
    media_type, charset = _content_type(response.headers)
    if not (media_type.startswith("text/") or media_type in _TEXT_CONTENT_TYPES):
        raise IntakeBlocked(f"URL_CONTENT_TYPE_NOT_TEXT:{media_type or 'missing'}")
    text, encoding = _decode_text(response.body, charset)
    is_html = media_type in {"text/html", "application/xhtml+xml"}
    extracted = _html_to_text(text) if is_html else text
    if not extracted.strip():
        raise IntakeBlocked("URL_SOURCE_TEXT_EMPTY")
    raw_digest = sha256_bytes(response.body)
    identity = hashlib.sha256((target.url + "\n" + raw_digest).encode("utf-8")).hexdigest()
    files = {"source.txt": extracted.encode("utf-8")}
    if is_html:
        files["source.html"] = response.body
    return _commit_intake(
        root, marker,
        source_id=f"url-{identity[:16]}",
        files=files,
        receipt={
            "intake_kind": "URL_TEXT",
            "rights_statement": str(rights_statement or ""),
            "origin": {
                "requested_url": str(url),
                "final_url": target.url,
                "redirects": redirects,
                "http_status": response.status,
                "content_type": media_type,
                "declared_charset": charset,
                "detected_encoding": encoding,
                "response_sha256": raw_digest,
                "response_size_bytes": len(response.body),
                "connected_public_ip": response.peer_ip,
                "decoded_character_count": len(extracted),
            },
        },
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create an isolated private project runtime")
    init.add_argument("--projects-root", required=True)
    init.add_argument("--engine-root", required=True)
    init.add_argument("--title", required=True)
    init.add_argument("--project-id")
    init.add_argument("--scope-id")
    init.add_argument("--episode", action="append", default=[])
    init.add_argument("--language", default="zh-CN")
    init.add_argument("--aspect-ratio", default="9:16")
    init.add_argument("--budget-cap", type=int, default=8000)

    local = sub.add_parser("intake-file", help="copy a local source text into the private project")
    local.add_argument("--project-root", required=True)
    local.add_argument("--input", required=True)
    local.add_argument("--rights-statement", default="")
    local.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)

    pasted = sub.add_parser(
        "intake-text",
        help="copy pasted text from stdin into the private project",
    )
    pasted.add_argument("--project-root", required=True)
    pasted.add_argument(
        "--input", default="-",
        help="UTF-8 text file, or - to read stdin without putting text in argv",
    )
    pasted.add_argument("--rights-statement", default="")
    pasted.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)

    remote = sub.add_parser("intake-url", help="download public HTTP(S) text into the private project")
    remote.add_argument("--project-root", required=True)
    remote.add_argument("--url", required=True)
    remote.add_argument("--rights-statement", default="")
    remote.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    remote.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)

    describe = sub.add_parser("describe", help="read the private project marker")
    describe.add_argument("--project-root", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            result = initialize_project(
                args.projects_root, args.engine_root,
                title=args.title,
                project_id=args.project_id,
                series_scope_id=args.scope_id,
                episodes=args.episode or [DEFAULT_EPISODE],
                language=args.language,
                aspect_ratio=args.aspect_ratio,
                budget_cap=args.budget_cap,
            )
        elif args.command == "intake-file":
            result = intake_local_text(
                args.project_root, args.input,
                rights_statement=args.rights_statement,
                max_bytes=args.max_bytes,
            )
        elif args.command == "intake-text":
            if args.input == "-":
                pasted_text = sys.stdin.read()
            else:
                pasted_text = Path(args.input).read_text(encoding="utf-8")
            result = intake_pasted_text(
                args.project_root, pasted_text,
                rights_statement=args.rights_statement,
                max_bytes=args.max_bytes,
            )
        elif args.command == "intake-url":
            result = intake_url(
                args.project_root, args.url,
                rights_statement=args.rights_statement,
                max_bytes=args.max_bytes,
                timeout=args.timeout,
            )
        else:
            _, result = load_private_project(args.project_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except IntakeBlocked as exc:
        print(json.dumps({
            "schema": "storyclaw.nalu.intake_block.v1",
            "status": "BLOCKED",
            "reason": str(exc),
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
