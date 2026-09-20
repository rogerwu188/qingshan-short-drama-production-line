import json
import fcntl
import hashlib
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import storyclaw_nalu_runtime as runtime


class StoryClawRuntimeTests(unittest.TestCase):
    def setUp(self):
        self._model_env = patch.dict(
            os.environ, {"STORYCLAW_MODEL": "storyclaw/gpt-6-astra"}
        )
        self._model_env.start()
        self.addCleanup(self._model_env.stop)

    def _root(self):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        (root / "qingshan_engine").mkdir()
        (root / "tools").mkdir()
        (root / "lines/nalu/runtime/tools").mkdir(parents=True)
        (root / "lines/nalu/runtime/tools/nalu_pipeline.py").write_text("", encoding="utf-8")
        (root / "lines/nalu/runtime/tools/nalu_paths.py").write_text("", encoding="utf-8")
        runtime_root = root / "runtime"
        paths = runtime.deployment_paths(root, runtime_root)
        paths["workspace_backing"].mkdir(parents=True)
        paths["transactions_backing"].mkdir(parents=True)
        paths["workspace"].parent.mkdir(parents=True)
        paths["workspace"].symlink_to(paths["workspace_backing"], target_is_directory=True)
        paths["transactions"].symlink_to(paths["transactions_backing"], target_is_directory=True)
        runtime.init_runtime(root, runtime_root, legacy_default_scope=True)
        readonly = patch.object(runtime, "_engine_readonly_probe", return_value={
            "status": "PASS", "path": str(root), "mode": "READ_ONLY",
        })
        readonly.start()
        self.addCleanup(readonly.stop)
        dependencies = patch.object(runtime, "_portable_dependency_checks", return_value={
            "portable_media": {"status": "PASS"},
            "portable_audio_provider": {"status": "PASS"},
            "portable_renderer": {"status": "PASS"},
        })
        dependencies.start()
        self.addCleanup(dependencies.stop)
        return td, root, runtime_root

    def test_storage_contract_accepts_created_stable_link_but_rejects_other_project(self):
        td, engine, private = self._root()
        with td:
            config = json.loads((private / "qingshan.json").read_text())
            storage = config["storyclaw"]["storage"]
            link = engine / "stable-current"
            # Mirror onboarding: store paths before the installer creates the link.
            storage["engine_root"] = str(link.absolute())
            storage["workspace_mount_target"] = str(link / "workflow/nalu")
            storage["transactions_mount_target"] = str(link / "workflow/tasks")
            self.assertEqual(runtime._storage_checks(engine, private, config)["storage_contract"]["status"], "BLOCKED")
            link.symlink_to(engine, target_is_directory=True)
            checks = runtime._storage_checks(engine, private, config)
            for key in ("storage_contract", "workspace_store", "transaction_store"):
                self.assertEqual(checks[key]["status"], "PASS", checks[key])
            other = engine / "other-project"
            other.mkdir()
            storage["workspace_backing_path"] = str(other)
            self.assertEqual(runtime._storage_checks(engine, private, config)["storage_contract"]["status"], "BLOCKED")
            storage["workspace_backing_path"] = None
            self.assertEqual(runtime._storage_checks(engine, private, config)["storage_contract"]["status"], "BLOCKED")

    def _archive_commit_fixture(self, base: Path):
        project = base / "project"
        engine = project / "engine/releases/v1"
        runtime_root = project / "projects/test"
        (engine / "tools").mkdir(parents=True)
        runtime_root.mkdir(parents=True)
        commit = "a" * 40
        tag = "v1"
        (engine / "tools/example.py").write_text("print('verified')\n")
        (engine / "RELEASE_MANIFEST.json").write_text(json.dumps({
            "schema": runtime._storyclaw_install.ARCHIVE_RELEASE_SCHEMA,
            "release_tag": tag,
            "git_commit": commit,
            "private_runtime_included": False,
            "credentials_included": False,
        }) + "\n")
        engine_link = project / "engine/current"
        os.symlink(engine, engine_link)
        (runtime_root / "runtime").mkdir()
        marker = {
            "engine_root": str(engine_link),
        }
        (runtime_root / "runtime/project.json").write_text(json.dumps(marker))
        (runtime_root / ".qingshan-private-runtime.json").write_text(
            json.dumps(marker)
        )
        (runtime_root / "qingshan.json").write_text(json.dumps({
            "storyclaw": {"storage": {"engine_root": str(engine_link)}}
        }))
        baseline = runtime_root / runtime._storyclaw_install.CURRENT_RELEASE_STATE_RELATIVE
        baseline.parent.mkdir(parents=True)
        baseline.write_text(json.dumps({
            "schema": runtime._storyclaw_install.CURRENT_RELEASE_STATE_SCHEMA,
            "status": "PASS",
            "release_tag": tag,
            "git_commit": commit,
            "signing_key_sha256": runtime._storyclaw_install.RELEASE_SIGNING_PUBLIC_KEY_SHA256,
        }))
        receipt = (
            runtime_root
            / runtime._storyclaw_install.UPGRADE_RECEIPT_ROOT_RELATIVE
            / f"{commit}.json"
        )
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({
            "schema": runtime._storyclaw_install.UPGRADE_RECEIPT_SCHEMA,
            "status": "PASS",
            "release_tag": tag,
            "git_commit": commit,
            "current_engine": str(engine.resolve()),
            "candidate_tree_sha256": runtime._storyclaw_install._tree_digest(engine),
        }))
        return engine, runtime_root, engine_link, baseline, receipt, commit

    def _first_install_archive_fixture(self, base: Path):
        install = runtime._storyclaw_install
        dependency_bundle = install._dependency_bundle
        base = base.resolve()
        project = base / "project"
        engine = project / "engine/releases/v1"
        runtime_root = project / "projects/test"
        workspace = base / "talenthub-workspace"
        engine.mkdir(parents=True)
        runtime_root.mkdir(parents=True)
        commit = "c" * 40
        tag = "v1"
        archive = project / "bootstrap-cache/source.tar.gz"
        archive.parent.mkdir(parents=True)
        archive.write_bytes(b"package-bound-source-archive")

        (engine / "tools").mkdir()
        (engine / "tools/example.py").write_text("print('verified')\n")
        (engine / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0'\n")
        (engine / "qingshan_engine").mkdir()
        (engine / "workflow").mkdir()
        (engine / "lines/nalu/runtime/tools").mkdir(parents=True)
        (engine / "lines/nalu/runtime/tools/nalu_pipeline.py").write_text("")
        (engine / "lines/nalu/runtime/tools/nalu_paths.py").write_text("")
        (engine / "RELEASE_MANIFEST.json").write_text(json.dumps({
            "schema": install.ARCHIVE_RELEASE_SCHEMA,
            "release_tag": tag,
            "git_commit": commit,
            "private_runtime_included": False,
            "credentials_included": False,
        }) + "\n")
        inventory_path = engine / "configs/DEPLOYMENT_CODE_SHA256.json"
        inventory_path.parent.mkdir()
        inventory_path.write_text(json.dumps({
            "file_count": 1,
            "files": [{
                "path": "tools/example.py",
                "sha256": hashlib.sha256(
                    (engine / "tools/example.py").read_bytes()
                ).hexdigest(),
            }],
        }) + "\n")

        for relative in install.INSTALLED_TALENTHUB_BOUND_FILES:
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"bound {relative}\n")
        bindings = {
            relative: {
                "size_bytes": (workspace / relative).stat().st_size,
                "sha256": hashlib.sha256(
                    (workspace / relative).read_bytes()
                ).hexdigest(),
            }
            for relative in install.INSTALLED_TALENTHUB_BOUND_FILES
        }
        dependency_profiles = []
        for profile in dependency_bundle.SUPPORTED_PROFILES:
            manifest_name = dependency_bundle.dependency_manifest_filename(
                tag, profile.profile_id
            )
            archive_name = dependency_bundle.dependency_archive_filename(
                tag, profile.profile_id
            )
            dependency_profiles.append({
                "profile_id": profile.profile_id,
                "manifest_url": dependency_bundle.github_asset_url(
                    tag, manifest_name
                ),
                "manifest_size_bytes": 1,
                "manifest_sha256": "1" * 64,
                "archive_url": dependency_bundle.github_asset_url(
                    tag, archive_name
                ),
                "archive_size_bytes": 1,
                "archive_sha256": "2" * 64,
            })
        talenthub_manifest = workspace / "skills/qingshan-nalu/RELEASE_MANIFEST.json"
        talenthub_payload = {
            "schema": install.TALENTHUB_RELEASE_SCHEMA,
            "agent_id": install.AGENT_ID,
            "skill": install.SKILL_NAME,
            "release_sequence": 1,
            "release_tag": tag,
            "git_commit": commit,
            "origin_tag_commit": commit,
            "release_signing_key_sha256": install.RELEASE_SIGNING_PUBLIC_KEY_SHA256,
            "validation_receipt_status": "PASS",
            "validation_receipt_sha256": "3" * 64,
            "public_runtime_only": True,
            "private_validation_contents_included": False,
            "dependency_profiles_action": "REPLACE_WITH_RELEASE_BUNDLES",
            "dependency_profiles": dependency_profiles,
            "source_archive_size_bytes": archive.stat().st_size,
            "source_archive_sha256": hashlib.sha256(
                archive.read_bytes()
            ).hexdigest(),
            "installed_file_bindings": bindings,
        }
        talenthub_manifest.write_text(json.dumps(talenthub_payload) + "\n")

        engine_link = project / "engine/current"
        marker = {
            "status": "INITIALIZED_PRIVATE",
            "project_id": "test",
            "series_scope_id": "TEST-SCOPE",
            "private_runtime_root": str(runtime_root),
            "engine_root": str(engine_link),
            "paid_requests_enabled": False,
        }
        (runtime_root / "runtime").mkdir(exist_ok=True)
        (runtime_root / "runtime/project.json").write_text(json.dumps(marker))
        (runtime_root / ".qingshan-private-runtime.json").write_text(
            json.dumps(marker)
        )
        config = {
            "generation": {"paid_requests_enabled": False},
            "storyclaw": {
                "policy_profile": runtime.POLICY_PROFILE,
                "series_scope_id": "TEST-SCOPE",
                "storage": {"engine_root": str(engine_link)},
            },
        }
        (runtime_root / "qingshan.json").write_text(json.dumps(config))

        venv = runtime_root / "runtime/storyclaw_host/venv"

        def dependency_installer(*_args, **_kwargs):
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!/bin/sh\n")
            python.chmod(0o755)
            return {
                "requested": True,
                "status": "INSTALLED",
                "venv": str(venv),
                "python": str(python),
                "network_used": False,
                "dependency_profile": dependency_profiles[0]["profile_id"],
                "interpreter_facts": {"schema": "storyclaw.nalu.dependency_profile.v1"},
                "bundle_manifest_sha256": "1" * 64,
                "bundle_archive_sha256": "2" * 64,
                "lock_sha256": "4" * 64,
                "installed_package_count": 1,
                "installed_inventory_sha256": "5" * 64,
                "pip_check": "PASS",
            }

        installed = install.install_host(
            engine,
            runtime_root,
            release_tag=tag,
            expected_commit=commit,
            install_deps=True,
            venv_path=venv,
            seal_read_only=True,
            project_view_root=engine,
            project_engine_link=engine_link,
            talenthub_release_manifest=talenthub_manifest,
            verified_bootstrap_archive=archive,
            dependency_manifest=base / "unused-dependencies.json",
            dependency_archive=base / "unused-dependencies.tar.gz",
            dependency_installer=dependency_installer,
        )
        install_path = Path(installed["receipt"]["path"])
        bootstrap_receipt = (
            runtime_root / "runtime/receipts/storyclaw_bootstrap/bootstrap.json"
        )
        bootstrap_receipt.parent.mkdir(parents=True)
        bootstrap_receipt.write_text(json.dumps({
            "schema": "storyclaw.nalu.skill_bootstrap.v1",
            "status": "PREFLIGHT_PENDING",
            "release_tag": tag,
            "git_commit": commit,
            "source_archive": str(archive),
            "source_archive_size_bytes": archive.stat().st_size,
            "source_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "talenthub_release_manifest": str(talenthub_manifest),
            "private_runtime_root": str(runtime_root),
            "project_engine_link": str(engine_link),
            "project_engine": str(engine),
            "host_install_receipt": str(install_path),
            "host_install_receipt_size_bytes": install_path.stat().st_size,
            "host_install_receipt_sha256": hashlib.sha256(
                install_path.read_bytes()
            ).hexdigest(),
            "provider_posts": 0,
            "provider_secret_names_present": [],
        }) + "\n")
        baseline = runtime_root / install.CURRENT_RELEASE_STATE_RELATIVE
        return {
            "engine": engine,
            "runtime": runtime_root,
            "engine_link": engine_link,
            "manifest": engine / "RELEASE_MANIFEST.json",
            "baseline": baseline,
            "install_receipt": install_path,
            "commit": commit,
        }

    def test_archive_commit_requires_tree_receipt_baseline_and_current_engine_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine, runtime_root, engine_link, _baseline, _receipt, commit = \
                self._archive_commit_fixture(Path(temporary))
            self.assertEqual(runtime._engine_commit(engine, runtime_root), commit)
            self.assertEqual(
                runtime.preflight(engine, runtime_root)["engine_commit"], commit
            )

        mutations = ("missing_receipt", "tree", "baseline", "engine_link", "manifest")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                engine, runtime_root, engine_link, baseline, receipt, _commit = \
                    self._archive_commit_fixture(Path(temporary))
                if mutation == "missing_receipt":
                    receipt.unlink()
                elif mutation == "tree":
                    (engine / "tools/example.py").write_text("tampered\n")
                elif mutation == "baseline":
                    value = json.loads(baseline.read_text())
                    value["git_commit"] = "b" * 40
                    baseline.write_text(json.dumps(value))
                elif mutation == "engine_link":
                    engine_link.unlink()
                    other = engine.parent / "other"
                    other.mkdir()
                    os.symlink(other, engine_link)
                else:
                    value = json.loads((engine / "RELEASE_MANIFEST.json").read_text())
                    value["credentials_included"] = True
                    (engine / "RELEASE_MANIFEST.json").write_text(json.dumps(value))
                    # Even a matching forged receipt/tree cannot authorize a
                    # manifest whose public/private boundary flags are wrong.
                    receipt_value = json.loads(receipt.read_text())
                    receipt_value["candidate_tree_sha256"] = \
                        runtime._storyclaw_install._tree_digest(engine)
                    receipt.write_text(json.dumps(receipt_value))
                self.assertIsNone(runtime._engine_commit(engine, runtime_root))

    def test_arbitrary_archive_manifest_without_private_binding_is_never_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = Path(temporary) / "engine"
            runtime_root = Path(temporary) / "runtime"
            engine.mkdir()
            runtime_root.mkdir()
            (engine / "RELEASE_MANIFEST.json").write_text(json.dumps({
                "schema": runtime._storyclaw_install.ARCHIVE_RELEASE_SCHEMA,
                "release_tag": "v-forged",
                "git_commit": "f" * 40,
                "private_runtime_included": False,
                "credentials_included": False,
            }))
            self.assertIsNone(runtime._engine_commit(engine, runtime_root))

    def test_first_install_archive_commit_reopens_package_and_host_receipt(self):
        bootstrap_env = {
            "QINGSHAN_BOOTSTRAP_NO_PROVIDER_POSTS": "1",
            "QINGSHAN_PAID_REQUESTS_ENABLED": "0",
            "GIGGLE_API_KEY": "",
        }
        with patch.dict(os.environ, bootstrap_env), \
             tempfile.TemporaryDirectory() as temporary:
            fixture = self._first_install_archive_fixture(Path(temporary))
            engine = fixture["engine"]
            runtime_root = fixture["runtime"]
            commit = fixture["commit"]
            # A retry may leave additional receipts.  They cannot authorize
            # anything and must not invalidate the exact path+SHA bound by the
            # provisional bootstrap receipt.
            extra = (
                runtime_root
                / runtime._storyclaw_install.RECEIPT_ROOT_RELATIVE
                / "unbound-retry.json"
            )
            extra.write_text('{"status":"forged"}\n')
            self.assertEqual(runtime._engine_commit(engine, runtime_root), commit)
            with patch.dict(os.environ, {
                "QINGSHAN_BOOTSTRAP_NO_PROVIDER_POSTS": "",
            }):
                self.assertIsNone(runtime._engine_commit(engine, runtime_root))
            voice = runtime_root / "runtime/voice.json"
            voice.write_text("{}\n")
            storage_checks = {
                "storage_contract": {"status": "PASS"},
                "engine_code_read_only": {"status": "PASS"},
                "workspace_store": {"status": "PASS"},
                "transaction_store": {"status": "PASS"},
                "writer_layers_store": {"status": "PASS"},
            }
            portable_checks = {
                "portable_media": {"status": "PASS"},
                "portable_audio_provider": {"status": "PASS"},
                "portable_renderer": {"status": "PASS"},
                "stable_release_signature_verifier": {"status": "PASS"},
            }
            with patch.object(runtime, "_storage_checks", return_value=storage_checks), \
                 patch.object(runtime, "_portable_dependency_checks", return_value=portable_checks), \
                 patch.object(runtime, "_series_scope_check", return_value={"status": "PASS"}), \
                 patch.object(runtime, "_scope_document_path", return_value=voice):
                report = runtime.preflight(engine, runtime_root)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["engine_commit"], commit)

        for mutation in ("manifest", "tree", "baseline", "install_receipt"):
            with self.subTest(mutation=mutation), \
                 patch.dict(os.environ, bootstrap_env), \
                 tempfile.TemporaryDirectory() as temporary:
                fixture = self._first_install_archive_fixture(Path(temporary))
                if mutation == "manifest":
                    path = fixture[mutation]
                    value = json.loads(path.read_text())
                    path.chmod(0o644)
                    value["credentials_included"] = True
                    path.write_text(json.dumps(value) + "\n")
                elif mutation == "tree":
                    path = fixture["engine"] / "tools/example.py"
                    path.chmod(0o644)
                    path.write_text("print('tampered')\n")
                elif mutation == "baseline":
                    path = fixture[mutation]
                    value = json.loads(path.read_text())
                    value["git_commit"] = "d" * 40
                    path.write_text(json.dumps(value) + "\n")
                else:
                    path = fixture[mutation]
                    value = json.loads(path.read_text())
                    value["status"] = "BLOCKED"
                    path.write_text(json.dumps(value) + "\n")
                self.assertIsNone(
                    runtime._engine_commit(fixture["engine"], fixture["runtime"])
                )

    def _write_s1_fixture(
        self, runtime_root: Path, *, episode: str = "E01",
        scope: str = "NALU-YEWUJIANG",
    ) -> Path:
        layers = runtime_root / "writer_layers" / scope / episode
        layers.mkdir(parents=True, exist_ok=True)
        paths = {
            "narrative_canonical": layers / f"{episode}_NARRATIVE_CANONICAL_v1.md",
            "directing_script": layers / f"{episode}_DIRECTING_SCRIPT_v1.md",
            "generation_contract": layers / f"{episode}_GENERATION_CONTRACT_v1.json",
            "writer_manifest": layers / f"{episode}_manifest_v1.json",
        }
        paths["narrative_canonical"].write_text("narrative", encoding="utf-8")
        paths["directing_script"].write_text("directing", encoding="utf-8")
        paths["writer_manifest"].write_text("{}", encoding="utf-8")
        paths["generation_contract"].write_text(json.dumps({
            "schema": "qingshan.generation_contract.v3",
            "episode": episode,
            "protagonist_ids": ["CHAR-LEAD"],
            "character_entities": [{"character_id": "CHAR-LEAD"}],
            "scene_states": [{"scene_id": "SCENE-A"}],
            "shots": [{
                "shot_id": f"{episode}-S01-01", "scene_id": "SCENE-A",
                "prompt_spec": {"props": [{"prop_id": "PROP-A"}]},
            }],
        }), encoding="utf-8")
        seq29 = runtime_root / "runtime/pipeline_logs" / episode / "seq29.json"
        seq29.parent.mkdir(parents=True, exist_ok=True)
        seq29.write_text(json.dumps({
            "schema": "nalu.writer_selfcheck_seq29.v1",
            "episode": episode,
            "enforced": True,
            "status": "PASS",
        }), encoding="utf-8")
        s1_receipt = runtime_root / "runtime/pipeline_logs" / episode / "S1_GATE_RECEIPT.json"
        s1_receipt.write_text(json.dumps({
            "schema": "nalu.s1_gate_receipt.v1",
            "episode": episode,
            "series_scope_id": scope,
            "stage": "S1",
            "status": "PASS",
        }), encoding="utf-8")
        s2_receipt = runtime_root / "runtime/pipeline_logs" / episode / "S2_PREPRODUCTION_RECEIPT.json"
        s2_receipt.write_text(json.dumps({
            "schema": "nalu.s2_preproduction_receipt.v1",
            "episode": episode,
            "series_scope_id": scope,
            "stage": "S2",
            "status": "PASS",
            "generation_contract_sha256": runtime.sha256(paths["generation_contract"]),
            "writer_manifest_sha256": runtime.sha256(paths["writer_manifest"]),
            "global_space_map_sha256": "1" * 64,
            "asset_requirements_sha256": "2" * 64,
            "preproduction_report_sha256": "3" * 64,
            "keyframes_included": False,
        }), encoding="utf-8")
        state = runtime_root / "runtime/pipeline_state" / f"{episode}.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({
            "episode": episode,
            "series_scope": {"scope_id": scope},
            "layers": {"source": "CLI", "paths": {
                key: str(value.resolve()) for key, value in paths.items()
            }},
            "stages": {"S1": {"status": "PASS", "details": {
                "writer_selfcheck_seq29": {"report": str(seq29.resolve())},
                "s1_gate_receipt": {"path": str(s1_receipt.resolve())},
            }}, "S2": {"status": "PASS", "details": {
                "s2_preproduction_receipt": {"path": str(s2_receipt.resolve())},
            }}},
        }), encoding="utf-8")
        source = runtime_root / f"{scope}_{episode}_proposal.json"
        source.write_text(json.dumps({
            "character_matches": [],
            "scene_matches": [],
            "prop_matches": [],
            "ai_generation_proposals": [
                {"entity_type": "character", "entity_id": "CHAR-LEAD", "model": "gpt-image-2-pro", "prompt": "lead portrait", "estimated_credits": 10, "rights_and_identity_note": "Synthetic protagonist proposal for private review."},
                {"entity_type": "scene", "entity_id": "SCENE-A", "model": "gpt-image-2-pro", "prompt": "scene reference", "estimated_credits": 11, "rights_and_identity_note": "Synthetic scene proposal for private review."},
                {"entity_type": "prop", "entity_id": "PROP-A", "model": "gpt-image-2-pro", "prompt": "prop reference", "estimated_credits": 2, "rights_and_identity_note": "Synthetic prop proposal for private review."},
            ],
            "script_summary": "The protagonist enters the first scene with the required prop.",
            "assumptions": [],
            "risks": [],
            "rights_and_identity_notes": [
                "AI identity proposals require the user's complete-plan approval."
            ],
            "total_estimated_credits": 23,
        }), encoding="utf-8")
        return source

    def _record_valid_plan(
        self, runtime_root: Path, *, episode: str = "E01",
        scope: str = "NALU-YEWUJIANG",
    ) -> Path:
        source = self._write_s1_fixture(
            runtime_root, episode=episode, scope=scope
        )
        return runtime.record_asset_plan(runtime_root, episode, source)

    def _fixture_layer_paths(self, runtime_root: Path, episode: str = "E01"):
        state = json.loads(
            (runtime_root / "runtime/pipeline_state" / f"{episode}.json").read_text()
        )
        paths = {
            key: Path(value) for key, value in state["layers"]["paths"].items()
        }
        lexicon = paths["writer_manifest"].parent / f"{episode}_PROJECT_LEXICON_v1.json"
        lexicon.write_text(json.dumps({
            "schema": "qingshan.lexicon.v1", "status": "SCRIPT_DERIVED",
        }), encoding="utf-8")
        paths["project_lexicon"] = lexicon
        return paths

    def _confirmation_receipt(
        self, runtime_root: Path, plan_path: Path, *, episode: str = "E01",
        scope: str = "NALU-YEWUJIANG", owner: str = "owner-test",
    ) -> Path:
        config_path = runtime_root / "qingshan.json"
        config = json.loads(config_path.read_text())
        config["authorization"]["line_owner_id"] = owner
        config_path.write_text(json.dumps(config), encoding="utf-8")
        plan = json.loads(plan_path.read_text())
        root = Path(config["authorization"]["confirmation_receipts_root"])
        root.mkdir(parents=True, exist_ok=True)
        receipt = root / f"{scope}_{episode}_confirmation.json"
        receipt.write_text(json.dumps({
            "schema": "storyclaw.asset_plan_confirmation_receipt.v1",
            "status": "CONFIRMED",
            "episode": episode,
            "series_scope_id": scope,
            "line_owner_id": owner,
            "asset_plan_sha256": runtime.sha256(plan_path),
            "script_evidence_sha256": plan["script_evidence_sha256"],
            "verbatim": "我确认采用这份完整素材方案。",
            "message_or_event_id": "storyclaw-event-001",
            "confirmed_at_utc": "2026-09-20T12:00:00Z",
        }), encoding="utf-8")
        return receipt

    def _confirm_valid_plan(
        self, runtime_root: Path, plan_path: Path, *, episode: str = "E01",
        scope: str = "NALU-YEWUJIANG",
    ) -> tuple[Path, Path]:
        receipt = self._confirmation_receipt(
            runtime_root, plan_path, episode=episode, scope=scope
        )
        confirmation = runtime.confirm_asset_plan(
            runtime_root, episode, receipt, runtime.sha256(receipt)
        )
        return confirmation, receipt

    def test_preflight_rejects_unapproved_model(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "qingshan_engine").mkdir()
            (root / "tools").mkdir()
            (root / "lines/nalu/runtime/tools").mkdir(parents=True)
            (root / "lines/nalu/runtime/tools/nalu_pipeline.py").write_text("", encoding="utf-8")
            (root / "lines/nalu/runtime/tools/nalu_paths.py").write_text("", encoding="utf-8")
            runtime_root = root / "runtime"
            runtime.init_runtime(root, runtime_root)
            with patch.dict(os.environ, {"STORYCLAW_MODEL": "storyclaw/MiniMax-M2.7"}):
                result = runtime.preflight(root, runtime_root)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("model", result["failures"])

    def test_fresh_generic_init_does_not_select_historical_series_or_platforms(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "qingshan_engine").mkdir()
            (root / "tools").mkdir()
            runtime_root = root / "runtime"
            runtime.init_runtime(root, runtime_root)
            config = json.loads((runtime_root / "qingshan.json").read_text())
            self.assertEqual(config["storyclaw"]["series_scope_id"], "UNCONFIGURED")
            self.assertFalse(config["release"]["automatic_platform_upload_enabled"])
            self.assertNotIn("order", config["release"])

    def test_paid_requires_two_config_locks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "qingshan_engine").mkdir()
            (root / "tools").mkdir()
            (root / "lines/nalu/runtime/tools").mkdir(parents=True)
            (root / "lines/nalu/runtime/tools/nalu_pipeline.py").write_text("", encoding="utf-8")
            (root / "lines/nalu/runtime/tools/nalu_paths.py").write_text("", encoding="utf-8")
            runtime_root = root / "runtime"
            runtime.init_runtime(root, runtime_root)
            with self.assertRaises(SystemExit) as ctx:
                runtime.run_episode(root, runtime_root, "E06", "S3", "S3", True, False)
            self.assertIn("paid requires both", str(ctx.exception))

    def test_run_rejects_unapproved_model_before_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "qingshan_engine").mkdir()
            (root / "tools").mkdir()
            (root / "lines/nalu/runtime/tools").mkdir(parents=True)
            (root / "lines/nalu/runtime/tools/nalu_pipeline.py").write_text("", encoding="utf-8")
            (root / "lines/nalu/runtime/tools/nalu_paths.py").write_text("", encoding="utf-8")
            runtime_root = root / "runtime"
            runtime.init_runtime(root, runtime_root)
            with patch.dict(os.environ, {"STORYCLAW_MODEL": "storyclaw/MiniMax-M2.7"}):
                with self.assertRaises(SystemExit) as ctx:
                    runtime.run_episode(root, runtime_root, "E06", "S1", "S2", False, True)
            self.assertIn("approved high-capability allowlist", str(ctx.exception))

    def test_preflight_accepts_configured_high_capability_fallback(self):
        td, root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        for model in ("storyclaw/claude-opus-5", "storyclaw/gpt-5.6-sol"):
            with self.subTest(model=model), patch.dict(
                os.environ, {"STORYCLAW_MODEL": model}
            ):
                result = runtime.preflight(root, runtime_root)
            self.assertEqual(result["checks"]["model"]["status"], "PASS")
            self.assertEqual(result["checks"]["policy_profile"]["status"], "PASS")

    def test_configure_series_selects_declared_new_series(self):
        td, _root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        scopes = runtime_root / "runtime/series_scopes.json"
        scopes.write_text(json.dumps({
            "schema": "nalu.series_scopes.v1",
            "default_scope": "NALU-YEWUJIANG",
            "scopes": {"FOBENSHIDAO": {}},
            "episodes": {},
        }), encoding="utf-8")
        result = runtime.configure_series_scope(runtime_root, "FOBENSHIDAO")
        self.assertEqual(result["scope_id"], "FOBENSHIDAO")
        config = json.loads((runtime_root / "qingshan.json").read_text())
        self.assertEqual(config["storyclaw"]["series_scope_id"], "FOBENSHIDAO")

    def test_heartbeat_missing_state_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            result = runtime.heartbeat(Path(td), "E06")
            self.assertEqual(result["status"], "BLOCKED")

    def test_run_and_heartbeat_fail_closed_while_engine_upgrade_barrier_is_exclusive(self):
        td, root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        barrier = runtime_root / runtime.UPGRADE_BARRIER_RELATIVE
        barrier.parent.mkdir(parents=True, exist_ok=True)
        with barrier.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(SystemExit, "engine upgrade is in progress"):
                runtime.run_episode(
                    root, runtime_root, "E01", "S1", "S1", False, True
                )
            with self.assertRaisesRegex(SystemExit, "engine upgrade is in progress"):
                runtime.heartbeat(runtime_root, "E01")
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def test_production_barrier_recovers_each_crash_point_before_running(self):
        for crash_point in ("venv_switched", "both_switched", "state_written"):
            with self.subTest(crash_point=crash_point), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                runtime_root = root / "private-runtime"
                runtime_root.mkdir()
                project = root / "project"
                releases = project / "releases"
                old_engine = releases / "v1"
                new_engine = releases / "v2"
                old_engine.mkdir(parents=True)
                new_engine.mkdir()
                engine_link = project / "current"
                os.symlink(old_engine, engine_link)
                old_venv = runtime_root / "runtime/storyclaw_host/venvs/v1"
                new_venv = runtime_root / "runtime/storyclaw_host/venvs/v2"
                (old_venv / "bin").mkdir(parents=True)
                (new_venv / "bin").mkdir(parents=True)
                (old_venv / "bin/python").write_text("old")
                (new_venv / "bin/python").write_text("new")
                selector = runtime_root / "runtime/storyclaw_host/current-venv"
                os.symlink(old_venv, selector)
                current_state_path = (
                    runtime_root / "runtime/storyclaw_host/current-release.json"
                )
                discovery_state_path = (
                    runtime_root
                    / "runtime/storyclaw_release_discovery/trusted_state.json"
                )
                old_current = {"schema": "old.current", "release_sequence": 1}
                old_discovery = {"schema": "old.discovery", "status": "AVAILABLE"}
                current_state_path.write_text(json.dumps(old_current))
                discovery_state_path.parent.mkdir(parents=True)
                discovery_state_path.write_text(json.dumps(old_discovery))
                receipt = (
                    runtime_root
                    / "runtime/receipts/storyclaw_engine_upgrades/new.json"
                )
                receipt.parent.mkdir(parents=True)

                runtime._upgrade_transaction.write_prepared(runtime_root, {
                    "releases_root": str(releases),
                    "engine_link": str(engine_link),
                    "old_engine": str(old_engine),
                    "new_engine": str(new_engine),
                    "old_engine_raw_link": os.readlink(engine_link),
                    "venv_selector": str(selector),
                    "old_venv": str(old_venv),
                    "new_venv": str(new_venv),
                    "old_venv_raw_link": os.readlink(selector),
                    "current_release_state_path": str(current_state_path),
                    "discovery_state_path": str(discovery_state_path),
                    "prior_current_release_state": old_current,
                    "prior_discovery_state": old_discovery,
                    "receipt_path": str(receipt),
                })
                runtime._upgrade_transaction.atomic_symlink_raw(selector, str(new_venv))
                if crash_point in {"both_switched", "state_written"}:
                    runtime._upgrade_transaction.atomic_symlink_raw(
                        engine_link, str(new_engine)
                    )
                if crash_point == "state_written":
                    current_state_path.write_text(json.dumps({"release_sequence": 2}))
                    discovery_state_path.write_text(json.dumps({"status": "APPLIED"}))
                    receipt.write_text("candidate receipt")

                with runtime._production_barrier(runtime_root):
                    self.assertFalse(
                        runtime._upgrade_transaction.journal_path(runtime_root).exists()
                    )
                self.assertEqual(engine_link.resolve(), old_engine.resolve())
                self.assertEqual(selector.resolve(), old_venv.resolve())
                self.assertEqual(json.loads(current_state_path.read_text()), old_current)
                self.assertEqual(json.loads(discovery_state_path.read_text()), old_discovery)
                self.assertFalse(new_engine.exists())
                self.assertFalse(new_venv.exists())
                self.assertFalse(receipt.exists())

    def test_s3_requires_s1_pass(self):
        td, root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        with self.assertRaises(SystemExit) as ctx:
            runtime.run_episode(root, runtime_root, "E01", "S3", "S3", False, True)
        self.assertIn("S1 PASS", str(ctx.exception))

    def test_s2_cannot_bypass_missing_sealed_writer_handoff(self):
        td, root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        with self.assertRaisesRegex(
            SystemExit, "cannot bypass the sealed private writer handoff"
        ):
            runtime.run_episode(root, runtime_root, "E01", "S2", "S2", False, True)

    def test_s3_requires_confirmed_asset_plan(self):
        td, root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        state = runtime_root / "runtime/pipeline_state/E01.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"stages": {"S1": {"status": "PASS"}}}), encoding="utf-8")
        with self.assertRaises(SystemExit) as ctx:
            runtime.run_episode(root, runtime_root, "E01", "S3", "S3", False, True)
        self.assertIn("confirmed script-derived asset matching plan", str(ctx.exception))

    def test_proposal_cannot_be_used_as_confirmation(self):
        td, root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        path = self._record_valid_plan(runtime_root)
        self.assertEqual(json.loads(path.read_text())["status"], "PROPOSED")
        with self.assertRaises(SystemExit):
            runtime.run_episode(root, runtime_root, "E01", "S3", "S3", False, True)

    def test_confirmed_plan_allows_stage_guard_then_pipeline(self):
        td, root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        selected_venv = runtime_root / "runtime/storyclaw_host/venvs/v1"
        selected_python = selected_venv / "bin/python"
        selected_python.parent.mkdir(parents=True)
        selected_python.write_text("private python", encoding="utf-8")
        selector = runtime_root / "runtime/storyclaw_host/current-venv"
        os.symlink(selected_venv, selector)
        plan_path = self._record_valid_plan(runtime_root)
        confirmation_path, receipt = self._confirm_valid_plan(
            runtime_root, plan_path
        )
        confirmation = json.loads(confirmation_path.read_text())
        self.assertEqual(confirmation["asset_plan_path"], str(plan_path.resolve()))
        self.assertEqual(confirmation["asset_plan_sha256"], runtime.sha256(plan_path))
        self.assertEqual(confirmation["receipt_path"], str(receipt.resolve()))
        self.assertEqual(confirmation["receipt_sha256"], runtime.sha256(receipt))
        layers = self._fixture_layer_paths(runtime_root)
        with patch.object(
            runtime._writer_workflow, "resolve_active_layers", return_value=layers
        ), patch.object(
            runtime._writer_workflow, "verify_writer_handoff",
            return_value={"status": "PASS", "failures": []},
        ), patch.object(runtime.subprocess, "run") as run:
            run.return_value.returncode = 0
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("NALU_VENV_PYTHON", None)
                result = runtime.run_episode(
                    root, runtime_root, "E01", "S3", "S3", False, True
                )
        self.assertEqual(result, 0)
        self.assertEqual(run.call_args.args[0][0], str(selected_python.resolve()))
        self.assertEqual(
            run.call_args.kwargs["env"]["NALU_VENV_PYTHON"],
            str(selected_python.resolve()),
        )
        self.assertEqual(run.call_args.kwargs["env"]["NALU_SERIES_SCOPE_ID"], "NALU-YEWUJIANG")
        self.assertEqual(run.call_args.kwargs["env"]["NALU_POLICY_PROFILE"], "CURRENT_PORTABLE")
        self.assertEqual(
            run.call_args.kwargs["env"]["NALU_PROJECT_LEXICON"],
            str(layers["project_lexicon"]),
        )
        receipt = max(
            (runtime_root / "runtime/storyclaw_runs").glob("*.json"),
            key=lambda path: path.stat().st_mtime_ns,
        )
        run_receipt = json.loads(receipt.read_text())
        selected = run_receipt["venv_python"]
        self.assertEqual(selected["configured_path"], str(selector / "bin/python"))
        self.assertEqual(selected["resolved_python"], str(selected_python.resolve()))
        self.assertIsNone(run_receipt["release_commit"])
        self.assertEqual(run_receipt["project_id"], "")
        self.assertEqual(run_receipt["from_stage"], "S3")
        self.assertEqual(run_receipt["until_stage"], "S3")
        self.assertEqual(run_receipt["target_stage"], "S3")
        self.assertEqual(run_receipt["paid_posts"], 0)
        self.assertFalse(run_receipt["provider_posts_allowed"])
        self.assertFalse(run_receipt["paid_lock_evidence"]["provider_key_present"])

    def test_run_rejects_legacy_policy_profile(self):
        td, root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        cfg = runtime_root / "qingshan.json"
        data = json.loads(cfg.read_text())
        data["storyclaw"]["policy_profile"] = "LEGACY_EPISODE_COMPAT"
        cfg.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(SystemExit) as ctx:
            runtime.run_episode(root, runtime_root, "E01", "S1", "S2", False, True)
        self.assertIn("policy_profile=CURRENT_PORTABLE", str(ctx.exception))

    def test_confirmation_requires_exact_current_proposal_sha(self):
        td, _root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        plan_path = self._record_valid_plan(runtime_root)
        receipt = self._confirmation_receipt(runtime_root, plan_path)
        data = json.loads(receipt.read_text())
        data["asset_plan_sha256"] = "0" * 64
        receipt.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(SystemExit) as ctx:
            runtime.confirm_asset_plan(
                runtime_root, "E01", receipt, runtime.sha256(receipt)
            )
        self.assertIn("RECEIPT_FIELD_MISMATCH:asset_plan_sha256", str(ctx.exception))

    def test_s3_revalidates_proposal_sha_on_every_run(self):
        td, root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        plan_path = self._record_valid_plan(runtime_root)
        self._confirm_valid_plan(runtime_root, plan_path)
        layers = self._fixture_layer_paths(runtime_root)
        with patch.object(
            runtime._writer_workflow, "resolve_active_layers", return_value=layers
        ), patch.object(
            runtime._writer_workflow, "verify_writer_handoff",
            return_value={"status": "PASS", "failures": []},
        ), patch.object(runtime.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertEqual(runtime.run_episode(root, runtime_root, "E01", "S3", "S3", False, True), 0)
        plan = json.loads(plan_path.read_text())
        plan["ai_generation_proposals"][0]["prompt"] = "changed-after-confirmation"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaises(SystemExit) as ctx:
            runtime.run_episode(root, runtime_root, "E01", "S3", "S3", False, True)
        self.assertIn("asset_plan_sha256_mismatch", str(ctx.exception))

    def test_s3_revalidates_receipt_sha_on_every_run(self):
        td, root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        plan_path = self._record_valid_plan(runtime_root)
        _confirmation, receipt = self._confirm_valid_plan(runtime_root, plan_path)
        receipt_data = json.loads(receipt.read_text())
        receipt_data["verbatim"] = "changed-after-confirmation"
        receipt.write_text(json.dumps(receipt_data), encoding="utf-8")
        with self.assertRaises(SystemExit) as ctx:
            runtime.run_episode(root, runtime_root, "E01", "S3", "S3", False, True)
        self.assertIn("RECEIPT_SHA256_MISMATCH", str(ctx.exception))

    def test_new_proposal_invalidates_previous_confirmation(self):
        td, root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        source = self._write_s1_fixture(runtime_root)
        plan_path = runtime.record_asset_plan(runtime_root, "E01", source)
        confirmation_path, _receipt = self._confirm_valid_plan(
            runtime_root, plan_path
        )
        self.assertTrue(confirmation_path.is_file())
        runtime.record_asset_plan(runtime_root, "E01", source)
        self.assertFalse(confirmation_path.exists())
        with self.assertRaises(SystemExit) as ctx:
            runtime.run_episode(root, runtime_root, "E01", "S3", "S3", False, True)
        self.assertIn("user_confirmation_missing", str(ctx.exception))

    def test_preflight_proves_private_workspace_and_transaction_mounts(self):
        td, root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        result = runtime.preflight(root, runtime_root)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["checks"]["engine_code_read_only"]["status"], "PASS")
        for name in ("workspace_store", "transaction_store"):
            check = result["checks"][name]
            self.assertEqual(check["status"], "PASS")
            self.assertTrue(check["same_storage_object"])
            self.assertTrue(check["writable"])
            self.assertTrue(check["flock"])

    def test_preflight_blocks_writable_engine_and_unmounted_private_stores(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "engine"
            (root / "qingshan_engine").mkdir(parents=True)
            (root / "tools").mkdir()
            (root / "lines/nalu/runtime/tools").mkdir(parents=True)
            (root / "lines/nalu/runtime/tools/nalu_pipeline.py").write_text("", encoding="utf-8")
            (root / "lines/nalu/runtime/tools/nalu_paths.py").write_text("", encoding="utf-8")
            runtime_root = Path(td) / "runtime"
            runtime.init_runtime(root, runtime_root)
            result = runtime.preflight(root, runtime_root)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("engine_code_read_only", result["failures"])
            self.assertIn("workspace_store", result["failures"])
            self.assertIn("transaction_store", result["failures"])
            self.assertEqual(
                result["checks"]["engine_code_read_only"]["reason"],
                "engine_checkout_is_writable",
            )

    def test_run_repeats_storage_guard_before_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "engine"
            (root / "qingshan_engine").mkdir(parents=True)
            (root / "tools").mkdir()
            (root / "lines/nalu/runtime/tools").mkdir(parents=True)
            (root / "lines/nalu/runtime/tools/nalu_pipeline.py").write_text("", encoding="utf-8")
            (root / "lines/nalu/runtime/tools/nalu_paths.py").write_text("", encoding="utf-8")
            runtime_root = Path(td) / "runtime"
            runtime.init_runtime(root, runtime_root, legacy_default_scope=True)
            with patch.object(runtime, "_engine_readonly_probe", return_value={
                "status": "PASS", "path": str(root), "mode": "READ_ONLY",
            }), patch.object(runtime.subprocess, "run") as run:
                with self.assertRaises(SystemExit) as ctx:
                    runtime.run_episode(root, runtime_root, "E01", "S1", "S2", False, True)
            self.assertIn("workspace_store", str(ctx.exception))
            self.assertIn("transaction_store", str(ctx.exception))
            run.assert_not_called()

    def test_nondefault_series_rejects_unscoped_old_e01_state_and_plan(self):
        td, _root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        scopes = runtime_root / "runtime/series_scopes.json"
        scopes.write_text(json.dumps({
            "schema": "nalu.series_scopes.v1",
            "default_scope": "NALU-YEWUJIANG",
            "scopes": {"FOBENSHIDAO": {}},
            "episodes": {},
        }), encoding="utf-8")
        runtime.configure_series_scope(runtime_root, "FOBENSHIDAO")
        source = self._write_s1_fixture(runtime_root)
        with self.assertRaises(SystemExit) as ctx:
            runtime.record_asset_plan(runtime_root, "E01", source)
        self.assertIn("exact S1 evidence", str(ctx.exception))

        source = self._write_s1_fixture(runtime_root, scope="FOBENSHIDAO")
        plan_path = runtime.record_asset_plan(runtime_root, "E01", source)
        self.assertEqual(json.loads(plan_path.read_text())["series_scope_id"], "FOBENSHIDAO")
        confirmation_path, _receipt = self._confirm_valid_plan(
            runtime_root, plan_path, scope="FOBENSHIDAO"
        )
        self.assertEqual(
            json.loads(confirmation_path.read_text())["series_scope_id"],
            "FOBENSHIDAO",
        )
        self.assertEqual(runtime.validate_asset_plan(runtime_root, "E01"), (True, "PASS"))

        runtime.configure_series_scope(runtime_root, "NALU-YEWUJIANG")
        valid, reason = runtime.validate_asset_plan(runtime_root, "E01")
        self.assertFalse(valid)
        self.assertEqual(reason, "ASSET_PLAN_FILE_MISSING")

    def test_confirmation_receipt_must_bind_selected_series(self):
        td, _root, runtime_root = self._root()
        self.addCleanup(td.cleanup)
        plan_path = self._record_valid_plan(runtime_root)
        receipt = self._confirmation_receipt(runtime_root, plan_path)
        data = json.loads(receipt.read_text())
        data["series_scope_id"] = "FOBENSHIDAO"
        receipt.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(SystemExit) as ctx:
            runtime.confirm_asset_plan(
                runtime_root, "E01", receipt, runtime.sha256(receipt)
            )
        self.assertIn("RECEIPT_FIELD_MISMATCH:series_scope_id", str(ctx.exception))

    def test_public_bundle_reads_only_committed_git_objects(self):
        with tempfile.TemporaryDirectory() as td:
            engine = Path(td) / "engine"
            (engine / "tools").mkdir(parents=True)
            (engine / "qingshan_engine").mkdir()
            (engine / "tools/tracked.txt").write_text("committed\n", encoding="utf-8")
            (engine / "workflow/nalu/E01").mkdir(parents=True)
            (engine / "workflow/nalu/E01/private.txt").write_text("workspace-private\n", encoding="utf-8")
            (engine / "workflow/tasks").mkdir(parents=True)
            (engine / "workflow/tasks/private.txt").write_text("transaction-private\n", encoding="utf-8")
            (engine / "sources").mkdir()
            (engine / "sources/novel.txt").write_text("source-private\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(engine)], check=True)
            subprocess.run(["git", "-C", str(engine), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(engine), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(engine), "add", "."], check=True)
            subprocess.run(["git", "-C", str(engine), "commit", "-qm", "fixture"], check=True)

            (engine / "tools/tracked.txt").write_text("uncommitted replacement\n", encoding="utf-8")
            (engine / "tools/untracked_secret.py").write_text("SECRET = True\n", encoding="utf-8")
            (engine / "tools/storyclaw_nalu_runtime.py").write_text("UNCOMMITTED_ADAPTER = True\n", encoding="utf-8")
            output = Path(td) / "bundle.tar.gz"
            receipt = runtime.public_bundle(engine, output)
            self.assertEqual(receipt["status"], "PASS")
            with tarfile.open(output, "r:gz") as archive:
                names = set(archive.getnames())
                tracked = archive.extractfile("qingshan-engine/tools/tracked.txt")
                self.assertIsNotNone(tracked)
                self.assertEqual(tracked.read(), b"committed\n")
                self.assertNotIn("qingshan-engine/tools/untracked_secret.py", names)
                self.assertNotIn("qingshan-engine/tools/storyclaw_nalu_runtime.py", names)
                self.assertFalse(any("workflow/nalu/" in name for name in names))
                self.assertFalse(any("workflow/tasks/" in name for name in names))
                self.assertFalse(any("sources/" in name for name in names))
                manifest_file = archive.extractfile(
                    "qingshan-engine/tools/STORYCLAW_BUNDLE_MANIFEST.json"
                )
                self.assertIsNotNone(manifest_file)
                manifest = json.loads(manifest_file.read())
                self.assertEqual(manifest["source"], "COMMITTED_GIT_OBJECTS_ONLY")
                self.assertFalse(manifest["working_tree_used"])


if __name__ == "__main__":
    unittest.main()
