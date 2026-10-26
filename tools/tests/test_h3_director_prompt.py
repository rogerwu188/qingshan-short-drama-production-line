"""CAMERA_GRAMMAR_V1 director block for H3 (Twelve Gazes E01 VU-011 / VU-012, synthetic fixture).

Only units whose camera plans carry the camera_grammar stamp change; unstamped units are byte-identical.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import unittest

from tools.h3_provider_prompt_renderer import director_active, render_h3_prompt
from tools.provider_contract_boundary import compact_identity_prop_fact
from tools.tests.test_h3_shot_scope_v1 import A, TRACK, build

MARK = {"camera_grammar": "CAMERA_GRAMMAR_V1"}
ARBITER = {
    "prop": "Arbiter", "prop_id": "PROP-ARBITER", "kind": "CREATURE",
    "note": "faceless 2.4 m two-armed matte-obsidian humanoid with a mirror-black oval face",
    "creature_card": {"locomotion": "biped", "eye_color": "none", "silhouette_ref": "REF-ARBITER"},
}
NOTEBOOK = {"prop": "leather notebook", "prop_id": "PROP-NOTEBOOK"}
WARDROBE = {"characters": [{"character": "阿尔", "character_id": A,
                            "authored_description": "a worn black cassock with a white clerical collar"}]}
CAMERA = {**TRACK, "shot_scale": "EXTREME_CLOSE_UP", "end_framing": "Framing changes with the camera motion."}


def vu011(*, stamped: bool) -> tuple[dict, dict]:
    unit, plan = build([{"cast": [A]}], camera_plan={**CAMERA, **(MARK if stamped else {})})
    unit["ordered_prompt_specs"][0]["props"] = [deepcopy(NOTEBOOK), deepcopy(ARBITER) if stamped else
                                                {k: ARBITER[k] for k in ("prop", "prop_id", "note")}]
    unit["wardrobe_contract"] = deepcopy(WARDROBE)
    unit["provider_scope_projection"]["visible_living_entity_instance_total"] = 2
    return unit, plan


def vu012(*, stamped: bool) -> tuple[dict, dict]:
    unit, plan = build([{"cast": []}], camera_plan={**CAMERA, **(MARK if stamped else {})})
    unit["reference_images"] = [{"path": "plate.png", "role": "LOCATION_REFERENCE"}]
    unit["provider_scope_projection"]["visible_living_entity_instance_total"] = 0
    unit["ordered_prompt_specs"][0]["props"] = [{"prop": "twelve dim points of light", "prop_id": "PROP-POINTS"}]
    return unit, plan


class DirectorPromptTest(unittest.TestCase):
    def test_switch_follows_the_camera_grammar_stamp(self):
        self.assertTrue(director_active(*vu011(stamped=True)))
        self.assertFalse(director_active(*vu011(stamped=False)))

    def test_creature_is_a_subject_with_its_look_and_wardrobe_in_words(self):
        text, _ = render_h3_prompt(*vu011(stamped=True))
        roster = next(line for line in text.splitlines() if line.startswith("cast_roster: "))
        self.assertIn("The only subjects in this clip are Alpha and Arbiter", roster)
        self.assertIn("Alpha wears a worn black cassock with a white clerical collar", roster)
        self.assertIn("Arbiter is a non-human subject, not a prop: faceless 2.4 m two-armed matte-obsidian "
                      "humanoid with a mirror-black oval face; moves upright on two legs.", roster)
        self.assertNotIn("eyes: none", roster)
        self.assertNotIn("leather notebook", roster)  # a real prop stays a prop
        self.assertIn("Each subject wears only its own clothing; never transfer clothing, collars, hands or "
                      "materials between subjects", roster)
        self.assertIn("No other people, figures, silhouettes, hands or body parts appear anywhere in frame, "
                      "including the background and frame edges", roster)

    def test_identity_fact_lists_beings_apart_from_props(self):
        unit, _ = vu011(stamped=True)
        fact, lineage = compact_identity_prop_fact(unit)
        self.assertIn("非人主体=Arbiter；关键道具=leather notebook", fact)
        self.assertEqual(lineage["beings"], ["Arbiter"])
        legacy, legacy_lineage = compact_identity_prop_fact(vu011(stamped=False)[0])
        self.assertIn("关键道具=leather notebook、Arbiter", legacy)
        self.assertNotIn("beings", legacy_lineage)

    def test_preproduction_stamps_only_beings(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lines" / "nalu" / "runtime" / "tools"))
        import build_nalu_preproduction as pre
        card = ARBITER["creature_card"]
        self.assertEqual(pre._being_fields({"kind": "CREATURE", "creature_card": card}),
                         {"kind": "CREATURE", "creature_card": card})
        self.assertEqual(pre._being_fields({"kind": "PROP", "name": "leather notebook"}), {})

    def test_boilerplate_end_framing_dropped_camera_line_kept(self):
        text, _ = render_h3_prompt(*vu011(stamped=True))
        camera = text.split("\ncamera: ", 1)[1].split("\n", 1)[0]
        self.assertNotIn("Framing changes", camera)
        self.assertIn("start framing: Beta enters frame left at the doorway", camera)
        self.assertIn("a motivated move", camera)

    def test_object_insert_has_no_people(self):
        text, _ = render_h3_prompt(*vu012(stamped=True))
        self.assertIn("vertical 9:16 a single photographic insert shot of twelve dim points of light; "
                      "no people, no hands, no body parts;", text)
        self.assertNotIn("live-action short drama", text)
        self.assertNotIn("cast_roster:", text)

    def test_overlong_prompt_trims_the_roster_instead_of_failing(self):
        unit, plan = vu011(stamped=True)
        full, _ = render_h3_prompt(unit, plan)
        # the CAMERA_GRAMMAR_V1 audio lines are dropped first, then the roster looks
        unit["h3_provider_english_contract"]["space_weather_fact"] = "x" * (10_100 - len(full))
        text, _ = render_h3_prompt(unit, plan)
        self.assertLessEqual(len(text), 10_000)
        self.assertNotIn("No background music", text)
        self.assertIn("cassock", text)
        # (+250: the 2026-10-26 provider-expert voice clause made the droppable audio lines longer)
        unit["h3_provider_english_contract"]["space_weather_fact"] = "x" * (10_250 - len(full))
        text, _ = render_h3_prompt(unit, plan)
        self.assertLessEqual(len(text), 10_000)
        self.assertIn("Arbiter is a non-human subject, not a prop.", text)
        self.assertNotIn("cassock", text)

    def test_unstamped_units_are_byte_identical(self):
        # sha256 of the origin/main (df6e19b) renderer output for the same unstamped fixtures
        pinned = {vu011: "971d2a98c3ed301ac8cfaaa190267b19cfec6c50eeec945beada0b00ef5437ca",
                  vu012: "ee28d66c87057d6c3969fb71a54cdd37e9bf09c0a19ee5110a02d3fa64a9318d"}
        for fixture, digest in pinned.items():
            text, _ = render_h3_prompt(*fixture(stamped=False))
            self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), digest, fixture.__name__)
            self.assertIn("live-action short drama", text)
            self.assertIn("Framing changes with the camera motion", text)
            self.assertNotIn("cast_roster:", text)


if __name__ == "__main__":
    unittest.main()
