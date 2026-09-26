"""Offline unit tests for lines/nalu/runtime/tools/nalu_tail_ad_opt_in.py.

Fully offline: fake say/sleep_fn/now_fn so nothing here ever really sleeps or
prints, matching the injectable-clock design so CI stays fast.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import nalu_tail_ad_opt_in as opt_in  # noqa: E402


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.t = start
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


class RunOptInTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.prompts = self.root / "prompts"
        self.ledger = self.root / "transactions" / "opt_in_ledger.json"
        self.manifest_path = self.root / "E08_manifest_v1.json"
        self.manifest_path.write_text(json.dumps({"schema": "nalu.writer_manifest.v1"}), encoding="utf-8")
        self.policy_path = self.root / "policy.json"
        self.said: list[str] = []

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, *, clock: FakeClock, answer_writer=None, deadline_seconds: float = 60.0):
        def sleep_fn(seconds: float) -> None:
            clock.sleep(seconds)
            if answer_writer is not None:
                answer_writer(clock)

        return opt_in.run_opt_in(
            "E08", prompts_dir=self.prompts, answer_dir=self.prompts, policy_path=self.policy_path,
            ledger_path=self.ledger, manifest_path=self.manifest_path, say=self.said.append,
            deadline_seconds=deadline_seconds, poll_interval_seconds=2.0,
            sleep_fn=sleep_fn, now_fn=clock.now,
        )

    def test_timeout_defaults_to_none_and_writes_manifest_once(self) -> None:
        clock = FakeClock()
        decision = self._run(clock=clock)
        self.assertEqual(decision, {"answer": "NONE", "reason": "TIMEOUT_DEFAULT"})
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["ad_slot"]["answer"], "NONE")
        self.assertEqual(manifest["ad_slot"]["reason"], "TIMEOUT_DEFAULT")
        ledger = json.loads(self.ledger.read_text(encoding="utf-8"))
        self.assertEqual(len(ledger["entries"]), 1)
        self.assertEqual(ledger["entries"][0]["event"], "TIMEOUT_DEFAULT")

    def test_timeout_honours_policy_default_other_than_none(self) -> None:
        self.policy_path.write_text(json.dumps({"ask": True, "default": "INBOX:demo_sku"}), encoding="utf-8")
        clock = FakeClock()
        decision = self._run(clock=clock)
        self.assertEqual(decision["answer"], "INBOX:demo_sku")
        self.assertEqual(decision["reason"], "TIMEOUT_DEFAULT")

    def test_answered_in_time(self) -> None:
        clock = FakeClock()

        def write_answer(_clock: FakeClock) -> None:
            answer_path = self.prompts / "E08_AD_ANSWER.json"
            if not answer_path.is_file():
                answer_path.parent.mkdir(parents=True, exist_ok=True)
                answer_path.write_text(json.dumps({"episode": "E08", "answer": "INBOX:giggle_tail5s"}),
                                       encoding="utf-8")

        decision = self._run(clock=clock, answer_writer=write_answer)
        self.assertEqual(decision, {"answer": "INBOX:giggle_tail5s", "reason": "ANSWERED"})
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["ad_slot"]["sku"], "giggle_tail5s")

    def test_wrong_episode_answer_rejected(self) -> None:
        clock = FakeClock()

        def write_answer(_clock: FakeClock) -> None:
            answer_path = self.prompts / "E08_AD_ANSWER.json"
            if not answer_path.is_file():
                answer_path.parent.mkdir(parents=True, exist_ok=True)
                answer_path.write_text(json.dumps({"episode": "E07", "answer": "INBOX:giggle_tail5s"}),
                                       encoding="utf-8")

        decision = self._run(clock=clock, answer_writer=write_answer)
        self.assertEqual(decision, {"answer": "NONE", "reason": "ANSWER_EPISODE_MISMATCH"})
        ledger = json.loads(self.ledger.read_text(encoding="utf-8"))
        self.assertEqual(ledger["entries"][0]["event"], "ANSWER_EPISODE_MISMATCH")

    def test_policy_skip_no_ask_never_writes_prompt(self) -> None:
        self.policy_path.write_text(json.dumps({"ask": False, "default": "NONE"}), encoding="utf-8")
        clock = FakeClock()
        decision = self._run(clock=clock)
        self.assertEqual(decision, {"answer": "NONE", "reason": "POLICY_SKIP_NO_ASK"})
        self.assertFalse((self.prompts / "E08_AD_PROMPT.json").exists())
        self.assertEqual(clock.sleeps, [])  # never entered the poll loop

    def test_manifest_ad_slot_written_exactly_once(self) -> None:
        clock1 = FakeClock()
        self._run(clock=clock1)
        first = json.loads(self.manifest_path.read_text(encoding="utf-8"))["ad_slot"]
        (self.prompts / "E08_AD_ANSWER.json").parent.mkdir(parents=True, exist_ok=True)
        (self.prompts / "E08_AD_ANSWER.json").write_text(
            json.dumps({"episode": "E08", "answer": "INBOX:giggle_tail5s"}), encoding="utf-8")
        clock2 = FakeClock()
        opt_in._write_manifest_ad_slot(self.manifest_path, "E08",
                                       {"answer": "INBOX:giggle_tail5s", "reason": "ANSWERED"}, opt_in.now())
        second = json.loads(self.manifest_path.read_text(encoding="utf-8"))["ad_slot"]
        self.assertEqual(first, second)  # second write was a no-op — already present


class RecheckBeforeS7Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.prompts = self.root / "prompts"
        self.ledger = self.root / "opt_in_ledger.json"
        self.prompts.mkdir(parents=True)
        self.said: list[str] = []

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_late_answer_accepted_before_s7(self) -> None:
        (self.prompts / "E08_AD_ANSWER.json").write_text(
            json.dumps({"episode": "E08", "answer": "INBOX:giggle_tail5s"}), encoding="utf-8")
        current = {"answer": "NONE", "reason": "TIMEOUT_DEFAULT"}
        decision = opt_in.recheck_before_s7("E08", answer_dir=self.prompts, ledger_path=self.ledger,
                                            current_decision=current, say=self.said.append)
        self.assertEqual(decision["answer"], "INBOX:giggle_tail5s")
        self.assertEqual(decision["reason"], "LATE_ANSWER_ACCEPTED_BEFORE_S7")

    def test_non_timeout_decision_is_never_rechecked(self) -> None:
        current = {"answer": "NONE", "reason": "ANSWERED"}
        decision = opt_in.recheck_before_s7("E08", answer_dir=self.prompts, ledger_path=self.ledger,
                                            current_decision=current, say=self.said.append)
        self.assertEqual(decision, current)

    def test_no_late_answer_keeps_current(self) -> None:
        current = {"answer": "NONE", "reason": "TIMEOUT_DEFAULT"}
        decision = opt_in.recheck_before_s7("E08", answer_dir=self.prompts, ledger_path=self.ledger,
                                            current_decision=current, say=self.said.append)
        self.assertEqual(decision, current)


if __name__ == "__main__":
    unittest.main()
