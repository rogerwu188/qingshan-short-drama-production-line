import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools/build_storyclaw_cloud_factory_bundles.py"
SPEC = importlib.util.spec_from_file_location("cloud_factory_bundle_builder", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class CloudFactoryBundleBuilderTest(unittest.TestCase):
    @staticmethod
    def registry_paths():
        data = json.loads(MODULE.REGISTRY.read_text(encoding="utf-8"))
        paths = set()
        for gate in data.get("gates", []):
            for field in ("code_paths", "test_paths", "stage_runner_paths"):
                paths.update(str(item) for item in gate.get(field, []) if item)
            checklist = gate.get("manual_checklist_path")
            if checklist:
                paths.add(str(checklist))
        return paths

    def test_all_five_roles_build_with_sha_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            receipts = [
                MODULE.build_bundle(role, spec, MODULE.DEFAULT_SOURCE, dist)
                for role, spec in MODULE.ROLE_SEEDS.items()
            ]
            self.assertEqual(
                {item["role"] for item in receipts},
                {
                    "qingshan-producer-supervisor",
                    "qingshan-claude-writer",
                    "qingshan-ai-drama-pipeline",
                    "qingshan-agent-cut-cloud",
                    "qingshan-ai-aduit",
                },
            )
            for receipt in receipts:
                self.assertEqual(len(receipt["archive_sha256"]), 64)
                self.assertGreater(receipt["file_count"], 0)
                self.assertEqual(receipt["package_self_test"], "PASS")
                manifest_path = Path(receipt["bundle_dir"]) / "BUNDLE_SHA256_MANIFEST.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(manifest["file_count"], len(manifest["files"]))
                paths = {item["source_path"] for item in manifest["files"]}
                self.assertIn(
                    "workflow/cloud_factory_migration_v1_20260724/SHARED_DIRECTORY_PROTOCOL_V2.md",
                    paths,
                )
                self.assertIn(
                    "workflow/cloud_factory_migration_v1_20260724/FACTORY_PRODUCT_MANIFEST.json",
                    paths,
                )
                self.assertIn(
                    "workflow/cloud_factory_migration_v1_20260724/TALENT_HUB_PORTABILITY_CONTRACT.md",
                    paths,
                )
                self.assertIn(
                    "workflow/cloud_factory_migration_v1_20260724/contracts/PRODUCTION_PROVEN_QUALITY_BASELINE_V1.md",
                    paths,
                )
                self.assertIn(
                    "workflow/cloud_factory_migration_v1_20260724/migrations/2.0.8_PRODUCTION_PROVEN_WRITER_AUDIT_BASELINE.md",
                    paths,
                )
                for workbench_file in (
                    "README.md",
                    "build_status.py",
                    "index.html",
                    "status.js",
                    "status.example.json",
                    "status_schema_v1.json",
                ):
                    self.assertIn(
                        "workflow/cloud_factory_migration_v1_20260724/"
                        f"customer_workbench/{workbench_file}",
                        paths,
                    )
                for prompt_file in ("IDENTITY.md", "USER.md", "SOUL.md", "AGENTS.md"):
                    self.assertIn(
                        "workflow/cloud_factory_migration_v1_20260724/"
                        f"prompt_files/{receipt['role']}/{prompt_file}",
                        paths,
                    )
                if receipt["role"] == "qingshan-agent-cut-cloud":
                    self.assertIn("tools/bootstrap_cloud_agentcut_runtime.sh", paths)
                    self.assertIn(
                        "workflow/cloud_factory_migration_v1_20260724/"
                        "runtime_wheels_portable/agentcut-0.9.16-py3-none-any.whl",
                        paths,
                    )
                    wheel_path = (
                        Path(receipt["bundle_dir"])
                        / "workflow/cloud_factory_migration_v1_20260724/"
                        "runtime_wheels_portable/agentcut-0.9.16-py3-none-any.whl"
                    )
                    with zipfile.ZipFile(wheel_path) as wheel:
                        self.assertIn("agentcut/release_gate.py", wheel.namelist())
                expected_registry_paths = MODULE.registry_files(
                    tuple(MODULE.ROLE_SEEDS[receipt["role"]]["stage_tokens"])
                )
                self.assertTrue(
                    expected_registry_paths.issubset(paths),
                    f"{receipt['role']} omitted its stage gate dependencies",
                )
                scoped_registry = json.loads(
                    (Path(receipt["bundle_dir"]) / "configs/GATE_REGISTRY_v3_20260716.json").read_text(
                        encoding="utf-8"
                    )
                )
                stages = tuple(MODULE.ROLE_SEEDS[receipt["role"]]["stage_tokens"])
                if stages:
                    self.assertEqual(
                        scoped_registry["package_scope"]["role"],
                        receipt["role"],
                    )
                    self.assertTrue(
                        {
                            str(gate.get("stage", "")).upper()
                            for gate in scoped_registry.get("gates", [])
                        }.issubset(set(stages))
                    )
                self.assertFalse(any(".secrets" in path for path in paths))
                self.assertFalse(
                    any(
                        MODULE.is_forbidden_bundle_path(path)
                        for path in paths
                    ),
                    f"{receipt['role']} contains project-specific assets or history",
                )
                self.assertFalse(
                    MODULE.scan_forbidden_content(paths),
                    f"{receipt['role']} contains project-specific text references",
                )
                self.assertNotIn("workflow/agent_mistake_ledger.json", paths)
                self.assertNotIn("codex_docs/CLAUDE_TO_CODEX.md", paths)
                self.assertNotIn("workflow/CODEX_TO_CLAUDE.md", paths)
                self.assertNotIn(
                    "configs/e35_agentcut_v1_release_20260723.json",
                    paths,
                )
                self.assertNotIn(
                    "workflow/script_review/剧本审核_经验记忆_MEMORY.md",
                    paths,
                )
                if receipt["role"] == "qingshan-claude-writer":
                    for required_path in (
                        "tools/canonical_writer_provenance.py",
                        "tools/canonical_writer_dispatcher.py",
                        "tools/shot_duration_policy.py",
                        "tools/common_sense_causality_gate.py",
                        "tools/tests/test_canonical_writer_dispatcher.py",
                        "tools/tests/test_shot_duration_policy.py",
                        "tools/tests/test_common_sense_causality_gate.py",
                    ):
                        self.assertIn(required_path, paths)
                if receipt["role"] == "qingshan-ai-aduit":
                    for required_path in (
                        "tools/scene_authority_lock.py",
                        "tools/shot_duration_policy.py",
                        "tools/common_sense_causality_gate.py",
                        "tools/cut_motivation_gate.py",
                        "tools/audience_score_gate.py",
                        "tools/defect_tolerance_gate.py",
                        "tools/final_package_blocker_gate.py",
                        "tools/source_brightness_jump_audit.py",
                        "tools/tests/test_scene_authority_lock.py",
                        "tools/tests/test_shot_duration_policy.py",
                        "tools/tests/test_common_sense_causality_gate.py",
                        "tools/tests/test_cut_motivation_gate_portable.py",
                        "tools/tests/test_audience_score_gate.py",
                        "tools/tests/test_defect_tolerance_gate.py",
                        "tools/tests/test_final_cut_quality_gates_portable.py",
                        "tools/tests/test_final_package_blocker_gate.py",
                        "tools/tests/test_frame_cadence_audit.py",
                        "tools/tests/test_source_brightness_jump_audit.py",
                    ):
                        self.assertIn(required_path, paths)
                bundle_dir = Path(receipt["bundle_dir"])
                for required in (
                    "talent_hub_hire.json",
                    "install_contract.json",
                    "SHA256_MANIFEST.json",
                    "install.py",
                    "doctor.py",
                    "self_test.py",
                    "migrate.py",
                    "rollback.py",
                ):
                    self.assertTrue((bundle_dir / "package" / required).is_file())
                check = subprocess.run(
                    [sys.executable, str(bundle_dir / "package/self_test.py")],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
                self.assertEqual(
                    json.loads(check.stdout)["privacy_scan"],
                    "PASS",
                )

    def test_product_roles_have_bootstrap_and_generic_charters(self):
        for role in ("qingshan-producer-supervisor", "qingshan-claude-writer"):
            spec = MODULE.ROLE_SEEDS[role]
            self.assertTrue(
                (MODULE.DEFAULT_SOURCE / str(spec["charter"])).is_file()
            )
            self.assertTrue(
                (MODULE.DEFAULT_SOURCE / "bootstrap_messages" / f"{role}.md").is_file()
            )

    def test_pipeline_bundle_keeps_one_ready_one_submit_rule(self):
        charter = (
            MODULE.DEFAULT_SOURCE
            / "charters/青山AI_Drama_Pipeline_云端可移植宪章.md"
        ).read_text(encoding="utf-8")
        self.assertIn("一就绪即独立预检、去重并立即提交", charter)
        self.assertIn("一单元可以 1 张或多张图", charter)
        self.assertIn("禁止默认雨夜", charter)

    def test_shared_protocol_requires_real_gate_invocation(self):
        protocol = (MODULE.DEFAULT_SOURCE / "SHARED_DIRECTORY_PROTOCOL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("只有工具实际被调用才允许 `invoked=true`", protocol)
        self.assertIn("PENDING_REFUND", protocol)

    def test_product_protocol_limits_heavy_media_without_batch_waiting(self):
        protocol = (
            MODULE.DEFAULT_SOURCE / "SHARED_DIRECTORY_PROTOCOL_V2.md"
        ).read_text(encoding="utf-8")
        self.assertIn("同机总并发上限为 1", protocol)
        self.assertIn("禁止把整段 1080×1920 视频全部载入内存", protocol)
        self.assertIn("一个视频单元一就绪仍应立即进入队列和预检", protocol)
        self.assertIn("INTERRUPTED_RECOVERABLE", protocol)

    def test_product_protocol_locks_full_series_before_episode_one_review(self):
        protocol = (
            MODULE.DEFAULT_SOURCE / "SHARED_DIRECTORY_PROTOCOL_V2.md"
        ).read_text(encoding="utf-8")
        self.assertIn("FULL_SERIES_WRITER", protocol)
        self.assertIn("FULL_SERIES_SCRIPT_GATE", protocol)
        self.assertIn("EP01_SCRIPT_REVIEW", protocol)
        self.assertIn("禁止以“写一集、制造一集”替代全季剧本锁定", protocol)


if __name__ == "__main__":
    unittest.main()
