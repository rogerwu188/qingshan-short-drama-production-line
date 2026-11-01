"""The profile switch: E01-E13 untouched, E14+ selected, nothing blocking by default."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.writer_capability import (
    CONFIG_PATH,
    LEGACY,
    SELECTED,
    applies,
    inputs,
    load_config,
    profile_for,
    sealed_binding,
    stage_summary,
)

ROOT = Path(__file__).resolve().parents[2]

SEALED = ["E01", "E02", "E03", "E04", "E05", "E06", "E07", "E08", "E09", "E10", "E11",
          "E12", "E13"]


class ProfileTests(unittest.TestCase):
    def test_the_committed_config_selects_from_e14(self):
        config = load_config()
        self.assertTrue(config["enabled"])
        self.assertEqual(config["enabled_from_episode"], "E14")

    def test_every_sealed_episode_stays_legacy(self):
        config = load_config()
        for episode in SEALED:
            self.assertEqual(profile_for(episode, config, {})["profile"], LEGACY, episode)

    def test_e14_and_later_are_selected(self):
        config = load_config()
        for episode in ("E14", "E15", "E70"):
            self.assertEqual(profile_for(episode, config, {})["profile"], SELECTED, episode)

    def test_the_switch_reports_why(self):
        config = load_config()
        self.assertEqual(profile_for("E11", config, {})["reason"], "SEALED_BEFORE_THIS_CAPABILITY")
        self.assertEqual(profile_for("E14", config, {})["reason"], "AT_OR_AFTER_E14")

    def test_the_env_override_can_turn_it_off_and_on(self):
        config = load_config()
        self.assertEqual(profile_for("E14", config, {"NALU_WRITER_CAPABILITY": "off"})["profile"],
                         LEGACY)
        self.assertEqual(profile_for("E11", config, {"NALU_WRITER_CAPABILITY": "on"})["profile"],
                         LEGACY, "a sealed episode is never re-judged, even with the override")

    def test_a_disabled_config_is_legacy_for_everyone(self):
        config = {**load_config(), "enabled": False}
        self.assertEqual(profile_for("E30", config, {})["profile"], LEGACY)

    def test_a_missing_config_is_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(Path(tmp) / "absent.json")
        self.assertEqual(profile_for("E30", config, {})["profile"], LEGACY)
        self.assertTrue(config["missing_config"])

    def test_applies_is_the_single_decision(self):
        config = load_config()
        self.assertFalse(applies("E13", config, {}))
        self.assertTrue(applies("E14", config, {}))

    def test_an_invalid_episode_name_raises(self):
        with self.assertRaises(SystemExit):
            profile_for("episode-14", load_config(), {})


class NothingBlocksByDefaultTests(unittest.TestCase):
    def test_every_blocking_switch_is_off(self):
        blocking = load_config()["blocking"]
        for name, value in blocking.items():
            if name == "note":
                continue
            self.assertIs(value, False, name)

    def test_a_missing_input_does_not_block(self):
        summary = stage_summary("E14", config=load_config(), environ={})
        self.assertEqual(summary["status"], "OWED")
        self.assertEqual(summary["blocks_stage"], [])
        self.assertIn("arc_ledger", summary["owed"])

    def test_legacy_summary_is_not_applicable(self):
        summary = stage_summary("E12", config=load_config(), environ={})
        self.assertEqual(summary["status"], "NOT_APPLICABLE_LEGACY_PROFILE")
        self.assertEqual(summary["profile"], LEGACY)
        self.assertNotIn("owed", summary)


class InputTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name: str, payload: dict) -> Path:
        path = self.tmp / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_a_broken_arc_ledger_is_reported_with_its_failures(self):
        ledger = self._write("arc.json", {"schema": "x", "arc_id": "", "episode_window": [],
                                          "episodes": [], "hooks": []})
        recorded = inputs("E14", arc_ledger=ledger, config=load_config())
        self.assertEqual(recorded["inputs"]["arc_ledger"]["status"], "FAIL")
        self.assertTrue(recorded["inputs"]["arc_ledger"]["failures"])
        self.assertEqual(recorded["blocks_stage"], [])

    def test_a_disposition_for_another_episode_is_flagged(self):
        disposition = self._write("disp.json", {
            "schema": "qingshan.adaptation_disposition.v1", "episode": "E15",
            "chapter": "ch0001",
            "beats": [{"beat_id": "B01", "category": "condensed", "source_ref": "ch0001",
                       "reason": "kept the causal step"}]})
        recorded = inputs("E14", adaptation_disposition=disposition, config=load_config())
        self.assertFalse(recorded["inputs"]["adaptation_disposition"]["matches_episode"])

    def test_an_incomplete_script_review_is_recorded_as_unanswered(self):
        report = self._write("review.json", {"review_state": "INCOMPLETE",
                                             "unanswered": ["CP-01-S01"],
                                             "narrative_sha256": "a" * 64})
        recorded = inputs("E14", script_review_report=report, config=load_config())
        row = recorded["inputs"]["script_review"]
        self.assertEqual(row["status"], "INCOMPLETE")
        self.assertFalse(row["answered"])

    def test_open_rule8_items_are_recorded(self):
        report = self._write("r8.json", {"status": "PENDING_WRITER_RESPONSE",
                                         "open_items": ["R8A"], "invalid_items": []})
        recorded = inputs("E14", rule8_report=report, config=load_config())
        self.assertEqual(recorded["inputs"]["rule8_response"]["open_items"], ["R8A"])


class BlockingSwitchTests(unittest.TestCase):
    def test_a_switch_turned_on_does_block_that_input_only(self):
        config = {**load_config(), "blocking": {"missing_inputs": True,
                                                "open_rule8_items": False,
                                                "unanswered_script_review": False,
                                                "ledger_failures": False}}
        summary = stage_summary("E14", config=config, environ={})
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertIn("ARC_LEDGER", summary["blocks_stage"])

    def test_the_committed_config_never_blocks(self):
        summary = stage_summary("E14", config=load_config(), environ={})
        self.assertNotEqual(summary["status"], "BLOCKED")


class SealedBindingTests(unittest.TestCase):
    def test_matching_shas(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            narrative = Path(tmp) / "n.md"
            narrative.write_text("## S01\n\ntext\n", encoding="utf-8")
            sha = hashlib.sha256(narrative.read_bytes()).hexdigest()
            result = sealed_binding({"narrative_sha256": sha}, narrative)
        self.assertEqual(result["status"], "MATCH")
        self.assertTrue(result["matches"])

    def test_a_revision_after_the_review_is_caught(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            narrative = Path(tmp) / "n.md"
            narrative.write_text("## S01\n\nrevised\n", encoding="utf-8")
            sha = hashlib.sha256(b"## S01\n\noriginal\n").hexdigest()
            result = sealed_binding({"narrative_sha256": sha}, narrative)
        self.assertEqual(result["status"], "SEALED_NARRATIVE_CHANGED_SINCE_REVIEW")
        self.assertFalse(result["matches"])

    def test_no_review_is_stated_plainly(self):
        self.assertEqual(sealed_binding(None, None)["status"], "NO_SCRIPT_REVIEW")

    def test_a_review_bound_to_nothing_is_stated_plainly(self):
        result = sealed_binding({"review_state": "COMPLETE"}, None)
        self.assertEqual(result["status"], "REVIEW_NOT_BOUND_TO_A_NARRATIVE")


class ConfigContentTests(unittest.TestCase):
    def test_the_config_names_the_four_inputs_and_their_validators(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        names = sorted(config["inputs"])
        self.assertEqual(names, ["adaptation_disposition", "arc_ledger", "rule8_response",
                                "script_review"])
        for row in config["inputs"].values():
            self.assertIn("validator", row)

    def test_the_config_lists_e01_to_e13_as_sealed(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(config["profiles"]["LEGACY"]["sealed_episodes"], SEALED)

    def test_the_config_carries_no_quota(self):
        text = CONFIG_PATH.read_text(encoding="utf-8").lower()
        for forbidden in ("hooks_per_episode", "fight_every", "min_hooks", "quota"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
