import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import storyclaw_release_validation as validation
from tools import submit_giggle_video_manifest_v2 as video_submitter


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StoryClawReleaseValidationTests(unittest.TestCase):
    def test_stable_promotion_reclassifies_under_cas_and_limits_registry_zip(self):
        workflow = (
            Path(__file__).resolve().parents[2]
            / ".github/workflows/storyclaw-stable-promote.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("concurrency:\n  group: storyclaw-stable-promotion", workflow)
        self.assertIn(
            "python3 /tmp/storyclaw-policy-base/tools/storyclaw_upgrade_classifier.py",
            workflow,
        )
        self.assertIn("classification.get('update_class') != update_class", workflow)
        self.assertIn(
            "initial stable promotion requires a TalentHub package", workflow
        )
        self.assertIn("host != 'storyclaw.com'", workflow)
        self.assertIn("not host.endswith('.storyclaw.com')", workflow)
        self.assertIn("len(entries) > 2048", workflow)
        self.assertIn("sum(entry.file_size for entry in entries)", workflow)

    def _private_runtime(self, temporary: str):
        runtime = Path(temporary) / "runtime"
        runtime.mkdir()
        engine = Path(temporary) / "engine"
        engine.mkdir()
        workspace = runtime / "runtime/storyclaw_storage/workflow/nalu"
        transactions = runtime / "runtime/storyclaw_storage/workflow/tasks"
        workspace.mkdir(parents=True)
        transactions.mkdir(parents=True)
        config = {
            "schema": "qingshan.pipeline.config.v1",
            "project": {"id": "project-a"},
            "authorization": {"line_owner_id": "owner-a"},
            "storyclaw": {
                "series_scope_id": "scope-a",
                "storage": {
                    "engine_root": str(engine),
                    "workspace_mount_target": str(engine / "workflow/nalu"),
                    "workspace_backing_path": str(workspace),
                    "transactions_mount_target": str(engine / "workflow/tasks"),
                    "transactions_backing_path": str(transactions),
                },
            },
        }
        _write_json(runtime / "qingshan.json", config)
        return runtime, engine, workspace, transactions, config, validation.PrivatePaths(runtime, config)

    def test_private_paths_reject_escape_and_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _engine, _workspace, _transactions, _config, guard = \
                self._private_runtime(temporary)
            outside = Path(temporary) / "outside.json"
            outside.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(validation.ValidationBlocked, "ESCAPES"):
                guard.file(outside, "OUTSIDE")
            target = runtime / "real.json"
            target.write_text("{}\n", encoding="utf-8")
            link = runtime / "linked.json"
            os.symlink(target, link)
            with self.assertRaisesRegex(validation.ValidationBlocked, "SYMLINK"):
                guard.file(link, "LINKED")

    def test_verified_archive_install_binds_bootstrap_package_and_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime, engine, _workspace, _transactions, _config, guard = \
                self._private_runtime(temporary)
            commit = "a" * 40
            _write_json(engine / "RELEASE_MANIFEST.json", {
                "schema": "qingshan.storyclaw.release.v1",
                "release_tag": "v1",
                "git_commit": commit,
                "private_runtime_included": False,
                "credentials_included": False,
            })
            archive = Path(temporary) / "project/bootstrap-cache/release.tar.gz"
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b"verified archive")
            archive_sha = _sha(archive)
            package_path = Path(temporary) / (
                "installed-agent/skills/qingshan-nalu/RELEASE_MANIFEST.json"
            )
            package = {
                "schema": "qingshan.storyclaw.talenthub.release.v1",
                "agent_id": "ai-drama-factory",
                "skill": "qingshan-nalu",
                "release_tag": "v1",
                "release_sequence": 1,
                "git_commit": commit,
                "origin_tag_commit": commit,
                "source_archive_size_bytes": archive.stat().st_size,
                "source_archive_sha256": archive_sha,
                "validation_receipt_status": "PASS",
                "public_runtime_only": True,
                "private_validation_contents_included": False,
            }
            _write_json(package_path, package)
            package_sha = _sha(package_path)
            engine_link = Path(temporary) / "project/engine/current"
            engine_link.parent.mkdir(parents=True)
            os.symlink(engine, engine_link)
            install_path = _write_json(runtime / "runtime/receipts/install.json", {
                "schema": "storyclaw.nalu.host_install_receipt.v1",
                "status": "PASS",
                "isolation_mode": "PER_PROJECT_VERIFIED_ARCHIVE_VIEW",
                "engine": {
                    "root": str(engine), "head_commit": commit,
                    "checkout_kind": "VERIFIED_RELEASE_ARCHIVE",
                },
                "base_engine": {
                    "checkout_kind": "PACKAGE_VERIFIED_RELEASE_ARCHIVE",
                    "source_archive_sha256": archive_sha,
                },
                "project_engine_link": {
                    "path": str(engine_link), "target": str(engine),
                },
                "verification": {"status": "PASS", "commit": commit},
                "release_baseline": {
                    "status": "PASS",
                    "talenthub_release_manifest_sha256": package_sha,
                },
                "wiring": [
                    {
                        "name": name,
                        "same_storage_object": True,
                        "storage_probe": {
                            "write": "PASS", "fsync": "PASS",
                            "flock_nonblocking": "PASS",
                        },
                    }
                    for name in ("episode_workspace", "transaction_store")
                ],
            })
            bootstrap_path = _write_json(
                runtime / "runtime/receipts/storyclaw_bootstrap/bootstrap.json",
                {
                    "schema": "storyclaw.nalu.skill_bootstrap.v1",
                    "status": "PASS",
                    "release_tag": "v1",
                    "git_commit": commit,
                    "source_archive": str(archive),
                    "source_archive_size_bytes": archive.stat().st_size,
                    "source_archive_sha256": archive_sha,
                    "talenthub_release_manifest": str(package_path),
                    "private_runtime_root": str(runtime.resolve()),
                    "project_engine_link": str(engine_link),
                    "project_engine": str(engine.resolve()),
                    "provider_posts": 0,
                },
            )
            required = (
                "engine_root", "nalu_pipeline", "nalu_paths", "runtime_persistent",
                "storage_contract", "engine_code_read_only", "workspace_store",
                "transaction_store", "writer_layers_store", "portable_media",
                "portable_audio_provider", "portable_renderer",
                "stable_release_signature_verifier", "model", "policy_profile",
                "series_scope", "voice_registry",
            )
            checks = {name: {"status": "PASS"} for name in required}
            checks["model"]["selected"] = "storyclaw/gpt-6-astra"
            for name in ("workspace_store", "transaction_store", "writer_layers_store"):
                checks[name]["flock"] = True
            checks["paid_lock"] = {
                "status": "PASS", "paid_requests_enabled": False,
                "api_key_present": False,
            }
            preflight_path = _write_json(runtime / "runtime/receipts/preflight.json", {
                "schema": "storyclaw.nalu.preflight.v1",
                "status": "PASS",
                "engine_commit": commit,
                "engine_root": str(engine.resolve()),
                "private_runtime_root": str(runtime.resolve()),
                "project_id": "project-a",
                "series_scope_id": "scope-a",
                "checks": checks,
            })
            inputs = {"evidence": {
                "install_receipt": str(install_path),
                "preflight": str(preflight_path),
                "bootstrap_receipt": str(bootstrap_path),
            }}
            result = validation._validate_install_preflight(
                inputs, guard, commit, "project-a", "scope-a", engine
            )
            self.assertEqual(result["isolation_mode"], "PER_PROJECT_VERIFIED_ARCHIVE_VIEW")
            self.assertEqual(result["source_archive_sha256"], archive_sha)
            self.assertEqual(result["talenthub_release_manifest_sha256"], package_sha)
            self.assertEqual(
                validation._git_acceptance(engine, commit)["remote_checkout_kind"],
                "VERIFIED_RELEASE_ARCHIVE",
            )

            archive.write_bytes(b"tampered")
            with self.assertRaisesRegex(validation.ValidationBlocked, "ARCHIVE_BYTES_MISMATCH"):
                validation._validate_install_preflight(
                    inputs, guard, commit, "project-a", "scope-a", engine
                )

    def test_s5_dry_run_requires_exact_context_and_zero_provider_route(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _engine, _workspace, _transactions, _config, guard = \
                self._private_runtime(temporary)
            receipt_path = _write_json(runtime / "s5-dry.json", {
                "schema": "storyclaw.nalu.run.v1",
                "release_commit": "a" * 40,
                "project_id": "project-a",
                "series_scope_id": "scope-a",
                "episode": "E01",
                "policy_profile": "CURRENT_PORTABLE",
                "model": "storyclaw/gpt-6-astra",
                "model_evidence": {"status": "PASS"},
                "singleflight_acquired": True,
                "from_stage": "S5",
                "until_stage": "S5",
                "target_stage": "S5",
                "dry_run": True,
                "provider_posts_allowed": False,
                "paid_posts": 0,
                "exit_code": 0,
                "paid_lock_evidence": {"provider_key_present": False},
            })
            inputs = {"evidence": {"s5_dry_run_receipt": str(receipt_path)}}
            result = validation._validate_s5_dry(
                inputs, guard, "a" * 40, "project-a", "scope-a", "E01"
            )
            self.assertEqual(result["paid_posts"], 0)
            tampered = json.loads(receipt_path.read_text())
            tampered["paid_posts"] = 1
            tampered["status"] = "PASS"
            _write_json(receipt_path, tampered)
            with self.assertRaisesRegex(validation.ValidationBlocked, "PAID_POSTS"):
                validation._validate_s5_dry(
                    inputs, guard, "a" * 40, "project-a", "scope-a", "E01"
                )

    def _video_transaction_fixture(self, temporary: str):
        runtime, _engine, workspace, transactions, config, guard = \
            self._private_runtime(temporary)
        episode_root = workspace / "E01"
        reference = episode_root / "assets/reference.png"
        reference.parent.mkdir(parents=True)
        reference.write_bytes(b"reference")
        source = _write_json(runtime / "runtime/orders/source.json", {
            "schema": "qingshan.line_owner_order_source_receipt.v1",
            "status": "CONFIRMED", "order_seq": 1, "order_id": "order-a",
            "issued_by": "owner-a", "verbatim": "authorize paid trial",
            "recorded_at_utc": "2026-09-20T00:00:00Z",
        })
        orders_path = _write_json(runtime / "runtime/orders/SUPERVISOR_ORDERS.json", {
            "_schema": "supervisor_orders_v1", "latest_order_seq": 1,
            "orders": [],
        })
        order = {
            "id": "order-a", "seq": 1, "issued_by": "owner-a",
            "orders_path": str(orders_path), "orders_sha256": _sha(orders_path),
            "source_receipt": {"path": str(source), "sha256": _sha(source)},
        }
        tasks = []
        for unit in ("UNIT-1", "UNIT-2"):
            prompt = episode_root / "prompts" / f"{unit}.txt"
            prompt.parent.mkdir(parents=True, exist_ok=True)
            prompt.write_text(f"prompt for {unit}\n", encoding="utf-8")
            tasks.append({
                "task_key": unit,
                "episode": "E01",
                "prompt_file": str(prompt),
                "prompt_sha256": _sha(prompt),
                "reference_images": [str(reference)],
                "reference_sha256": [_sha(reference)],
                "model": "seedance-2.0-pro",
                "duration_seconds": 4,
                "aspect_ratio": "9:16",
                "resolution": "720p",
                "status": "READY_TO_SUBMIT",
                "provider_post_allowed": True,
                "maximum_new_submissions": 1,
                "authorization_ref": "order-a",
            })
        _write_json(
            episode_root / "preproduction/E01_VIDEO_TRANSACTION_MANIFEST_V1.json",
            {
                "schema": "qingshan.giggle_video_transaction_manifest.v1",
                "episode": "E01",
                "authorization_ref": "order-a",
                "provider_post_allowed": True,
                "paid_authorization": {
                    "order_seq": 1, "order_id": "order-a",
                    "issued_by": "owner-a", "orders_file": str(orders_path),
                    "orders_file_sha256": _sha(orders_path),
                    "source_receipt": {"path": str(source), "sha256": _sha(source)},
                    "episode": "E01",
                },
                "tasks": tasks,
            },
        )
        transaction_root = transactions / "giggle_video_submit_transactions/E01"
        paths = []
        for index, task in enumerate(tasks):
            paths.append(_write_json(transaction_root / f"{task['task_key']}.json", {
                "schema": "qingshan.giggle_video_submit_transaction.v1",
                "task_key": task["task_key"],
                "task_id": f"provider-{index}",
                "state": "SUBMITTED_TASK_ID_BOUND",
                "submission_fingerprint": video_submitter.task_fingerprint(task),
                "prompt_sha256": task["prompt_sha256"],
                "reference_sha256": task["reference_sha256"],
            }))
        return runtime, config, guard, paths, reference, order

    def test_transactions_recompute_manifest_fingerprints_and_reject_duplicates(self):
        with tempfile.TemporaryDirectory() as temporary:
            _runtime, config, guard, paths, _reference, order = \
                self._video_transaction_fixture(temporary)
            result, task_ids = validation._validate_transactions(
                guard, config, "E01", ["UNIT-1", "UNIT-2"], order,
            )
            self.assertEqual(result["video_unit_ids"], ["UNIT-1", "UNIT-2"])
            self.assertEqual(task_ids, {"provider-0", "provider-1"})

            row = json.loads(paths[1].read_text())
            row["task_id"] = "provider-0"
            row["submission_fingerprint"] = "e" * 64
            _write_json(paths[1], row)
            with self.assertRaises(validation.ValidationBlocked):
                validation._validate_transactions(
                    guard, config, "E01", ["UNIT-1", "UNIT-2"], order,
                )

    def test_transactions_reject_reference_bytes_changed_after_submission(self):
        with tempfile.TemporaryDirectory() as temporary:
            _runtime, config, guard, _paths, reference, order = \
                self._video_transaction_fixture(temporary)
            reference.write_bytes(b"tampered")
            with self.assertRaisesRegex(validation.ValidationBlocked, "REFERENCE_SHA_MISMATCH"):
                validation._validate_transactions(
                    guard, config, "E01", ["UNIT-1", "UNIT-2"], order,
                )

    def test_transactions_reject_paid_manifest_order_tamper(self):
        with tempfile.TemporaryDirectory() as temporary:
            _runtime, config, guard, _paths, _reference, order = \
                self._video_transaction_fixture(temporary)
            manifest = Path(config["storyclaw"]["storage"]["workspace_backing_path"]) \
                / "E01/preproduction/E01_VIDEO_TRANSACTION_MANIFEST_V1.json"
            payload = json.loads(manifest.read_text())
            payload["paid_authorization"]["order_id"] = "forged-order"
            _write_json(manifest, payload)
            with self.assertRaisesRegex(validation.ValidationBlocked, "ORDER_ID_MISMATCH"):
                validation._validate_transactions(
                    guard, config, "E01", ["UNIT-1", "UNIT-2"], order,
                )

    def test_ledger_requires_provider_task_set_and_exact_total(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _engine, _workspace, _transactions, _config, guard = \
                self._private_runtime(temporary)
            budget = _write_json(runtime / "budget-report.json", {
                "schema": "nalu.episode_credit_budget_ledger.v1",
                "episode": "E01", "status": "PASS", "failures": [],
                "cap_credits": 100,
                "spend": {"recorded_total_credits": 12, "accounting_complete": True},
            })
            provider = _write_json(runtime / "provider-ledger.json", {
                "schema": "qingshan.giggle_credit_ledger.v1",
                "submitted_task_count": 2, "image_task_count": 0,
                "video_task_count": 2, "unknown_media_task_count": 0,
                "actual_credits_total": 12, "balance_before": 100,
                "balance_after": 88,
                "tasks": [{"task_id": "provider-0"}, {"task_id": "provider-1"}],
            })
            _write_json(runtime / "runtime/budget/ledger.json", {
                "schema": "nalu.episode_credit_budget_ledger_log.v1",
                "entries": [{
                    "episode": "E01", "status": "PASS",
                    "accounting_complete": True, "recorded_total_credits": 12,
                }],
            })
            inputs = {"evidence": {
                "budget_report": str(budget), "provider_ledger": str(provider),
            }}
            result = validation._validate_ledger(
                inputs, guard, "E01", {"provider-0", "provider-1"}
            )
            self.assertTrue(result["reconciled"])
            changed = json.loads(provider.read_text())
            changed["actual_credits_total"] = 11
            changed["balance_after"] = 89
            _write_json(provider, changed)
            with self.assertRaisesRegex(validation.ValidationBlocked, "TOTAL_MISMATCH"):
                validation._validate_ledger(
                    inputs, guard, "E01", {"provider-0", "provider-1"}
                )

    def test_paid_order_forbids_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _engine, _workspace, _transactions, config, guard = \
                self._private_runtime(temporary)
            config["generation"] = {"budget_cap_credits_per_episode": 100}
            source = _write_json(runtime / "runtime/orders/source.json", {
                "schema": "qingshan.line_owner_order_source_receipt.v1",
                "status": "CONFIRMED", "order_seq": 1, "order_id": "order-a",
                "issued_by": "owner-a", "verbatim": "authorize trial",
                "recorded_at_utc": "2026-09-20T00:00:00Z",
            })
            orders_path = runtime / "runtime/orders/SUPERVISOR_ORDERS.json"

            def state_for(publication_allowed: bool):
                _write_json(orders_path, {
                    "_schema": "supervisor_orders_v1", "latest_order_seq": 1,
                    "orders": [{
                        "seq": 1, "id": "order-a", "status": "active",
                        "issued_by": "owner-a", "order": "authorize trial",
                        "decision": {
                            "kind": "PAID_PRODUCTION_AUTHORIZATION",
                            "paid_requests_allowed": True,
                            "publication_allowed": publication_allowed,
                            "paid_stages": ["S3", "S4", "S5", "S6"],
                            "episode_scope": ["E01"],
                            "budget_cap_credits_per_episode": 100,
                        },
                        "source_receipt": {"path": str(source), "sha256": _sha(source)},
                    }],
                })
                return {"line_owner_authority": {
                    "status": "PASS", "failures": [],
                    "orders_path": str(orders_path),
                    "orders_file_sha256": _sha(orders_path),
                    "paid_order_seq": 1, "latest_order_seq": 1,
                    "order_id": "order-a",
                }}

            result, _order = validation._validate_paid_authority(
                guard, config, state_for(False), "E01"
            )
            self.assertFalse(result["publication_allowed"])
            with self.assertRaisesRegex(validation.ValidationBlocked, "SCOPE_STAGES_OR_CAP"):
                validation._validate_paid_authority(
                    guard, config, state_for(True), "E01"
                )

    def test_verify_receipt_does_not_trust_nested_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _engine, _workspace, _transactions, _config, _guard = \
                self._private_runtime(temporary)
            inputs = _write_json(runtime / "validation/inputs.json", {"placeholder": True})
            receipt = _write_json(runtime / "validation/receipt.json", {
                "schema": validation.RECEIPT_SCHEMA,
                "status": "PASS",
                "release_commit": "a" * 40,
                "remote_engine_commit": "a" * 40,
                "remote_worktree_clean": True,
                "remote_diff_sha256": validation.EMPTY_SHA256,
                "private_validation_contents_included_in_public_release": False,
                "private_runtime_root": str(runtime),
                "project_id": "project-a", "series_scope_id": "scope-a",
                "episode": "E01",
                "input_manifest": {"path": str(inputs), "sha256": _sha(inputs)},
                "validator": {"mode": "FAKE"},
                "checks": {name: {"status": "PASS"} for name in validation.VALIDATION_CHECKS},
            })
            recomputed = {
                "project_id": "project-a", "series_scope_id": "scope-a",
                "episode": "E01", "private_runtime_root": str(runtime),
                "input_manifest": {"path": str(inputs), "sha256": _sha(inputs)},
                "validator": {"mode": "LIVE_PRIVATE_EVIDENCE_RECOMPUTED"},
                "checks": {},
            }
            with mock.patch.object(validation, "evaluate_inputs", return_value=recomputed):
                with self.assertRaisesRegex(
                    validation.ValidationBlocked, "RECOMPUTED_FIELD_MISMATCH"
                ):
                    validation.verify_receipt(receipt, "a" * 40)


if __name__ == "__main__":
    unittest.main()
