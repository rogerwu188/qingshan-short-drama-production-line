"""Stale budget reservations must not double count spend the durable stores already hold.

Lab E02, 2026-10-24: the CLI's stdout verdict never carried ``reservation_result``, so
``nalu_pipeline.paid_step`` never learned the reservation id and never released it.  Spend 1069
plus 244 of reservations for already-bound units (VU-005 160, VU-008 76, BGM 8) left a 1500 cap
with 203 headroom instead of 431, and the quality redos were skipped.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
TOOL = TOOLS / "nalu_budget_ledger.py"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
B = importlib.import_module("nalu_budget_ledger")
EP = "E97"


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


class SettleTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        patcher = mock.patch.object(B, "ENGINE_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ledger = B.reservation_ledger_path(EP)
        self.ledger.parent.mkdir(parents=True)

    def _reserve(self, rid: str, credits: int, at: str, **owner) -> None:
        row = {"reservation_id": rid, "episode": EP, "credits": credits,
               "reserved_at": at, "released_at": None, **owner}
        with self.ledger.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def _video(self, key: str, at: str, credits: int, state: str = "SUBMITTED_TASK_ID_BOUND") -> None:
        d = self.root / "workflow" / "tasks" / B.VIDEO_TRANSACTION_DIRNAME / EP
        d.mkdir(parents=True, exist_ok=True)
        payload = {"task_key": key, "state": state, "intent_recorded_at": at, "estimated_credits": credits}
        if state == "SUBMITTED_TASK_ID_BOUND":
            payload["task_id"] = f"t-{key}"
        (d / f"{key}.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_legacy_reservation_covered_by_bound_unit_is_settled(self) -> None:
        self._reserve("a", 76, "2026-10-24T09:42:16Z")
        self._reserve("b", 160, "2026-10-24T09:59:22Z")
        self._video("VU-008", "2026-10-24T09:42:17Z", 76)
        self._video("VU-005", "2026-10-24T09:59:23Z", 160)
        scan = B.scan_reservations(EP)
        self.assertEqual(scan["active_credits"], 0)
        self.assertEqual({r["settle_reason"] for r in scan["settled_reservations"]},
                         {"COVERED_BY_RECORDED_SPEND"})

    def test_legacy_reservation_with_in_flight_intent_is_held(self) -> None:
        self._reserve("a", 160, "2026-10-24T09:59:22Z")
        self._video("VU-005", "2026-10-24T09:59:23Z", 160, state="INTENT_RECORDED")
        self.assertEqual(B.scan_reservations(EP)["active_credits"], 160)

    def test_legacy_reservation_not_yet_covered_is_held(self) -> None:
        self._reserve("a", 236, "2026-10-24T09:59:22Z")
        self._video("VU-005", "2026-10-24T09:59:23Z", 160)  # second unit not submitted yet
        self.assertEqual(B.scan_reservations(EP)["active_credits"], 236)

    def test_earlier_spend_never_covers_a_later_reservation(self) -> None:
        self._video("VU-001", "2026-10-24T09:00:00Z", 400)
        self._reserve("a", 160, "2026-10-24T09:59:22Z")
        self.assertEqual(B.scan_reservations(EP)["active_credits"], 160)

    def test_live_owner_keeps_its_reservation_even_when_covered(self) -> None:
        self._reserve("a", 160, "2026-10-24T09:59:22Z", owner_pid=os.getpid(),
                      owner_host=__import__("socket").gethostname())
        self._video("VU-005", "2026-10-24T09:59:23Z", 160)
        self.assertEqual(B.scan_reservations(EP)["active_credits"], 160)

    def test_ended_owner_settles_unless_a_post_may_be_in_flight(self) -> None:
        host = __import__("socket").gethostname()
        self._reserve("a", 160, "2026-10-24T09:59:22Z", owner_pid=_dead_pid(), owner_host=host)
        scan = B.scan_reservations(EP)
        self.assertEqual(scan["active_credits"], 0)  # step ended without charging
        self.assertEqual(scan["settled_reservations"][0]["settle_reason"], "OWNER_ENDED")
        self._video("VU-005", "2026-10-24T09:59:23Z", 160, state="INTENT_RECORDED")
        self.assertEqual(B.scan_reservations(EP)["active_credits"], 160)

    def test_other_host_owner_is_held(self) -> None:
        self._reserve("a", 160, "2026-10-24T09:59:22Z", owner_pid=_dead_pid(), owner_host="elsewhere")
        self.assertEqual(B.scan_reservations(EP)["active_credits"], 160)

    def test_release_is_append_only_and_carries_reason(self) -> None:
        self._reserve("a", 76, "2026-10-24T09:42:16Z")
        before = self.ledger.read_text(encoding="utf-8")
        B.release_reservation(EP, "a", reason="COVERED_BY_RECORDED_SPEND", evidence={"covered_credits": 76})
        after = self.ledger.read_text(encoding="utf-8")
        self.assertTrue(after.startswith(before))
        row = json.loads(after.splitlines()[-1])
        self.assertEqual((row["release_reason"], row["auto_release"]), ("COVERED_BY_RECORDED_SPEND", True))
        self.assertEqual(B.scan_reservations(EP)["active_credits"], 0)

    def test_new_reservation_records_its_owner(self) -> None:
        with mock.patch.dict(os.environ, {B.RESERVATION_OWNER_ENV: "4242"}):
            owner = B._reservation_owner()
        self.assertEqual(owner["owner_pid"], 4242)
        self.assertTrue(owner["owner_host"])
        self.assertEqual(Decimal(0), Decimal(str(B.scan_reservations(EP)["active_credits"])))


class CliVerdictCarriesReservationId(unittest.TestCase):
    """nalu_pipeline.paid_step parses the stdout line; the id must be on it or it never releases."""

    def test_stdout_has_reservation_id(self) -> None:
        episode = "E98"
        resv = ROOT / "workflow" / "nalu" / episode
        self.addCleanup(shutil.rmtree, resv, True)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ledger = Path(tmp.name) / "ledger.json"
        proc = subprocess.run(
            [sys.executable, "-I", str(TOOL), "--check", "--episode", episode, "--planned-credits", "10",
             "--cap", "8000", "--ledger", str(ledger), "--reserve"],
            capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        verdict = json.loads(proc.stdout.strip().splitlines()[-1])
        rid = (verdict.get("reservation_result") or {}).get("reservation_id")
        self.assertTrue(rid, verdict)
        row = json.loads((resv / "BUDGET_RESERVATION.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(row["reservation_id"], rid)
        self.assertEqual(row["owner_pid"], os.getpid())  # the caller owns it, and it is alive


if __name__ == "__main__":
    unittest.main()
