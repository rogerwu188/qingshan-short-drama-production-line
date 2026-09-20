#!/usr/bin/env python3
"""Build the reproducible StoryClaw/NALU release and TalentHub agent workspace.

The release is intentionally three bound artifacts:

* a complete source archive containing the public engine and the StoryClaw
  adapter; and
* an immutable tag-specific release-channel manifest binding the archive hash,
  compatibility contract, and whether TalentHub must republish; and
* a small TalentHub agent workspace whose bundled skill points at the exact
  Git commit and source archive SHA.

Private runtime data, source novels, media, credentials, ledgers, reviews and
episode state are never copied.  Publishing is opt-in and is only possible
after the repository checks and a clean worktree have passed.
"""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urlsplit, urlunsplit

_IMPORT_ROOT = Path(__file__).resolve().parents[1]
if str(_IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(_IMPORT_ROOT))

from tools.storyclaw_upgrade_classifier import (
    ClassificationBlocked,
    classify_release,
)
from tools.deployment_code_integrity import (
    MANIFEST as DEPLOYMENT_CODE_MANIFEST,
    SCHEMA as DEPLOYMENT_CODE_SCHEMA,
    included as deployment_code_included,
)
from tools import storyclaw_release_validation as _release_validation
from tools import storyclaw_dependency_bundle as _dependency_bundle
from tools import storyclaw_registry_clean_install_smoke as _registry_clean_smoke


ROOT = _IMPORT_ROOT
DEFAULT_OUTPUT = ROOT / "dist" / "storyclaw-talenthub"
GITHUB_REPO = "https://github.com/rogerwu188/qingshan-short-drama-production-line"
SKILL_NAME = "qingshan-nalu"
AGENT_ID = "ai-drama-factory"
PORTABLE_BRAIN_ROOT = ROOT / "agent_factory" / "storyclaw_portable"
CANONICAL_SKILL = ROOT / "skills" / SKILL_NAME / "SKILL.md"
CANONICAL_BOOTSTRAP = ROOT / "skills" / SKILL_NAME / "bootstrap_storyclaw.py"
RELEASE_TAG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
ARCHIVE_PREFIX = "qingshan-storyclaw-workflow/"
VALIDATION_SCHEMA = _release_validation.RECEIPT_SCHEMA
RELEASE_CHANNEL_SCHEMA = "storyclaw.nalu.release_channel.v1"
RELEASE_CHANNEL_NAME = "stable"
STABLE_INDEX_SCHEMA = "storyclaw.nalu.stable_index.v1"
STABLE_INDEX_FILENAME = "qingshan-storyclaw-stable-index.json"
STABLE_SIGNATURE_FILENAME = STABLE_INDEX_FILENAME + ".sig"
STABLE_CHANNEL_RELEASE_TAG = "storyclaw-stable-channel"
TALENTHUB_ATTESTATION_SCHEMA = "storyclaw.nalu.talenthub_package_attestation.v1"
TALENTHUB_ATTESTATION_FILENAME = "qingshan-storyclaw-talenthub-package-attestation.json"
TALENTHUB_ATTESTATION_SIGNATURE_FILENAME = TALENTHUB_ATTESTATION_FILENAME + ".sig"
REGISTRY_CANARY_RECEIPT_SCHEMA = "storyclaw.nalu.registry_canary_publish.v1"
REGISTRY_CANARY_RECEIPT_FILENAME = "REGISTRY_CANARY_PUBLISH_RECEIPT.json"
REGISTRY_FORMAL_RECEIPT_SCHEMA = "storyclaw.nalu.registry_formal_publish.v1"
REGISTRY_FORMAL_RECEIPT_FILENAME = "REGISTRY_FORMAL_PUBLISH_RECEIPT.json"
RELEASE_SIGNING_PUBLIC_KEY = ROOT / "configs" / "storyclaw_release_signing_public_key.pem"
RELEASE_SIGNING_PUBLIC_KEY_SHA256 = "d27484512874011dc5e894b602d6a42ca846a4e048688d32389acf7852d3646f"
RUNTIME_SCHEMA = "nalu.pipeline_state.v1"
MIN_INSTALLER_VERSION = "1.1.0"
STORYCLAW_REQUIREMENTS_ROOT = ROOT / "requirements" / "storyclaw"
PACKAGE_REQUIRED = "TALENTHUB_PACKAGE_REQUIRED"
ALLOWED_UPDATE_CLASSES = {
    "ENGINE_ONLY",
    PACKAGE_REQUIRED,
    "RUNTIME_MIGRATION_REQUIRED",
}
VALIDATION_CHECKS = _release_validation.VALIDATION_CHECKS
FORBIDDEN_ARCHIVE_PREFIXES = (
    "workflow/nalu/",
    "workflow/tasks/",
    "sources/",
    "deliverables/",
    ".qingshan-venv/",
)
FORBIDDEN_PORTABLE_MANIFEST_FILES = {
    # Historical replay fixtures may stay in Git, but they are not part of the
    # installable product.  A fresh customer's package must begin empty.
    "workflow/time_ledger/E17_time_ledger.json",
    "workflow/production_line/THREE_EPISODE_CONCURRENCY_POLICY.json",
    "configs/PLATFORM_RELEASE_AUTOMATION_POLICY_V1.json",
    "lines/nalu/runtime/configs/LEXICON_qingshan_v1.json",
    "lines/nalu/runtime/configs/LEXICON_yewujiang_v1.json",
    "tools/tests/fixtures/e04_negative_sample/contract_skeleton.json",
    "tools/tests/fixtures/e04_negative_sample/manifest_skeleton.json",
    "tools/tests/fixtures/e04_negative_sample/audio_metrics.json",
    "tools/tests/fixtures/e04_negative_sample/final_cut_summary.json",
    "tools/tests/test_nalu_e05_sync.py",
}
FORBIDDEN_PORTABLE_TEST_MODULES = {
    "tools.tests.test_nalu_e05_sync",
    "tools.tests.test_e51_pipeline_rectification",
}
PORTABLE_ARCHIVE_ROOT_FILES = {
    ".env.example",
    ".gitignore",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "pyproject.toml",
    "requirements-core.txt",
    "requirements-dev.txt",
    "requirements-media.txt",
    "setup.py",
}
PORTABLE_ARCHIVE_TREE_PREFIXES = (
    "qingshan_engine/",
    "agent_factory/claude_writer_v2/",
    "agent_factory/storyclaw_portable/",
    "skills/qingshan-nalu/",
    "lines/nalu/runtime/templates/",
)
HISTORICAL_TOOL_NAME_RE = re.compile(
    r"(?i)(?:^|[_-])(?:e|ep)\d{2,}(?:r|c)?(?:[_-]|\.|$)"
    r"|(?:^|[_-])u\d{2,}[a-z]?(?:[_-]|\.|$)"
)
REPOSITORY_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"((?:agent_factory|codex_docs|configs|docs|knowledge|lines|qingshan_engine|skills|tools|workflow)/"
    r"[A-Za-z0-9_.\-/\u4e00-\u9fff]+)"
)
EMPTY_ORDER_TEMPLATES = {
    "agent_factory/claude_writer/runtime_templates/SUPERVISOR_ORDERS.json",
    "agent_factory/claude_writer_v2/state/SUPERVISOR_ORDERS.json",
}
PORTABLE_MANIFEST = ROOT / "configs" / "PORTABLE_CORE_MANIFEST.json"
TALENTHUB_PROMPT_FILES = (
    "IDENTITY.md", "USER.md", "SOUL.md", "AGENTS.md", "HEARTBEAT.md"
)
TALENTHUB_FILE_LIMIT = 200 * 1024
TALENTHUB_PROMPT_TOTAL_LIMIT = 1024 * 1024

# These files are the public StoryClaw product surface, rather than historical
# episode replay material.  Keep the list explicit so a newly added adapter,
# installer or safety regression cannot silently be absent from clean-clone CI.
REQUIRED_STORYCLAW_PORTABLE_FILES = (
    ".github/workflows/storyclaw-release-candidate.yml",
    ".github/workflows/storyclaw-stable-promote.yml",
    "agent_factory/STORYCLAW_WORKFLOW_POLICY.md",
    "agent_factory/storyclaw_portable/AGENTS.md",
    "agent_factory/storyclaw_portable/HEARTBEAT.md",
    "agent_factory/storyclaw_portable/RELEASE_VALIDATION_INPUTS.example.json",
    "agent_factory/storyclaw_portable/SCRIPT_COUNCIL_CHECKLIST.md",
    "agent_factory/storyclaw_portable/SOUL.md",
    "agent_factory/storyclaw_portable/USER.md",
    "agent_factory/storyclaw_portable/WRITER_CONTRACT.md",
    "configs/PORTABLE_CORE_MANIFEST.json",
    "configs/storyclaw_release_signing_public_key.pem",
    "configs/storyclaw_release_signing_probe.txt",
    "configs/storyclaw_release_signing_probe.txt.sig",
    "lines/nalu/runtime/configs/LEXICON_portable_template_v1.json",
    "docs/STORYCLAW_NALU_DEPLOYMENT.md",
    "docs/STORYCLAW_NALU_USER_QUICKSTART.md",
    "docs/STORYCLAW_HOST_INSTALL.md",
    "docs/STORYCLAW_UPGRADE_CLASSIFICATION.md",
    "lines/nalu/runtime/tools/nalu_paths.py",
    "lines/nalu/runtime/tools/nalu_pipeline.py",
    "lines/nalu/runtime/tools/nalu_series_scope.py",
    "lines/nalu/runtime/tools/nalu_budget_ledger.py",
    "lines/nalu/runtime/tools/nalu_selective_bgm.py",
    "lines/nalu/runtime/tools/WIRING_NOTES.md",
    "lines/nalu/runtime/tools/bootstrap_identity_cards.py",
    "lines/nalu/runtime/tools/bootstrap_voice_references.py",
    "lines/nalu/runtime/tools/build_burnin_subtitles.py",
    "lines/nalu/runtime/tools/build_keyframe_manifest.py",
    "lines/nalu/runtime/tools/build_nalu_preproduction.py",
    "lines/nalu/runtime/tools/final_qa_evidence_bundle.py",
    "lines/nalu/runtime/tools/final_audience_review.py",
    "lines/nalu/runtime/tools/identity_qa_lock.py",
    "lines/nalu/runtime/tools/library_lock_non_plate.py",
    "lines/nalu/runtime/tools/materialize_paid_authorization.py",
    "lines/nalu/runtime/tools/nalu_media_tools.py",
    "lines/nalu/runtime/tools/nalu_policy_profile.py",
    "lines/nalu/runtime/tools/nalu_qa_common.py",
    "lines/nalu/runtime/tools/post_generation_qa_runner.py",
    "lines/nalu/runtime/tools/prompt_batch_register.py",
    "lines/nalu/runtime/tools/review_fill/video_sheets.py",
    "lines/nalu/runtime/tools/roger_gate_acceptance.py",
    "lines/nalu/runtime/tools/static_design_gate.py",
    "lines/nalu/runtime/tools/keyframe_q1_builder.py",
    "lines/nalu/runtime/tools/video_q2_builder.py",
    "lines/nalu/runtime/tools/vlm_review_protocol.py",
    "skills/qingshan-nalu/SKILL.md",
    "skills/qingshan-nalu/bootstrap_storyclaw.py",
    "tools/build_storyclaw_talenthub_release.py",
    "tools/storyclaw_dependency_bundle.py",
    "tools/deployment_code_integrity.py",
    "tools/knowledge_registry.py",
    "tools/render_portable_timeline.py",
    "tools/run_portable_ci.py",
    "tools/canonical_writer_dispatcher.py",
    "tools/canonical_writer_provenance.py",
    "tools/storyclaw_asset_plan_gate.py",
    "tools/storyclaw_audio_provider.py",
    "tools/storyclaw_guided_onboarding.py",
    "tools/storyclaw_install.py",
    "tools/storyclaw_nalu_runtime.py",
    "tools/storyclaw_project_intake.py",
    "tools/storyclaw_registry_clean_install_smoke.py",
    "tools/storyclaw_release_discovery.py",
    "tools/storyclaw_release_validation.py",
    "tools/storyclaw_release_surface.py",
    "tools/storyclaw_upgrade_classifier.py",
    "tools/storyclaw_upgrade_transaction.py",
    "tools/storyclaw_writer_workflow.py",
    "tools/tests/test_build_storyclaw_talenthub_release.py",
    "tools/tests/test_canonical_writer_dispatcher.py",
    "tools/tests/test_nalu_final_audience_review.py",
    "tools/tests/test_nalu_current_policy_profile.py",
    "tools/tests/test_nalu_media_tools.py",
    "tools/tests/test_nalu_paid_authority.py",
    "tools/tests/test_nalu_q1_roger_acceptance.py",
    "tools/tests/test_nalu_roger_gate_acceptance.py",
    "tools/tests/test_nalu_scoped_qa_paths.py",
    "tools/tests/test_nalu_selective_bgm_s6.py",
    "tools/tests/test_provider_scope_projection.py",
    "tools/tests/test_storyclaw_asset_plan_gate.py",
    "tools/tests/test_storyclaw_audio_provider.py",
    "tools/tests/test_storyclaw_dependency_bundle.py",
    "tools/tests/test_storyclaw_guided_onboarding.py",
    "tools/tests/test_storyclaw_install.py",
    "tools/tests/test_storyclaw_nalu_runtime.py",
    "tools/tests/test_storyclaw_project_intake.py",
    "tools/tests/test_storyclaw_registry_clean_install_smoke.py",
    "tools/tests/test_storyclaw_release_discovery.py",
    "tools/tests/test_storyclaw_release_validation.py",
    "tools/tests/test_storyclaw_generic_gate_smoke.py",
    "tools/tests/test_storyclaw_upgrade_classifier.py",
    "tools/tests/test_storyclaw_writer_workflow.py",
    "workflow/production_line/PORTABLE_CONCURRENCY_POLICY_TEMPLATE.json",
    "workflow/time_ledger/PORTABLE_TIME_LEDGER_TEMPLATE.json",
    "requirements/storyclaw/storyclaw-linux-x86_64-cpu-v1.in",
    "requirements/storyclaw/storyclaw-linux-x86_64-cpython310-cpu-v1.lock",
    "requirements/storyclaw/storyclaw-linux-x86_64-cpython311-cpu-v1.lock",
)
REQUIRED_STORYCLAW_TEST_MODULES = (
    "tools.tests.test_build_storyclaw_talenthub_release",
    "tools.tests.test_canonical_writer_dispatcher",
    "tools.tests.test_nalu_final_audience_review",
    "tools.tests.test_nalu_current_policy_profile",
    "tools.tests.test_nalu_media_tools",
    "tools.tests.test_nalu_paid_authority",
    "tools.tests.test_nalu_q1_roger_acceptance",
    "tools.tests.test_nalu_roger_gate_acceptance",
    "tools.tests.test_nalu_scoped_qa_paths",
    "tools.tests.test_nalu_selective_bgm_s6",
    "tools.tests.test_provider_scope_projection",
    "tools.tests.test_storyclaw_asset_plan_gate",
    "tools.tests.test_storyclaw_audio_provider",
    "tools.tests.test_storyclaw_dependency_bundle",
    "tools.tests.test_storyclaw_bootstrap",
    "tools.tests.test_storyclaw_guided_onboarding",
    "tools.tests.test_storyclaw_install",
    "tools.tests.test_storyclaw_nalu_runtime",
    "tools.tests.test_storyclaw_project_intake",
    "tools.tests.test_storyclaw_registry_clean_install_smoke",
    "tools.tests.test_storyclaw_release_discovery",
    "tools.tests.test_storyclaw_release_validation",
    "tools.tests.test_storyclaw_generic_gate_smoke",
    "tools.tests.test_storyclaw_upgrade_classifier",
    "tools.tests.test_storyclaw_writer_workflow",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_string_list(payload: dict[str, Any], field: str) -> list[str]:
    values = payload.get(field)
    if not isinstance(values, list) or not values or not all(
        isinstance(item, str) and item for item in values
    ):
        raise SystemExit(f"RELEASE_BLOCKED: portable manifest {field} must be a non-empty string list")
    duplicates = sorted({item for item in values if values.count(item) > 1})
    if duplicates:
        raise SystemExit(
            f"RELEASE_BLOCKED: portable manifest {field} has duplicate entries: "
            + ", ".join(duplicates)
        )
    return values


def validate_portable_release_manifest(path: Path = PORTABLE_MANIFEST) -> dict[str, int]:
    """Require the complete generic StoryClaw surface in clean-clone CI.

    The source archive is built from an immutable Git commit, but the portable
    manifest decides which files are compile-checked and which regressions run.
    Omitting a new installer or gate from that manifest would therefore make a
    superficially valid archive that was never actually release-tested.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"RELEASE_BLOCKED: invalid portable manifest: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != "qingshan.portable_core_manifest.v1":
        raise SystemExit("RELEASE_BLOCKED: unexpected portable manifest schema")
    required_files = _unique_string_list(payload, "required_files")
    test_modules = _unique_string_list(payload, "portable_test_modules")

    forbidden_files = sorted(set(required_files) & FORBIDDEN_PORTABLE_MANIFEST_FILES)
    forbidden_tests = sorted(set(test_modules) & FORBIDDEN_PORTABLE_TEST_MODULES)
    if forbidden_files or forbidden_tests:
        details = []
        if forbidden_files:
            details.append("files=" + ",".join(forbidden_files))
        if forbidden_tests:
            details.append("tests=" + ",".join(forbidden_tests))
        raise SystemExit(
            "RELEASE_BLOCKED: project-specific replay material is not portable: "
            + "; ".join(details)
        )

    missing_files = sorted(set(REQUIRED_STORYCLAW_PORTABLE_FILES) - set(required_files))
    missing_tests = sorted(set(REQUIRED_STORYCLAW_TEST_MODULES) - set(test_modules))
    if missing_files or missing_tests:
        details = []
        if missing_files:
            details.append("files=" + ",".join(missing_files))
        if missing_tests:
            details.append("tests=" + ",".join(missing_tests))
        raise SystemExit("RELEASE_BLOCKED: incomplete StoryClaw portable manifest: " + "; ".join(details))

    root = path.resolve().parents[1]
    unsafe: list[str] = []
    absent: list[str] = []
    for relative in required_files:
        candidate_relative = Path(relative)
        candidate = root / candidate_relative
        if candidate_relative.is_absolute() or ".." in candidate_relative.parts or candidate.is_symlink():
            unsafe.append(relative)
        elif not candidate.is_file():
            absent.append(relative)
    if unsafe:
        raise SystemExit(
            "RELEASE_BLOCKED: unsafe portable manifest file entries: " + ", ".join(sorted(unsafe))
        )
    if absent:
        raise SystemExit(
            "RELEASE_BLOCKED: missing portable manifest files: " + ", ".join(sorted(absent))
        )
    return {"required_file_count": len(required_files), "test_module_count": len(test_modules)}


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, check=check)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def assert_tag_points_to_head(tag: str, commit: str, allow_unreleased: bool) -> None:
    exists = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/tags/{tag}"],
        cwd=ROOT,
        check=False,
    ).returncode == 0
    if not exists:
        if allow_unreleased:
            return
        raise SystemExit(
            f"RELEASE_BLOCKED: tag {tag!r} does not exist; create the final tag before packaging"
        )
    tagged = git("rev-parse", "--verify", f"{tag}^{{commit}}")
    if tagged != commit:
        raise SystemExit(
            f"RELEASE_BLOCKED: tag {tag} resolves to {tagged}, but HEAD is {commit}"
        )


def assert_tag_pushed_to_origin(tag: str, commit: str, allow_unreleased: bool) -> str | None:
    """Require the immutable release tag to resolve to HEAD on ``origin``.

    ``ls-remote`` returns both the tag object and its peeled commit for an
    annotated tag.  A lightweight tag has only the direct record.  In either
    case the commit that an installer checks out must be the exact local HEAD.
    Experimental ``--allow-unreleased`` builds deliberately skip this network
    assertion and can never be published.
    """
    if allow_unreleased:
        return None
    ref = f"refs/tags/{tag}"
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", "origin", ref, f"{ref}^{{}}"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise SystemExit(f"RELEASE_BLOCKED: cannot query origin tag {tag}: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or "git ls-remote failed"
        raise SystemExit(f"RELEASE_BLOCKED: cannot query origin tag {tag}: {detail}")
    refs: dict[str, str] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2:
            refs[fields[1]] = fields[0].lower()
    remote_commit = refs.get(f"{ref}^{{}}") or refs.get(ref)
    if remote_commit is None:
        raise SystemExit(f"RELEASE_BLOCKED: tag {tag!r} has not been pushed to origin")
    if remote_commit != commit.lower():
        raise SystemExit(
            f"RELEASE_BLOCKED: origin tag {tag} resolves to {remote_commit}, but HEAD is {commit}"
        )
    return remote_commit


def validate_release_tag(tag: str) -> None:
    if not RELEASE_TAG_RE.fullmatch(tag):
        raise SystemExit(
            "RELEASE_BLOCKED: release tag must contain only letters, digits, '.', '_' and '-'"
        )
    if tag == STABLE_CHANNEL_RELEASE_TAG:
        raise SystemExit(
            "RELEASE_BLOCKED: storyclaw-stable-channel is reserved for the signed pointer"
        )


def validate_publish_mode(
    *,
    publish: bool,
    skip_checks: bool,
    allow_unreleased: bool,
    validation_receipt: Path | None = None,
) -> None:
    if publish and (skip_checks or allow_unreleased):
        raise SystemExit(
            "RELEASE_BLOCKED: --publish cannot be combined with --skip-checks or --allow-unreleased"
        )
    if publish and validation_receipt is None:
        raise SystemExit("RELEASE_BLOCKED: --publish requires --validation-receipt")


def assert_clean_worktree() -> None:
    status = git("status", "--porcelain")
    if status:
        raise SystemExit(
            "RELEASE_BLOCKED: git worktree is not clean; commit the final remote fixes first:\n"
            + status
        )


def github_release_archive_url(tag: str) -> str:
    filename = f"qingshan-storyclaw-workflow-{tag}.tar.gz"
    return f"{GITHUB_REPO}/releases/download/{quote(tag)}/{quote(filename)}"


def release_channel_filename(tag: str) -> str:
    return f"qingshan-storyclaw-release-channel-{tag}.json"


def github_release_channel_url(tag: str) -> str:
    filename = release_channel_filename(tag)
    return f"{GITHUB_REPO}/releases/download/{quote(tag)}/{quote(filename)}"


def stable_index_latest_url() -> str:
    return (
        f"{GITHUB_REPO}/releases/download/{STABLE_CHANNEL_RELEASE_TAG}/"
        f"{STABLE_INDEX_FILENAME}"
    )


def stable_signature_latest_url() -> str:
    return (
        f"{GITHUB_REPO}/releases/download/{STABLE_CHANNEL_RELEASE_TAG}/"
        f"{STABLE_SIGNATURE_FILENAME}"
    )


def build_dependency_profile_assets(
    output: Path,
    *,
    tag: str,
    commit: str,
    release_sequence: int,
    wheelhouse_root: Path | None = None,
    python: Path = Path(sys.executable),
) -> tuple[list[dict[str, Any]], tuple[Path, ...], list[dict[str, Any]]]:
    """Build both supported, release-bound Linux wheel bundles.

    Network resolution is a publisher-only operation.  Every selected wheel is
    already authorized by the checked-in ``--require-hashes`` lock; installed
    StoryClaw hosts consume only the resulting immutable offline archives.
    """
    bindings: list[dict[str, Any]] = []
    assets: list[Path] = []
    reports: list[dict[str, Any]] = []
    for profile in _dependency_bundle.SUPPORTED_PROFILES:
        lock = STORYCLAW_REQUIREMENTS_ROOT / profile.lock_filename
        if wheelhouse_root is None:
            temporary = tempfile.TemporaryDirectory(
                prefix=f".{profile.profile_id}-", dir=output
            )
            wheelhouse = Path(temporary.name) / "wheels"
            download = _dependency_bundle.download_profile_wheels(
                profile.profile_id, lock, wheelhouse, python=python
            )
        else:
            temporary = None
            wheelhouse = wheelhouse_root / profile.profile_id
            compact, wheels = _dependency_bundle.validate_wheelhouse(
                lock.read_bytes(), wheelhouse
            )
            download = {
                "status": "PREBUILT_VERIFIED",
                "profile_id": profile.profile_id,
                "wheelhouse": str(wheelhouse),
                "package_count": len(wheels),
                "compact_lock_sha256": hashlib.sha256(compact).hexdigest(),
                "network_used": False,
            }
        try:
            manifest_path, archive_path, manifest = _dependency_bundle.build_bundle(
                profile_id=profile.profile_id,
                source_lock=lock,
                wheelhouse=wheelhouse,
                output_dir=output,
                release_tag=tag,
                git_commit=commit,
                release_sequence=release_sequence,
            )
        finally:
            if temporary is not None:
                temporary.cleanup()
        binding = _dependency_bundle.release_binding(
            manifest_path, archive_path, manifest
        )
        bindings.append(binding)
        assets.extend((manifest_path, archive_path))
        reports.append({
            **download,
            "manifest": str(manifest_path),
            "manifest_sha256": binding["manifest_sha256"],
            "archive": str(archive_path),
            "archive_sha256": binding["archive_sha256"],
        })
    try:
        _dependency_bundle.validate_release_bindings(bindings, release_tag=tag)
    except _dependency_bundle.DependencyBundleBlocked as exc:
        raise SystemExit(f"RELEASE_BLOCKED: {exc}") from exc
    return bindings, tuple(assets), reports


def verify_published_github_assets(
    tag: str,
    expected_paths: tuple[Path, ...],
    *,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Require exact immutable tag assets before any public promotion."""
    repository = "rogerwu188/qingshan-short-drama-production-line"
    verified: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="storyclaw-release-assets-") as temporary:
        destination = Path(temporary)
        for expected in expected_paths:
            downloaded = runner(
                [
                    "gh", "release", "download", tag, "--repo", repository,
                    "--pattern", expected.name, "--dir", str(destination),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            actual = destination / expected.name
            if downloaded.returncode != 0 or not actual.is_file():
                raise SystemExit(
                    f"RELEASE_BLOCKED: GitHub Release asset missing: {expected.name}"
                )
            expected_sha = sha256(expected)
            actual_sha = sha256(actual)
            if actual.stat().st_size != expected.stat().st_size or actual_sha != expected_sha:
                raise SystemExit(
                    f"RELEASE_BLOCKED: GitHub Release asset bytes differ: {expected.name}"
                )
            verified.append({
                "name": expected.name,
                "size_bytes": expected.stat().st_size,
                "sha256": expected_sha,
            })
    return {"status": "PASS", "release_tag": tag, "assets": verified}


def read_published_stable_pointer(
    *,
    public_key: Path = RELEASE_SIGNING_PUBLIC_KEY,
    expected_public_key_sha256: str = RELEASE_SIGNING_PUBLIC_KEY_SHA256,
    runner: Any = subprocess.run,
) -> dict[str, Any] | None:
    """Read and verify the dedicated public stable pointer.

    A missing dedicated release means no StoryClaw stable has ever been
    promoted.  Every other lookup/download/signature/identity error blocks;
    callers must never interpret a transient GitHub failure as an initial
    release.
    """
    repository = "rogerwu188/qingshan-short-drama-production-line"
    viewed = runner(
        [
            "gh", "release", "view", STABLE_CHANNEL_RELEASE_TAG,
            "--repo", repository, "--json", "tagName",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if viewed.returncode != 0:
        detail = (viewed.stderr or viewed.stdout or "").strip()
        if re.search(r"(?:HTTP\s+404|release\s+not\s+found|not\s+found)", detail, re.I):
            return None
        raise SystemExit(
            "RELEASE_BLOCKED: cannot resolve dedicated StoryClaw stable channel: "
            + (detail or str(viewed.returncode))
        )
    try:
        release_row = json.loads(viewed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit("RELEASE_BLOCKED: stable-channel release metadata is invalid") from exc
    if release_row.get("tagName") != STABLE_CHANNEL_RELEASE_TAG:
        raise SystemExit("RELEASE_BLOCKED: stable-channel release tag identity mismatch")

    try:
        public_bytes = public_key.expanduser().resolve(strict=True).read_bytes()
    except OSError as exc:
        raise SystemExit(f"RELEASE_BLOCKED: pinned stable public key unavailable: {exc}") from exc
    if hashlib.sha256(public_bytes).hexdigest() != expected_public_key_sha256:
        raise SystemExit("RELEASE_BLOCKED: pinned stable public-key digest mismatch")

    with tempfile.TemporaryDirectory(prefix="storyclaw-stable-base-") as temporary:
        destination = Path(temporary)
        for filename in (STABLE_INDEX_FILENAME, STABLE_SIGNATURE_FILENAME):
            downloaded = runner(
                [
                    "gh", "release", "download", STABLE_CHANNEL_RELEASE_TAG,
                    "--repo", repository, "--pattern", filename,
                    "--dir", str(destination),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            if downloaded.returncode != 0 or not (destination / filename).is_file():
                raise SystemExit(
                    f"RELEASE_BLOCKED: dedicated stable-channel asset missing: {filename}"
                )
        index_path = destination / STABLE_INDEX_FILENAME
        signature_path = destination / STABLE_SIGNATURE_FILENAME
        verified = runner(
            [
                "openssl", "pkeyutl", "-verify", "-pubin", "-inkey",
                str(public_key.expanduser().resolve(strict=True)), "-rawin", "-in",
                str(index_path), "-sigfile", str(signature_path),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if verified.returncode != 0:
            raise SystemExit("RELEASE_BLOCKED: dedicated stable index signature is invalid")
        index_bytes = index_path.read_bytes()
        signature_bytes = signature_path.read_bytes()
        try:
            payload = json.loads(index_bytes.decode("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit("RELEASE_BLOCKED: dedicated stable index is invalid") from exc

    exact = {
        "schema": STABLE_INDEX_SCHEMA,
        "channel": RELEASE_CHANNEL_NAME,
        "validation_receipt_status": "PASS",
        "signing_key_sha256": expected_public_key_sha256,
    }
    bad = [key for key, value in exact.items() if payload.get(key) != value]
    if bad:
        raise SystemExit(
            "RELEASE_BLOCKED: dedicated stable index trust fields differ: " + ",".join(bad)
        )
    tag = str(payload.get("release_tag") or "")
    commit = str(payload.get("git_commit") or "").lower()
    sequence = payload.get("release_sequence")
    if not RELEASE_TAG_RE.fullmatch(tag) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit("RELEASE_BLOCKED: dedicated stable release identity is invalid")
    if type(sequence) is not int or sequence <= 0:
        raise SystemExit("RELEASE_BLOCKED: dedicated stable release sequence is invalid")
    if payload.get("update_class") not in ALLOWED_UPDATE_CLASSES:
        raise SystemExit("RELEASE_BLOCKED: dedicated stable update class is invalid")
    for field in (
        "release_channel_sha256", "source_archive_sha256", "validation_receipt_sha256"
    ):
        if not SHA256_RE.fullmatch(str(payload.get(field) or "")):
            raise SystemExit(f"RELEASE_BLOCKED: dedicated stable {field} is invalid")
    for field in ("release_channel_size_bytes", "source_archive_size_bytes"):
        if type(payload.get(field)) is not int or payload[field] <= 0:
            raise SystemExit(f"RELEASE_BLOCKED: dedicated stable {field} is invalid")
    if payload.get("release_channel_url") != github_release_channel_url(tag):
        raise SystemExit("RELEASE_BLOCKED: dedicated stable channel URL is not canonical")
    if payload.get("source_archive_url") != github_release_archive_url(tag):
        raise SystemExit("RELEASE_BLOCKED: dedicated stable archive URL is not canonical")
    try:
        tag_commit = git("rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
    except SystemExit as exc:
        raise SystemExit("RELEASE_BLOCKED: dedicated stable business tag is unavailable") from exc
    if tag_commit.lower() != commit:
        raise SystemExit("RELEASE_BLOCKED: dedicated stable tag does not match signed commit")
    return {
        **payload,
        "_index_sha256": hashlib.sha256(index_bytes).hexdigest(),
        "_signature_sha256": hashlib.sha256(signature_bytes).hexdigest(),
    }


def resolve_publish_classification_base(
    previous_release_ref: str | None,
    initial_release: bool,
    published_base: dict[str, Any] | None,
) -> tuple[str | None, bool]:
    """Bind formal classification to the signed public stable predecessor."""
    if published_base is None:
        if not initial_release:
            raise SystemExit(
                "RELEASE_BLOCKED: no dedicated StoryClaw stable pointer exists; "
                "the first publication must use --initial-release"
            )
        if previous_release_ref:
            raise SystemExit(
                "RELEASE_BLOCKED: an initial release cannot assert a previous release"
            )
        return None, True
    if initial_release:
        raise SystemExit(
            "RELEASE_BLOCKED: a signed StoryClaw stable already exists; "
            "--initial-release is forbidden"
        )
    trusted_tag = str(published_base["release_tag"])
    if previous_release_ref and previous_release_ref != trusted_tag:
        raise SystemExit(
            "RELEASE_BLOCKED: --previous-release-ref differs from the signed "
            f"StoryClaw stable base {trusted_tag}"
        )
    return trusted_tag, False


def write_release_channel_manifest(
    output: Path,
    *,
    tag: str,
    commit: str,
    archive_sha256: str,
    archive_size: int,
    update_class: str = PACKAGE_REQUIRED,
    dependencies_changed: bool = False,
    runtime_migration: str = "NONE",
    upgrade_impact: dict[str, Any] | None = None,
    release_sequence: int = 1,
    validation: dict[str, Any] | None = None,
    dependency_profiles: list[dict[str, Any]] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Write the immutable tag-specific input consumed by the host updater.

    A build with no reviewed impact classification is deliberately marked as
    requiring a TalentHub package update.  This is the safe initial-release
    behavior: an engine-only updater may never infer that prompts, skills,
    dependencies, or runtime state remained compatible.
    """
    if update_class not in ALLOWED_UPDATE_CLASSES:
        raise SystemExit(f"RELEASE_BLOCKED: unsupported update class {update_class!r}")
    if not SHA256_RE.fullmatch(archive_sha256):
        raise SystemExit("RELEASE_BLOCKED: invalid source archive SHA-256")
    if type(archive_size) is not int or archive_size <= 0:
        raise SystemExit("RELEASE_BLOCKED: invalid source archive byte size")
    if runtime_migration != "NONE" and update_class != "RUNTIME_MIGRATION_REQUIRED":
        raise SystemExit(
            "RELEASE_BLOCKED: a runtime migration must use RUNTIME_MIGRATION_REQUIRED"
        )
    if dependencies_changed and update_class == "ENGINE_ONLY":
        raise SystemExit(
            "RELEASE_BLOCKED: dependency changes cannot be classified ENGINE_ONLY"
        )
    if type(release_sequence) is not int or release_sequence <= 0:
        raise SystemExit("RELEASE_BLOCKED: invalid release sequence")
    validation_status = validation.get("status") if validation else "UNVALIDATED"
    validation_sha = validation.get("sha256") if validation else None
    profile_rows = list(dependency_profiles or [])
    replace_dependencies = update_class != "ENGINE_ONLY" or dependencies_changed
    if replace_dependencies and validation_status == "PASS":
        try:
            _dependency_bundle.validate_release_bindings(profile_rows, release_tag=tag)
        except _dependency_bundle.DependencyBundleBlocked as exc:
            raise SystemExit(
                f"RELEASE_BLOCKED: validated channel requires complete dependency bundles: {exc}"
            ) from exc
    if not replace_dependencies and profile_rows:
        raise SystemExit(
            "RELEASE_BLOCKED: ENGINE_ONLY channel must reuse the selected private venv"
        )
    payload: dict[str, Any] = {
        "schema": RELEASE_CHANNEL_SCHEMA,
        "immutable": True,
        "channel": RELEASE_CHANNEL_NAME,
        "release_sequence": release_sequence,
        "release_tag": tag,
        "source_ref": f"refs/tags/{tag}",
        "git_commit": commit,
        "source_archive_url": github_release_archive_url(tag),
        "source_archive_sha256": archive_sha256,
        "source_archive_size_bytes": archive_size,
        "runtime_schema": RUNTIME_SCHEMA,
        "compatible_runtime_schemas": [RUNTIME_SCHEMA],
        "runtime_migration": runtime_migration,
        "min_installer_version": MIN_INSTALLER_VERSION,
        "update_class": update_class,
        "dependencies_changed": dependencies_changed,
        "validation_receipt_status": validation_status,
        "validation_receipt_sha256": validation_sha,
        "release_signing_key_sha256": RELEASE_SIGNING_PUBLIC_KEY_SHA256,
        "talenthub_update_command": "talenthub agent update ai-drama-factory",
        "dependency_profiles": profile_rows,
        "dependency_profiles_action": (
            "REPLACE_WITH_RELEASE_BUNDLES" if replace_dependencies else "REUSE_CURRENT"
        ),
    }
    if upgrade_impact:
        payload["upgrade_impact"] = {
            "schema": upgrade_impact.get("schema"),
            "base_ref": (upgrade_impact.get("base") or {}).get("input"),
            "base_commit": (upgrade_impact.get("base") or {}).get("commit"),
            "target_ref": (upgrade_impact.get("target") or {}).get("input"),
            "target_commit": (upgrade_impact.get("target") or {}).get("commit"),
            "changed_path_count": len(upgrade_impact.get("changed_paths") or []),
            "reason_codes": [
                row.get("code") for row in (upgrade_impact.get("reasons") or [])
                if isinstance(row, dict) and row.get("code")
            ],
        }
    path = output / release_channel_filename(tag)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    metadata = {
        "path": str(path),
        "url": github_release_channel_url(tag),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
        "update_class": update_class,
    }
    return path, metadata


def write_signed_stable_index(
    output: Path,
    *,
    tag: str,
    commit: str,
    release_sequence: int,
    archive_sha256: str,
    archive_size: int,
    release_channel: dict[str, Any],
    update_class: str,
    validation: dict[str, Any],
    signing_key: Path,
    public_key: Path = RELEASE_SIGNING_PUBLIC_KEY,
    expected_public_key_sha256: str = RELEASE_SIGNING_PUBLIC_KEY_SHA256,
    openssl: str = "openssl",
) -> tuple[Path, Path, dict[str, Any]]:
    """Write and Ed25519-sign the mutable stable discovery pointer.

    The pointer is served only from the dedicated
    ``storyclaw-stable-channel`` release. Installed agents trust it only after
    verification with the public key pinned in the current engine/TalentHub
    package. Every referenced business-release artifact stays immutable and
    digest-bound.
    """
    if validation.get("status") != "PASS" or not SHA256_RE.fullmatch(
        str(validation.get("sha256") or "")
    ):
        raise SystemExit(
            "RELEASE_BLOCKED: signed stable index requires a validated StoryClaw receipt"
        )
    if type(release_sequence) is not int or release_sequence <= 0:
        raise SystemExit("RELEASE_BLOCKED: signed stable index needs a positive sequence")
    if update_class not in ALLOWED_UPDATE_CLASSES:
        raise SystemExit("RELEASE_BLOCKED: signed stable index update class is invalid")
    try:
        key_lstat = signing_key.expanduser().lstat()
        if signing_key.expanduser().is_symlink() or not stat.S_ISREG(key_lstat.st_mode):
            raise SystemExit("RELEASE_BLOCKED: release signing key must be a regular non-symlink file")
        if key_lstat.st_uid != os.geteuid():
            raise SystemExit("RELEASE_BLOCKED: release signing key must be owned by the publisher")
        if stat.S_IMODE(key_lstat.st_mode) & 0o077:
            raise SystemExit("RELEASE_BLOCKED: release signing key permissions must be 0600 or stricter")
        key_path = signing_key.expanduser().resolve(strict=True)
        public_key_path = public_key.expanduser().resolve(strict=True)
        public_bytes = public_key_path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"RELEASE_BLOCKED: release signing key unavailable: {exc}") from exc
    public_sha = hashlib.sha256(public_bytes).hexdigest()
    if public_sha != expected_public_key_sha256:
        raise SystemExit("RELEASE_BLOCKED: pinned release public-key digest mismatch")

    commit_epoch = int(git("show", "-s", "--format=%ct", commit))
    generated_at = datetime.fromtimestamp(commit_epoch, timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    payload = {
        "schema": STABLE_INDEX_SCHEMA,
        "channel": "stable",
        "release_sequence": release_sequence,
        "release_tag": tag,
        "git_commit": commit,
        "update_class": update_class,
        "release_channel_url": release_channel["url"],
        "release_channel_size_bytes": release_channel["size_bytes"],
        "release_channel_sha256": release_channel["sha256"],
        "source_archive_url": github_release_archive_url(tag),
        "source_archive_size_bytes": archive_size,
        "source_archive_sha256": archive_sha256,
        "validation_receipt_status": "PASS",
        "validation_receipt_sha256": validation["sha256"],
        "signing_key_sha256": expected_public_key_sha256,
        "generated_at": generated_at,
    }
    index_path = output / STABLE_INDEX_FILENAME
    signature_path = output / STABLE_SIGNATURE_FILENAME
    index_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    signed = subprocess.run(
        [
            openssl, "pkeyutl", "-sign", "-inkey", str(key_path), "-rawin",
            "-in", str(index_path), "-out", str(signature_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if signed.returncode != 0:
        raise SystemExit(
            "RELEASE_BLOCKED: stable index signing failed: "
            + (signed.stderr.strip() or str(signed.returncode))
        )
    verified = subprocess.run(
        [
            openssl, "pkeyutl", "-verify", "-pubin", "-inkey",
            str(public_key_path), "-rawin", "-in", str(index_path),
            "-sigfile", str(signature_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if verified.returncode != 0:
        raise SystemExit("RELEASE_BLOCKED: stable index signature self-check failed")
    metadata = {
        "path": str(index_path),
        "url": stable_index_latest_url(),
        "sha256": sha256(index_path),
        "size_bytes": index_path.stat().st_size,
        "signature_path": str(signature_path),
        "signature_url": stable_signature_latest_url(),
        "signature_sha256": sha256(signature_path),
        "signature_size_bytes": signature_path.stat().st_size,
        "signing_key_sha256": expected_public_key_sha256,
        "release_sequence": release_sequence,
    }
    return index_path, signature_path, metadata


def release_impact(
    previous_release_ref: str | None,
    *,
    target_ref: str,
    initial_release: bool,
) -> dict[str, Any]:
    """Classify a tag-to-tag upgrade, or fail closed for a first release."""
    if initial_release and previous_release_ref:
        raise SystemExit(
            "RELEASE_BLOCKED: --initial-release cannot be combined with --previous-release-ref"
        )
    if previous_release_ref:
        try:
            return classify_release(previous_release_ref, target_ref, root=ROOT)
        except ClassificationBlocked as exc:
            raise SystemExit(
                f"RELEASE_BLOCKED: upgrade impact classification failed: {exc.code}:{exc.detail}"
            ) from exc
    return {
        "schema": "storyclaw.nalu.upgrade_impact.v1",
        "status": "PASS",
        "base": None,
        "target": {"input": target_ref, "kind": "tag"},
        "update_class": PACKAGE_REQUIRED,
        "dependencies_changed": False,
        "runtime_schema_changed": False,
        "runtime_migration": "NONE",
        "talenthub_republish_required": True,
        "engine_only_eligible": False,
        "changed_paths": [],
        "reasons": [{
            "code": "INITIAL_OR_UNCLASSIFIED_RELEASE",
            "summary": (
                "No previous immutable release was supplied; fail closed to a full "
                "TalentHub package update."
            ),
            "paths": [],
        }],
    }


def validate_storyclaw_release_receipt(path: Path, commit: str) -> dict[str, Any]:
    """Recompute private acceptance evidence and return a hash-only summary.

    The receipt's nested PASS strings are never accepted as authority.  The
    dedicated validator re-opens every private evidence artifact, rejects path
    escape/symlinks, recalculates hashes, and re-evaluates the release gates.
    """
    try:
        return _release_validation.verify_receipt(path, commit)
    except _release_validation.ValidationBlocked as exc:
        raise SystemExit(
            f"RELEASE_BLOCKED: StoryClaw validation evidence failed: {exc}"
        ) from exc


def talenthub_cli_version() -> str | None:
    try:
        result = subprocess.run(
            ["talenthub", "--version"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    value = (result.stdout or result.stderr).strip().splitlines()
    return value[-1].strip() if value else None


def talenthub_canary_agent_id(tag: str) -> str:
    """Return a stable private staging ID without exposing release text."""
    digest = hashlib.sha256(tag.encode("utf-8")).hexdigest()[:16]
    return f"{AGENT_ID}-release-{digest}"


def talenthub_canary_publish_command(workspace: Path, tag: str) -> list[str]:
    return [
        "talenthub", "agent", "publish", "--private",
        "--id", talenthub_canary_agent_id(tag), "--dir", str(workspace),
    ]


def talenthub_formal_publish_command(workspace: Path) -> list[str]:
    return ["talenthub", "agent", "publish", "--dir", str(workspace)]


def _talenthub_registry_module() -> tuple[str, Path]:
    talenthub = shutil.which("talenthub")
    node = shutil.which("node")
    if talenthub is None or node is None:
        raise SystemExit("RELEASE_BLOCKED: TalentHub registry readback needs talenthub and node")
    module = Path(talenthub).resolve().parent / "lib" / "registry.js"
    if not module.is_file():
        raise SystemExit("RELEASE_BLOCKED: installed TalentHub CLI has no registry module")
    return node, module


def _canonical_talenthub_package_url(value: object) -> str:
    url = str(value or "").strip()
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not hostname
        or (hostname != "storyclaw.com" and not hostname.endswith(".storyclaw.com"))
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise SystemExit("RELEASE_BLOCKED: TalentHub returned a non-canonical package URL")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def read_authenticated_talenthub_manifest(
    agent_id: str, *, runner: Any = subprocess.run
) -> dict[str, str] | None:
    """Read one private or public registry row via the CLI's authenticated API."""
    node, module = _talenthub_registry_module()
    script = (
        "import {pathToFileURL} from 'node:url';"
        "const m=await import(pathToFileURL(process.argv[1]).href);"
        "try{const v=await m.fetchManifest(process.argv[2]);"
        "console.log(JSON.stringify(v));}catch(e){"
        "const s=String(e?.message||e);"
        "if(s.includes('(404)')){console.log(JSON.stringify({status:'NOT_FOUND'}));}"
        "else{console.error('REGISTRY_READ_FAILED');process.exit(2);}}"
    )
    result = runner(
        [node, "--input-type=module", "-e", script, str(module), agent_id],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise SystemExit("RELEASE_BLOCKED: authenticated TalentHub registry readback failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit("RELEASE_BLOCKED: TalentHub registry readback returned invalid JSON") from exc
    if payload == {"status": "NOT_FOUND"}:
        return None
    if not isinstance(payload, dict) or payload.get("id") != agent_id:
        raise SystemExit("RELEASE_BLOCKED: TalentHub registry identity mismatch")
    version = str(payload.get("version") or "")
    zip_url = _canonical_talenthub_package_url(payload.get("zip_url"))
    if not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}-[1-9]\d*", version):
        raise SystemExit("RELEASE_BLOCKED: TalentHub registry version is invalid")
    return {"agent_id": agent_id, "version": version, "package_url": zip_url}


def read_public_talenthub_manifest(
    agent_id: str, *, fetcher: Any | None = None
) -> dict[str, str] | None:
    """Read the unauthenticated public registry row after formal publication."""
    base = (os.environ.get("TALENTHUB_URL") or os.environ.get("TALENTHUB_REGISTRY")
            or "https://app.storyclaw.com").rstrip("/")
    parsed = urlsplit(base)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or (
        host != "storyclaw.com" and not host.endswith(".storyclaw.com")
    ):
        raise SystemExit("RELEASE_BLOCKED: TalentHub registry base URL is invalid")
    url = f"{base}/api/talenthub/registry/{quote(agent_id)}"
    try:
        if fetcher is None:
            request = urllib.request.Request(
                url, headers={"Accept": "application/json", "User-Agent": "qingshan-release-builder/1"}
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read(2 * 1024 * 1024 + 1)
        else:
            body = fetcher(url, 2 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise SystemExit("RELEASE_BLOCKED: public TalentHub registry readback failed") from exc
    except OSError as exc:
        raise SystemExit("RELEASE_BLOCKED: public TalentHub registry readback failed") from exc
    if len(body) > 2 * 1024 * 1024:
        raise SystemExit("RELEASE_BLOCKED: TalentHub public manifest is oversized")
    try:
        payload = json.loads(body)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit("RELEASE_BLOCKED: TalentHub public manifest is invalid") from exc
    if not isinstance(payload, dict) or payload.get("id") != agent_id:
        raise SystemExit("RELEASE_BLOCKED: TalentHub public registry identity mismatch")
    version = str(payload.get("version") or "")
    if not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}-[1-9]\d*", version):
        raise SystemExit("RELEASE_BLOCKED: TalentHub public registry version is invalid")
    return {
        "agent_id": agent_id,
        "version": version,
        "package_url": _canonical_talenthub_package_url(payload.get("zip_url")),
    }


def _talenthub_version_key(version: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(r"(\d{4})\.(\d{2})\.(\d{2})-([1-9]\d*)", version)
    if match is None:
        raise SystemExit("RELEASE_BLOCKED: TalentHub registry version is invalid")
    key = tuple(int(value) for value in match.groups())
    if not 1 <= key[1] <= 12 or not 1 <= key[2] <= 31:
        raise SystemExit("RELEASE_BLOCKED: TalentHub registry version is invalid")
    return key


def require_talenthub_version_advance(previous: str | None, current: str) -> None:
    current_key = _talenthub_version_key(current)
    if previous is not None and current_key <= _talenthub_version_key(previous):
        raise SystemExit("RELEASE_BLOCKED: TalentHub server version did not advance")


def recover_formal_registry_publication(
    workspace: Path,
    canary: Mapping[str, Any],
    official: Mapping[str, str] | None,
    *,
    verifier: Any | None = None,
) -> tuple[dict[str, str], dict[str, Any]] | None:
    """Adopt an exact formal package left by a crash before receipt persistence.

    A missing formal receipt is not proof that publication did not happen.  The
    registry is authoritative: the former public row means publication is still
    pending, while a newer row may be adopted only when its ZIP is byte-for-byte
    the already smoke-tested canary/local workspace package.
    """
    if verifier is None:
        verifier = verify_talenthub_registry_package_url
    expected_previous = (
        {
            "agent_id": AGENT_ID,
            "version": canary["official_previous_version"],
            "package_url": canary["official_previous_package_url"],
        }
        if canary.get("official_previous_version") is not None else None
    )
    if official == expected_previous:
        return None
    if official is None:
        raise SystemExit(
            "RELEASE_BLOCKED: formal TalentHub entry disappeared after canary publication"
        )
    require_talenthub_version_advance(
        canary.get("official_previous_version"), official["version"]
    )
    package = verifier(workspace, official["package_url"])
    if (
        package["size_bytes"] != canary["canary_package_size_bytes"]
        or package["sha256"] != canary["canary_package_sha256"]
    ):
        raise SystemExit(
            "RELEASE_BLOCKED: formal registry changed to a package other than the smoke-tested canary"
        )
    return dict(official), package


def parse_talenthub_publish_version(stdout: str, stderr: str = "") -> str | None:
    """Extract the registry version from JSON or human-readable CLI output."""
    text = "\n".join(part for part in (stdout, stderr) if part)
    version_keys = {
        "version",
        "agentversion",
        "agent_version",
        "publishedversion",
        "published_version",
    }

    def visit(value: Any) -> str | None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if key.lower() in version_keys and isinstance(nested, (str, int, float)):
                    return str(nested)
            for nested in value.values():
                found = visit(nested)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = visit(nested)
                if found is not None:
                    return found
        return None

    for line in text.splitlines():
        candidate = line.strip()
        if not candidate.startswith(("{", "[")):
            continue
        try:
            found = visit(json.loads(candidate))
        except json.JSONDecodeError:
            continue
        if found is not None:
            return found
    patterns = (
        r"(?i)\b(?:published[_ ]?version|agent[_ ]?version|version)\s*[:=#]?\s*([A-Za-z0-9][A-Za-z0-9._+-]*)",
        r"(?i)\bpublished\s+[^\n]*?@([A-Za-z0-9][A-Za-z0-9._+-]*)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def parse_talenthub_package_url(stdout: str, stderr: str = "") -> str:
    """Return the public package URL emitted by TalentHub CLI 0.4.11+."""
    text = "\n".join(part for part in (stdout, stderr) if part)
    match = re.search(r"(?im)^\s*Package:\s*(https://\S+)\s*$", text)
    if not match:
        raise SystemExit("RELEASE_BLOCKED: TalentHub publish did not return a package URL")
    return _canonical_talenthub_package_url(match.group(1))


def _download_talenthub_package(url: str, limit: int = 50 * 1024 * 1024) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/zip", "User-Agent": "qingshan-release-builder/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read(limit + 1)
    except OSError as exc:
        raise SystemExit(f"RELEASE_BLOCKED: cannot read back TalentHub package: {exc}") from exc
    if len(payload) > limit:
        raise SystemExit("RELEASE_BLOCKED: TalentHub package exceeds 50 MiB")
    return payload


def _build_expected_talenthub_zip(
    workspace: Path,
    destination: Path,
    *,
    runner: Any = subprocess.run,
) -> None:
    talenthub = shutil.which("talenthub")
    node = shutil.which("node")
    if talenthub is None or node is None:
        raise SystemExit("RELEASE_BLOCKED: TalentHub package verifier needs talenthub and node")
    cli = Path(talenthub).resolve()
    agent_zip = cli.parent / "lib" / "agent-zip.js"
    if not agent_zip.is_file():
        raise SystemExit("RELEASE_BLOCKED: installed TalentHub CLI has no agent-zip module")
    script = (
        "import fs from 'node:fs';"
        "import {pathToFileURL} from 'node:url';"
        "const m=await import(pathToFileURL(process.argv[1]).href);"
        "const c=m.readAgentDir(process.argv[2]);"
        "const r=await m.buildAgentZip(c);"
        "fs.writeFileSync(process.argv[3],r.buffer);"
    )
    built = runner(
        [node, "--input-type=module", "-e", script, str(agent_zip),
         str(workspace.resolve(strict=True)), str(destination)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if built.returncode != 0 or not destination.is_file():
        raise SystemExit(
            "RELEASE_BLOCKED: cannot reproduce TalentHub package locally: "
            + ((built.stderr or built.stdout or "").strip() or str(built.returncode))
        )


def verify_talenthub_registry_package(
    workspace: Path,
    publish_stdout: str,
    publish_stderr: str = "",
    *,
    fetcher: Any = _download_talenthub_package,
    expected_builder: Any = _build_expected_talenthub_zip,
) -> dict[str, Any]:
    """Compare the registry package to the deterministic CLI package bytes."""
    package_url = parse_talenthub_package_url(publish_stdout, publish_stderr)
    return verify_talenthub_registry_package_url(
        workspace, package_url, fetcher=fetcher, expected_builder=expected_builder
    )


def verify_talenthub_registry_package_url(
    workspace: Path,
    package_url: str,
    *,
    fetcher: Any = _download_talenthub_package,
    expected_builder: Any = _build_expected_talenthub_zip,
) -> dict[str, Any]:
    """Compare one exact registry URL to the deterministic local CLI ZIP."""
    package_url = _canonical_talenthub_package_url(package_url)
    with tempfile.TemporaryDirectory(prefix="storyclaw-talenthub-package-") as temporary:
        expected_path = Path(temporary) / "expected.zip"
        expected_builder(workspace, expected_path)
        expected = expected_path.read_bytes()
        actual = fetcher(package_url, 50 * 1024 * 1024)
    expected_sha = hashlib.sha256(expected).hexdigest()
    actual_sha = hashlib.sha256(actual).hexdigest()
    if len(actual) != len(expected) or actual_sha != expected_sha:
        raise SystemExit(
            "RELEASE_BLOCKED: published TalentHub package differs from the local CLI package"
        )
    return {
        "status": "PASS",
        "package_url": package_url,
        "size_bytes": len(actual),
        "sha256": actual_sha,
    }


def recover_unreceipted_registry_canary(
    workspace: Path,
    remote_canary: Mapping[str, str] | None,
    official_before: Mapping[str, str] | None,
    *,
    public_reader: Any = read_public_talenthub_manifest,
    verifier: Any = verify_talenthub_registry_package_url,
) -> tuple[dict[str, str], dict[str, Any]] | None:
    """Adopt a deterministic canary left by a crash before receipt persistence."""
    if remote_canary is None:
        return None
    package = verifier(workspace, remote_canary["package_url"])
    require_talenthub_version_advance(None, remote_canary["version"])
    if public_reader(AGENT_ID) != official_before:
        raise SystemExit(
            "RELEASE_BLOCKED: formal TalentHub entry changed while recovering canary"
        )
    return dict(remote_canary), package


def canary_cleanup_report(
    result: subprocess.CompletedProcess[str],
    registry_entry: Mapping[str, str] | None,
) -> dict[str, Any]:
    """Interpret interactive CLI cleanup without treating Cancelled as success."""
    output = (result.stdout + "\n" + result.stderr).strip()
    reported_success = (
        result.returncode == 0
        and any(line.lstrip().startswith("✓") for line in output.splitlines())
        and "Cancelled." not in output
    )
    return {
        "status": "PASS" if reported_success and registry_entry is None else "DEFERRED",
        "exit_code": result.returncode,
        "command_reported_success": reported_success,
        "registry_entry_absent": registry_entry is None,
    }


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_registry_canary_receipt(
    output: Path,
    *,
    tag: str,
    commit: str,
    release_sequence: int,
    stable_index_path: Path,
    workspace: Path,
    canary_agent_id: str,
    canary_version: str,
    canary_package: Mapping[str, Any],
    official_before: Mapping[str, str] | None,
) -> tuple[Path, dict[str, Any]]:
    payload = {
        "schema": REGISTRY_CANARY_RECEIPT_SCHEMA,
        "status": "PENDING_REGISTRY_CLEAN_INSTALL_SMOKE",
        "release_tag": tag,
        "git_commit": commit,
        "release_sequence": release_sequence,
        "stable_index_sha256": sha256(stable_index_path),
        "installed_release_manifest_sha256": sha256(
            workspace / "skills" / SKILL_NAME / "RELEASE_MANIFEST.json"
        ),
        "canary_agent_id": canary_agent_id,
        "canary_registry_version": canary_version,
        "canary_package_url": canary_package["package_url"],
        "canary_package_size_bytes": canary_package["size_bytes"],
        "canary_package_sha256": canary_package["sha256"],
        "official_previous_version": (
            official_before["version"] if official_before else None
        ),
        "official_previous_package_url": (
            official_before["package_url"] if official_before else None
        ),
    }
    path = output / REGISTRY_CANARY_RECEIPT_FILENAME
    _write_json_atomic(path, payload)
    return path, {**payload, "path": str(path), "sha256": sha256(path)}


def load_registry_canary_receipt(
    path: Path,
    *,
    tag: str,
    commit: str,
    release_sequence: int,
    stable_index_path: Path,
    workspace: Path,
) -> dict[str, Any]:
    try:
        resolved = path.expanduser().resolve(strict=True)
        raw = resolved.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("RELEASE_BLOCKED: registry canary receipt is invalid") from exc
    exact = {
        "schema": REGISTRY_CANARY_RECEIPT_SCHEMA,
        "status": "PENDING_REGISTRY_CLEAN_INSTALL_SMOKE",
        "release_tag": tag,
        "git_commit": commit,
        "release_sequence": release_sequence,
        "stable_index_sha256": sha256(stable_index_path),
        "installed_release_manifest_sha256": sha256(
            workspace / "skills" / SKILL_NAME / "RELEASE_MANIFEST.json"
        ),
        "canary_agent_id": talenthub_canary_agent_id(tag),
    }
    if not isinstance(payload, dict) or any(
        payload.get(key) != value for key, value in exact.items()
    ):
        raise SystemExit("RELEASE_BLOCKED: registry canary receipt binding mismatch")
    for key in ("canary_package_sha256",):
        if not SHA256_RE.fullmatch(str(payload.get(key) or "")):
            raise SystemExit("RELEASE_BLOCKED: registry canary receipt digest invalid")
    if type(payload.get("canary_package_size_bytes")) is not int or payload[
        "canary_package_size_bytes"
    ] <= 0:
        raise SystemExit("RELEASE_BLOCKED: registry canary receipt size invalid")
    _canonical_talenthub_package_url(payload.get("canary_package_url"))
    _talenthub_version_key(str(payload.get("canary_registry_version") or ""))
    previous = payload.get("official_previous_version")
    if previous is not None:
        _talenthub_version_key(str(previous))
        _canonical_talenthub_package_url(payload.get("official_previous_package_url"))
    elif payload.get("official_previous_package_url") is not None:
        raise SystemExit("RELEASE_BLOCKED: registry canary receipt prior state invalid")
    return {**payload, "path": str(resolved), "sha256": hashlib.sha256(raw).hexdigest()}


def write_registry_formal_receipt(
    output: Path,
    *,
    tag: str,
    commit: str,
    release_sequence: int,
    canary: Mapping[str, Any],
    official: Mapping[str, str],
    package: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    payload = {
        "schema": REGISTRY_FORMAL_RECEIPT_SCHEMA,
        "status": "PUBLIC_REGISTRY_READBACK_PASS",
        "release_tag": tag,
        "git_commit": commit,
        "release_sequence": release_sequence,
        "canary_receipt_sha256": canary["sha256"],
        "official_previous_version": canary.get("official_previous_version"),
        "official_published_version": official["version"],
        "official_package_url": official["package_url"],
        "official_package_size_bytes": package["size_bytes"],
        "official_package_sha256": package["sha256"],
    }
    path = output / REGISTRY_FORMAL_RECEIPT_FILENAME
    _write_json_atomic(path, payload)
    return path, {**payload, "path": str(path), "sha256": sha256(path)}


def load_registry_formal_receipt(
    path: Path,
    *,
    tag: str,
    commit: str,
    release_sequence: int,
    canary: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        resolved = path.expanduser().resolve(strict=True)
        raw = resolved.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("RELEASE_BLOCKED: formal registry receipt is invalid") from exc
    exact = {
        "schema": REGISTRY_FORMAL_RECEIPT_SCHEMA,
        "status": "PUBLIC_REGISTRY_READBACK_PASS",
        "release_tag": tag,
        "git_commit": commit,
        "release_sequence": release_sequence,
        "canary_receipt_sha256": canary["sha256"],
        "official_previous_version": canary.get("official_previous_version"),
        "official_package_size_bytes": canary["canary_package_size_bytes"],
        "official_package_sha256": canary["canary_package_sha256"],
    }
    if not isinstance(payload, dict) or any(
        payload.get(key) != value for key, value in exact.items()
    ):
        raise SystemExit("RELEASE_BLOCKED: formal registry receipt binding mismatch")
    _talenthub_version_key(str(payload.get("official_published_version") or ""))
    require_talenthub_version_advance(
        payload.get("official_previous_version"),
        str(payload["official_published_version"]),
    )
    _canonical_talenthub_package_url(payload.get("official_package_url"))
    return {**payload, "path": str(resolved), "sha256": hashlib.sha256(raw).hexdigest()}


def validate_registry_clean_smoke(
    receipt_path: Path,
    *,
    tag: str,
    commit: str,
    release_sequence: int,
    stable_index_path: Path,
    archive: Path,
    workspace: Path,
    canary: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute the private clean install and bind it to this canary build."""
    try:
        summary = _registry_clean_smoke.verify_receipt(receipt_path)
        private = json.loads(receipt_path.expanduser().resolve(strict=True).read_text())
    except (_registry_clean_smoke.SmokeBlocked, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"RELEASE_BLOCKED: registry clean-install smoke failed: {exc}") from exc
    facts = private.get("facts") if isinstance(private, dict) else None
    if not isinstance(facts, dict):
        raise SystemExit("RELEASE_BLOCKED: registry clean-install smoke facts missing")
    expected = {
        "release": {"tag": tag, "commit": commit, "sequence": release_sequence},
        "stable_index_sha256": sha256(stable_index_path),
        "source_archive_sha256": sha256(archive),
        "nested_manifest_sha256": sha256(
            workspace / "skills" / SKILL_NAME / "RELEASE_MANIFEST.json"
        ),
        "registry_package_url": canary["canary_package_url"],
        "registry_package_size_bytes": canary["canary_package_size_bytes"],
        "registry_package_sha256": canary["canary_package_sha256"],
    }
    mismatches: list[str] = []
    if facts.get("release") != expected["release"]:
        mismatches.append("release")
    for name, branch, field in (
        ("stable_index_sha256", "stable_index", "sha256"),
        ("source_archive_sha256", "source_archive", "sha256"),
        ("nested_manifest_sha256", "nested_manifest", "sha256"),
        ("registry_package_url", "registry_package", "url"),
        ("registry_package_size_bytes", "registry_package", "size_bytes"),
        ("registry_package_sha256", "registry_package", "sha256"),
    ):
        row = facts.get(branch)
        if not isinstance(row, dict) or row.get(field) != expected[name]:
            mismatches.append(name)
    if mismatches:
        raise SystemExit(
            "RELEASE_BLOCKED: registry clean-install smoke binding mismatch: "
            + ",".join(mismatches)
        )
    return summary


def write_signed_talenthub_package_attestation(
    output: Path,
    *,
    tag: str,
    commit: str,
    stable_index_path: Path,
    workspace: Path,
    registry_package: Mapping[str, Any],
    canary_receipt: Mapping[str, Any],
    formal_receipt: Mapping[str, Any],
    clean_smoke: Mapping[str, Any],
    signing_key: Path,
    openssl: str = "openssl",
) -> tuple[Path, Path, dict[str, Any]]:
    """Sign public proof that the required Agent package exists byte-for-byte."""
    manifest_path = workspace / "skills" / SKILL_NAME / "RELEASE_MANIFEST.json"
    payload = {
        "schema": TALENTHUB_ATTESTATION_SCHEMA,
        "agent_id": AGENT_ID,
        "skill": SKILL_NAME,
        "release_tag": tag,
        "git_commit": commit,
        "stable_index_sha256": sha256(stable_index_path),
        "package_url": registry_package["package_url"],
        "package_size_bytes": registry_package["size_bytes"],
        "package_sha256": registry_package["sha256"],
        "readiness": "READY_AFTER_REGISTRY_CLEAN_INSTALL_SMOKE",
        "registry_clean_install_smoke_schema": _registry_clean_smoke.SCHEMA,
        "registry_clean_install_smoke_hashes": clean_smoke["hashes"],
        "registry_clean_install_smoke_receipt_sha256": clean_smoke["hashes"][
            "receipt_sha256"
        ],
        "canary_agent_id": canary_receipt["canary_agent_id"],
        "canary_receipt_sha256": canary_receipt["sha256"],
        "canary_package_url_sha256": hashlib.sha256(
            str(canary_receipt["canary_package_url"]).encode("utf-8")
        ).hexdigest(),
        "canary_package_size_bytes": canary_receipt["canary_package_size_bytes"],
        "canary_package_sha256": canary_receipt["canary_package_sha256"],
        "formal_publish_receipt_sha256": formal_receipt["sha256"],
        "previous_registry_version": formal_receipt["official_previous_version"],
        "published_registry_version": formal_receipt["official_published_version"],
        "official_registry_readback": "PUBLIC_UNAUTHENTICATED",
        "installed_release_manifest_path": f"skills/{SKILL_NAME}/RELEASE_MANIFEST.json",
        "installed_release_manifest_sha256": sha256(manifest_path),
        "signing_key_sha256": RELEASE_SIGNING_PUBLIC_KEY_SHA256,
    }
    path = output / TALENTHUB_ATTESTATION_FILENAME
    signature = output / TALENTHUB_ATTESTATION_SIGNATURE_FILENAME
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    key = signing_key.expanduser().resolve(strict=True)
    signed = subprocess.run(
        [
            openssl, "pkeyutl", "-sign", "-inkey", str(key), "-rawin",
            "-in", str(path), "-out", str(signature),
        ],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    if signed.returncode != 0:
        raise SystemExit("RELEASE_BLOCKED: TalentHub package attestation signing failed")
    verified = subprocess.run(
        [
            openssl, "pkeyutl", "-verify", "-pubin", "-inkey",
            str(RELEASE_SIGNING_PUBLIC_KEY), "-rawin", "-in", str(path),
            "-sigfile", str(signature),
        ],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    if verified.returncode != 0:
        raise SystemExit("RELEASE_BLOCKED: TalentHub package attestation self-check failed")
    return path, signature, {
        **payload,
        "path": str(path),
        "sha256": sha256(path),
        "signature_path": str(signature),
        "signature_sha256": sha256(signature),
    }


def upload_immutable_release_assets(
    tag: str,
    paths: tuple[Path, ...],
    *,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    repository = "rogerwu188/qingshan-short-drama-production-line"
    names = [path.name for path in paths]
    if len(set(names)) != len(names):
        raise SystemExit("RELEASE_BLOCKED: duplicate immutable release asset name")
    viewed = runner(
        ["gh", "release", "view", tag, "--repo", repository, "--json", "assets"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    if viewed.returncode != 0:
        raise SystemExit("RELEASE_BLOCKED: immutable release lookup failed")
    try:
        metadata = json.loads(viewed.stdout)
        existing_names = {
            str(row.get("name") or "")
            for row in metadata.get("assets", [])
            if isinstance(row, dict)
        }
    except (AttributeError, json.JSONDecodeError) as exc:
        raise SystemExit("RELEASE_BLOCKED: immutable release lookup was invalid") from exc
    present = existing_names.intersection(names)
    if present:
        if present != set(names):
            raise SystemExit("RELEASE_BLOCKED: immutable attestation asset set is partial")
        # verify_published_github_assets performs an exact byte readback.  A
        # retry may reuse only a complete, byte-identical pair.
        return verify_published_github_assets(tag, paths, runner=runner)
    uploaded = runner(
        ["gh", "release", "upload", tag, *map(str, paths), "--repo", repository],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    if uploaded.returncode != 0:
        raise SystemExit("RELEASE_BLOCKED: immutable release attestation upload failed")
    return verify_published_github_assets(tag, paths, runner=runner)


def run_release_checks() -> None:
    python = os.environ.get("NALU_VENV_PYTHON")
    if python:
        check_python = Path(python).expanduser()
    else:
        candidate = ROOT / ".qingshan-venv" / "bin" / "python"
        check_python = candidate if candidate.exists() else Path(sys.executable)
    explicit_regressions = [
        "tools.tests.test_nalu_paid_authority",
        "tools.tests.test_nalu_scoped_qa_paths",
        "tools.tests.test_nalu_current_policy_profile",
        "tools.tests.test_storyclaw_asset_plan_gate",
        "tools.tests.test_storyclaw_project_intake",
        "tools.tests.test_nalu_media_tools",
        "tools.tests.test_provider_scope_projection",
    ]
    commands = [
        [str(check_python), "tools/deployment_code_integrity.py"],
        [str(check_python), "tools/knowledge_registry.py", "--validate"],
        [str(check_python), "tools/run_portable_ci.py"],
        [str(check_python), "-m", "unittest", "tools.tests.test_build_storyclaw_talenthub_release"],
        [str(check_python), "-m", "unittest", "tools.tests.test_storyclaw_nalu_runtime"],
        [str(check_python), "-m", "unittest", "tools.tests.test_storyclaw_release_validation"],
        [str(check_python), "-m", "unittest", *explicit_regressions],
    ]
    for command in commands:
        print("RELEASE_CHECK", " ".join(command))
        run(command)


def audit_source_archive(archive: Path) -> dict[str, object]:
    """Fail closed if private runtime material entered the public archive.

    The two tracked supervisor-order files are deliberately empty bootstrap
    templates.  Any other file with that name, or a non-empty copy of either
    template, is live authority data and cannot be released.
    """
    checked_files = 0
    release_manifests = 0
    with tarfile.open(archive, mode="r:gz") as tar:
        for member in tar.getmembers():
            name = member.name
            if name == ARCHIVE_PREFIX.rstrip("/") and member.isdir():
                continue
            if not name.startswith(ARCHIVE_PREFIX):
                raise SystemExit(f"RELEASE_BLOCKED: archive member escapes release prefix: {name}")
            relative = name[len(ARCHIVE_PREFIX):]
            parts = Path(relative).parts
            if member.issym() or member.islnk():
                raise SystemExit(f"RELEASE_BLOCKED: archive link is not allowed: {relative}")
            if relative.startswith(FORBIDDEN_ARCHIVE_PREFIXES):
                raise SystemExit(f"RELEASE_BLOCKED: private runtime path entered archive: {relative}")
            if any(part in {".env", "credentials.json", "secrets.json"} for part in parts):
                raise SystemExit(f"RELEASE_BLOCKED: credential filename entered archive: {relative}")
            if not member.isfile():
                continue
            checked_files += 1
            if relative == "RELEASE_MANIFEST.json":
                release_manifests += 1
            if Path(relative).name != "SUPERVISOR_ORDERS.json":
                continue
            if relative not in EMPTY_ORDER_TEMPLATES:
                raise SystemExit(f"RELEASE_BLOCKED: live supervisor orders entered archive: {relative}")
            stream = tar.extractfile(member)
            try:
                payload = json.loads((stream.read() if stream else b"").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SystemExit(f"RELEASE_BLOCKED: invalid empty order template: {relative}") from exc
            if int(payload.get("latest_order_seq") or 0) != 0 or payload.get("orders") != []:
                raise SystemExit(f"RELEASE_BLOCKED: non-empty supervisor order template: {relative}")
    if release_manifests != 1:
        raise SystemExit(
            f"RELEASE_BLOCKED: archive must contain exactly one RELEASE_MANIFEST.json; found {release_manifests}"
        )
    return {"status": "PASS", "checked_files": checked_files, "private_runtime_included": False}


def audit_portable_archive_inventory(archive: Path) -> dict[str, object]:
    """Prove every portable-manifest file is physically present in the tarball."""
    manifest_name = ARCHIVE_PREFIX + "configs/PORTABLE_CORE_MANIFEST.json"
    with tarfile.open(archive, mode="r:gz") as tar:
        members = tar.getmembers()
        names = [member.name for member in members]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise SystemExit(
                "RELEASE_BLOCKED: duplicate source archive members: " + ", ".join(duplicates)
            )
        try:
            member = tar.getmember(manifest_name)
        except KeyError as exc:
            raise SystemExit("RELEASE_BLOCKED: source archive has no portable manifest") from exc
        stream = tar.extractfile(member)
        try:
            payload = json.loads((stream.read() if stream else b"").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SystemExit("RELEASE_BLOCKED: invalid portable manifest in source archive") from exc
    if not isinstance(payload, dict) or payload.get("schema") != "qingshan.portable_core_manifest.v1":
        raise SystemExit("RELEASE_BLOCKED: unexpected portable manifest schema in source archive")
    required_files = _unique_string_list(payload, "required_files")
    missing = sorted(
        relative for relative in required_files if ARCHIVE_PREFIX + relative not in names
    )
    if missing:
        raise SystemExit(
            "RELEASE_BLOCKED: portable files missing from source archive: " + ", ".join(missing)
        )
    return {
        "status": "PASS",
        "required_file_count": len(required_files),
        "archive_member_count": len(names),
    }


def audit_talenthub_workspace(workspace: Path) -> dict[str, object]:
    """Validate TalentHub's documented prompt limits and public-only layout."""
    expected = {
        "manifest.json",
        "IDENTITY.md",
        "USER.md",
        "SOUL.md",
        "AGENTS.md",
        "HEARTBEAT.md",
        f"skills/{SKILL_NAME}/SKILL.md",
        f"skills/{SKILL_NAME}/bootstrap_storyclaw.py",
        f"skills/{SKILL_NAME}/RELEASE_MANIFEST.json",
    }
    actual: set[str] = set()
    prompt_bytes = 0
    prompt_count = 0
    for path in workspace.rglob("*"):
        relative = path.relative_to(workspace).as_posix()
        if path.is_symlink():
            raise SystemExit(f"RELEASE_BLOCKED: TalentHub workspace link is not allowed: {relative}")
        if not path.is_file():
            continue
        actual.add(relative)
        if path.suffix == ".md":
            size = path.stat().st_size
            if size > TALENTHUB_FILE_LIMIT:
                raise SystemExit(
                    f"RELEASE_BLOCKED: TalentHub prompt exceeds 200 KB: {relative} ({size} bytes)"
                )
            prompt_bytes += size
            prompt_count += 1
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise SystemExit(
            "RELEASE_BLOCKED: unexpected TalentHub workspace layout: "
            f"missing={missing}, extra={extra}"
        )
    if prompt_bytes > TALENTHUB_PROMPT_TOTAL_LIMIT:
        raise SystemExit(
            f"RELEASE_BLOCKED: TalentHub prompt content exceeds 1 MB ({prompt_bytes} bytes)"
        )
    try:
        manifest = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("RELEASE_BLOCKED: invalid TalentHub manifest.json") from exc
    if manifest.get("id") != AGENT_ID or manifest.get("skills") != [f"{GITHUB_REPO}@{SKILL_NAME}"]:
        raise SystemExit("RELEASE_BLOCKED: TalentHub manifest is not bound to the canonical agent and skill")
    return {
        "status": "PASS",
        "file_count": len(actual),
        "prompt_file_count": prompt_count,
        "prompt_bytes": prompt_bytes,
    }


def _tar_json(source_tar: tarfile.TarFile, relative: str) -> dict[str, Any]:
    member_name = ARCHIVE_PREFIX + relative
    try:
        member = source_tar.getmember(member_name)
    except KeyError as exc:
        raise SystemExit(f"RELEASE_BLOCKED: source tree has no {relative}") from exc
    stream = source_tar.extractfile(member)
    try:
        payload = json.loads((stream.read() if stream else b"").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"RELEASE_BLOCKED: source tree has invalid JSON: {relative}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"RELEASE_BLOCKED: source tree JSON is not an object: {relative}")
    return payload


def _json_repository_paths(value: Any, existing: set[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for nested in value.values():
            found.update(_json_repository_paths(nested, existing))
    elif isinstance(value, list):
        for nested in value:
            found.update(_json_repository_paths(nested, existing))
    elif isinstance(value, str):
        candidate = value.split("#", 1)[0]
        if candidate in existing:
            found.add(candidate)
    return found


def _portable_test_path(module_name: str) -> str:
    return module_name.replace(".", "/") + ".py"


def _generic_line_tool(relative: str) -> bool:
    prefix = "lines/nalu/runtime/tools/"
    if not relative.startswith(prefix):
        return False
    nested = relative[len(prefix):]
    if nested == "ingest_yewujiang_source.py":
        return False
    if nested == "review_fill/nalu_e03_s6_loop.sh":
        return False
    if re.fullmatch(r"review_fill/e\d+_fill_[A-Za-z0-9_]+\.py", nested):
        return False
    return relative.endswith((".py", ".sh", ".md"))


def _python_repository_imports(
    text_value: str,
    existing: set[str],
) -> set[str]:
    """Return repository files imported through the public ``tools`` package."""
    try:
        tree = ast.parse(text_value)
    except SyntaxError:
        return set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
                if node.module == "tools":
                    modules.update(f"tools.{alias.name}" for alias in node.names)
    found: set[str] = set()
    for module in modules:
        if module != "tools" and not module.startswith("tools."):
            continue
        base = module.replace(".", "/")
        for candidate in (base + ".py", base + "/__init__.py"):
            if candidate in existing:
                found.add(candidate)
    return found


def _project_replay_path(relative: str) -> bool:
    if relative in FORBIDDEN_PORTABLE_MANIFEST_FILES:
        return True
    if relative.startswith("tools/") and HISTORICAL_TOOL_NAME_RE.search(Path(relative).name):
        return True
    if relative == "lines/nalu/runtime/tools/ingest_yewujiang_source.py":
        return True
    if relative.startswith((
        "lines/nalu/runtime/engine_patches/",
        "workflow/cloud_factory_migration_v1_20260724/",
        "workflow/claude_writer_agent/",
        "tools/tests/fixtures/e04_negative_sample/",
    )):
        return True
    nested = relative.removeprefix("lines/nalu/runtime/tools/")
    return bool(
        nested == "review_fill/nalu_e03_s6_loop.sh"
        or re.fullmatch(r"review_fill/e\d+_fill_[A-Za-z0-9_]+\.py", nested)
    )


def _deployment_inventory_payload(
    source_tar: tarfile.TarFile,
    selected_files: set[str],
) -> bytes:
    """Build the integrity manifest for the files that actually ship.

    The repository inventory intentionally covers the complete maintainer
    checkout.  A generic StoryClaw archive is a strict subset, so copying that
    inventory would make verification fail after extraction.  Derive the same
    schema from immutable ``git archive`` bytes and keep the verifier's
    inclusion policy unchanged.
    """
    rows: list[dict[str, str]] = []
    for relative in sorted(selected_files):
        if not deployment_code_included(relative):
            continue
        try:
            member = source_tar.getmember(ARCHIVE_PREFIX + relative)
        except KeyError as exc:
            raise SystemExit(
                f"RELEASE_BLOCKED: selected deployment file is absent: {relative}"
            ) from exc
        stream = source_tar.extractfile(member)
        if stream is None:
            raise SystemExit(
                f"RELEASE_BLOCKED: selected deployment file is not regular: {relative}"
            )
        rows.append({
            "path": relative,
            "sha256": hashlib.sha256(stream.read()).hexdigest(),
        })
    if not rows:
        raise SystemExit("RELEASE_BLOCKED: generic deployment inventory is empty")
    payload = {
        "schema": DEPLOYMENT_CODE_SCHEMA,
        "scope": "PORTABLE_GENERIC_ENGINE_NOT_PRIVATE_RUNTIME",
        "file_count": len(rows),
        "files": rows,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode() + b"\n"


def portable_archive_files(source_tar: tarfile.TarFile) -> tuple[set[str], dict[str, int | str]]:
    """Select the reusable engine surface from an immutable Git tree.

    The repository intentionally retains old episode repair utilities for
    forensic replay.  They are not dependencies of a new customer's Agent and
    must not silently become part of the TalentHub release merely because they
    remain tracked by Git.
    """
    members = source_tar.getmembers()
    existing = {
        member.name[len(ARCHIVE_PREFIX):]
        for member in members
        if member.isfile() and member.name.startswith(ARCHIVE_PREFIX)
    }
    manifest = _tar_json(source_tar, "configs/PORTABLE_CORE_MANIFEST.json")
    required = set(_unique_string_list(manifest, "required_files"))
    test_modules = _unique_string_list(manifest, "portable_test_modules")
    tests = {_portable_test_path(module) for module in test_modules}
    registry = _tar_json(source_tar, "configs/GATE_REGISTRY_v3_20260716.json")
    registered = _json_repository_paths(registry, existing)
    knowledge = _tar_json(source_tar, "configs/ENGINEERING_KNOWLEDGE_V1.json")
    knowledge_paths = _json_repository_paths(knowledge, existing)
    strict_generic = str(manifest.get("version") or "") >= "0.5.0"
    declared_replay = sorted(required & FORBIDDEN_PORTABLE_MANIFEST_FILES)
    if strict_generic and declared_replay:
        raise SystemExit(
            "RELEASE_BLOCKED: generic manifest declares project replay files: "
            + ", ".join(declared_replay)
        )

    selected = (
        required | tests | registered | knowledge_paths | PORTABLE_ARCHIVE_ROOT_FILES
    ) & existing
    if strict_generic:
        selected = {relative for relative in selected if not _project_replay_path(relative)}
    for relative in existing:
        if strict_generic and _project_replay_path(relative):
            continue
        if relative.startswith(PORTABLE_ARCHIVE_TREE_PREFIXES):
            selected.add(relative)
        elif _generic_line_tool(relative):
            selected.add(relative)
        elif relative.startswith("configs/") and Path(relative).suffix == ".json":
            selected.add(relative)
        elif relative.startswith(("tools/policies/", "tools/schemas/")):
            selected.add(relative)

    # Runtime orchestrators call a small number of helpers by repository path
    # rather than by Python import.  Close that dependency set transitively,
    # while still refusing to sweep unrelated historical tools into the tarball.
    by_name = {
        member.name[len(ARCHIVE_PREFIX):]: member
        for member in members
        if member.isfile() and member.name.startswith(ARCHIVE_PREFIX)
    }
    while True:
        discovered: set[str] = set()
        for relative in sorted(selected):
            member = by_name.get(relative)
            if member is None or Path(relative).suffix not in {".py", ".sh", ".md"}:
                continue
            stream = source_tar.extractfile(member)
            if stream is None:
                continue
            text_value = stream.read().decode("utf-8", errors="ignore")
            discovered.update(
                match.group(1).rstrip("./")
                for match in REPOSITORY_PATH_RE.finditer(text_value)
                if match.group(1).rstrip("./") in existing
            )
            if Path(relative).suffix == ".py":
                discovered.update(_python_repository_imports(text_value, existing))
        discovered -= selected
        if strict_generic:
            discovered = {
                relative for relative in discovered if not _project_replay_path(relative)
            }
        if not discovered:
            break
        selected.update(discovered)

    if strict_generic:
        leaked = sorted(selected & FORBIDDEN_PORTABLE_MANIFEST_FILES)
        if leaked:
            raise SystemExit(
                "RELEASE_BLOCKED: generic archive selected project replay files: "
                + ", ".join(leaked)
            )
    return selected, {
        "portable_manifest_version": str(manifest.get("version") or "UNKNOWN"),
        "selected_file_count": len(selected),
        "tracked_file_count": len(existing),
    }


def archive_source(output: Path, tag: str, commit: str) -> tuple[Path, str]:
    archive = output / f"qingshan-storyclaw-workflow-{tag}.tar.gz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.unlink(missing_ok=True)
    commit_epoch = int(git("show", "-s", "--format=%ct", commit))
    built_at = datetime.fromtimestamp(commit_epoch, timezone.utc).isoformat().replace("+00:00", "Z")
    source = subprocess.check_output(
        ["git", "archive", "--format=tar", f"--prefix={ARCHIVE_PREFIX}", commit],
        cwd=ROOT,
    )
    with archive.open("wb") as raw, gzip.GzipFile(
        filename="", mode="wb", fileobj=raw, mtime=0
    ) as compressed, tarfile.open(fileobj=compressed, mode="w") as tar, tarfile.open(
        fileobj=io.BytesIO(source), mode="r:"
    ) as source_tar:
        selected_files, selection = portable_archive_files(source_tar)
        deployment_inventory = _deployment_inventory_payload(source_tar, selected_files)
        selected_directories = {
            "/".join(Path(relative).parts[:index])
            for relative in selected_files
            for index in range(1, len(Path(relative).parts))
        }
        for member in source_tar.getmembers():
            relative = member.name[len(ARCHIVE_PREFIX):] if member.name.startswith(ARCHIVE_PREFIX) else ""
            if member.isfile() and relative not in selected_files:
                continue
            if member.isfile() and relative == DEPLOYMENT_CODE_MANIFEST:
                # The tracked inventory describes the full maintainer checkout.
                # A package receives the subset inventory derived above.
                continue
            if member.isdir() and relative.rstrip("/") not in selected_directories and relative.rstrip("/"):
                continue
            extracted = source_tar.extractfile(member) if member.isfile() else None
            if extracted is None:
                tar.addfile(member)
            else:
                tar.addfile(member, extracted)
        inventory_info = tarfile.TarInfo(ARCHIVE_PREFIX + DEPLOYMENT_CODE_MANIFEST)
        inventory_info.size = len(deployment_inventory)
        inventory_info.mtime = commit_epoch
        inventory_info.mode = 0o644
        inventory_info.uid = inventory_info.gid = 0
        inventory_info.uname = inventory_info.gname = ""
        tar.addfile(inventory_info, io.BytesIO(deployment_inventory))
        release_info = {
            "schema": "qingshan.storyclaw.release.v1",
            "release_tag": tag,
            "git_commit": commit,
            "repository": GITHUB_REPO,
            "source_scope": "PORTABLE_GENERIC_ENGINE_NOT_PRIVATE_RUNTIME",
            "portable_manifest_version": selection["portable_manifest_version"],
            "selected_file_count": selection["selected_file_count"],
            "tracked_file_count": selection["tracked_file_count"],
            "built_at": built_at,
            "talenthub_agent_id": AGENT_ID,
            "talenthub_skill": SKILL_NAME,
            "private_runtime_included": False,
            "credentials_included": False,
            "paid_requests_enabled": False,
        }
        payload = json.dumps(release_info, ensure_ascii=False, indent=2).encode() + b"\n"
        info = tarfile.TarInfo("qingshan-storyclaw-workflow/RELEASE_MANIFEST.json")
        info.size = len(payload)
        info.mtime = commit_epoch
        info.mode = 0o644
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        tar.addfile(info, io.BytesIO(payload))
    audit_source_archive(archive)
    audit_portable_archive_inventory(archive)
    return archive, sha256(archive)


def write_talenthub_workspace(
    output: Path,
    tag: str,
    commit: str,
    archive_sha: str,
    *,
    archive_size: int,
    validation: dict[str, Any] | None,
    origin_tag_commit: str | None,
    release_channel: dict[str, Any] | None = None,
    release_sequence: int = 1,
    stable_index: dict[str, Any] | None = None,
    dependency_profiles: list[dict[str, Any]] | None = None,
    package_publish_required: bool = True,
) -> Path:
    workspace = output / "talenthub-agent"
    if workspace.exists():
        shutil.rmtree(workspace)
    (workspace / "skills" / SKILL_NAME).mkdir(parents=True)

    manifest = {
        "id": AGENT_ID,
        "name": "AI Drama Factory",
        "emoji": "🎬",
        "role": "Vertical drama production line director",
        "tagline": "Turn a novel into a gated, auditable vertical-drama production line.",
        "description": (
            "Runs the Qingshan/NALU S1-S8 production line on StoryClaw. "
            "It writes the script first, passes real gates, derives one complete asset plan, "
            "then waits for the user's single confirmation before any paid generation."
        ),
        "category": "creative",
        "skills": [f"{GITHUB_REPO}@{SKILL_NAME}"],
        "i18n": {
            "zh-CN": {
                "role": "竖屏短剧生产线导演",
                "tagline": "把原著变成有门禁、有收据、可复现的竖屏短剧生产线。",
                "description": "先生成剧本并通过 S1，再自动匹配角色、场景、道具和素材；一次性确认后才进入付费生成。",
            }
        },
        "minOpenClawVersion": "2026.3.1",
        "avatarUrl": None,
    }
    (workspace / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    identity = f"""# IDENTITY.md

- **Name:** AI Drama Factory
- **Chinese name:** AI短剧工厂
- **Release:** `{tag}` (`{commit}`)
- **Role:** Vertical-drama production-line director

You operate the public Qingshan/NALU engine pinned by the `qingshan-nalu` skill.
The engine is the source of truth for gates, receipts, transactions, budgets and
stage state. Never manufacture PASS, receipts, orders or paid submissions.
"""
    (workspace / "IDENTITY.md").write_text(identity, encoding="utf-8")
    for filename in ("USER.md", "SOUL.md", "HEARTBEAT.md"):
        source = PORTABLE_BRAIN_ROOT / filename
        shutil.copy2(source, workspace / filename)

    archive_url = github_release_archive_url(tag)
    validation_sha = validation["sha256"] if validation else None
    profile_rows = list(dependency_profiles or [])
    if (
        package_publish_required
        and validation is not None
        and validation.get("status") == "PASS"
    ):
        try:
            _dependency_bundle.validate_release_bindings(profile_rows, release_tag=tag)
        except _dependency_bundle.DependencyBundleBlocked as exc:
            raise SystemExit(
                f"RELEASE_BLOCKED: TalentHub package lacks dependency bundles: {exc}"
            ) from exc
    agents = (PORTABLE_BRAIN_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    channel_note = (
        f"The tag-specific stable-channel manifest is `{release_channel['url']}` "
        f"({release_channel['size_bytes']} bytes), SHA-256 "
        f"`{release_channel['sha256']}`. Its update class is "
        f"`{release_channel['update_class']}`."
        if release_channel
        else "No stable-channel manifest is bound to this experimental workspace."
    )
    discovery_note = (
        f"The signed stable discovery index is `{stable_index['url']}` with detached "
        f"signature `{stable_index['signature_url']}`. The pinned Ed25519 public-key "
        f"SHA-256 is `{stable_index['signing_key_sha256']}`."
        if stable_index
        else "This experimental workspace has no signed stable discovery index."
    )
    agents += f"""

## P0 TalentHub installed release provenance

This installed agent is bound to Qingshan/NALU tag `{tag}`, commit `{commit}`.
The matching public source archive is `{archive_url}` ({archive_size} bytes),
with SHA-256 `{archive_sha}`. Install or recover the engine from that immutable
tag and GitHub Release asset, verify the archive size and hash before
extraction, and reject a moving branch or an uncommitted StoryClaw repair.
The StoryClaw validation receipt SHA-256 is `{validation_sha or 'NOT_BOUND'}`.
{channel_note}
{discovery_note}

This tag is the bootstrap engine for the installed Agent. A later engine may
replace it only through the verified side-by-side updater and its private PASS
receipt. If the channel reports `TALENTHUB_PACKAGE_REQUIRED`, keep the current
engine selected until the user runs `talenthub agent update ai-drama-factory`; do not
rewrite TalentHub prompt files from inside the Agent.
"""
    (workspace / "AGENTS.md").write_text(agents, encoding="utf-8")

    skill_body = CANONICAL_SKILL.read_text(encoding="utf-8")
    if not skill_body.endswith("\n"):
        skill_body += "\n"
    skill = skill_body + f"""
## Installed release binding

- Release tag: `{tag}`
- Git commit: `{commit}`
- Origin peeled commit: `{origin_tag_commit or 'UNRELEASED_EXPERIMENT'}`
- Immutable source archive: `{archive_url}`
- Source archive size: `{archive_size}` bytes
- Source archive SHA-256: `{archive_sha}`
- StoryClaw validation receipt SHA-256: `{validation_sha or 'NOT_BOUND'}`

Clone the exact tag with:

```bash
git clone --branch {tag} --depth 1 {GITHUB_REPO} qingshan-engine
```

Verify the GitHub Release asset's byte size and SHA-256 before extraction. A
published workspace must have a bound validation receipt; its private contents
and evidence files are intentionally absent here.
"""
    (workspace / "skills" / SKILL_NAME / "SKILL.md").write_text(skill, encoding="utf-8")
    shutil.copy2(
        CANONICAL_BOOTSTRAP,
        workspace / "skills" / SKILL_NAME / "bootstrap_storyclaw.py",
    )
    installed_file_paths = (
        "IDENTITY.md",
        "USER.md",
        "SOUL.md",
        "AGENTS.md",
        "HEARTBEAT.md",
        f"skills/{SKILL_NAME}/SKILL.md",
        f"skills/{SKILL_NAME}/bootstrap_storyclaw.py",
    )
    installed_file_bindings = {
        relative: {
            "size_bytes": (workspace / relative).stat().st_size,
            "sha256": sha256(workspace / relative),
        }
        for relative in installed_file_paths
    }
    release_manifest = {
        "schema": "qingshan.storyclaw.talenthub.release.v1",
        "agent_id": AGENT_ID,
        "skill": SKILL_NAME,
        "release_tag": tag,
        "release_sequence": release_sequence,
        "git_commit": commit,
        "origin_tag_commit": origin_tag_commit,
        "source_archive_github_release_url": archive_url,
        "source_archive_size_bytes": archive_size,
        "source_archive_sha256": archive_sha,
        "release_channel_url": release_channel["url"] if release_channel else None,
        "release_channel_size_bytes": (
            release_channel["size_bytes"] if release_channel else None
        ),
        "release_channel_sha256": release_channel["sha256"] if release_channel else None,
        "release_channel_update_class": (
            release_channel["update_class"] if release_channel else None
        ),
        "stable_index_url": stable_index["url"] if stable_index else None,
        "stable_index_sha256": stable_index["sha256"] if stable_index else None,
        "stable_index_signature_url": (
            stable_index["signature_url"] if stable_index else None
        ),
        "stable_index_signature_sha256": (
            stable_index["signature_sha256"] if stable_index else None
        ),
        "release_signing_key_sha256": RELEASE_SIGNING_PUBLIC_KEY_SHA256,
        "validation_receipt_schema": validation["schema"] if validation else None,
        "validation_receipt_status": validation["status"] if validation else None,
        "validation_receipt_sha256": validation_sha,
        "validation_checks": validation["checks"] if validation else None,
        "repository": GITHUB_REPO,
        "public_runtime_only": True,
        "private_validation_contents_included": False,
        "dependency_profiles": profile_rows,
        "dependency_profiles_action": (
            "REPLACE_WITH_RELEASE_BUNDLES" if package_publish_required else "REUSE_CURRENT"
        ),
        "installed_file_bindings": installed_file_bindings,
    }
    release_manifest_text = json.dumps(release_manifest, ensure_ascii=False, indent=2) + "\n"
    (workspace / "skills" / SKILL_NAME / "RELEASE_MANIFEST.json").write_text(
        release_manifest_text, encoding="utf-8"
    )
    return workspace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--publish", action="store_true", help="publish the generated TalentHub workspace")
    parser.add_argument(
        "--registry-smoke-receipt",
        type=Path,
        help=(
            "finalize a prior private canary after an independent clean StoryClaw install; "
            "this phase never republishes the canary"
        ),
    )
    parser.add_argument(
        "--registry-canary-receipt",
        type=Path,
        help="explicit phase-one canary receipt; defaults to OUTPUT/REGISTRY_CANARY_PUBLISH_RECEIPT.json",
    )
    parser.add_argument("--skip-checks", action="store_true", help="for local packaging experiments only")
    parser.add_argument("--allow-unreleased", action="store_true", help="local packaging experiment; do not use for publication")
    parser.add_argument(
        "--previous-release-ref",
        help=(
            "previous immutable tag/full commit used to classify ENGINE_ONLY versus "
            "TalentHub/package or runtime-migration updates"
        ),
    )
    parser.add_argument(
        "--initial-release",
        action="store_true",
        help="declare the first TalentHub release; fail-closed to a full package update",
    )
    parser.add_argument(
        "--validation-receipt",
        type=Path,
        help="private StoryClaw release-validation receipt; required for --publish",
    )
    parser.add_argument(
        "--stable-signing-key",
        type=Path,
        help=(
            "private Ed25519 PEM used to sign the public stable discovery index; "
            "required for --publish and never copied into release artifacts"
        ),
    )
    parser.add_argument(
        "--dependency-wheelhouse-root",
        type=Path,
        help=(
            "Optional predownloaded profile directories. Each directory name must be an "
            "exact supported profile id and pass the checked-in hash lock. Without this, "
            "a validated publisher build downloads locked wheels before packaging."
        ),
    )
    args = parser.parse_args()

    if args.publish and args.registry_smoke_receipt is not None:
        raise SystemExit(
            "RELEASE_BLOCKED: --publish and --registry-smoke-receipt are separate phases"
        )
    if args.publish and args.registry_canary_receipt is not None:
        raise SystemExit(
            "RELEASE_BLOCKED: --registry-canary-receipt is an input to finalization only"
        )
    formal_mode = args.publish or args.registry_smoke_receipt is not None
    validate_publish_mode(
        publish=formal_mode,
        skip_checks=args.skip_checks,
        allow_unreleased=args.allow_unreleased,
        validation_receipt=args.validation_receipt,
    )
    validate_release_tag(args.release_tag)
    if formal_mode and args.stable_signing_key is None:
        raise SystemExit("RELEASE_BLOCKED: formal registry work requires --stable-signing-key")
    if args.stable_signing_key is not None and (
        args.validation_receipt is None or args.skip_checks or args.allow_unreleased
    ):
        raise SystemExit(
            "RELEASE_BLOCKED: stable signing requires validation, full checks, and a released tag"
        )
    portable_manifest_audit = validate_portable_release_manifest()
    assert_clean_worktree()
    commit = git("rev-parse", "HEAD")
    release_sequence = int(git("rev-list", "--count", commit))
    assert_tag_points_to_head(args.release_tag, commit, args.allow_unreleased)
    origin_tag_commit = assert_tag_pushed_to_origin(
        args.release_tag, commit, args.allow_unreleased
    )
    validation = (
        validate_storyclaw_release_receipt(args.validation_receipt, commit)
        if args.validation_receipt is not None
        else None
    )
    published_base: dict[str, Any] | None = None
    classification_base = args.previous_release_ref
    initial_release = args.initial_release
    if formal_mode:
        published_base = read_published_stable_pointer()
        classification_base, initial_release = resolve_publish_classification_base(
            args.previous_release_ref, args.initial_release, published_base
        )
    if not args.skip_checks:
        run_release_checks()
    impact = release_impact(
        classification_base,
        # Candidate CI deliberately has no release tag yet.  A full commit ID
        # is still immutable and lets the classifier compare daily ``main``
        # with the last promoted StoryClaw stable tag without weakening the
        # requirements for a real publication build.
        target_ref=commit if args.allow_unreleased else args.release_tag,
        initial_release=initial_release,
    )
    if published_base is not None and release_sequence <= int(
        published_base["release_sequence"]
    ):
        raise SystemExit(
            "RELEASE_BLOCKED: release sequence must advance beyond the signed stable base"
        )
    if formal_mode and impact["update_class"] == "RUNTIME_MIGRATION_REQUIRED":
        raise SystemExit(
            "RELEASE_BLOCKED: runtime migration releases require a separately implemented "
            "and validated migration/rollback transaction before promotion"
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    impact_path = args.output_dir / "UPGRADE_IMPACT.json"
    impact_path.write_text(
        json.dumps(impact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    archive, archive_sha = archive_source(args.output_dir, args.release_tag, commit)
    archive_size = archive.stat().st_size
    archive_url = github_release_archive_url(args.release_tag)
    package_publish_required = impact["update_class"] == PACKAGE_REQUIRED
    if args.registry_smoke_receipt is not None and not package_publish_required:
        raise SystemExit(
            "RELEASE_BLOCKED: registry clean-install finalization requires a package release"
        )
    dependency_profiles: list[dict[str, Any]] = []
    dependency_assets: tuple[Path, ...] = ()
    dependency_reports: list[dict[str, Any]] = []
    if validation is not None and package_publish_required:
        dependency_profiles, dependency_assets, dependency_reports = (
            build_dependency_profile_assets(
                args.output_dir,
                tag=args.release_tag,
                commit=commit,
                release_sequence=release_sequence,
                wheelhouse_root=args.dependency_wheelhouse_root,
            )
        )
    _channel_path, release_channel = write_release_channel_manifest(
        args.output_dir,
        tag=args.release_tag,
        commit=commit,
        archive_sha256=archive_sha,
        archive_size=archive_size,
        update_class=str(impact["update_class"]),
        dependencies_changed=bool(impact["dependencies_changed"]),
        runtime_migration=str(impact["runtime_migration"]),
        upgrade_impact=impact,
        release_sequence=release_sequence,
        validation=validation,
        dependency_profiles=dependency_profiles,
    )
    stable_index: dict[str, Any] | None = None
    stable_index_path: Path | None = None
    stable_signature_path: Path | None = None
    if args.stable_signing_key is not None:
        stable_index_path, stable_signature_path, stable_index = write_signed_stable_index(
            args.output_dir,
            tag=args.release_tag,
            commit=commit,
            release_sequence=release_sequence,
            archive_sha256=archive_sha,
            archive_size=archive_size,
            release_channel=release_channel,
            update_class=str(impact["update_class"]),
            validation=validation or {},
            signing_key=args.stable_signing_key,
        )
    workspace = write_talenthub_workspace(
        args.output_dir,
        args.release_tag,
        commit,
        archive_sha,
        archive_size=archive_size,
        validation=validation,
        origin_tag_commit=origin_tag_commit,
        release_channel=release_channel,
        release_sequence=release_sequence,
        stable_index=stable_index,
        dependency_profiles=dependency_profiles,
        package_publish_required=package_publish_required,
    )
    workspace_audit = audit_talenthub_workspace(workspace)
    cli_version = talenthub_cli_version()
    if formal_mode and package_publish_required and cli_version is None:
        raise SystemExit("RELEASE_BLOCKED: cannot determine installed TalentHub CLI version")
    receipt = {
        "schema": "qingshan.storyclaw.release.receipt.v1",
        "release_tag": args.release_tag,
        "git_commit": commit,
        "origin_tag_commit": origin_tag_commit,
        "source_archive": str(archive),
        "source_archive_github_release_url": archive_url,
        "source_archive_size_bytes": archive_size,
        "source_archive_sha256": archive_sha,
        "release_channel_manifest": release_channel["path"],
        "release_channel_manifest_url": release_channel["url"],
        "release_channel_manifest_size_bytes": release_channel["size_bytes"],
        "release_channel_manifest_sha256": release_channel["sha256"],
        "release_channel_update_class": release_channel["update_class"],
        "release_sequence": release_sequence,
        "stable_index": stable_index,
        "upgrade_impact": {
            "path": str(impact_path),
            "sha256": sha256(impact_path),
            "schema": impact.get("schema"),
            "base_ref": (impact.get("base") or {}).get("input"),
            "base_commit": (impact.get("base") or {}).get("commit"),
            "target_ref": (impact.get("target") or {}).get("input"),
            "target_commit": (impact.get("target") or {}).get("commit"),
            "update_class": impact.get("update_class"),
            "dependencies_changed": impact.get("dependencies_changed"),
            "runtime_schema_changed": impact.get("runtime_schema_changed"),
            "runtime_migration": impact.get("runtime_migration"),
            "changed_path_count": len(impact.get("changed_paths") or []),
            "reason_codes": [
                row.get("code") for row in (impact.get("reasons") or [])
                if isinstance(row, dict) and row.get("code")
            ],
        },
        "validation_receipt_schema": validation["schema"] if validation else None,
        "validation_receipt_status": validation["status"] if validation else None,
        "validation_receipt_sha256": validation["sha256"] if validation else None,
        "validation_checks": validation["checks"] if validation else None,
        "private_validation_contents_included": False,
        "talenthub_workspace": str(workspace),
        "talenthub_agent_id": AGENT_ID,
        "talenthub_skill": SKILL_NAME,
        "talenthub_cli_version": cli_version,
        "talenthub_registry_package": None,
        "talenthub_package_attestation": None,
        "checks": "SKIPPED" if args.skip_checks else "PASS",
        "archive_audit": "PASS",
        "portable_manifest_audit": portable_manifest_audit,
        "talenthub_workspace_audit": workspace_audit,
        "publish_requested": args.publish,
        "registry_finalize_requested": args.registry_smoke_receipt is not None,
        "publish_status": (
            "PENDING_PRIVATE_CANARY" if args.publish and package_publish_required
            else "PENDING_FORMAL_PUBLICATION" if args.registry_smoke_receipt is not None
            else "NOT_REQUIRED" if args.publish
            else "NOT_REQUESTED"
        ),
        "github_release_assets": None,
        "stable_base": published_base,
        "stable_pointer_promotion": None,
        "dependency_profiles": dependency_profiles,
        "dependency_bundle_builds": dependency_reports,
    }
    receipt_path = args.output_dir / "RELEASE_RECEIPT.json"
    _write_json_atomic(receipt_path, receipt)
    if formal_mode:
        assert stable_index_path is not None and stable_signature_path is not None
        github_assets = verify_published_github_assets(
            args.release_tag,
            (
                archive, _channel_path, stable_index_path, stable_signature_path,
                *dependency_assets,
            ),
        )
        receipt["github_release_assets"] = github_assets
        _write_json_atomic(receipt_path, receipt)
        if package_publish_required:
            canary_path = (
                args.registry_canary_receipt
                if args.registry_canary_receipt is not None
                else args.output_dir / REGISTRY_CANARY_RECEIPT_FILENAME
            )
            if args.publish:
                if canary_path.exists():
                    canary = load_registry_canary_receipt(
                        canary_path,
                        tag=args.release_tag,
                        commit=commit,
                        release_sequence=release_sequence,
                        stable_index_path=stable_index_path,
                        workspace=workspace,
                    )
                    remote_canary = read_authenticated_talenthub_manifest(
                        canary["canary_agent_id"]
                    )
                    if remote_canary is None or (
                        remote_canary["version"] != canary["canary_registry_version"]
                        or remote_canary["package_url"] != canary["canary_package_url"]
                    ):
                        raise SystemExit(
                            "RELEASE_BLOCKED: existing canary receipt differs from registry"
                        )
                    canary_package = verify_talenthub_registry_package_url(
                        workspace, canary["canary_package_url"]
                    )
                    if (
                        canary_package["size_bytes"] != canary["canary_package_size_bytes"]
                        or canary_package["sha256"] != canary["canary_package_sha256"]
                    ):
                        raise SystemExit("RELEASE_BLOCKED: existing canary package differs")
                    official_now = read_public_talenthub_manifest(AGENT_ID)
                    expected_official = (
                        {
                            "agent_id": AGENT_ID,
                            "version": canary["official_previous_version"],
                            "package_url": canary["official_previous_package_url"],
                        }
                        if canary["official_previous_version"] is not None else None
                    )
                    if official_now != expected_official:
                        raise SystemExit(
                            "RELEASE_BLOCKED: formal TalentHub entry changed after canary publication"
                        )
                else:
                    official_before = read_public_talenthub_manifest(AGENT_ID)
                    canary_id = talenthub_canary_agent_id(args.release_tag)
                    remote_canary = read_authenticated_talenthub_manifest(canary_id)
                    recovered_canary = recover_unreceipted_registry_canary(
                        workspace, remote_canary, official_before
                    )
                    if recovered_canary is None:
                        published = subprocess.run(
                            talenthub_canary_publish_command(workspace, args.release_tag),
                            cwd=ROOT, text=True, capture_output=True, check=False,
                        )
                        receipt["publish_exit_code"] = published.returncode
                        receipt["publish_output_tail"] = "\n".join(
                            (published.stdout + "\n" + published.stderr).strip().splitlines()[-20:]
                        )
                        if published.returncode != 0:
                            receipt["publish_status"] = "FAIL_PRIVATE_CANARY"
                            _write_json_atomic(receipt_path, receipt)
                            raise SystemExit(published.returncode)
                        canary_package = verify_talenthub_registry_package(
                            workspace, published.stdout, published.stderr
                        )
                        remote_canary = read_authenticated_talenthub_manifest(canary_id)
                        if remote_canary is None or remote_canary[
                            "package_url"
                        ] != canary_package["package_url"]:
                            raise SystemExit("RELEASE_BLOCKED: private canary readback mismatch")
                    else:
                        # A crash can occur after the registry accepted the unique
                        # canary but before its receipt was persisted.  Adopt it only
                        # if the authoritative ZIP is exactly this local workspace.
                        remote_canary, canary_package = recovered_canary
                    require_talenthub_version_advance(None, remote_canary["version"])
                    if read_public_talenthub_manifest(AGENT_ID) != official_before:
                        raise SystemExit(
                            "RELEASE_BLOCKED: canary publication changed the formal public entry"
                        )
                    _canary_path, canary = write_registry_canary_receipt(
                        args.output_dir,
                        tag=args.release_tag,
                        commit=commit,
                        release_sequence=release_sequence,
                        stable_index_path=stable_index_path,
                        workspace=workspace,
                        canary_agent_id=canary_id,
                        canary_version=remote_canary["version"],
                        canary_package=canary_package,
                        official_before=official_before,
                    )
                receipt["talenthub_registry_package"] = canary_package
                receipt["registry_canary_receipt"] = canary
                receipt["publish_status"] = "PENDING_REGISTRY_CLEAN_INSTALL_SMOKE"
                receipt["stable_pointer_promotion"] = {
                    "status": "PENDING_REGISTRY_CLEAN_INSTALL_SMOKE",
                    "canary_agent_id": canary["canary_agent_id"],
                    "canary_receipt_sha256": canary["sha256"],
                }
                _write_json_atomic(receipt_path, receipt)
            else:
                canary = load_registry_canary_receipt(
                    canary_path,
                    tag=args.release_tag,
                    commit=commit,
                    release_sequence=release_sequence,
                    stable_index_path=stable_index_path,
                    workspace=workspace,
                )
                clean_smoke = validate_registry_clean_smoke(
                    args.registry_smoke_receipt,
                    tag=args.release_tag,
                    commit=commit,
                    release_sequence=release_sequence,
                    stable_index_path=stable_index_path,
                    archive=archive,
                    workspace=workspace,
                    canary=canary,
                )
                canary_package = verify_talenthub_registry_package_url(
                    workspace, canary["canary_package_url"]
                )
                if (
                    canary_package["size_bytes"] != canary["canary_package_size_bytes"]
                    or canary_package["sha256"] != canary["canary_package_sha256"]
                ):
                    raise SystemExit("RELEASE_BLOCKED: smoke-tested canary package changed")
                formal_path = args.output_dir / REGISTRY_FORMAL_RECEIPT_FILENAME
                if formal_path.exists():
                    formal = load_registry_formal_receipt(
                        formal_path,
                        tag=args.release_tag,
                        commit=commit,
                        release_sequence=release_sequence,
                        canary=canary,
                    )
                    official = read_public_talenthub_manifest(AGENT_ID)
                    if official is None or (
                        official["version"] != formal["official_published_version"]
                        or official["package_url"] != formal["official_package_url"]
                    ):
                        raise SystemExit(
                            "RELEASE_BLOCKED: formal registry receipt differs from public registry"
                        )
                    official_package = verify_talenthub_registry_package_url(
                        workspace, official["package_url"]
                    )
                else:
                    official_before = read_public_talenthub_manifest(AGENT_ID)
                    recovered = recover_formal_registry_publication(
                        workspace, canary, official_before
                    )
                    if recovered is None:
                        published = subprocess.run(
                            talenthub_formal_publish_command(workspace),
                            cwd=ROOT, text=True, capture_output=True, check=False,
                        )
                        receipt["publish_exit_code"] = published.returncode
                        receipt["publish_output_tail"] = "\n".join(
                            (published.stdout + "\n" + published.stderr).strip().splitlines()[-20:]
                        )
                        if published.returncode != 0:
                            receipt["publish_status"] = "FAIL_FORMAL_PUBLICATION"
                            _write_json_atomic(receipt_path, receipt)
                            raise SystemExit(published.returncode)
                        official_from_output = verify_talenthub_registry_package(
                            workspace, published.stdout, published.stderr
                        )
                        official = read_public_talenthub_manifest(AGENT_ID)
                        if official is None or official[
                            "package_url"
                        ] != official_from_output["package_url"]:
                            raise SystemExit(
                                "RELEASE_BLOCKED: formal public registry readback failed"
                            )
                        require_talenthub_version_advance(
                            canary["official_previous_version"], official["version"]
                        )
                        official_package = verify_talenthub_registry_package_url(
                            workspace, official["package_url"]
                        )
                        if (
                            official_package["size_bytes"]
                            != canary["canary_package_size_bytes"]
                            or official_package["sha256"]
                            != canary["canary_package_sha256"]
                        ):
                            raise SystemExit(
                                "RELEASE_BLOCKED: formal, canary and local TalentHub ZIPs differ"
                            )
                    else:
                        official, official_package = recovered
                    _formal_path, formal = write_registry_formal_receipt(
                        args.output_dir,
                        tag=args.release_tag,
                        commit=commit,
                        release_sequence=release_sequence,
                        canary=canary,
                        official=official,
                        package=official_package,
                    )
                if (
                    official_package["size_bytes"] != canary["canary_package_size_bytes"]
                    or official_package["sha256"] != canary["canary_package_sha256"]
                ):
                    raise SystemExit(
                        "RELEASE_BLOCKED: formal, canary and local TalentHub ZIPs differ"
                    )
                attestation_path, attestation_signature, attestation = (
                    write_signed_talenthub_package_attestation(
                        args.output_dir,
                        tag=args.release_tag,
                        commit=commit,
                        stable_index_path=stable_index_path,
                        workspace=workspace,
                        registry_package=official_package,
                        canary_receipt=canary,
                        formal_receipt=formal,
                        clean_smoke=clean_smoke,
                        signing_key=args.stable_signing_key,
                    )
                )
                attestation["github_release_assets"] = upload_immutable_release_assets(
                    args.release_tag,
                    (attestation_path, attestation_signature),
                )
                receipt["talenthub_registry_package"] = official_package
                receipt["registry_canary_receipt"] = canary
                receipt["registry_formal_receipt"] = formal
                receipt["registry_clean_install_smoke"] = clean_smoke
                receipt["talenthub_package_attestation"] = attestation
                receipt["talenthub_published_version"] = formal[
                    "official_published_version"
                ]
                receipt["publish_status"] = "PASS_PUBLIC_AFTER_CLEAN_INSTALL_SMOKE"
                cleanup = subprocess.run(
                    ["talenthub", "agent", "unpublish", canary["canary_agent_id"]],
                    cwd=ROOT, text=True, input="y\n", capture_output=True, check=False,
                )
                canary_after_cleanup = read_authenticated_talenthub_manifest(
                    canary["canary_agent_id"]
                )
                receipt["canary_cleanup"] = canary_cleanup_report(
                    cleanup, canary_after_cleanup
                )
                _write_json_atomic(receipt_path, receipt)
        # Stable-channel mutation is deliberately serialized by the dedicated
        # GitHub Actions workflow. A local publisher may prepare and verify the
        # exact signed candidate, but cannot race another publisher's clobber.
        ready = not package_publish_required or args.registry_smoke_receipt is not None
        if ready:
            receipt["stable_pointer_promotion"] = {
                "status": "READY_FOR_SERIALIZED_WORKFLOW",
                "workflow": "storyclaw-stable-promote.yml",
                "target_tag": args.release_tag,
                "target_index_sha256": sha256(stable_index_path),
                "target_signature_sha256": sha256(stable_signature_path),
                "expected_base_sequence": (
                    published_base["release_sequence"] if published_base else 0
                ),
                "expected_base_tag": (
                    published_base["release_tag"] if published_base else "NONE"
                ),
                "expected_base_commit": (
                    published_base["git_commit"] if published_base else "NONE"
                ),
                "expected_base_index_sha256": (
                    published_base["_index_sha256"] if published_base else "NONE"
                ),
            }
        _write_json_atomic(receipt_path, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
