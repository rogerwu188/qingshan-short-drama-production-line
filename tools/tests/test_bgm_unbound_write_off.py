"""A selective-BGM music POST that bound no task id is written off once and gets one new attempt.

Fleet devices 0891 E15 and 1144 E13, 2026-11-18: the music POST came back without a task id, the
transaction stayed RESPONSE_LOST (MISSING_TASK_ID) and every paid re-entry failed the budget preflight
with BGM_UNRESOLVED_TRANSACTIONS:1.  The speech write-off (ruling A) did not cover music.
"""
from __future__ import annotations

import contextlib
import importlib
import io
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
BGM = importlib.import_module("nalu_selective_bgm")

T0 = datetime(2026, 11, 18, 5, 58, 0, tzinfo=timezone.utc)


class UnboundBgmWriteOffTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "giggle_bgm_transactions"
        self.dir = self.root / "E15"
        self.dir.mkdir(parents=True)

    def _tx(self, name: str = "e17f1c51cd651562.json", state: str = "RESPONSE_LOST", **extra) -> Path:
        path = self.dir / name
        payload = {"schema": P.SCHEMA, "transaction_id": f"id-{name}-{state}", "state": state,
                   "capability": P.BGM_CAPABILITY, "intent_recorded_at": "2026-11-18T05:57:30Z",
                   "response_lost_at": "2026-11-18T05:58:00Z", "transport_error_type": "MISSING_TASK_ID",
                   "provider_post_count": 1, "request": {"prompt_sha256": "a" * 64, "instrumental": True},
                   **extra}
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_speech_settlement_still_ignores_music(self) -> None:
        path = self._tx()
        self.assertEqual(P.settle_unbound_speech([path], now=T0 + timedelta(hours=1)), [])
        self.assertTrue(path.is_file())

    def test_recent_loss_waits_for_the_grace_period(self) -> None:
        path = self._tx()
        rows = P.settle_unbound_speech([path], now=T0 + timedelta(seconds=120), capability=P.BGM_CAPABILITY)
        self.assertEqual([row["status"] for row in rows], ["PENDING_GRACE"])
        self.assertEqual(rows[0]["eligible_at"], "2026-11-18T06:08:00Z")
        self.assertTrue(path.is_file())

    def test_after_grace_the_request_is_archived_and_the_key_is_a_new_submission(self) -> None:
        path = self._tx()
        rows = P.settle_unbound_speech([path], now=T0 + timedelta(seconds=601), capability=P.BGM_CAPABILITY)
        self.assertEqual([row["status"] for row in rows], ["WRITTEN_OFF_RETRY_OPEN"])
        self.assertFalse(path.exists())
        archive = self.dir / "e17f1c51cd651562.written_off_1.json"
        saved = json.loads(archive.read_text(encoding="utf-8"))
        self.assertEqual(saved["state"], P.WRITTEN_OFF_STATE)
        self.assertEqual(saved["written_off"]["previous_state"], "RESPONSE_LOST")

        class Paths:
            tx = self.dir
        state, failures = BGM._generation_transaction_state(
            Paths, {"source_key": "e17f1c51cd651562", "prompt_sha256": "a" * 64})
        self.assertEqual((state, failures), ("NEW_SUBMISSION", []))

    def test_second_loss_of_the_same_key_stays_blocked(self) -> None:
        path = self._tx()
        P.settle_unbound_speech([path], now=T0 + timedelta(hours=1), capability=P.BGM_CAPABILITY)
        again = self._tx(transaction_id="second")
        rows = P.settle_unbound_speech([again], now=T0 + timedelta(hours=2), capability=P.BGM_CAPABILITY)
        self.assertEqual([row["status"] for row in rows], ["ALREADY_WRITTEN_OFF_ONCE"])
        self.assertTrue(again.is_file())

    def test_bound_and_completed_music_is_not_touched(self) -> None:
        bound = self._tx("bound.json", state="TASK_ID_BOUND_QUERY_PENDING", task_id="t-1")
        done = self._tx("done.json", state="TERMINAL_COMPLETED", task_id="t-2")
        rows = P.settle_unbound_speech([bound, done], now=T0 + timedelta(hours=1), capability=P.BGM_CAPABILITY)
        self.assertEqual(rows, [])
        self.assertTrue(bound.is_file() and done.is_file())

    def test_ledger_counts_the_written_off_request_and_stops_blocking(self) -> None:
        path = self._tx()
        before = B.scan_non_video_spend("E15", bgm_transactions_dir=self.dir)
        self.assertEqual(len(before["bgm_unresolved_transactions"]), 1)
        P.settle_unbound_speech([path], now=T0 + timedelta(hours=1), capability=P.BGM_CAPABILITY)
        after = B.scan_non_video_spend("E15", bgm_transactions_dir=self.dir)
        self.assertEqual(after["bgm_unresolved_transactions"], [])
        self.assertEqual(Decimal(str(after["bgm_credits"])) - Decimal(str(before["bgm_credits"])),
                         B.BGM_PROVISIONAL_CREDITS_PER_TASK)
        self.assertEqual([row["statement_status"] for row in after["bgm_rows"]],
                         ["WRITTEN_OFF_UNBOUND_UNIT_PRICE"])
        evidence = [row for row in B._spend_evidence("E15", self.dir)
                    if row["source"].endswith(".written_off_1.json")]
        self.assertEqual([(row["credits"], row["in_flight"]) for row in evidence],
                         [(B.BGM_PROVISIONAL_CREDITS_PER_TASK, False)])

    def test_cli_settles_one_episode_in_both_store_layouts(self) -> None:
        path = self._tx()
        scoped = self.root / "SERIES_A" / "E15"
        scoped.mkdir(parents=True)
        scoped_tx = scoped / "k.json"
        scoped_tx.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        other = self.root / "E16"
        other.mkdir()
        foreign = other / "k.json"
        foreign.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = P.main(["settle-unbound-bgm", "--episode", "E15", "--transactions-root", str(self.root)])
        self.assertEqual(rc, 0)
        result = json.loads(buffer.getvalue())
        self.assertEqual([row["status"] for row in result["rows"]], ["WRITTEN_OFF_RETRY_OPEN"] * 2)
        self.assertFalse(path.exists() or scoped_tx.exists())
        self.assertTrue(foreign.is_file())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(P.main(["settle-unbound-bgm", "--episode", "../x",
                                     "--transactions-root", str(self.root)]), 2)

    def test_both_paid_entries_settle_music_before_the_budget_check(self) -> None:
        tools = ROOT / "lines" / "nalu" / "runtime" / "tools"
        source = (tools / "nalu_pipeline.py").read_text(encoding="utf-8")
        body = source[source.index("    def budget_check("):source.index("    def budget_release(")]
        self.assertLess(body.index("self.settle_unbound_bgm(label=label)"), body.index("BUDGET_LEDGER"))
        shell = (tools / "paid_stage.sh").read_text(encoding="utf-8")
        self.assertLess(shell.index("settle-unbound-bgm --episode"), shell.index('"$LEDGER" --check'))


if __name__ == "__main__":
    unittest.main()
