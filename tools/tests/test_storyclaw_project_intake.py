"""Regression tests for isolated StoryClaw project/bootstrap and source intake."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools import storyclaw_project_intake as intake


PUBLIC_IP = "93.184.216.34"


class StoryClawProjectIntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.engine = self.root / "engine"
        self.engine.mkdir()
        (self.engine / "tools").mkdir()
        self.projects = self.root / "private-projects"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_project(self, **overrides):
        values = {
            "title": "Portable drama",
            "project_id": "portable-drama",
            "series_scope_id": "PORTABLE_DRAMA",
            "episodes": ["E01", "E02"],
        }
        values.update(overrides)
        receipt = intake.initialize_project(self.projects, self.engine, **values)
        return (self.projects / values["project_id"]).resolve(), receipt

    def test_init_creates_isolated_private_runtime_and_safe_empty_authorities(self):
        project, receipt = self.create_project()
        self.assertEqual(receipt["status"], "INITIALIZED_PRIVATE")
        self.assertFalse(project.is_relative_to(self.engine))
        marker = json.loads((project / "runtime/project.json").read_text())
        self.assertEqual(marker["private_runtime_root"], str(project))
        self.assertFalse(marker["paid_requests_enabled"])

        config = json.loads((project / "qingshan.json").read_text())
        self.assertFalse(config["generation"]["paid_requests_enabled"])
        self.assertFalse(config["release"]["automatic_platform_upload_enabled"])
        self.assertEqual(config["storyclaw"]["policy_profile"], "CURRENT_PORTABLE")
        self.assertEqual(config["storyclaw"]["model_priority"][:2], [
            "storyclaw/gpt-6-astra", "storyclaw/claude-opus-5",
        ])
        self.assertEqual(
            config["storyclaw"]["model_priority"][2], "storyclaw/gpt-5.6-sol"
        )
        self.assertEqual(config["authorization"]["paid_order_seq"], 0)
        self.assertEqual(config["authorization"]["line_owner_id"], "")
        self.assertTrue(Path(config["authorization"]["supervisor_orders_path"]).is_relative_to(project))

        scopes = json.loads((project / "runtime/series_scopes.json").read_text())
        self.assertEqual(scopes["default_scope"], "PORTABLE_DRAMA")
        self.assertEqual(scopes["episodes"], {"E01": "PORTABLE_DRAMA", "E02": "PORTABLE_DRAMA"})
        scope = scopes["scopes"]["PORTABLE_DRAMA"]
        required = {
            "series_root", "asset_library", "asset_library_seed", "voice_registry",
            "voice_catalog", "voice_cast", "entity_registry", "agentcut_voice_policy",
            "character_registry", "character_sources", "voice_refs", "lexicon", "charter",
        }
        self.assertTrue(required.issubset(scope))
        self.assertEqual(scope["lexicon"], "runtime/series/PORTABLE_DRAMA/lexicon.json")
        lexicon = json.loads((project / scope["lexicon"]).read_text())
        self.assertEqual(lexicon["status"], "EMPTY_PENDING_SCRIPT_DERIVATION")
        self.assertEqual(lexicon["canonical_names"], {})

        library = json.loads((project / scope["asset_library"]).read_text())
        self.assertEqual(library["schema"], "ai_drama.production_asset_library.v1")
        self.assertEqual(library["project_id"], "PORTABLE_DRAMA")
        self.assertEqual(library["assets"]["characters"], {})
        orders = json.loads((project / "runtime/orders/SUPERVISOR_ORDERS.json").read_text())
        self.assertEqual(orders, {
            "_schema": "supervisor_orders_v1", "latest_order_seq": 0, "orders": [],
        })
        ledger = json.loads((project / "runtime/budget/ledger.json").read_text())
        self.assertEqual(ledger["schema"], "nalu.episode_credit_budget_ledger_log.v1")
        self.assertEqual(ledger["entries"], [])
        for expected in (
            "writer_layers/PORTABLE_DRAMA/E01",
            "writer_layers/PORTABLE_DRAMA/E02",
            "runtime/reviews/PORTABLE_DRAMA/E01",
            "runtime/storyclaw_storage/workflow/nalu",
            "runtime/storyclaw_storage/workflow/tasks",
            "sources/PORTABLE_DRAMA/intake",
        ):
            self.assertTrue((project / expected).is_dir(), expected)

    def test_init_is_idempotent_but_refuses_id_collision_or_engine_overlap(self):
        project, _ = self.create_project()
        _, again = self.create_project()
        self.assertEqual(again["status"], "EXISTS_UNCHANGED")
        with self.assertRaisesRegex(intake.IntakeBlocked, "CONFIGURATION_MISMATCH"):
            intake.initialize_project(
                self.projects, self.engine, title="Different title",
                project_id="portable-drama", series_scope_id="PORTABLE_DRAMA", episodes=["E01", "E02"],
            )
        with self.assertRaisesRegex(intake.IntakeBlocked, "PROJECT_ID_INVALID"):
            intake.initialize_project(
                self.projects, self.engine, title="Bad", project_id="../escape",
                series_scope_id="BAD", episodes=["E01"],
            )
        with self.assertRaisesRegex(intake.IntakeBlocked, "OVERLAPS_ENGINE"):
            intake.initialize_project(
                self.engine / "private", self.engine, title="Bad location",
                project_id="inside", series_scope_id="INSIDE", episodes=["E01"],
            )
        self.assertTrue(project.is_dir())

    def test_local_text_is_copied_with_hash_and_private_receipt(self):
        project, _ = self.create_project()
        source = self.root / "novel.txt"
        raw = "第一章 起点\n这是测试正文。\n".encode("gb18030")
        source.write_bytes(raw)
        rights = "The deployer states adaptation rights are held."
        receipt = intake.intake_local_text(project, source, rights_statement=rights)
        self.assertEqual(receipt["status"], "INGESTED")
        self.assertEqual(receipt["intake_kind"], "LOCAL_TEXT")
        self.assertEqual(receipt["origin"]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(receipt["origin"]["detected_encoding"], "gb18030")
        artifact = project / receipt["artifacts"][0]["path"]
        self.assertEqual(artifact.read_bytes(), raw)
        copied_receipt = project / "runtime/receipts/source_intake" / f"{receipt['source_id']}.json"
        self.assertTrue(copied_receipt.is_file())
        self.assertFalse(any(self.engine.rglob("novel.txt")))
        again = intake.intake_local_text(project, source, rights_statement=rights)
        self.assertEqual(again["status"], "EXISTS_UNCHANGED")
        with self.assertRaisesRegex(intake.IntakeBlocked, "PROVENANCE_MISMATCH"):
            intake.intake_local_text(project, source, rights_statement="a different declaration")

    def test_pasted_text_is_private_and_return_value_never_echoes_source(self):
        project, _ = self.create_project()
        source_text = "A private opening scene that must not be echoed."
        receipt = intake.intake_pasted_text(project, source_text)
        self.assertEqual(receipt["status"], "INGESTED")
        self.assertEqual(receipt["intake_kind"], "PASTED_TEXT")
        self.assertEqual(
            receipt["origin"]["sha256"],
            hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        )
        self.assertNotIn(source_text, json.dumps(receipt))
        artifact = project / receipt["artifacts"][0]["path"]
        self.assertEqual(artifact.read_text(), source_text)
        self.assertTrue(artifact.is_relative_to(project))
        with self.assertRaisesRegex(intake.IntakeBlocked, "PASTED_SOURCE_TEXT_EMPTY"):
            intake.intake_pasted_text(project, "  \n")

    def test_non_text_local_file_is_blocked_without_success_receipt(self):
        project, _ = self.create_project()
        binary = self.root / "binary.dat"
        binary.write_bytes(b"text\x00binary")
        with self.assertRaisesRegex(intake.IntakeBlocked, "SOURCE_IS_NOT_TEXT"):
            intake.intake_local_text(project, binary)
        self.assertEqual(list((project / "runtime/receipts/source_intake").iterdir()), [])

    def test_url_validation_rejects_unsafe_schemes_credentials_and_private_dns(self):
        for url in ("file:///etc/passwd", "ftp://example.com/a", "http://user:pass@example.com/a"):
            with self.subTest(url=url), self.assertRaises(intake.IntakeBlocked):
                intake.validate_public_url(url, resolver=lambda host, port: [PUBLIC_IP])
        with self.assertRaisesRegex(intake.IntakeBlocked, "LOCALHOST"):
            intake.validate_public_url("http://localhost/a", resolver=lambda host, port: [PUBLIC_IP])
        for addresses in (["127.0.0.1"], ["10.0.0.8"], [PUBLIC_IP, "192.168.1.2"], ["::1"]):
            with self.subTest(addresses=addresses), self.assertRaisesRegex(
                intake.IntakeBlocked, "URL_TARGET_NOT_PUBLIC"
            ):
                intake.validate_public_url("https://example.com/source", resolver=lambda host, port, a=addresses: a)

    def test_url_intake_extracts_html_and_records_final_url_hash_and_peer(self):
        project, _ = self.create_project()
        calls = []

        def resolver(host, port):
            calls.append(("resolve", host, port))
            return [PUBLIC_IP]

        def requester(target, *, timeout, max_bytes):
            calls.append(("request", target.url, target.addresses))
            return intake.HTTPResult(
                200, "OK", {"content-type": "text/html; charset=utf-8"},
                "<html><head><style>x</style></head><body><h1>第一章</h1><p>正文内容</p><script>bad()</script></body></html>".encode(),
                PUBLIC_IP,
            )

        receipt = intake.intake_url(
            project, "https://example.com/book?id=1#fragment",
            rights_statement="Private validation source", resolver=resolver, requester=requester,
        )
        self.assertEqual(receipt["status"], "INGESTED")
        self.assertEqual(receipt["origin"]["final_url"], "https://example.com/book?id=1")
        self.assertEqual(receipt["origin"]["connected_public_ip"], PUBLIC_IP)
        self.assertRegex(receipt["origin"]["response_sha256"], r"^[0-9a-f]{64}$")
        by_name = {row["name"]: project / row["path"] for row in receipt["artifacts"]}
        self.assertIn("第一章", by_name["source.txt"].read_text())
        self.assertIn("正文内容", by_name["source.txt"].read_text())
        self.assertNotIn("bad()", by_name["source.txt"].read_text())
        self.assertTrue(by_name["source.html"].is_file())
        self.assertEqual(calls[0], ("resolve", "example.com", 443))

    def test_redirect_to_private_network_is_blocked_before_second_request(self):
        project, _ = self.create_project()
        request_count = 0

        def resolver(host, port):
            return ["10.1.2.3"] if host == "internal.example" else [PUBLIC_IP]

        def requester(target, *, timeout, max_bytes):
            nonlocal request_count
            request_count += 1
            return intake.HTTPResult(
                302, "Found", {"location": "http://internal.example/private"}, b"", PUBLIC_IP,
            )

        with self.assertRaisesRegex(intake.IntakeBlocked, "URL_TARGET_NOT_PUBLIC"):
            intake.intake_url(
                project, "https://example.com/start", resolver=resolver, requester=requester,
            )
        self.assertEqual(request_count, 1)
        self.assertEqual(list((project / "runtime/receipts/source_intake").iterdir()), [])

    def test_binary_url_response_is_blocked_without_success_receipt(self):
        project, _ = self.create_project()

        def requester(target, *, timeout, max_bytes):
            return intake.HTTPResult(
                200, "OK", {"content-type": "application/octet-stream"}, b"not text", PUBLIC_IP,
            )

        with self.assertRaisesRegex(intake.IntakeBlocked, "CONTENT_TYPE_NOT_TEXT"):
            intake.intake_url(
                project, "https://example.com/file.bin",
                resolver=lambda host, port: [PUBLIC_IP], requester=requester,
            )
        self.assertEqual(list((project / "runtime/receipts/source_intake").iterdir()), [])

    def test_url_response_peer_must_match_the_validated_public_address(self):
        project, _ = self.create_project()

        def requester(target, *, timeout, max_bytes):
            return intake.HTTPResult(
                200, "OK", {"content-type": "text/plain"}, b"source text", "1.1.1.1",
            )

        with self.assertRaisesRegex(intake.IntakeBlocked, "URL_PEER_IP_MISMATCH"):
            intake.intake_url(
                project, "https://example.com/source.txt",
                resolver=lambda host, port: [PUBLIC_IP], requester=requester,
            )
        self.assertEqual(list((project / "runtime/receipts/source_intake").iterdir()), [])

    def test_cli_reports_blocked_with_nonzero_exit(self):
        script = Path(intake.__file__)
        result = subprocess.run(
            [sys.executable, str(script), "init", "--projects-root", str(self.projects),
             "--engine-root", str(self.engine), "--title", "Bad", "--project-id", "../bad"],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
