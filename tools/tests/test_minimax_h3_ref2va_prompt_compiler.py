import unittest

from tools.minimax_h3_ref2va_prompt_compiler import (
    H3_OFFICIAL_REF2VA_PROFILE,
    REQUIRED_CONSTRAINT_COVERAGE,
    compile_h3_official_ref2va_prompt,
    validate_h3_official_ref2va_prompt,
)
from tools.tests.test_video_prompt_compiler import h3_unit
from tools.video_prompt_compiler import compile_model_prompt


def official_contract(*, dialogue: bool = True, refs=None):
    refs = refs or ["one.png", "two.png"]
    speaker_defs = [
        "<Audio 1> is the voice-timbre reference for <Subject 1> (S1).",
    ] if dialogue else []
    spoken = (
        "<Subject 1> (S1) uses the measured adult voice timbre referenced from <Audio 1> and says, "
        "<d>[Chinese]陈迹。</d> The speaker closes the lips completely after the final syllable."
        if dialogue else
        "<Subject 1> keeps the lips closed and produces no speech at any point in the video."
    )
    # 375 provider-facing English words.  Each sentence carries an existing
    # production concern; the padding is intentional so the official
    # generation-detail range is enforced without deleting prior H3 gates.
    detail_sentences = [
        "The target video uses vertical live-action period-drama photography with natural skin, textured fabric, restrained contrast, and a stable cool morning palette.",
        "[Shot 1] The shot begins from <Picture 1> in a medium close composition and preserves the same adult identity, facial structure, hairstyle, ivory outer robe, pale-blue inner layer, red fastening cord, and worn footwear shown by the reference.",
        "The courtyard map remains fixed, with the carriage on frame left, the clinic doorway on frame right, the stone path running between them, and every actor remaining on the established side of the one-hundred-eighty-degree axis.",
        "The curtain remains owned by <Subject 1>; the visible shoulder, upper arm, elbow, forearm, wrist, palm, and fingers stay anatomically connected while the hand lifts the fabric, and no limb emerges from the carriage wall or foreground occlusion.",
        "The movement follows one physical chain: fingertips take the curtain weight, the wrist rises, the elbow follows, the cloth tension changes, the curtain slides sideways, and the body settles into the resulting pose without a reset, loop, frozen tableau, or speed ramp.",
        "A slow shallow push-in is motivated by the character discovering the doorway and never circles the subject, reverses direction, crosses the axis, or changes lens language without a story reason.",
        "The eyes move first toward the doorway, the pupils settle, the jaw tightens once, the shoulder follows, and quiet breathing continues after the single microexpression change instead of repeating it.",
        spoken,
        "Any listener or background figure remains silent, keeps a closed mouth, never inherits the speaking voice, never performs the principal hand action, and never exchanges identity, wardrobe, position, prop ownership, or screen direction with <Subject 1>.",
        "The incoming state preserves the previous unit's eye line, cloth inertia, body weight, weather, room tone, and causal result; the ending leaves a settled curtain edge, continuous breath, fabric micro-motion, and matching ambience for the next unit's safe cut.",
        "Natural location audio remains synchronized to visible causes: light wind, distant street life, cloth friction, sleeve movement, one small contact sound at the curtain edge, and no unexplained voice, narration, singing, replacement track, or external score.",
        "Every wall, sign surface, garment, curtain, carriage panel, and background object remains blank and unmarked, with no captions, subtitles, labels, interface graphics, logos, watermarks, letters, numerals, or readable writing.",
        "Lighting direction, exposure, rain or wind continuity, skin tone, prop scale, costume color, and foreground-background depth remain continuous until the final frame, while the camera preserves enough tail motion for a media-safe transition.",
        "The final image holds the completed causal result through natural breathing and residual cloth motion, not through a freeze frame, and the native ambience continues cleanly beyond the last visible gesture.",
    ]
    return {
        "subject_definitions": [
            "<Subject 1> is the adult period-drama character whose identity, wardrobe, anatomy, and carriage-side position come from <Picture 1> and <Picture 2>.",
            "<Subject 2> is the clinic courtyard environment whose map, doorway, carriage, stone path, weather, and light direction come from <Picture 1> and <Picture 2>.",
            "<Picture 1> is the opening composition anchor for [Shot 1].",
            "<Picture 2> is the result-state and continuity anchor for [Shot 1].",
            *speaker_defs,
        ],
        "summary": (
            "[reference generation + keyframe completion + audio reference] The target video is a six-second vertical live-action period-drama unit that preserves <Subject 1> and <Subject 2>, begins from <Picture 1>, reaches the result state in <Picture 2>, and uses the supplied audio only as a voice-timbre reference."
            if dialogue else
            "[reference generation + keyframe completion] The target video is a six-second silent vertical live-action period-drama unit that preserves <Subject 1> and <Subject 2>, begins from <Picture 1>, and reaches the result state in <Picture 2>."
        ),
        "retention_analysis": [
            "<Subject 1> (appears in [Shot 1]): fully_preserved - identity, wardrobe, anatomy, action ownership, and screen position remain unchanged.",
            "<Subject 2> (appears in [Shot 1]): fully_preserved - map geometry, weather, props, lighting, and screen direction remain unchanged.",
            "<Picture 1> ([Shot 1] first frame): fully_preserved - opening composition and subject placement are retained.",
            "<Picture 2> ([Shot 1] result state): fully_preserved - the terminal physical state is reached without interpolating a static tableau.",
            *(
                ["<Audio 1>: reference - only timbre, rhythm, emotion, and delivery guide <Subject 1> (S1); the original dialogue content is not carried into the target video."]
                if dialogue else []
            ),
        ],
        "detailed_description": "\n".join(detail_sentences),
        "overall_soundscape": "Natural courtyard wind, distant street ambience, cloth friction, sleeve movement, and one synchronized curtain contact continue without dialogue repetition.",
        "non_diegetic_music": "N/A",
        "constraint_coverage": {key: True for key in REQUIRED_CONSTRAINT_COVERAGE},
        "speaker_subject_bindings": {"白鲤": "<Subject 1>"} if dialogue else {},
        "reference_text_audit": {
            "status": "PASS_TEXT_FREE_REFERENCES",
            "picture_count": len(refs),
            "rows": [
                {
                    "picture_index": index,
                    "reference_image": value,
                    "reference_sha256": f"sha-{index}",
                    "readable_text_detected": False,
                    "character_like_marks_detected": False,
                    "evidence_ref": f"qa/reference-{index}.json",
                }
                for index, value in enumerate(refs, 1)
            ],
        },
    }


class H3OfficialRef2VATest(unittest.TestCase):
    def test_dialogue_uses_exact_official_six_section_grammar(self):
        unit = h3_unit(dialogue="白鲤：陈迹。")
        unit["h3_prompt_profile"] = H3_OFFICIAL_REF2VA_PROFILE
        unit["h3_ref2va_contract"] = official_contract(
            dialogue=True, refs=unit["reference_images"]
        )
        text = compile_model_prompt(unit)
        report = validate_h3_official_ref2va_prompt(
            text, source_id=unit["unit_id"], unit=unit
        )
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertEqual(text.count("<d>[Chinese]陈迹。</d>"), 1)
        self.assertNotIn("ROLE_LOCK", text)
        self.assertNotRegex(text.replace("<d>[Chinese]陈迹。</d>", ""), r"[\u3400-\u9fff]")
        positions = [text.index(field) for field in (
            "subject_definitions:", "summary:", "retention_analysis:",
            "detailed_description:", "overall_soundscape:", "non_diegetic_music:",
        )]
        self.assertEqual(positions, sorted(positions))

    def test_silent_unit_has_no_dialogue_or_speaker_id(self):
        unit = h3_unit()
        unit["h3_prompt_profile"] = H3_OFFICIAL_REF2VA_PROFILE
        unit["h3_ref2va_contract"] = official_contract(
            dialogue=False, refs=unit["reference_images"]
        )
        text = compile_h3_official_ref2va_prompt(unit)
        self.assertNotIn("<d>", text)
        self.assertNotRegex(text, r"\(S\d+\)")
        self.assertIn("lips closed and produces no speech", text)

    def test_missing_existing_constraint_fails_closed(self):
        unit = h3_unit(dialogue="白鲤：陈迹。")
        unit["h3_prompt_profile"] = H3_OFFICIAL_REF2VA_PROFILE
        unit["h3_ref2va_contract"] = official_contract(
            dialogue=True, refs=unit["reference_images"]
        )
        unit["h3_ref2va_contract"]["constraint_coverage"]["map"] = False
        with self.assertRaisesRegex(ValueError, "CONSTRAINT_COVERAGE_MISSING"):
            compile_h3_official_ref2va_prompt(unit)

    def test_missing_reference_text_audit_fails_closed(self):
        unit = h3_unit(dialogue="白鲤：陈迹。")
        unit["h3_prompt_profile"] = H3_OFFICIAL_REF2VA_PROFILE
        unit["h3_ref2va_contract"] = official_contract(
            dialogue=True, refs=unit["reference_images"]
        )
        del unit["h3_ref2va_contract"]["reference_text_audit"]
        with self.assertRaisesRegex(ValueError, "REFERENCE_TEXT_AUDIT_MISSING"):
            compile_h3_official_ref2va_prompt(unit)

    def test_character_like_marks_in_reference_fail_closed(self):
        unit = h3_unit(dialogue="白鲤：陈迹。")
        unit["h3_prompt_profile"] = H3_OFFICIAL_REF2VA_PROFILE
        unit["h3_ref2va_contract"] = official_contract(
            dialogue=True, refs=unit["reference_images"]
        )
        unit["h3_ref2va_contract"]["reference_text_audit"]["rows"][0][
            "character_like_marks_detected"
        ] = True
        with self.assertRaisesRegex(ValueError, "REFERENCE_CHARACTER_MARKS_PRESENT"):
            compile_h3_official_ref2va_prompt(unit)


if __name__ == "__main__":
    unittest.main()
