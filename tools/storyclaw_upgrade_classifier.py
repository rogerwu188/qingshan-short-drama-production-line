#!/usr/bin/env python3
"""Classify the impact of one immutable NALU release on another.

The engine updater is intentionally allowed to consume only ``ENGINE_ONLY``
releases.  Changes to the TalentHub-managed agent surface require a TalentHub
package update, while persistent runtime-schema changes require an explicit
migration release.  This tool makes that decision from two immutable Git
commits or tags; it never follows a branch such as ``main``.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Optional, Sequence

try:
    from tools.storyclaw_release_surface import (
        TALENTHUB_MANAGED_EXACT,
        TALENTHUB_MANAGED_FILE_PREFIXES,
        TALENTHUB_MANAGED_TREE_ROOTS,
        is_talenthub_managed,
    )
except ModuleNotFoundError:  # direct ``python tools/...`` execution
    from storyclaw_release_surface import (  # type: ignore[no-redef]
        TALENTHUB_MANAGED_EXACT,
        TALENTHUB_MANAGED_FILE_PREFIXES,
        TALENTHUB_MANAGED_TREE_ROOTS,
        is_talenthub_managed,
    )


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "storyclaw.nalu.upgrade_impact.v1"
ERROR_SCHEMA = "storyclaw.nalu.upgrade_impact_error.v1"

ENGINE_ONLY = "ENGINE_ONLY"
TALENTHUB_PACKAGE_REQUIRED = "TALENTHUB_PACKAGE_REQUIRED"
RUNTIME_MIGRATION_REQUIRED = "RUNTIME_MIGRATION_REQUIRED"

_FULL_OBJECT_ID_RE = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
_SAFE_TAG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+\-]{0,199}\Z")
_MUTABLE_REF_NAMES = {
    "head",
    "main",
    "master",
    "develop",
    "development",
    "trunk",
    "latest",
    "nightly",
    "canary",
    "edge",
}

# A dependency change cannot use the offline engine-only updater because the
# existing private venv may no longer satisfy the release.
DEPENDENCY_EXACT = frozenset(
    {
        ".python-version",
        "Pipfile",
        "Pipfile.lock",
        "poetry.lock",
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
        "uv.lock",
    }
)
DEPENDENCY_PREFIXES = ("requirements/", "constraints/")

# Only constants that identify persistent private-runtime formats belong here.
# Receipt/report schemas can evolve without rewriting existing project state,
# so treating every ``SCHEMA`` symbol in the repository as a migration would
# make safe engine-only releases impossible.
RUNTIME_SCHEMA_CONSTANTS: Mapping[str, frozenset[str]] = {
    "lines/nalu/runtime/tools/nalu_pipeline.py": frozenset({"SCHEMA"}),
    "lines/nalu/runtime/tools/nalu_series_scope.py": frozenset({"SCHEMA"}),
    "lines/nalu/runtime/tools/nalu_budget_ledger.py": frozenset({"SCHEMA"}),
    "lines/nalu/runtime/tools/nalu_qa_common.py": frozenset(
        {"SCHEMA_REQUEST", "SCHEMA_ANSWERS", "SCHEMA_SUBMITTED"}
    ),
    "tools/storyclaw_audio_provider.py": frozenset({"SCHEMA"}),
    "tools/storyclaw_install.py": frozenset(
        {"RECEIPT_SCHEMA", "UPGRADE_RECEIPT_SCHEMA", "CURRENT_RELEASE_STATE_SCHEMA"}
    ),
    "tools/storyclaw_release_discovery.py": frozenset({"RESULT_SCHEMA"}),
    "tools/storyclaw_upgrade_transaction.py": frozenset({"SCHEMA"}),
    "tools/storyclaw_writer_workflow.py": frozenset(
        {"INPUT_SCHEMA", "LEXICON_DRAFT_SCHEMA", "ACTIVE_SCHEMA", "SEAL_SCHEMA"}
    ),
    "tools/storyclaw_asset_plan_gate.py": frozenset(
        {
            "PLAN_SCHEMA",
            "SCRIPT_EVIDENCE_SCHEMA",
            "CONFIRMATION_RECEIPT_SCHEMA",
            "REPORT_SCHEMA",
        }
    ),
    "tools/storyclaw_guided_onboarding.py": frozenset({"MATERIAL_RECEIPT_SCHEMA"}),
    "tools/storyclaw_project_intake.py": frozenset(
        {"PROJECT_SCHEMA", "INTAKE_SCHEMA", "SERIES_SCOPES_SCHEMA", "ORDERS_SCHEMA"}
    ),
    "lines/nalu/runtime/tools/final_audience_review.py": frozenset(
        {"REQUEST_SCHEMA", "ANSWERS_SCHEMA", "REPORT_SCHEMA", "LEDGER_SCHEMA"}
    ),
    "lines/nalu/runtime/tools/bootstrap_voice_references.py": frozenset(
        {"REGISTRY_SCHEMA", "POLICY_SCHEMA"}
    ),
    "lines/nalu/runtime/tools/identity_qa_lock.py": frozenset({"LIBRARY_SCHEMA"}),
    "lines/nalu/runtime/tools/materialize_paid_authorization.py": frozenset(
        {"ORDERS_SCHEMA", "RECEIPT_SCHEMA"}
    ),
}


class ClassificationBlocked(RuntimeError):
    """A fail-closed refusal to classify mutable or unverifiable inputs."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}:{detail}" if detail else code)


def _git(
    root: Path,
    arguments: Sequence[str],
    *,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[Any]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        text=text,
        env=environment,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.strip() if text else ""
        raise ClassificationBlocked("GIT_COMMAND_FAILED", stderr or " ".join(arguments))
    return result


def _repository_root(root: Path) -> Path:
    candidate = Path(root).expanduser().resolve()
    result = _git(candidate, ["rev-parse", "--show-toplevel"], check=False)
    if result.returncode != 0:
        raise ClassificationBlocked("NOT_A_GIT_REPOSITORY", str(candidate))
    discovered = Path(result.stdout.strip()).resolve()
    if discovered != candidate:
        raise ClassificationBlocked(
            "REPOSITORY_ROOT_REQUIRED", f"requested={candidate},actual={discovered}"
        )
    return discovered


def _validate_tag_syntax(value: str) -> str:
    tag = value.strip()
    lowered = tag.lower()
    if (
        not _SAFE_TAG_RE.fullmatch(tag)
        or ".." in tag
        or "@{" in tag
        or tag.endswith(("/", ".", ".lock"))
        or tag.startswith("-")
        or lowered in _MUTABLE_REF_NAMES
        or lowered.startswith(("refs/", "origin/", "remotes/", "heads/"))
    ):
        raise ClassificationBlocked("MUTABLE_OR_INVALID_REF", value)
    return tag


def _resolve_immutable_ref(root: Path, value: str, label: str) -> dict[str, str]:
    ref = str(value or "").strip()
    if not ref:
        raise ClassificationBlocked(f"{label}_REF_REQUIRED")

    if _FULL_OBJECT_ID_RE.fullmatch(ref):
        result = _git(root, ["rev-parse", "--verify", f"{ref}^{{commit}}"], check=False)
        if result.returncode != 0:
            raise ClassificationBlocked(f"{label}_COMMIT_NOT_FOUND", ref)
        commit = result.stdout.strip().lower()
        # Full object IDs only: abbreviated hashes could change meaning as the
        # repository grows and therefore are not immutable release inputs.
        if commit != ref.lower():
            raise ClassificationBlocked(f"{label}_COMMIT_NOT_EXACT", ref)
        return {"input": ref, "kind": "commit", "commit": commit}

    tag = _validate_tag_syntax(ref)
    tag_ref = f"refs/tags/{tag}"
    exists = _git(root, ["show-ref", "--verify", "--quiet", tag_ref], check=False)
    if exists.returncode != 0:
        branch = _git(root, ["show-ref", "--verify", "--quiet", f"refs/heads/{tag}"], check=False)
        code = f"{label}_BRANCH_FORBIDDEN" if branch.returncode == 0 else f"{label}_TAG_NOT_FOUND"
        raise ClassificationBlocked(code, ref)
    result = _git(root, ["rev-parse", "--verify", f"{tag_ref}^{{commit}}"])
    commit = result.stdout.strip().lower()
    if not _FULL_OBJECT_ID_RE.fullmatch(commit):
        raise ClassificationBlocked(f"{label}_TAG_COMMIT_INVALID", commit)
    return {"input": ref, "kind": "tag", "tag": tag, "commit": commit}


def _changed_paths(root: Path, base: str, target: str) -> list[str]:
    result = _git(
        root,
        ["diff", "--name-only", "--no-renames", "-z", base, target, "--"],
        text=False,
    )
    try:
        names = result.stdout.decode("utf-8").split("\0")
    except UnicodeDecodeError as exc:
        raise ClassificationBlocked("NON_UTF8_GIT_PATH", str(exc)) from exc
    paths: list[str] = []
    for name in names:
        if not name:
            continue
        pure = PurePosixPath(name)
        if pure.is_absolute() or ".." in pure.parts:
            raise ClassificationBlocked("UNSAFE_CHANGED_PATH", name)
        paths.append(pure.as_posix())
    return sorted(set(paths))


def _is_talenthub_managed(path: str) -> bool:
    return is_talenthub_managed(path)


def _is_dependency_path(path: str) -> bool:
    name = PurePosixPath(path).name
    lowered = name.lower()
    return (
        path in DEPENDENCY_EXACT
        or path.startswith(DEPENDENCY_PREFIXES)
        or lowered.startswith("requirements") and lowered.endswith((".txt", ".in"))
        or lowered.startswith("constraints") and lowered.endswith((".txt", ".in"))
        or lowered.startswith("dockerfile")
        or lowered in {"environment.yml", "environment.yaml", "conda.yml", "conda.yaml"}
    )


def _is_schema_definition_path(path: str) -> bool:
    lowered = path.lower()
    parts = PurePosixPath(lowered).parts
    return (
        lowered.endswith(".schema.json")
        or "migrations" in parts
        or "runtime_migrations" in parts
        or lowered == "configs/storyclaw_runtime_schema_contract.json"
    )


def _show_file(root: Path, commit: str, path: str) -> Optional[str]:
    result = _git(root, ["show", f"{commit}:{path}"], check=False, text=False)
    if result.returncode != 0:
        return None
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ClassificationBlocked("SCHEMA_SOURCE_NOT_UTF8", f"{path}:{exc}") from exc


def _assigned_constants(
    source: Optional[str], names: Iterable[str]
) -> Optional[dict[str, Any]]:
    if source is None:
        return None
    wanted = set(names)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    values: dict[str, Any] = {}
    for statement in tree.body:
        targets: list[ast.expr] = []
        value: Optional[ast.expr] = None
        if isinstance(statement, ast.Assign):
            targets = list(statement.targets)
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
            value = statement.value
        if value is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id in wanted:
                try:
                    values[target.id] = ast.literal_eval(value)
                except (ValueError, TypeError):
                    values[target.id] = "<NON_LITERAL>"
    return values


def _runtime_schema_changes(
    root: Path,
    base_commit: str,
    target_commit: str,
    changed_paths: Sequence[str],
) -> tuple[list[str], list[str]]:
    paths: set[str] = {path for path in changed_paths if _is_schema_definition_path(path)}
    inspection_failures: list[str] = []
    for path in changed_paths:
        names = RUNTIME_SCHEMA_CONSTANTS.get(path)
        if not names:
            continue
        before = _assigned_constants(_show_file(root, base_commit, path), names)
        after = _assigned_constants(_show_file(root, target_commit, path), names)
        if before is None or after is None:
            # An added/deleted or unparsable persistent schema carrier cannot
            # safely be called engine-only.
            paths.add(path)
            inspection_failures.append(path)
        elif before != after:
            paths.add(path)
    return sorted(paths), sorted(inspection_failures)


def classify_release(
    base_ref: str,
    target_ref: str,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Return upgrade impact for two immutable Git commits or tags.

    ``base_ref`` and ``target_ref`` must each be a full object ID or an exact
    tag.  Branches, ``HEAD``, abbreviated hashes and channel aliases are
    rejected.  The target must descend from the base, preventing accidental
    downgrade or cross-branch release comparisons.
    """

    repository = _repository_root(Path(root))
    base = _resolve_immutable_ref(repository, base_ref, "BASE")
    target = _resolve_immutable_ref(repository, target_ref, "TARGET")

    ancestry = _git(
        repository,
        ["merge-base", "--is-ancestor", base["commit"], target["commit"]],
        check=False,
    )
    if ancestry.returncode == 1:
        raise ClassificationBlocked(
            "TARGET_NOT_DESCENDANT_OF_BASE", f"{base['commit']}..{target['commit']}"
        )
    if ancestry.returncode != 0:
        raise ClassificationBlocked("ANCESTRY_CHECK_FAILED")

    changed_paths = _changed_paths(repository, base["commit"], target["commit"])
    talenthub_paths = [path for path in changed_paths if _is_talenthub_managed(path)]
    dependency_paths = [path for path in changed_paths if _is_dependency_path(path)]
    schema_paths, schema_inspection_failures = _runtime_schema_changes(
        repository, base["commit"], target["commit"], changed_paths
    )

    dependencies_changed = bool(dependency_paths)
    runtime_schema_changed = bool(schema_paths)
    talenthub_managed_changed = bool(talenthub_paths)
    reasons: list[dict[str, Any]] = []
    if runtime_schema_changed:
        reasons.append(
            {
                "code": "RUNTIME_SCHEMA_CHANGE",
                "summary": "Persistent runtime schema changed; an explicit migration release is required.",
                "paths": schema_paths,
            }
        )
    if schema_inspection_failures:
        reasons.append(
            {
                "code": "RUNTIME_SCHEMA_INSPECTION_FAIL_CLOSED",
                "summary": "A persistent schema carrier could not be compared safely.",
                "paths": schema_inspection_failures,
            }
        )
    if dependencies_changed:
        reasons.append(
            {
                "code": "DEPENDENCY_CHANGE",
                "summary": "Host or Python dependencies changed; rebuild and republish the TalentHub package.",
                "paths": dependency_paths,
            }
        )
    if talenthub_managed_changed:
        reasons.append(
            {
                "code": "TALENTHUB_MANAGED_SURFACE_CHANGE",
                "summary": "TalentHub-managed brain, skill, onboarding, installer, or release surface changed.",
                "paths": talenthub_paths,
            }
        )

    if runtime_schema_changed:
        update_class = RUNTIME_MIGRATION_REQUIRED
    elif dependencies_changed or talenthub_managed_changed:
        update_class = TALENTHUB_PACKAGE_REQUIRED
    else:
        update_class = ENGINE_ONLY
        engine_paths = list(changed_paths)
        reasons.append(
            {
                "code": "ENGINE_CODE_CHANGE" if engine_paths else "NO_CHANGES",
                "summary": (
                    "Only engine implementation changed; immutable side-by-side upgrade is eligible."
                    if engine_paths
                    else "The immutable refs resolve to identical content."
                ),
                "paths": engine_paths,
            }
        )

    return {
        "schema": SCHEMA,
        "status": "PASS",
        "repository": str(repository),
        "base": base,
        "target": target,
        "immutable_refs_verified": True,
        "target_descends_from_base": True,
        "update_class": update_class,
        "dependencies_changed": dependencies_changed,
        "runtime_schema_changed": runtime_schema_changed,
        "runtime_migration": "REQUIRED" if runtime_schema_changed else "NONE",
        "talenthub_managed_changed": talenthub_managed_changed,
        "talenthub_republish_required": update_class != ENGINE_ONLY,
        "engine_only_eligible": update_class == ENGINE_ONLY,
        "changed_paths": changed_paths,
        "classified_paths": {
            "talenthub_managed": talenthub_paths,
            "dependencies": dependency_paths,
            "runtime_schema": schema_paths,
        },
        "reasons": reasons,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Classify an immutable NALU release diff for StoryClaw/TalentHub."
    )
    parser.add_argument("--base", required=True, help="full commit ID or exact immutable tag")
    parser.add_argument("--target", required=True, help="full commit ID or exact immutable tag")
    parser.add_argument("--repo", type=Path, default=ROOT, help="Git repository root")
    parser.add_argument("--pretty", action="store_true", help="indent JSON output")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = classify_release(args.base, args.target, root=args.repo)
    except ClassificationBlocked as exc:
        result = {
            "schema": ERROR_SCHEMA,
            "status": "BLOCKED",
            "error": {"code": exc.code, "detail": exc.detail},
        }
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 2
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
