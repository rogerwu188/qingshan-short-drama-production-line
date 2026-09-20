"""Signed stable-release discovery regression tests."""
from __future__ import annotations

import hashlib
import fcntl
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import storyclaw_release_discovery as discovery


class StoryClawReleaseDiscoveryTests(unittest.TestCase):
    @staticmethod
    def _dependency_bindings(tag: str):
        rows = []
        for index, profile in enumerate(discovery._dependency_bundle.SUPPORTED_PROFILES, 1):
            manifest = discovery._dependency_bundle.dependency_manifest_filename(
                tag, profile.profile_id
            )
            archive = discovery._dependency_bundle.dependency_archive_filename(
                tag, profile.profile_id
            )
            rows.append({
                "profile_id": profile.profile_id,
                "manifest_url": discovery._dependency_bundle.github_asset_url(tag, manifest),
                "manifest_size_bytes": 100 + index,
                "manifest_sha256": f"{index}" * 64,
                "archive_url": discovery._dependency_bundle.github_asset_url(tag, archive),
                "archive_size_bytes": 1000 + index,
                "archive_sha256": f"{index + 2}" * 64,
            })
        return rows

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.engine = self.root / "engine"
        self.runtime = self.root / "runtime"
        self.engine.mkdir()
        self.runtime.mkdir()
        subprocess.run(["git", "init", str(self.engine)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(self.engine), "config", "user.email", "test@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.engine), "config", "user.name", "Test"], check=True
        )
        (self.engine / "README.md").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.engine), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.engine), "commit", "-m", "fixture"],
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "-C", str(self.engine), "tag", "v1.0.0"], check=True)
        self.commit = subprocess.run(
            ["git", "-C", str(self.engine), "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        self.private_key = self.root / "private.pem"
        self.public_key = self.root / "public.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(self.private_key)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "openssl", "pkey", "-in", str(self.private_key), "-pubout", "-out",
                str(self.public_key),
            ],
            check=True,
            capture_output=True,
        )
        self.key_sha = hashlib.sha256(self.public_key.read_bytes()).hexdigest()

    def _signed_fixture(
        self,
        *,
        sequence: int = 2,
        commit: str = "2" * 40,
        tag: str = "v2.0.0",
        archive_sha: str = "a" * 64,
    ):
        channel_url = discovery._expected_asset_url(
            tag, f"qingshan-storyclaw-release-channel-{tag}.json"
        )
        archive_url = discovery._expected_asset_url(
            tag, f"qingshan-storyclaw-workflow-{tag}.tar.gz"
        )
        channel = {
            "schema": discovery.CHANNEL_SCHEMA,
            "immutable": True,
            "channel": "stable",
            "release_sequence": sequence,
            "release_tag": tag,
            "git_commit": commit,
            "source_archive_url": archive_url,
            "source_archive_size_bytes": 1234,
            "source_archive_sha256": archive_sha,
            "update_class": "ENGINE_ONLY",
            "validation_receipt_status": "PASS",
            "validation_receipt_sha256": "b" * 64,
            "release_signing_key_sha256": self.key_sha,
            "dependencies_changed": False,
            "dependency_profiles_action": "REUSE_CURRENT",
            "dependency_profiles": [],
        }
        channel_bytes = json.dumps(channel, sort_keys=True).encode() + b"\n"
        index = {
            "schema": discovery.SCHEMA,
            "channel": "stable",
            "release_sequence": sequence,
            "release_tag": tag,
            "git_commit": commit,
            "update_class": "ENGINE_ONLY",
            "release_channel_url": channel_url,
            "release_channel_size_bytes": len(channel_bytes),
            "release_channel_sha256": hashlib.sha256(channel_bytes).hexdigest(),
            "source_archive_url": archive_url,
            "source_archive_size_bytes": 1234,
            "source_archive_sha256": archive_sha,
            "validation_receipt_status": "PASS",
            "validation_receipt_sha256": "b" * 64,
            "signing_key_sha256": self.key_sha,
            "generated_at": "2026-09-20T00:00:00Z",
        }
        index_bytes = json.dumps(index, sort_keys=True).encode() + b"\n"
        index_path = self.root / "index.json"
        signature_path = self.root / "index.json.sig"
        index_path.write_bytes(index_bytes)
        subprocess.run(
            [
                "openssl", "pkeyutl", "-sign", "-inkey", str(self.private_key),
                "-rawin", "-in", str(index_path), "-out", str(signature_path),
            ],
            check=True,
            capture_output=True,
        )
        return index_bytes, signature_path.read_bytes(), channel_bytes, channel_url

    def _package(self, *, sequence: int = 1) -> Path:
        path = self.root / "RELEASE_MANIFEST.json"
        path.write_text(json.dumps({
            "schema": discovery.TALENTHUB_RELEASE_SCHEMA,
            "agent_id": discovery.AGENT_ID,
            "skill": discovery.SKILL_NAME,
            "release_sequence": sequence,
            "release_tag": "v1.0.0",
            "git_commit": self.commit,
            "release_channel_update_class": "ENGINE_ONLY",
            "release_channel_sha256": "c" * 64,
            "source_archive_size_bytes": 1000,
            "source_archive_sha256": "d" * 64,
            "validation_receipt_status": "PASS",
            "validation_receipt_sha256": "e" * 64,
            "release_signing_key_sha256": self.key_sha,
            "dependency_profiles_action": "REPLACE_WITH_RELEASE_BUNDLES",
            "dependency_profiles": self._dependency_bindings("v1.0.0"),
        }) + "\n", encoding="utf-8")
        state_path = self.runtime / discovery.CURRENT_RELEASE_STATE_RELATIVE
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            "schema": discovery.CURRENT_RELEASE_STATE_SCHEMA,
            "status": "PASS",
            "release_sequence": sequence,
            "release_tag": "v1.0.0",
            "git_commit": self.commit,
            "signing_key_sha256": self.key_sha,
            "talenthub_release_manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }) + "\n", encoding="utf-8")
        return path

    def test_signed_index_discovers_and_caches_exact_immutable_channel(self):
        index, signature, channel, channel_url = self._signed_fixture()
        mapping = {
            discovery.STABLE_INDEX_URL: index,
            discovery.STABLE_SIGNATURE_URL: signature,
            channel_url: channel,
        }
        with mock.patch.object(discovery, "TRUSTED_PUBLIC_KEY_SHA256", self.key_sha):
            result = discovery.discover_stable_release(
                self.engine,
                self.runtime,
                self._package(),
                public_key=self.public_key,
                fetcher=lambda url, _limit: mapping[url],
            )
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["trusted_release_sequence"], 2)
        self.assertEqual(result["provider_posts"], 0)
        channel_path = Path(result["channel_manifest"])
        self.assertTrue(channel_path.resolve().is_relative_to(self.runtime.resolve()))
        self.assertEqual(channel_path.read_bytes(), channel)

    def test_dedicated_channel_tag_at_engine_commit_is_not_engine_identity(self):
        subprocess.run(
            ["git", "-C", str(self.engine), "tag", discovery.STABLE_CHANNEL_RELEASE_TAG],
            check=True,
            capture_output=True,
        )
        self.assertEqual(
            discovery._current_engine_identity(self.engine),
            ("v1.0.0", self.commit),
        )

    def test_tampered_index_fails_signature_before_channel_is_trusted(self):
        index, signature, channel, channel_url = self._signed_fixture()
        tampered = index.replace(b'"ENGINE_ONLY"', b'"TALENTHUB_PACKAGE_REQUIRED"')
        mapping = {
            discovery.STABLE_INDEX_URL: tampered,
            discovery.STABLE_SIGNATURE_URL: signature,
            channel_url: channel,
        }
        with mock.patch.object(discovery, "TRUSTED_PUBLIC_KEY_SHA256", self.key_sha):
            with self.assertRaisesRegex(discovery.DiscoveryBlocked, "STABLE_INDEX_SIGNATURE_INVALID"):
                discovery.discover_stable_release(
                    self.engine,
                    self.runtime,
                    self._package(),
                    public_key=self.public_key,
                    fetcher=lambda url, _limit: mapping[url],
                )

    def test_package_manifest_modified_after_install_is_blocked_by_private_baseline(self):
        package = self._package()
        payload = json.loads(package.read_text())
        payload["validation_receipt_sha256"] = "9" * 64
        package.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        index, signature, channel, channel_url = self._signed_fixture()
        mapping = {
            discovery.STABLE_INDEX_URL: index,
            discovery.STABLE_SIGNATURE_URL: signature,
            channel_url: channel,
        }
        with mock.patch.object(discovery, "TRUSTED_PUBLIC_KEY_SHA256", self.key_sha):
            with self.assertRaisesRegex(
                discovery.DiscoveryBlocked, "CURRENT_RELEASE_BASELINE_MISMATCH"
            ):
                discovery.discover_stable_release(
                    self.engine,
                    self.runtime,
                    package,
                    public_key=self.public_key,
                    fetcher=lambda url, _limit: mapping[url],
                )

    def test_signed_replay_below_installed_sequence_is_blocked(self):
        index, signature, channel, channel_url = self._signed_fixture(sequence=1)
        mapping = {
            discovery.STABLE_INDEX_URL: index,
            discovery.STABLE_SIGNATURE_URL: signature,
            channel_url: channel,
        }
        with mock.patch.object(discovery, "TRUSTED_PUBLIC_KEY_SHA256", self.key_sha):
            with self.assertRaisesRegex(discovery.DiscoveryBlocked, "STABLE_INDEX_ROLLBACK"):
                discovery.discover_stable_release(
                    self.engine,
                    self.runtime,
                    self._package(sequence=2),
                    public_key=self.public_key,
                    fetcher=lambda url, _limit: mapping[url],
                )

    def test_same_sequence_different_signed_binding_is_blocked(self):
        first = self._signed_fixture(sequence=2)
        first_mapping = {
            discovery.STABLE_INDEX_URL: first[0],
            discovery.STABLE_SIGNATURE_URL: first[1],
            first[3]: first[2],
        }
        with mock.patch.object(discovery, "TRUSTED_PUBLIC_KEY_SHA256", self.key_sha):
            discovery.discover_stable_release(
                self.engine,
                self.runtime,
                self._package(),
                public_key=self.public_key,
                fetcher=lambda url, _limit: first_mapping[url],
            )
            second = self._signed_fixture(sequence=2, archive_sha="f" * 64)
            second_mapping = {
                discovery.STABLE_INDEX_URL: second[0],
                discovery.STABLE_SIGNATURE_URL: second[1],
                second[3]: second[2],
            }
            with self.assertRaisesRegex(
                discovery.DiscoveryBlocked, "STABLE_INDEX_SEQUENCE_EQUIVOCATION"
            ):
                discovery.discover_stable_release(
                    self.engine,
                    self.runtime,
                    self._package(),
                    public_key=self.public_key,
                    fetcher=lambda url, _limit: second_mapping[url],
                )

    def test_same_commit_different_package_tag_is_not_a_baseline(self):
        subprocess.run(
            ["git", "-C", str(self.engine), "tag", "-d", "v1.0.0"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(self.engine), "tag", "alias-v1"],
            check=True,
            capture_output=True,
        )
        index, signature, channel, channel_url = self._signed_fixture()
        mapping = {
            discovery.STABLE_INDEX_URL: index,
            discovery.STABLE_SIGNATURE_URL: signature,
            channel_url: channel,
        }
        with mock.patch.object(discovery, "TRUSTED_PUBLIC_KEY_SHA256", self.key_sha):
            with self.assertRaisesRegex(
                discovery.DiscoveryBlocked, "CURRENT_RELEASE_BASELINE_MISMATCH"
            ):
                discovery.discover_stable_release(
                    self.engine,
                    self.runtime,
                    self._package(),
                    public_key=self.public_key,
                    fetcher=lambda url, _limit: mapping[url],
                )

    def test_discovery_lock_and_private_path_symlink_fail_closed(self):
        lock = self.runtime / discovery.DISCOVERY_LOCK_RELATIVE
        lock.parent.mkdir(parents=True)
        with lock.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(
                discovery.DiscoveryBlocked, "DISCOVERY_ALREADY_RUNNING"
            ):
                discovery.discover_stable_release(
                    self.engine, self.runtime, self._package()
                )
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

        lock.unlink()
        lock.parent.rmdir()
        outside = self.root / "outside"
        outside.mkdir()
        os.symlink(
            outside,
            self.runtime / discovery.DISCOVERY_ROOT_RELATIVE,
        )
        with self.assertRaisesRegex(
            discovery.DiscoveryBlocked, "DISCOVERY_PRIVATE_DIRECTORY_INVALID"
        ):
            discovery.discover_stable_release(
                self.engine, self.runtime, self._package()
            )

    def test_pinned_repository_public_key_matches_compiled_trust_root(self):
        key = Path(discovery.__file__).resolve().parents[1] / discovery.TRUSTED_PUBLIC_KEY_RELATIVE
        self.assertTrue(key.is_file())
        self.assertEqual(
            hashlib.sha256(key.read_bytes()).hexdigest(),
            discovery.TRUSTED_PUBLIC_KEY_SHA256,
        )

    def test_checked_in_probe_proves_openssl_ed25519_readiness(self):
        repository = Path(discovery.__file__).resolve().parents[1]
        result = discovery.verifier_readiness(repository)
        self.assertEqual(result["status"], "PASS", result)

        unavailable = discovery.verifier_readiness(
            repository,
            runner=lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1),
        )
        self.assertEqual(unavailable["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
