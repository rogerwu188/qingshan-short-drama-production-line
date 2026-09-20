"""Paid production authority must come from a current private, source-receipted order."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location(
    "materialize_paid_authorization", TOOLS / "materialize_paid_authorization.py")
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)
import nalu_pipeline as pipeline  # noqa: E402


def _write_fixture(root: Path, *, episode_scope=None, paid=True, owner="owner-1",
                   status="active", latest=1, seq=1):
    private = root / "private"; private.mkdir()
    verbatim = "Authorize paid production for E01 under the declared cap and rights basis."
    receipt = {
        "schema": mod.RECEIPT_SCHEMA, "status": "CONFIRMED", "issued_by": owner,
        "order_seq": seq, "order_id": "ORDER-1", "verbatim": verbatim,
        "recorded_at_utc": "2026-09-20T00:00:00Z",
    }
    receipt_path = private / "order-1-source-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    receipt_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    order = {
        "seq": seq, "id": "ORDER-1", "issued_by": owner, "status": status,
        "order": verbatim,
        "source_receipt": {"path": str(receipt_path), "sha256": receipt_sha},
        "decision": {
            "kind": mod.PAID_DECISION_KIND,
            "paid_requests_allowed": paid,
            "paid_stages": ["S3", "S4", "S5", "S6"],
            "episode_scope": episode_scope or ["E01"],
            "budget_cap_credits_per_episode": 8000,
            "video_model": mod.SD2,
            "rights_basis": "Line owner declares adaptation and likeness rights handled offline.",
            "rights_declared_by": owner,
            "rights_scope": "E01 production assets",
            "publication_allowed": False,
        },
        "conditions": [
            {"id": "VIDEO_MODEL_SD2_ONLY", "text": "Use seedance-2.0-pro only."},
            {"id": "BUDGET_CAP_PER_EPISODE", "text": "Hard cap 8000 credits."},
            {"id": "PAID_REQUESTS_EXPLICITLY_AUTHORIZED", "text": "Paid requests allowed."},
            {"id": "RIGHTS_BASIS_DECLARED", "text": "Rights basis declared by line owner."},
        ],
    }
    orders_path = private / "SUPERVISOR_ORDERS.json"
    payload = {"_schema": mod.ORDERS_SCHEMA, "latest_order_seq": latest, "orders": [order]}
    orders_path.write_text(json.dumps(payload), encoding="utf-8")
    return orders_path, receipt_path, payload


class PaidOrderTests(unittest.TestCase):
    def read(self, root: Path, orders: Path, **kwargs):
        return mod.read_order(
            orders, kwargs.pop("seq", 1), kwargs.pop("episode", "E01"),
            kwargs.pop("cap", 8000), expected_owner=kwargs.pop("owner", "owner-1"),
            expected_latest_seq=kwargs.pop("latest", 1), engine_root=root / "engine",
            paid_stage=kwargs.pop("stage", "S3"), require_private=True, **kwargs)

    def test_valid_order_is_exactly_scoped_and_source_receipted(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "engine").mkdir()
            orders, _, _ = _write_fixture(root)
            got = self.read(root, orders)
            self.assertEqual(got["episode_scope"], ["E01"])
            self.assertEqual(got["issued_by"], "owner-1")
            self.assertTrue(got["paid_requests_allowed"])
            self.assertEqual(got["authorized_stage"], "S3")
            self.assertEqual(got["source_receipt"]["status"], "CONFIRMED")

    def test_minimal_agent_created_order_without_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "engine").mkdir()
            orders, _, payload = _write_fixture(root)
            payload["orders"][0].pop("source_receipt")
            orders.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(mod.Refused, "SOURCE_RECEIPT_BINDING_MISSING"):
                self.read(root, orders)

    def test_stale_latest_duplicate_and_public_engine_path_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); engine = root / "engine"; engine.mkdir()
            orders, _, payload = _write_fixture(root)
            with self.assertRaisesRegex(mod.Refused, "LATEST_SEQ_MISMATCH"):
                self.read(root, orders, latest=2)
            payload["orders"].append(dict(payload["orders"][0]))
            orders.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(mod.Refused, "SEQ_DUPLICATE"):
                self.read(root, orders)
            public_orders = engine / "SUPERVISOR_ORDERS.json"
            public_orders.write_text(json.dumps({"_schema": mod.ORDERS_SCHEMA,
                                                  "latest_order_seq": 0, "orders": []}))
            with self.assertRaisesRegex(mod.Refused, "MUST_BE_OUTSIDE_PUBLIC_ENGINE_ROOT"):
                self.read(root, public_orders)

    def test_wrong_episode_or_no_explicit_paid_permission_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "engine").mkdir()
            orders, _, _ = _write_fixture(root, episode_scope=["E02"])
            with self.assertRaisesRegex(mod.Refused, "EPISODE_OUT_OF_ORDER_SCOPE"):
                self.read(root, orders)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "engine").mkdir()
            orders, _, _ = _write_fixture(root, paid=False)
            with self.assertRaisesRegex(mod.Refused, "DOES_NOT_EXPLICITLY_AUTHORIZE"):
                self.read(root, orders)

    def test_paid_stage_must_be_explicitly_listed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "engine").mkdir()
            orders, _, payload = _write_fixture(root)
            payload["orders"][0]["decision"]["paid_stages"] = ["S3", "S5", "S6"]
            orders.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(mod.Refused, "DOES_NOT_AUTHORIZE_PAID_STAGE:S4"):
                self.read(root, orders, stage="S4")

    def test_receipt_byte_change_and_issuer_mismatch_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "engine").mkdir()
            orders, receipt, _ = _write_fixture(root)
            receipt.write_text(receipt.read_text() + "\n", encoding="utf-8")
            with self.assertRaisesRegex(mod.Refused, "RECEIPT_SHA256_MISMATCH"):
                self.read(root, orders)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "engine").mkdir()
            orders, _, _ = _write_fixture(root)
            with self.assertRaisesRegex(mod.Refused, "ORDER_ISSUER_MISMATCH"):
                self.read(root, orders, owner="someone-else")

    def test_runtime_receipts_do_not_claim_the_historical_seq3_authority(self):
        pipeline = (TOOLS / "nalu_pipeline.py").read_text(encoding="utf-8")
        prompt_register = (TOOLS / "prompt_batch_register.py").read_text(encoding="utf-8")
        budget = (TOOLS / "nalu_budget_ledger.py").read_text(encoding="utf-8")
        self.assertNotIn('"authorization": "SUPERVISOR_ORDERS seq=3', prompt_register)
        self.assertNotIn('"authority": "SUPERVISOR_ORDERS.json seq=3', budget)
        self.assertNotIn("ROGER-20260909-NALU-E01-E10-PRODUCTION-AUTHORIZED", pipeline)
        self.assertNotIn("PAID_ORDER_SEQ = 3", pipeline)

    def test_paid_dispatcher_blocks_stage_not_named_by_order_before_budget_or_post(self):
        ctx = object.__new__(pipeline.Ctx)
        ctx.paid_order = {"id": "ORDER-1", "seq": 1, "orders_file_sha256": "a" * 64,
                          "paid_stages": ["S3", "S5", "S6"]}
        ctx.authority_blockers = []
        ctx.paid_enabled = True
        ctx.planned_commands = []
        messages = []
        ctx.say = messages.append
        ctx.budget_check = lambda *args, **kwargs: self.fail("budget must not run before authority")
        status, step = pipeline.Ctx.paid_step(
            ctx, ["provider", "post"], name="s4_voice", sid="S4", planned_credits=2)
        self.assertEqual(status, pipeline.BLOCKED)
        self.assertEqual(step["blocker"], "PAID_AUTHORITY_NOT_VALID_FOR_STAGE")
        self.assertIn("ORDER_DOES_NOT_AUTHORIZE_PAID_STAGE:S4", step["failures"])


if __name__ == "__main__":
    unittest.main()
