"""Device 0080 E05 (2026-11-21): VU-012/VU-015 failed post-generation ``freeze`` and S6 dead-ended at
POST_GENERATION_QA_PARTIAL_18_OF_20 -- the default-acceptance order seq=62 did not match (gate / detector
spelling) and the reroll the runner kept requesting is never executed by the engine (one redo already used)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
sys.path.insert(0, str(TOOLS))


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


qa = load("post_generation_qa_runner")
UNIT = "E05-VU-012"
SHA = "a" * 64


def write_inbox(root: Path, *, gate_id: str, detectors: list[str], shas: dict[str, str],
                latest_ack: int = 62, seq: int = 62) -> Path:
    verbatim = "默认条款自动接受：质量问题不阻塞连续生产（短剧工作流）"
    receipt = {"schema": "qingshan.line_owner_order_source_receipt.v1", "status": "CONFIRMED",
               "issued_by": "owner", "order_seq": seq, "order_id": f"OWNER-{seq}",
               "verbatim": verbatim, "recorded_at_utc": "2026-11-21T20:00:00Z"}
    rp = root / "receipt.json"
    rp.write_text(json.dumps(receipt), encoding="utf-8")
    order = {"seq": seq, "id": f"OWNER-{seq}", "issued_by": "owner", "status": "active", "order": verbatim,
             "decision": {"kind": "GATE_FAIL_ACCEPTANCE", "episode": "E05", "gate_id": gate_id,
                          "detectors": detectors, "media_sha256_by_item": shas},
             "source_receipt": {"path": str(rp), "sha256": hashlib.sha256(rp.read_bytes()).hexdigest()}}
    inbox = root / "SUPERVISOR_ORDERS.json"
    inbox.write_text(json.dumps({"_schema": "supervisor_orders_v1", "latest_order_seq": seq,
                                 "orders": [order]}), encoding="utf-8")
    return inbox


def rows(sha: str = SHA):
    return [{"unit_id": UNIT, "verdict": "REJECT", "reasons": ["freeze:FAIL"], "media_sha256": sha,
             "media_path": f"/w/video/{UNIT}.mp4"}]


class PostgenFreezeAcceptance(unittest.TestCase):
    def _apply(self, inbox: Path, root: Path, r, ack: int = 62):
        with patch.dict(os.environ, {"NALU_SUPERVISOR_ORDERS_PATH": str(inbox),
                                     "NALU_LATEST_ORDER_SEQ": str(ack), "NALU_LINE_OWNER_ID": "owner"}):
            return qa.apply_roger_postgen_acceptance("E05", r, root)

    def test_device_shaped_order_admits_freeze(self):
        # blocker-text gate id, short unit + bare check name, ack trailing the inbox
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            inbox = write_inbox(root, gate_id="POST_GENERATION_QA_PARTIAL_18_OF_20",
                                detectors=["VU-012:freeze"], shas={"VU-012": SHA})
            r = rows()
            out = self._apply(inbox, root, r, ack=61)
            self.assertEqual(out["accepted_unit_ids"], [UNIT])
            self.assertEqual(r[0]["verdict"], "ADMIT")
            self.assertEqual(r[0]["engine_reasons"], ["freeze:FAIL"])
            self.assertEqual(r[0]["roger_acceptance"]["order_seq"], 62)

    def test_tolerant_detector_names(self):
        for gate, det in [("POST-GENERATION-QA-ADMISSION", f"{UNIT}:freeze:FAIL"),
                          ("freeze", "FREEZE"), ("POSTGEN_QA", "E05-VU-012:FROZEN"),
                          ("POST-GENERATION-QA", "VU-012:POST-GENERATION-QA-ADMISSION")]:
            with self.subTest(gate=gate, det=det), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                inbox = write_inbox(root, gate_id=gate, detectors=[det], shas={UNIT: SHA})
                self.assertEqual(self._apply(inbox, root, rows())["accepted_unit_ids"], [UNIT])

    def test_other_unit_or_other_check_not_covered(self):
        self.assertFalse(qa.postgen_detector_covers("VU-015:freeze", UNIT, "freeze:FAIL"))
        self.assertFalse(qa.postgen_detector_covers(f"{UNIT}:black_frame", UNIT, "freeze:FAIL"))
        self.assertFalse(qa.postgen_detector_covers(f"{UNIT}:FAIL", UNIT, "freeze:FAIL"))

    def test_wrong_sha_refused_with_reason(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            inbox = write_inbox(root, gate_id="POST-GENERATION-QA-ADMISSION",
                                detectors=[f"{UNIT}:freeze:FAIL"], shas={UNIT: "b" * 64})
            r = rows()
            out = self._apply(inbox, root, r)
            self.assertEqual(out["accepted_unit_ids"], [])
            self.assertEqual(r[0]["verdict"], "REJECT")
            need = out["orders_needed"][0]
            self.assertTrue(need["candidates"][0]["refused"].startswith("SHA_NOT_CURRENT"))
            self.assertIn(f"--media {UNIT}=/w/video/{UNIT}.mp4", out["record_hint"])
            self.assertIn(f"--detector '{UNIT}:freeze:FAIL'", out["record_hint"])
            self.assertIn("--gate-id POST-GENERATION-QA-ADMISSION", out["record_hint"])


class RerollThatCannotRun(unittest.TestCase):
    def test_redo_used_is_not_requested_again(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            media = root / "video"
            (media / "_superseded_run1").mkdir(parents=True)
            (media / "_superseded_run1" / f"{UNIT}.mp4").write_bytes(b"old")
            paths = SimpleNamespace(video_media=media, preprod_reports=root / "reports", qa_root=root / "qa",
                                    reroll_ledger=root / "qa" / "ledger.json",
                                    reroll_requests=root / "qa" / "REROLL_REQUESTS.json")
            rejected = [{"unit_id": UNIT, "primary_reason": "freeze:FAIL", "reasons": ["freeze:FAIL"],
                         "failure_class": "CANDIDATE_TECHNICAL_FAILURE"},
                        {"unit_id": "E05-VU-003", "primary_reason": "freeze:FAIL", "reasons": ["freeze:FAIL"]}]
            with patch.object(qa, "QaPaths", lambda ep: paths):
                first = qa.build_reroll_requests("E05", rejected, total_paid_tasks=20)
                second = qa.build_reroll_requests("E05", rejected, total_paid_tasks=20)
            self.assertEqual([r["unit_id"] for r in first["not_executable"]], [UNIT])
            self.assertIn("ONE_PAID_REDO_PER_UNIT_USED:SUPERSEDED_CLIP", first["not_executable"][0]["why_not_executed"])
            self.assertEqual([r["unit_id"] for r in first["requests"]], ["E05-VU-003"])
            self.assertEqual(second["request_count"], 1)
            ledger = json.loads(paths.reroll_ledger.read_text())
            self.assertEqual(len(ledger["events"]), 1)   # no new REQUESTED event per S6 pass

    def test_s6_qa_names_needed_order_instead_of_bare_partial(self):
        npl = load("nalu_pipeline")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "video").mkdir()
            (root / "video" / f"{UNIT}.mp4").write_bytes(b"x")
            summary = root / "E05_POST_GENERATION_QA_SUMMARY.json"
            summary.write_text(json.dumps({
                "units": [], "postgen_record_hint": "record_supervisor_order.py --gate-id POST-GENERATION-QA-ADMISSION",
                "roger_gate_acceptance": {"inbox": {"inbox": "STRICT_OK"}, "orders_read": 1},
                "postgen_orders_needed": [{"unit_id": UNIT, "reason": "NO_ORDER_MATCHES_EPISODE_GATE_REASONS_AND_SHA",
                                           "reroll": "NOT_EXECUTABLE:ONE_PAID_REDO_PER_UNIT_USED:X"}]}))
            ctx = SimpleNamespace(episode="E05", p=SimpleNamespace(video_media=root / "video",
                                                                  preprod_reports=root / "reports"))
            res = SimpleNamespace(steps=[], receipts=[])
            outs = {"s6_qa_post_generation_qa_runner": {"status": "PARTIAL_19_OF_20", "out": str(summary)}}
            with patch.object(npl, "qa_run", side_effect=lambda c, argv, name, **kw: {"name": name}), \
                 patch.object(npl, "qa_json", side_effect=lambda step: outs.get(step["name"], {})), \
                 patch.object(npl, "latest_submitted_review", return_value=(summary, {})), \
                 patch.object(npl, "ctx_language", return_value="ko"), \
                 patch.object(npl, "kb_events", return_value=[]), \
                 patch.object(npl, "kb_postgen_rows", return_value=[]):
                detail = npl.s6_qa(ctx, res)
            self.assertEqual(detail["blockers"][0], "POST_GENERATION_QA_PARTIAL_19_OF_20")
            self.assertIn(f"{UNIT}:NO_ORDER_MATCHES_EPISODE_GATE_REASONS_AND_SHA:REROLL_NOT_EXECUTABLE",
                          detail["blockers"])
            self.assertIn("POST-GENERATION-QA-ADMISSION", detail["record_hint"])


if __name__ == "__main__":
    unittest.main()
