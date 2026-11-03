"""Cross-shot state + perceived state: the three states a row can be in, and six rules.

Every fixture here is invented for this file: invented shot ids, invented prop ids, invented
action text.  No episode text from any production is read, and nothing reaches the network or
workflow/.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.cross_shot_state_perception import (
    CONFIG_PATH,
    evaluate,
    load_config,
    load_state,
    shots_from_contract,
)
from tools.event_boundary_continuity_contract import (
    PERCEPTION_PROP_HOLDER_SENTINELS,
    PERCEPTION_TIME_SPACE_VALUES,
    PROP_PICKUP_STATES,
    validate_perception_state,
)

ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- fixtures


def ledger_shot(shot_id, *, characters=("C_A",), props=None, on_screen=None,
                action_repeat=None, time_space="SAME_CONTINUOUS", jump_cut=False,
                positions=None, state_suffix="", roster=None):
    """One authored shot record: a persistent contract plus a perception block.

    ``characters`` is the entitlement roster (whose states the shot declares); ``on_screen``
    is what the audience actually sees.  They differ in the off-screen cases below.
    """
    state = {"presence": "PRESENT", "posture": f"STANDING{state_suffix}",
             "injury": "NONE", "wardrobe": "W1", "position": "P1"}
    record = {
        "shot_id": shot_id,
        "author": "fixture author",
        "source_ref": "invented fixture",
        "persistent_state_contract": {
            "status": "PASS",
            "characters": [{"character_id": cid, "entry_state": dict(state),
                            "exit_state": dict(state)} for cid in (roster if roster is not None else characters)],
            "environment": {"entry_state": {"time": "T_NIGHT"},
                            "exit_state": {"time": "T_NIGHT"}},
        },
        "perception_state": {
            "on_screen": list(characters) if on_screen is None else on_screen,
            "characters": positions if positions is not None else [
                {"character_id": cid, "screen_slot": "LEFT_THIRD",
                 "eyeline_target": "" } for cid in characters],
            "props": props or [],
            "time_space": time_space,
            "action_repeat": action_repeat or {"status": "NEW"},
            "jump_cut": jump_cut,
        },
    }
    return record


def state_file(records):
    return {"schema": "qingshan.authored_shot_state_attachment.v1", "episode": "E14",
            "source_contract_sha256": "f" * 64, "shots": list(records), "internal_transitions": []}


def contract(scenes, shots):
    return {"episode": "E14", "scene_states": scenes, "shots": shots}


def shot(shot_id, scene_id, action, *, device=None, blocking=""):
    return {"shot_id": shot_id, "scene_id": scene_id, "blocking": blocking,
            "prompt_spec": {"action": {"primary_action": action},
                            "cast": [], "props": []},
            "incoming_transition_contract": {"transition_device": device} if device else {}}


SCENES = [{"scene_id": "E14-S01", "location_id": "LOC-HALL", "time_id": "TIME-NIGHT"},
          {"scene_id": "E14-S02", "location_id": "LOC-HALL", "time_id": "TIME-NIGHT"}]


def evaluate_pair(state, contract_obj, **kwargs):
    return evaluate(shots_from_contract(contract_obj), state=state, **kwargs)


# --------------------------------------------------------------------------- vocabulary


class VocabularyTests(unittest.TestCase):
    """The new dimensions live in the EXISTING ledger module — one definition."""

    def test_the_five_dimensions_are_declared_where_the_ledger_is(self):
        self.assertEqual(PERCEPTION_PROP_HOLDER_SENTINELS,
                         {"ON_GROUND", "OFF_SCREEN", "NOT_PRESENT"})
        self.assertEqual(PROP_PICKUP_STATES,
                         {"HELD", "PICKED_UP_IN_SHOT", "PUT_DOWN_IN_SHOT", "INHERITED"})
        self.assertEqual(PERCEPTION_TIME_SPACE_VALUES,
                         {"SAME_CONTINUOUS", "DECLARED_TIME_JUMP", "DECLARED_SCENE_CHANGE"})

    def test_a_bad_vocabulary_value_is_named_not_absorbed(self):
        record = ledger_shot("E14-S01-01", time_space="SAME_ISH", jump_cut=False)
        record["perception_state"]["props"] = [{"prop_id": "PROP-X", "holder": "ON_FLOOR",
                                                "pickup_state": "HOLDING"}]
        record["perception_state"]["action_repeat"] = {"status": "SAME"}
        failures = validate_perception_state(record, uid="E14-S01-01")
        self.assertIn("PERCEPTION_TIME_SPACE_INVALID:E14-S01-01:SAME_ISH", failures)
        self.assertIn("PERCEPTION_PICKUP_STATE_INVALID:E14-S01-01:HOLDING", failures)
        self.assertIn("PERCEPTION_ACTION_REPEAT_INVALID:E14-S01-01:SAME", failures)

    def test_a_declared_repeat_needs_a_reason(self):
        record = ledger_shot("E14-S01-01", action_repeat={"status": "REPEAT", "reason": ""})
        self.assertIn("PERCEPTION_ACTION_REPEAT_REASON_MISSING:E14-S01-01",
                      validate_perception_state(record, uid="E14-S01-01"))

    def test_an_absent_block_is_not_a_coverage_requirement(self):
        record = {"shot_id": "E14-S01-01", "author": "x", "source_ref": "y"}
        self.assertEqual(validate_perception_state(record, uid="E14-S01-01"), [])

    def test_a_holder_that_is_neither_sentinel_nor_character_is_unknown(self):
        state = state_file([ledger_shot(
            "E14-S01-01", props=[{"prop_id": "PROP-X", "holder": "SOMEONE_ELSE"}]),
            ledger_shot("E14-S01-02", props=[{"prop_id": "PROP-X", "holder": "C_A"}])])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "she waits"),
                                shot("E14-S01-02", "E14-S01", "she lifts it")])
        report = evaluate_pair(state, obj)
        row = report["rows"][0]
        self.assertEqual(row["status"], "UNKNOWN")
        self.assertEqual(row["checks"]["PROP_HELD_WITHOUT_PICKUP"], "UNKNOWN")


# --------------------------------------------------------------------------- P1 prop held


class PropHeldTests(unittest.TestCase):
    def test_held_with_no_pickup_and_no_inheritance_is_a_P1_candidate(self):
        state = state_file([
            ledger_shot("E14-S01-01", props=[{"prop_id": "PROP-BOWL", "holder": "ON_GROUND"}]),
            ledger_shot("E14-S01-02", props=[{"prop_id": "PROP-BOWL", "holder": "C_A"}]),
        ])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "the bowl sits on the stones"),
                                shot("E14-S01-02", "E14-S01", "she raises it overhead")])
        report = evaluate_pair(state, obj)
        row = report["rows"][0]
        self.assertEqual(row["checks"]["PROP_HELD_WITHOUT_PICKUP"], "FINDING")
        self.assertEqual(report["status"], "FINDINGS")
        item = report["writer_items"][0]
        self.assertEqual(item["prop_id"], "PROP-BOWL")
        self.assertEqual(item["severity"], "P1")
        self.assertEqual(item["kind"], "BLOCKING_CANDIDATE")
        # both shots cited
        self.assertEqual((item["from_shot_id"], item["to_shot_id"]),
                         ("E14-S01-01", "E14-S01-02"))

    def test_the_real_production_state_is_report_only_by_default(self):
        self.assertFalse(load_config()["blocking"])
        state = state_file([
            ledger_shot("E14-S01-01", props=[{"prop_id": "PROP-BOWL", "holder": "ON_GROUND"}]),
            ledger_shot("E14-S01-02", props=[{"prop_id": "PROP-BOWL", "holder": "C_A"}]),
        ])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "the bowl sits"),
                                shot("E14-S01-02", "E14-S01", "she raises it")])
        report = evaluate_pair(state, obj)
        self.assertFalse(report["blocking_enabled"])
        self.assertFalse(report["would_block"])
        # the line owner's switch is the only thing that could make it refuse
        blocked = evaluate_pair(state, obj, config={"blocking": True})
        self.assertTrue(blocked["would_block"])

    def test_a_missing_config_reports_and_never_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(Path(tmp) / "absent.json")
        self.assertFalse(config["blocking"])
        self.assertTrue(config["missing_config"])

    def test_the_committed_config_ships_blocking_off(self):
        committed = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertIs(committed["blocking"], False)

    def test_legacy_props_map_is_read_when_the_new_block_is_absent(self):
        """A prop declared only through persistent_state_contract.props is still compared."""
        state = state_file([
            {"shot_id": "E14-S01-01", "source_ref": "fixture", "author": "a",
             "persistent_state_contract": {"props": {"entry_state": {"PROP-ROPE": "ON_GROUND"}}}},
            {"shot_id": "E14-S01-02", "source_ref": "fixture", "author": "a",
             "persistent_state_contract": {"props": {"entry_state": {"PROP-ROPE": "C_A"}}}},
        ])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "the rope lies coiled"),
                                shot("E14-S01-02", "E14-S01", "she knots it")])
        report = evaluate_pair(state, obj)
        self.assertEqual(report["rows"][0]["checks"]["PROP_HELD_WITHOUT_PICKUP"], "FINDING")


    def test_an_unreadable_prop_row_does_not_mask_a_real_finding(self):
        state = state_file([
            ledger_shot("E14-S01-01", props=[
                {"prop_id": "PROP-BOWL", "holder": "ON_GROUND"},
                {"prop_id": "PROP-BAG", "holder": "WHATEVER"}]),
            ledger_shot("E14-S01-02", props=[
                {"prop_id": "PROP-BOWL", "holder": "C_A"},
                {"prop_id": "PROP-BAG", "holder": "WHATEVER"}]),
        ])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "the bowl sits"),
                                shot("E14-S01-02", "E14-S01", "she raises the bowl")])
        report = evaluate_pair(state, obj)
        self.assertEqual(report["rows"][0]["checks"]["PROP_HELD_WITHOUT_PICKUP"], "FINDING")
        self.assertEqual([f["prop_id"] for f in report["findings"]
                          if f["code"] == "PROP_HELD_WITHOUT_PICKUP"], ["PROP-BOWL"])


# --------------------------------------------------------------------------- P2 retake


class PropRetakeTests(unittest.TestCase):
    def test_put_down_then_held_without_a_re_take_is_flagged(self):
        state = state_file([
            ledger_shot("E14-S01-01", props=[{"prop_id": "PROP-KEY", "holder": "C_A",
                                              "pickup_state": "PUT_DOWN_IN_SHOT"}]),
            ledger_shot("E14-S01-02", props=[{"prop_id": "PROP-KEY", "holder": "C_A",
                                              "pickup_state": "HELD"}]),
        ])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "she sets it on the ledge"),
                                shot("E14-S01-02", "E14-S01", "she turns the key")])
        report = evaluate_pair(state, obj)
        codes = [finding["code"] for finding in report["findings"]]
        self.assertIn("PROP_RETAKE_UNDECLARED", codes)

    def test_a_declared_re_take_clears_the_flag(self):
        state = state_file([
            ledger_shot("E14-S01-01", props=[{"prop_id": "PROP-KEY", "holder": "C_A",
                                              "pickup_state": "PUT_DOWN_IN_SHOT"}]),
            ledger_shot("E14-S01-02", props=[{"prop_id": "PROP-KEY", "holder": "C_A",
                                              "pickup_state": "PICKED_UP_IN_SHOT"}]),
        ])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "she sets it down"),
                                shot("E14-S01-02", "E14-S01", "she takes it again")])
        report = evaluate_pair(state, obj)
        self.assertNotIn("PROP_RETAKE_UNDECLARED",
                         [finding["code"] for finding in report["findings"]])


# --------------------------------------------------------------------------- merge


class ActionRepeatTests(unittest.TestCase):
    def test_identical_action_and_state_proposes_a_merge(self):
        state = state_file([ledger_shot("E14-S01-01"), ledger_shot("E14-S01-02")])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "she crosses the hall"),
                                shot("E14-S01-02", "E14-S01", "she crosses the hall")])
        report = evaluate_pair(state, obj)
        item = next(i for i in report["writer_items"]
                    if i["code"] == "ACTION_REPEAT_WITHOUT_STATE_CHANGE")
        self.assertEqual(item["kind"], "MERGE_PROPOSAL")
        self.assertEqual(item["severity"], "MERGE")

    def test_a_declared_repeat_with_a_reason_is_legal(self):
        state = state_file([
            ledger_shot("E14-S01-01"),
            ledger_shot("E14-S01-02", action_repeat={"status": "REPEAT",
                                                     "reason": "the second attempt is refused again"}),
        ])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "she crosses the hall"),
                                shot("E14-S01-02", "E14-S01", "she crosses the hall")])
        report = evaluate_pair(state, obj)
        self.assertNotIn("ACTION_REPEAT_WITHOUT_STATE_CHANGE",
                         [finding["code"] for finding in report["findings"]])

    def test_a_state_change_clears_the_repeat(self):
        state = state_file([
            ledger_shot("E14-S01-01"),
            ledger_shot("E14-S01-02", state_suffix="_THEN_STOPS"),
        ])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "she crosses the hall"),
                                shot("E14-S01-02", "E14-S01", "she crosses the hall")])
        report = evaluate_pair(state, obj)
        self.assertNotIn("ACTION_REPEAT_WITHOUT_STATE_CHANGE",
                         [finding["code"] for finding in report["findings"]])


# --------------------------------------------------------------------------- eye-line


class EyelineTests(unittest.TestCase):
    def test_addressing_a_character_while_nobody_is_in_frame_is_a_contradiction(self):
        state = state_file([
            ledger_shot("E14-S01-01", roster=("C_A", "C_B"), on_screen=[],
                        positions=[{"character_id": "C_B", "screen_slot": "OFFSCREEN",
                                    "eyeline_target": "C_A"}]),
            ledger_shot("E14-S01-02", roster=("C_A", "C_B"), on_screen=[]),
        ])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "she calls across the yard"),
                                shot("E14-S01-02", "E14-S01", "the yard is empty")])
        report = evaluate_pair(state, obj)
        codes = [finding["code"] for finding in report["findings"]]
        self.assertIn("EYELINE_ADDRESSEE_NOT_IN_FRAME", codes)
        finding = next(f for f in report["findings"] if f["code"] == "EYELINE_ADDRESSEE_NOT_IN_FRAME")
        self.assertEqual(finding["addressee"], "C_A")
        self.assertEqual(finding["to_shot_id"], "E14-S01-01")

    def test_a_legal_case_off_screen_addressee_with_nobody_in_frame(self):
        state = state_file([
            ledger_shot("E14-S01-01", roster=("C_A", "C_B"), on_screen=[],
                        positions=[{"character_id": "C_B", "screen_slot": "OFFSCREEN",
                                    "eyeline_target": "OFF_SCREEN:C_A"}]),
            ledger_shot("E14-S01-02", roster=("C_A", "C_B"), on_screen=[]),
        ])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "she calls to the dark"),
                                shot("E14-S01-02", "E14-S01", "the doorway stands empty")])
        report = evaluate_pair(state, obj)
        self.assertNotIn("EYELINE_ADDRESSEE_NOT_IN_FRAME",
                         [finding["code"] for finding in report["findings"]])

    def test_a_legal_case_over_the_shoulder_occlusion(self):
        """The addressee IS on screen; occlusion is not absence."""
        positions = [{"character_id": "C_A", "screen_slot": "FOREGROUND",
                      "eyeline_target": "C_B"},
                     {"character_id": "C_B", "screen_slot": "BACKGROUND",
                      "eyeline_target": "C_A", "occluded_by": "C_A",
                      "occlusion": "OVER_THE_SHOULDER"}]
        state = state_file([
            ledger_shot("E14-S01-01", characters=("C_A", "C_B"),
                        on_screen=["C_A", "C_B"], positions=positions),
            ledger_shot("E14-S01-02", characters=("C_A", "C_B"),
                        on_screen=["C_A", "C_B"], positions=positions),
        ])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "she speaks past his shoulder"),
                                shot("E14-S01-02", "E14-S01", "he answers over her shoulder")])
        report = evaluate_pair(state, obj)
        self.assertNotIn("EYELINE_ADDRESSEE_NOT_IN_FRAME",
                         [finding["code"] for finding in report["findings"]])

    def test_an_object_gaze_is_legal(self):
        state = state_file([
            ledger_shot("E14-S01-01", characters=(), on_screen=[],
                        positions=[{"character_id": "C_A", "screen_slot": "OFFSCREEN",
                                    "eyeline_target": "OBJECT:PROP-LAMP"}]),
            ledger_shot("E14-S01-02", characters=(), on_screen=[]),
        ])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "she looks toward the lamp"),
                                shot("E14-S01-02", "E14-S01", "the wall is bare")])
        report = evaluate_pair(state, obj)
        self.assertNotIn("EYELINE_ADDRESSEE_NOT_IN_FRAME",
                         [finding["code"] for finding in report["findings"]])


# --------------------------------------------------------------------------- screen slot


class ScreenSlotTests(unittest.TestCase):
    def _state(self, *, second_slot, jump_cut=False, device=None, time_space="SAME_CONTINUOUS"):
        return state_file([
            ledger_shot("E14-S01-01", positions=[{"character_id": "C_A", "screen_slot": "LEFT_THIRD"}]),
            ledger_shot("E14-S01-02", jump_cut=jump_cut, time_space=time_space,
                        positions=[{"character_id": "C_A", "screen_slot": second_slot}]),
        ])

    def _obj(self, device=None):
        return contract(SCENES, [
            shot("E14-S01-01", "E14-S01", "she stands at the left"),
            shot("E14-S01-02", "E14-S01", "she stands at the right", device=device),
        ])

    def test_a_slot_change_with_no_cut_is_a_contradiction(self):
        report = evaluate_pair(self._state(second_slot="RIGHT_THIRD"), self._obj())
        self.assertIn("SCREEN_SLOT_CHANGED_WITHOUT_CUT",
                      [finding["code"] for finding in report["findings"]])

    def test_a_legal_case_declared_jump_cut(self):
        report = evaluate_pair(self._state(second_slot="RIGHT_THIRD", jump_cut=True), self._obj())
        self.assertNotIn("SCREEN_SLOT_CHANGED_WITHOUT_CUT",
                         [finding["code"] for finding in report["findings"]])

    def test_a_declared_cut_device_carries_the_move(self):
        report = evaluate_pair(self._state(second_slot="RIGHT_THIRD"), self._obj(device="REACTION_CUT"))
        self.assertNotIn("SCREEN_SLOT_CHANGED_WITHOUT_CUT",
                         [finding["code"] for finding in report["findings"]])


# --------------------------------------------------------------------------- time / space


class TimeSpaceTests(unittest.TestCase):
    def test_a_location_change_declaring_same_continuous_is_flagged(self):
        scenes = [{"scene_id": "E14-S01", "location_id": "LOC-HALL", "time_id": "TIME-NIGHT"},
                  {"scene_id": "E14-S02", "location_id": "LOC-YARD", "time_id": "TIME-NIGHT"}]
        state = state_file([ledger_shot("E14-S01-01"), ledger_shot("E14-S02-01")])
        obj = contract(scenes, [shot("E14-S01-01", "E14-S01", "she steps back"),
                                shot("E14-S02-01", "E14-S02", "the yard is still")])
        report = evaluate_pair(state, obj)
        self.assertIn("TIME_SPACE_CHANGE_UNDECLARED",
                      [finding["code"] for finding in report["findings"]])

    def test_a_legal_case_declared_time_jump(self):
        scenes = [{"scene_id": "E14-S01", "location_id": "LOC-HALL", "time_id": "TIME-NIGHT"},
                  {"scene_id": "E14-S02", "location_id": "LOC-HALL", "time_id": "TIME-DAWN"}]
        state = state_file([
            ledger_shot("E14-S01-01"),
            ledger_shot("E14-S02-01", time_space="DECLARED_TIME_JUMP"),
        ])
        obj = contract(scenes, [shot("E14-S01-01", "E14-S01", "she sits by the window"),
                                shot("E14-S02-01", "E14-S02", "the window is grey with first light")])
        report = evaluate_pair(state, obj)
        self.assertNotIn("TIME_SPACE_CHANGE_UNDECLARED",
                         [finding["code"] for finding in report["findings"]])

    def test_a_legal_case_declared_scene_change(self):
        scenes = [{"scene_id": "E14-S01", "location_id": "LOC-HALL", "time_id": "TIME-NIGHT"},
                  {"scene_id": "E14-S02", "location_id": "LOC-YARD", "time_id": "TIME-NIGHT"}]
        state = state_file([
            ledger_shot("E14-S01-01"),
            ledger_shot("E14-S02-01", time_space="DECLARED_SCENE_CHANGE"),
        ])
        obj = contract(scenes, [shot("E14-S01-01", "E14-S01", "the hall empties"),
                                shot("E14-S02-01", "E14-S02", "the gate is bolted")])
        report = evaluate_pair(state, obj)
        self.assertNotIn("TIME_SPACE_CHANGE_UNDECLARED",
                         [finding["code"] for finding in report["findings"]])


# --------------------------------------------------------------------------- legal: pickup, mention


class LegalPickupAndMentionTests(unittest.TestCase):
    def test_a_legal_case_pickup_happening_on_screen(self):
        state = state_file([
            ledger_shot("E14-S01-01", props=[{"prop_id": "PROP-CUP", "holder": "ON_GROUND"}]),
            ledger_shot("E14-S01-02", props=[{"prop_id": "PROP-CUP", "holder": "C_A",
                                              "pickup_state": "PICKED_UP_IN_SHOT"}]),
        ])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "the cup sits on the table"),
                                shot("E14-S01-02", "E14-S01", "she lifts the cup")])
        report = evaluate_pair(state, obj)
        self.assertNotIn("PROP_HELD_WITHOUT_PICKUP",
                         [finding["code"] for finding in report["findings"]])

    def test_a_legal_case_prop_only_mentioned(self):
        """A prop named in the action text but absent from the state block is not held."""
        state = state_file([
            ledger_shot("E14-S01-01", props=[{"prop_id": "PROP-CUP", "holder": "ON_GROUND"}]),
            ledger_shot("E14-S01-02", props=[{"prop_id": "PROP-CUP", "holder": "ON_GROUND"}]),
        ])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "the cup sits on the table"),
                                shot("E14-S01-02", "E14-S01", "she speaks of the cup")])
        report = evaluate_pair(state, obj)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["rows"][0]["checks"]["PROP_HELD_WITHOUT_PICKUP"], "PASS")

    def test_an_inherited_holder_is_legal(self):
        state = state_file([
            ledger_shot("E14-S01-01", props=[{"prop_id": "PROP-CUP", "holder": "C_A",
                                              "pickup_state": "HELD"}]),
            ledger_shot("E14-S01-02", props=[{"prop_id": "PROP-CUP", "holder": "C_A",
                                              "pickup_state": "INHERITED"}]),
        ])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "she holds the cup"),
                                shot("E14-S01-02", "E14-S01", "she turns, still holding it")])
        report = evaluate_pair(state, obj)
        self.assertNotIn("PROP_HELD_WITHOUT_PICKUP",
                         [finding["code"] for finding in report["findings"]])


# --------------------------------------------------------------------------- unknown, planned/observed


class UnknownStateTests(unittest.TestCase):
    def test_no_ledger_is_unknown_never_a_failure_and_never_a_pass(self):
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "she waits"),
                                shot("E14-S01-02", "E14-S01", "she lifts it")])
        report = evaluate_pair(None, obj)
        self.assertEqual(report["status"], "UNKNOWN")
        self.assertFalse(report["state_declared"])
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["writer_items"], [])
        for row in report["rows"]:
            self.assertEqual(set(row["checks"].values()), {"UNKNOWN"})

    def test_a_missing_state_file_loads_as_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_state(Path(tmp) / "shot_state_authoring.json"))
            self.assertIsNone(load_state(None))

    def test_planned_and_observed_are_separate_and_observation_unknown(self):
        state = state_file([ledger_shot("E14-S01-01"), ledger_shot("E14-S01-02")])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "she crosses"),
                                shot("E14-S01-02", "E14-S01", "she stops")])
        row = evaluate_pair(state, obj)["rows"][0]
        self.assertEqual(row["planned"]["to_shot_id"], "E14-S01-02")
        self.assertTrue(row["planned"]["declared"])
        self.assertEqual(row["observed"]["to_shot"]["status"], "NO_QA_MEASUREMENT")

    def test_an_observation_is_reported_beside_the_plan_and_inconclusive_is_unknown(self):
        state = state_file([ledger_shot("E14-S01-01"), ledger_shot("E14-S01-02")])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "she crosses"),
                                shot("E14-S01-02", "E14-S01", "she stops")])
        observations = {"E14-S01-02": {"status": "MEASURED", "source": "fixture-vlm",
                                       "characters": {"C_A": {"screen_slot": "LEFT_THIRD"}}},
                        "E14-S01-01": {"status": "INCONCLUSIVE"}}
        row = evaluate_pair(state, obj, observations=observations)["rows"][0]
        self.assertEqual(row["observed"]["to_shot"]["characters"]["C_A"]["screen_slot"], "LEFT_THIRD")
        self.assertEqual(row["observed"]["from_shot"]["status"], "UNKNOWN")
        self.assertEqual(row["planned"]["characters"]["C_A"]["screen_slot"], "LEFT_THIRD")


# --------------------------------------------------------------------------- shape / safety


class ReportShapeTests(unittest.TestCase):
    def test_per_pair_rows_and_no_global_pass(self):
        state = state_file([ledger_shot("E14-S01-01"), ledger_shot("E14-S01-02"),
                            ledger_shot("E14-S01-03")])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "a"),
                                shot("E14-S01-02", "E14-S01", "b"),
                                shot("E14-S01-03", "E14-S01", "c")])
        report = evaluate_pair(state, obj)
        self.assertEqual(report["pair_count"], 2)
        self.assertEqual([(r["from_shot_id"], r["to_shot_id"]) for r in report["rows"]],
                         [("E14-S01-01", "E14-S01-02"), ("E14-S01-02", "E14-S01-03")])

    def test_a_unit_focus_keeps_the_slice_per_pair(self):
        state = state_file([ledger_shot("E14-S01-01"), ledger_shot("E14-S01-02")])
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "a"),
                                shot("E14-S01-02", "E14-S01", "b")])
        full = evaluate_pair(state, obj)
        sliced = evaluate(shots_from_contract(obj), state=state, focus={"E14-S01-02"})
        self.assertEqual(len(full["rows"]), len(sliced["rows"]))

    def test_evaluate_does_not_mutate_its_inputs(self):
        state = state_file([ledger_shot("E14-S01-01"), ledger_shot("E14-S01-02")])
        before = json.dumps(state, sort_keys=True)
        obj = contract(SCENES, [shot("E14-S01-01", "E14-S01", "a"),
                                shot("E14-S01-02", "E14-S01", "b")])
        evaluate_pair(state, obj)
        self.assertEqual(before, json.dumps(state, sort_keys=True))

    def test_every_rule_has_a_writer_question_and_options(self):
        report = evaluate_pair(None, contract(SCENES, [shot("E14-S01-01", "E14-S01", "a")]))
        self.assertEqual(set(report["rules"]), {
            "PROP_HELD_WITHOUT_PICKUP", "PROP_RETAKE_UNDECLARED",
            "ACTION_REPEAT_WITHOUT_STATE_CHANGE", "EYELINE_ADDRESSEE_NOT_IN_FRAME",
            "SCREEN_SLOT_CHANGED_WITHOUT_CUT", "TIME_SPACE_CHANGE_UNDECLARED"})
        for rule in report["rules"].values():
            self.assertTrue(rule["question"])
            self.assertTrue(rule["answer_options"])


if __name__ == "__main__":
    unittest.main()
