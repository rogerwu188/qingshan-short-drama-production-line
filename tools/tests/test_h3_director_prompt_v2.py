"""DIRECTOR_PROMPT_V2: the opt-in H3 director prompt (synthetic two-person fixture).

Opt-in only (generation contract ``h3_prompt_style``); every other unit renders the V1 prompt byte-identically.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import re
import sys
import unittest
from pathlib import Path

from tools import h3_director_prompt_v2 as v2
from tools.h3_english_contract_io import request_row
from tools.h3_provider_english_contract import validate_h3_provider_text_boundary
from tools.h3_provider_prompt_renderer import render_h3_prompt
from tools.provider_contract_boundary import validate_provider_prompt_boundary
from tools.provider_scope_projection import (
    DIRECTOR_V2_SECTION_MARKERS,
    h3_prompt_style,
    validate_provider_scope_projection,
)
from tools.provider_semantic_coverage import build_semantic_coverage_receipt
from tools.submit_giggle_video_manifest_v2 import provider_prompt_unit, uses_structured_role_gate
from tools.tests.test_h3_shot_scope_v1 import A, B, LOCKED, build

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lines" / "nalu" / "runtime" / "tools"))
import prompt_batch_qa  # noqa: E402

STYLE = {"h3_prompt_style": "DIRECTOR_PROMPT_V2"}
CAMERA = {**LOCKED, "camera_grammar": "CAMERA_GRAMMAR_V1",
          "start_framing": "Two-person medium shot, Alpha on the left and Beta on the right, waist up",
          "end_framing": "Two-person medium shot, Alpha on the left and Beta on the right, waist up"}
ORDER = ("References:\n", "\n\nWho is in frame (", "\n\nSetting:\n", "\n\nCamera:\n", "\n\nAction (0",
         "\n\nDialogue (", "\n\nSound: ", "\n\nNever: ")
INTERNAL = re.compile(r"\b(?:CHAR|SUBSPACE|LOC|SET|PROP|AXIS|ANGLE)-[A-Z0-9-]+|\bE\d+-(?:VU|S)\d|\bVU-T01\b")
#: sha256 of the V1 render of fixture(style=False) / fixture(style=False, director=False), computed with the
#: pre-V2 engine (HEAD 7bd213c): the opt-in must leave every other unit byte-identical.
V1_SHA = {
    True: "0857f6108bb1499f90b181328a418c582c853a02fcc572a38a62f385cbddfb83",
    False: "ab9d6ae00614e4f89f53a4a7e0960162458dd56af941aa23f2abec8481a3561d",
}


def fixture(*, style: bool = True, director: bool = True, listener: object = None) -> tuple[dict, dict]:
    unit, plan = build([{"cast": [A, B], "speaker": A}], camera_plan=CAMERA if director else deepcopy(LOCKED))
    if style:
        unit.update(STYLE)
    unit["reference_images"] = [{"path": "open.png", "role": "ADMITTED_NEW_EVENT_ENTRY_STATE"},
                                {"path": "a.png", "role": "CHARACTER_IDENTITY_REFERENCE"},
                                {"path": "b.png", "role": "CHARACTER_IDENTITY_REFERENCE"}]
    projection = unit["provider_scope_projection"]
    for index, row in enumerate(projection["reference_identity_bindings"], 2):
        row.update(reference_index=index, role="CHARACTER_IDENTITY_REFERENCE", binding_role="IDENTITY",
                   may_define_identity=True)
    projection.update({
        "schema": "qingshan.provider_scope_projection.v1", "status": "LOCKED",
        "provider_reads_episode_global_contract_directly": False, "exclusive_visible_living_entity_set": True,
        "visible_character_ids": [A, B], "visible_entity_instance_counts": {A: 1, B: 1},
        "visible_living_entity_instance_total": 2, "background_population_count": 0,
        "unbound_visible_living_entity_count": 0, "anonymous_role_descriptors": [],
    })
    spec = unit["ordered_prompt_specs"][0]
    spec["role_semantic_disambiguation"].update(primary_actor_id=A, dialogue_speaker_id=A, dialogue_listener_id=B)
    if listener is not None:
        spec["action"] = {"listener_reaction_en": listener}
    unit["character_entities"] = [{"character_id": A, "canonical_name": "阿尔", "english_name": "Alpha",
                                   "appearance_ch1": "三十岁男性，短发。"},
                                  {"character_id": B, "canonical_name": "贝塔", "english_name": "Beta",
                                   "appearance_ch1": "二十八岁女性，长发。"}]
    unit["wardrobe_contract"] = {"characters": [
        {"character": "阿尔", "character_id": A, "authored_description": "藏蓝西装"},
        {"character": "贝塔", "character_id": B, "authored_description": "a plain off-white shirt and grey trousers"}]}
    plan["interaction_topology_required"] = True
    plan["sounds"] = {"ambience": ["空调声"], "foley": ["仅分镜T-S01适用：衣料声"], "action_sound": ["NO_BGM"]}
    plan["environment_motion"] = ["天候：晴"]
    english = unit["h3_provider_english_contract"]
    english["space_weather_fact"] = "Within the same SUBSPACE-T01-01; time: DUSK; clear weather"
    english["identity_prop_fact"] = ("Characters: Alpha and Beta. Key prop: gray long table. Use supplied task "
                                     "references to lock named characters, wardrobe, setting and prop ownership.")
    english["beats"][0].update(entry_state="Alpha stands left of the table; Beta stands right",
                               primary_action="Alpha leans forward and points at the contract",
                               exit_state="Alpha leans over the table; Beta stands right")
    english["sounds"] = {"ambience": ["Low air-conditioning hum"],
                         "foley": ["Only for shot T-S01: cloth rustle from this action: Alpha leans forward and "
                                   "points at the contract."],
                         "action_sound": ["One sleeve brush. NO_BGM."]}
    english["environment_motion"] = ["Clear weather; continuous subtle motion only, no effects"]
    english["camera_plan"] = {k: CAMERA[k] for k in ("start_framing", "end_framing")}
    english["director_v2"] = {
        "subjects": {A: {"appearance": "Man, 30, short black hair", "wardrobe": "Plain navy suit"},
                     B: {"appearance": "Woman, 28, long black hair"}},
        "setting": "A glass-walled meeting room, a long grey table in front",
    }
    return unit, plan


def render(**kwargs) -> tuple[str, dict]:
    return render_h3_prompt(*fixture(**kwargs))


class DirectorPromptV2Shape(unittest.TestCase):
    def test_sections_in_order_and_exact_count_sentence(self):
        text, receipt = render()
        positions = [text.find(marker) for marker in ORDER]
        self.assertTrue(all(p >= 0 for p in positions), positions)
        self.assertEqual(positions, sorted(positions))
        self.assertIn("\nWho is in frame (exactly these two people, each exactly once, both visible from the "
                      "first frame to the last):\n", text)
        self.assertIn("- Alpha, frame left: Man, 30, short black hair. Plain navy suit.\n", text)
        self.assertIn("- Beta, frame right: Woman, 28, long black hair. A plain off-white shirt and grey trousers.\n", text)
        self.assertIn("Each keeps only their own clothes. Nobody else appears", text)
        self.assertIn("@Image1 is the opening frame", text)
        self.assertIn("@Image2 is Alpha's face and body.\n@Image3 is Beta's face and body.\n", text)
        self.assertIn("@Audio1 is Alpha's voice. It gives timbre only — never speak or echo its words.", text)
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["h3_prompt_style"], "DIRECTOR_PROMPT_V2")
        self.assertTrue(1000 < len(text) < 3500, len(text))

    def test_dialogue_listener_sound_and_never(self):
        text, _ = render()
        self.assertEqual(text.count("<d>[Chinese] 你好。</d>"), 1)
        self.assertIn("Dialogue (Alpha only, once, lips in sync):\n<d>[Chinese] 你好。</d>\n", text)
        self.assertIn("After the line nobody speaks; the remaining time is room tone.", text)
        self.assertIn("Beta listens without speaking, holding Alpha's gaze.", text)
        self.assertIn("Sound: Low air-conditioning hum. Cloth rustle from this action. One sleeve brush. "
                      "No background music.", text)
        self.assertIn("Never: captions, subtitles, letters or logos on screen; a second copy of anyone; "
                      "anyone else in frame; music.", text)
        self.assertIn("Key prop: gray long table.", text)
        self.assertIn("Time: dusk; clear weather.", text)

    def test_no_cjk_outside_dialogue_no_ids_no_v1_templates(self):
        text, _ = render()
        outside = re.sub(r"<d>\[Chinese\].*?</d>", "", text)
        self.assertFalse(re.search(r"[㐀-鿿]", outside))
        self.assertFalse(INTERNAL.search(outside), INTERNAL.search(outside))
        for phrase in ("at most one", "subject_definitions", "retention_analysis", "Force origin",
                       "Interaction mode", "NO_BGM", "this reference alone does not put", "role=",
                       "SUBJECT_1", "SPEAKER_1", "Use supplied task references"):
            self.assertNotIn(phrase, text)
        self.assertEqual(v2.director_v2_self_check(text, *fixture()), [])

    def test_authored_listener_reaction_replaces_the_default(self):
        text, _ = render(listener="Beta folds her arms and narrows her eyes, silent")
        self.assertIn("Beta folds her arms and narrows her eyes, silent.", text)
        self.assertNotIn("Beta listens without speaking", text)
        text, _ = render(listener={B: "keeps her eyes on the contract"})
        self.assertIn("Beta: keeps her eyes on the contract.", text)

    def test_partial_and_offscreen_presence_is_stated_per_subject(self):
        unit, plan = build([{"cast": [A, B], "speaker": A, "extent": {B: "HANDS_ONLY"}}], camera_plan=CAMERA)
        unit.update(STYLE)
        unit["provider_scope_projection"]["visible_living_entity_instance_total"] = 2
        text, _ = render_h3_prompt(unit, plan)
        self.assertIn("Who is in frame (exactly these two people, each exactly once, presence as noted for each):", text)
        self.assertIn("0–3 s: only Beta's hands in frame; Beta's face is not shown.", text)


class DirectorPromptV2Validators(unittest.TestCase):
    def test_boundary_scope_and_section_validators_accept_v2(self):
        unit, plan = fixture()
        text, receipt = render_h3_prompt(unit, plan)
        self.assertEqual(validate_provider_prompt_boundary(text, source_id="u", model_family="MINIMAX_H3")["failures"], [])
        self.assertEqual(validate_h3_provider_text_boundary(text, source_id="u")["failures"], [])
        self.assertTrue(all(marker in text for marker in DIRECTOR_V2_SECTION_MARKERS))
        enforced = {**unit, "provider_scope_prompt_checks": "ENFORCED"}
        self.assertEqual(validate_provider_scope_projection(enforced, prompt_text=text, model="MiniMax-H3")["failures"], [])
        coverage = receipt["provider_semantic_coverage_receipt"]
        self.assertEqual(coverage["status"], "PASS")
        self.assertEqual(coverage["prompt_style"], "DIRECTOR_PROMPT_V2")
        self.assertIn("BEAT.1.FORCE_ORIGIN", [row["fact_id"] for row in coverage["coverage_rows"]])
        self.assertEqual(receipt["shot_scope"]["status"], "PASS")

    def test_v2_gate_checks_the_v2_promises_instead_of_disabling_them(self):
        unit, plan = fixture()
        text, _ = render_h3_prompt(unit, plan)
        enforced = {**unit, "provider_scope_prompt_checks": "ENFORCED"}
        wrong = text.replace("exactly these two people", "these people")
        failures = validate_provider_scope_projection(enforced, prompt_text=wrong, model="MiniMax-H3")["failures"]
        self.assertIn("H3_PROVIDER_SCOPE_EXCLUSIVE_POPULATION_CLAUSE_MISSING", failures)
        missing = text.replace("\n- Beta, frame right", "\nBeta, frame right")
        failures = validate_provider_scope_projection(enforced, prompt_text=missing, model="MiniMax-H3")["failures"]
        self.assertIn("H3_PROVIDER_SCOPE_INSTANCE_CARDINALITY_MISSING:" + B, failures)
        v1_payload = {k: v for k, v in enforced.items() if k != "h3_prompt_style"}
        self.assertTrue(validate_provider_scope_projection(v1_payload, prompt_text=text, model="MiniMax-H3")["failures"])

    def test_coverage_still_fails_closed_for_v2(self):
        unit, plan = fixture()
        text, _ = render_h3_prompt(unit, plan)
        receipt = build_semantic_coverage_receipt(plan=plan, prompt_text=text, model_family="MINIMAX_H3",
                                                  clause_evidence={}, prompt_style="DIRECTOR_PROMPT_V2")
        self.assertEqual(receipt["status"], "FAIL")
        v1 = build_semantic_coverage_receipt(plan=plan, prompt_text=text, model_family="MINIMAX_H3", clause_evidence={})
        self.assertNotIn("prompt_style", v1)

    def test_submitter_digest_and_compiler_input_carry_the_style(self):
        text, _ = render()
        task = {"model": "MiniMax-H3", "h3_prompt_style": "DIRECTOR_PROMPT_V2"}
        self.assertTrue(uses_structured_role_gate(task, text))
        self.assertFalse(uses_structured_role_gate({"model": "MiniMax-H3"}, text))
        self.assertEqual(provider_prompt_unit(task)["h3_prompt_style"], "DIRECTOR_PROMPT_V2")
        self.assertNotIn("h3_prompt_style", provider_prompt_unit({"model": "MiniMax-H3"}))
        self.assertTrue(prompt_batch_qa.is_h3_director_v2(text))
        self.assertIn("Beta listens without speaking", prompt_batch_qa.section(text, "时间轴"))
        self.assertTrue(prompt_batch_qa.section(text, "声音").startswith("Low air-conditioning hum"))

    def test_style_declaration_is_exact(self):
        self.assertEqual(h3_prompt_style({"h3_prompt_style": " director_prompt_v2 "}), "DIRECTOR_PROMPT_V2")
        for value in (None, "", "V2", "DIRECTOR_PROMPT_V3"):
            self.assertEqual(h3_prompt_style({"h3_prompt_style": value}), "")

    def test_english_request_asks_only_v2_units_for_appearance_and_setting(self):
        unit, plan = fixture()
        unit.pop("h3_provider_english_contract")
        row = request_row(unit, plan)
        self.assertEqual(row["english"]["director_v2"],
                         {"subjects": {A: {"appearance": "", "wardrobe": ""}, B: {"appearance": ""}}})
        legacy, legacy_plan = fixture(style=False)
        legacy.pop("h3_provider_english_contract")
        self.assertNotIn("director_v2", request_row(legacy, legacy_plan)["english"])


class V1ByteIdentity(unittest.TestCase):
    def test_units_without_the_opt_in_render_v1_byte_identically(self):
        for director in (True, False):
            text, receipt = render(style=False, director=director)
            self.assertTrue(text.startswith("subject_definitions:\n"))
            self.assertNotIn("prompt_style", receipt["provider_semantic_coverage_receipt"])
            self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(), V1_SHA[director])

    def test_single_subject_profiles_keep_their_own_grammar(self):
        unit, plan = fixture()
        unit["h3_prompt_profile"] = "H3_POSITIVE_SINGLE_SUBJECT_V1"
        self.assertNotEqual(h3_prompt_style({}), "DIRECTOR_PROMPT_V2")
        try:
            text, _ = render_h3_prompt(unit, plan)
        except ValueError:
            return  # a two-person fixture may legitimately fail the single-subject grammar: never V2
        self.assertFalse(text.startswith("References:\n"))


if __name__ == "__main__":
    unittest.main()
