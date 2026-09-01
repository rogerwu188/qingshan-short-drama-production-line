import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/canonical_writer_dispatcher.py"
sys.path.insert(0, str(ROOT / "tools"))

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
            self.assertEqual([], verdict["warnings"])

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


if __name__ == "__main__":
    unittest.main()
