#!/usr/bin/env python3
"""Plain-language onboarding and deterministic progress guidance for NALU.

This is the product-facing layer used by a TalentHub-installed StoryClaw
agent.  It creates a private project through ``storyclaw_project_intake``,
accepts exactly one source form (pasted text, local file, or public URL),
registers optional uploaded materials, and reports the next safe action in
bilingual JSON.

The module never calls a generation provider, reads credentials, enables paid
work, or creates a confirmation.  Before S3 the only confirmation it requests
is one confirmation of the complete, script-derived asset plan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    from tools import storyclaw_asset_plan_gate as _asset_gate
    from tools import storyclaw_project_intake as _intake
except ImportError:  # direct execution from tools/
    import storyclaw_asset_plan_gate as _asset_gate
    import storyclaw_project_intake as _intake


SCHEMA = "storyclaw.nalu.guided_onboarding.v1"
MATERIAL_RECEIPT_SCHEMA = "storyclaw.nalu.material_intake.v1"
DEFAULT_EPISODE = "E01"
DEFAULT_BUDGET_CAP = 8000
DEFAULT_MATERIAL_FILE_LIMIT = 100
DEFAULT_MATERIAL_FILE_BYTES = 256 * 1024 * 1024
DEFAULT_MATERIAL_TOTAL_BYTES = 1024 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PASS = {"PASS", "SKIPPED_ALREADY_PASS"}
_FAIL = {"BLOCKED", "FAIL", "FAILED", "ERROR"}


class OnboardingBlocked(RuntimeError):
    """A fail-closed onboarding or material-intake refusal."""


MESSAGES: dict[str, dict[str, str]] = {
    "SOURCE_REQUIRED": {
        "zh-CN": "请直接粘贴原著或大纲，或提供一个文本文件或公开网址。参考图、音频和视频可以同时提供；其他设置会采用安全默认值。",
        "en": "Paste the source or outline, or provide one text file or public URL. You may attach reference images, audio, or video now; safe defaults cover the remaining settings.",
    },
    "SCRIPT_READY": {
        "zh-CN": "来源已安全保存。系统下一步自动生成四层剧本并运行 S1 与 S2；现在不需要选择角色或逐项回答素材问题。",
        "en": "The source is stored privately. Next, the agent generates the four script layers and runs S1 and S2; no casting or item-by-item material choices are needed yet.",
    },
    "SCRIPT_IN_PROGRESS": {
        "zh-CN": "剧本或预制作正在运行。系统会从当前阶段继续，并保留真实门禁结果。",
        "en": "Script or preproduction work is in progress. The agent will resume from the current stage and preserve the real gate results.",
    },
    "SCRIPT_BLOCKED": {
        "zh-CN": "剧本或预制作门禁尚未通过。代理应根据真实失败项修复并重跑，不能跳过门禁。",
        "en": "A script or preproduction gate has not passed. The agent must fix the recorded failures and rerun; it cannot bypass the gate.",
    },
    "ASSET_PLAN_READY": {
        "zh-CN": "剧本与预制作已通过。系统将自动匹配已上传素材，并为所有缺口生成含模型、提示词和费用的完整方案。",
        "en": "Script and preproduction have passed. The agent will match uploaded materials and prepare one complete plan with models, prompts, and costs for every gap.",
    },
    "ASSET_PLAN_BLOCKED": {
        "zh-CN": "素材方案还不完整或未绑定当前剧本。代理应自行补齐角色、场景、道具、主角来源、提示词和费用后重新校验。",
        "en": "The asset plan is incomplete or not bound to the current script. The agent must complete character, scene, prop, protagonist-source, prompt, and cost coverage, then validate it again.",
    },
    "CONFIRMATION_REQUIRED": {
        "zh-CN": "请一次性确认下面的完整剧本与素材方案。确认前不会进入 S3、不会付费，也不会调用生成供应商。",
        "en": "Please confirm the complete script and asset plan below once. Before confirmation, S3, paid work, and provider generation remain disabled.",
    },
    "PRODUCTION_READY": {
        "zh-CN": "完整素材方案已确认。代理可以在订单、预算、付费双锁和事务去重全部通过后开始 S3→S8。",
        "en": "The complete asset plan is confirmed. The agent may start S3 through S8 only after order, budget, paid double-lock, and transaction-deduplication gates pass.",
    },
    "PRODUCTION_IN_PROGRESS": {
        "zh-CN": "生产正在进行或等待真实评审。系统会从私有状态恢复，已绑定的供应商任务不会重发。",
        "en": "Production is running or awaiting a real review. The agent will resume from private state and will not resend provider tasks already bound to transactions.",
    },
    "COMPLETE": {
        "zh-CN": "S1→S8 已完成。请在私有交付目录审看成片、QA、账本和检查点；系统不会自动发布到平台。",
        "en": "S1 through S8 are complete. Review the private final cut, QA, ledger, and checkpoint; the system will not publish to a platform automatically.",
    },
    "PROJECT_BLOCKED": {
        "zh-CN": "项目证据不一致或损坏。代理必须先修复列出的私有状态问题，不能继续生成。",
        "en": "Project evidence is inconsistent or damaged. The agent must repair the listed private-state issues before generation continues.",
    },
}


NEXT_ACTION = {
    "SOURCE_REQUIRED": ("PROVIDE_ONE_SOURCE", False),
    "SCRIPT_READY": ("RUN_S1_THEN_S2", True),
    "SCRIPT_IN_PROGRESS": ("RESUME_S1_OR_S2", True),
    "SCRIPT_BLOCKED": ("FIX_RECORDED_GATE_FAILURES", True),
    "ASSET_PLAN_READY": ("BUILD_COMPLETE_ASSET_PLAN", True),
    "ASSET_PLAN_BLOCKED": ("FIX_COMPLETE_ASSET_PLAN", True),
    "CONFIRMATION_REQUIRED": ("CONFIRM_COMPLETE_PLAN_ONCE", False),
    "PRODUCTION_READY": ("CHECK_PAID_GATES_THEN_RUN_S3_TO_S8", True),
    "PRODUCTION_IN_PROGRESS": ("RESUME_CURRENT_PRODUCTION_STAGE", True),
    "COMPLETE": ("REVIEW_PRIVATE_DELIVERABLES", False),
    "PROJECT_BLOCKED": ("REPAIR_PRIVATE_PROJECT_EVIDENCE", True),
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_bytes(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def _read_json(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"JSON_INVALID:{path}:{type(exc).__name__}"


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
        return True
    except (OSError, ValueError):
        return False


def _expand_materials(values: Iterable[Path | str]) -> list[Path]:
    files: list[Path] = []
    for raw in values:
        candidate = Path(raw).expanduser()
        if candidate.is_symlink():
            raise OnboardingBlocked(f"MATERIAL_SYMLINK_REFUSED:{candidate}")
        if candidate.is_file():
            files.append(candidate.resolve())
            continue
        if not candidate.is_dir():
            raise OnboardingBlocked(f"MATERIAL_PATH_MISSING:{candidate}")
        for directory, directory_names, file_names in os.walk(candidate, followlinks=False):
            directory_path = Path(directory)
            for name in list(directory_names):
                child = directory_path / name
                if child.is_symlink():
                    raise OnboardingBlocked(f"MATERIAL_SYMLINK_REFUSED:{child}")
            for name in file_names:
                child = directory_path / name
                if child.is_symlink():
                    raise OnboardingBlocked(f"MATERIAL_SYMLINK_REFUSED:{child}")
                if not child.is_file():
                    raise OnboardingBlocked(f"MATERIAL_NOT_REGULAR_FILE:{child}")
                files.append(child.resolve())
    # Stable ordering makes repeated agent calls deterministic.
    return sorted(dict.fromkeys(files), key=lambda value: str(value))


def register_materials(
    project_root: Path | str,
    materials: Iterable[Path | str],
    *,
    max_files: int = DEFAULT_MATERIAL_FILE_LIMIT,
    max_file_bytes: int = DEFAULT_MATERIAL_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MATERIAL_TOTAL_BYTES,
) -> list[dict[str, Any]]:
    """Copy user-provided materials into private content-addressed storage."""
    root, marker = _intake.load_private_project(project_root)
    files = _expand_materials(materials)
    if len(files) > max_files:
        raise OnboardingBlocked(f"MATERIAL_FILE_LIMIT_EXCEEDED:{len(files)}:MAX={max_files}")
    sizes = []
    for path in files:
        size = path.stat().st_size
        if size <= 0 or size > max_file_bytes:
            raise OnboardingBlocked(f"MATERIAL_FILE_SIZE_REFUSED:{path}:{size}:MAX={max_file_bytes}")
        sizes.append(size)
    if sum(sizes) > max_total_bytes:
        raise OnboardingBlocked(
            f"MATERIAL_TOTAL_SIZE_REFUSED:{sum(sizes)}:MAX={max_total_bytes}"
        )

    receipt_root = root / "runtime" / "receipts" / "material_intake"
    storage_root = root / "working_assets" / "user_uploads"
    for private_directory in (receipt_root, storage_root):
        if private_directory.is_symlink():
            raise OnboardingBlocked(f"PRIVATE_MATERIAL_DIRECTORY_SYMLINK:{private_directory}")
        private_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not _inside(private_directory, root):
            raise OnboardingBlocked(f"PRIVATE_MATERIAL_DIRECTORY_ESCAPES_PROJECT:{private_directory}")
    receipts: list[dict[str, Any]] = []
    for source, size in zip(files, sizes):
        digest = _sha256_file(source)
        material_id = f"material-{digest}"
        suffix = source.suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,12}", suffix):
            suffix = ".bin"
        content_directory = storage_root / digest
        if content_directory.is_symlink():
            raise OnboardingBlocked(
                f"PRIVATE_MATERIAL_CONTENT_DIRECTORY_SYMLINK:{content_directory}"
            )
        content_directory.mkdir(parents=False, exist_ok=True, mode=0o700)
        if not _inside(content_directory, root):
            raise OnboardingBlocked(
                f"PRIVATE_MATERIAL_CONTENT_DIRECTORY_ESCAPES_PROJECT:{content_directory}"
            )
        destination = content_directory / f"material{suffix}"
        receipt_path = receipt_root / f"{material_id}.json"
        existing, error = _read_json(receipt_path)
        if error:
            raise OnboardingBlocked(error)
        if isinstance(existing, dict):
            existing_path = Path(str(existing.get("private_path") or ""))
            if (
                existing.get("schema") != MATERIAL_RECEIPT_SCHEMA
                or existing.get("sha256") != digest
                or not existing_path.is_file()
                or _sha256_file(existing_path) != digest
            ):
                raise OnboardingBlocked(f"MATERIAL_RECEIPT_COLLISION:{receipt_path}")
            receipts.append({**existing, "status": "EXISTS_UNCHANGED"})
            continue

        payload = source.read_bytes()
        _atomic_bytes(destination, payload)
        receipt = {
            "schema": MATERIAL_RECEIPT_SCHEMA,
            "status": "INGESTED",
            "project_id": marker["project_id"],
            "series_scope_id": marker["series_scope_id"],
            "material_id": material_id,
            "source_kind": "USER_UPLOAD",
            "original_file_name": source.name,
            "private_path": str(destination.resolve()),
            "sha256": digest,
            "size_bytes": size,
            "publication_allowed": False,
        }
        _atomic_json(receipt_path, receipt)
        receipts.append(receipt)
    return receipts


def _source_receipts(root: Path, marker: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    receipts: list[dict[str, Any]] = []
    failures: list[str] = []
    receipt_root = root / "runtime" / "receipts" / "source_intake"
    for path in sorted(receipt_root.glob("*.json")) if receipt_root.is_dir() else []:
        row, error = _read_json(path)
        if error:
            failures.append(error)
            continue
        if not isinstance(row, dict) or row.get("schema") != _intake.INTAKE_SCHEMA:
            failures.append(f"SOURCE_RECEIPT_SCHEMA_INVALID:{path}")
            continue
        if row.get("status") not in {"INGESTED", "EXISTS_UNCHANGED"}:
            failures.append(f"SOURCE_RECEIPT_STATUS_INVALID:{path}")
            continue
        if row.get("project_id") != marker["project_id"] or row.get(
            "series_scope_id"
        ) != marker["series_scope_id"]:
            failures.append(f"SOURCE_RECEIPT_SCOPE_MISMATCH:{path}")
            continue
        artifacts = row.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            failures.append(f"SOURCE_RECEIPT_ARTIFACTS_INVALID:{path}")
            continue
        artifact_invalid = False
        for artifact in artifacts:
            relative = str((artifact or {}).get("path") or "") if isinstance(artifact, dict) else ""
            digest = str((artifact or {}).get("sha256") or "") if isinstance(artifact, dict) else ""
            artifact_path = root / relative
            if (
                not relative
                or Path(relative).is_absolute()
                or ".." in Path(relative).parts
                or not _SHA256.fullmatch(digest)
                or artifact_path.is_symlink()
                or not artifact_path.is_file()
                or not _inside(artifact_path, root)
                or _sha256_file(artifact_path) != digest
            ):
                artifact_invalid = True
                break
        if artifact_invalid:
            failures.append(f"SOURCE_RECEIPT_ARTIFACT_INVALID:{path}")
            continue
        receipts.append(row)
    return receipts, failures


def _material_receipts(root: Path, marker: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    receipts: list[dict[str, Any]] = []
    failures: list[str] = []
    receipt_root = root / "runtime" / "receipts" / "material_intake"
    for path in sorted(receipt_root.glob("*.json")) if receipt_root.is_dir() else []:
        row, error = _read_json(path)
        if error:
            failures.append(error)
            continue
        private_path = Path(str((row or {}).get("private_path") or ""))
        digest = str((row or {}).get("sha256") or "")
        if (
            not isinstance(row, dict)
            or row.get("schema") != MATERIAL_RECEIPT_SCHEMA
            or row.get("project_id") != marker["project_id"]
            or row.get("series_scope_id") != marker["series_scope_id"]
            or not _SHA256.fullmatch(digest)
            or private_path.is_symlink()
            or not private_path.is_file()
            or not _inside(private_path, root)
            or _sha256_file(private_path) != digest
        ):
            failures.append(f"MATERIAL_RECEIPT_INVALID:{path}")
            continue
        receipts.append(row)
    return receipts, failures


def _stage_row(state: Mapping[str, Any], stage: str) -> dict[str, Any]:
    stages = state.get("stages")
    row = stages.get(stage) if isinstance(stages, dict) else None
    return row if isinstance(row, dict) else {}


def _stage_status(state: Mapping[str, Any], stage: str) -> str | None:
    value = _stage_row(state, stage).get("status")
    return str(value).upper() if isinstance(value, str) else None


def _state_scope(state: Mapping[str, Any]) -> str | None:
    value = state.get("series_scope_id") or state.get("scope_id")
    if value:
        return str(value)
    nested = state.get("series_scope")
    if isinstance(nested, dict):
        value = nested.get("scope_id") or nested.get("series_scope_id")
        return str(value) if value else None
    return None


def _asset_context(
    root: Path,
    marker: Mapping[str, Any],
    episode: str,
    state: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    failures: list[str] = []
    config, config_error = _read_json(root / "qingshan.json")
    if config_error or not isinstance(config, dict):
        return None, [config_error or "PROJECT_CONFIG_INVALID"]
    storyclaw = config.get("storyclaw") if isinstance(config.get("storyclaw"), dict) else {}
    configured_models = storyclaw.get("asset_generation_model_allowlist")
    allowed_models = (
        {str(value).strip() for value in configured_models if str(value).strip()}
        if isinstance(configured_models, list)
        else set(_asset_gate.DEFAULT_ALLOWED_GENERATION_MODELS)
    )
    paths = (state.get("layers") or {}).get("paths") if isinstance(
        state.get("layers"), dict
    ) else None
    if not isinstance(paths, dict):
        details = _stage_row(state, "S1").get("details")
        layers = details.get("layers") if isinstance(details, dict) else None
        paths = layers.get("paths") if isinstance(layers, dict) else None
    if not isinstance(paths, dict):
        return None, ["SCRIPT_LAYER_PATHS_MISSING"]
    layer_paths: dict[str, Path] = {}
    for name in _asset_gate.LAYER_NAMES:
        value = str(paths.get(name) or "")
        if not value:
            failures.append(f"SCRIPT_LAYER_PATH_MISSING:{name}")
        else:
            layer_paths[name] = Path(value).expanduser()

    details = _stage_row(state, "S1").get("details")
    seq = details.get("writer_selfcheck_seq29") if isinstance(details, dict) else None
    seq_path = str(seq.get("report") or "") if isinstance(seq, dict) else ""
    if not seq_path:
        failures.append("SEQ29_REPORT_PATH_MISSING")
    s1_receipt = details.get("s1_gate_receipt") if isinstance(details, dict) else None
    s1_receipt_path = (
        str(s1_receipt.get("path") or "") if isinstance(s1_receipt, dict) else ""
    )
    if not s1_receipt_path:
        failures.append("IMMUTABLE_S1_GATE_RECEIPT_PATH_MISSING")
    s2_details = _stage_row(state, "S2").get("details")
    s2_receipt = (
        s2_details.get("s2_preproduction_receipt")
        if isinstance(s2_details, dict) else None
    )
    s2_receipt_path = (
        str(s2_receipt.get("path") or "")
        if isinstance(s2_receipt, dict) else ""
    )
    if not s2_receipt_path:
        # The immutable filename is part of the portable S2 contract.  Older
        # state rows may omit the detail while the real receipt is present.
        candidate = root / "runtime/pipeline_logs" / episode / "S2_PREPRODUCTION_RECEIPT.json"
        if candidate.is_file():
            s2_receipt_path = str(candidate)
    if not s2_receipt_path:
        failures.append("IMMUTABLE_S2_PREPRODUCTION_RECEIPT_PATH_MISSING")
    if failures:
        return None, failures
    return {
        "episode": episode,
        "series_scope_id": marker["series_scope_id"],
        "generation_contract_path": layer_paths["generation_contract"],
        "layer_paths": layer_paths,
        "s1_gate_evidence_path": Path(s1_receipt_path).expanduser(),
        "s2_gate_evidence_path": Path(s2_receipt_path).expanduser(),
        "seq29_report_path": Path(seq_path).expanduser(),
        "private_roots": [root],
        "allowed_models": allowed_models,
    }, []


def _plan_summary(
    plan: Mapping[str, Any], report: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    script_summary = str(plan.get("script_summary") or "").strip()
    if not script_summary:
        failures.append("HUMAN_READABLE_SCRIPT_SUMMARY_MISSING")
    assumptions = plan.get("assumptions")
    if not isinstance(assumptions, list):
        failures.append("PLAN_ASSUMPTIONS_LIST_MISSING")
        assumptions = []
    risks = plan.get("risks")
    if not isinstance(risks, list):
        failures.append("PLAN_RISKS_LIST_MISSING")
        risks = []
    rights_notes = plan.get("rights_and_identity_notes")
    if not isinstance(rights_notes, list) or not rights_notes:
        failures.append("PLAN_RIGHTS_IDENTITY_NOTES_MISSING")
        rights_notes = []

    def matches(field: str) -> list[dict[str, Any]]:
        result = []
        for row in plan.get(field) or []:
            if not isinstance(row, dict):
                continue
            result.append({
                "entity_type": row.get("entity_type"),
                "entity_id": row.get("entity_id"),
                "source_kind": row.get("source_kind") or row.get("source_origin"),
                "media_kind": row.get("media_kind"),
                "file_name": Path(str(row.get("source_path") or "")).name,
                "source_sha256": row.get("source_sha256"),
                "rights_basis": row.get("rights_basis"),
            })
        return result

    proposals = []
    for row in plan.get("ai_generation_proposals") or []:
        if isinstance(row, dict):
            proposals.append({
                "entity_type": row.get("entity_type"),
                "entity_id": row.get("entity_id"),
                "model": row.get("model"),
                "prompt": row.get("prompt"),
                "estimated_credits": row.get("estimated_credits"),
                "rights_and_identity_note": row.get("rights_and_identity_note"),
            })
    return {
        "asset_plan_sha256": report.get("asset_plan_sha256"),
        "script_evidence_sha256": report.get("script_evidence_sha256"),
        "script_summary": script_summary,
        "assumptions": assumptions,
        "required_entities": report.get("required_entities"),
        "coverage": report.get("coverage"),
        "matched_assets": (
            matches("character_matches")
            + matches("scene_matches")
            + matches("prop_matches")
        ),
        "ai_generation_proposals": proposals,
        "total_estimated_credits": report.get("total_estimated_credits"),
        "risks": risks,
        "rights_and_identity_notes": rights_notes,
        "confirmation_scope": {
            "includes": [
                "script_and_assumptions",
                "all_asset_matches",
                "all_ai_generation_proposals",
                "estimated_credits",
                "rights_to_use_uploaded_materials",
            ],
            "does_not_enable_platform_publication": True,
        },
    }, failures


def _human_input(state: str) -> dict[str, Any]:
    if state == "SOURCE_REQUIRED":
        return {
            "required": True,
            "confirmation": False,
            "request_mode": "ONE_SOURCE_INPUT",
            "accepted": ["pasted_text", "local_text_file", "public_url"],
        }
    if state == "CONFIRMATION_REQUIRED":
        return {
            "required": True,
            "confirmation": True,
            "request_mode": "SINGLE_COMPLETE_PLAN_CONFIRMATION",
            "item_by_item_questions_allowed": False,
        }
    return {"required": False, "confirmation": False}


def _response(
    *,
    state: str,
    root: Path,
    marker: Mapping[str, Any],
    episode: str,
    source_count: int,
    material_count: int,
    failures: Sequence[str] = (),
    asset_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    action, automatic = NEXT_ACTION[state]
    config, _config_error = _read_json(root / "qingshan.json")
    config = config if isinstance(config, dict) else {}
    project_config = config.get("project") if isinstance(config.get("project"), dict) else {}
    generation = config.get("generation") if isinstance(config.get("generation"), dict) else {}
    release = config.get("release") if isinstance(config.get("release"), dict) else {}
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "state": state,
        "message": MESSAGES[state],
        "project": {
            "project_id": marker["project_id"],
            "series_scope_id": marker["series_scope_id"],
            "title": marker.get("title"),
            "episode": episode,
            "private_runtime_root": str(root),
        },
        "progress": {
            "source_count": source_count,
            "material_count": material_count,
        },
        "defaults": {
            "aspect_ratio": project_config.get("aspect_ratio", "9:16"),
            "language": project_config.get("language", "zh-CN"),
            "first_episode": (marker.get("episodes") or [episode])[0],
            "budget_cap_credits_per_episode": generation.get(
                "budget_cap_credits_per_episode", DEFAULT_BUDGET_CAP
            ),
            "paid_requests_enabled": bool(generation.get("paid_requests_enabled")),
            "automatic_platform_upload_enabled": bool(
                release.get("automatic_platform_upload_enabled")
            ),
        },
        "next_action": {"id": action, "automatic": automatic},
        "human_input": _human_input(state),
        "safety": {
            "provider_posts_performed": 0,
            "credentials_read": False,
            "paid_work_enabled": False,
            "public_upload_enabled": False,
        },
        "failures": list(failures),
    }
    if asset_plan is not None:
        payload["complete_asset_plan"] = dict(asset_plan)
    return payload


def guided_status(project_root: Path | str, episode: str = DEFAULT_EPISODE) -> dict[str, Any]:
    """Derive the next user-visible step from private, file-backed evidence."""
    root, marker = _intake.load_private_project(project_root)
    if episode not in marker.get("episodes", []):
        raise OnboardingBlocked(f"EPISODE_NOT_DECLARED:{episode}")
    sources, source_failures = _source_receipts(root, marker)
    materials, material_failures = _material_receipts(root, marker)
    failures = source_failures + material_failures
    if len(sources) > 1:
        failures.append(f"MULTIPLE_PRIMARY_SOURCES_REFUSED:{len(sources)}")
    config, config_error = _read_json(root / "qingshan.json")
    if config_error or not isinstance(config, dict):
        failures.append(config_error or "PROJECT_CONFIG_INVALID")
    if failures:
        return _response(
            state="PROJECT_BLOCKED", root=root, marker=marker, episode=episode,
            source_count=len(sources), material_count=len(materials), failures=failures,
        )
    if not sources:
        return _response(
            state="SOURCE_REQUIRED", root=root, marker=marker, episode=episode,
            source_count=0, material_count=len(materials),
        )

    state_path = root / "runtime" / "pipeline_state" / f"{episode}.json"
    pipeline_state, state_error = _read_json(state_path)
    if state_error:
        return _response(
            state="PROJECT_BLOCKED", root=root, marker=marker, episode=episode,
            source_count=len(sources), material_count=len(materials), failures=[state_error],
        )
    if not isinstance(pipeline_state, dict):
        return _response(
            state="SCRIPT_READY", root=root, marker=marker, episode=episode,
            source_count=len(sources), material_count=len(materials),
        )
    scope = _state_scope(pipeline_state)
    if scope != marker["series_scope_id"]:
        return _response(
            state="PROJECT_BLOCKED", root=root, marker=marker, episode=episode,
            source_count=len(sources), material_count=len(materials),
            failures=[f"PIPELINE_SCOPE_MISMATCH:{scope!r}"],
        )

    s1 = _stage_status(pipeline_state, "S1")
    s2 = _stage_status(pipeline_state, "S2")
    if s1 in _FAIL or s2 in _FAIL:
        blockers = []
        for stage in ("S1", "S2"):
            blockers.extend(str(value) for value in (_stage_row(pipeline_state, stage).get("blockers") or []))
        return _response(
            state="SCRIPT_BLOCKED", root=root, marker=marker, episode=episode,
            source_count=len(sources), material_count=len(materials), failures=blockers,
        )
    if s1 not in _PASS or s2 not in _PASS:
        in_progress = bool(s1 or s2)
        return _response(
            state="SCRIPT_IN_PROGRESS" if in_progress else "SCRIPT_READY",
            root=root, marker=marker, episode=episode,
            source_count=len(sources), material_count=len(materials),
        )

    plan_root = root / "runtime" / "asset_plans" / str(marker["series_scope_id"])
    plan_path = plan_root / f"{episode}_ASSET_MATCH_PLAN.json"
    if not plan_path.is_file():
        return _response(
            state="ASSET_PLAN_READY", root=root, marker=marker, episode=episode,
            source_count=len(sources), material_count=len(materials),
        )
    context, context_failures = _asset_context(root, marker, episode, pipeline_state)
    if context is None:
        return _response(
            state="ASSET_PLAN_BLOCKED", root=root, marker=marker, episode=episode,
            source_count=len(sources), material_count=len(materials), failures=context_failures,
        )
    plan_report = _asset_gate.validate_asset_plan(plan_path, **context)
    if plan_report["status"] != "PASS":
        return _response(
            state="ASSET_PLAN_BLOCKED", root=root, marker=marker, episode=episode,
            source_count=len(sources), material_count=len(materials),
            failures=plan_report["failures"],
        )
    plan, plan_error = _read_json(plan_path)
    if plan_error or not isinstance(plan, dict):
        return _response(
            state="ASSET_PLAN_BLOCKED", root=root, marker=marker, episode=episode,
            source_count=len(sources), material_count=len(materials),
            failures=[plan_error or "ASSET_PLAN_JSON_INVALID"],
        )
    summary, summary_failures = _plan_summary(plan, plan_report)
    if summary_failures:
        return _response(
            state="ASSET_PLAN_BLOCKED", root=root, marker=marker, episode=episode,
            source_count=len(sources), material_count=len(materials),
            failures=summary_failures,
        )

    confirmation_path = plan_root / f"{episode}_ASSET_MATCH_CONFIRMATION.json"
    confirmation, confirmation_error = _read_json(confirmation_path)
    if confirmation_error:
        return _response(
            state="PROJECT_BLOCKED", root=root, marker=marker, episode=episode,
            source_count=len(sources), material_count=len(materials),
            failures=[confirmation_error], asset_plan=summary,
        )
    confirmed = False
    confirmation_failures: list[str] = []
    if isinstance(confirmation, dict):
        config, config_error = _read_json(root / "qingshan.json")
        if config_error or not isinstance(config, dict):
            confirmation_failures.append(config_error or "PROJECT_CONFIG_INVALID")
        else:
            authorization = config.get("authorization") or {}
            receipt_path = Path(str(confirmation.get("receipt_path") or ""))
            expected_sha = str(confirmation.get("receipt_sha256") or "")
            receipt_root = Path(str(authorization.get("confirmation_receipts_root") or ""))
            owner = str(authorization.get("line_owner_id") or "")
            report = _asset_gate.validate_confirmation_receipt(
                receipt_path,
                receipt_root=receipt_root,
                expected_receipt_sha256=expected_sha,
                expected_line_owner_id=owner,
                plan_path=plan_path,
                **context,
            )
            confirmed = report["status"] == "PASS"
            confirmation_failures.extend(report["failures"])
    if not confirmed:
        # A missing confirmation is the one normal human checkpoint.  A
        # malformed attempted receipt is shown as evidence but cannot advance.
        return _response(
            state="CONFIRMATION_REQUIRED", root=root, marker=marker, episode=episode,
            source_count=len(sources), material_count=len(materials),
            failures=confirmation_failures, asset_plan=summary,
        )

    if _stage_status(pipeline_state, "S8") in _PASS:
        production_state = "COMPLETE"
    else:
        started = any(_stage_status(pipeline_state, f"S{index}") for index in range(3, 9))
        production_state = "PRODUCTION_IN_PROGRESS" if started else "PRODUCTION_READY"
    return _response(
        state=production_state, root=root, marker=marker, episode=episode,
        source_count=len(sources), material_count=len(materials), asset_plan=summary,
    )


def add_source(
    project_root: Path | str,
    *,
    episode: str = DEFAULT_EPISODE,
    source_text: str | None = None,
    source_file: Path | str | None = None,
    source_url: str | None = None,
    rights_statement: str = "",
) -> dict[str, Any]:
    """Add the project's one primary source and return the next guided step."""
    supplied = sum(value is not None for value in (source_text, source_file, source_url))
    if supplied != 1:
        raise OnboardingBlocked("PROVIDE_EXACTLY_ONE_SOURCE_FORM")
    root, marker = _intake.load_private_project(project_root)
    existing, failures = _source_receipts(root, marker)
    if failures:
        raise OnboardingBlocked(";".join(failures))
    if existing:
        if len(existing) != 1:
            raise OnboardingBlocked("MULTIPLE_PRIMARY_SOURCES_REFUSED")
        current = existing[0]
        origin = current.get("origin") if isinstance(current.get("origin"), dict) else {}
        same = False
        if source_text is not None:
            same = (
                current.get("intake_kind") == "PASTED_TEXT"
                and origin.get("sha256") == hashlib.sha256(source_text.encode("utf-8")).hexdigest()
            )
        elif source_file is not None:
            path = Path(source_file).expanduser()
            same = (
                path.is_file()
                and current.get("intake_kind") == "LOCAL_TEXT"
                and origin.get("sha256") == _sha256_file(path)
            )
        else:
            same = (
                current.get("intake_kind") == "URL_TEXT"
                and origin.get("requested_url") == str(source_url)
            )
        if same and current.get("rights_statement") == str(rights_statement or ""):
            return guided_status(root, episode)
        raise OnboardingBlocked("PRIMARY_SOURCE_ALREADY_INGESTED")
    try:
        if source_text is not None:
            _intake.intake_pasted_text(
                root, source_text, rights_statement=rights_statement,
            )
        elif source_file is not None:
            _intake.intake_local_text(
                root, source_file, rights_statement=rights_statement,
            )
        else:
            _intake.intake_url(
                root, str(source_url), rights_statement=rights_statement,
            )
    except _intake.IntakeBlocked as exc:
        raise OnboardingBlocked(str(exc)) from exc
    return guided_status(root, episode)


def start_project(
    projects_root: Path | str,
    engine_root: Path | str,
    *,
    title: str | None = None,
    project_id: str | None = None,
    series_scope_id: str | None = None,
    episode: str = DEFAULT_EPISODE,
    source_text: str | None = None,
    source_file: Path | str | None = None,
    source_url: str | None = None,
    materials: Iterable[Path | str] = (),
    rights_statement: str = "",
    language: str = "zh-CN",
    aspect_ratio: str = "9:16",
    budget_cap: int = DEFAULT_BUDGET_CAP,
) -> dict[str, Any]:
    """Create an isolated project, ingest optional inputs, and return guidance."""
    supplied = sum(value is not None for value in (source_text, source_file, source_url))
    if supplied > 1:
        raise OnboardingBlocked("PROVIDE_EXACTLY_ONE_SOURCE_FORM")
    chosen_title = str(title or "").strip() or "Untitled short drama"
    marker = _intake.initialize_project(
        projects_root,
        engine_root,
        title=chosen_title,
        project_id=project_id,
        series_scope_id=series_scope_id,
        episodes=[episode],
        language=language,
        aspect_ratio=aspect_ratio,
        budget_cap=budget_cap,
    )
    root = Path(str(marker["private_runtime_root"])).resolve()
    try:
        if supplied:
            add_source(
                root,
                episode=episode,
                source_text=source_text,
                source_file=source_file,
                source_url=source_url,
                rights_statement=rights_statement,
            )
        register_materials(root, materials)
    except _intake.IntakeBlocked as exc:
        raise OnboardingBlocked(str(exc)) from exc
    return guided_status(root, episode)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="create a private project and show the next step")
    start.add_argument("--projects-root", required=True)
    start.add_argument("--engine-root", required=True)
    start.add_argument("--title", default="Untitled short drama")
    start.add_argument("--project-id")
    start.add_argument("--scope-id")
    start.add_argument("--episode", default=DEFAULT_EPISODE)
    source = start.add_mutually_exclusive_group()
    source.add_argument("--source-file")
    source.add_argument("--source-url")
    source.add_argument(
        "--source-text-file",
        help="UTF-8 text file, or - for stdin; source text is never placed in argv",
    )
    start.add_argument("--material", action="append", default=[])
    start.add_argument("--rights-statement", default="")
    start.add_argument("--language", default="zh-CN")
    start.add_argument("--aspect-ratio", default="9:16")
    start.add_argument("--budget-cap", type=int, default=DEFAULT_BUDGET_CAP)

    status = sub.add_parser("status", help="show the deterministic next step")
    status.add_argument("--project-root", required=True)
    status.add_argument("--episode", default=DEFAULT_EPISODE)

    add = sub.add_parser("add-source", help="add the project's one primary source")
    add.add_argument("--project-root", required=True)
    add.add_argument("--episode", default=DEFAULT_EPISODE)
    add_source_group = add.add_mutually_exclusive_group(required=True)
    add_source_group.add_argument("--source-file")
    add_source_group.add_argument("--source-url")
    add_source_group.add_argument(
        "--source-text-file",
        help="UTF-8 text file, or - for stdin; source text is never placed in argv",
    )
    add.add_argument("--rights-statement", default="")

    materials = sub.add_parser("add-materials", help="copy optional files into private storage")
    materials.add_argument("--project-root", required=True)
    materials.add_argument("--material", action="append", required=True)
    materials.add_argument("--episode", default=DEFAULT_EPISODE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "status":
            result = guided_status(args.project_root, args.episode)
        elif args.command == "add-materials":
            register_materials(args.project_root, args.material)
            result = guided_status(args.project_root, args.episode)
        elif args.command == "add-source":
            source_text = None
            if args.source_text_file is not None:
                if args.source_text_file == "-":
                    source_text = sys.stdin.read()
                else:
                    try:
                        source_text = Path(args.source_text_file).read_text(encoding="utf-8")
                    except (OSError, UnicodeError) as exc:
                        raise OnboardingBlocked(
                            f"PASTED_SOURCE_FILE_UNREADABLE:{args.source_text_file}:{exc}"
                        ) from exc
            result = add_source(
                args.project_root,
                episode=args.episode,
                source_text=source_text,
                source_file=args.source_file,
                source_url=args.source_url,
                rights_statement=args.rights_statement,
            )
        else:
            source_text = None
            if args.source_text_file is not None:
                if args.source_text_file == "-":
                    source_text = sys.stdin.read()
                else:
                    try:
                        source_text = Path(args.source_text_file).read_text(encoding="utf-8")
                    except (OSError, UnicodeError) as exc:
                        raise OnboardingBlocked(
                            f"PASTED_SOURCE_FILE_UNREADABLE:{args.source_text_file}:{exc}"
                        ) from exc
            result = start_project(
                args.projects_root,
                args.engine_root,
                title=args.title,
                project_id=args.project_id,
                series_scope_id=args.scope_id,
                episode=args.episode,
                source_text=source_text,
                source_file=args.source_file,
                source_url=args.source_url,
                materials=args.material,
                rights_statement=args.rights_statement,
                language=args.language,
                aspect_ratio=args.aspect_ratio,
                budget_cap=args.budget_cap,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OnboardingBlocked, _intake.IntakeBlocked) as exc:
        print(json.dumps({
            "schema": SCHEMA,
            "state": "BLOCKED",
            "message": {
                "zh-CN": "输入未能安全接收，请按原因修正后重试。",
                "en": "The input could not be accepted safely. Correct the reported reason and retry.",
            },
            "reason": str(exc),
            "safety": {
                "provider_posts_performed": 0,
                "credentials_read": False,
                "paid_work_enabled": False,
            },
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
