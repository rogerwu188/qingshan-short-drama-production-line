"""Host-install and immutable engine-upgrade regression tests."""
from __future__ import annotations

import gzip
import fcntl
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import storyclaw_install as installer
from tools import storyclaw_release_surface as release_surface


class StoryClawInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.engine = self.root / "engine"
        self.runtime = self.root / "private-runtime"
        self.engine.mkdir()
        self.runtime.mkdir(mode=0o700)
        self._make_engine_tree(self.engine)
        self._git("init")
        self._git("config", "user.email", "test@example.invalid")
        self._git("config", "user.name", "StoryClaw Test")
        self._git("add", ".")
        self._git("commit", "-m", "fixture")
        self._git("tag", "v1.0.0")
        self.commit = self._git("rev-parse", "HEAD").stdout.strip()

    def tearDown(self) -> None:
        # A seal intentionally removes directory write bits.  Restore only the
        # temporary fixture so TemporaryDirectory can clean it up.
        for base in (self.engine, self.root / "releases"):
            if not base.exists():
                continue
            for current, directories, _files in os.walk(base, topdown=True, followlinks=False):
                path = Path(current)
                if not path.is_symlink():
                    os.chmod(path, stat.S_IMODE(path.stat().st_mode) | 0o700)
                for name in directories:
                    child = path / name
                    if not child.is_symlink():
                        os.chmod(child, stat.S_IMODE(child.stat().st_mode) | 0o700)
        self.temporary.cleanup()

    @staticmethod
    def _make_engine_tree(engine: Path) -> None:
        files = {
            "pyproject.toml": "[project]\nname='fixture'\nversion='1.0.0'\n",
            "lines/nalu/runtime/tools/nalu_pipeline.py": "PIPELINE_VERSION = 1\n",
            "tools/storyclaw_nalu_runtime.py": "print('fixture adapter')\n",
            "tools/storyclaw_install.py": "INSTALLER_FIXTURE = 1\n",
            "tools/storyclaw_guided_onboarding.py": "ONBOARDING_FIXTURE = 1\n",
            "tools/storyclaw_project_intake.py": "INTAKE_FIXTURE = 1\n",
            "AGENTS.md": "portable agent contract\n",
            "agent_factory/AGENTS.md": "factory contract\n",
            "agent_factory/storyclaw_portable/AGENTS.md": "portable brain\n",
            "agent_factory/storyclaw_portable/SOUL.md": "portable soul\n",
            "agent_factory/storyclaw_portable/USER.md": "portable user\n",
            "skills/qingshan-nalu/SKILL.md": "portable skill\n",
            "workflow/KEEP": "tracked workflow parent\n",
            ".gitignore": "/workflow/nalu\n/workflow/tasks\n",
        }
        for relative, content in files.items():
            path = engine / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.engine), *args],
            check=True,
            text=True,
            capture_output=True,
        )

    @staticmethod
    def _dependency_bindings(tag: str) -> list[dict[str, object]]:
        rows = []
        for index, profile in enumerate(installer._dependency_bundle.SUPPORTED_PROFILES, 1):
            manifest_name = installer._dependency_bundle.dependency_manifest_filename(
                tag, profile.profile_id
            )
            archive_name = installer._dependency_bundle.dependency_archive_filename(
                tag, profile.profile_id
            )
            rows.append({
                "profile_id": profile.profile_id,
                "manifest_url": installer._dependency_bundle.github_asset_url(tag, manifest_name),
                "manifest_size_bytes": 100 + index,
                "manifest_sha256": f"{index}" * 64,
                "archive_url": installer._dependency_bundle.github_asset_url(tag, archive_name),
                "archive_size_bytes": 1000 + index,
                "archive_sha256": f"{index + 2}" * 64,
            })
        return rows

    def _install(self, **overrides):
        values = {
            "release_tag": "v1.0.0",
            "expected_commit": self.commit,
        }
        # Most focused tests below exercise direct wiring mechanics.  They
        # explicitly model a per-project mount namespace; production host
        # installs use the per-project worktree test further below.
        if "project_view_root" not in overrides:
            values["isolated_mount_namespace"] = True
        values.update(overrides)
        return installer.install_host(self.engine, self.runtime, **values)

    def test_install_is_exact_private_idempotent_and_network_free_by_default(self):
        before = installer.inspect_host(
            self.engine, self.runtime, release_tag="v1.0.0"
        )
        self.assertFalse(before["mutations_performed"])
        self.assertTrue(all(row["state"] == "BACKING_ABSENT_OR_INVALID" for row in before["wiring"]))
        self.assertFalse((self.runtime / "runtime").exists())

        result = self._install()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["isolation_mode"], "ISOLATED_MOUNT_NAMESPACE")
        self.assertEqual(result["engine"]["head_commit"], self.commit)
        self.assertEqual(result["dependencies"]["status"], "NOT_INSTALLED")
        self.assertFalse(result["dependencies"]["network_used"])
        for _name, target_relative, backing_relative in installer.WIRE_SPECS:
            target = self.engine / target_relative
            backing = self.runtime / backing_relative
            self.assertTrue(target.is_symlink())
            self.assertEqual(target.resolve(), backing.resolve())
            self.assertTrue(os.access(backing, os.W_OK))
        receipt = Path(result["receipt"]["path"])
        self.assertTrue(receipt.resolve().is_relative_to(self.runtime.resolve()))
        self.assertEqual(hashlib.sha256(receipt.read_bytes()).hexdigest(), result["receipt"]["sha256"])
        self.assertEqual(json.loads(receipt.read_text())["source_or_media_paths_touched"], [])
        self.assertEqual(
            json.loads(receipt.read_text())["isolation_mode"],
            "ISOLATED_MOUNT_NAMESPACE",
        )
        self.assertFalse((self.runtime / installer.DEFAULT_VENV_RELATIVE).exists())

        again = self._install()
        self.assertEqual(
            {row["action"] for row in again["actions"]}, {"ALREADY_WIRED"}
        )
        verified = installer.verify_host(
            self.engine,
            self.runtime,
            release_tag="v1.0.0",
            expected_commit=self.commit,
        )
        self.assertEqual(verified["status"], "PASS")
        for row in verified["wiring"]:
            self.assertEqual(row["storage_probe"]["flock_nonblocking"], "PASS")

    def test_empty_targets_are_replaced_but_nonempty_or_wrong_links_are_never_overwritten(self):
        for _name, target_relative, _backing_relative in installer.WIRE_SPECS:
            (self.engine / target_relative).mkdir(parents=True)
        self._install()
        self.assertTrue((self.engine / "workflow/nalu").is_symlink())

        # Fresh fixture for the destructive-conflict cases.
        other = self.root / "other-engine"
        other.mkdir()
        self._make_engine_tree(other)
        subprocess.run(["git", "init", str(other)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(other), "config", "user.email", "x@y.invalid"], check=True)
        subprocess.run(["git", "-C", str(other), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(other), "add", "."], check=True)
        subprocess.run(["git", "-C", str(other), "commit", "-m", "fixture"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(other), "tag", "v1.0.0"], check=True)
        (other / "workflow/nalu").mkdir()
        sentinel = other / "workflow/nalu/DO_NOT_DELETE.txt"
        sentinel.write_text("private existing data")
        with self.assertRaisesRegex(installer.InstallBlocked, "ENGINE_TARGET_NOT_SAFE_TO_WIRE"):
            installer.install_host(
                other,
                self.runtime,
                release_tag="v1.0.0",
                isolated_mount_namespace=True,
            )
        self.assertEqual(sentinel.read_text(), "private existing data")

        sentinel.unlink()
        (other / "workflow/nalu").rmdir()
        wrong = self.root / "wrong"
        wrong.mkdir()
        os.symlink(wrong, other / "workflow/nalu")
        with self.assertRaisesRegex(installer.InstallBlocked, "ENGINE_TARGET_NOT_SAFE_TO_WIRE"):
            installer.install_host(
                other,
                self.runtime,
                release_tag="v1.0.0",
                isolated_mount_namespace=True,
            )
        self.assertEqual((other / "workflow/nalu").resolve(), wrong.resolve())

    def test_dirty_wrong_tag_and_runtime_overlap_fail_closed(self):
        (self.engine / "pyproject.toml").write_text("dirty\n")
        with self.assertRaisesRegex(installer.InstallBlocked, "ENGINE_WORKTREE_NOT_CLEAN"):
            self._install()
        self._git("checkout", "--", "pyproject.toml")
        with self.assertRaisesRegex(installer.InstallBlocked, "RELEASE_TAG_NOT_FOUND"):
            installer.install_host(
                self.engine,
                self.runtime,
                release_tag="v9",
                isolated_mount_namespace=True,
            )
        with self.assertRaisesRegex(installer.InstallBlocked, "ENGINE_COMMIT_MISMATCH"):
            installer.install_host(
                self.engine,
                self.runtime,
                release_tag="v1.0.0",
                expected_commit="0" * 40,
                isolated_mount_namespace=True,
            )
        nested = self.engine / "private"
        nested.mkdir()
        with self.assertRaisesRegex(installer.InstallBlocked, "ENGINE_RUNTIME_OVERLAP"):
            installer.install_host(
                self.engine,
                nested,
                release_tag="v1.0.0",
                isolated_mount_namespace=True,
            )

    def test_default_install_refuses_to_wire_shared_canonical_engine(self):
        with self.assertRaisesRegex(installer.InstallBlocked, "PROJECT_VIEW_ROOT_REQUIRED"):
            installer.install_host(
                self.engine,
                self.runtime,
                release_tag="v1.0.0",
                expected_commit=self.commit,
            )
        self.assertFalse(os.path.lexists(self.engine / "workflow/nalu"))
        self.assertFalse(os.path.lexists(self.engine / "workflow/tasks"))
        self.assertFalse((self.runtime / "runtime").exists())

    def test_cli_default_install_fails_closed_without_project_view(self):
        command = [
            sys.executable,
            str(Path(installer.__file__)),
            "install",
            "--engine-root", str(self.engine),
            "--runtime-root", str(self.runtime),
            "--release-tag", "v1.0.0",
            "--expected-commit", self.commit,
        ]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["code"], "PROJECT_VIEW_ROOT_REQUIRED")
        self.assertFalse(os.path.lexists(self.engine / "workflow/nalu"))
        self.assertFalse((self.runtime / "runtime").exists())

    def test_dependency_install_is_explicit_private_and_strips_provider_key(self):
        calls = []
        profile = installer._dependency_bundle.PROFILE_BY_ID[
            "storyclaw-linux-x86_64-cpython311-cpu-v1"
        ]
        manifest_path = self.root / "dependencies.json"
        manifest_path.write_text("{}\n")
        archive_path = self.root / "dependencies.tar.gz"
        archive_path.write_bytes(b"bound offline bundle")
        manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        archive_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        archive_url = installer._dependency_bundle.github_asset_url(
            "v1.0.0",
            installer._dependency_bundle.dependency_archive_filename(
                "v1.0.0", profile.profile_id
            ),
        )
        binding = {
            "profile_id": profile.profile_id,
            "manifest_size_bytes": manifest_path.stat().st_size,
            "manifest_sha256": manifest_sha,
            "archive_url": archive_url,
            "archive_size_bytes": archive_path.stat().st_size,
            "archive_sha256": archive_sha,
        }
        validated_manifest = {
            "profile": {"id": profile.profile_id},
            "archive": {
                "url": archive_url,
                "size_bytes": archive_path.stat().st_size,
                "sha256": archive_sha,
            },
            "lock": {"sha256": "a" * 64},
        }

        def runner(command, **kwargs):
            calls.append((list(command), kwargs))
            if command[1:3] == ["-m", "venv"]:
                python = Path(command[-1]) / "bin/python"
                python.parent.mkdir(parents=True)
                python.write_text("fixture")
            if command[-3:] == ["pip", "list", "--format=json"]:
                return subprocess.CompletedProcess(
                    command, 0, stdout='[{"name":"pip","version":"25.3"}]', stderr=""
                )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        extracted_root = self.root / "extracted"
        (extracted_root / "wheels").mkdir(parents=True)
        (extracted_root / "requirements.lock").write_text("pip==25.3 --hash=sha256:x\n")
        facts = self._dependency_facts()
        with (
            mock.patch.dict(os.environ, {"GIGGLE_API_KEY": "must-not-pass"}),
            mock.patch.object(installer._dependency_bundle, "probe_interpreter", return_value=facts),
            mock.patch.object(installer._dependency_bundle, "validate_manifest", return_value=validated_manifest),
            mock.patch.object(
                installer._dependency_bundle,
                "extract_verified_bundle",
                return_value={
                    "wheelhouse": str(extracted_root / "wheels"),
                    "lock": str(extracted_root / "requirements.lock"),
                },
            ),
        ):
            report = installer.install_dependencies(
                self.engine,
                self.runtime,
                runner=runner,
                dependency_manifest=manifest_path,
                dependency_archive=archive_path,
                release_tag="v1.0.0",
                git_commit=self.commit,
                release_sequence=1,
                expected_binding={profile.profile_id: binding},
            )
        self.assertEqual(report["status"], "INSTALLED")
        pip_calls = [row for row in calls if row[0][1:4] == ["-m", "pip", "install"]]
        self.assertEqual(len(pip_calls), 2)
        pip_environment = pip_calls[0][1]["env"]
        self.assertNotIn("GIGGLE_API_KEY", pip_environment)
        self.assertEqual(pip_environment["PIP_NO_INDEX"], "1")
        self.assertEqual(pip_environment["PIP_REQUIRE_HASHES"], "1")
        self.assertIn("--require-hashes", pip_calls[0][0])
        self.assertIn("--no-deps", pip_calls[1][0])
        self.assertIn("--no-index", pip_calls[1][0])
        self.assertIn("--no-build-isolation", pip_calls[1][0])
        self.assertEqual(pip_calls[1][1]["env"]["PIP_REQUIRE_HASHES"], "0")
        self.assertNotIn("GIGGLE_API_KEY", pip_calls[1][1]["env"])
        self.assertFalse(report["network_used"])
        self.assertTrue(Path(report["venv"]).resolve().is_relative_to(self.runtime.resolve()))
        # Exercise real pip's directory/hash interaction without installing
        # anything or needing a downloaded build backend.
        project = self.root / "local-engine-regression"
        project.mkdir()
        (project / "pyproject.toml").write_text(
            '[build-system]\nrequires=[]\nbuild-backend="backend"\nbackend-path=["."]\n'
        )
        (project / "backend.py").write_text(
            'from pathlib import Path\n'
            'def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):\n'
            '    name="storyclaw_fixture-0.0.1.dist-info"\n'
            '    root=Path(metadata_directory)/name\n'
            '    root.mkdir()\n'
            '    (root/"METADATA").write_text("Metadata-Version: 2.1\\nName: storyclaw-fixture\\nVersion: 0.0.1\\n")\n'
            '    return name\n'
        )
        command = [sys.executable, "-m", "pip", "install", "--dry-run",
                   "--no-index", "--no-deps", "--no-build-isolation", str(project)]
        old = subprocess.run(command, env=pip_environment, capture_output=True, text=True)
        self.assertNotEqual(old.returncode, 0)
        self.assertIn("Can't verify hashes", old.stderr)
        fixed = subprocess.run(command, env=pip_calls[1][1]["env"], capture_output=True, text=True)
        self.assertEqual(fixed.returncode, 0, fixed.stderr)
        with self.assertRaisesRegex(installer.InstallBlocked, "VENV_MUST_BE_PRIVATE_RUNTIME_PATH"):
            installer.install_dependencies(
                self.engine,
                self.runtime,
                venv_path=self.root / "outside/venv",
                runner=runner,
                dependency_manifest=manifest_path,
                dependency_archive=archive_path,
                release_tag="v1.0.0",
                git_commit=self.commit,
                release_sequence=1,
                expected_binding={profile.profile_id: binding},
            )
        self.assertFalse((self.root / "outside").exists())

    @staticmethod
    def _dependency_facts() -> dict[str, object]:
        return {
            "schema": installer._dependency_bundle.PROFILE_SCHEMA,
            "implementation": "cpython",
            "python_major": 3,
            "python_minor": 11,
            "system": "Linux",
            "machine": "x86_64",
            "libc": "glibc",
            "libc_version": "2.35",
        }

    def test_host_install_creates_project_local_stable_venv_selector(self):
        private_venv = self.runtime / "runtime/storyclaw_host/venvs/v1"

        def fake_dependencies(engine, runtime, *, venv_path, python_executable, **kwargs):
            self.assertEqual(engine, self.engine.resolve())
            self.assertEqual(runtime, self.runtime.resolve())
            python = Path(venv_path) / "bin/python"
            python.parent.mkdir(parents=True)
            python.write_text("private python")
            return {
                "requested": True,
                "status": "INSTALLED",
                "venv": str(venv_path),
                "python": str(python),
                "network_used": False,
            }

        package = {
            "release_sequence": 1,
            "release_tag": "v1.0.0",
            "git_commit": self.commit,
            "dependency_profile_bindings": {
                row["profile_id"]: row for row in self._dependency_bindings("v1.0.0")
            },
            "validation_receipt_sha256": "a" * 64,
            "source_archive_size_bytes": 1,
            "source_archive_sha256": "b" * 64,
            "sha256": "c" * 64,
            "status": "PASS",
        }
        dummy_manifest = self.root / "skills/qingshan-nalu/RELEASE_MANIFEST.json"
        dummy_manifest.parent.mkdir(parents=True)
        dummy_manifest.write_text("{}\n")
        with mock.patch.object(
            installer, "_validate_bootstrap_talenthub_manifest", return_value=package
        ):
            result = self._install(
                install_deps=True,
                venv_path=private_venv,
                dependency_installer=fake_dependencies,
                talenthub_release_manifest=dummy_manifest,
            )
        selector = self.runtime / installer.VENV_SELECTOR_RELATIVE
        self.assertTrue(selector.is_symlink())
        self.assertEqual(selector.resolve(), private_venv.resolve())
        self.assertEqual(
            result["dependencies"]["stable_python"],
            str(self.runtime.resolve() / installer.VENV_SELECTOR_RELATIVE / "bin/python"),
        )
        self.assertEqual(result["venv_selector"]["status"], "PASS")
        inspected = installer.inspect_host(
            self.engine,
            self.runtime,
            release_tag="v1.0.0",
            venv_path=private_venv,
        )
        self.assertEqual(inspected["venv_selector"]["target"], str(private_venv.resolve()))
        verified = installer.verify_host(
            self.engine,
            self.runtime,
            release_tag="v1.0.0",
            expected_commit=self.commit,
            venv_path=private_venv,
        )
        self.assertEqual(verified["venv_selector"]["status"], "PASS")

    def test_published_install_records_trusted_release_sequence_baseline(self):
        workspace = self.root / "talenthub-agent"
        nested = workspace / "skills" / installer.SKILL_NAME
        nested.mkdir(parents=True)
        (workspace / "manifest.json").write_text(json.dumps({
            "id": installer.AGENT_ID,
            "skills": [f"https://example.invalid/repo@{installer.SKILL_NAME}"],
        }) + "\n")
        for relative in installer.INSTALLED_TALENTHUB_BOUND_FILES:
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"installed {relative}\n", encoding="utf-8")
        bindings = {
            relative: {
                "size_bytes": (workspace / relative).stat().st_size,
                "sha256": hashlib.sha256((workspace / relative).read_bytes()).hexdigest(),
            }
            for relative in installer.INSTALLED_TALENTHUB_BOUND_FILES
        }
        release = {
            "schema": installer.TALENTHUB_RELEASE_SCHEMA,
            "agent_id": installer.AGENT_ID,
            "skill": installer.SKILL_NAME,
            "release_tag": "v1.0.0",
            "git_commit": self.commit,
            "origin_tag_commit": self.commit,
            "release_sequence": 101,
            "source_archive_size_bytes": 123,
            "source_archive_sha256": "b" * 64,
            "release_signing_key_sha256": installer.RELEASE_SIGNING_PUBLIC_KEY_SHA256,
            "validation_receipt_status": "PASS",
            "validation_receipt_sha256": "a" * 64,
            "public_runtime_only": True,
            "private_validation_contents_included": False,
            "dependency_profiles_action": "REPLACE_WITH_RELEASE_BUNDLES",
            "dependency_profiles": self._dependency_bindings("v1.0.0"),
            "installed_file_bindings": bindings,
        }
        raw = json.dumps(release, sort_keys=True).encode() + b"\n"
        top = workspace / "RELEASE_MANIFEST.json"
        top.write_bytes(raw)
        (nested / "RELEASE_MANIFEST.json").write_bytes(raw)

        installed = nested / "RELEASE_MANIFEST.json"
        result = self._install(talenthub_release_manifest=installed)
        self.assertEqual(result["release_baseline"]["action"], "BOUND")
        state = json.loads(
            (self.runtime / installer.CURRENT_RELEASE_STATE_RELATIVE).read_text()
        )
        self.assertEqual(state["release_sequence"], 101)
        self.assertEqual(state["git_commit"], self.commit)

        again = self._install(talenthub_release_manifest=installed)
        self.assertEqual(again["release_baseline"]["action"], "ALREADY_BOUND")

    def test_optional_seal_makes_tracked_code_read_only_and_keeps_backings_writable(self):
        result = self._install(seal_read_only=True)
        self.assertTrue(result["engine_seal"]["sealed"])
        self.assertEqual(
            stat.S_IMODE((self.engine / "pyproject.toml").stat().st_mode) & 0o222,
            0,
        )
        self.assertTrue(os.access(self.runtime / "runtime/storyclaw_storage/workflow/nalu", os.W_OK))
        verified = installer.verify_host(
            self.engine,
            self.runtime,
            release_tag="v1.0.0",
            expected_commit=self.commit,
            require_sealed=True,
        )
        self.assertTrue(verified["engine_seal"]["sealed"])

    def test_verified_archive_first_install_seals_without_git_and_is_idempotent(self):
        view = self.root / "releases/v1.0.0"
        shutil.copytree(self.engine, view, ignore=shutil.ignore_patterns(".git"))
        release = {
            "schema": installer.ARCHIVE_RELEASE_SCHEMA,
            "release_tag": "v1.0.0",
            "git_commit": self.commit,
            "private_runtime_included": False,
            "credentials_included": False,
        }
        (view / "RELEASE_MANIFEST.json").write_text(json.dumps(release) + "\n")
        inventory_rows = []
        for path in sorted(view.rglob("*")):
            if path.is_file() and not path.is_symlink():
                inventory_rows.append({
                    "path": path.relative_to(view).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                })
        inventory = view / "configs/DEPLOYMENT_CODE_SHA256.json"
        inventory.parent.mkdir(parents=True, exist_ok=True)
        inventory.write_text(json.dumps({
            "file_count": len(inventory_rows), "files": inventory_rows,
        }) + "\n")
        archive = self.root / "verified-release.tar.gz"
        archive.write_bytes(b"package-bound immutable archive fixture")

        workspace = self.root / "installed-agent"
        nested = workspace / "skills" / installer.SKILL_NAME
        nested.mkdir(parents=True)
        for relative in installer.INSTALLED_TALENTHUB_BOUND_FILES:
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"installed {relative}\n", encoding="utf-8")
        bindings = {
            relative: {
                "size_bytes": (workspace / relative).stat().st_size,
                "sha256": hashlib.sha256((workspace / relative).read_bytes()).hexdigest(),
            }
            for relative in installer.INSTALLED_TALENTHUB_BOUND_FILES
        }
        package = {
            "schema": installer.TALENTHUB_RELEASE_SCHEMA,
            "agent_id": installer.AGENT_ID,
            "skill": installer.SKILL_NAME,
            "release_tag": "v1.0.0",
            "release_sequence": 1,
            "git_commit": self.commit,
            "origin_tag_commit": self.commit,
            "source_archive_size_bytes": archive.stat().st_size,
            "source_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "release_signing_key_sha256": installer.RELEASE_SIGNING_PUBLIC_KEY_SHA256,
            "validation_receipt_status": "PASS",
            "validation_receipt_sha256": "a" * 64,
            "public_runtime_only": True,
            "private_validation_contents_included": False,
            "dependency_profiles_action": "REPLACE_WITH_RELEASE_BUNDLES",
            "dependency_profiles": self._dependency_bindings("v1.0.0"),
            "installed_file_bindings": bindings,
        }
        package_path = nested / "RELEASE_MANIFEST.json"
        package_path.write_text(json.dumps(package) + "\n")
        link = self.root / "project/engine/current"
        upgrade_receipt = (
            self.runtime / installer.UPGRADE_RECEIPT_ROOT_RELATIVE / f"{self.commit}.json"
        )

        with mock.patch.object(
            installer,
            "verify_host",
            side_effect=installer.InstallBlocked("FORCED_VERIFY_FAILURE"),
        ):
            with self.assertRaisesRegex(installer.InstallBlocked, "FORCED_VERIFY_FAILURE"):
                installer.install_host(
                    view,
                    self.runtime,
                    release_tag="v1.0.0",
                    expected_commit=self.commit,
                    project_view_root=view,
                    project_engine_link=link,
                    seal_read_only=True,
                    talenthub_release_manifest=package_path,
                    verified_bootstrap_archive=archive,
                )
        self.assertFalse(upgrade_receipt.exists())

        with mock.patch.object(
            installer,
            "_record_install_release_baseline",
            side_effect=installer.InstallBlocked("FORCED_BASELINE_FAILURE"),
        ):
            with self.assertRaisesRegex(installer.InstallBlocked, "FORCED_BASELINE_FAILURE"):
                installer.install_host(
                    view,
                    self.runtime,
                    release_tag="v1.0.0",
                    expected_commit=self.commit,
                    project_view_root=view,
                    project_engine_link=link,
                    seal_read_only=True,
                    talenthub_release_manifest=package_path,
                    verified_bootstrap_archive=archive,
                )
        self.assertFalse(upgrade_receipt.exists())

        result = installer.install_host(
            view,
            self.runtime,
            release_tag="v1.0.0",
            expected_commit=self.commit,
            project_view_root=view,
            project_engine_link=link,
            seal_read_only=True,
            talenthub_release_manifest=package_path,
            verified_bootstrap_archive=archive,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["isolation_mode"], "PER_PROJECT_VERIFIED_ARCHIVE_VIEW")
        self.assertTrue(result["engine_seal"]["sealed"])
        self.assertEqual(link.resolve(), view.resolve())
        self.assertFalse((view / ".git").exists())

        again = installer.install_host(
            view,
            self.runtime,
            release_tag="v1.0.0",
            expected_commit=self.commit,
            project_view_root=view,
            project_engine_link=link,
            seal_read_only=True,
            talenthub_release_manifest=package_path,
            verified_bootstrap_archive=archive,
        )
        self.assertEqual(again["status"], "PASS")
        self.assertEqual(again["project_engine_link"]["action"], "ALREADY_LINKED")

    def test_multiple_projects_get_distinct_worktree_views_at_the_same_commit(self):
        project_engines = self.root / "project-engines"
        runtime_two = self.root / "private-runtime-two"
        runtime_two.mkdir(mode=0o700)
        view_one = project_engines / "one/releases/v1"
        view_two = project_engines / "two/releases/v1"
        link_one = project_engines / "one/current"
        link_two = project_engines / "two/current"

        first = self._install(
            project_view_root=view_one,
            project_engine_link=link_one,
        )
        second = installer.install_host(
            self.engine,
            runtime_two,
            release_tag="v1.0.0",
            expected_commit=self.commit,
            project_view_root=view_two,
            project_engine_link=link_two,
        )
        self.assertEqual(first["project_view"]["action"], "CREATED")
        self.assertEqual(first["isolation_mode"], "PER_PROJECT_WORKTREE_VIEW")
        self.assertEqual(second["project_view"]["action"], "CREATED")
        self.assertEqual(first["engine"]["head_commit"], second["engine"]["head_commit"])
        self.assertEqual(link_one.resolve(), view_one.resolve())
        self.assertEqual(link_two.resolve(), view_two.resolve())
        self.assertNotEqual(link_one.resolve(), link_two.resolve())
        self.assertFalse(os.path.lexists(self.engine / "workflow/nalu"))
        self.assertEqual(
            (view_one / "workflow/nalu").resolve(),
            (self.runtime / "runtime/storyclaw_storage/workflow/nalu").resolve(),
        )
        self.assertEqual(
            (view_two / "workflow/nalu").resolve(),
            (runtime_two / "runtime/storyclaw_storage/workflow/nalu").resolve(),
        )

        again = self._install(
            project_view_root=view_one,
            project_engine_link=link_one,
        )
        self.assertEqual(again["project_view"]["action"], "EXISTS_VERIFIED")
        self.assertEqual(again["project_engine_link"]["action"], "ALREADY_LINKED")

    def test_cli_inspect_prints_json_without_mutation(self):
        command = [
            sys.executable,
            str(Path(installer.__file__)),
            "inspect",
            "--engine-root", str(self.engine),
            "--runtime-root", str(self.runtime),
            "--release-tag", "v1.0.0",
        ]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["command"], "INSPECT")
        self.assertFalse(payload["mutations_performed"])
        self.assertFalse((self.runtime / "runtime").exists())


class StoryClawUpgradeTests(unittest.TestCase):
    _dependency_bindings = staticmethod(StoryClawInstallTests._dependency_bindings)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.releases = self.root / "releases"
        self.releases.mkdir()
        self.runtime = self.root / "private-runtime"
        self.runtime.mkdir(mode=0o700)
        self.current = self.releases / "v1"
        self.current.mkdir()
        StoryClawInstallTests._make_engine_tree(self.current)
        self._init_git(self.current, "v1.0.0")
        self.stable = self.root / "engine-current"
        os.symlink(self.current, self.stable)
        installer.install_host(
            self.current,
            self.runtime,
            release_tag="v1.0.0",
            isolated_mount_namespace=True,
        )
        current_commit = subprocess.check_output(
            ["git", "-C", str(self.current), "rev-parse", "HEAD"], text=True
        ).strip()
        baseline = self.runtime / installer.CURRENT_RELEASE_STATE_RELATIVE
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(json.dumps({
            "schema": installer.CURRENT_RELEASE_STATE_SCHEMA,
            "status": "PASS",
            "release_sequence": 1,
            "release_tag": "v1.0.0",
            "git_commit": current_commit,
            "signing_key_sha256": installer.RELEASE_SIGNING_PUBLIC_KEY_SHA256,
            "talenthub_release_manifest_sha256": "1" * 64,
            "validation_receipt_sha256": "1" * 64,
        }) + "\n")
        private_source = self.runtime / "sources/fixture/source.txt"
        private_source.parent.mkdir(parents=True)
        private_source.write_text("private source must survive")
        self.private_source = private_source

    def tearDown(self) -> None:
        for current, directories, _files in os.walk(self.root, topdown=True, followlinks=False):
            path = Path(current)
            if not path.is_symlink():
                try:
                    os.chmod(path, stat.S_IMODE(path.stat().st_mode) | 0o700)
                except FileNotFoundError:
                    pass
            for name in directories:
                child = path / name
                if not child.is_symlink():
                    try:
                        os.chmod(child, stat.S_IMODE(child.stat().st_mode) | 0o700)
                    except FileNotFoundError:
                        pass
        self.temporary.cleanup()

    @staticmethod
    def _init_git(engine: Path, tag: str) -> str:
        subprocess.run(["git", "init", str(engine)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(engine), "config", "user.email", "x@y.invalid"], check=True)
        subprocess.run(["git", "-C", str(engine), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(engine), "add", "."], check=True)
        subprocess.run(["git", "-C", str(engine), "commit", "-m", "fixture"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(engine), "tag", tag], check=True)
        return subprocess.run(
            ["git", "-C", str(engine), "rev-parse", "HEAD"],
            check=True, text=True, capture_output=True,
        ).stdout.strip()

    def _build_release(
        self,
        *,
        protected_change: bool = False,
        update_class: str = installer.ENGINE_ONLY,
        dependencies_changed: bool = False,
    ):
        candidate_source = self.root / "candidate-source"
        candidate_source.mkdir()
        StoryClawInstallTests._make_engine_tree(candidate_source)
        (candidate_source / "lines/nalu/runtime/tools/nalu_pipeline.py").write_text(
            "PIPELINE_VERSION = 2\n"
        )
        if protected_change:
            (candidate_source / "agent_factory/storyclaw_portable/AGENTS.md").write_text(
                "changed brain requires TalentHub republish\n"
            )
        commit = "2" * 40
        tag = "v2.0.0"
        release_manifest = {
            "schema": installer.ARCHIVE_RELEASE_SCHEMA,
            "release_tag": tag,
            "git_commit": commit,
            "private_runtime_included": False,
            "credentials_included": False,
        }
        (candidate_source / "RELEASE_MANIFEST.json").write_text(
            json.dumps(release_manifest) + "\n"
        )
        archive = self.root / "v2.tar.gz"
        with archive.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                for path in sorted(candidate_source.rglob("*")):
                    relative = path.relative_to(candidate_source)
                    info = tarfile.TarInfo(
                        f"qingshan-storyclaw-workflow/{relative.as_posix()}"
                    )
                    info.mtime = 0
                    if path.is_dir():
                        info.type = tarfile.DIRTYPE
                        info.mode = 0o755
                        tar.addfile(info)
                    else:
                        data = path.read_bytes()
                        info.size = len(data)
                        info.mode = 0o644
                        tar.addfile(info, io.BytesIO(data))
        archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        replace_dependencies = update_class != installer.ENGINE_ONLY or dependencies_changed
        channel = {
            "schema": installer.UPGRADE_SCHEMA,
            "immutable": True,
            "channel": "stable",
            "release_sequence": 2,
            "release_tag": tag,
            "source_ref": f"refs/tags/{tag}",
            "git_commit": commit,
            "source_archive_sha256": archive_sha,
            "source_archive_size_bytes": archive.stat().st_size,
            "runtime_schema": "nalu.pipeline_state.v1",
            "compatible_runtime_schemas": ["nalu.pipeline_state.v1"],
            "runtime_migration": "NONE",
            "min_installer_version": installer.INSTALLER_VERSION,
            "update_class": update_class,
            "dependencies_changed": dependencies_changed,
            "validation_receipt_status": "PASS",
            "validation_receipt_sha256": "a" * 64,
            "release_signing_key_sha256": installer.RELEASE_SIGNING_PUBLIC_KEY_SHA256,
            "dependency_profiles_action": (
                "REPLACE_WITH_RELEASE_BUNDLES"
                if replace_dependencies else "REUSE_CURRENT"
            ),
            "dependency_profiles": (
                self._dependency_bindings(tag) if replace_dependencies else []
            ),
        }
        channel_path = self.root / "stable-v2.json"
        channel_path.write_text(json.dumps(channel, sort_keys=True) + "\n")
        channel_sha = hashlib.sha256(channel_path.read_bytes()).hexdigest()
        return archive, channel_path, channel_sha, channel

    def _talenthub_workspace(self, channel_path, channel_sha, channel):
        workspace = self.root / "installed-talenthub-workspace"
        nested = workspace / "skills" / installer.SKILL_NAME
        nested.mkdir(parents=True)
        (workspace / "manifest.json").write_text(json.dumps({
            "id": installer.AGENT_ID,
            "skills": [
                "https://github.com/rogerwu188/qingshan-short-drama-production-line"
                f"@{installer.SKILL_NAME}"
            ],
        }) + "\n")
        for relative in installer.INSTALLED_TALENTHUB_BOUND_FILES:
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"installed {relative}\n", encoding="utf-8")
        bindings = {
            relative: {
                "size_bytes": (workspace / relative).stat().st_size,
                "sha256": hashlib.sha256((workspace / relative).read_bytes()).hexdigest(),
            }
            for relative in installer.INSTALLED_TALENTHUB_BOUND_FILES
        }
        release = {
            "schema": installer.TALENTHUB_RELEASE_SCHEMA,
            "agent_id": installer.AGENT_ID,
            "skill": installer.SKILL_NAME,
            "release_tag": channel["release_tag"],
            "git_commit": channel["git_commit"],
            "origin_tag_commit": channel["git_commit"],
            "source_archive_size_bytes": channel["source_archive_size_bytes"],
            "source_archive_sha256": channel["source_archive_sha256"],
            "release_channel_size_bytes": channel_path.stat().st_size,
            "release_channel_sha256": channel_sha,
            "release_channel_update_class": channel["update_class"],
            "release_sequence": channel["release_sequence"],
            "release_signing_key_sha256": installer.RELEASE_SIGNING_PUBLIC_KEY_SHA256,
            "validation_receipt_status": "PASS",
            "validation_receipt_sha256": "a" * 64,
            "public_runtime_only": True,
            "private_validation_contents_included": False,
            "dependency_profiles_action": channel["dependency_profiles_action"],
            "dependency_profiles": channel["dependency_profiles"],
            "installed_file_bindings": bindings,
        }
        raw = json.dumps(release, sort_keys=True).encode() + b"\n"
        top = workspace / "RELEASE_MANIFEST.json"
        top.write_bytes(raw)
        installed = nested / "RELEASE_MANIFEST.json"
        installed.write_bytes(raw)
        return installed

    @staticmethod
    def _preflight_pass(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout='{"status":"PASS"}', stderr="")

    def _install_old_venv_selector(self) -> tuple[Path, Path]:
        old_venv = self.runtime / "runtime/storyclaw_host/venvs/v1"
        old_python = old_venv / "bin/python"
        old_python.parent.mkdir(parents=True, exist_ok=True)
        old_python.write_text("old private python")
        selector = self.runtime / installer.VENV_SELECTOR_RELATIVE
        selector.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(old_venv, selector)
        return old_venv, selector

    def _upgrade(self, archive, manifest, manifest_sha, *, trust=True, **overrides):
        if trust:
            channel = json.loads(Path(manifest).read_text())
            current_state = json.loads(
                (self.runtime / installer.CURRENT_RELEASE_STATE_RELATIVE).read_text()
            )
            current_identity = installer._current_engine_identity(
                self.stable.resolve(), self.runtime.resolve()
            )
            trusted = self.runtime / installer.DISCOVERY_STATE_RELATIVE
            trusted.parent.mkdir(parents=True, exist_ok=True)
            trusted.write_text(json.dumps({
                "schema": installer.DISCOVERY_RESULT_SCHEMA,
                "status": (
                    "CURRENT"
                    if channel["git_commit"] == current_identity["git_commit"]
                    else "AVAILABLE"
                ),
                "current_release_tag": current_identity["release_tag"],
                "current_release_commit": current_identity["git_commit"],
                "baseline_release_sequence": current_state["release_sequence"],
                "trusted_release_sequence": channel["release_sequence"],
                "trusted_release_tag": channel["release_tag"],
                "trusted_release_commit": channel["git_commit"],
                "update_class": channel["update_class"],
                "signing_key_sha256": installer.RELEASE_SIGNING_PUBLIC_KEY_SHA256,
                "channel_manifest": str(Path(manifest).resolve()),
                "channel_manifest_sha256": hashlib.sha256(
                    Path(manifest).read_bytes()
                ).hexdigest(),
                "source_archive_size_bytes": channel["source_archive_size_bytes"],
                "source_archive_sha256": channel["source_archive_sha256"],
                "validation_receipt_sha256": channel["validation_receipt_sha256"],
                "provider_posts": 0,
            }) + "\n")
        values = {
            "channel_manifest": manifest,
            "channel_manifest_sha256": manifest_sha,
            "archive": archive,
            "preflight_runner": self._preflight_pass,
        }
        values.update(overrides)
        return installer.upgrade_engine(
            self.stable, self.releases, self.runtime, **values
        )

    def test_every_canonical_talenthub_surface_is_compared_by_installer(self):
        for relative in sorted(release_surface.TALENTHUB_MANAGED_EXACT):
            with self.subTest(exact=relative), tempfile.TemporaryDirectory() as td:
                pair = Path(td)
                old = pair / "old"
                new = pair / "new"
                for root, value in ((old, "old"), (new, "new")):
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(value, encoding="utf-8")
                self.assertIn(relative, installer._talenthub_managed_changes(old, new))

        for root_relative in release_surface.TALENTHUB_MANAGED_TREE_ROOTS:
            with self.subTest(tree=root_relative), tempfile.TemporaryDirectory() as td:
                pair = Path(td)
                old = pair / "old"
                new = pair / "new"
                for root, value in ((old, "old"), (new, "new")):
                    path = root / root_relative / "nested.txt"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(value, encoding="utf-8")
                self.assertIn(
                    root_relative, installer._talenthub_managed_changes(old, new)
                )

        for prefix in release_surface.TALENTHUB_MANAGED_FILE_PREFIXES:
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as td:
                pair = Path(td)
                old = pair / "old"
                new = pair / "new"
                relative = prefix + "TEST.md"
                for root, value in ((old, "old"), (new, "new")):
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(value, encoding="utf-8")
                self.assertIn(relative, installer._talenthub_managed_changes(old, new))

    def test_engine_only_upgrade_is_side_by_side_atomic_and_idempotent(self):
        state = self.runtime / "runtime/pipeline_state/E01.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({
            "schema": "nalu.pipeline_state.v1",
            "episode": "E01",
            "overall_status": "REVIEW_REQUIRED",
            "current_stage": "S5",
        }))
        archive, manifest, manifest_sha, channel = self._build_release()
        result = self._upgrade(archive, manifest, manifest_sha)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["git_commit"], channel["git_commit"])
        upgraded = self.stable.resolve()
        self.assertNotEqual(upgraded, self.current.resolve())
        self.assertTrue(upgraded.is_relative_to(self.releases.resolve()))
        self.assertEqual(self.private_source.read_text(), "private source must survive")
        self.assertTrue((upgraded / "workflow/nalu").is_symlink())
        self.assertEqual(
            (upgraded / "workflow/nalu").resolve(),
            (self.runtime / "runtime/storyclaw_storage/workflow/nalu").resolve(),
        )
        receipt = Path(result["receipt"]["path"])
        payload = json.loads(receipt.read_text())
        self.assertTrue(payload["runtime_preserved"])
        self.assertFalse(payload["network_used"])

        verified = installer.verify_host(
            self.stable,
            self.runtime,
            release_tag=channel["release_tag"],
            expected_commit=channel["git_commit"],
            require_sealed=True,
        )
        self.assertEqual(verified["engine"]["checkout_kind"], "VERIFIED_RELEASE_ARCHIVE")
        self.assertTrue(verified["engine"]["immutable_tree_verified"])

        again = self._upgrade(archive, manifest, manifest_sha)
        self.assertEqual(again["status"], "ALREADY_CURRENT")

    def test_upgrade_refuses_active_or_unknown_episode_state(self):
        state = self.runtime / "runtime/pipeline_state/E01.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        archive, manifest, manifest_sha, _channel = self._build_release()
        for status in ("RUNNING", "STOPPED_AT_S6_CRASHED"):
            with self.subTest(status=status):
                state.write_text(json.dumps({
                    "schema": "nalu.pipeline_state.v1",
                    "overall_status": status,
                    "current_stage": "S6",
                }))
                with self.assertRaisesRegex(
                    installer.InstallBlocked, "EPISODE_NOT_AT_SAFE_STOP"
                ):
                    self._upgrade(archive, manifest, manifest_sha)
        self.assertEqual(self.stable.resolve(), self.current.resolve())

    def test_upgrade_barrier_blocks_a_new_upgrade_while_production_holds_shared_lock(self):
        archive, manifest, manifest_sha, _channel = self._build_release()
        barrier = self.runtime / installer.UPGRADE_BARRIER_RELATIVE
        barrier.parent.mkdir(parents=True, exist_ok=True)
        with barrier.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            with self.assertRaisesRegex(installer.InstallBlocked, "ENGINE_UPGRADE_LOCKED"):
                self._upgrade(archive, manifest, manifest_sha)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        self.assertEqual(self.stable.resolve(), self.current.resolve())

    def test_upgrade_holds_exclusive_barrier_through_candidate_preflight(self):
        archive, manifest, manifest_sha, _channel = self._build_release()
        observed = {"shared_blocked": False}

        def preflight(command, **kwargs):
            barrier = self.runtime / installer.UPGRADE_BARRIER_RELATIVE
            with barrier.open("a+b") as handle:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    observed["shared_blocked"] = True
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return subprocess.CompletedProcess(command, 0, stdout='{"status":"PASS"}', stderr="")

        result = self._upgrade(
            archive, manifest, manifest_sha, preflight_runner=preflight
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(observed["shared_blocked"])

    def test_upgrade_verifies_manifest_and_archive_hashes_before_extracting(self):
        archive, manifest, manifest_sha, _channel = self._build_release()
        with self.assertRaisesRegex(installer.InstallBlocked, "CHANNEL_MANIFEST_SHA256_MISMATCH"):
            self._upgrade(archive, manifest, "0" * 64)
        archive.write_bytes(archive.read_bytes() + b"tamper")
        with self.assertRaisesRegex(installer.InstallBlocked, "SOURCE_ARCHIVE_SIZE_MISMATCH"):
            self._upgrade(archive, manifest, manifest_sha)
        self.assertEqual(self.stable.resolve(), self.current.resolve())

    def test_direct_upgrade_cli_requires_signed_discovery_binding(self):
        archive, manifest, manifest_sha, _channel = self._build_release()
        command = [
            sys.executable,
            str(Path(installer.__file__)),
            "upgrade",
            "--engine-link", str(self.stable),
            "--releases-root", str(self.releases),
            "--runtime-root", str(self.runtime),
            "--channel-manifest", str(manifest),
            "--channel-manifest-sha256", manifest_sha,
            "--archive", str(archive),
        ]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 2)
        error = json.loads(result.stderr)
        self.assertEqual(error["code"], "TRUSTED_DISCOVERY_STATE_REQUIRED")
        self.assertEqual(self.stable.resolve(), self.current.resolve())

    def test_direct_replay_cannot_downgrade_release_sequence(self):
        archive, manifest, manifest_sha, _channel = self._build_release()
        upgraded = self._upgrade(archive, manifest, manifest_sha)
        self.assertEqual(upgraded["status"], "PASS")

        replay = json.loads(manifest.read_text())
        replay["release_sequence"] = 1
        manifest.write_text(json.dumps(replay, sort_keys=True) + "\n")
        replay_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
        with self.assertRaisesRegex(installer.InstallBlocked, "RELEASE_SEQUENCE_ROLLBACK"):
            self._upgrade(archive, manifest, replay_sha)
        self.assertEqual(
            json.loads(
                (self.runtime / installer.CURRENT_RELEASE_STATE_RELATIVE).read_text()
            )["release_sequence"],
            2,
        )

    def test_brain_or_installer_changes_require_talenthub_republish(self):
        archive, manifest, manifest_sha, _channel = self._build_release(protected_change=True)
        with self.assertRaisesRegex(installer.InstallBlocked, "TALENTHUB_REPUBLISH_REQUIRED"):
            self._upgrade(archive, manifest, manifest_sha)
        self.assertEqual(self.stable.resolve(), self.current.resolve())
        self.assertEqual(self.private_source.read_text(), "private source must survive")
        self.assertFalse(any(path.name.startswith("v2.0.0-") for path in self.releases.iterdir()))

    def test_package_required_upgrade_needs_exact_installed_workspace_binding(self):
        archive, manifest, manifest_sha, channel = self._build_release(
            protected_change=True,
            update_class=installer.PACKAGE_REQUIRED,
        )
        with self.assertRaisesRegex(installer.InstallBlocked, "TALENTHUB_REPUBLISH_REQUIRED"):
            self._upgrade(archive, manifest, manifest_sha)
        self.assertEqual(self.stable.resolve(), self.current.resolve())

        workspace_release = self._talenthub_workspace(manifest, manifest_sha, channel)
        payload = json.loads(workspace_release.read_text())
        payload["git_commit"] = "3" * 40
        workspace_release.write_text(json.dumps(payload) + "\n")
        with self.assertRaisesRegex(installer.InstallBlocked, "TALENTHUB_REPUBLISH_REQUIRED"):
            self._upgrade(
                archive,
                manifest,
                manifest_sha,
                talenthub_release_manifest=workspace_release,
            )
        self.assertEqual(self.stable.resolve(), self.current.resolve())

    def test_package_binding_rejects_every_release_identity_mismatch(self):
        archive, manifest, manifest_sha, channel = self._build_release(
            protected_change=True,
            update_class=installer.PACKAGE_REQUIRED,
        )
        workspace_release = self._talenthub_workspace(manifest, manifest_sha, channel)
        nested_release = workspace_release
        original = json.loads(workspace_release.read_text())
        mismatches = {
            "schema": "wrong.schema.v1",
            "release_tag": "v9.9.9",
            "git_commit": "3" * 40,
            "source_archive_sha256": "b" * 64,
            "release_channel_sha256": "c" * 64,
            "release_channel_update_class": installer.ENGINE_ONLY,
            "validation_receipt_status": "FAIL",
        }
        for field, bad_value in mismatches.items():
            with self.subTest(field=field):
                changed = {**original, field: bad_value}
                raw = json.dumps(changed, sort_keys=True).encode() + b"\n"
                workspace_release.write_bytes(raw)
                with self.assertRaisesRegex(
                    installer.InstallBlocked, "TALENTHUB_REPUBLISH_REQUIRED"
                ):
                    self._upgrade(
                        archive,
                        manifest,
                        manifest_sha,
                        talenthub_release_manifest=workspace_release,
                    )
                self.assertEqual(self.stable.resolve(), self.current.resolve())

        # A top-level local build copy is not an installed authority in
        # TalentHub 0.4.11; the bundled skill path and installed prompt hashes
        # are the machine-readable contract.
        canonical_raw = json.dumps(original, sort_keys=True).encode() + b"\n"
        workspace_release.write_bytes(canonical_raw)
        prompt = workspace_release.parents[2] / "AGENTS.md"
        prompt.write_text("tampered installed prompt\n", encoding="utf-8")
        with self.assertRaisesRegex(
            installer.InstallBlocked, "TALENTHUB_REPUBLISH_REQUIRED"
        ):
            self._upgrade(
                archive,
                manifest,
                manifest_sha,
                talenthub_release_manifest=workspace_release,
            )
        self.assertEqual(self.stable.resolve(), self.current.resolve())

    def test_matching_talenthub_package_allows_protected_engine_switch(self):
        archive, manifest, manifest_sha, channel = self._build_release(
            protected_change=True,
            update_class=installer.PACKAGE_REQUIRED,
        )
        workspace_release = self._talenthub_workspace(manifest, manifest_sha, channel)
        result = self._upgrade(
            archive,
            manifest,
            manifest_sha,
            talenthub_release_manifest=workspace_release,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["update_class"], installer.PACKAGE_REQUIRED)
        self.assertEqual(
            result["talenthub_package_binding"]["release_channel_sha256"],
            manifest_sha,
        )
        receipt = json.loads(Path(result["receipt"]["path"]).read_text())
        self.assertEqual(
            receipt["talenthub_managed_files_changed"],
            ["agent_factory/storyclaw_portable"],
        )
        self.assertEqual(receipt["talenthub_package_binding"]["status"], "PASS")

    def test_dependency_change_requires_and_uses_brand_new_private_venv(self):
        old_venv, selector = self._install_old_venv_selector()
        archive, manifest, manifest_sha, channel = self._build_release(
            update_class=installer.PACKAGE_REQUIRED,
            dependencies_changed=True,
        )
        workspace_release = self._talenthub_workspace(manifest, manifest_sha, channel)
        with self.assertRaisesRegex(
            installer.InstallBlocked, "DEPENDENCY_UPGRADE_REQUIRES_NEW_PRIVATE_VENV"
        ):
            self._upgrade(
                archive,
                manifest,
                manifest_sha,
                talenthub_release_manifest=workspace_release,
            )

        calls = []

        def fake_dependencies(engine, runtime, *, venv_path, python_executable, **_kwargs):
            calls.append((engine, runtime, venv_path, python_executable))
            python = Path(venv_path) / "bin/python"
            python.parent.mkdir(parents=True)
            python.write_text("new private python")
            return {
                "requested": True,
                "venv": str(venv_path),
                "python": str(python),
                "network_used": False,
            }

        new_venv = self.runtime / "runtime/storyclaw_host/venvs/v2"
        result = self._upgrade(
            archive,
            manifest,
            manifest_sha,
            talenthub_release_manifest=workspace_release,
            install_deps=True,
            new_venv_path=new_venv,
            dependency_installer=fake_dependencies,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["dependency_update"]["status"], "INSTALLED_NEW_PRIVATE_VENV")
        self.assertEqual(
            result["dependency_update"]["next_nalu_venv_python"],
            str(self.runtime.resolve() / installer.VENV_SELECTOR_RELATIVE / "bin/python"),
        )
        self.assertEqual(
            result["dependency_update"]["installed_venv_python"],
            str((new_venv / "bin/python").resolve()),
        )
        self.assertFalse(result["dependency_update"]["activation_required"])
        self.assertEqual(
            Path(result["previous_venv_selector"]["target"]).resolve(),
            old_venv.resolve(),
        )
        self.assertEqual(result["venv_selector"]["target"], str(new_venv.resolve()))
        self.assertEqual(selector.resolve(), new_venv.resolve())
        self.assertFalse(result["network_used"])
        self.assertTrue(new_venv.is_dir())

    def test_failed_dependency_candidate_removes_new_venv_and_keeps_old_engine(self):
        old_venv, selector = self._install_old_venv_selector()
        archive, manifest, manifest_sha, channel = self._build_release(
            update_class=installer.PACKAGE_REQUIRED,
            dependencies_changed=True,
        )
        workspace_release = self._talenthub_workspace(manifest, manifest_sha, channel)
        new_venv = self.runtime / "runtime/storyclaw_host/venvs/failed-v2"

        def fake_dependencies(engine, runtime, *, venv_path, python_executable, **_kwargs):
            python = Path(venv_path) / "bin/python"
            python.parent.mkdir(parents=True)
            python.write_text("candidate python")
            return {"venv": str(venv_path), "python": str(python)}

        def failed_preflight(command, **kwargs):
            return subprocess.CompletedProcess(command, 2, stdout="", stderr="blocked")

        with self.assertRaisesRegex(installer.InstallBlocked, "CANDIDATE_PREFLIGHT_FAILED"):
            self._upgrade(
                archive,
                manifest,
                manifest_sha,
                talenthub_release_manifest=workspace_release,
                install_deps=True,
                new_venv_path=new_venv,
                dependency_installer=fake_dependencies,
                preflight_runner=failed_preflight,
            )
        self.assertFalse(new_venv.exists())
        self.assertEqual(selector.resolve(), old_venv.resolve())
        self.assertEqual(self.stable.resolve(), self.current.resolve())
        self.assertEqual(self.private_source.read_text(), "private source must survive")

    def test_dependency_post_switch_failure_rolls_back_engine_and_venv_selector(self):
        old_venv, selector = self._install_old_venv_selector()
        archive, manifest, manifest_sha, channel = self._build_release(
            update_class=installer.PACKAGE_REQUIRED,
            dependencies_changed=True,
        )
        workspace_release = self._talenthub_workspace(manifest, manifest_sha, channel)
        new_venv = self.runtime / "runtime/storyclaw_host/venvs/rollback-v2"

        def fake_dependencies(engine, runtime, *, venv_path, python_executable, **_kwargs):
            python = Path(venv_path) / "bin/python"
            python.parent.mkdir(parents=True)
            python.write_text("candidate python")
            return {"venv": str(venv_path), "python": str(python)}

        real_wire_report = installer._wire_report

        def fail_after_switch(rows, *, probe):
            materialized = list(rows)
            if materialized and str(materialized[0]["target"]).startswith(str(self.stable)):
                raise installer.InstallBlocked("FORCED_POST_SWITCH_FAILURE")
            return real_wire_report(materialized, probe=probe)

        with mock.patch.object(installer, "_wire_report", side_effect=fail_after_switch):
            with self.assertRaisesRegex(installer.InstallBlocked, "FORCED_POST_SWITCH_FAILURE"):
                self._upgrade(
                    archive,
                    manifest,
                    manifest_sha,
                    talenthub_release_manifest=workspace_release,
                    install_deps=True,
                    new_venv_path=new_venv,
                    dependency_installer=fake_dependencies,
                )
        self.assertEqual(self.stable.resolve(), self.current.resolve())
        self.assertEqual(selector.resolve(), old_venv.resolve())
        self.assertFalse(new_venv.exists())

    def test_prepared_crash_journal_restores_engine_venv_state_and_removes_candidate(self):
        transaction = installer._upgrade_transaction
        new_engine = self.releases / "crashed-v2"
        new_engine.mkdir()
        old_venv = self.runtime / "runtime/storyclaw_host/venvs/old"
        new_venv = self.runtime / "runtime/storyclaw_host/venvs/crashed-v2"
        for venv in (old_venv, new_venv):
            (venv / "bin").mkdir(parents=True)
            (venv / "bin/python").write_text("fixture\n")
        selector = self.runtime / transaction.VENV_SELECTOR_RELATIVE
        selector.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(old_venv, selector)
        current_state_path = self.runtime / installer.CURRENT_RELEASE_STATE_RELATIVE
        prior_current = json.loads(current_state_path.read_text())
        discovery_path = self.runtime / installer.DISCOVERY_STATE_RELATIVE
        prior_discovery = {
            "schema": "storyclaw.nalu.release_discovery_state.v1",
            "status": "CURRENT",
            "baseline_release_sequence": 1,
        }
        discovery_path.parent.mkdir(parents=True, exist_ok=True)
        discovery_path.write_text(json.dumps(prior_discovery) + "\n")
        receipt_path = (
            self.runtime / installer.UPGRADE_RECEIPT_ROOT_RELATIVE / "crashed.json"
        )
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text('{"status":"PASS"}\n')
        transaction.write_prepared(self.runtime, {
            "releases_root": str(self.releases),
            "engine_link": str(self.stable),
            "old_engine": str(self.current),
            "new_engine": str(new_engine),
            "old_engine_raw_link": os.readlink(self.stable),
            "venv_selector": str(selector),
            "old_venv": str(old_venv),
            "new_venv": str(new_venv),
            "old_venv_raw_link": os.readlink(selector),
            "current_release_state_path": str(current_state_path),
            "discovery_state_path": str(discovery_path),
            "prior_current_release_state": prior_current,
            "prior_discovery_state": prior_discovery,
            "receipt_path": str(receipt_path),
        })
        self.stable.unlink()
        os.symlink(new_engine, self.stable)
        selector.unlink()
        os.symlink(new_venv, selector)
        current_state_path.write_text('{"status":"CRASHED_NEW"}\n')
        discovery_path.write_text('{"status":"APPLIED_NEW"}\n')

        recovered = transaction.recover(self.runtime)
        self.assertEqual(recovered["status"], "RECOVERED")
        self.assertEqual(self.stable.resolve(), self.current.resolve())
        self.assertEqual(selector.resolve(), old_venv.resolve())
        self.assertEqual(json.loads(current_state_path.read_text()), prior_current)
        self.assertEqual(json.loads(discovery_path.read_text()), prior_discovery)
        self.assertFalse(receipt_path.exists())
        self.assertFalse(new_engine.exists())
        self.assertFalse(new_venv.exists())
        self.assertFalse(transaction.journal_path(self.runtime).exists())

    def test_post_switch_failure_rolls_back_and_removes_candidate(self):
        archive, manifest, manifest_sha, _channel = self._build_release()
        real_wire_report = installer._wire_report

        def fail_after_switch(rows, *, probe):
            materialized = list(rows)
            if materialized and str(materialized[0]["target"]).startswith(str(self.stable)):
                raise installer.InstallBlocked("FORCED_POST_SWITCH_FAILURE")
            return real_wire_report(materialized, probe=probe)

        with mock.patch.object(installer, "_wire_report", side_effect=fail_after_switch):
            with self.assertRaisesRegex(installer.InstallBlocked, "FORCED_POST_SWITCH_FAILURE"):
                self._upgrade(archive, manifest, manifest_sha)
        self.assertEqual(self.stable.resolve(), self.current.resolve())
        self.assertEqual(self.private_source.read_text(), "private source must survive")
        self.assertFalse(any(path.name.startswith("v2.0.0-") for path in self.releases.iterdir()))


if __name__ == "__main__":
    unittest.main()
