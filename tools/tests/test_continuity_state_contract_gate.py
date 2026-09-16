import json
import tempfile
import unittest
from pathlib import Path

from tools import continuity_state_contract_gate as gate


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "e04_negative_sample"


def shot(shot_id, scene_id, cast, props=(), action="", entry="", completion="", position_exit="", group_counts=None):
    row = {
        "shot_id": shot_id,
        "scene_id": scene_id,
        "target_seconds": 4,
        "blocking": action,
        "entry_state": entry,
        "completion_state": completion,
        "state_delta_dimensions": ["POSITION"],
        "state_delta_evidence": {"POSITION": {"entry": entry, "exit": position_exit}},
        "prompt_spec": {
            "cast": [{"character": cid, "character_id": cid, "life_state": state} for cid, state in cast],
            "props": [{"prop_id": p, "prop": p} for p in props],
            "dialogue": "",
            "action": {"subject_id": cast[0][0] if cast else "", "primary_action": action, "patient_id": ""},
            "role_semantic_disambiguation": {"entity_states": {}, "entity_presence": {}},
        },
    }
    if group_counts is not None:
        row["group_counts"] = group_counts
    return row


def positive_contract():
    """Synthetic: an ambush at a snow pit, a biped creature, a hat taken off indoors."""
    return {
        "schema": "qingshan.generation_contract.v3",
        "episode": "E99",
        "character_entities": [
            {"character_id": "CHAR-A", "canonical_name": "甲", "aliases": []},
            {"character_id": "CHAR-B", "canonical_name": "乙", "aliases": []},
        ],
        "non_character_entities": [
            {"entity_id": "SET-PIT", "name": "雪坑", "kind": "SET", "first_shot": "E99-S01-01"},
            {
                "entity_id": "PROP-MUTANT-BEAST",
                "name": "猛兽",
                "kind": "CREATURE",
                "first_shot": "E99-S02-01",
                "creature_card": {"locomotion": "biped", "eye_color": "猩红", "silhouette_ref": "card://beast-v1"},
            },
        ],
        "ambush_contracts": [
            {"who_hides": ["CHAR-B"], "who_approaches": ["CHAR-A"], "hide_place_id": "SET-PIT", "reveal_shot_id": "E99-S01-03"}
        ],
        "scene_states": [
            {"scene_id": "E99-S01", "location_id": "LOC-ROAD-EXT"},
            {"scene_id": "E99-S02", "location_id": "LOC-WOODS-EXT"},
            {
                "scene_id": "E99-S03",
                "location_id": "LOC-HOUSE-INT",
                "costume_overrides": {"CHAR-A": {"remove": ["hat"], "add": []}},
            },
        ],
        "shots": [
            shot("E99-S01-01", "E99-S01", [("CHAR-B", "alive")], props=("SET-PIT",), action="乙藏身雪坑",
                 group_counts={"G-IDLERS": {"count": 3}}),
            shot("E99-S01-02", "E99-S01", [("CHAR-A", "alive")], action="甲沿雪路走近", position_exit="雪路上，距坑口十步",
                 group_counts={"G-IDLERS": {"count": 3}}),
            shot("E99-S01-03", "E99-S01", [("CHAR-A", "alive"), ("CHAR-B", "alive")], action="乙从雪坑跃出拦住甲",
                 group_counts={"G-IDLERS": {"count": 2, "count_change_note": "one idler runs off"}}),
            shot("E99-S02-01", "E99-S02", [("CHAR-A", "injured")], props=("PROP-MUTANT-BEAST",), action="黑影直立奔行"),
            shot("E99-S02-02", "E99-S02", [("CHAR-A", "injured")], props=("PROP-MUTANT-BEAST",), action="黑影两足立在林边"),
            shot("E99-S03-01", "E99-S03", [("CHAR-A", "injured")], action="甲摘下帽子"),
        ],
        "audio_contract": {"dialogue_units": []},
    }


class PositiveContractTests(unittest.TestCase):
    def test_positive_contract_passes(self):
        result = gate.evaluate(positive_contract())
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["schema"], "qingshan.continuity_state_contract_gate.v1")
        self.assertEqual(result["measurements"]["life_state"]["final_group_counts"], {"G-IDLERS": 2})


class LifeStateTests(unittest.TestCase):
    def test_undeclared_and_invalid_life_state(self):
        contract = positive_contract()
        del contract["shots"][0]["prompt_spec"]["cast"][0]["life_state"]
        contract["shots"][1]["prompt_spec"]["cast"][0]["life_state"] = "zombie"
        failures = gate.check_life_state(contract)["failures"]
        self.assertIn("LIFE_STATE_UNDECLARED:E99-S01-01:CHAR-B", failures)
        self.assertIn("LIFE_STATE_INVALID:E99-S01-02:CHAR-A:zombie", failures)

    def test_dead_then_alive(self):
        contract = positive_contract()
        contract["shots"][3]["prompt_spec"]["cast"][0]["life_state"] = "dead"
        failures = gate.check_life_state(contract)["failures"]
        self.assertIn("DEAD_THEN_ALIVE:CHAR-A:E99-S02-02", failures)
        self.assertNotIn("DEAD_THEN_ALIVE:CHAR-A:E99-S02-01", failures)

    def test_group_count_drift_without_note(self):
        contract = positive_contract()
        del contract["shots"][2]["group_counts"]["G-IDLERS"]["count_change_note"]
        self.assertIn("GROUP_COUNT_DRIFT:G-IDLERS:E99-S01-03", gate.check_life_state(contract)["failures"])
        contract["shots"][2]["group_counts"]["G-IDLERS"] = {"count": "three"}
        self.assertIn("GROUP_COUNT_INVALID:G-IDLERS:E99-S01-03", gate.check_life_state(contract)["failures"])


class CreatureCardTests(unittest.TestCase):
    def test_form_drift_against_card(self):
        contract = positive_contract()
        contract["shots"][4]["blocking"] = "黑影四足奔来"
        contract["shots"][4]["prompt_spec"]["action"]["primary_action"] = "黑影四足奔来"
        self.assertIn(
            "CREATURE_FORM_DRIFT:PROP-MUTANT-BEAST:E99-S02-02",
            gate.check_creature_card(contract)["failures"],
        )

    def test_kind_inferred_from_id_and_card_required(self):
        contract = positive_contract()
        beast = contract["non_character_entities"][1]
        del beast["kind"]
        del beast["creature_card"]
        failures = gate.check_creature_card(contract)["failures"]
        self.assertIn("CREATURE_KIND_UNDECLARED:PROP-MUTANT-BEAST", failures)
        self.assertIn("CREATURE_CARD_MISSING:PROP-MUTANT-BEAST", failures)

    def test_card_field_validation(self):
        contract = positive_contract()
        card = contract["non_character_entities"][1]["creature_card"]
        card["locomotion"] = "hexapod"
        self.assertIn("CREATURE_CARD_INVALID:PROP-MUTANT-BEAST:hexapod", gate.check_creature_card(contract)["failures"])
        card["locomotion"] = "quadruped"
        card["eye_color"] = ""
        failures = gate.check_creature_card(contract)["failures"]
        self.assertIn("CREATURE_CARD_FIELD_MISSING:PROP-MUTANT-BEAST:eye_color", failures)
        self.assertIn("CREATURE_FORM_DRIFT:PROP-MUTANT-BEAST:E99-S02-01", failures)


class AmbushSpaceTests(unittest.TestCase):
    def test_approacher_entering_hideout_before_reveal(self):
        contract = positive_contract()
        contract["shots"][1]["state_delta_evidence"]["POSITION"]["exit"] = "甲在雪坑里"
        self.assertIn(
            "AMBUSH_APPROACHER_ENTERS_HIDEOUT_BEFORE_REVEAL:E99-S01-02",
            gate.check_ambush_space(contract)["failures"],
        )
        contract["shots"][1]["state_delta_evidence"]["POSITION"]["exit"] = ""
        contract["shots"][1]["completion_state"] = "甲爬进雪坑"
        self.assertIn(
            "AMBUSH_APPROACHER_ENTERS_HIDEOUT_BEFORE_REVEAL:E99-S01-02",
            gate.check_ambush_space(contract)["failures"],
        )

    def test_entering_after_reveal_is_fine(self):
        contract = positive_contract()
        contract["shots"][3]["completion_state"] = "甲爬进雪坑"
        contract["shots"][3]["prompt_spec"]["cast"].append({"character": "甲", "character_id": "CHAR-A", "life_state": "alive"})
        self.assertEqual(gate.check_ambush_space(contract)["failures"], [])

    def test_undeclared_ambush_contract(self):
        contract = positive_contract()
        del contract["ambush_contracts"]
        self.assertIn("AMBUSH_CONTRACT_UNDECLARED", gate.check_ambush_space(contract)["failures"])
        contract["shots"][0]["blocking"] = "乙蹲在坑里"
        contract["shots"][0]["prompt_spec"]["action"]["primary_action"] = "乙蹲在坑里"
        self.assertEqual(gate.check_ambush_space(contract)["failures"], [])

    def test_missing_reveal_shot(self):
        contract = positive_contract()
        contract["ambush_contracts"][0]["reveal_shot_id"] = "E99-S09-09"
        self.assertIn("AMBUSH_REVEAL_SHOT_MISSING:E99-S09-09", gate.check_ambush_space(contract)["failures"])


class CostumeInheritanceTests(unittest.TestCase):
    def test_hat_indoors_without_override_is_a_warning(self):
        contract = positive_contract()
        del contract["scene_states"][2]["costume_overrides"]
        result = gate.evaluate(contract)
        self.assertEqual(result["failures"], [])
        self.assertIn("COSTUME_STATE_UNDECLARED:E99-S03:CHAR-A", result["warnings"])
        self.assertEqual(result["status"], "WARN")

    def test_no_costume_mention_needs_no_override(self):
        contract = positive_contract()
        del contract["scene_states"][2]["costume_overrides"]
        contract["shots"][5]["blocking"] = "甲坐到炕边"
        contract["shots"][5]["prompt_spec"]["action"]["primary_action"] = "甲坐到炕边"
        self.assertEqual(gate.check_costume_inheritance(contract)["warnings"], [])


class E04NegativeSampleTests(unittest.TestCase):
    """Regression against the stripped E04 v1 contract: report §一 #4/#5/#6."""

    def test_e04_skeleton_fails_with_the_report_codes(self):
        contract = json.loads((FIXTURES / "contract_skeleton.json").read_text(encoding="utf-8"))
        result = gate.evaluate(contract)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("AMBUSH_CONTRACT_UNDECLARED", result["failures"])
        self.assertIn("CREATURE_KIND_UNDECLARED:PROP-MUTANT-BEAST", result["failures"])
        self.assertIn("CREATURE_CARD_MISSING:PROP-MUTANT-BEAST", result["failures"])
        self.assertIn("LIFE_STATE_UNDECLARED:E04-S01-01:CHAR-QINMING", result["failures"])
        self.assertTrue(any(f.startswith("LIFE_STATE_UNDECLARED:E04-S08-04:") for f in result["failures"]))
        # E04 declared everyone alive, so the 108 s "corpses" cannot be caught here (plan §0).
        self.assertFalse(any(f.startswith("DEAD_THEN_ALIVE") for f in result["failures"]))


class CliTests(unittest.TestCase):
    def test_cli_writes_report_and_exits_nonzero_on_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            code = gate.main(["--contract", str(FIXTURES / "contract_skeleton.json"), "--out", str(out)])
            self.assertEqual(code, 1)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("AMBUSH_CONTRACT_UNDECLARED", report["failures"])


if __name__ == "__main__":
    unittest.main()
