import argparse
import contextlib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/canonical_writer_dispatcher.py"
sys.path.insert(0, str(ROOT / "tools"))

import canonical_writer_dispatcher as dispatcher  # noqa: E402
from writer_receipt_resolver import resolve as resolve_receipt  # noqa: E402


class CanonicalWriterDispatcherTests(unittest.TestCase):
    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, str(TOOL), *map(str, args)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_start_finish_writes_exact_receipt_and_releases_lease(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            input_bundle = base / "input.json"
            rule = base / "rule.md"
            authority = base / "E41_NARRATIVE_CANONICAL_v5.md"
            receipt = base / "receipt.json"
            locks = base / "locks"
            input_bundle.write_text("{}\n", encoding="utf-8")
            rule.write_text("rule\n", encoding="utf-8")
            authority.write_text("story\n", encoding="utf-8")
            started = self.run_tool(
                "start",
                "--episode", "E41",
                "--version", "5",
                "--writer-run-id", "WRITER-E41-V5-TEST",
                "--agent-id", "qingshan-claude-writer-agent",
                "--provider", "anthropic-cowork",
                "--model-id", "claude-opus-4-8-20260821",
                "--session-or-task-id", "session-e41-v5-test",
                "--input-bundle", input_bundle,
                "--rule", rule,
                "--receipt", receipt,
                "--lock-dir", locks,
            )
            self.assertEqual(0, started.returncode, started.stderr)
            running = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual("RUNNING", running["status"])
            self.assertTrue(Path(running["write_lease"]).is_file())

            duplicate = self.run_tool(
                "start",
                "--episode", "E41",
                "--version", "5",
                "--writer-run-id", "WRITER-E41-V5-SECOND",
                "--agent-id", "qingshan-claude-writer",
                "--provider", "storyclaw",
                "--model-id", "storyclaw/claude-opus-4-8",
                "--session-or-task-id", "session-second",
                "--input-bundle", input_bundle,
                "--rule", rule,
                "--receipt", base / "second.json",
                "--lock-dir", locks,
            )
            self.assertNotEqual(0, duplicate.returncode)

            finished = self.run_tool("finish", "--receipt", receipt, "--authority", authority)
            self.assertEqual(0, finished.returncode, finished.stderr)
            completed = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual("COMPLETED", completed["status"])
            self.assertEqual(64, len(completed["authority_output"]["sha256"]))
            self.assertFalse(Path(completed["write_lease"]).exists())

    def test_generic_model_alias_is_rejected_before_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            input_bundle = base / "input.json"
            rule = base / "rule.md"
            input_bundle.write_text("{}\n", encoding="utf-8")
            rule.write_text("rule\n", encoding="utf-8")
            result = self.run_tool(
                "start",
                "--episode", "E41",
                "--version", "5",
                "--writer-run-id", "WRITER-E41-V5-TEST",
                "--agent-id", "qingshan-claude-writer-agent",
                "--provider", "anthropic-cowork",
                "--model-id", "Claude",
                "--session-or-task-id", "session-test",
                "--input-bundle", input_bundle,
                "--rule", rule,
                "--receipt", base / "receipt.json",
                "--lock-dir", base / "locks",
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("WRITER_MODEL_ID_NOT_EXACT", result.stderr)

    def test_public_talenthub_agent_can_open_a_bound_writer_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            input_bundle = base / "input.json"
            rule = base / "rule.md"
            receipt = base / "receipt.json"
            input_bundle.write_text("{}\n", encoding="utf-8")
            rule.write_text("public portable writer rule\n", encoding="utf-8")
            result = self.run_tool(
                "start",
                "--episode", "E01",
                "--version", "1",
                "--writer-run-id", "WRITER-E01-V1-STORYCLAW",
                "--agent-id", "ai-drama-factory",
                "--provider", "storyclaw",
                "--model-id", "storyclaw/gpt-6-astra",
                "--session-or-task-id", "storyclaw-task-test",
                "--input-bundle", input_bundle,
                "--rule", rule,
                "--receipt", receipt,
                "--lock-dir", base / "locks",
            )
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual("ai-drama-factory", payload["agent_id"])
            self.assertEqual("RUNNING", payload["status"])


class TerminalReceiptIsSealedTests(CanonicalWriterDispatcherTests):
    """SUPERVISOR_ORDERS seq=53 conditions[4]：终态 receipt 不可被二次覆写。"""

    def _start(self, base: Path):
        input_bundle = base / "input.json"
        rule = base / "rule.md"
        receipt = base / "receipt.json"
        locks = base / "locks"
        input_bundle.write_text("{}\n", encoding="utf-8")
        rule.write_text("rule\n", encoding="utf-8")
        started = self.run_tool(
            "start",
            "--episode", "E51",
            "--version", "4",
            "--writer-run-id", "WRITER-E51-V4-TEST",
            "--agent-id", "qingshan-claude-writer-agent",
            "--provider", "anthropic",
            "--model-id", "claude-opus-5",
            "--session-or-task-id", "unit-test",
            "--input-bundle", input_bundle,
            "--rule", rule,
            "--receipt", receipt,
            "--lock-dir", locks,
        )
        self.assertEqual(started.returncode, 0, started.stderr)
        return receipt

    def test_second_abort_on_an_aborted_receipt_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            receipt = self._start(base)
            first = self.run_tool("abort", "--receipt", receipt, "--reason", "real reason")
            self.assertEqual(first.returncode, 0, first.stderr)
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "ABORTED")
            self.assertEqual(payload["abort_reason"], "real reason")

            second = self.run_tool("abort", "--receipt", receipt, "--reason", "test")
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("TERMINAL_WRITER_RUN_CANNOT_BE_ABORTED", second.stderr + second.stdout)
            after = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(after["abort_reason"], "real reason")
            self.assertEqual(after, payload)


class FourLayerSealTests(CanonicalWriterDispatcherTests):
    """SUPERVISOR_ORDERS seq=54 c5 / seq=55 c5：COMPLETED 的 receipt 必须能证明四层已在盘上。

    第 4 层（manifest）无法在租约内落盘——宪章第 22 行要求 manifest 绑定**已完成**
    receipt 的 SHA，把 manifest SHA 写回 receipt 会改变 receipt 字节并令 manifest 的
    申报值作废（两文件互指的 SHA-256 不动点）。故封缄改由 finish 之后的独立件承担。
    """

    EPISODE = "E90"
    VERSION = 7

    def _bootstrap(self, base: Path):
        scripts = base / "scripts"
        scripts.mkdir()
        narrative = scripts / f"{self.EPISODE}_NARRATIVE_CANONICAL_v{self.VERSION}.md"
        directing = scripts / f"{self.EPISODE}_DIRECTING_SCRIPT_v{self.VERSION}.md"
        contract = scripts / f"{self.EPISODE}_GENERATION_CONTRACT_v{self.VERSION}.json"
        narrative.write_text("正文\n", encoding="utf-8")
        directing.write_text("导演稿\n", encoding="utf-8")
        contract.write_text('{"shots": []}\n', encoding="utf-8")
        input_bundle = base / "input.json"
        rule = base / "rule.md"
        input_bundle.write_text("{}\n", encoding="utf-8")
        rule.write_text("rule\n", encoding="utf-8")
        receipt = base / "receipt.json"
        started = self.run_tool(
            "start",
            "--episode", self.EPISODE,
            "--version", self.VERSION,
            "--writer-run-id", f"WRITER-{self.EPISODE}-V{self.VERSION}-TEST",
            "--agent-id", "qingshan-claude-writer-agent",
            "--provider", "anthropic-cowork",
            "--model-id", "claude-opus-5",
            "--session-or-task-id", "unit-test-seal",
            "--input-bundle", input_bundle,
            "--rule", rule,
            "--receipt", receipt,
            "--lock-dir", base / "locks",
        )
        self.assertEqual(0, started.returncode, started.stderr)
        return scripts, narrative, directing, contract, receipt

    def _sha(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _manifest(self, scripts, narrative, directing, contract, receipt) -> Path:
        completed = json.loads(receipt.read_text(encoding="utf-8"))
        manifest = scripts / f"{self.EPISODE}_manifest_v{self.VERSION}.json"
        manifest.write_text(json.dumps({
            "episode": self.EPISODE,
            "version": self.VERSION,
            "narrative_canonical": {
                "authority_path": str(narrative),
                "authority_sha256": self._sha(narrative),
            },
            "directing_script": {"path": str(directing), "sha256": self._sha(directing)},
            "generation_contract": {"path": str(contract), "sha256": self._sha(contract)},
            "writer_provenance": {
                "writer_run_id": completed["writer_run_id"],
                "receipt_path": str(receipt),
                "receipt_sha256": self._sha(receipt),
            },
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest

    def test_finish_refuses_a_declared_layer_that_is_not_on_disk(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            scripts, narrative, directing, contract, receipt = self._bootstrap(base)
            missing = scripts / "not_written.json"
            result = self.run_tool(
                "finish",
                "--receipt", receipt,
                "--authority", narrative,
                "--layer", narrative,
                "--layer", missing,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("WRITER_FINISH_LAYER_MISSING", result.stderr + result.stdout)
            still_running = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual("RUNNING", still_running["status"])

    def test_finish_records_the_three_pre_manifest_layers_by_sha(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            scripts, narrative, directing, contract, receipt = self._bootstrap(base)
            result = self.run_tool(
                "finish",
                "--receipt", receipt,
                "--authority", narrative,
                "--layer", narrative,
                "--layer", directing,
                "--layer", contract,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            completed = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(3, len(completed["layers_at_finish"]))
            self.assertEqual(
                {self._sha(narrative), self._sha(directing), self._sha(contract)},
                {row["sha256"] for row in completed["layers_at_finish"]},
            )

    def test_seal_writes_a_four_layer_record_and_refuses_to_overwrite_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            scripts, narrative, directing, contract, receipt = self._bootstrap(base)
            self.assertEqual(0, self.run_tool(
                "finish", "--receipt", receipt, "--authority", narrative,
                "--layer", narrative, "--layer", directing, "--layer", contract,
            ).returncode)
            manifest = self._manifest(scripts, narrative, directing, contract, receipt)

            checked = self.run_tool(
                "seal", "--receipt", receipt, "--manifest", manifest,
                "--seal-dir", base / "seals", "--lock-dir", base / "locks", "--check",
            )
            self.assertEqual(0, checked.returncode, checked.stderr)
            self.assertEqual("SEALED", json.loads(checked.stdout)["status"])
            self.assertFalse((base / "seals").exists(), "--check must not write")

            sealed = self.run_tool(
                "seal", "--receipt", receipt, "--manifest", manifest,
                "--seal-dir", base / "seals", "--lock-dir", base / "locks",
            )
            self.assertEqual(0, sealed.returncode, sealed.stderr)
            seal_file = base / "seals" / f"{self.EPISODE}_V{self.VERSION}_FOUR_LAYER_SEAL.json"
            self.assertTrue(seal_file.is_file())
            record = json.loads(seal_file.read_text(encoding="utf-8"))
            self.assertEqual("SEALED", record["status"])
            self.assertEqual(
                ["narrative_canonical", "directing_script", "generation_contract", "manifest"],
                [row["layer"] for row in record["layers"]],
            )

            again = self.run_tool(
                "seal", "--receipt", receipt, "--manifest", manifest,
                "--seal-dir", base / "seals", "--lock-dir", base / "locks",
            )
            self.assertNotEqual(0, again.returncode)
            self.assertIn("WRITER_SEAL_ALREADY_EXISTS", again.stderr + again.stdout)

    def test_seal_refuses_when_a_layer_drifted_after_the_manifest_declared_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            scripts, narrative, directing, contract, receipt = self._bootstrap(base)
            self.assertEqual(0, self.run_tool(
                "finish", "--receipt", receipt, "--authority", narrative,
                "--layer", narrative, "--layer", directing, "--layer", contract,
            ).returncode)
            manifest = self._manifest(scripts, narrative, directing, contract, receipt)
            directing.write_text("导演稿（过门之后被改了一个字）\n", encoding="utf-8")
            result = self.run_tool(
                "seal", "--receipt", receipt, "--manifest", manifest,
                "--seal-dir", base / "seals", "--lock-dir", base / "locks", "--check",
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("WRITER_SEAL_LAYER_SHA_MISMATCH:directing_script", result.stderr + result.stdout)

    def test_seal_refuses_a_manifest_that_does_not_bind_this_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            scripts, narrative, directing, contract, receipt = self._bootstrap(base)
            self.assertEqual(0, self.run_tool(
                "finish", "--receipt", receipt, "--authority", narrative,
                "--layer", narrative, "--layer", directing, "--layer", contract,
            ).returncode)
            manifest = self._manifest(scripts, narrative, directing, contract, receipt)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["writer_provenance"]["receipt_sha256"] = "0" * 64
            manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result = self.run_tool(
                "seal", "--receipt", receipt, "--manifest", manifest,
                "--seal-dir", base / "seals", "--lock-dir", base / "locks", "--check",
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("WRITER_SEAL_RECEIPT_SHA_MISMATCH", result.stderr + result.stdout)

    def test_seal_refuses_while_the_write_lease_is_still_held(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            scripts, narrative, directing, contract, receipt = self._bootstrap(base)
            # No finish: the lease is still on disk and the receipt is still RUNNING.
            manifest = self._manifest(scripts, narrative, directing, contract, receipt)
            result = self.run_tool(
                "seal", "--receipt", receipt, "--manifest", manifest,
                "--seal-dir", base / "seals", "--lock-dir", base / "locks", "--check",
            )
            self.assertNotEqual(0, result.returncode)
            combined = result.stderr + result.stdout
            self.assertIn("WRITER_SEAL_RECEIPT_NOT_COMPLETED", combined)
            self.assertIn("WRITER_SEAL_LEASE_STILL_HELD", combined)

    def test_seal_treats_this_runs_own_unremoved_lease_as_a_warning_not_a_refusal(self):
        """charter line 65：finish 的 unlink 在某些挂载下抛 PermissionError，
        留下的是本次运行自己的锁，不是别人在写 —— 记 warning，不拒绝。"""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            scripts, narrative, directing, contract, receipt = self._bootstrap(base)
            lease = base / "locks" / f"{self.EPISODE}_V{self.VERSION}.writer.lock.json"
            preserved = json.loads(lease.read_text(encoding="utf-8"))
            self.assertEqual(0, self.run_tool(
                "finish", "--receipt", receipt, "--authority", narrative,
                "--layer", narrative, "--layer", directing, "--layer", contract,
            ).returncode)
            self.assertFalse(lease.exists())
            # Re-create it exactly as an unlink failure would have left it.
            lease.write_text(json.dumps(preserved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            manifest = self._manifest(scripts, narrative, directing, contract, receipt)
            result = self.run_tool(
                "seal", "--receipt", receipt, "--manifest", manifest,
                "--seal-dir", base / "seals", "--lock-dir", base / "locks", "--check",
            )
            self.assertEqual(0, result.returncode, result.stderr)
            verdict = json.loads(result.stdout)
            self.assertEqual("SEALED", verdict["status"])
            self.assertEqual([], verdict["failures"])
            self.assertTrue(any("ORPHAN_LEASE_OF_THIS_RUN" in w for w in verdict["warnings"]))

    def test_seal_still_refuses_a_lease_belonging_to_a_different_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            scripts, narrative, directing, contract, receipt = self._bootstrap(base)
            lease = base / "locks" / f"{self.EPISODE}_V{self.VERSION}.writer.lock.json"
            preserved = json.loads(lease.read_text(encoding="utf-8"))
            self.assertEqual(0, self.run_tool(
                "finish", "--receipt", receipt, "--authority", narrative,
                "--layer", narrative, "--layer", directing, "--layer", contract,
            ).returncode)
            preserved["writer_run_id"] = f"WRITER-{self.EPISODE}-V{self.VERSION}-SOMEONE-ELSE"
            lease.write_text(json.dumps(preserved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            manifest = self._manifest(scripts, narrative, directing, contract, receipt)
            result = self.run_tool(
                "seal", "--receipt", receipt, "--manifest", manifest,
                "--seal-dir", base / "seals", "--lock-dir", base / "locks", "--check",
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("WRITER_SEAL_LEASE_STILL_HELD", result.stderr + result.stdout)


class VersionFieldIsNonAuthoritativeTests(FourLayerSealTests):
    """SUPERVISOR_ORDERS seq=56 conditions[2]：manifest 的 $.version 已被 erratum
    CLAUDE-SUP-20260829-E49V5-E50V5-VERSION-FIELD-NON-AUTHORITATIVE 裁为非权威，
    seal 不得据此拒绝封缄（未注册判据阻断工位＝违铁律一），只能出 warning。"""

    ERRATUM = "CLAUDE-SUP-20260829-E49V5-E50V5-VERSION-FIELD-NON-AUTHORITATIVE"

    def _finished_with_manifest(self, base: Path, version_field):
        scripts, narrative, directing, contract, receipt = self._bootstrap(base)
        self.assertEqual(0, self.run_tool(
            "finish", "--receipt", receipt, "--authority", narrative,
            "--layer", narrative, "--layer", directing, "--layer", contract,
        ).returncode)
        manifest = self._manifest(scripts, narrative, directing, contract, receipt)
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["version"] = version_field
        manifest.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        # writer_provenance binds the receipt, not the manifest, so rewriting the
        # manifest's own version field cannot invalidate any other seal criterion.
        return manifest, receipt

    def test_seal_warns_instead_of_refusing_when_the_manifest_self_declares_the_wrong_version(self):
        """E49 v5 / E50 v5 shape: filename+receipt say 5, the manifest's bytes say 4."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            manifest, receipt = self._finished_with_manifest(base, self.VERSION - 1)
            checked = self.run_tool(
                "seal", "--receipt", receipt, "--manifest", manifest,
                "--seal-dir", base / "seals", "--lock-dir", base / "locks", "--check",
            )
            self.assertEqual(0, checked.returncode, checked.stderr)
            verdict = json.loads(checked.stdout)
            self.assertEqual("SEALED", verdict["status"])
            self.assertEqual([], verdict["failures"])
            warning = next(
                w for w in verdict["warnings"]
                if w.startswith("WRITER_SEAL_VERSION_FIELD_MISMATCH")
            )
            self.assertIn(self.ERRATUM, warning)
            self.assertIn("LINEAGE_KEY=", warning)

    def test_the_warning_survives_into_the_written_seal_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            manifest, receipt = self._finished_with_manifest(base, self.VERSION - 1)
            sealed = self.run_tool(
                "seal", "--receipt", receipt, "--manifest", manifest,
                "--seal-dir", base / "seals", "--lock-dir", base / "locks",
            )
            self.assertEqual(0, sealed.returncode, sealed.stderr)
            record = json.loads(
                (base / "seals" / f"{self.EPISODE}_V{self.VERSION}_FOUR_LAYER_SEAL.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual("SEALED", record["status"])
            self.assertTrue(any(
                self.ERRATUM in w for w in record["warnings"]
            ), record["warnings"])
            # the seal records the receipt's version, never the manifest's claim
            self.assertEqual(self.VERSION, record["version"])

    def test_string_and_integer_forms_of_the_same_version_do_not_warn(self):
        """CL2X-1291 ④ ruled "5" and 5 are one value; v-prefixed forms too."""
        for declared in (str(FourLayerSealTests.VERSION), f"v{FourLayerSealTests.VERSION}"):
            with self.subTest(declared=declared):
                with tempfile.TemporaryDirectory() as temporary:
                    base = Path(temporary)
                    manifest, receipt = self._finished_with_manifest(base, declared)
                    checked = self.run_tool(
                        "seal", "--receipt", receipt, "--manifest", manifest,
                        "--seal-dir", base / "seals", "--lock-dir", base / "locks", "--check",
                    )
                    self.assertEqual(0, checked.returncode, checked.stderr)
                    verdict = json.loads(checked.stdout)
                    self.assertEqual("SEALED", verdict["status"])
                    self.assertEqual([], [
                        w for w in verdict["warnings"]
                        if w.startswith("WRITER_SEAL_VERSION_FIELD_MISMATCH")
                    ])

    def test_episode_mismatch_is_still_a_refusal(self):
        """Only the version field was ruled non-authoritative — episode was not."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            scripts, narrative, directing, contract, receipt = self._bootstrap(base)
            self.assertEqual(0, self.run_tool(
                "finish", "--receipt", receipt, "--authority", narrative,
                "--layer", narrative, "--layer", directing, "--layer", contract,
            ).returncode)
            manifest = self._manifest(scripts, narrative, directing, contract, receipt)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["episode"] = "E99"
            manifest.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            result = self.run_tool(
                "seal", "--receipt", receipt, "--manifest", manifest,
                "--seal-dir", base / "seals", "--lock-dir", base / "locks", "--check",
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("WRITER_SEAL_EPISODE_MISMATCH", result.stderr + result.stdout)


class FinishLayerDeclarationPolicyTests(FourLayerSealTests):
    """SEQ56 c4 自决：--layer 不设必填，缺层时 warning 并写进 receipt 自身字节。"""

    def test_finish_without_layer_declaration_succeeds_but_records_the_omission(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            _, narrative, _, _, receipt = self._bootstrap(base)
            result = self.run_tool("finish", "--receipt", receipt, "--authority", narrative)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("WRITER_FINISH_NO_LAYER_DECLARATION", result.stderr)
            completed = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual("COMPLETED", completed["status"])
            self.assertIsNone(completed["layers_at_finish"])
            self.assertTrue(any(
                w.startswith("WRITER_FINISH_NO_LAYER_DECLARATION")
                for w in completed["finish_warnings"]
            ), completed["finish_warnings"])

    def test_a_complete_layer_declaration_records_no_warning(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            _, narrative, directing, contract, receipt = self._bootstrap(base)
            result = self.run_tool(
                "finish", "--receipt", receipt, "--authority", narrative,
                "--layer", narrative, "--layer", directing, "--layer", contract,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            completed = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertIsNone(completed["finish_warnings"])
            self.assertEqual(3, len(completed["layers_at_finish"]))


class WriterReceiptResolutionTests(FourLayerSealTests):
    """R432: the customary receipt filename is not always the authority.

    E51 v4's customary path holds an ABORTED receipt (seq=53 conditions[1]
    ordered a new path after a clean abort), while ~80 call sites in tools/
    still format that filename by hand.  Resolution must come from payload
    fields, and the seal must report divergence as a warning, never a refusal.
    """

    def _bootstrap_named(self, base: Path, receipt_name: str):
        scripts = base / "scripts"
        scripts.mkdir()
        receipts = base / "receipts"
        receipts.mkdir()
        narrative = scripts / f"{self.EPISODE}_NARRATIVE_CANONICAL_v{self.VERSION}.md"
        directing = scripts / f"{self.EPISODE}_DIRECTING_SCRIPT_v{self.VERSION}.md"
        contract = scripts / f"{self.EPISODE}_GENERATION_CONTRACT_v{self.VERSION}.json"
        narrative.write_text("正文\n", encoding="utf-8")
        directing.write_text("导演稿\n", encoding="utf-8")
        contract.write_text('{"shots": []}\n', encoding="utf-8")
        input_bundle = base / "input.json"
        rule = base / "rule.md"
        input_bundle.write_text("{}\n", encoding="utf-8")
        rule.write_text("rule\n", encoding="utf-8")
        receipt = receipts / receipt_name
        started = self.run_tool(
            "start",
            "--episode", self.EPISODE,
            "--version", self.VERSION,
            "--writer-run-id", f"WRITER-{self.EPISODE}-V{self.VERSION}-ATTEMPT2",
            "--agent-id", "qingshan-claude-writer-agent",
            "--provider", "anthropic-cowork",
            "--model-id", "claude-opus-5",
            "--session-or-task-id", "unit-test-receipt-resolution",
            "--input-bundle", input_bundle,
            "--rule", rule,
            "--receipt", receipt,
            "--lock-dir", base / "locks",
        )
        self.assertEqual(0, started.returncode, started.stderr)
        return scripts, receipts, narrative, directing, contract, receipt

    def _aborted_receipt(self, receipts: Path, name: str) -> Path:
        path = receipts / name
        path.write_text(json.dumps({
            "schema": "qingshan.canonical_writer_run_receipt.v1",
            "status": "ABORTED",
            "writer_run_id": f"WRITER-{self.EPISODE}-V{self.VERSION}-ATTEMPT1",
            "episode": self.EPISODE,
            "version": self.VERSION,
            "authority_output": None,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def test_resolver_picks_the_completed_receipt_not_the_customary_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            customary = f"{self.EPISODE}_V{self.VERSION}_WRITER_RUN_RECEIPT.json"
            scripts, receipts, narrative, directing, contract, receipt = self._bootstrap_named(
                base, f"{self.EPISODE}_V{self.VERSION}_WRITER_RUN_RECEIPT_ATTEMPT2.json"
            )
            self._aborted_receipt(receipts, customary)
            self.assertEqual(0, self.run_tool(
                "finish", "--receipt", receipt, "--authority", narrative,
                "--layer", narrative, "--layer", directing, "--layer", contract,
            ).returncode)

            verdict = resolve_receipt(receipts, self.EPISODE, self.VERSION)
            self.assertEqual("RESOLVED", verdict["status"])
            self.assertEqual(str(receipt.resolve()), verdict["authoritative_receipt"])
            self.assertTrue(verdict["customary_exists"])
            self.assertFalse(verdict["customary_is_authoritative"])
            self.assertEqual(2, len(verdict["candidates"]))

    def test_resolver_reports_when_no_receipt_carries_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            receipts = base / "receipts"
            receipts.mkdir()
            self._aborted_receipt(
                receipts, f"{self.EPISODE}_V{self.VERSION}_WRITER_RUN_RECEIPT.json"
            )
            verdict = resolve_receipt(receipts, self.EPISODE, self.VERSION)
            self.assertEqual("NO_AUTHORITATIVE_RECEIPT", verdict["status"])
            self.assertIsNone(verdict["authoritative_receipt"])

    def test_resolver_ignores_receipts_of_other_episodes_and_versions(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            scripts, receipts, narrative, directing, contract, receipt = self._bootstrap_named(
                base, f"{self.EPISODE}_V{self.VERSION}_WRITER_RUN_RECEIPT.json"
            )
            self.assertEqual(0, self.run_tool(
                "finish", "--receipt", receipt, "--authority", narrative,
                "--layer", narrative, "--layer", directing, "--layer", contract,
            ).returncode)
            stranger = receipts / "E11_V2_WRITER_RUN_RECEIPT.json"
            stranger.write_text(json.dumps({
                "schema": "qingshan.canonical_writer_run_receipt.v1",
                "status": "COMPLETED",
                "episode": "E11",
                "version": 2,
                "authority_output": {"sha256": "f" * 64},
            }, ensure_ascii=False) + "\n", encoding="utf-8")

            verdict = resolve_receipt(receipts, self.EPISODE, self.VERSION)
            self.assertEqual("RESOLVED", verdict["status"])
            self.assertEqual(str(receipt.resolve()), verdict["authoritative_receipt"])
            self.assertTrue(verdict["customary_is_authoritative"])
            self.assertEqual(1, len(verdict["candidates"]))

    def test_string_and_integer_versions_resolve_to_the_same_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            scripts, receipts, narrative, directing, contract, receipt = self._bootstrap_named(
                base, f"{self.EPISODE}_V{self.VERSION}_WRITER_RUN_RECEIPT.json"
            )
            self.assertEqual(0, self.run_tool(
                "finish", "--receipt", receipt, "--authority", narrative,
                "--layer", narrative, "--layer", directing, "--layer", contract,
            ).returncode)
            # R438 F-R438-02: asserting only `status` is what let the defect
            # through -- `v4` resolved, but answered the *customary* question
            # wrongly because `customary_name` interpolated the raw argument.
            # Every spelling must agree on every field a caller reads.
            baseline = resolve_receipt(receipts, self.EPISODE, self.VERSION)
            for version in (self.VERSION, str(self.VERSION), f"v{self.VERSION}",
                            f"V{self.VERSION}", f"0{self.VERSION}"):
                verdict = resolve_receipt(receipts, self.EPISODE, version)
                self.assertEqual("RESOLVED", verdict["status"], version)
                for field in ("authoritative_receipt", "customary_path",
                              "customary_exists", "customary_is_authoritative"):
                    self.assertEqual(baseline[field], verdict[field], (version, field))
                self.assertTrue(verdict["customary_is_authoritative"], version)

    def test_every_spelling_of_the_episode_resolves_to_the_same_receipt(self):
        """R437 F-R437-01: `--episode 51` reported NO_AUTHORITATIVE_RECEIPT."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            scripts, receipts, narrative, directing, contract, receipt = self._bootstrap_named(
                base, f"{self.EPISODE}_V{self.VERSION}_WRITER_RUN_RECEIPT.json"
            )
            self.assertEqual(0, self.run_tool(
                "finish", "--receipt", receipt, "--authority", narrative,
                "--layer", narrative, "--layer", directing, "--layer", contract,
            ).returncode)
            number = str(self.EPISODE).lstrip("Ee")
            baseline = resolve_receipt(receipts, self.EPISODE, self.VERSION)
            for episode in (self.EPISODE, number, f"e{number}", f"E{number}"):
                verdict = resolve_receipt(receipts, episode, self.VERSION)
                self.assertEqual("RESOLVED", verdict["status"], episode)
                self.assertEqual(
                    baseline["authoritative_receipt"], verdict["authoritative_receipt"], episode
                )
                self.assertTrue(verdict["customary_is_authoritative"], episode)

    def test_normalisation_never_invents_an_episode_or_version(self):
        """Un-parseable input is passed through, not guessed at."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            receipts = base / "receipts"
            receipts.mkdir()
            self._aborted_receipt(
                receipts, f"{self.EPISODE}_V{self.VERSION}_WRITER_RUN_RECEIPT.json"
            )
            verdict = resolve_receipt(receipts, "E41R", "draft")
            self.assertEqual("NO_AUTHORITATIVE_RECEIPT", verdict["status"])
            self.assertEqual("E41R", verdict["episode_normalized"])
            self.assertEqual("draft", verdict["version_normalized"])
            self.assertTrue(verdict["customary_path"].endswith(
                "E41R_Vdraft_WRITER_RUN_RECEIPT.json"
            ))

    def test_seal_warns_when_the_authority_is_not_at_the_customary_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            scripts, receipts, narrative, directing, contract, receipt = self._bootstrap_named(
                base, f"{self.EPISODE}_V{self.VERSION}_WRITER_RUN_RECEIPT_ATTEMPT2.json"
            )
            self._aborted_receipt(
                receipts, f"{self.EPISODE}_V{self.VERSION}_WRITER_RUN_RECEIPT.json"
            )
            self.assertEqual(0, self.run_tool(
                "finish", "--receipt", receipt, "--authority", narrative,
                "--layer", narrative, "--layer", directing, "--layer", contract,
            ).returncode)
            manifest = self._manifest(scripts, narrative, directing, contract, receipt)

            checked = self.run_tool(
                "seal", "--receipt", receipt, "--manifest", manifest,
                "--seal-dir", base / "seals", "--lock-dir", base / "locks", "--check",
            )
            self.assertEqual(0, checked.returncode, checked.stderr)
            verdict = json.loads(checked.stdout)
            self.assertEqual("SEALED", verdict["status"])
            self.assertEqual([], verdict["failures"])
            self.assertTrue(any(
                warning.startswith("WRITER_SEAL_AUTHORITY_RECEIPT_NOT_AT_CUSTOMARY_PATH")
                for warning in verdict["warnings"]
            ), verdict["warnings"])

    def test_seal_records_no_receipt_warning_when_the_customary_path_is_the_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            scripts, receipts, narrative, directing, contract, receipt = self._bootstrap_named(
                base, f"{self.EPISODE}_V{self.VERSION}_WRITER_RUN_RECEIPT.json"
            )
            self.assertEqual(0, self.run_tool(
                "finish", "--receipt", receipt, "--authority", narrative,
                "--layer", narrative, "--layer", directing, "--layer", contract,
            ).returncode)
            manifest = self._manifest(scripts, narrative, directing, contract, receipt)

            checked = self.run_tool(
                "seal", "--receipt", receipt, "--manifest", manifest,
                "--seal-dir", base / "seals", "--lock-dir", base / "locks", "--check",
            )
            self.assertEqual(0, checked.returncode, checked.stderr)
            verdict = json.loads(checked.stdout)
            self.assertEqual("SEALED", verdict["status"])
            # Scoped to this test's actual subject: the RECEIPT warning.
            # Asserting the whole list is empty coupled this test to every
            # unregistered criterion seal may ever report -- F-R543-01's
            # charter-key presence warning fires on this fixture because the
            # synthetic manifest has no `beat_disposition`, which is correct
            # behaviour for that check and unrelated to receipt resolution.
            self.assertEqual(
                [], [w for w in verdict["warnings"] if "RECEIPT" in w]
            )

    def test_the_receipt_warning_never_becomes_a_refusal(self):
        """铁律一: an unregistered criterion must not block a workstation."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            scripts, receipts, narrative, directing, contract, receipt = self._bootstrap_named(
                base, f"{self.EPISODE}_V{self.VERSION}_WRITER_RUN_RECEIPT_ATTEMPT2.json"
            )
            self._aborted_receipt(
                receipts, f"{self.EPISODE}_V{self.VERSION}_WRITER_RUN_RECEIPT.json"
            )
            self.assertEqual(0, self.run_tool(
                "finish", "--receipt", receipt, "--authority", narrative,
                "--layer", narrative, "--layer", directing, "--layer", contract,
            ).returncode)
            manifest = self._manifest(scripts, narrative, directing, contract, receipt)

            sealed = self.run_tool(
                "seal", "--receipt", receipt, "--manifest", manifest,
                "--seal-dir", base / "seals", "--lock-dir", base / "locks",
            )
            self.assertEqual(0, sealed.returncode, sealed.stderr)
            seal_file = base / "seals" / f"{self.EPISODE}_V{self.VERSION}_FOUR_LAYER_SEAL.json"
            record = json.loads(seal_file.read_text(encoding="utf-8"))
            self.assertEqual("SEALED", record["status"])
            self.assertTrue(any(
                "NOT_AT_CUSTOMARY_PATH" in warning for warning in record["warnings"]
            ), record["warnings"])


class ManifestSelfDeclarationTests(FourLayerSealTests):
    """R504：封缄件第 4 层补填 declared_sha256（监制连续十集 P2「请封印工具补填」）。

    F-R491-04 给出了它的实际代价：manifest 内嵌构建时间戳，封缄之后重跑构建器就会
    改变字节，而 `seal --check` 仍报 SEALED——因为 manifest 层没有任何申报值可比。
    写时由封缄件申报自己封的那份 manifest 的 SHA，查时读回来比对。
    **漂移只出 warning，永不拒绝封缄**：漂移检测不是注册判据，未注册判据不得阻断
    工位（铁律一），与版本字段、回执路径两条 warning 同一处置。
    """

    EPISODE = "E91"
    VERSION = 9

    def _sealed(self, base: Path):
        scripts, narrative, directing, contract, receipt = self._bootstrap(base)
        self.assertEqual(0, self.run_tool(
            "finish", "--receipt", receipt, "--authority", narrative,
            "--layer", narrative, "--layer", directing, "--layer", contract,
        ).returncode)
        manifest = self._manifest(scripts, narrative, directing, contract, receipt)
        sealed = self.run_tool(
            "seal", "--receipt", receipt, "--manifest", manifest,
            "--seal-dir", base / "seals", "--lock-dir", base / "locks",
        )
        self.assertEqual(0, sealed.returncode, sealed.stderr)
        seal_file = base / "seals" / f"{self.EPISODE}_V{self.VERSION}_FOUR_LAYER_SEAL.json"
        return manifest, receipt, seal_file

    def _manifest_row(self, payload: dict) -> dict:
        return next(row for row in payload["layers"] if row["layer"] == "manifest")

    def test_the_seal_declares_the_manifest_sha_it_sealed(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            manifest, _, seal_file = self._sealed(base)
            row = self._manifest_row(json.loads(seal_file.read_text(encoding="utf-8")))
            self.assertEqual(self._sha(manifest), row["declared_sha256"])
            self.assertEqual(row["declared_sha256"], row["actual_sha256"])

    def test_manifest_drift_after_sealing_is_reported_as_a_warning_not_a_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            manifest, receipt, seal_file = self._sealed(base)
            before = self._sha(manifest)
            # F-R491-04 的形态：重跑构建器，只有时间戳类字段变，内容零差异。
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["built_at"] = "2026-09-11T16:40:00Z"
            manifest.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            self.assertNotEqual(before, self._sha(manifest))

            checked = self.run_tool(
                "seal", "--receipt", receipt, "--manifest", manifest,
                "--seal-dir", base / "seals", "--lock-dir", base / "locks", "--check",
            )
            self.assertEqual(0, checked.returncode, checked.stderr)
            verdict = json.loads(checked.stdout)
            self.assertEqual("SEALED", verdict["status"])
            self.assertEqual([], verdict["failures"])
            self.assertTrue(any(
                warning.startswith("WRITER_SEAL_MANIFEST_DRIFT_SINCE_SEAL:")
                for warning in verdict["warnings"]
            ), verdict["warnings"])
            row = self._manifest_row(verdict)
            self.assertEqual(before, row["declared_sha256"])
            self.assertEqual(self._sha(manifest), row["actual_sha256"])
            self.assertTrue(seal_file.is_file(), "--check 不得改写封缄件")
            self.assertEqual(
                before,
                self._manifest_row(json.loads(seal_file.read_text(encoding="utf-8")))["declared_sha256"],
            )

    def test_an_unchanged_manifest_raises_no_drift_warning(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            manifest, receipt, _ = self._sealed(base)
            checked = self.run_tool(
                "seal", "--receipt", receipt, "--manifest", manifest,
                "--seal-dir", base / "seals", "--lock-dir", base / "locks", "--check",
            )
            self.assertEqual(0, checked.returncode, checked.stderr)
            verdict = json.loads(checked.stdout)
            self.assertEqual("SEALED", verdict["status"])
            self.assertFalse(any(
                "MANIFEST_DRIFT" in warning for warning in verdict["warnings"]
            ), verdict["warnings"])

    def test_a_pre_existing_seal_that_declared_nothing_stays_silent(self):
        """E65–E96 十集旧封缄件 declared_sha256=null：无申报即无可比，不得凭空报漂移。"""

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            manifest, receipt, seal_file = self._sealed(base)
            legacy = json.loads(seal_file.read_text(encoding="utf-8"))
            self._manifest_row(legacy)["declared_sha256"] = None
            seal_file.write_text(
                json.dumps(legacy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["built_at"] = "2026-09-11T16:41:00Z"
            manifest.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

            checked = self.run_tool(
                "seal", "--receipt", receipt, "--manifest", manifest,
                "--seal-dir", base / "seals", "--lock-dir", base / "locks", "--check",
            )
            self.assertEqual(0, checked.returncode, checked.stderr)
            verdict = json.loads(checked.stdout)
            self.assertEqual("SEALED", verdict["status"])
            self.assertFalse(any(
                "MANIFEST_DRIFT" in warning for warning in verdict["warnings"]
            ), verdict["warnings"])
            self.assertIsNone(self._manifest_row(verdict)["declared_sha256"])

    def test_an_unreadable_seal_never_becomes_a_refusal(self):
        """铁律一：封缄件读不动是闭嘴的理由，不是阻断工位的理由。"""

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            manifest, receipt, seal_file = self._sealed(base)
            seal_file.write_text("{ 这不是 JSON", encoding="utf-8")
            checked = self.run_tool(
                "seal", "--receipt", receipt, "--manifest", manifest,
                "--seal-dir", base / "seals", "--lock-dir", base / "locks", "--check",
            )
            self.assertEqual(0, checked.returncode, checked.stderr)
            verdict = json.loads(checked.stdout)
            self.assertEqual("SEALED", verdict["status"])
            self.assertEqual([], verdict["failures"])


class LeaseReleaseFallbackTests(unittest.TestCase):
    """F-R523-01：unlink 被挂载拒绝时，租约释放必须自救而不是把终态运行摔在地上。

    背景实据：R430 扫出的 72 个残锁、以及 R522 在 PROGRESS.json.bak_* 上再次撞到的
    PermissionError（同目录 rename/write 均可 ⇒ 限制只在 unlink 这一个系统调用）。
    宪章原本只有一条**人工**兜底（改名 *.released）；本组测试把它钉在工具里。
    """

    def _lease(self, base: Path, run_id: str = "WRITER-R523-TEST") -> Path:
        lease = base / "E41_V5.writer.lock.json"
        lease.write_text(
            json.dumps({"writer_run_id": run_id}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return lease

    def test_clean_unlink_is_recorded_as_unlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            lease = self._lease(base)
            record = dispatcher.release_lease(lease, "WRITER-R523-TEST", "finish")
            self.assertEqual("UNLINK", record["method"])
            self.assertTrue(record["released"])
            self.assertFalse(lease.exists())

    def test_permission_error_falls_back_to_rename_and_frees_the_customary_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            lease = self._lease(base)
            with _unlink_refused():
                record = dispatcher.release_lease(lease, "WRITER-R523-TEST", "finish")
            self.assertEqual("RENAMED_UNLINK_REFUSED", record["method"])
            self.assertTrue(record["released"])
            # 关键判据不是「文件没了」，是**俗成路径腾空了**：后续 start 能重新取锁，
            # seal 也不会再把它读成「别人正在写」。
            self.assertFalse(lease.exists())
            released = Path(record["released_path"])
            self.assertTrue(released.is_file())
            self.assertTrue(released.name.endswith(".released_by_WRITER-R523-TEST_finish"))
            self.assertIn("PermissionError", record["unlink_error"])

    def test_both_paths_failing_is_reported_never_raised(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            lease = self._lease(base)
            with _unlink_refused(), _rename_refused():
                record = dispatcher.release_lease(lease, "WRITER-R523-TEST", "abort")
            self.assertEqual("FAILED", record["method"])
            self.assertFalse(record["released"])
            self.assertTrue(lease.is_file())  # 零字节丢失：失败就是原样留着
            self.assertIn("WRITER_LEASE_RESIDUE_NOT_RELEASED", record["note"])

    def test_missing_or_empty_lease_path_never_touches_the_working_directory(self):
        """`Path("")` 规范化成 `Path(".")`；旧码会对 CWD 调 unlink。"""

        record = dispatcher.release_lease(Path(""), "WRITER-R523-TEST", "abort")
        self.assertEqual("ALREADY_ABSENT", record["method"])
        self.assertTrue(record["released"])

    def test_finish_survives_a_refused_unlink_and_records_it_in_the_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            authority = base / "E41_NARRATIVE_CANONICAL_v5.md"
            authority.write_text("story\n", encoding="utf-8")
            lease = self._lease(base)
            receipt = base / "receipt.json"
            receipt.write_text(
                json.dumps(
                    {
                        "status": "RUNNING",
                        "writer_run_id": "WRITER-R523-TEST",
                        "write_lease": str(lease),
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(receipt=receipt, authority=authority, layer=[])
            with _unlink_refused():
                self.assertEqual(0, dispatcher.finish(args))
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            # 终态先落盘、释放在后：释放方式变了，COMPLETED 不受影响。
            self.assertEqual("COMPLETED", payload["status"])
            self.assertEqual("RENAMED_UNLINK_REFUSED", payload["lease_release"]["method"])
            self.assertTrue(payload["lease_release"]["released"])
            self.assertFalse(lease.exists())


@contextlib.contextmanager
def _unlink_refused():
    original = Path.unlink

    def refuse(self, *args, **kwargs):
        raise PermissionError(1, "Operation not permitted")

    Path.unlink = refuse
    try:
        yield
    finally:
        Path.unlink = original


@contextlib.contextmanager
def _rename_refused():
    original = Path.rename

    def refuse(self, *args, **kwargs):
        raise PermissionError(1, "Operation not permitted")

    Path.rename = refuse
    try:
        yield
    finally:
        Path.rename = original


class RollbackPathsAlsoSurviveRefusedUnlinkTests(unittest.TestCase):
    """F-R524-01：F-R523-01 只覆盖了 finish/abort 的**成功**路径；两条**回滚**路径
    仍是裸 `unlink`，在同一个挂载上有同一个病，且后果更重。

    实撞（R524 探针，非推演）：给 `acquire_lock` 一个 json 序列化不了的 payload，
    调用方拿到的不是真错（TypeError），而是回滚自己抛的 PermissionError——真错被降
    级成 `__context__`；与此同时半写的租约**原样留在俗成路径上**，此后该集该版本的
    每一次 `start` 都会被它挡住。这正是 R430 手扫 72 个残锁的形状，只是发生在取锁端。

    判据同 F-R523-01：不是「文件没了」，是**原始异常原样到达调用方**且**俗成路径腾空**。
    """

    def test_acquire_rollback_preserves_the_real_error_instead_of_the_unlink_error(self):
        class Unserialisable:
            pass

        with tempfile.TemporaryDirectory() as temporary:
            lease = Path(temporary) / "E99_V1.writer.lock.json"
            with _unlink_refused():
                with self.assertRaises(TypeError):  # 真错，不是 PermissionError
                    dispatcher.acquire_lock(
                        lease,
                        {"writer_run_id": "WRITER-R524-TEST", "bad": Unserialisable()},
                    )

    def test_acquire_rollback_frees_the_customary_path_so_a_later_start_can_acquire(self):
        class Unserialisable:
            pass

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            lease = base / "E99_V1.writer.lock.json"
            with _unlink_refused():
                with contextlib.suppress(TypeError):
                    dispatcher.acquire_lock(
                        lease,
                        {"writer_run_id": "WRITER-R524-TEST", "bad": Unserialisable()},
                    )
            self.assertFalse(lease.exists(), "俗成路径必须腾空，否则永久挡住该集该版本")
            residue = list(base.glob("*.released_by_WRITER-R524-TEST_acquire_rollback"))
            self.assertEqual(1, len(residue), "改名兜底必须留下可追溯的已释放件")
            # 腾空的真正意义：紧接着重新取锁必须成功。
            dispatcher.acquire_lock(lease, {"writer_run_id": "WRITER-R524-TEST-2"})
            self.assertTrue(lease.is_file())

    def test_acquire_rollback_without_a_run_id_still_releases(self):
        """payload 里没有 writer_run_id 时不得因取不到名字而放弃释放。"""

        class Unserialisable:
            pass

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            lease = base / "E99_V1.writer.lock.json"
            with _unlink_refused():
                with contextlib.suppress(TypeError):
                    dispatcher.acquire_lock(lease, {"bad": Unserialisable()})
            self.assertFalse(lease.exists())
            self.assertEqual(1, len(list(base.glob("*.released_by_unknown_acquire_rollback"))))

    def test_start_rollback_preserves_the_real_error_and_leaves_no_held_lease(self):
        """start 写 RUNNING receipt 失败时：真错到达调用方，且不留「有锁无 receipt」的残局。

        「有锁无 receipt」是最坏的残留形态——seal 会把它读成「别人正在写」，而盘上
        没有任何 receipt 能解释这把锁是谁的。
        """
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            input_bundle = base / "input.json"
            rule = base / "rule.md"
            input_bundle.write_text("{}\n", encoding="utf-8")
            rule.write_text("rule\n", encoding="utf-8")
            args = argparse.Namespace(
                episode="E99",
                version="1",
                writer_run_id="WRITER-E99-V1-R524-TEST",
                agent_id="qingshan-claude-writer-agent",
                provider="anthropic-cowork",
                model_id="claude-opus-5",
                session_or_task_id="session-r524-test",
                input_bundle=input_bundle,
                rule=[rule],
                receipt=base / "receipt.json",
                lock_dir=base / "locks",
            )
            original = dispatcher.atomic_json

            def explode(*_args, **_kwargs):
                raise RuntimeError("RECEIPT_WRITE_FAILED")

            dispatcher.atomic_json = explode
            try:
                with _unlink_refused():
                    with self.assertRaises(RuntimeError):  # 真错，不是 PermissionError
                        dispatcher.start(args)
            finally:
                dispatcher.atomic_json = original

            locks = base / "locks"
            held = [p for p in locks.glob("E99_V1.writer.lock.json")]
            self.assertEqual([], held, "不得留下有锁无 receipt 的残局")
            self.assertEqual(
                1,
                len(list(locks.glob("*.released_by_WRITER-E99-V1-R524-TEST_start_rollback"))),
            )

    def test_rollback_release_is_never_itself_a_new_failure_mode(self):
        """两条兜底全败时，回滚只记录不再抛——调用方仍须看见**原始**异常。"""

        class Unserialisable:
            pass

        with tempfile.TemporaryDirectory() as temporary:
            lease = Path(temporary) / "E99_V1.writer.lock.json"
            with _unlink_refused(), _rename_refused():
                with self.assertRaises(TypeError):
                    dispatcher.acquire_lock(
                        lease,
                        {"writer_run_id": "WRITER-R524-TEST", "bad": Unserialisable()},
                    )
            self.assertTrue(lease.is_file(), "释放失败就原样留着：零字节丢失")


class AtomicJsonLeavesNoPermanentResidueTests(unittest.TestCase):
    """F-R526-01：`atomic_json` 的临时件只带 pid，且失败时零回滚 —— 合起来是**永久砖死**。

    与 F-R525-01 同族但落在写手**自己的权威链**上：`atomic_json` 写的是 receipt 与 seal，
    一旦某个 receipt 路径被残留临时件占住，该集的 start/finish/abort/seal 全部打不开。

    实测（非推理）：
      ① 本沙盒给新 `python3` 的 pid 是 4,5,…,13 这样的小号顺序值 ⇒ **跨轮 pid 复用近乎必然**；
      ② 残留件存在时连撞三次 `open("x")`，三次全 FileExistsError；本挂载 unlink 被拒 ⇒ 无人能清；
      ③ 序列化中途抛 TypeError 时，旧实现把临时件永久留在盘上 —— 正是 ① 的上膛动作。

    判据不是「临时件没了」，是**下一次写还能成功**，且活件任何时候都不是半截。
    """

    def _payload_that_fails_to_serialise(self):
        class Unserialisable:
            pass

        return {"ok": 1, "bad": Unserialisable()}

    def test_successful_write_leaves_no_temporary_behind(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / "E97_V1.writer.receipt.json"
            dispatcher.atomic_json(target, {"a": 1})
            self.assertEqual({"a": 1}, json.loads(target.read_text(encoding="utf-8")))
            self.assertEqual([], list(base.glob("*.tmp")), "成功路径不得留临时件")

    def test_failed_serialisation_rolls_the_temporary_back(self):
        """旧实现在这里留下永久残留；回滚后目录必须干净。"""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / "E97_V1.writer.receipt.json"
            with self.assertRaises(TypeError):
                dispatcher.atomic_json(target, self._payload_that_fails_to_serialise())
            self.assertEqual([], list(base.glob("*.tmp")))
            self.assertFalse(target.exists(), "失败不得凭空造出活件")

    def test_a_stale_temporary_can_never_brick_a_later_write(self):
        """旧实现的核心病灶：同 pid 的残留件让此后每一次写都 FileExistsError，且无人能清。"""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / "E97_V1.writer.receipt.json"
            dispatcher.atomic_json(target, {"a": 1})
            # 伪造一份「上一轮同 pid 崩掉」留下的半截临时件。
            stale = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            stale.write_text('{"half', encoding="utf-8")
            for expected in (2, 3, 4):
                dispatcher.atomic_json(target, {"a": expected})
                self.assertEqual(
                    {"a": expected}, json.loads(target.read_text(encoding="utf-8"))
                )
            self.assertTrue(stale.is_file(), "残留件保留作证，但不得挡路")

    def test_rollback_never_masks_the_original_exception(self):
        """两条兜底全败时也只能静默 —— 调用方须看见 TypeError，不是 PermissionError。"""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / "E97_V1.writer.receipt.json"
            with _unlink_refused(), _rename_refused():
                with self.assertRaises(TypeError):
                    dispatcher.atomic_json(
                        target, self._payload_that_fails_to_serialise()
                    )

    def test_refused_unlink_still_frees_the_way_by_renaming(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / "E97_V1.writer.receipt.json"
            with _unlink_refused():
                with self.assertRaises(TypeError):
                    dispatcher.atomic_json(
                        target, self._payload_that_fails_to_serialise()
                    )
            self.assertEqual([], list(base.glob("*.tmp")), "改名兜底须让开 .tmp 名字")
            self.assertEqual(1, len(list(base.glob("*.tmp.discarded"))))

    def test_live_bytes_are_never_half_written(self):
        """`os.replace` 收尾的不变量：活件要么全旧、要么全新。"""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / "E97_V1.writer.receipt.json"
            dispatcher.atomic_json(target, {"a": "old"})
            with self.assertRaises(TypeError):
                dispatcher.atomic_json(target, self._payload_that_fails_to_serialise())
            self.assertEqual(
                {"a": "old"},
                json.loads(target.read_text(encoding="utf-8")),
                "写失败时活件必须是**完整的旧内容**",
            )

    def test_two_concurrent_writers_do_not_collide_on_the_temporary_name(self):
        """同 pid 的两次交错写（旧实现必撞名）现在各自有独立临时件。"""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            names = set()
            original = Path.open

            def spy(self, *args, **kwargs):
                if self.name.endswith(".tmp"):
                    names.add(self.name)
                return original(self, *args, **kwargs)

            Path.open = spy
            try:
                for index in range(5):
                    dispatcher.atomic_json(base / "E97_V1.writer.receipt.json", {"a": index})
            finally:
                Path.open = original
            self.assertEqual(5, len(names), f"每次写须有独立临时件名，实得 {names}")


if __name__ == "__main__":
    unittest.main()
