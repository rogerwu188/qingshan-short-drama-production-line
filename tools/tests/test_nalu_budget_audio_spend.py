"""S4 TTS (Giggle text-to-audio) spend must be in the per-episode budget ledger.

Lab E09, 2026-10-30: 13 completed S4 speech transactions under
``workflow/tasks/giggle_audio_transactions/<scope>/E09/speech/`` (live + ``_superseded_*`` recasts)
were never scanned, so the S6 check reported 881.47 / 900 with ``accounting_complete=true``.
"""
from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
B = importlib.import_module("nalu_budget_ledger")
EP = "E97"
SCOPE = "SCOPE-A"


class AudioSpendTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "engine"
        self.runtime = Path(tmp.name) / "runtime"
        (self.runtime / "runtime" / "reports").mkdir(parents=True)
        for patcher in (mock.patch.object(B, "ENGINE_ROOT", self.root),
                        mock.patch.object(B._np, "RUNTIME_ROOT", self.runtime),
                        mock.patch.object(B, "_series_scope_id", return_value=SCOPE)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.tasks = self.root / "workflow" / "tasks"
        self.audio = self.tasks / B.AUDIO_TRANSACTION_DIRNAME / SCOPE / EP / "speech"

    def _tx(self, rel: str, task_id: str | None, state: str = "TERMINAL_COMPLETED", **extra) -> None:
        path = self.audio / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema": "qingshan.storyclaw_audio_transaction.v1", "state": state,
                   "capability": "AGENTCUT-SPEECH-001", "intent_recorded_at": "2026-10-30T02:52:23Z", **extra}
        if task_id:
            payload["task_id"] = task_id
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _image_statement(self, name: str, rows: list[dict]) -> None:
        d = self.root / "workflow" / "nalu" / EP / "identity"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}_credit_statement.json").write_text(json.dumps({
            "episode": EP, "status": "PASS_BOUNDED", "event_description": "SingleGenerateImage",
            "charged_credits": sum(abs(float(r["credit"])) for r in rows), "matched_count": len(rows),
            "statement_rows": rows}), encoding="utf-8")

    def test_completed_tts_including_superseded_recasts_are_counted_and_flagged(self) -> None:
        self._tx("jones.json", "t-live")
        self._tx("_superseded_20261029T194529_s4_voice_collision/jones.json", "t-old-1")
        self._tx("_superseded_20261029T194800_s4_voice_collision/jones.json", "t-old-2")
        spend = B.scan_non_video_spend(EP)
        audio = spend["audio"]
        self.assertEqual(audio["task_count"], 3)
        self.assertEqual(audio["estimated_credits"], 6)
        self.assertEqual(audio["estimated_task_count"], 3)
        self.assertEqual({r["method"] for r in audio["rows"]}, {"ESTIMATED_UNIT_PRICE"})
        self.assertEqual(spend["audio_credits"], 6)
        self.assertEqual(spend["subtotal_credits"], 6)

    def test_parked_copy_of_the_same_task_is_counted_once(self) -> None:
        self._tx("jones.json", "t-1")
        self._tx("_superseded_x/jones.json", "t-1")
        self.assertEqual(B.scan_non_video_spend(EP)["audio_credits"], 2)

    def test_actual_charge_preferred_transaction_then_receipt(self) -> None:
        self._tx("a.json", "t-a", credit={"net_charged_credits": 1.5, "statement_status": "PASS_CHARGED"})
        self._tx("b.json", "t-b")
        self._tx("c.json", "t-c", state="TERMINAL_FAILED")
        (self.runtime / "runtime" / "reports" / f"{EP}_S4_EXACT_TASK_CREDITS.json").write_text(json.dumps([
            {"task_id": "t-b", "ledger": {"status": "PASS_CHARGED", "net_charged_credits": 2}},
            {"task_id": "t-c", "ledger": {"status": "PASS_REFUNDED", "net_charged_credits": 0}},
        ]), encoding="utf-8")
        audio = B.scan_non_video_spend(EP)["audio"]
        methods = {r["task_id"]: (r["method"], r["credits"]) for r in audio["rows"]}
        self.assertEqual(methods["t-a"], ("TRANSACTION_RECONCILED_CREDIT", 1.5))
        self.assertEqual(methods["t-b"], ("EXACT_TASK_CREDIT_RECEIPT", 2))
        self.assertEqual(methods["t-c"], ("EXACT_TASK_CREDIT_RECEIPT", 0))
        self.assertEqual(audio["charged_credits"], 3.5)
        self.assertEqual(audio["estimated_task_count"], 0)

    def test_statement_row_with_tts_task_id_is_not_double_counted(self) -> None:
        self._tx("jones.json", "t-tts")
        self._image_statement("w1", [
            {"project_id": "img-1", "event_type": "Pay", "event_description": "SingleGenerateImage",
             "created_at": "2026-10-30 02:00:00", "credit": "-11"},
            {"project_id": "t-tts", "event_type": "Pay", "event_description": "SingleGenerateAudio",
             "created_at": "2026-10-30 02:52:30", "credit": "-2"},
        ])
        spend = B.scan_non_video_spend(EP)
        self.assertEqual(spend["batch_reconciled_credits"], 11)
        self.assertEqual(spend["audio"]["rows"][0]["method"], "GIGGLE_STATEMENT_TASK_ID_MATCH")
        self.assertEqual(spend["audio_credits"], 2)
        self.assertEqual(spend["subtotal_credits"], 13)

    def test_decimal_string_statement_credits_are_counted(self) -> None:
        # Field E09 2026-11-12: Giggle video statements carry charged_credits as "13.6"-style strings.
        d = self.root / "workflow" / "nalu" / EP / "preproduction" / "reports"
        d.mkdir(parents=True, exist_ok=True)
        for name, task_id, amount in (("v1", "vid-1", "13.6"), ("v2", "vid-2", "23.8"), ("v3", "vid-3", "28.9")):
            (d / f"{name}_credit_statement.json").write_text(json.dumps({
                "episode": EP, "status": "PASS_BOUNDED", "event_description": "VideoGenerate",
                "charged_credits": amount, "matched_count": 1,
                "statement_rows": [{"project_id": task_id, "event_type": "Pay", "event_description": "VideoGenerate",
                                    "created_at": "2026-11-12 10:00:00", "credit": "-" + amount}]}), encoding="utf-8")
        (d / "bare_credit_statement.json").write_text(json.dumps({
            "episode": EP, "status": "PASS_BOUNDED", "charged_credits": "5.5"}), encoding="utf-8")
        spend = B.scan_non_video_spend(EP)
        self.assertAlmostEqual(float(spend["batch_reconciled_credits"]), 71.8)

    def test_statement_credits_coercion(self) -> None:
        self.assertEqual(B._statement_credits("13.6"), 13.6)
        self.assertEqual(B._statement_credits(" 7 "), 7)
        self.assertEqual(B._statement_credits(4.5), 4.5)
        for bad in (None, True, "abc", "NaN", "", [1]):
            self.assertIsNone(B._statement_credits(bad))

    def test_credit_attempt_with_tts_task_id_moves_to_audio_leg(self) -> None:
        self._tx("jones.json", "t-tts")
        d = self.tasks / "voice_jobs"
        d.mkdir(parents=True)
        (d / "x.json").write_text(json.dumps({"episode": EP, "tasks": [{
            "tool_type": "text_to_audio", "task_key": "jones",
            "credit_attempts": [{"task_id": "t-tts", "actual_charged_credits": 2, "success": True}]}]}),
            encoding="utf-8")
        spend = B.scan_non_video_spend(EP)
        self.assertEqual(spend["per_task_credits"], 0)
        self.assertEqual(spend["audio"]["rows"][0]["method"], "CREDIT_ATTEMPT_TASK_ID_MATCH")
        self.assertEqual(spend["subtotal_credits"], 2)

    def test_intent_without_task_id_is_unresolved(self) -> None:
        self._tx("jones.json", None, state="INTENT_RECORDED")
        audio = B.scan_non_video_spend(EP)["audio"]
        self.assertEqual(len(audio["unresolved_transactions"]), 1)
        self.assertEqual(audio["task_count"], 0)

    def test_scoped_bgm_store_found_without_explicit_dir(self) -> None:
        d = self.tasks / B.BGM_TRANSACTION_DIRNAME / SCOPE / EP
        d.mkdir(parents=True)
        (d / "cue.json").write_text(json.dumps({"state": "TERMINAL_COMPLETED", "task_id": "m-1",
                                                "credit": {"net_charged_credits": 8}}), encoding="utf-8")
        spend = B.scan_non_video_spend(EP)
        self.assertEqual(spend["bgm_credits"], 8)
        self.assertEqual(spend["subtotal_credits"], 8)

    def test_audio_store_is_scoped(self) -> None:
        self._tx("jones.json", "t-mine")
        other = self.tasks / B.AUDIO_TRANSACTION_DIRNAME / "OTHER-SERIES" / EP / "speech"
        other.mkdir(parents=True)
        (other / "x.json").write_text(json.dumps({"state": "TERMINAL_COMPLETED", "task_id": "t-other"}),
                                      encoding="utf-8")
        self.assertEqual(B.scan_non_video_spend(EP)["audio"]["task_count"], 1)


class ScopeDerivationTests(unittest.TestCase):
    def test_scope_comes_from_the_pipeline_bgm_dir(self) -> None:
        bgm = Path("/x/workflow/tasks") / B.BGM_TRANSACTION_DIRNAME / "SCOPE-Z" / EP
        self.assertEqual(B._series_scope_id(EP, bgm), "SCOPE-Z")


if __name__ == "__main__":
    unittest.main()
