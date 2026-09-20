from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tools import storyclaw_registry_clean_install_smoke as smoke


TEST_PRIVATE_KEY = b"""-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEICKXf7yfRrE94DsYOauAjfr8n5fLotiYV335Xlg7a3ew
-----END PRIVATE KEY-----
"""
TEST_PUBLIC_KEY = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEArtovlPTTuzak17u9M/DKCb/6sfd48gEXzLTR2Yky9oI=
-----END PUBLIC KEY-----
"""


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class CleanInstallFixture:
    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project_home = self.root / "project-home"
        self.runtime = self.project_home / "projects/test-project"
        self.installed = self.root / "installed-agent"
        self.artifacts = self.root / "public-artifacts"
        self.engine = self.project_home / "engine/releases/v1.2.3"
        self.engine_link = self.project_home / "engine/current"
        self.workspace_backing = self.runtime / "runtime/storyclaw_storage/workflow/nalu"
        self.transactions_backing = self.runtime / "runtime/storyclaw_storage/workflow/tasks"
        self.receipt_root = self.runtime / smoke.SMOKE_RECEIPT_ROOT
        for path in (
            self.runtime, self.installed, self.artifacts, self.engine / "workflow",
            self.workspace_backing, self.transactions_backing, self.receipt_root,
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.original_signing_key_sha256 = smoke.SIGNING_KEY_SHA256
        self.public_key = self.engine / "configs/storyclaw_release_signing_public_key.pem"
        self.public_key.parent.mkdir(parents=True, exist_ok=True)
        self.public_key.write_bytes(TEST_PUBLIC_KEY)
        self.private_key = self.artifacts / "test-signing-key.pem"
        self.private_key.write_bytes(TEST_PRIVATE_KEY)
        smoke.SIGNING_KEY_SHA256 = _sha(self.public_key)
        self.tag = "v1.2.3"
        self.commit = "a" * 40
        self.sequence = 12
        self.channel_sha = "b" * 64
        self.validation_sha = "c" * 64
        self.profile_id = "storyclaw-linux-x86_64-cpython311-cpu-v1"
        self.profile_manifest_sha = "d" * 64
        self.profile_archive_sha = "e" * 64
        self.archive = self.project_home / "bootstrap-cache/qingshan-storyclaw-workflow-v1.2.3.tar.gz"
        self.archive.parent.mkdir(parents=True)
        self.archive.write_bytes(b"immutable verified engine archive\n")
        self.archive_sha = _sha(self.archive)
        self.archive_size = self.archive.stat().st_size
        self.archive_url = (
            f"{smoke.REPOSITORY}/releases/download/{self.tag}/"
            f"qingshan-storyclaw-workflow-{self.tag}.tar.gz"
        )
        self.index = self.artifacts / "qingshan-storyclaw-stable-index.json"
        self.index_payload = {
            "schema": smoke.STABLE_INDEX_SCHEMA,
            "channel": "stable",
            "release_sequence": self.sequence,
            "release_tag": self.tag,
            "git_commit": self.commit,
            "update_class": "TALENTHUB_PACKAGE_REQUIRED",
            "source_archive_url": self.archive_url,
            "source_archive_size_bytes": self.archive_size,
            "source_archive_sha256": self.archive_sha,
            "release_channel_sha256": self.channel_sha,
            "validation_receipt_status": "PASS",
            "validation_receipt_sha256": self.validation_sha,
            "signing_key_sha256": smoke.SIGNING_KEY_SHA256,
        }
        _write_json(self.index, self.index_payload)
        self.index_sha = _sha(self.index)
        self.index_signature = self.artifacts / "qingshan-storyclaw-stable-index.json.sig"
        signed = subprocess.run(
            [
                "openssl", "pkeyutl", "-sign", "-inkey", str(self.private_key),
                "-rawin", "-in", str(self.index), "-out", str(self.index_signature),
            ],
            check=False, capture_output=True, text=True,
        )
        if signed.returncode != 0:
            raise RuntimeError(signed.stderr)

        self.bound_bodies = {
            relative: f"bound registry content: {relative}\n".encode("utf-8")
            for relative in smoke.BOUND_AGENT_FILES
        }
        for relative, body in self.bound_bodies.items():
            target = self.installed / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        self.manifest_payload = {
            "schema": smoke.TALENTHUB_SCHEMA,
            "agent_id": smoke.AGENT_ID,
            "skill": smoke.SKILL_NAME,
            "release_tag": self.tag,
            "release_sequence": self.sequence,
            "git_commit": self.commit,
            "origin_tag_commit": self.commit,
            "source_archive_github_release_url": self.archive_url,
            "source_archive_size_bytes": self.archive_size,
            "source_archive_sha256": self.archive_sha,
            "release_channel_sha256": self.channel_sha,
            "release_channel_update_class": "TALENTHUB_PACKAGE_REQUIRED",
            "stable_index_sha256": self.index_sha,
            "release_signing_key_sha256": smoke.SIGNING_KEY_SHA256,
            "validation_receipt_status": "PASS",
            "validation_receipt_sha256": self.validation_sha,
            "public_runtime_only": True,
            "private_validation_contents_included": False,
            "dependency_profiles": [{
                "profile_id": self.profile_id,
                "manifest_url": "https://github.com/example/deps.json",
                "manifest_size_bytes": 123,
                "manifest_sha256": self.profile_manifest_sha,
                "archive_url": "https://github.com/example/deps.tar.gz",
                "archive_size_bytes": 456,
                "archive_sha256": self.profile_archive_sha,
            }],
            "installed_file_bindings": {
                relative: {"size_bytes": len(body), "sha256": _sha_bytes(body)}
                for relative, body in self.bound_bodies.items()
            },
        }
        self.manifest = self.installed / smoke.NESTED_MANIFEST
        _write_json(self.manifest, self.manifest_payload)
        self.registry = self.artifacts / "ai-drama-factory.zip"
        self._write_registry_package()
        self.registry_url = "https://assets.storyclaw.com/registry/ai-drama-factory-v1.2.3.zip"

        (self.engine / "RELEASE_MANIFEST.json").write_text("immutable engine\n")
        os.symlink(self.workspace_backing, self.engine / "workflow/nalu")
        os.symlink(self.transactions_backing, self.engine / "workflow/tasks")
        self.engine_link.parent.mkdir(parents=True, exist_ok=True)

        self.marker_payload = {
            "schema": "storyclaw.nalu.project.v1",
            "status": "INITIALIZED_PRIVATE",
            "project_id": "test-project",
            "series_scope_id": "TEST-SCOPE",
            "private_runtime_root": str(self.runtime.resolve()),
            "engine_root": str(self.engine_link),
            "paid_requests_enabled": False,
        }
        self.marker = _write_json(self.runtime / "runtime/project.json", self.marker_payload)
        self.hidden_marker = _write_json(
            self.runtime / ".qingshan-private-runtime.json", self.marker_payload
        )
        self.config_payload = {
            "schema": "qingshan.pipeline.config.v1",
            "project": {"id": "test-project"},
            "generation": {"paid_requests_enabled": False},
            "authorization": {"paid_order_seq": 0, "status": "NOT_AUTHORIZED"},
            "storyclaw": {
                "project_id": "test-project",
                "series_scope_id": "TEST-SCOPE",
                "storage": {
                    "mode": "READ_ONLY_ENGINE_WITH_PRIVATE_WRITABLE_MOUNTS",
                    "engine_root": str(self.engine_link),
                    "workspace_mount_target": str(self.engine_link / "workflow/nalu"),
                    "workspace_backing_path": str(self.workspace_backing.resolve()),
                    "transactions_mount_target": str(self.engine_link / "workflow/tasks"),
                    "transactions_backing_path": str(self.transactions_backing.resolve()),
                },
            },
        }
        self.config = _write_json(self.runtime / "qingshan.json", self.config_payload)

        self.before = self.receipt_root / "transactions-before.json"
        saved_secrets = {
            name: os.environ.pop(name)
            for name in smoke.PROVIDER_SECRET_NAMES if name in os.environ
        }
        try:
            smoke.snapshot_transactions(self.runtime, self.before, label="before")
        finally:
            os.environ.update(saved_secrets)
        os.symlink(self.engine, self.engine_link)

        self.venv = self.runtime / "runtime/storyclaw_host/venv"
        self.python = self.venv / "bin/python"
        self.python.parent.mkdir(parents=True)
        self.python.write_bytes(b"#!/bin/sh\nexit 0\n")
        os.chmod(self.python, 0o555)
        self.selector = self.runtime / smoke.VENV_SELECTOR_RELATIVE
        self.selector.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(self.venv, self.selector)

        self.baseline_payload = {
            "schema": smoke.CURRENT_RELEASE_SCHEMA,
            "status": "PASS",
            "release_sequence": self.sequence,
            "release_tag": self.tag,
            "git_commit": self.commit,
            "signing_key_sha256": smoke.SIGNING_KEY_SHA256,
            "talenthub_release_manifest_sha256": _sha(self.manifest),
            "validation_receipt_sha256": self.validation_sha,
        }
        self.baseline = _write_json(
            self.runtime / smoke.CURRENT_RELEASE_RELATIVE, self.baseline_payload
        )

        self.bootstrap_payload = {
            "schema": smoke.BOOTSTRAP_SCHEMA,
            "status": "PREFLIGHT_PASS_PENDING_SNAPSHOT",
            "release_tag": self.tag,
            "git_commit": self.commit,
            "release_sequence": self.sequence,
            "source_archive": str(self.archive.resolve()),
            "source_archive_size_bytes": self.archive_size,
            "source_archive_sha256": self.archive_sha,
            "talenthub_release_manifest": str(self.manifest.resolve()),
            "private_runtime_root": str(self.runtime.resolve()),
            "project_engine_link": str(self.engine_link),
            "project_engine": str(self.engine.resolve()),
            "provider_posts": 0,
            "provider_secret_names_present": [],
        }
        self.bootstrap = _write_json(
            self.runtime / "runtime/receipts/storyclaw_bootstrap/bootstrap.json",
            self.bootstrap_payload,
        )
        wiring = [
            {
                "name": "episode_workspace",
                "target": str(self.engine / "workflow/nalu"),
                "backing": str(self.workspace_backing.resolve()),
                "state": "EXACT_SYMLINK",
                "same_storage_object": True,
                "storage_probe": {"write": "PASS", "fsync": "PASS", "flock_nonblocking": "PASS"},
            },
            {
                "name": "transaction_store",
                "target": str(self.engine / "workflow/tasks"),
                "backing": str(self.transactions_backing.resolve()),
                "state": "EXACT_SYMLINK",
                "same_storage_object": True,
                "storage_probe": {"write": "PASS", "fsync": "PASS", "flock_nonblocking": "PASS"},
            },
        ]
        self.install_payload = {
            "schema": smoke.INSTALL_SCHEMA,
            "status": "PASS",
            "engine": {
                "root": str(self.engine.resolve()), "head_commit": self.commit,
                "checkout_kind": "PACKAGE_VERIFIED_RELEASE_ARCHIVE",
                "immutable_tree_verified": True,
                "source_archive_sha256": self.archive_sha,
            },
            "base_engine": {
                "root": str(self.engine.resolve()), "head_commit": self.commit,
                "checkout_kind": "PACKAGE_VERIFIED_RELEASE_ARCHIVE",
                "immutable_tree_verified": True,
                "source_archive_sha256": self.archive_sha,
            },
            "project_view": {
                "base_engine_root": str(self.engine.resolve()),
                "engine_root": str(self.engine.resolve()), "commit": self.commit,
            },
            "project_engine_link": {"path": str(self.engine_link), "target": str(self.engine.resolve())},
            "isolation_mode": "PER_PROJECT_VERIFIED_ARCHIVE_VIEW",
            "runtime": {"root": str(self.runtime.resolve())},
            "wiring": wiring,
            "dependencies": {
                "requested": True, "status": "INSTALLED", "network_used": False,
                "dependency_profile": self.profile_id,
                "interpreter_facts": {"schema": "storyclaw.nalu.dependency_profile.v1"},
                "bundle_manifest_sha256": self.profile_manifest_sha,
                "bundle_archive_sha256": self.profile_archive_sha,
                "lock_sha256": "f" * 64,
                "installed_package_count": 5,
                "installed_inventory_sha256": "1" * 64,
                "pip_check": "PASS",
                "venv": str(self.venv.resolve()),
                "stable_python": str(self.selector / "bin/python"),
            },
            "venv_selector": {
                "status": "PASS", "path": str(self.selector),
                "target": str(self.venv.resolve()),
                "python": str(self.selector / "bin/python"),
                "resolved_python": str(self.python.resolve()),
            },
            "release_baseline": {
                **self.baseline_payload,
                "path": str(self.baseline.resolve()), "action": "BOUND",
            },
            "engine_seal": {"sealed": True, "writable_path_count": 0},
            "verification": {
                "status": "PASS", "tag": self.tag, "commit": self.commit,
                "storage_probe": "PASS",
            },
            "source_or_media_paths_touched": [],
            "secret_values_recorded": False,
        }
        self.install = _write_json(
            self.runtime / "runtime/receipts/storyclaw_host_install/install.json",
            self.install_payload,
        )
        checks = {
            name: {"status": "PASS"}
            for name in (
                "engine_root", "nalu_pipeline", "nalu_paths", "runtime_persistent",
                "storage_contract", "engine_code_read_only", "writer_layers_store",
                "portable_media", "portable_audio_provider", "portable_renderer",
                "stable_release_signature_verifier", "model", "policy_profile",
                "series_scope", "voice_registry",
            )
        }
        checks["workspace_store"] = {
            "status": "PASS", "mount_target": str(self.engine / "workflow/nalu"),
            "backing_path": str(self.workspace_backing.resolve()),
            "same_storage_object": True, "private_runtime_backing": True,
            "writable": True, "flock": True,
        }
        checks["transaction_store"] = {
            "status": "PASS", "mount_target": str(self.engine / "workflow/tasks"),
            "backing_path": str(self.transactions_backing.resolve()),
            "same_storage_object": True, "private_runtime_backing": True,
            "writable": True, "flock": True,
        }
        checks["paid_lock"] = {
            "status": "PASS", "paid_requests_enabled": False, "api_key_present": False,
        }
        self.preflight_payload = {
            "schema": smoke.PREFLIGHT_SCHEMA, "status": "PASS",
            "engine_commit": self.commit, "engine_root": str(self.engine.resolve()),
            "private_runtime_root": str(self.runtime.resolve()),
            "project_id": "test-project", "series_scope_id": "TEST-SCOPE",
            "checks": checks, "failures": [],
        }
        self.preflight = _write_json(
            self.runtime / smoke.SMOKE_PREFLIGHT_RELATIVE, self.preflight_payload
        )

        before_payload = json.loads(self.before.read_text())
        self.bootstrap_payload.update({
            "transactions_before_snapshot": str(self.before.resolve()),
            "transactions_before_snapshot_sha256": _sha(self.before),
            "transactions_before_tree_sha256": before_payload["tree_sha256"],
            "preflight_receipt": str(self.preflight.resolve()),
            "preflight_receipt_sha256": _sha(self.preflight),
        })
        _write_json(self.bootstrap, self.bootstrap_payload)
        provisional_bootstrap_sha = _sha(self.bootstrap)

        self.after = self.receipt_root / "transactions-after.json"
        saved_secrets = {
            name: os.environ.pop(name)
            for name in smoke.PROVIDER_SECRET_NAMES if name in os.environ
        }
        try:
            smoke.snapshot_transactions(
                self.runtime, self.after, label="after", prior_snapshot=self.before
            )
        finally:
            os.environ.update(saved_secrets)
        after_payload = json.loads(self.after.read_text())
        self.bootstrap_payload.update({
            "status": "PASS",
            "registry_clean_install_smoke_status": "SNAPSHOTS_PASS",
            "snapshot_bound_bootstrap_receipt_sha256": provisional_bootstrap_sha,
            "transactions_after_snapshot": str(self.after.resolve()),
            "transactions_after_snapshot_sha256": _sha(self.after),
            "transactions_after_tree_sha256": after_payload["tree_sha256"],
        })
        _write_json(self.bootstrap, self.bootstrap_payload)
        self.output = self.receipt_root / "registry-clean-install.json"
        self._seal_engine()

    def _write_registry_package(self) -> None:
        with zipfile.ZipFile(self.registry, "w", compression=zipfile.ZIP_DEFLATED) as package:
            for relative, body in sorted(self.bound_bodies.items()):
                package.writestr(relative, body)
            package.writestr(
                smoke.NESTED_MANIFEST,
                json.dumps(self.manifest_payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
            )

    def _seal_engine(self) -> None:
        for root_text, directories, files in os.walk(self.engine, topdown=False, followlinks=False):
            root = Path(root_text)
            for name in files:
                path = root / name
                if not path.is_symlink():
                    os.chmod(path, 0o444)
            for name in directories:
                path = root / name
                if not path.is_symlink():
                    os.chmod(path, 0o555)
            os.chmod(root, 0o555)

    def unseal_engine(self) -> None:
        if not self.engine.exists():
            return
        for root_text, directories, files in os.walk(self.engine, topdown=False, followlinks=False):
            root = Path(root_text)
            for name in [*files, *directories]:
                path = root / name
                if not path.is_symlink():
                    try:
                        os.chmod(path, 0o755 if path.is_dir() else 0o644)
                    except OSError:
                        pass
            try:
                os.chmod(root, 0o755)
            except OSError:
                pass

    def build(self) -> dict:
        return smoke.build_receipt(
            runtime_root=self.runtime,
            project_home=self.project_home,
            installed_agent_root=self.installed,
            artifact_root=self.artifacts,
            registry_package=self.registry,
            registry_package_url=self.registry_url,
            stable_index=self.index,
            stable_index_signature=self.index_signature,
            release_public_key=self.public_key,
            source_archive=self.archive,
            bootstrap_receipt=self.bootstrap,
            install_receipt=self.install,
            preflight_receipt=self.preflight,
            transactions_before_snapshot=self.before,
            transactions_after_snapshot=self.after,
            output=self.output,
        )

    def close(self) -> None:
        self.unseal_engine()
        smoke.SIGNING_KEY_SHA256 = self.original_signing_key_sha256
        self.temporary.cleanup()


class RegistryCleanInstallSmokeTests(unittest.TestCase):
    def test_registry_zip_traversal_and_member_bomb_block_before_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            traversal = root / "traversal.zip"
            with zipfile.ZipFile(traversal, "w") as archive:
                archive.writestr("skills/qingshan-nalu/../../../escape", b"x")
            with self.assertRaisesRegex(smoke.SmokeBlocked, "PATH_INVALID"):
                smoke._registry_package(
                    traversal, "https://assets.storyclaw.com/private/traversal.zip"
                )

            bomb = root / "member-bomb.zip"
            with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_STORED) as archive:
                for index in range(smoke.MAX_ZIP_MEMBERS + 1):
                    archive.writestr(f"skills/x/{index}.txt", b"x")
            with self.assertRaisesRegex(smoke.SmokeBlocked, "MEMBER_LIMIT"):
                smoke._registry_package(
                    bomb, "https://assets.storyclaw.com/private/member-bomb.zip"
                )

    def test_snapshot_refuses_any_provider_secret_in_environment(self):
        fixture = CleanInstallFixture()
        try:
            output = fixture.receipt_root / "secret-bearing-snapshot.json"
            with mock.patch.dict(os.environ, {"GIGGLE_API_KEY": "must-not-be-used"}):
                with self.assertRaisesRegex(
                    smoke.SmokeBlocked, "PROVIDER_SECRETS_PRESENT"
                ):
                    smoke.snapshot_transactions(fixture.runtime, output, label="before")
            self.assertFalse(output.exists())
        finally:
            fixture.close()

    def test_build_and_verify_return_hash_only_public_summary(self):
        fixture = CleanInstallFixture()
        try:
            result = fixture.build()
            self.assertEqual(result["schema"], smoke.SCHEMA)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(set(result), {"schema", "status", "hashes"})
            self.assertEqual(set(result["hashes"]), {
                "receipt_sha256", "facts_sha256", "release_identity_sha256",
                "registry_package_sha256", "registry_package_url_sha256",
                "nested_manifest_sha256", "stable_index_sha256",
                "stable_index_signature_sha256", "release_public_key_sha256",
                "source_archive_sha256", "bootstrap_receipt_sha256",
                "install_receipt_sha256", "preflight_receipt_sha256",
                "transactions_before_snapshot_sha256",
                "transactions_after_snapshot_sha256", "transactions_tree_sha256",
                "controls_sha256", "dependency_profile_sha256",
                "dependency_bundle_manifest_sha256",
                "dependency_bundle_archive_sha256",
            })
            for key, value in result["hashes"].items():
                self.assertTrue(key.endswith("sha256"), key)
                self.assertRegex(value, r"^[0-9a-f]{64}$")
            rendered = json.dumps(result, sort_keys=True)
            self.assertNotIn(str(fixture.root), rendered)
            self.assertNotIn("storyclaw.com", rendered)
            self.assertNotIn("test-project", rendered)
            self.assertEqual(smoke.verify_receipt(fixture.output), result)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(smoke.main(["verify", str(fixture.output)]), 0)
            cli_payload = json.loads(stdout.getvalue())
            self.assertEqual(cli_payload, result)
            self.assertNotIn(str(fixture.root), stdout.getvalue())
            self.assertNotIn("storyclaw.com", stdout.getvalue())
        finally:
            fixture.close()

    def test_each_bound_artifact_or_receipt_tamper_blocks(self):
        cases = {
            "registry_package": lambda f: self._append_bytes(f.registry, b"tamper"),
            "stable_index": lambda f: f.index.write_text("{}\n"),
            "stable_index_signature": lambda f: self._append_bytes(
                f.index_signature, b"tamper"
            ),
            "release_public_key": lambda f: self._replace_public_key(f),
            "source_archive": lambda f: self._append_bytes(f.archive, b"tamper"),
            "bootstrap_receipt": lambda f: self._mutate_json(f.bootstrap, "provider_posts", 1),
            "install_receipt": lambda f: self._mutate_json(f.install, "isolation_mode", "PER_PROJECT_WORKTREE_VIEW"),
            "preflight_receipt": lambda f: self._mutate_json(f.preflight, "status", "BLOCKED"),
            "before_snapshot": lambda f: self._mutate_json(f.before, "tree_sha256", "9" * 64),
            "after_snapshot": lambda f: self._mutate_json(f.after, "entry_count", 99),
            "installed_manifest": lambda f: self._append_bytes(f.manifest, b"tamper"),
        }
        for name, mutation in cases.items():
            with self.subTest(name=name):
                fixture = CleanInstallFixture()
                try:
                    fixture.build()
                    mutation(fixture)
                    with self.assertRaises(smoke.SmokeBlocked):
                        smoke.verify_receipt(fixture.output)
                finally:
                    fixture.close()

    def test_each_clean_install_control_tamper_blocks(self):
        def retarget_engine(f: CleanInstallFixture) -> None:
            f.engine_link.unlink()
            other = f.project_home / "engine/other"
            other.mkdir()
            os.symlink(other, f.engine_link)

        def retarget_mount(f: CleanInstallFixture, name: str) -> None:
            f.unseal_engine()
            target = f.engine / f"workflow/{name}"
            target.unlink()
            wrong = f.runtime / f"runtime/wrong-{name}"
            wrong.mkdir(parents=True)
            os.symlink(wrong, target)
            f._seal_engine()

        def retarget_venv(f: CleanInstallFixture) -> None:
            f.selector.unlink()
            wrong = f.runtime / "runtime/storyclaw_host/wrong-venv/bin"
            wrong.mkdir(parents=True)
            (wrong / "python").write_text("wrong\n")
            os.symlink(wrong.parent, f.selector)

        cases = {
            "future_engine_link": retarget_engine,
            "marker_engine": lambda f: self._mutate_json(f.marker, "engine_root", "/outside"),
            "config_engine": lambda f: self._mutate_nested(f.config, ("storyclaw", "storage", "engine_root"), "/outside"),
            "workspace_mount": lambda f: retarget_mount(f, "nalu"),
            "transactions_mount": lambda f: retarget_mount(f, "tasks"),
            "seal_receipt": lambda f: self._mutate_nested(f.install, ("engine_seal", "sealed"), False),
            "seal_actual": lambda f: self._make_engine_writable(f),
            "baseline": lambda f: self._mutate_json(f.baseline, "release_sequence", 99),
            "dependency_profile": lambda f: self._mutate_nested(f.install, ("dependencies", "dependency_profile"), "unbound-profile"),
            "venv_selector": retarget_venv,
            "provider_secret": lambda f: self._mutate_json(f.config, "GIGGLE_API_KEY", "secret-value"),
            "paid_enabled": lambda f: self._mutate_nested(f.config, ("generation", "paid_requests_enabled"), True),
            "transaction_changed": lambda f: (f.transactions_backing / "unexpected.json").write_text("{}\n"),
            "provider_posts": lambda f: self._mutate_json(f.bootstrap, "provider_posts", 1),
        }
        for name, mutation in cases.items():
            with self.subTest(name=name):
                fixture = CleanInstallFixture()
                try:
                    fixture.build()
                    mutation(fixture)
                    with self.assertRaises(smoke.SmokeBlocked):
                        smoke.verify_receipt(fixture.output)
                finally:
                    fixture.close()

    def test_symlink_and_path_escape_receipts_are_refused(self):
        fixture = CleanInstallFixture()
        try:
            fixture.build()
            outside = fixture.root / "outside-preflight.json"
            shutil.copy2(fixture.preflight, outside)
            fixture.preflight.unlink()
            os.symlink(outside, fixture.preflight)
            with self.assertRaisesRegex(smoke.SmokeBlocked, "PATH_INVALID"):
                smoke.verify_receipt(fixture.output)
        finally:
            fixture.close()

    @staticmethod
    def _mutate_json(path: Path, key: str, value: object) -> None:
        payload = json.loads(path.read_text())
        payload[key] = value
        _write_json(path, payload)

    @staticmethod
    def _mutate_nested(path: Path, keys: tuple[str, ...], value: object) -> None:
        payload = json.loads(path.read_text())
        cursor = payload
        for key in keys[:-1]:
            cursor = cursor[key]
        cursor[keys[-1]] = value
        _write_json(path, payload)

    @staticmethod
    def _make_engine_writable(fixture: CleanInstallFixture) -> None:
        fixture.unseal_engine()
        os.chmod(fixture.engine / "RELEASE_MANIFEST.json", 0o644)

    @staticmethod
    def _append_bytes(path: Path, body: bytes) -> None:
        with path.open("ab") as handle:
            handle.write(body)

    @staticmethod
    def _replace_public_key(fixture: CleanInstallFixture) -> None:
        fixture.unseal_engine()
        fixture.public_key.write_text("not the pinned public key\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
