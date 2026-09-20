"""Tests for immutable StoryClaw/TalentHub release impact classification."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import storyclaw_release_surface as release_surface
from tools import storyclaw_upgrade_classifier as classifier


class StoryClawUpgradeClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self._git("init")
        self._git("config", "user.email", "test@example.invalid")
        self._git("config", "user.name", "Upgrade Classifier Test")
        self._write(
            "lines/nalu/runtime/tools/nalu_pipeline.py",
            'SCHEMA = "nalu.pipeline_state.v1"\nENGINE_VALUE = 1\n',
        )
        self._write(
            "lines/nalu/runtime/tools/nalu_series_scope.py",
            'SCHEMA = "nalu.series_scopes.v1"\n',
        )
        self._write(
            "lines/nalu/runtime/tools/nalu_budget_ledger.py",
            'SCHEMA = "nalu.episode_credit_budget_ledger.v1"\n',
        )
        self._write("engine/core.py", "VALUE = 1\n")
        self._write("pyproject.toml", "[project]\nname = 'fixture'\n")
        self._write(
            "tools/storyclaw_install.py",
            "INSTALLER_VERSION = '1.0.0'\nOFFLINE_ONLY = True\n",
        )
        self._write(
            "tools/storyclaw_writer_workflow.py",
            (
                'INPUT_SCHEMA = "writer.input.v1"\n'
                'LEXICON_DRAFT_SCHEMA = "writer.lexicon.v1"\n'
                'ACTIVE_SCHEMA = "writer.active.v1"\n'
                'SEAL_SCHEMA = "writer.seal.v1"\n'
                "WORKFLOW_VALUE = 1\n"
            ),
        )
        self._write("agent_factory/storyclaw_portable/AGENTS.md", "brain v1\n")
        self.base_commit = self._commit("base")
        self._git("tag", "v1.0.0")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=check,
            text=True,
            capture_output=True,
        )

    def _write(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _commit(self, message: str) -> str:
        self._git("add", ".")
        self._git("commit", "-m", message)
        return self._git("rev-parse", "HEAD").stdout.strip()

    def _classify(self, base: str = "v1.0.0", target: str = "v1.1.0"):
        return classifier.classify_release(base, target, root=self.root)

    def test_engine_change_is_engine_only_and_reports_exact_commits(self):
        self._write("engine/core.py", "VALUE = 2\n")
        target_commit = self._commit("engine")
        self._git("tag", "v1.1.0")

        report = self._classify()
        self.assertEqual(report["update_class"], classifier.ENGINE_ONLY)
        self.assertTrue(report["engine_only_eligible"])
        self.assertFalse(report["dependencies_changed"])
        self.assertFalse(report["runtime_schema_changed"])
        self.assertEqual(report["base"]["commit"], self.base_commit)
        self.assertEqual(report["target"]["commit"], target_commit)
        self.assertEqual(report["changed_paths"], ["engine/core.py"])
        self.assertEqual(report["reasons"][0]["code"], "ENGINE_CODE_CHANGE")

    def test_portable_brain_change_requires_talenthub_package(self):
        self._write("agent_factory/storyclaw_portable/AGENTS.md", "brain v2\n")
        self._commit("brain")
        self._git("tag", "v1.1.0")

        report = self._classify()
        self.assertEqual(report["update_class"], classifier.TALENTHUB_PACKAGE_REQUIRED)
        self.assertTrue(report["talenthub_managed_changed"])
        self.assertFalse(report["runtime_schema_changed"])
        self.assertEqual(
            report["classified_paths"]["talenthub_managed"],
            ["agent_factory/storyclaw_portable/AGENTS.md"],
        )

    def test_classifier_uses_the_complete_shared_talenthub_surface(self):
        self.assertIs(
            classifier.TALENTHUB_MANAGED_EXACT,
            release_surface.TALENTHUB_MANAGED_EXACT,
        )
        for path in sorted(release_surface.TALENTHUB_MANAGED_EXACT):
            with self.subTest(exact=path):
                self.assertTrue(classifier._is_talenthub_managed(path))
        for root in release_surface.TALENTHUB_MANAGED_TREE_ROOTS:
            with self.subTest(tree=root):
                self.assertTrue(classifier._is_talenthub_managed(root + "/nested"))
        for prefix in release_surface.TALENTHUB_MANAGED_FILE_PREFIXES:
            with self.subTest(prefix=prefix):
                self.assertTrue(classifier._is_talenthub_managed(prefix + "NEW.md"))

    def test_writer_workflow_change_requires_talenthub_package(self):
        self._write(
            "tools/storyclaw_writer_workflow.py",
            (
                'INPUT_SCHEMA = "writer.input.v1"\n'
                'LEXICON_DRAFT_SCHEMA = "writer.lexicon.v1"\n'
                'ACTIVE_SCHEMA = "writer.active.v1"\n'
                'SEAL_SCHEMA = "writer.seal.v1"\n'
                "WORKFLOW_VALUE = 2\n"
            ),
        )
        self._commit("writer workflow")
        self._git("tag", "v1.1.0")

        report = self._classify()
        self.assertEqual(report["update_class"], classifier.TALENTHUB_PACKAGE_REQUIRED)
        self.assertEqual(
            report["classified_paths"]["talenthub_managed"],
            ["tools/storyclaw_writer_workflow.py"],
        )

    def test_dependency_change_requires_package_and_sets_boolean(self):
        self._write(
            "pyproject.toml",
            "[project]\nname = 'fixture'\ndependencies = ['requests>=2']\n",
        )
        self._commit("dependency")
        self._git("tag", "v1.1.0")

        report = self._classify()
        self.assertEqual(report["update_class"], classifier.TALENTHUB_PACKAGE_REQUIRED)
        self.assertTrue(report["dependencies_changed"])
        self.assertEqual(report["classified_paths"]["dependencies"], ["pyproject.toml"])

    def test_installer_logic_change_requires_package_without_inventing_dependency_change(self):
        self._write(
            "tools/storyclaw_install.py",
            "INSTALLER_VERSION = '1.1.0'\nOFFLINE_ONLY = True\n",
        )
        self._commit("installer dependencies")
        self._git("tag", "v1.1.0")

        report = self._classify()
        self.assertEqual(report["update_class"], classifier.TALENTHUB_PACKAGE_REQUIRED)
        self.assertFalse(report["dependencies_changed"])
        self.assertIn(
            "tools/storyclaw_install.py",
            report["classified_paths"]["talenthub_managed"],
        )

    def test_dependency_bundle_logic_can_never_ship_as_engine_only(self):
        self._write(
            "tools/storyclaw_dependency_bundle.py",
            "SCHEMA = 'storyclaw.nalu.dependency_bundle.v1'\n",
        )
        self._commit("dependency bundle base")
        base = self._git("rev-parse", "HEAD").stdout.strip()
        self._write(
            "tools/storyclaw_dependency_bundle.py",
            "SCHEMA = 'storyclaw.nalu.dependency_bundle.v1'\nMAX_ARCHIVE_BYTES = 7\n",
        )
        self._commit("change dependency bundle verifier")
        target = self._git("rev-parse", "HEAD").stdout.strip()
        report = classifier.classify_release(base, target, root=self.root)
        self.assertEqual(report["update_class"], classifier.TALENTHUB_PACKAGE_REQUIRED)
        self.assertIn(
            "tools/storyclaw_dependency_bundle.py",
            report["classified_paths"]["talenthub_managed"],
        )

    def test_future_storyclaw_tool_is_fail_closed_to_package_update(self):
        self._write("tools/storyclaw_future.py", "VALUE = 1\n")
        self._commit("future StoryClaw helper")
        self._git("tag", "v1.1.0")
        report = self._classify()
        self.assertEqual(report["update_class"], classifier.TALENTHUB_PACKAGE_REQUIRED)
        self.assertIn(
            "tools/storyclaw_future.py",
            report["classified_paths"]["talenthub_managed"],
        )

    def test_pipeline_state_schema_change_requires_runtime_migration(self):
        self._write(
            "lines/nalu/runtime/tools/nalu_pipeline.py",
            'SCHEMA = "nalu.pipeline_state.v2"\nENGINE_VALUE = 1\n',
        )
        self._commit("schema")
        self._git("tag", "v1.1.0")

        report = self._classify()
        self.assertEqual(report["update_class"], classifier.RUNTIME_MIGRATION_REQUIRED)
        self.assertTrue(report["runtime_schema_changed"])
        self.assertEqual(report["runtime_migration"], "REQUIRED")
        self.assertEqual(
            report["classified_paths"]["runtime_schema"],
            ["lines/nalu/runtime/tools/nalu_pipeline.py"],
        )

    def test_every_registered_persistent_schema_constant_requires_migration(self):
        # Materialize every carrier in one immutable baseline, then create an
        # independent one-constant change from that baseline.  This proves the
        # registry is executable policy rather than documentation only.
        for path, names in classifier.RUNTIME_SCHEMA_CONSTANTS.items():
            self._write(
                path,
                "\n".join(f'{name} = "fixture.{name}.v1"' for name in sorted(names))
                + "\n",
            )
        schema_base = self._commit("all persistent schema carriers")
        for path, names in classifier.RUNTIME_SCHEMA_CONSTANTS.items():
            for name in sorted(names):
                with self.subTest(path=path, constant=name):
                    self._git("reset", "--hard", schema_base)
                    source = (self.root / path).read_text()
                    source = source.replace(
                        f'{name} = "fixture.{name}.v1"',
                        f'{name} = "fixture.{name}.v2"',
                        1,
                    )
                    self._write(path, source)
                    target = self._commit(f"change {path} {name}")
                    report = classifier.classify_release(
                        schema_base, target, root=self.root
                    )
                    self.assertEqual(
                        report["update_class"],
                        classifier.RUNTIME_MIGRATION_REQUIRED,
                    )
                    self.assertIn(path, report["classified_paths"]["runtime_schema"])
        self._git("reset", "--hard", schema_base)

    def test_schema_definition_change_has_precedence_over_managed_change(self):
        self._write(
            "configs/schemas/narrative.schema.json",
            json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}),
        )
        self._write("skills/qingshan-nalu/SKILL.md", "skill v2\n")
        self._commit("schema and skill")
        self._git("tag", "v1.1.0")

        report = self._classify()
        self.assertEqual(report["update_class"], classifier.RUNTIME_MIGRATION_REQUIRED)
        self.assertTrue(report["talenthub_managed_changed"])
        self.assertIn("configs/schemas/narrative.schema.json", report["changed_paths"])
        self.assertIn("skills/qingshan-nalu/SKILL.md", report["changed_paths"])

    def test_non_schema_pipeline_change_remains_engine_only(self):
        self._write(
            "lines/nalu/runtime/tools/nalu_pipeline.py",
            'SCHEMA = "nalu.pipeline_state.v1"\nENGINE_VALUE = 2\n',
        )
        self._commit("pipeline implementation")
        self._git("tag", "v1.1.0")

        report = self._classify()
        self.assertEqual(report["update_class"], classifier.ENGINE_ONLY)
        self.assertFalse(report["runtime_schema_changed"])

    def test_full_commit_ids_are_accepted(self):
        self._write("engine/core.py", "VALUE = 2\n")
        target = self._commit("engine")

        report = classifier.classify_release(
            self.base_commit, target, root=self.root
        )
        self.assertEqual(report["base"]["kind"], "commit")
        self.assertEqual(report["target"]["kind"], "commit")
        self.assertEqual(report["update_class"], classifier.ENGINE_ONLY)

    def test_branch_head_and_abbreviated_commit_are_rejected(self):
        self._git("branch", "release-candidate")
        cases = ("main", "HEAD", "release-candidate", self.base_commit[:12])
        for base in cases:
            with self.subTest(base=base):
                with self.assertRaises(classifier.ClassificationBlocked):
                    classifier.classify_release(base, self.base_commit, root=self.root)

    def test_divergent_target_is_rejected(self):
        self._git("checkout", "-b", "other", self.base_commit)
        self._write("engine/other.py", "OTHER = 1\n")
        other_commit = self._commit("other")
        self._git("tag", "v-other")
        self._git("checkout", "--detach", self.base_commit)
        self._write("engine/core.py", "VALUE = 9\n")
        self._commit("target")
        self._git("tag", "v-target")

        with self.assertRaisesRegex(
            classifier.ClassificationBlocked, "TARGET_NOT_DESCENDANT_OF_BASE"
        ):
            classifier.classify_release("v-other", "v-target", root=self.root)
        self.assertTrue(other_commit)

    def test_cli_emits_machine_readable_blocked_json(self):
        output = subprocess.run(
            [
                "python3",
                str(Path(classifier.__file__)),
                "--repo",
                str(self.root),
                "--base",
                "main",
                "--target",
                self.base_commit,
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(output.returncode, 2)
        payload = json.loads(output.stdout)
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(payload["error"]["code"], "MUTABLE_OR_INVALID_REF")


if __name__ == "__main__":
    unittest.main()
