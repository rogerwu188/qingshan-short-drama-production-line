"""An interrupted speech POST (no task id) is written off once and the line gets one new attempt.

Fleet device 0899 E18 S4, 2026-11-17: voice-over transaction E18-S05-03 stayed INTENT_RECORDED with no
task id; the provider refuses to re-post it and the ledger failed closed with
AUDIO_UNRESOLVED_TRANSACTIONS on every re-entry, so the episode had no way forward.
"""
from __future__ import annotations

import fcntl
import importlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / "tools", ROOT / "lines" / "nalu" / "runtime" / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
P = importlib.import_module("storyclaw_audio_provider")
B = importlib.import_module("nalu_budget_ledger")

T0 = datetime(2026, 11, 17, 12, 9, 0, tzinfo=timezone.utc)


class UnboundSpeechWriteOffTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "giggle_audio_transactions" / "SCOPE" / "E18" / "voice_over"
        self.dir.mkdir(parents=True)

    def _tx(self, name: str, state: str = "INTENT_RECORDED", **extra) -> Path:
        path = self.dir / name
        payload = {"schema": P.SCHEMA, "transaction_id": f"id-{name}-{state}", "state": state,
                   "capability": P.SPEECH_CAPABILITY, "intent_recorded_at": "2026-11-17T12:09:00Z", **extra}
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _spend(self) -> dict:
        return B.scan_audio_spend([self.dir.parent], statement_net={}, attempt_credits={})

    def test_recent_intent_waits_for_the_grace_period(self) -> None:
        path = self._tx("E18-S05-03.json")
        rows = P.settle_unbound_speech([path], now=T0 + timedelta(seconds=120))
        self.assertEqual([row["status"] for row in rows], ["PENDING_GRACE"])
        self.assertEqual(rows[0]["eligible_at"], "2026-11-17T12:19:00Z")
        self.assertTrue(path.is_file())
        self.assertEqual(len(self._spend()["unresolved_transactions"]), 1)

    def test_after_grace_it_is_archived_counted_and_the_path_released(self) -> None:
        path = self._tx("E18-S05-03.json")
        rows = P.settle_unbound_speech([path], now=T0 + timedelta(seconds=601))
        self.assertEqual([row["status"] for row in rows], ["WRITTEN_OFF_RETRY_OPEN"])
        self.assertFalse(path.exists())
        archive = self.dir / "E18-S05-03.written_off_1.json"
        saved = json.loads(archive.read_text(encoding="utf-8"))
        self.assertEqual(saved["state"], P.WRITTEN_OFF_STATE)
        self.assertEqual(saved["written_off"]["previous_state"], "INTENT_RECORDED")
        spend = self._spend()
        self.assertEqual(spend["unresolved_transactions"], [])
        self.assertEqual(Decimal(str(spend["charged_credits"])), Decimal("2"))
        self.assertEqual(spend["estimated_task_count"], 0)
        self.assertEqual(spend["rows"][0]["method"], "WRITTEN_OFF_UNBOUND_UNIT_PRICE")

    def test_response_lost_uses_the_later_timestamp(self) -> None:
        path = self._tx("a.json", state="RESPONSE_LOST", response_lost_at="2026-11-17T12:14:00Z")
        self.assertEqual(P.settle_unbound_speech([path], now=T0 + timedelta(seconds=601))[0]["status"],
                         "PENDING_GRACE")
        self.assertEqual(P.settle_unbound_speech([path], now=T0 + timedelta(seconds=901))[0]["status"],
                         "WRITTEN_OFF_RETRY_OPEN")

    def test_second_loss_of_the_same_line_stays_blocked(self) -> None:
        path = self._tx("a.json")
        P.settle_unbound_speech([path], now=T0 + timedelta(hours=1))
        again = self._tx("a.json", state="RESPONSE_LOST")
        rows = P.settle_unbound_speech([again], now=T0 + timedelta(hours=2))
        self.assertEqual([row["status"] for row in rows], ["ALREADY_WRITTEN_OFF_ONCE"])
        self.assertTrue(again.is_file())
        spend = self._spend()
        self.assertEqual(len(spend["unresolved_transactions"]), 1)
        self.assertEqual(Decimal(str(spend["charged_credits"])), Decimal("2"))

    def test_a_request_whose_process_still_holds_the_lock_is_left_alone(self) -> None:
        path = self._tx("a.json")
        with path.with_name(path.name + ".lock").open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            rows = P.settle_unbound_speech([path], now=T0 + timedelta(hours=1))
        self.assertEqual([row["status"] for row in rows], ["IN_FLIGHT"])
        self.assertTrue(path.is_file())

    def test_bound_bgm_and_archived_records_are_not_touched(self) -> None:
        bound = self._tx("bound.json", state="TASK_ID_BOUND_QUERY_PENDING", task_id="t-1")
        bgm = self._tx("bgm.json", capability=P.BGM_CAPABILITY)
        archived = self._tx("x.written_off_1.json")
        rows = P.settle_unbound_speech([bound, bgm, archived], now=T0 + timedelta(hours=1))
        self.assertEqual(rows, [])
        self.assertTrue(bound.is_file() and bgm.is_file() and archived.is_file())

    def test_interrupted_settlement_is_completed_not_blocked(self) -> None:
        path = self._tx("a.json")
        archive = self.dir / "a.written_off_1.json"
        archive.write_text(json.dumps({**json.loads(path.read_text(encoding="utf-8")),
                                       "state": P.WRITTEN_OFF_STATE}), encoding="utf-8")
        rows = P.settle_unbound_speech([path], now=T0 + timedelta(hours=1))
        self.assertEqual([row["status"] for row in rows], ["WRITTEN_OFF_RETRY_OPEN"])
        self.assertFalse(path.exists())

    def test_pipeline_settles_before_the_budget_check(self) -> None:
        source = (ROOT / "lines" / "nalu" / "runtime" / "tools" / "nalu_pipeline.py").read_text(encoding="utf-8")
        body = source[source.index("    def budget_check("):source.index("    def budget_release(")]
        self.assertLess(body.index("self.settle_unbound_audio(label=label)"), body.index("BUDGET_LEDGER"))

    def test_cli_settles_one_episode_only(self) -> None:
        import contextlib, io, os, time
        path = self._tx("a.json", intent_recorded_at="2026-11-17T12:09:00Z")
        other = self.dir.parent.parent / "E19" / "voice_over"
        other.mkdir(parents=True)
        foreign = other / "b.json"
        foreign.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        root = self.dir.parent.parent.parent
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = P.main(["settle-unbound-speech", "--episode", "E18", "--transactions-root", str(root)])
        self.assertEqual(rc, 0)
        result = json.loads(buffer.getvalue())
        self.assertEqual([row["status"] for row in result["rows"]], ["WRITTEN_OFF_RETRY_OPEN"])
        self.assertFalse(path.exists())
        self.assertTrue((self.dir / "a.written_off_1.json").is_file())
        self.assertTrue(foreign.is_file())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(P.main(["settle-unbound-speech", "--episode", "../x",
                                     "--transactions-root", str(root)]), 2)
            self.assertEqual(P.main(["settle-unbound-speech", "--episode", "E18",
                                     "--transactions-root", str(root / "missing")]), 0)

    def test_paid_entry_settles_before_its_own_budget_preflight(self) -> None:
        source = (ROOT / "lines" / "nalu" / "runtime" / "tools" / "paid_stage.sh").read_text(encoding="utf-8")
        settle = source.index("settle-unbound-speech --episode")
        self.assertLess(settle, source.index('"$LEDGER" --check'))
        self.assertIn('[ "$CHECK_ONLY" = 0 ] && [ -f "$AUDIO_PROVIDER" ]', source)


if __name__ == "__main__":
    unittest.main()
