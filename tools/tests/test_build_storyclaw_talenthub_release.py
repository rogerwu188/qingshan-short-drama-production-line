import importlib.util
import hashlib
import http.server
import io
import json
import os
import subprocess
import shutil
import sys
import tarfile
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tools.deployment_code_integrity import verify as verify_deployment_inventory


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools/build_storyclaw_talenthub_release.py"
SPEC = importlib.util.spec_from_file_location("storyclaw_release", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class StoryClawTalentHubReleaseTest(unittest.TestCase):
    def test_immutable_package_candidate_always_builds_dependency_bundles(self):
        decide = MODULE.should_build_dependency_bundles
        self.assertTrue(decide(
            package_publish_required=True,
            allow_unreleased=False,
            validation_present=False,
            explicitly_requested=False,
        ))
        self.assertFalse(decide(
            package_publish_required=True,
            allow_unreleased=True,
            validation_present=False,
            explicitly_requested=False,
        ))
        self.assertTrue(decide(
            package_publish_required=True,
            allow_unreleased=True,
            validation_present=False,
            explicitly_requested=True,
        ))
        self.assertTrue(decide(
            package_publish_required=True,
            allow_unreleased=True,
            validation_present=True,
            explicitly_requested=False,
        ))
        self.assertFalse(decide(
            package_publish_required=False,
            allow_unreleased=False,
            validation_present=True,
            explicitly_requested=True,
        ))

    def test_documented_direct_cli_entrypoint_imports_repository_modules(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/build_storyclaw_talenthub_release.py"), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--registry-smoke-receipt", result.stdout)

    def test_talenthub_0_4_11_real_zip_and_install_roundtrip_uses_nested_manifest(self):
        talenthub = shutil.which("talenthub")
        if talenthub is None:
            self.skipTest("TalentHub CLI is unavailable")
        version = subprocess.run(
            [talenthub, "--version"], text=True, capture_output=True, check=False
        )
        if version.returncode != 0 or version.stdout.strip() != "0.4.11":
            self.skipTest("roundtrip is pinned to TalentHub CLI 0.4.11")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            skill = workspace / "skills/qingshan-nalu"
            skill.mkdir(parents=True)
            (workspace / "manifest.json").write_text(json.dumps({
                "id": "roundtrip-agent", "name": "Roundtrip", "emoji": "R",
            }))
            (workspace / "AGENTS.md").write_text("roundtrip brain\n")
            (workspace / "RELEASE_MANIFEST.json").write_text("top-level must be omitted\n")
            (skill / "SKILL.md").write_text("---\nname: qingshan-nalu\n---\n")
            nested_bytes = b'{"schema":"qingshan.storyclaw.talenthub.release.v1"}\n'
            (skill / "RELEASE_MANIFEST.json").write_bytes(nested_bytes)
            package = root / "agent.zip"
            MODULE._build_expected_talenthub_zip(workspace, package)
            with zipfile.ZipFile(package) as archive:
                names = set(archive.namelist())
                self.assertIn("skills/qingshan-nalu/RELEASE_MANIFEST.json", names)
                self.assertNotIn("RELEASE_MANIFEST.json", names)

            package_bytes = package.read_bytes()
            manifest_path = "/api/talenthub/registry/roundtrip-agent"

            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):  # noqa: N802 - stdlib callback spelling
                    if self.path == manifest_path:
                        payload = json.dumps({
                            "id": "roundtrip-agent", "name": "Roundtrip", "emoji": "R",
                            "version": "2026.09.20-1",
                            "zip_url": f"http://127.0.0.1:{self.server.server_port}/agent.zip",
                        }).encode()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(payload)))
                        self.end_headers()
                        self.wfile.write(payload)
                    elif self.path == "/agent.zip":
                        self.send_response(200)
                        self.send_header("Content-Type", "application/zip")
                        self.send_header("Content-Length", str(len(package_bytes)))
                        self.end_headers()
                        self.wfile.write(package_bytes)
                    else:
                        self.send_error(404)

                def log_message(self, _format, *_args):
                    pass

            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                state = root / "state"
                env = os.environ.copy()
                env.update({
                    "OPENCLAW_HOME": str(root / "home"),
                    "OPENCLAW_STATE_DIR": str(state),
                    "TALENTHUB_URL": f"http://127.0.0.1:{server.server_port}",
                })
                installed = subprocess.run(
                    [talenthub, "agent", "install", "roundtrip-agent", "--json"],
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()
            self.assertEqual(installed.returncode, 0, installed.stderr + installed.stdout)
            installed_root = state / "workspace-roundtrip-agent"
            self.assertEqual(
                (installed_root / "skills/qingshan-nalu/RELEASE_MANIFEST.json").read_bytes(),
                nested_bytes,
            )
            self.assertFalse((installed_root / "RELEASE_MANIFEST.json").exists())

    @staticmethod
    def _dependency_bindings(tag: str) -> list[dict[str, object]]:
        rows = []
        for index, profile in enumerate(MODULE._dependency_bundle.SUPPORTED_PROFILES, 1):
            manifest_name = MODULE._dependency_bundle.dependency_manifest_filename(
                tag, profile.profile_id
            )
            archive_name = MODULE._dependency_bundle.dependency_archive_filename(
                tag, profile.profile_id
            )
            rows.append({
                "profile_id": profile.profile_id,
                "manifest_url": MODULE._dependency_bundle.github_asset_url(tag, manifest_name),
                "manifest_size_bytes": 100 + index,
                "manifest_sha256": f"{index}" * 64,
                "archive_url": MODULE._dependency_bundle.github_asset_url(tag, archive_name),
                "archive_size_bytes": 1000 + index,
                "archive_sha256": f"{index + 2}" * 64,
            })
        return rows

    @staticmethod
    def _archive_with(tmp: str, files: dict[str, bytes]) -> Path:
        path = Path(tmp) / "candidate.tar.gz"
        with tarfile.open(path, "w:gz") as tar:
            root = tarfile.TarInfo("qingshan-storyclaw-workflow")
            root.type = tarfile.DIRTYPE
            tar.addfile(root)
            for relative, payload in files.items():
                info = tarfile.TarInfo(f"qingshan-storyclaw-workflow/{relative}")
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
        return path

    @staticmethod
    def _validation_receipt(tmp: str, commit: str) -> Path:
        root = Path(tmp)
        private_title = "PRIVATE_ACCEPTANCE_SOURCE_TITLE"
        private_source_sha = hashlib.sha256(b"private acceptance source").hexdigest()
        checks = {}
        for name in MODULE.VALIDATION_CHECKS:
            evidence = root / f"{name}.json"
            evidence.write_text(json.dumps({"check": name, "status": "PASS"}) + "\n")
            checks[name] = {
                "status": "PASS",
                "evidence_path": evidence.name,
                "evidence_sha256": MODULE.sha256(evidence),
            }
        checks["s5_dry_run"]["paid_posts"] = 0
        checks["two_unit_paid_trial"]["unit_count"] = 2
        checks["ledger_reconciliation"]["reconciled"] = True
        receipt = root / "private-validation.json"
        receipt.write_text(
            json.dumps(
                {
                    "schema": MODULE.VALIDATION_SCHEMA,
                    "status": "PASS",
                    "release_commit": commit,
                    "remote_engine_commit": commit,
                    "remote_worktree_clean": True,
                    "remote_diff_sha256": MODULE.EMPTY_SHA256,
                    "private_fixture_title": private_title,
                    "private_source_sha256": private_source_sha,
                    "private_validation_contents_included_in_public_release": False,
                    "checks": checks,
                }
            )
            + "\n"
        )
        return receipt

    def test_candidate_dependencies_do_not_grant_validation_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            profiles = self._dependency_bindings("v-test")
            _, channel = MODULE.write_release_channel_manifest(
                Path(tmp), tag="v-test", commit="a" * 40,
                archive_sha256="b" * 64, archive_size=12345,
                dependency_profiles=profiles,
            )
            workspace = MODULE.write_talenthub_workspace(
                Path(tmp), "v-test", "a" * 40, "b" * 64,
                archive_size=12345, origin_tag_commit="a" * 40, validation=None,
                release_channel=channel, dependency_profiles=profiles,
            )
            release = json.loads((
                workspace / "skills/qingshan-nalu/RELEASE_MANIFEST.json"
            ).read_text())
            self.assertTrue(release["dependency_profiles"])
            self.assertIsNone(release["validation_receipt_status"])
            self.assertIsNone(release["validation_receipt_sha256"])
            self.assertIsNone(release["stable_index_sha256"])

    def test_workspace_contains_pinned_skill_and_public_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            _channel_path, channel = MODULE.write_release_channel_manifest(
                Path(tmp),
                tag="v-test",
                commit="a" * 40,
                archive_sha256="b" * 64,
                archive_size=12345,
            )
            workspace = MODULE.write_talenthub_workspace(
                Path(tmp),
                "v-test",
                "a" * 40,
                "b" * 64,
                archive_size=12345,
                validation={
                    "schema": MODULE.VALIDATION_SCHEMA,
                    "status": "PASS",
                    "sha256": "c" * 64,
                    "checks": {name: "PASS" for name in MODULE.VALIDATION_CHECKS},
                },
                origin_tag_commit="a" * 40,
                release_channel=channel,
                dependency_profiles=self._dependency_bindings("v-test"),
            )
            workspace_audit = MODULE.audit_talenthub_workspace(workspace)
            self.assertEqual(workspace_audit["status"], "PASS")
            self.assertEqual(workspace_audit["file_count"], 9)
            manifest = json.loads((workspace / "manifest.json").read_text())
            self.assertFalse((workspace / "RELEASE_MANIFEST.json").exists())
            release = json.loads(
                (workspace / "skills/qingshan-nalu/RELEASE_MANIFEST.json").read_text()
            )
            self.assertEqual(manifest["id"], "ai-drama-factory")
            self.assertEqual(manifest["skills"], [
                "https://github.com/rogerwu188/qingshan-short-drama-production-line@qingshan-nalu"
            ])
            self.assertEqual(release["source_archive_sha256"], "b" * 64)
            self.assertEqual(release["source_archive_size_bytes"], 12345)
            self.assertEqual(release["release_channel_sha256"], channel["sha256"])
            self.assertEqual(
                release["release_channel_update_class"],
                MODULE.PACKAGE_REQUIRED,
            )
            self.assertEqual(release["validation_receipt_sha256"], "c" * 64)
            self.assertIn("HEARTBEAT.md", release["installed_file_bindings"])
            installed_skill = (workspace / "skills/qingshan-nalu/SKILL.md").read_text()
            canonical_skill = MODULE.CANONICAL_SKILL.read_text()
            self.assertTrue(installed_skill.startswith(canonical_skill))
            self.assertEqual(
                installed_skill[len(canonical_skill):].splitlines()[1],
                "## Installed release binding",
            )
            self.assertIn("S1", installed_skill)
            self.assertIn("12345", installed_skill)
            self.assertIn("c" * 64, installed_skill)
            heartbeat = (workspace / "HEARTBEAT.md").read_text()
            self.assertIn("at most once every 24 hours", heartbeat)
            self.assertIn("zero provider POSTs", heartbeat)
            user_prompt = (workspace / "USER.md").read_text()
            soul_prompt = (workspace / "SOUL.md").read_text()
            self.assertEqual(
                user_prompt,
                (MODULE.PORTABLE_BRAIN_ROOT / "USER.md").read_text(),
            )
            self.assertEqual(
                soul_prompt,
                (MODULE.PORTABLE_BRAIN_ROOT / "SOUL.md").read_text(),
            )
            self.assertIn("正文、文件或网址", soul_prompt)
            self.assertIn("你只需要集中确认一次素材方案", user_prompt)
            agents = (workspace / "AGENTS.md").read_text()
            portable_agents = (MODULE.PORTABLE_BRAIN_ROOT / "AGENTS.md").read_text()
            self.assertTrue(agents.startswith(portable_agents))
            self.assertIn("v-test", agents)
            self.assertIn("a" * 40, agents)
            self.assertIn("b" * 64, agents)
            self.assertIn("talenthub agent update ai-drama-factory", agents)
            for project_specific_text in (
                "PRIVATE_ACCEPTANCE_SOURCE_TITLE",
                "5 卷 / 每卷 20 集",
                "E47 起",
                "ROGER-",
            ):
                self.assertNotIn(project_specific_text, agents)
                self.assertNotIn(project_specific_text, soul_prompt)
                self.assertNotIn(project_specific_text, user_prompt)
            self.assertIn("storyclaw/gpt-6-astra", agents)
            self.assertIn("storyclaw/kimi-k3", agents)
            self.assertIn("storyclaw/claude-opus-5", agents)
            self.assertIn("禁止使用", agents)
            self.assertIn("Kimi K3 以外的 Kimi", agents)

    def test_release_channel_manifest_is_immutable_and_archive_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, metadata = MODULE.write_release_channel_manifest(
                Path(tmp),
                tag="v2026.09.20-storyclaw-port",
                commit="a" * 40,
                archive_sha256="b" * 64,
                archive_size=4567,
                update_class="ENGINE_ONLY",
            )
            payload = json.loads(path.read_text())
            self.assertEqual(payload["schema"], MODULE.RELEASE_CHANNEL_SCHEMA)
            self.assertTrue(payload["immutable"])
            self.assertEqual(
                payload["source_ref"],
                "refs/tags/v2026.09.20-storyclaw-port",
            )
            self.assertEqual(payload["source_archive_sha256"], "b" * 64)
            self.assertEqual(payload["source_archive_size_bytes"], 4567)
            self.assertEqual(
                payload["talenthub_update_command"],
                "talenthub agent update ai-drama-factory",
            )
            self.assertEqual(payload["update_class"], "ENGINE_ONLY")
            self.assertEqual(metadata["sha256"], MODULE.sha256(path))
            self.assertEqual(metadata["size_bytes"], path.stat().st_size)
            self.assertIn(
                MODULE.release_channel_filename("v2026.09.20-storyclaw-port"),
                metadata["url"],
            )

    def test_release_channel_defaults_fail_closed_to_talenthub_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            _path, metadata = MODULE.write_release_channel_manifest(
                Path(tmp),
                tag="v-initial",
                commit="c" * 40,
                archive_sha256="d" * 64,
                archive_size=1,
            )
            self.assertEqual(metadata["update_class"], MODULE.PACKAGE_REQUIRED)
            with self.assertRaises(SystemExit):
                MODULE.write_release_channel_manifest(
                    Path(tmp),
                    tag="v-bad",
                    commit="c" * 40,
                    archive_sha256="d" * 64,
                    archive_size=1,
                    update_class="ENGINE_ONLY",
                    dependencies_changed=True,
                )

    def test_signed_stable_index_binds_validated_immutable_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private = root / "private.pem"
            public = root / "public.pem"
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
                check=True,
                capture_output=True,
            )
            public_sha = hashlib.sha256(public.read_bytes()).hexdigest()
            channel_path = root / "channel.json"
            channel_path.write_text("{}\n", encoding="utf-8")
            channel = {
                "path": str(channel_path),
                "url": MODULE.github_release_channel_url("v2.0.0"),
                "size_bytes": channel_path.stat().st_size,
                "sha256": MODULE.sha256(channel_path),
                "update_class": "ENGINE_ONLY",
            }
            with mock.patch.object(MODULE, "git", return_value="0"):
                index_path, signature_path, metadata = MODULE.write_signed_stable_index(
                    root,
                    tag="v2.0.0",
                    commit="2" * 40,
                    release_sequence=2,
                    archive_sha256="a" * 64,
                    archive_size=1234,
                    release_channel=channel,
                    update_class="ENGINE_ONLY",
                    validation={"status": "PASS", "sha256": "b" * 64},
                    signing_key=private,
                    public_key=public,
                    expected_public_key_sha256=public_sha,
                )
            verified = subprocess.run(
                [
                    "openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(public),
                    "-rawin", "-in", str(index_path), "-sigfile", str(signature_path),
                ],
                check=False,
                capture_output=True,
            )
            self.assertEqual(verified.returncode, 0)
            payload = json.loads(index_path.read_text())
            self.assertEqual(payload["release_sequence"], 2)
            self.assertEqual(payload["validation_receipt_status"], "PASS")
            self.assertEqual(payload["signing_key_sha256"], public_sha)
            self.assertEqual(metadata["signature_size_bytes"], 64)
            private.chmod(0o644)
            with mock.patch.object(MODULE, "git", return_value="0"), self.assertRaisesRegex(
                SystemExit, "permissions"
            ):
                MODULE.write_signed_stable_index(
                    root, tag="v2.0.0", commit="2" * 40, release_sequence=2,
                    archive_sha256="a" * 64, archive_size=1234,
                    release_channel=channel, update_class="ENGINE_ONLY",
                    validation={"status": "PASS", "sha256": "b" * 64},
                    signing_key=private, public_key=public,
                    expected_public_key_sha256=public_sha,
                )
            private.chmod(0o600)
            linked_key = root / "linked-private.pem"
            os.symlink(private, linked_key)
            with mock.patch.object(MODULE, "git", return_value="0"), self.assertRaisesRegex(
                SystemExit, "non-symlink"
            ):
                MODULE.write_signed_stable_index(
                    root, tag="v2.0.0", commit="2" * 40, release_sequence=2,
                    archive_sha256="a" * 64, archive_size=1234,
                    release_channel=channel, update_class="ENGINE_ONLY",
                    validation={"status": "PASS", "sha256": "b" * 64},
                    signing_key=linked_key, public_key=public,
                    expected_public_key_sha256=public_sha,
                )

    def test_talenthub_publish_requires_exact_github_release_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = []
            source_by_name = {}
            for index, name in enumerate(("archive.tar.gz", "channel.json", "index.json", "index.sig")):
                path = root / name
                path.write_bytes(f"asset-{index}".encode())
                expected.append(path)
                source_by_name[name] = path

            def runner(command, **_kwargs):
                pattern = command[command.index("--pattern") + 1]
                destination = Path(command[command.index("--dir") + 1])
                shutil.copy2(source_by_name[pattern], destination / pattern)
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            result = MODULE.verify_published_github_assets(
                "v2.0.0", tuple(expected), runner=runner
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(len(result["assets"]), 4)

    def test_formal_publish_base_is_exact_signed_stable_or_true_initial(self):
        stable = {"release_tag": "v2.0.0", "git_commit": "2" * 40}
        self.assertEqual(
            MODULE.resolve_publish_classification_base(None, False, stable),
            ("v2.0.0", False),
        )
        with self.assertRaisesRegex(SystemExit, "differs from the signed"):
            MODULE.resolve_publish_classification_base("v2.1.0", False, stable)
        with self.assertRaisesRegex(SystemExit, "initial-release is forbidden"):
            MODULE.resolve_publish_classification_base(None, True, stable)
        self.assertEqual(
            MODULE.resolve_publish_classification_base(None, True, None),
            (None, True),
        )
        with self.assertRaisesRegex(SystemExit, "must use --initial-release"):
            MODULE.resolve_publish_classification_base(None, False, None)

    def test_talenthub_registry_package_must_match_local_cli_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()

            def build(_workspace, destination):
                destination.write_bytes(b"deterministic-talenthub-zip")

            output = "Package: https://assets.storyclaw.com/public/agent.zip\n"
            report = MODULE.verify_talenthub_registry_package(
                workspace,
                output,
                fetcher=lambda _url, _limit: b"deterministic-talenthub-zip",
                expected_builder=build,
            )
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(
                report["sha256"],
                hashlib.sha256(b"deterministic-talenthub-zip").hexdigest(),
            )
            with self.assertRaisesRegex(SystemExit, "differs"):
                MODULE.verify_talenthub_registry_package(
                    workspace,
                    output,
                    fetcher=lambda _url, _limit: b"wrong-registry-zip",
                    expected_builder=build,
                )
            with self.assertRaisesRegex(SystemExit, "non-canonical"):
                MODULE.verify_talenthub_registry_package(
                    workspace,
                    "Package: https://evil.example/agent.zip\n",
                    fetcher=lambda _url, _limit: b"deterministic-talenthub-zip",
                    expected_builder=build,
                )

    def test_unclassified_or_initial_release_requires_full_talenthub_package(self):
        impact = MODULE.release_impact(
            None,
            target_ref="v2026.09.20-storyclaw-port",
            initial_release=True,
        )
        self.assertEqual(impact["update_class"], MODULE.PACKAGE_REQUIRED)
        self.assertFalse(impact["engine_only_eligible"])
        self.assertEqual(
            impact["reasons"][0]["code"],
            "INITIAL_OR_UNCLASSIFIED_RELEASE",
        )
        with self.assertRaises(SystemExit):
            MODULE.release_impact(
                "v-old",
                target_ref="v-new",
                initial_release=True,
            )

    def test_release_impact_uses_immutable_classifier(self):
        classified = {
            "schema": "storyclaw.nalu.upgrade_impact.v1",
            "base": {"input": "v-old", "commit": "a" * 40},
            "target": {"input": "v-new", "commit": "b" * 40},
            "update_class": "ENGINE_ONLY",
            "dependencies_changed": False,
            "runtime_schema_changed": False,
            "runtime_migration": "NONE",
            "changed_paths": ["engine.py"],
            "reasons": [{"code": "ENGINE_CODE_CHANGE"}],
        }
        with mock.patch.object(MODULE, "classify_release", return_value=classified) as classify:
            result = MODULE.release_impact(
                "v-old", target_ref="v-new", initial_release=False
            )
        classify.assert_called_once_with("v-old", "v-new", root=MODULE.ROOT)
        self.assertEqual(result["update_class"], "ENGINE_ONLY")

    def test_portable_manifest_has_each_generic_storyclaw_surface_once(self):
        audit = MODULE.validate_portable_release_manifest()
        payload = json.loads(MODULE.PORTABLE_MANIFEST.read_text())
        required_files = payload["required_files"]
        test_modules = payload["portable_test_modules"]
        self.assertEqual(len(required_files), len(set(required_files)))
        self.assertEqual(len(test_modules), len(set(test_modules)))
        self.assertEqual(audit["required_file_count"], len(required_files))
        self.assertEqual(audit["test_module_count"], len(test_modules))
        for relative in MODULE.REQUIRED_STORYCLAW_PORTABLE_FILES:
            self.assertEqual(required_files.count(relative), 1, relative)
        for module in MODULE.REQUIRED_STORYCLAW_TEST_MODULES:
            self.assertEqual(test_modules.count(module), 1, module)
        self.assertFalse(
            set(required_files) & MODULE.FORBIDDEN_PORTABLE_MANIFEST_FILES
        )
        self.assertFalse(
            set(test_modules) & MODULE.FORBIDDEN_PORTABLE_TEST_MODULES
        )

    def test_portable_archive_selection_excludes_unrelated_episode_replay(self):
        manifest = json.dumps({
            "schema": "qingshan.portable_core_manifest.v1",
            "version": "0.5.0",
            "required_files": [
                "configs/PORTABLE_CORE_MANIFEST.json",
                "configs/GATE_REGISTRY_v3_20260716.json",
                "tools/generic_gate.py",
            ],
            "portable_test_modules": ["tools.tests.test_generic_gate"],
        }).encode()
        registry = json.dumps({"schema": "test.registry", "gates": []}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive_with(tmp, {
                "configs/PORTABLE_CORE_MANIFEST.json": manifest,
                "configs/GATE_REGISTRY_v3_20260716.json": registry,
                "configs/ENGINEERING_KNOWLEDGE_V1.json": b'{"entries":[]}\n',
                "tools/generic_gate.py": b"pass\n",
                "tools/tests/test_generic_gate.py": b"pass\n",
                "tools/e40_one_off_episode_repair.py": b"pass\n",
                "lines/nalu/runtime/tools/ingest_yewujiang_source.py": b"pass\n",
                "workflow/time_ledger/E17_time_ledger.json": b"{}\n",
            })
            with tarfile.open(archive, "r:gz") as source:
                selected, facts = MODULE.portable_archive_files(source)
        self.assertIn("tools/generic_gate.py", selected)
        self.assertIn("tools/tests/test_generic_gate.py", selected)
        self.assertNotIn("tools/e40_one_off_episode_repair.py", selected)
        self.assertNotIn("lines/nalu/runtime/tools/ingest_yewujiang_source.py", selected)
        self.assertNotIn("workflow/time_ledger/E17_time_ledger.json", selected)
        self.assertEqual("0.5.0", facts["portable_manifest_version"])

    def test_strict_portable_archive_rejects_declared_project_fixture(self):
        manifest = json.dumps({
            "schema": "qingshan.portable_core_manifest.v1",
            "version": "0.5.0",
            "required_files": [
                "configs/PORTABLE_CORE_MANIFEST.json",
                "configs/GATE_REGISTRY_v3_20260716.json",
                "workflow/time_ledger/E17_time_ledger.json",
            ],
            "portable_test_modules": ["tools.tests.test_generic_gate"],
        }).encode()
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive_with(tmp, {
                "configs/PORTABLE_CORE_MANIFEST.json": manifest,
                "configs/GATE_REGISTRY_v3_20260716.json": b'{"gates": []}\n',
                "workflow/time_ledger/E17_time_ledger.json": b"{}\n",
                "tools/tests/test_generic_gate.py": b"pass\n",
            })
            with tarfile.open(archive, "r:gz") as source:
                with self.assertRaises(SystemExit):
                    MODULE.portable_archive_files(source)

    def test_deployment_inventory_is_derived_from_selected_archive_bytes(self):
        selected = {
            MODULE.DEPLOYMENT_CODE_MANIFEST,
            "configs/generic.json",
            "tools/generic_gate.py",
        }
        generic_config = b'{"kind":"portable"}\n'
        generic_tool = b"VALUE = 'portable'\n"
        stale_inventory = b'{"schema":"old","files":[]}\n'
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive_with(tmp, {
                MODULE.DEPLOYMENT_CODE_MANIFEST: stale_inventory,
                "configs/generic.json": generic_config,
                "tools/generic_gate.py": generic_tool,
                "tools/e40_historical_repair.py": b"do_not_ship = True\n",
            })
            with tarfile.open(archive, "r:gz") as source:
                payload = MODULE._deployment_inventory_payload(source, selected)
            inventory = json.loads(payload)
            self.assertEqual(
                [row["path"] for row in inventory["files"]],
                ["configs/generic.json", "tools/generic_gate.py"],
            )
            self.assertEqual(
                inventory["files"][0]["sha256"],
                hashlib.sha256(generic_config).hexdigest(),
            )
            extracted = Path(tmp) / "extracted"
            (extracted / "configs").mkdir(parents=True)
            (extracted / "tools").mkdir()
            (extracted / "configs/generic.json").write_bytes(generic_config)
            (extracted / "tools/generic_gate.py").write_bytes(generic_tool)
            report = verify_deployment_inventory(extracted, inventory)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["missing"], [])
            self.assertEqual(report["changed"], [])

    def test_portable_manifest_rejects_duplicates_and_omissions(self):
        source = json.loads(MODULE.PORTABLE_MANIFEST.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "configs" / "PORTABLE_CORE_MANIFEST.json"
            path.parent.mkdir()
            duplicate = dict(source)
            duplicate["required_files"] = list(source["required_files"]) + [
                source["required_files"][0]
            ]
            path.write_text(json.dumps(duplicate))
            with self.assertRaises(SystemExit):
                MODULE.validate_portable_release_manifest(path)

            omitted = dict(source)
            omitted["required_files"] = [
                value
                for value in source["required_files"]
                if value != "tools/storyclaw_nalu_runtime.py"
            ]
            path.write_text(json.dumps(omitted))
            with self.assertRaises(SystemExit):
                MODULE.validate_portable_release_manifest(path)

    def test_workspace_audit_enforces_talenthub_prompt_size_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = MODULE.write_talenthub_workspace(
                Path(tmp),
                "v-test",
                "a" * 40,
                "b" * 64,
                archive_size=123,
                validation=None,
                origin_tag_commit=None,
            )
            (workspace / "USER.md").write_bytes(b"x" * (MODULE.TALENTHUB_FILE_LIMIT + 1))
            with self.assertRaises(SystemExit):
                MODULE.audit_talenthub_workspace(workspace)

    def test_private_validation_content_is_not_copied_to_workspace(self):
        commit = "d" * 40
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self._validation_receipt(tmp, commit)
            validation_summary = {
                "schema": MODULE.VALIDATION_SCHEMA,
                "status": "PASS",
                "sha256": MODULE.sha256(receipt),
                "release_commit": commit,
                "remote_engine_commit": commit,
                "remote_worktree_clean": True,
                "remote_diff_sha256": MODULE.EMPTY_SHA256,
                "checks": {name: "PASS" for name in MODULE.VALIDATION_CHECKS},
            }
            with mock.patch.object(
                MODULE._release_validation, "verify_receipt",
                return_value=validation_summary,
            ):
                validation = MODULE.validate_storyclaw_release_receipt(receipt, commit)
            workspace = MODULE.write_talenthub_workspace(
                Path(tmp),
                "v-test",
                commit,
                "e" * 64,
                archive_size=987,
                validation=validation,
                origin_tag_commit=commit,
                dependency_profiles=self._dependency_bindings("v-test"),
            )
            all_public_text = "\n".join(
                path.read_text(errors="replace")
                for path in workspace.rglob("*")
                if path.is_file()
            )
            private_title = "PRIVATE_ACCEPTANCE_SOURCE_TITLE"
            private_source_sha = hashlib.sha256(b"private acceptance source").hexdigest()
            self.assertNotIn(private_title, all_public_text)
            self.assertNotIn(private_source_sha, all_public_text)
            self.assertNotIn(str(receipt.resolve()), all_public_text)
            self.assertIn(MODULE.sha256(receipt), all_public_text)

    def test_source_archive_is_byte_reproducible(self):
        if not (ROOT / ".git").exists():
            self.skipTest("source archive construction requires the maintainer Git checkout")
        commit = MODULE.git("rev-parse", "HEAD")
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_path, first_sha = MODULE.archive_source(Path(first), "v-test", commit)
            second_path, second_sha = MODULE.archive_source(Path(second), "v-test", commit)
            self.assertEqual(first_sha, second_sha)
            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
            self.assertEqual(
                first_sha,
                hashlib.sha256(first_path.read_bytes()).hexdigest(),
            )

    def test_source_archive_prompts_exclude_private_acceptance_markers(self):
        if not (ROOT / ".git").exists():
            self.skipTest("source archive construction requires the maintainer Git checkout")
        commit = MODULE.git("rev-parse", "HEAD")
        private_title = "PRIVATE_ACCEPTANCE_SOURCE_TITLE"
        private_hash = hashlib.sha256(b"private acceptance source").hexdigest()
        prompt_prefixes = (
            "qingshan-storyclaw-workflow/agent_factory/storyclaw_portable/",
            "qingshan-storyclaw-workflow/skills/qingshan-nalu/",
        )
        with tempfile.TemporaryDirectory() as tmp:
            archive, _ = MODULE.archive_source(Path(tmp), "v-test", commit)
            with tarfile.open(archive, "r:gz") as tar:
                prompt_text = "\n".join(
                    (tar.extractfile(member).read().decode("utf-8", errors="replace"))
                    for member in tar.getmembers()
                    if member.isfile() and member.name.startswith(prompt_prefixes)
                )
            self.assertNotIn(private_title, prompt_text)
            self.assertNotIn(private_hash, prompt_text)

    def test_release_tag_rejects_path_separators(self):
        with self.assertRaises(SystemExit):
            MODULE.validate_release_tag("release/unsafe")
        MODULE.validate_release_tag("v2026.09.20-storyclaw-port")

    def test_publish_rejects_experimental_release_flags(self):
        with self.assertRaises(SystemExit):
            MODULE.validate_publish_mode(
                publish=True, skip_checks=True, allow_unreleased=False
            )
        with self.assertRaises(SystemExit):
            MODULE.validate_publish_mode(
                publish=True, skip_checks=False, allow_unreleased=True
            )
        MODULE.validate_publish_mode(
            publish=True,
            skip_checks=False,
            allow_unreleased=False,
            validation_receipt=Path("validation.json"),
        )
        with self.assertRaises(SystemExit):
            MODULE.validate_publish_mode(
                publish=True,
                skip_checks=False,
                allow_unreleased=False,
                validation_receipt=None,
            )

    def test_remote_tag_must_be_pushed_and_peeled_to_head(self):
        tag = "v2026.09.20-storyclaw-port"
        commit = "1" * 40
        ref = f"refs/tags/{tag}"
        annotated = mock.Mock(
            returncode=0,
            stdout=f"{'2' * 40}\t{ref}\n{commit}\t{ref}^{{}}\n",
            stderr="",
        )
        with mock.patch.object(MODULE.subprocess, "run", return_value=annotated):
            self.assertEqual(MODULE.assert_tag_pushed_to_origin(tag, commit, False), commit)
        missing = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(MODULE.subprocess, "run", return_value=missing):
            with self.assertRaises(SystemExit):
                MODULE.assert_tag_pushed_to_origin(tag, commit, False)
        self.assertIsNone(MODULE.assert_tag_pushed_to_origin(tag, commit, True))

    def test_validation_receipt_delegates_to_live_evidence_verifier(self):
        commit = "3" * 40
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self._validation_receipt(tmp, commit)
            expected = {
                "schema": MODULE.VALIDATION_SCHEMA, "status": "PASS",
                "sha256": "a" * 64,
                "checks": {name: "PASS" for name in MODULE.VALIDATION_CHECKS},
            }
            with mock.patch.object(
                MODULE._release_validation, "verify_receipt", return_value=expected,
            ) as verify:
                summary = MODULE.validate_storyclaw_release_receipt(receipt, commit)
            self.assertEqual(summary, expected)
            verify.assert_called_once_with(receipt, commit)

    def test_validation_receipt_wraps_live_evidence_failure(self):
        commit = "4" * 40
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self._validation_receipt(tmp, commit)
            with mock.patch.object(
                MODULE._release_validation, "verify_receipt",
                side_effect=MODULE._release_validation.ValidationBlocked(
                    "TRANSACTION_MANIFEST_BINDING_MISMATCH"
                ),
            ), self.assertRaisesRegex(
                SystemExit, "TRANSACTION_MANIFEST_BINDING_MISMATCH"
            ):
                MODULE.validate_storyclaw_release_receipt(receipt, commit)

    def test_validation_registry_includes_every_live_acceptance_gate(self):
        self.assertEqual(
            MODULE.VALIDATION_CHECKS,
            (
                "install_preflight", "source_intake", "s1_s2",
                "asset_plan_confirmation", "s5_dry_run",
                "two_unit_paid_trial", "paid_authority",
                "transaction_integrity", "ledger_reconciliation",
                "final_qa", "checkpoint",
            ),
        )

    def test_publish_version_parser_accepts_json_and_human_output(self):
        self.assertEqual(
            MODULE.parse_talenthub_publish_version('{"agent":{"version":"2.4.0"}}'),
            "2.4.0",
        )
        self.assertEqual(
            MODULE.parse_talenthub_publish_version("✓ Published version: 17"),
            "17",
        )
        self.assertIsNone(MODULE.parse_talenthub_publish_version("✓ Published successfully"))

    def test_private_canary_and_formal_publish_commands_are_separate(self):
        workspace = Path("/private/build/talenthub-agent")
        tag = "v2026.09.20-storyclaw-port"
        canary = MODULE.talenthub_canary_publish_command(workspace, tag)
        formal = MODULE.talenthub_formal_publish_command(workspace)
        self.assertIn("--private", canary)
        self.assertIn("--id", canary)
        canary_id = canary[canary.index("--id") + 1]
        self.assertNotEqual(canary_id, MODULE.AGENT_ID)
        self.assertEqual(canary_id, MODULE.talenthub_canary_agent_id(tag))
        self.assertNotIn("--private", formal)
        self.assertNotIn("--id", formal)
        self.assertEqual(formal, [
            "talenthub", "agent", "publish", "--dir", str(workspace)
        ])

    def test_registry_versions_must_strictly_advance(self):
        MODULE.require_talenthub_version_advance(
            "2026.07.10-1", "2026.09.20-1"
        )
        MODULE.require_talenthub_version_advance(None, "2026.09.20-1")
        for current in ("2026.07.10-1", "2026.07.09-9"):
            with self.subTest(current=current), self.assertRaises(SystemExit):
                MODULE.require_talenthub_version_advance("2026.07.10-1", current)

    def test_unreceipted_canary_is_recovered_only_for_exact_bytes_and_stable_official(self):
        workspace = Path("/private/build/talenthub-agent")
        prior = {
            "agent_id": MODULE.AGENT_ID,
            "version": "2026.07.10-1",
            "package_url": "https://assets.storyclaw.com/public/old.zip",
        }
        remote = {
            "agent_id": MODULE.talenthub_canary_agent_id("v-test"),
            "version": "2026.09.20-1",
            "package_url": "https://assets.storyclaw.com/private/canary.zip",
        }
        exact = {
            "status": "PASS", "package_url": remote["package_url"],
            "size_bytes": 123, "sha256": "a" * 64,
        }
        recovered = MODULE.recover_unreceipted_registry_canary(
            workspace,
            remote,
            prior,
            public_reader=lambda _agent_id: prior,
            verifier=lambda _workspace, _url: exact,
        )
        self.assertEqual(recovered, (remote, exact))
        self.assertIsNone(MODULE.recover_unreceipted_registry_canary(
            workspace,
            None,
            prior,
            public_reader=lambda _agent_id: self.fail("unexpected registry read"),
            verifier=lambda _workspace, _url: self.fail("unexpected ZIP verification"),
        ))
        with self.assertRaisesRegex(SystemExit, "changed while recovering canary"):
            MODULE.recover_unreceipted_registry_canary(
                workspace,
                remote,
                prior,
                public_reader=lambda _agent_id: {**prior, "version": "2026.09.19-1"},
                verifier=lambda _workspace, _url: exact,
            )

    def test_unreceipted_formal_publish_is_adopted_without_republish_only_for_exact_zip(self):
        workspace = Path("/private/build/talenthub-agent")
        canary = {
            "official_previous_version": "2026.07.10-1",
            "official_previous_package_url": "https://assets.storyclaw.com/public/old.zip",
            "canary_package_size_bytes": 123,
            "canary_package_sha256": "a" * 64,
        }
        prior = {
            "agent_id": MODULE.AGENT_ID,
            "version": canary["official_previous_version"],
            "package_url": canary["official_previous_package_url"],
        }
        published = {
            "agent_id": MODULE.AGENT_ID,
            "version": "2026.09.20-1",
            "package_url": "https://assets.storyclaw.com/public/new.zip",
        }
        exact = {
            "status": "PASS", "package_url": published["package_url"],
            "size_bytes": 123, "sha256": "a" * 64,
        }
        self.assertIsNone(MODULE.recover_formal_registry_publication(
            workspace, canary, prior,
            verifier=lambda _workspace, _url: self.fail("prior row must not be downloaded"),
        ))
        self.assertEqual(
            MODULE.recover_formal_registry_publication(
                workspace, canary, published,
                verifier=lambda _workspace, _url: exact,
            ),
            (published, exact),
        )
        with self.assertRaisesRegex(SystemExit, "other than the smoke-tested canary"):
            MODULE.recover_formal_registry_publication(
                workspace, canary, published,
                verifier=lambda _workspace, _url: {**exact, "sha256": "b" * 64},
            )

    def test_canary_cleanup_never_treats_cancelled_or_still_visible_as_pass(self):
        cancelled = subprocess.CompletedProcess([], 0, "Cancelled.\n", "")
        self.assertEqual(
            MODULE.canary_cleanup_report(cancelled, None)["status"], "DEFERRED"
        )
        success = subprocess.CompletedProcess([], 0, "✓ Agent unpublished\n", "")
        still_visible = {
            "agent_id": "canary", "version": "2026.09.20-1",
            "package_url": "https://assets.storyclaw.com/private/canary.zip",
        }
        self.assertEqual(
            MODULE.canary_cleanup_report(success, still_visible)["status"], "DEFERRED"
        )
        self.assertEqual(MODULE.canary_cleanup_report(success, None)["status"], "PASS")

    def test_canary_receipt_binds_release_workspace_and_prior_public_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            nested = workspace / "skills/qingshan-nalu/RELEASE_MANIFEST.json"
            nested.parent.mkdir(parents=True)
            nested.write_text('{"bound":true}\n')
            index = root / MODULE.STABLE_INDEX_FILENAME
            index.write_text('{"signed":true}\n')
            tag = "v-test"
            canary_id = MODULE.talenthub_canary_agent_id(tag)
            path, written = MODULE.write_registry_canary_receipt(
                root,
                tag=tag,
                commit="a" * 40,
                release_sequence=12,
                stable_index_path=index,
                workspace=workspace,
                canary_agent_id=canary_id,
                canary_version="2026.09.20-1",
                canary_package={
                    "package_url": "https://assets.storyclaw.com/private/canary.zip",
                    "size_bytes": 123,
                    "sha256": "b" * 64,
                },
                official_before={
                    "agent_id": MODULE.AGENT_ID,
                    "version": "2026.07.10-1",
                    "package_url": "https://assets.storyclaw.com/public/official.zip",
                },
            )
            loaded = MODULE.load_registry_canary_receipt(
                path,
                tag=tag,
                commit="a" * 40,
                release_sequence=12,
                stable_index_path=index,
                workspace=workspace,
            )
            self.assertEqual(loaded["sha256"], written["sha256"])
            self.assertEqual(
                loaded["status"], "PENDING_REGISTRY_CLEAN_INSTALL_SMOKE"
            )
            nested.write_text('{"bound":false}\n')
            with self.assertRaises(SystemExit):
                MODULE.load_registry_canary_receipt(
                    path,
                    tag=tag,
                    commit="a" * 40,
                    release_sequence=12,
                    stable_index_path=index,
                    workspace=workspace,
                )

    def test_immutable_attestation_retry_reuses_exact_bytes_and_rejects_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "attestation.json"
            second = root / "attestation.json.sig"
            first.write_bytes(b"attestation")
            second.write_bytes(b"signature")
            calls = []

            def exact_runner(command, **_kwargs):
                calls.append(list(command))
                if command[2:4] == ["view", "v-test"]:
                    return subprocess.CompletedProcess(
                        command, 0,
                        json.dumps({"assets": [{"name": first.name}, {"name": second.name}]}),
                        "",
                    )
                if command[2:4] == ["download", "v-test"]:
                    name = command[command.index("--pattern") + 1]
                    destination = Path(command[command.index("--dir") + 1])
                    destination.mkdir(parents=True, exist_ok=True)
                    destination.joinpath(name).write_bytes(
                        first.read_bytes() if name == first.name else second.read_bytes()
                    )
                    return subprocess.CompletedProcess(command, 0, "", "")
                return subprocess.CompletedProcess(command, 2, "", "unexpected")

            report = MODULE.upload_immutable_release_assets(
                "v-test", (first, second), runner=exact_runner
            )
            self.assertEqual(report["status"], "PASS")
            self.assertFalse(any("upload" in command for command in calls))

            def mismatch_runner(command, **_kwargs):
                if command[2:4] == ["view", "v-test"]:
                    return subprocess.CompletedProcess(
                        command, 0,
                        json.dumps({"assets": [{"name": first.name}, {"name": second.name}]}),
                        "",
                    )
                if command[2:4] == ["download", "v-test"]:
                    name = command[command.index("--pattern") + 1]
                    destination = Path(command[command.index("--dir") + 1])
                    destination.mkdir(parents=True, exist_ok=True)
                    destination.joinpath(name).write_bytes(b"wrong")
                    return subprocess.CompletedProcess(command, 0, "", "")
                return subprocess.CompletedProcess(command, 2, "", "unexpected")

            with self.assertRaises(SystemExit):
                MODULE.upload_immutable_release_assets(
                    "v-test", (first, second), runner=mismatch_runner
                )

    def test_release_checks_explicitly_include_portability_and_authority_suites(self):
        with mock.patch.object(MODULE, "run") as run_mock:
            MODULE.run_release_checks()
        command_text = "\n".join(" ".join(call.args[0]) for call in run_mock.call_args_list)
        for module_name in (
            "test_nalu_paid_authority",
            "test_nalu_scoped_qa_paths",
            "test_nalu_current_policy_profile",
            "test_storyclaw_asset_plan_gate",
            "test_storyclaw_project_intake",
            "test_nalu_media_tools",
            "test_provider_scope_projection",
        ):
            self.assertIn(module_name, command_text)

    def test_archive_audit_rejects_private_runtime_and_live_orders(self):
        manifest = b'{}\n'
        with tempfile.TemporaryDirectory() as tmp:
            private = self._archive_with(tmp, {
                "RELEASE_MANIFEST.json": manifest,
                "workflow/tasks/giggle_submit_transactions/E01/tx.json": b'{}\n',
            })
            with self.assertRaises(SystemExit):
                MODULE.audit_source_archive(private)
        with tempfile.TemporaryDirectory() as tmp:
            live = self._archive_with(tmp, {
                "RELEASE_MANIFEST.json": manifest,
                "workflow/claude_writer_agent/SUPERVISOR_ORDERS.json": b'{"latest_order_seq":1,"orders":[{}]}\n',
            })
            with self.assertRaises(SystemExit):
                MODULE.audit_source_archive(live)

    def test_archive_audit_allows_only_empty_order_templates(self):
        empty = json.dumps({"latest_order_seq": 0, "orders": []}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive_with(tmp, {
                "RELEASE_MANIFEST.json": b'{}\n',
                "agent_factory/claude_writer/runtime_templates/SUPERVISOR_ORDERS.json": empty,
                "agent_factory/claude_writer_v2/state/SUPERVISOR_ORDERS.json": empty,
            })
            result = MODULE.audit_source_archive(archive)
            self.assertEqual(result["status"], "PASS")

    def test_portable_archive_inventory_requires_every_declared_file(self):
        manifest = json.dumps({
            "schema": "qingshan.portable_core_manifest.v1",
            "required_files": ["tools/example.py"],
            "portable_test_modules": ["tools.tests.test_example"],
        }).encode()
        with tempfile.TemporaryDirectory() as tmp:
            complete = self._archive_with(tmp, {
                "configs/PORTABLE_CORE_MANIFEST.json": manifest,
                "tools/example.py": b"pass\n",
            })
            result = MODULE.audit_portable_archive_inventory(complete)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["required_file_count"], 1)
        with tempfile.TemporaryDirectory() as tmp:
            incomplete = self._archive_with(tmp, {
                "configs/PORTABLE_CORE_MANIFEST.json": manifest,
            })
            with self.assertRaises(SystemExit):
                MODULE.audit_portable_archive_inventory(incomplete)


if __name__ == "__main__":
    unittest.main()
