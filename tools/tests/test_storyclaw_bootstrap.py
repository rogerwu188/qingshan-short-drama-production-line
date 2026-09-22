"""Tests for the TalentHub-bundled one-command bootstrap."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import types
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import storyclaw_registry_clean_install_smoke as smoke


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "skills/qingshan-nalu/bootstrap_storyclaw.py"
SPEC = importlib.util.spec_from_file_location("storyclaw_skill_bootstrap", SOURCE)
bootstrap = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(bootstrap)


class StoryClawSkillBootstrapTests(unittest.TestCase):
    @staticmethod
    def _dependency_fixture(tag: str) -> tuple[list[dict[str, object]], dict[str, bytes]]:
        rows: list[dict[str, object]] = []
        assets: dict[str, bytes] = {}
        for index, profile_id in enumerate(
            sorted(bootstrap.DEPENDENCY_PROFILE_BY_PYTHON.values()), 1
        ):
            manifest_name, archive_name = bootstrap._dependency_asset_names(
                tag, profile_id
            )
            manifest = f"manifest-{profile_id}".encode()
            archive = f"archive-{profile_id}".encode()
            manifest_url = bootstrap._asset_url(tag, manifest_name)
            archive_url = bootstrap._asset_url(tag, archive_name)
            assets[manifest_url] = manifest
            assets[archive_url] = archive
            rows.append({
                "profile_id": profile_id,
                "manifest_url": manifest_url,
                "manifest_size_bytes": len(manifest),
                "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
                "archive_url": archive_url,
                "archive_size_bytes": len(archive),
                "archive_sha256": hashlib.sha256(archive).hexdigest(),
            })
        return rows, assets

    @staticmethod
    def _custom_archive(entries: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            root = tarfile.TarInfo("qingshan-storyclaw-workflow")
            root.type = tarfile.DIRTYPE
            tar.addfile(root)
            for info, body in entries:
                tar.addfile(info, io.BytesIO(body) if body is not None else None)
        return buffer.getvalue()

    @staticmethod
    def _archive(commit: str, tag: str = "v1.2.3") -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            root = tarfile.TarInfo("qingshan-storyclaw-workflow")
            root.type = tarfile.DIRTYPE
            tar.addfile(root)
            workflow = tarfile.TarInfo("qingshan-storyclaw-workflow/workflow")
            workflow.type = tarfile.DIRTYPE
            workflow.mode = 0o755
            tar.addfile(workflow)
            files = {
                "RELEASE_MANIFEST.json": json.dumps({
                    "schema": "qingshan.storyclaw.release.v1",
                    "release_tag": tag,
                    "git_commit": commit,
                    "private_runtime_included": False,
                    "credentials_included": False,
                }).encode(),
                "tools/storyclaw_project_intake.py": b"# fixture\n",
                "tools/storyclaw_install.py": b"# fixture\n",
                "tools/storyclaw_nalu_runtime.py": b"# fixture\n",
                "tools/storyclaw_registry_clean_install_smoke.py": b"# fixture\n",
            }
            for relative, body in files.items():
                info = tarfile.TarInfo(f"qingshan-storyclaw-workflow/{relative}")
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
        return buffer.getvalue()

    def _workspace(self, root: Path, archive: bytes, commit: str) -> Path:
        workspace = root / "workspace"
        for relative in bootstrap.BOUND_FILES:
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if relative.endswith("bootstrap_storyclaw.py"):
                target.write_bytes(SOURCE.read_bytes())
            else:
                target.write_text(f"bound {relative}\n", encoding="utf-8")
        bindings = {
            relative: {
                "size_bytes": (workspace / relative).stat().st_size,
                "sha256": hashlib.sha256((workspace / relative).read_bytes()).hexdigest(),
            }
            for relative in bootstrap.BOUND_FILES
        }
        tag = "v1.2.3"
        dependency_profiles, _assets = self._dependency_fixture(tag)
        manifest = {
            "schema": bootstrap.SCHEMA,
            "agent_id": bootstrap.AGENT_ID,
            "skill": bootstrap.SKILL_NAME,
            "release_tag": tag,
            "release_sequence": 12,
            "git_commit": commit,
            "origin_tag_commit": commit,
            "repository": bootstrap.REPOSITORY,
            "source_archive_github_release_url": (
                f"{bootstrap.REPOSITORY}/releases/download/{tag}/"
                f"qingshan-storyclaw-workflow-{tag}.tar.gz"
            ),
            "source_archive_size_bytes": len(archive),
            "source_archive_sha256": hashlib.sha256(archive).hexdigest(),
            "release_signing_key_sha256": bootstrap.SIGNING_KEY_SHA256,
            "validation_receipt_status": "PASS",
            "public_runtime_only": True,
            "private_validation_contents_included": False,
            "dependency_profiles_action": "REPLACE_WITH_RELEASE_BUNDLES",
            "dependency_profiles": dependency_profiles,
            "installed_file_bindings": bindings,
        }
        (workspace / "skills/qingshan-nalu/RELEASE_MANIFEST.json").write_text(
            json.dumps(manifest) + "\n", encoding="utf-8"
        )
        return workspace

    def test_bootstrap_uses_future_link_before_install_and_finishes_bound(self):
        commit = "a" * 40
        archive = self._archive(commit)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root, archive, commit)
            project_home = root / "project-home"
            calls: list[list[str]] = []
            dependency_profiles, dependency_assets = self._dependency_fixture("v1.2.3")
            selected = dependency_profiles[0]
            preflight_failure = {"enabled": False}
            after_snapshot_failure = {"enabled": False}

            child_environments: list[dict[str, str]] = []

            def runner(command, **kwargs):
                command = list(command)
                calls.append(command)
                child_environments.append(dict(kwargs["env"]))
                if len(command) > 2 and command[1].endswith("storyclaw_project_intake.py"):
                    projects = Path(command[command.index("--projects-root") + 1])
                    engine_link = Path(command[command.index("--engine-root") + 1])
                    runtime = projects / "test-project"
                    (runtime / "runtime").mkdir(parents=True, exist_ok=True)
                    marker = {
                        "status": "INITIALIZED_PRIVATE",
                        "private_runtime_root": str(runtime),
                        "engine_root": str(engine_link),
                        "project_id": "test-project",
                        "series_scope_id": "TEST-SCOPE",
                        "paid_requests_enabled": False,
                    }
                    (runtime / "runtime/project.json").write_text(json.dumps(marker))
                    (runtime / ".qingshan-private-runtime.json").write_text(
                        json.dumps(marker)
                    )
                    workspace_backing = runtime / "runtime/storyclaw_storage/workflow/nalu"
                    transaction_backing = runtime / "runtime/storyclaw_storage/workflow/tasks"
                    workspace_backing.mkdir(parents=True, exist_ok=True)
                    transaction_backing.mkdir(parents=True, exist_ok=True)
                    (runtime / "qingshan.json").write_text(json.dumps({
                        "generation": {"paid_requests_enabled": False},
                        "storyclaw": {
                            "policy_profile": "CURRENT_PORTABLE",
                            "series_scope_id": "TEST-SCOPE",
                            "storage": {
                            "engine_root": str(engine_link),
                            "workspace_mount_target": str(engine_link / "workflow/nalu"),
                            "workspace_backing_path": str(workspace_backing),
                            "transactions_mount_target": str(engine_link / "workflow/tasks"),
                            "transactions_backing_path": str(transaction_backing),
                        }}
                    }))
                    return subprocess.CompletedProcess(command, 0, json.dumps(marker), "")
                if len(command) > 3 and command[1].endswith(
                    "storyclaw_registry_clean_install_smoke.py"
                ):
                    runtime = Path(command[command.index("--runtime-root") + 1])
                    output = Path(command[command.index("--output") + 1])
                    label = command[command.index("--label") + 1]
                    if label == "after" and after_snapshot_failure["enabled"]:
                        return subprocess.CompletedProcess(
                            command, 2, "", "injected after-snapshot failure"
                        )
                    prior = (
                        Path(command[command.index("--prior-snapshot") + 1])
                        if "--prior-snapshot" in command else None
                    )
                    with mock.patch.dict(os.environ, kwargs["env"], clear=True):
                        summary = smoke.snapshot_transactions(
                            runtime, output, label=label, prior_snapshot=prior
                        )
                    return subprocess.CompletedProcess(
                        command, 0, json.dumps(summary), ""
                    )
                if len(command) > 2 and command[1].endswith("storyclaw_install.py"):
                    link = Path(command[command.index("--project-engine-link") + 1])
                    view = Path(command[command.index("--project-view-root") + 1])
                    view.mkdir(parents=True, exist_ok=True)
                    runtime = Path(command[command.index("--runtime-root") + 1])
                    for name in ("nalu", "tasks"):
                        backing = runtime / "runtime/storyclaw_storage/workflow" / name
                        backing.mkdir(parents=True, exist_ok=True)
                        target = view / "workflow" / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.symlink(backing, target)
                    link.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(view, link)
                    venv = runtime / "runtime/storyclaw_host/venv"
                    python = venv / "bin/python"
                    python.parent.mkdir(parents=True)
                    python.write_text("#!/bin/sh\n")
                    python.chmod(0o755)
                    selector = runtime / "runtime/storyclaw_host/current-venv"
                    os.symlink(venv, selector)
                    baseline = runtime / "runtime/storyclaw_host/current-release.json"
                    baseline.write_text(json.dumps({"status": "PASS"}))
                    install_root = runtime / "runtime/receipts/storyclaw_host_install"
                    install_root.mkdir(parents=True)
                    install_receipt = install_root / "install.json"
                    install_receipt.write_text(json.dumps({
                        "schema": bootstrap.INSTALL_RECEIPT_SCHEMA,
                        "status": "PASS",
                        "release_baseline": {"status": "PASS"},
                    }))
                    report = {
                        "status": "PASS",
                        "release_baseline": {"status": "PASS"},
                        "receipt": {
                            "path": str(install_receipt),
                            "sha256": hashlib.sha256(
                                install_receipt.read_bytes()
                            ).hexdigest(),
                        },
                    }
                    return subprocess.CompletedProcess(command, 0, json.dumps(report), "")
                if len(command) > 2 and command[1].endswith(
                    "storyclaw_nalu_runtime.py"
                ):
                    if preflight_failure["enabled"]:
                        return subprocess.CompletedProcess(
                            command,
                            2,
                            json.dumps({
                                "schema": bootstrap.PREFLIGHT_SCHEMA,
                                "status": "BLOCKED",
                            }),
                            "preflight blocked",
                        )
                    runtime = Path(kwargs["env"]["NALU_RUNTIME_ROOT"]).resolve()
                    engine = Path(kwargs["env"]["NALU_ENGINE_ROOT"]).resolve()
                    checks = {
                        "engine_root": {"status": "PASS"},
                        "paid_lock": {
                            "status": "PASS",
                            "paid_requests_enabled": False,
                            "api_key_present": False,
                        },
                    }
                    report = {
                        "schema": bootstrap.PREFLIGHT_SCHEMA,
                        "status": "PASS",
                        "engine_commit": commit,
                        "engine_root": str(engine),
                        "private_runtime_root": str(runtime),
                        "project_id": "test-project",
                        "series_scope_id": "TEST-SCOPE",
                        "checks": checks,
                        "failures": [],
                    }
                    return subprocess.CompletedProcess(
                        command, 0, json.dumps(report), ""
                    )
                return subprocess.CompletedProcess(command, 1, "", "unexpected command")

            with mock.patch.dict(
                os.environ,
                {
                    "GIGGLE_API_KEY": "must-not-pass",
                    "GIGGLEPRO_API_KEY": "must-not-pass",
                    "OPENAI_API_KEY": "must-not-pass",
                },
            ):
                with mock.patch.object(
                    bootstrap, "_select_dependency_binding", return_value=selected
                ):
                    result = bootstrap.bootstrap_project(
                        workspace,
                        project_home,
                        title="Test drama",
                        project_id="test-project",
                        runner=runner,
                        fetcher=lambda url, _size: (
                            archive if "qingshan-storyclaw-workflow" in url
                            else dependency_assets[url]
                        ),
                    )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["provider_posts"], 0)
            self.assertEqual(
                result["registry_clean_install_smoke_status"], "SNAPSHOTS_PASS"
            )
            intake = next(row for row in calls if len(row) > 2 and row[1].endswith("storyclaw_project_intake.py"))
            install = next(row for row in calls if len(row) > 2 and row[1].endswith("storyclaw_install.py"))
            self.assertEqual(
                intake[intake.index("--engine-root") + 1],
                install[install.index("--project-engine-link") + 1],
            )
            self.assertIn("--talenthub-release-manifest", install)
            self.assertIn("--dependency-manifest", install)
            self.assertIn("--dependency-archive", install)
            self.assertEqual(result["dependency_profile_id"], selected["profile_id"])
            self.assertTrue(Path(result["receipt"]).is_file())
            self.assertTrue(Path(result["transactions_before_snapshot"]).is_file())
            self.assertTrue(Path(result["transactions_after_snapshot"]).is_file())
            before_call = next(
                index for index, row in enumerate(calls)
                if "snapshot" in row and row[row.index("--label") + 1] == "before"
            )
            install_call = calls.index(install)
            preflight_call = next(
                index for index, row in enumerate(calls)
                if len(row) > 2 and row[1].endswith("storyclaw_nalu_runtime.py")
            )
            after_call = next(
                index for index, row in enumerate(calls)
                if "snapshot" in row and row[row.index("--label") + 1] == "after"
            )
            self.assertLess(before_call, install_call)
            self.assertLess(install_call, preflight_call)
            self.assertLess(preflight_call, after_call)
            self.assertTrue(child_environments)
            for environment in child_environments:
                for name in bootstrap.PROVIDER_CREDENTIAL_NAMES:
                    self.assertNotIn(name, environment)
                self.assertEqual(environment["QINGSHAN_PAID_REQUESTS_ENABLED"], "0")
                self.assertEqual(environment["QINGSHAN_BOOTSTRAP_NO_PROVIDER_POSTS"], "1")
            transaction_root = Path(result["private_runtime_root"]) / "workflow/tasks/giggle_submit_transactions"
            self.assertFalse(transaction_root.exists())

            # A real preflight failure must leave only provisional evidence;
            # no overall PASS bootstrap receipt or after snapshot may survive.
            preflight_failure["enabled"] = True
            failed_home = root / "failed-project-home"
            with self.assertRaisesRegex(
                bootstrap.BootstrapBlocked, "COMMAND_FAILED"
            ):
                with mock.patch.object(
                    bootstrap, "_select_dependency_binding", return_value=selected
                ):
                    bootstrap.bootstrap_project(
                        workspace,
                        failed_home,
                        title="Failed drama",
                        project_id="test-project",
                        runner=runner,
                        fetcher=lambda url, _size: (
                            archive if "qingshan-storyclaw-workflow" in url
                            else dependency_assets[url]
                        ),
                    )
            failed_runtime = failed_home / "projects/test-project"
            pending = json.loads((
                failed_runtime / bootstrap.BOOTSTRAP_RECEIPT_RELATIVE
            ).read_text())
            self.assertEqual(pending["status"], "PREFLIGHT_PENDING")
            self.assertFalse(
                (failed_runtime / bootstrap.SMOKE_PREFLIGHT_RELATIVE).exists()
            )
            self.assertFalse((
                failed_runtime
                / bootstrap.SMOKE_RECEIPT_ROOT_RELATIVE
                / "transactions-after.json"
            ).exists())

            install_calls_before_preflight_retry = sum(
                1 for row in calls
                if len(row) > 2 and row[1].endswith("storyclaw_install.py")
            )
            preflight_failure["enabled"] = False
            with mock.patch.object(
                bootstrap, "_select_dependency_binding", return_value=selected
            ):
                preflight_retried = bootstrap.bootstrap_project(
                    workspace,
                    failed_home,
                    title="Failed drama",
                    project_id="test-project",
                    runner=runner,
                    fetcher=lambda url, _size: (
                        archive if "qingshan-storyclaw-workflow" in url
                        else dependency_assets[url]
                    ),
                )
            self.assertEqual(preflight_retried["status"], "PASS")
            self.assertEqual(
                preflight_retried["registry_clean_install_smoke_status"],
                "SNAPSHOTS_PASS",
            )
            self.assertEqual(
                install_calls_before_preflight_retry,
                sum(
                    1 for row in calls
                    if len(row) > 2 and row[1].endswith("storyclaw_install.py")
                ),
            )

            after_snapshot_failure["enabled"] = True
            retry_home = root / "retry-project-home"
            with self.assertRaisesRegex(
                bootstrap.BootstrapBlocked, "COMMAND_FAILED"
            ):
                with mock.patch.object(
                    bootstrap, "_select_dependency_binding", return_value=selected
                ):
                    bootstrap.bootstrap_project(
                        workspace,
                        retry_home,
                        title="Retry drama",
                        project_id="test-project",
                        runner=runner,
                        fetcher=lambda url, _size: (
                            archive if "qingshan-storyclaw-workflow" in url
                            else dependency_assets[url]
                        ),
                    )
            retry_runtime = retry_home / "projects/test-project"
            provisional_path = retry_runtime / bootstrap.BOOTSTRAP_RECEIPT_RELATIVE
            provisional = json.loads(provisional_path.read_text())
            self.assertEqual(
                provisional["status"], "PREFLIGHT_PASS_PENDING_SNAPSHOT"
            )
            self.assertNotEqual(provisional["status"], "PASS")

            install_calls_before_retry = sum(
                1 for row in calls
                if len(row) > 2 and row[1].endswith("storyclaw_install.py")
            )
            preflight_calls_before_retry = sum(
                1 for row in calls
                if len(row) > 2 and row[1].endswith("storyclaw_nalu_runtime.py")
            )
            after_snapshot_failure["enabled"] = False
            with mock.patch.object(
                bootstrap, "_select_dependency_binding", return_value=selected
            ):
                retried = bootstrap.bootstrap_project(
                    workspace,
                    retry_home,
                    title="Retry drama",
                    project_id="test-project",
                    runner=runner,
                    fetcher=lambda url, _size: (
                        archive if "qingshan-storyclaw-workflow" in url
                        else dependency_assets[url]
                    ),
                )
            self.assertEqual(retried["status"], "PASS")
            self.assertEqual(
                retried["registry_clean_install_smoke_status"], "SNAPSHOTS_PASS"
            )
            self.assertEqual(
                install_calls_before_retry,
                sum(
                    1 for row in calls
                    if len(row) > 2 and row[1].endswith("storyclaw_install.py")
                ),
            )
            self.assertEqual(
                preflight_calls_before_retry,
                sum(
                    1 for row in calls
                    if len(row) > 2 and row[1].endswith("storyclaw_nalu_runtime.py")
                ),
            )

    def test_dependency_profile_selection_is_exact_and_has_no_fallback(self):
        rows, _assets = self._dependency_fixture("v1.2.3")
        release = {"dependency_profile_bindings": {
            str(row["profile_id"]): row for row in rows
        }}
        supported = {
            "system": "Linux",
            "machine": "x86_64",
            "implementation": "cpython",
            "libc": "glibc",
            "libc_version": "2.31",
            "python_major": 3,
            "python_minor": 10,
        }
        with mock.patch.object(bootstrap.platform, "system", return_value=supported["system"]), \
             mock.patch.object(bootstrap.platform, "machine", return_value=supported["machine"]), \
             mock.patch.object(bootstrap.platform, "python_implementation", return_value="CPython"), \
             mock.patch.object(bootstrap.platform, "libc_ver", return_value=("glibc", "2.31")), \
             mock.patch.object(bootstrap.sys, "version_info", types.SimpleNamespace(major=3, minor=10)):
            chosen = bootstrap._select_dependency_binding(release)
        self.assertEqual(
            chosen["profile_id"], "storyclaw-linux-x86_64-cpython310-cpu-v1"
        )
        with mock.patch.object(bootstrap.platform, "system", return_value="Darwin"):
            with self.assertRaisesRegex(
                bootstrap.BootstrapBlocked, "DEPENDENCY_PLATFORM_UNSUPPORTED"
            ):
                bootstrap._select_dependency_binding(release)

    def test_dependency_binding_tamper_blocks_before_asset_download(self):
        archive = self._archive("9" * 40)
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self._workspace(Path(temporary), archive, "9" * 40)
            manifest_path = workspace / "skills/qingshan-nalu/RELEASE_MANIFEST.json"
            payload = json.loads(manifest_path.read_text())
            payload["dependency_profiles"][0]["archive_url"] = "https://example.invalid/bundle"
            manifest_path.write_text(json.dumps(payload) + "\n")
            with self.assertRaisesRegex(
                bootstrap.BootstrapBlocked, "BINDING_MISMATCH"
            ):
                bootstrap.load_installed_release(workspace)

    def test_tampered_installed_prompt_blocks_before_network(self):
        archive = self._archive("b" * 40)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root, archive, "b" * 40)
            (workspace / "AGENTS.md").write_text("tampered\n")
            with self.assertRaisesRegex(bootstrap.BootstrapBlocked, "BINDING_MISMATCH"):
                bootstrap.load_installed_release(workspace)

    def test_bound_file_parent_symlink_blocks(self):
        archive = self._archive("c" * 40)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root, archive, "c" * 40)
            outside = root / "outside"
            outside.mkdir()
            skill = workspace / "skills/qingshan-nalu"
            moved = outside / "qingshan-nalu"
            skill.rename(moved)
            os.symlink(moved, skill)
            with self.assertRaisesRegex(bootstrap.BootstrapBlocked, "SYMLINK"):
                bootstrap.load_installed_release(workspace)

    def test_project_internal_directory_symlink_blocks_before_download(self):
        commit = "7" * 40
        archive = self._archive(commit)
        cases = ("engine", "engine/releases", "bootstrap-cache", "projects")
        for relative in cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                workspace = self._workspace(root, archive, commit)
                project = root / "project"
                project.mkdir()
                link = project / relative
                link.parent.mkdir(parents=True, exist_ok=True)
                outside = root / ("outside-" + relative.replace("/", "-"))
                outside.mkdir()
                os.symlink(outside, link)
                with self.assertRaisesRegex(bootstrap.BootstrapBlocked, "PROJECT_DIRECTORY_UNSAFE"):
                    bootstrap.bootstrap_project(
                        workspace,
                        project,
                        runner=lambda *_args, **_kwargs: self.fail("runner must not execute"),
                        fetcher=lambda *_args, **_kwargs: self.fail("network must not execute"),
                    )

    def test_existing_identical_release_view_is_idempotent(self):
        commit = "d" * 40
        archive = self._archive(commit)
        with tempfile.TemporaryDirectory() as temporary:
            project_home = Path(temporary) / "project"
            destination = project_home / "engine/releases/v1.2.3"
            bootstrap._extract_verified_archive(
                archive, destination, release_tag="v1.2.3", git_commit=commit
            )
            first = bootstrap._tree_facts(destination)
            private = project_home / "projects/test/runtime/storyclaw_storage/workflow"
            for relative in bootstrap.RUNTIME_LINK_PATHS:
                target = destination / relative
                backing = private / Path(relative).name
                backing.mkdir(parents=True, exist_ok=True)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(backing, target)
            for path in sorted(destination.rglob("*"), reverse=True):
                if not path.is_symlink():
                    os.chmod(path, path.stat().st_mode & ~0o222)
            bootstrap._extract_verified_archive(
                archive, destination, release_tag="v1.2.3", git_commit=commit
            )
            self.assertTrue((destination / "workflow/nalu").is_symlink())
            self.assertTrue((destination / "workflow/tasks").is_symlink())
            self.assertTrue(first)

    def test_existing_tampered_or_extra_release_view_blocks(self):
        commit = "e" * 40
        archive = self._archive(commit)
        for mutation in ("tampered", "extra"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                destination = Path(temporary) / "release"
                bootstrap._extract_verified_archive(
                    archive, destination, release_tag="v1.2.3", git_commit=commit
                )
                if mutation == "tampered":
                    (destination / "tools/storyclaw_install.py").write_text("malicious\n")
                else:
                    (destination / "tools/extra.py").write_text("malicious\n")
                with self.assertRaisesRegex(
                    bootstrap.BootstrapBlocked, "EXISTING_VIEW_MISMATCH"
                ):
                    bootstrap._extract_verified_archive(
                        archive, destination, release_tag="v1.2.3", git_commit=commit
                    )

    def test_existing_release_view_symlink_blocks(self):
        commit = "f" * 40
        archive = self._archive(commit)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "release"
            bootstrap._extract_verified_archive(
                archive, destination, release_tag="v1.2.3", git_commit=commit
            )
            target = destination / "tools/storyclaw_install.py"
            target.unlink()
            os.symlink(root / "outside.py", target)
            with self.assertRaisesRegex(bootstrap.BootstrapBlocked, "SYMLINK"):
                bootstrap._extract_verified_archive(
                    archive, destination, release_tag="v1.2.3", git_commit=commit
                )

    def test_archive_rejects_unsafe_paths_links_specials_duplicates_and_truncation(self):
        prefix = "qingshan-storyclaw-workflow/"
        cases: list[tuple[str, list[tuple[tarfile.TarInfo, bytes | None]]]] = []
        absolute = tarfile.TarInfo("/absolute")
        absolute.size = 0
        cases.append(("PREFIX_INVALID", [(absolute, b"")]))
        traversal = tarfile.TarInfo(prefix + "../escape")
        traversal.size = 0
        cases.append(("PATH_INVALID", [(traversal, b"")]))
        for label, kind in (
            ("symlink", tarfile.SYMTYPE),
            ("hardlink", tarfile.LNKTYPE),
            ("device", tarfile.CHRTYPE),
            ("fifo", tarfile.FIFOTYPE),
        ):
            info = tarfile.TarInfo(prefix + label)
            info.type = kind
            info.linkname = "target"
            cases.append(("SPECIAL_MEMBER", [(info, None)]))
        duplicate_a = tarfile.TarInfo(prefix + "same")
        duplicate_a.size = 1
        duplicate_b = tarfile.TarInfo(prefix + "same")
        duplicate_b.size = 1
        cases.append(("DUPLICATE_MEMBER", [(duplicate_a, b"a"), (duplicate_b, b"b")]))

        for expected, entries in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temporary:
                archive = self._custom_archive(entries)
                with self.assertRaisesRegex(bootstrap.BootstrapBlocked, expected):
                    bootstrap._extract_verified_archive(
                        archive,
                        Path(temporary) / "release",
                        release_tag="v1.2.3",
                        git_commit="1" * 40,
                    )

        valid = self._archive("2" * 40)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(bootstrap.BootstrapBlocked, "SOURCE_ARCHIVE_INVALID"):
                bootstrap._extract_verified_archive(
                    valid[: len(valid) // 2],
                    Path(temporary) / "release",
                    release_tag="v1.2.3",
                    git_commit="2" * 40,
                )

    def test_archive_member_count_and_manifest_binding_fail_closed(self):
        prefix = "qingshan-storyclaw-workflow/"
        many = []
        for index in range(20000):
            info = tarfile.TarInfo(prefix + f"d{index}")
            info.type = tarfile.DIRTYPE
            many.append((info, None))
        archive = self._custom_archive(many)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(bootstrap.BootstrapBlocked, "TOO_MANY_MEMBERS"):
                bootstrap._extract_verified_archive(
                    archive,
                    Path(temporary) / "release",
                    release_tag="v1.2.3",
                    git_commit="3" * 40,
                )

        wrong_manifest = self._archive("4" * 40, tag="v9")
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(bootstrap.BootstrapBlocked, "RELEASE_BINDING_MISMATCH"):
                bootstrap._extract_verified_archive(
                    wrong_manifest,
                    Path(temporary) / "release",
                    release_tag="v1.2.3",
                    git_commit="4" * 40,
                )


if __name__ == "__main__":
    unittest.main()
