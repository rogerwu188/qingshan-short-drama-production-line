"""The cross-shot check as the prompt-batch step runs it: per unit, before submission.

The whole point of the wiring is that the check does not need a new pipeline stage and does
not need the units to be generated in any particular order.  This test builds a minimal
prompt batch in a temporary directory (invented episode, invented shots, invented props),
runs the real ``digest``-side slice for each unit independently, and asserts:

  * each unit's slice is computed from its own shot pairs only;
  * the two units do not have to run in order, and running one does not change the other;
  * a missing ``shot_state_authoring.json`` is UNKNOWN — the digest still completes;
  * the blocking switch being off means no unit's slice can refuse anything.

Nothing here reads workflow/, nalu_runtime/, or the network.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from lines.nalu.runtime.tools import prompt_batch_qa as qa

ROOT = Path(__file__).resolve().parents[2]


def shot(shot_id, scene_id, action):
    return {"shot_id": shot_id, "scene_id": scene_id, "blocking": "",
            "prompt_spec": {"action": {"primary_action": action}, "cast": [], "props": []}}


CONTRACT = {
    "episode": "E14",
    "scene_states": [{"scene_id": "E14-S01", "location_id": "LOC-HALL", "time_id": "TIME-NIGHT"}],
    "shots": [shot("E14-S01-01", "E14-S01", "the lantern sits on the sill"),
              shot("E14-S01-02", "E14-S01", "she lifts the lantern"),
              shot("E14-S01-03", "E14-S01", "she crosses to the door")],
}

UNIT_A = {"unit_id": "E14-VU-001", "editorial_shot_ids": ["E14-S01-01", "E14-S01-02"]}
UNIT_B = {"unit_id": "E14-VU-002", "editorial_shot_ids": ["E14-S01-03"]}


def ledger(*records):
    return {"schema": "qingshan.authored_shot_state_attachment.v1", "episode": "E14",
            "source_contract_sha256": "a" * 64, "shots": list(records),
            "internal_transitions": []}


def record(shot_id, props):
    return {"shot_id": shot_id, "author": "fixture", "source_ref": "invented fixture",
            "persistent_state_contract": {
                "status": "PASS",
                "characters": [{"character_id": "C_A",
                                "entry_state": {"presence": "PRESENT", "posture": "STANDING",
                                                "injury": "NONE", "wardrobe": "W1",
                                                "position": "P1"},
                                "exit_state": {"presence": "PRESENT", "posture": "STANDING",
                                               "injury": "NONE", "wardrobe": "W1",
                                               "position": "P1"}}],
                "environment": {"entry_state": {"time": "T_NIGHT"},
                                "exit_state": {"time": "T_NIGHT"}}},
            "perception_state": {"on_screen": ["C_A"], "time_space": "SAME_CONTINUOUS",
                                 "characters": [{"character_id": "C_A",
                                                 "screen_slot": "LEFT_THIRD"}],
                                 "props": props}}


class PromptBatchWiringTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.pre = Path(self._tmp.name) / "preproduction"
        self.pre.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def write_state(self, records):
        (self.pre / "shot_state_authoring.json").write_text(
            json.dumps(ledger(*records), ensure_ascii=False), encoding="utf-8")

    def slice(self, unit, **kwargs):
        return qa.cross_shot_state_slice(
            CONTRACT, unit, state_path=self.pre / "shot_state_authoring.json", **kwargs)

    def test_a_missing_ledger_is_unknown_and_the_digest_still_completes(self):
        result = self.slice(UNIT_A)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertFalse(result["state_declared"])
        self.assertEqual(result["writer_items"], [])
        self.assertEqual(result["unknown_pairs"][0]["codes"],
                         sorted(result["rows"][0]["checks"]))

    def test_a_p1_is_listed_for_the_writer_and_blocks_nothing(self):
        self.write_state([record("E14-S01-01", [{"prop_id": "PROP-LANTERN",
                                                 "holder": "ON_GROUND"}]),
                          record("E14-S01-02", [{"prop_id": "PROP-LANTERN",
                                                 "holder": "C_A"}]),
                          record("E14-S01-03", [{"prop_id": "PROP-LANTERN",
                                                 "holder": "C_A",
                                                 "pickup_state": "INHERITED"}])])
        result = self.slice(UNIT_A)
        self.assertEqual(result["status"], "FINDINGS")
        self.assertEqual([item["severity"] for item in result["writer_items"]], ["P1"])
        self.assertFalse(result["blocking_enabled"])
        self.assertFalse(result["would_block"])
        self.assertEqual(result["tally"]["PROP_HELD_WITHOUT_PICKUP"], 1)

    def test_units_are_independent_and_order_does_not_matter(self):
        self.write_state([record("E14-S01-01", [{"prop_id": "PROP-LANTERN",
                                                 "holder": "ON_GROUND"}]),
                          record("E14-S01-02", [{"prop_id": "PROP-LANTERN",
                                                 "holder": "C_A"}]),
                          record("E14-S01-03", [{"prop_id": "PROP-LANTERN",
                                                 "holder": "C_A",
                                                 "pickup_state": "INHERITED"}])])
        b_first = self.slice(UNIT_B)
        a_first = self.slice(UNIT_A)
        a_again = self.slice(UNIT_A)
        self.assertEqual(json.dumps(a_first, sort_keys=True), json.dumps(a_again, sort_keys=True))
        # unit B's slice covers the pair entering its shot and nothing else
        self.assertEqual([row["to_shot_id"] for row in b_first["rows"]], ["E14-S01-03"])
        self.assertEqual([row["to_shot_id"] for row in a_first["rows"]], ["E14-S01-02"])
        # the entering pair of unit B inherits the holder: no new P1 there
        self.assertNotEqual(b_first["status"], "FINDINGS")

    def test_the_batch_summary_reports_state_absence_not_pass(self):
        summary = qa.cross_shot_summary(self.pre / "shot_state_authoring.json", [])
        self.assertFalse(summary["state_declared"])
        self.assertEqual(summary["state_source"], "UNKNOWN")
        self.assertFalse(summary["blocking_enabled"])

    def test_the_digest_does_not_add_a_failing_check(self):
        """The new report rides the digest; it never turns a deterministic check into FAIL."""
        source = (ROOT / "lines/nalu/runtime/tools/prompt_batch_qa.py").read_text(encoding="utf-8")
        self.assertIn('"cross_shot_state": cross_shot', source)
        self.assertIn('"cross_shot_state": cross_shot_summary', source)
        # deterministic_status still comes from the checks list alone
        self.assertIn('"deterministic_status": "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"',
                      source)


if __name__ == "__main__":
    unittest.main()
