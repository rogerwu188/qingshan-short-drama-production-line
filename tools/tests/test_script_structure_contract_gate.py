import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools import script_structure_contract_gate as gate


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "e04_negative_sample"
LEXICON_PATH = (
    Path(__file__).resolve().parents[2] / "lines" / "nalu" / "runtime" / "configs" / "LEXICON_yewujiang_v1.json"
)

LINE = "台" * 12  # 12 spoken chars → 3 s at 4 cps


def shot(shot_id, scene_id, seconds=4, dialogue="", dims=("POSTURE",), cast=("CHAR-A",), props=(), blocking=""):
    return {
        "shot_id": shot_id,
        "scene_id": scene_id,
        "target_seconds": seconds,
        "blocking": blocking,
        "entry_state": "",
        "completion_state": "",
        "state_delta_dimensions": list(dims),
        "prompt_spec": {
            "cast": [{"character": c, "character_id": c} for c in cast],
            "props": [{"prop_id": p, "prop": p} for p in props],
            "dialogue": dialogue,
            "action": {"subject_id": cast[0] if cast else "", "primary_action": blocking, "patient_id": ""},
            "role_semantic_disambiguation": {"entity_states": {}, "entity_presence": {}},
        },
    }


def positive_contract():
    """Synthetic 32 s episode: hook line at 0 s, an action beat with outcome, a
    declared antagonist group, an introduced prop with a cross-episode source."""
    return {
        "schema": "qingshan.generation_contract.v3",
        "episode": "E99",
        "protagonist_ids": ["CHAR-A"],
        "pacing": {
            "hook": {"type": "dialogue", "at_seconds": 0, "line_or_shot_id": "E99-S01-01"},
            "dialogue_density": {"max_silent_run_seconds": 15, "max_silent_run_action_seconds": 25, "min_coverage": 0.35},
        },
        "character_entities": [
            {"character_id": "CHAR-A", "canonical_name": "甲", "aliases": []},
            {"character_id": "CHAR-B", "canonical_name": "乙", "aliases": [], "role": "antagonist"},
        ],
        "non_character_entities": [
            {"entity_id": "PROP-KNIFE", "name": "短刀", "first_shot": "E99-S03-01"},
        ],
        "props": {
            "reference_cards": [
                {
                    "entity_id": "PROP-KNIFE",
                    "name": "短刀",
                    "acquired": {"episode": "E98", "shot_id": "E98-S05-01"},
                    "recap_shot_id": "E99-S01-01",
                    "payoff_shot_ids": ["E99-S03-02"],
                }
            ]
        },
        "antagonist_groups": [
            {
                "group_id": "G-BANDITS",
                "member_ids": ["CHAR-B"],
                "first_action_shot_id": "E99-S02-02",
                "motive_setup": {"kind": "line", "ref": "E99-S01-02"},
            }
        ],
        "entity_introductions": [
            {"entity_id": "CHAR-B", "first_shot_id": "E99-S02-01", "setup": {"kind": "line", "ref": "E99-S01-02"}},
            {"entity_id": "PROP-KNIFE", "first_shot_id": "E99-S03-01", "payoff_shot_id": "E99-S03-02"},
        ],
        "scene_states": [
            {"scene_id": "E99-S01", "location_id": "LOC-A-EXT"},
            {"scene_id": "E99-S02", "location_id": "LOC-B-EXT"},
            {"scene_id": "E99-S03", "location_id": "LOC-C-INT"},
        ],
        "shots": [
            shot("E99-S01-01", "E99-S01", dialogue=f"甲：{LINE}", props=("PROP-KNIFE",)),
            shot("E99-S01-02", "E99-S01", dialogue=f"甲：{LINE}"),
            shot("E99-S02-01", "E99-S02", cast=("CHAR-A", "CHAR-B")),
            shot("E99-S02-02", "E99-S02", dims=("MOMENTUM", "CONTACT"), cast=("CHAR-A", "CHAR-B")),
            shot("E99-S02-03", "E99-S02", dialogue=f"乙：{LINE}", dims=("POSITION",), cast=("CHAR-A", "CHAR-B")),
            shot("E99-S03-01", "E99-S03", dialogue=f"甲：{LINE}", props=("PROP-KNIFE",)),
            shot("E99-S03-02", "E99-S03", props=("PROP-KNIFE",)),
            shot("E99-S03-03", "E99-S03", dialogue=f"甲：{LINE}"),
        ],
        "audio_contract": {
            "dialogue_units": [
                {"shot_id": "E99-S01-01", "speaker_id": "CHAR-A", "listener_id": "", "text": LINE},
                {"shot_id": "E99-S01-02", "speaker_id": "CHAR-A", "listener_id": "", "text": LINE},
                {"shot_id": "E99-S02-03", "speaker_id": "CHAR-B", "listener_id": "CHAR-A", "text": LINE},
                {"shot_id": "E99-S03-01", "speaker_id": "CHAR-A", "listener_id": "", "text": LINE},
                {"shot_id": "E99-S03-03", "speaker_id": "CHAR-A", "listener_id": "", "text": LINE},
            ]
        },
    }


def positive_manifest():
    return {
        "episode": "E99",
        "structure": [
            {"beat_id": "E99-B01", "scene_id": "E99-S01", "target_seconds": 8, "type": "dialogue"},
            {
                "beat_id": "E99-B02",
                "scene_id": "E99-S02",
                "target_seconds": 12,
                "type": "action",
                "outcome": {"kind": "escape", "evidence_shot_id": "E99-S02-03"},
            },
            {"beat_id": "E99-B03", "scene_id": "E99-S03", "target_seconds": 12, "type": "reveal"},
        ],
        "beat_disposition": [],
    }


def lexicon():
    return json.loads(LEXICON_PATH.read_text(encoding="utf-8"))


def e04_skeleton():
    contract = json.loads((FIXTURES / "contract_skeleton.json").read_text(encoding="utf-8"))
    manifest = json.loads((FIXTURES / "manifest_skeleton.json").read_text(encoding="utf-8"))
    return contract, manifest


class PositiveContractTests(unittest.TestCase):
    def test_positive_contract_passes_every_check(self):
        result = gate.evaluate(positive_contract(), positive_manifest(), lexicon())
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["schema"], "qingshan.script_structure_contract_gate.v1")
        self.assertEqual(result["measurements"]["hook"]["first_dialogue_seconds"], 0.0)
        self.assertGreaterEqual(result["measurements"]["dialogue_density"]["coverage"], 0.35)

    def test_no_lexicon_is_unverified_not_failed(self):
        result = gate.evaluate(positive_contract(), positive_manifest(), None)
        self.assertEqual(result["status"], "PASS")
        self.assertIn("lexicon: NOT_PROVIDED", result["unverified"])

    def test_no_manifest_leaves_action_outcome_unverified(self):
        result = gate.evaluate(positive_contract(), None, lexicon())
        self.assertEqual(result["status"], "PASS")
        self.assertIn("action_outcome: MANIFEST_NOT_PROVIDED", result["unverified"])


class HookTests(unittest.TestCase):
    def test_missing_hook(self):
        contract = positive_contract()
        del contract["pacing"]["hook"]
        self.assertIn("HOOK_MISSING", gate.check_hook(contract)["failures"])

    def test_hook_after_five_seconds(self):
        contract = positive_contract()
        contract["pacing"]["hook"]["at_seconds"] = 6
        self.assertIn("HOOK_NOT_IN_FIRST_5S", gate.check_hook(contract)["failures"])

    def test_dialogue_hook_without_early_dialogue(self):
        contract = positive_contract()
        contract["shots"][0]["prompt_spec"]["dialogue"] = ""
        contract["shots"][1]["prompt_spec"]["dialogue"] = ""
        self.assertIn("HOOK_NOT_IN_FIRST_5S", gate.check_hook(contract)["failures"])

    def test_shock_hook_requires_momentum_or_contact(self):
        contract = positive_contract()
        contract["pacing"]["hook"] = {"type": "shock", "at_seconds": 0, "line_or_shot_id": "E99-S01-01"}
        self.assertIn("HOOK_SHOT_NOT_SHOCK", gate.check_hook(contract)["failures"])
        contract["shots"][0]["state_delta_dimensions"] = ["MOMENTUM"]
        self.assertEqual(gate.check_hook(contract)["failures"], [])

    def test_question_hook_needs_question_mark(self):
        contract = positive_contract()
        contract["pacing"]["hook"] = {"type": "question", "at_seconds": 3, "line_or_shot_id": "E99-S01-01"}
        self.assertIn("HOOK_NOT_IN_FIRST_5S", gate.check_hook(contract)["failures"])
        contract["shots"][0]["prompt_spec"]["dialogue"] = "甲：台台台台？"
        self.assertEqual(gate.check_hook(contract)["failures"], [])


class DialogueDensityTests(unittest.TestCase):
    def test_silent_run_inside_action_beat_uses_action_limit(self):
        contract = positive_contract()
        contract["shots"][2]["target_seconds"] = 10
        contract["shots"][3]["target_seconds"] = 10  # 20 s silent run inside the action beat
        result = gate.check_dialogue_density(contract, positive_manifest())
        self.assertNotIn("DIALOGUE_STARVATION_SILENT_RUN:8-28", result["failures"])
        result = gate.check_dialogue_density(contract, None)  # no beat types → 15 s limit
        self.assertIn("DIALOGUE_STARVATION_SILENT_RUN:8-28", result["failures"])

    def test_low_coverage_fails_and_warn_verdict_downgrades(self):
        contract = positive_contract()
        for row in contract["shots"][3:]:
            row["prompt_spec"]["dialogue"] = ""
        result = gate.check_dialogue_density(contract, positive_manifest())
        self.assertTrue(any(f.startswith("DIALOGUE_STARVATION_COVERAGE:") for f in result["failures"]))
        contract["pacing"]["dialogue_density"]["verdict"] = "WARN"
        result = gate.check_dialogue_density(contract, positive_manifest())
        self.assertEqual(result["failures"], [])
        self.assertTrue(any(w.startswith("DIALOGUE_STARVATION_COVERAGE:") for w in result["warnings"]))
        self.assertEqual(gate.evaluate(contract, positive_manifest(), lexicon())["status"], "WARN")

    def test_speech_is_capped_by_shot_seconds(self):
        contract = positive_contract()
        contract["shots"][0]["prompt_spec"]["dialogue"] = "甲：" + "台" * 100
        per_shot = gate.check_dialogue_density(contract)["measurements"]["per_shot_speech"]
        self.assertEqual(per_shot[0]["speech_seconds"], 4.0)


class ActionOutcomeTests(unittest.TestCase):
    def test_structure_without_types_is_undeclared(self):
        manifest = positive_manifest()
        for row in manifest["structure"]:
            row.pop("type")
            row.pop("outcome", None)
        self.assertIn("BEAT_TYPE_UNDECLARED", gate.check_action_outcome(positive_contract(), manifest)["failures"])

    def test_action_without_outcome(self):
        manifest = positive_manifest()
        del manifest["structure"][1]["outcome"]
        self.assertIn("ACTION_NO_OUTCOME:E99-B02", gate.check_action_outcome(positive_contract(), manifest)["failures"])

    def test_evidence_shot_missing_or_late(self):
        manifest = positive_manifest()
        manifest["structure"][1]["outcome"]["evidence_shot_id"] = "E99-S09-09"
        self.assertIn(
            "ACTION_OUTCOME_EVIDENCE_MISSING_SHOT:E99-B02",
            gate.check_action_outcome(positive_contract(), manifest)["failures"],
        )
        manifest["structure"][1]["outcome"]["evidence_shot_id"] = "E99-S03-03"  # starts 28 s, beat ends 20 s
        contract = positive_contract()
        contract["shots"][5]["target_seconds"] = 8
        self.assertIn("ACTION_OUTCOME_EVIDENCE_LATE:E99-B02", gate.check_action_outcome(contract, manifest)["failures"])

    def test_beats_resolve_shots_through_landed_at_ranges(self):
        manifest = positive_manifest()
        manifest["structure"][1]["source_events"] = ["EV-1"]
        manifest["beat_disposition"] = [{"event_id": "EV-1", "disposition": "landed", "landed_at": "E99-S02-01 至 E99-S02-02"}]
        beat = gate.check_action_outcome(positive_contract(), manifest)["measurements"]["action_beats"][0]
        self.assertEqual(beat["shot_ids"], ["E99-S02-01", "E99-S02-02"])


class AntagonistPropEntityLexiconTests(unittest.TestCase):
    def test_undeclared_groups_when_antagonist_role_present(self):
        contract = positive_contract()
        del contract["antagonist_groups"]
        self.assertIn("ANTAGONIST_GROUPS_UNDECLARED", gate.check_antagonist_motive(contract)["failures"])
        contract["character_entities"][1].pop("role")
        self.assertEqual(gate.check_antagonist_motive(contract)["failures"], [])
        contract["shots"][2]["blocking"] = "乙在路口埋伏"
        contract["shots"][2]["prompt_spec"]["action"]["primary_action"] = contract["shots"][2]["blocking"]
        self.assertIn("ANTAGONIST_GROUPS_UNDECLARED", gate.check_antagonist_motive(contract)["failures"])

    def test_motive_after_action_and_missing(self):
        contract = positive_contract()
        contract["antagonist_groups"][0]["motive_setup"]["ref"] = "E99-S02-03"
        self.assertIn("ANTAGONIST_MOTIVE_AFTER_ACTION:G-BANDITS", gate.check_antagonist_motive(contract)["failures"])
        contract["antagonist_groups"][0]["motive_setup"] = {"kind": "shot", "ref": "E99-S00-00"}
        self.assertIn("ANTAGONIST_NO_MOTIVE:G-BANDITS", gate.check_antagonist_motive(contract)["failures"])

    def test_recap_motive_accepted_before_action(self):
        contract = positive_contract()
        contract["antagonist_groups"][0]["motive_setup"] = {
            "kind": "recap",
            "ref": {"episode": "E98", "shot_id": "E98-S09-01", "recap_shot_id": "E99-S01-01"},
        }
        self.assertEqual(gate.check_antagonist_motive(contract)["failures"], [])

    def test_prop_source_and_recap(self):
        contract = positive_contract()
        card = contract["props"]["reference_cards"][0]
        del card["acquired"]
        self.assertIn("PROP_NO_SOURCE:PROP-KNIFE", gate.check_prop_source(contract)["failures"])
        card["acquired"] = {"episode": "E98", "shot_id": "E98-S05-01"}
        card["recap_shot_id"] = "E99-S03-01"  # 20 s, payoff at 24 s → less than 10 s lead
        self.assertIn("PROP_RECAP_MISSING:PROP-KNIFE", gate.check_prop_source(contract)["failures"])
        card["acquired"] = {"episode": "E99", "shot_id": "E99-S01-01"}
        del card["recap_shot_id"]
        self.assertEqual(gate.check_prop_source(contract)["failures"], [])

    def test_prop_named_in_dialogue_requires_source(self):
        contract = positive_contract()
        card = contract["props"]["reference_cards"][0]
        card.pop("payoff_shot_ids")
        card.pop("acquired")
        self.assertEqual(gate.check_prop_source(contract)["failures"], [])
        contract["audio_contract"]["dialogue_units"][3]["text"] = "台台短刀台"
        self.assertIn("PROP_NO_SOURCE:PROP-KNIFE", gate.check_prop_source(contract)["failures"])

    def test_entity_without_setup_or_payoff(self):
        contract = positive_contract()
        contract["entity_introductions"] = []
        failures = gate.check_entity_introduction(contract)["failures"]
        self.assertIn("ENTITY_NO_SETUP_OR_PAYOFF:CHAR-B", failures)
        self.assertIn("ENTITY_NO_SETUP_OR_PAYOFF:PROP-KNIFE", failures)
        contract["carry_in"] = {"entities": ["PROP-KNIFE"]}
        self.assertNotIn("ENTITY_NO_SETUP_OR_PAYOFF:PROP-KNIFE", gate.check_entity_introduction(contract)["failures"])

    def test_lexicon_forbidden_term_and_name_variant(self):
        contract = positive_contract()
        contract["shots"][0]["prompt_spec"]["dialogue"] = "秦明：台台系统台"
        failures = gate.check_lexicon(contract, lexicon())["failures"]
        self.assertIn("MODERN_LEXICON:系统:E99-S01-01", failures)
        self.assertIn("NAME_VARIANT:秦明:E99-S01-01", failures)
        self.assertIn(
            "LEXICON_SCHEMA_INVALID:EMPTY",
            gate.check_lexicon(contract, {"forbidden_terms": ["系统"]})["failures"],
        )


class E04NegativeSampleTests(unittest.TestCase):
    """Regression against the stripped E04 v1 contract: report §一 #1/#2/#3/#7/#8/#11."""

    def test_e04_skeleton_fails_with_the_report_codes(self):
        contract, manifest = e04_skeleton()
        result = gate.evaluate(contract, manifest, lexicon())
        self.assertEqual(result["status"], "FAIL")
        failures = result["failures"]
        for code in (
            "HOOK_MISSING",
            "DIALOGUE_STARVATION_SILENT_RUN:0-45",
            "BEAT_TYPE_UNDECLARED",
            "ANTAGONIST_GROUPS_UNDECLARED",
            "PROP_NO_SOURCE:PROP-RED-SQUIRREL",
            "ENTITY_NO_SETUP_OR_PAYOFF:PROP-DONKEY",
            "ENTITY_NO_SETUP_OR_PAYOFF:PROP-WHITE-WEASEL",
            "MODERN_LEXICON:变异:E04-S04-04",
        ):
            self.assertIn(code, failures)
        self.assertTrue(any(f.startswith("DIALOGUE_STARVATION_COVERAGE:") for f in failures))

    def test_e04_skeleton_timeline_numbers(self):
        contract, manifest = e04_skeleton()
        density = gate.check_dialogue_density(contract, manifest)["measurements"]
        self.assertEqual(density["total_seconds"], 170.0)
        self.assertEqual(density["first_dialogue_seconds"], 45.0)
        self.assertLess(density["coverage"], 0.35)
        runs = sorted(density["silent_runs"], key=lambda r: -r["seconds"])
        self.assertEqual((runs[0]["start"], runs[0]["end"]), (0.0, 45.0))
        self.assertEqual((runs[1]["start"], runs[1]["end"]), (65.0, 89.0))

    def test_corrected_e04_contract_passes(self):
        contract, manifest = e04_skeleton()
        contract = copy.deepcopy(contract)
        shots = {s["shot_id"]: s for s in contract["shots"]}
        # A1 hook: a line in the first shot.  A5: break the 0–45 s and 65–89 s silent runs.
        for sid in ("E04-S01-01", "E04-S02-04", "E04-S03-03", "E04-S04-01", "E04-S06-02", "E04-S07-03"):
            shots[sid]["prompt_spec"]["dialogue"] = "秦铭：" + "台" * 12
        contract["pacing"]["hook"] = {"type": "dialogue", "at_seconds": 0, "line_or_shot_id": "E04-S01-01"}
        # A6: no modern word in the opening line.
        shots["E04-S04-04"]["prompt_spec"]["dialogue"] = "秦铭：" + "台" * 10 + "？"
        for unit in contract["audio_contract"]["dialogue_units"]:
            if unit["shot_id"] == "E04-S04-04":
                unit["text"] = "台" * 10 + "？"
        # A3: the three idlers as a declared group with a motive line before their first action.
        contract["antagonist_groups"] = [
            {
                "group_id": "G-IDLERS",
                "member_ids": ["CHAR-HUYONG", "CHAR-MAYANG", "CHAR-WANGYOUPING"],
                "first_action_shot_id": "E04-S07-01",
                "motive_setup": {"kind": "line", "ref": "E04-S05-02"},
            }
        ]
        # A4: prop sources.
        for card in contract["props"]["reference_cards"]:
            card["acquired"] = {"episode": "E03", "shot_id": "E03-S10-01"}
            card["recap_shot_id"] = "E04-S01-01"
        # B3′: every non-protagonist entity is set up or paid off.
        required = gate.check_entity_introduction(contract)["measurements"]["required_entities"]
        contract["entity_introductions"] = [
            {"entity_id": eid, "first_shot_id": "E04-S01-01", "setup": {"kind": "line", "ref": "E04-S01-01"}}
            for eid in required
        ]
        # A2: beat types and action outcomes.
        for row in manifest["structure"]:
            row["type"] = "dialogue"
        for beat_id, evidence in (("E04-B03", "E04-S03-05"), ("E04-B07", "E04-S07-05")):
            row = next(r for r in manifest["structure"] if r["beat_id"] == beat_id)
            row["type"] = "action"
            row["outcome"] = {"kind": "escape", "evidence_shot_id": evidence}
        result = gate.evaluate(contract, manifest, lexicon())
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["status"], "PASS")
        self.assertGreaterEqual(result["measurements"]["dialogue_density"]["coverage"], 0.35)


class CliTests(unittest.TestCase):
    def test_cli_writes_report_and_exits_nonzero_on_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            code = gate.main(
                [
                    "--contract", str(FIXTURES / "contract_skeleton.json"),
                    "--manifest", str(FIXTURES / "manifest_skeleton.json"),
                    "--lexicon", str(LEXICON_PATH),
                    "--out", str(out),
                ]
            )
            self.assertEqual(code, 1)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("HOOK_MISSING", report["failures"])


if __name__ == "__main__":
    unittest.main()
