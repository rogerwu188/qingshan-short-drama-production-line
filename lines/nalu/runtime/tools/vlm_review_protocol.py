#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vlm_review_protocol.py — the machine-review contract for the nalu line.

Why this exists
---------------
Roger's standing policy is that the line runs continuously with a human check
only after a finished episode.  Every per-asset QA therefore has to be a MACHINE
review.  Where the engine owns a deterministic measurer (insightface cosine,
RapidOCR, ffmpeg/ffprobe, faster-whisper) that measurer runs for real.  What no
measurer can answer — "is this the entry_state and not the completion_state?",
"is the declared cast exactly what is visible?" — is answered by a Claude
reviewer process that actually LOOKS at the image or the contact sheet and fills
in a closed questionnaire.

This module is the contract between the pipeline and that reviewer:

    request  — the pipeline writes a review request: the media paths (with their
               exact sha256), the AUTHORITATIVE expectations read out of the
               authored layers, and a closed questionnaire with enumerated
               answers.  Nothing in the request is derived from the media.
    submit   — the reviewer's answers are validated (every item answered, only
               enumerated values, a real free-text observation per item, an
               explicit defect list) and then materialised into ENGINE-FORMAT
               evidence by the per-kind materialiser (identity_qa_lock.py,
               keyframe_q1_builder.py, start_frame_evidence_writer.py,
               post_generation_qa_runner.py).

Honesty rules that are enforced in code, not by convention:
  * ``reviewer`` must be exactly ``claude-code-nalu-vlm``.
  * the answers must be bound to the request's exact sha256.
  * ``--example-answers`` emits a template whose every value is ``null`` and
    which carries a refusal marker, so it can never be mistaken for a review;
    ``submit`` rejects that marker and rejects any remaining ``null``.
  * an item with any FAIL answer, or any P0/P1 defect, is a FAIL/REJECT and
    produces a reroll request.  A PASS cannot be written without answers.
  * a free-text observation shorter than 20 characters is not an observation.

CLI
---
  request         --kind identity|keyframe|start_frame|post_gen_plot|video_q2 --episode EP
                  [--items <json>] [--out <path>]
  example-answers --request <file> [--out <path>]
  submit          --request <file> --answers <json> [--out <path>]
                  [--no-materialise]
  questionnaire   --kind <kind>

Exit codes
----------
  0  request written / answers valid and materialised, every item PASS
  2  invalid answers (validation failure) — nothing materialised
  3  materialisation error
  5  answers valid but at least one item FAILed → reroll requested
"""

from __future__ import annotations
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nalu_qa_common import (  # noqa: E402
    KINDS, MIN_OBSERVATION_CHARS, REVIEWER_ID, REVIEW_METHOD, REVIEWS_ROOT,
    SCHEMA_ANSWERS, SCHEMA_REQUEST, SCHEMA_SUBMITTED, TEMPLATE_MARKER,
    Expectations, QaPaths, canonical_sha256, find_scoped_operator_source, now,
    read_json, run_id, sha256_file, write_json,
)

TOOL_ID = "vlm_review_protocol.v1"

PASS_ANSWERS = {"PASS", "YES", "NOT_APPLICABLE"}
FAIL_ANSWERS = {"FAIL", "NO"}
#: UNCERTAIN is never a pass.  A reviewer that cannot tell has found a defect in
#: the asset's legibility, and the item is rejected so a human or a reroll
#: resolves it rather than the pipeline guessing.
UNCERTAIN_ANSWERS = {"UNCERTAIN"}

PF = ["PASS", "FAIL", "UNCERTAIN"]
PFN = ["PASS", "FAIL", "NOT_APPLICABLE", "UNCERTAIN"]
YN = ["YES", "NO", "UNCERTAIN"]

SEVERITIES = ("P0", "P1", "P2")

# --------------------------------------------------------------------------- #
# the questionnaires — closed, contract-derived, one per kind
# --------------------------------------------------------------------------- #
# ``maps_to`` records which registered engine gate / evidence field each answer
# feeds, so the materialisers never have to guess and an auditor can trace a
# PASS back to the question that earned it.
QUESTIONNAIRES: dict[str, dict[str, dict[str, Any]]] = {
    "identity": {
        "appearance_matches_script": {
            "enum": PF, "maps_to": ["asset_library.qa.checks.APPEARANCE"],
            "question": "Do the plates show the person/object described in expectations.appearance "
                        "(face, hair, build, distinguishing features), with no contradiction?"},
        "apparent_age_in_declared_range": {
            "enum": PFN, "maps_to": ["asset_library.qa.checks.AGE"],
            "question": "Is the apparent age inside expectations.apparent_age_range? "
                        "NOT_APPLICABLE only for a non-character asset."},
        "sex_presentation_matches": {
            "enum": PFN, "maps_to": ["asset_library.qa.checks.SEX"],
            "question": "Does the presented sex match expectations.sex? "
                        "NOT_APPLICABLE only for a non-character asset."},
        "all_required_views_present": {
            "enum": PF, "maps_to": ["asset_library.qa.checks.CARD_DELIVERABLES"],
            "question": "Is every view in expectations.card_deliverables actually present "
                        "among the supplied plates?"},
        "single_subject_no_clone_no_extra_person": {
            "enum": PF, "maps_to": ["asset_library.qa.checks.SINGLE_SUBJECT"],
            "question": "Does each plate show exactly one subject, with no duplicated/cloned "
                        "face and no additional person in frame?"},
        "identity_consistent_across_views": {
            "enum": PF, "maps_to": ["asset_library.qa.checks.CROSS_VIEW_IDENTITY"],
            "question": "Is it the same individual in every view (face geometry, hair, "
                        "skin tone, build), not a family resemblance?"},
        "wardrobe_matches_bible": {
            "enum": PFN, "maps_to": ["asset_library.qa.checks.WARDROBE"],
            "question": "Does the clothing match expectations.wardrobe "
                        "(outer_layer, inner_layer, colours, material, condition, footwear)?"},
        "palette_and_lighting_match_visual_culture": {
            "enum": PF, "maps_to": ["asset_library.qa.checks.VISUAL_CULTURE"],
            "question": "Do palette, skin rendering and lighting match "
                        "expectations.visual_culture_palette?"},
        "no_forbidden_influence_visible": {
            "enum": PF, "maps_to": ["asset_library.qa.checks.FORBIDDEN_INFLUENCE"],
            "question": "Is every item in expectations.forbidden_influences absent from every plate?"},
        "no_text_logo_watermark_or_subtitle": {
            "enum": PF, "maps_to": ["asset_library.qa.checks.NO_BURNED_TEXT"],
            "question": "Is the plate free of burned-in text, captions, logos, watermarks and "
                        "signatures?"},
        "framing_and_aspect_ratio_correct": {
            "enum": PF, "maps_to": ["asset_library.qa.checks.FRAMING"],
            "question": "Is the aspect ratio expectations.aspect_ratio and is the subject framed "
                        "as the named deliverable requires (headshot / bust / full body)?"},
        "face_unobstructed_and_in_focus": {
            "enum": PFN, "maps_to": ["asset_library.qa.checks.FACE_USABLE",
                                     "CHARACTER-IDENTITY-ADMISSION.canonical_reference_usability"],
            "question": "Is the face unobstructed, in focus and large enough to be a canonical "
                        "identity reference?  NOT_APPLICABLE only for a non-character asset."},
        "plate_is_photographic_not_illustrated": {
            "enum": PF, "maps_to": ["asset_library.qa.checks.REALISM"],
            "question": "Is the plate photographic (real skin microtexture, natural asymmetry, "
                        "motivated light) rather than illustrated, plastic or beauty-filtered?"},
    },
    "keyframe": {
        "shows_entry_state_only": {
            "enum": PF, "maps_to": ["ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"],
            "question": "Does the frame show expectations.entry_state ONLY, with "
                        "expectations.forbidden_completion_state not yet visible "
                        "(see expectations.still_prompt_contract)?"},
        "cast_exactly_as_declared": {
            "enum": PF, "maps_to": ["ACTION-SHOT-DESIGN-AND-STATE-HANDOFF",
                                    "CHARACTER-IDENTITY-ADMISSION"],
            "question": "Is every character in expectations.required_visible_characters visible, "
                        "and is NO undeclared person visible?"},
        "screen_slots_and_depth_planes_match": {
            "enum": PFN, "maps_to": ["ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"],
            "question": "Does each cast member occupy the declared screen_slot and depth_plane?"},
        "props_exactly_as_declared": {
            "enum": PF, "maps_to": ["ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"],
            "question": "Is every prop in expectations.required_visible_props visible, and is no "
                        "undeclared story prop present?"},
        "space_anchors_match": {
            "enum": PF, "maps_to": ["SCENE-AUTHORITY-LOCK"],
            "question": "Is the depicted place the declared expectations.space "
                        "(location + subspace), with the mapped fixed elements in their "
                        "mapped relationship?"},
        "camera_framing_and_axis_match": {
            "enum": PF, "maps_to": ["SCENE-AUTHORITY-LOCK",
                                    "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"],
            "question": "Do shot size, angle and axis match expectations.camera / shot_size / axis?"},
        "lighting_palette_and_time_match": {
            "enum": PF, "maps_to": ["SCENE-AUTHORITY-LOCK"],
            "question": "Do the lighting, palette, time of day and weather match "
                        "expectations.scene_state / key_light / palette / atmosphere?"},
        "wardrobe_matches_bible": {
            "enum": PFN, "maps_to": ["ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"],
            "question": "Does each visible character's clothing match expectations.wardrobe?"},
        "no_anachronism_from_closed_set": {
            "enum": PF, "maps_to": ["PERIOD-ANACHRONISM-LOCK"],
            "question": "Is every term in closed_vocabulary.forbidden_terms absent from the frame?"},
        "no_burned_in_text_or_subtitle": {
            "enum": PF, "maps_to": ["PERIOD-ANACHRONISM-LOCK", "FINAL-OCR-POLICY"],
            "question": "Is the frame free of burned-in text, subtitles, logos and watermarks?"},
        "each_visible_character_identity_recognisable": {
            "enum": PFN, "maps_to": ["CHARACTER-IDENTITY-ADMISSION"],
            "question": "Is each visible character recognisably the locked identity plate person? "
                        "NOT_APPLICABLE when no character is declared visible."},
        "action_role_topology_readable": {
            "enum": PFN, "maps_to": ["ACTION-SHOT-DESIGN-AND-STATE-HANDOFF",
                                     "qingshan.exact_output_action_role_verification.v1"],
            "question": "Can the initiator, the target and the prop owner be read off the frame "
                        "without ambiguity?  NOT_APPLICABLE for a unit with no physical "
                        "interaction."},
        "no_freeze_reset_or_replay_cue": {
            "enum": PF, "maps_to": ["ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"],
            "question": "Is the frame a genuine single-beat start (no mid-action freeze, no "
                        "reset to a previous state, no replay of an earlier beat)?"},
        "no_p0_defect_present": {
            "enum": PF, "maps_to": ["DEFECT-TIER-TOLERANCE"],
            "question": "Is the frame free of any P0 defect (wrong person, wrong place, "
                        "anachronism, burned-in text, anatomical break, cloned face)?"},
    },
    "start_frame": {
        "entry_state_only": {
            "enum": PF, "maps_to": ["start_frame_semantic_evidence.entry_state"],
            "question": "Does the frame show expectations.entry_state ONLY "
                        "(see expectations.start_frame_must_show_only_entry_state)?"},
        "camera_start_framing_match": {
            "enum": YN, "maps_to": ["start_frame_semantic_evidence.camera_start_framing_match"],
            "question": "Does the frame's opening framing match "
                        "expectations.camera_start_framing?"},
        "space_match": {
            "enum": YN, "maps_to": ["start_frame_semantic_evidence.space_match"],
            "question": "Is the frame in the mapped start space, i.e. every anchor in "
                        "expectations.required_space_anchors is actually visible/identifiable?"},
        "empty_establishing_frame": {
            "enum": YN, "maps_to": ["start_frame_semantic_evidence.empty_establishing_frame"],
            "question": "Is this an empty establishing frame with NO living character visible? "
                        "Answer YES only when no person is visible at all."},
        "all_required_characters_visible": {
            "enum": PFN, "maps_to": ["start_frame_semantic_evidence.observed_visible_characters"],
            "question": "Is every name in expectations.required_visible_characters visible? "
                        "NOT_APPLICABLE when that list is empty."},
        "all_required_props_visible": {
            "enum": PFN, "maps_to": ["start_frame_semantic_evidence.observed_visible_props"],
            "question": "Is every name in expectations.required_visible_props visible? "
                        "NOT_APPLICABLE when that list is empty."},
    },
    "action_role": {
        # shot_media_admission_gate._validate_action_role_verification: interaction_state,
        # initiator_entity_id, target_entity_id, forbidden_role_reversal, prop_ownership
        "interaction_state": {
            "enum": ["PRE_CONTACT", "CONTACT_RESULT", "BRIDGE_STATE_NO_ACTION_OWNER_VISIBLE", "UNCERTAIN"],
            "maps_to": ["action_role_verification.interaction_state"],
            "question": "At this START frame, has the unit's expectations.primary_action already "
                        "made contact?  PRE_CONTACT = not yet (entry state); CONTACT_RESULT = the "
                        "contact/result is already visible; BRIDGE_STATE_NO_ACTION_OWNER_VISIBLE = "
                        "no character who could own the action is visible (empty or bridge frame)."},
        "initiator_is_expected_entity": {
            "enum": PFN, "maps_to": ["action_role_verification.initiator_entity_id"],
            "question": "Is the entity positioned/poised to perform expectations.primary_action "
                        "the declared expectations.initiator_entity_id (same person as the locked "
                        "identity, not another character)?  NOT_APPLICABLE when initiator_kind is "
                        "ENVIRONMENT or the initiator is declared not visible at entry."},
        "target_is_expected_entity": {
            "enum": PFN, "maps_to": ["action_role_verification.target_entity_id"],
            "question": "Is the receiver of the action the declared expectations.target_entity_id "
                        "(a character, or the mapped fixed element / space)?  NOT_APPLICABLE when "
                        "the target is not visible at entry by contract."},
        "no_role_reversal": {
            "enum": PF, "maps_to": ["action_role_verification.forbidden_role_reversal"],
            "question": "Are the roles NOT reversed — the frame does not show the target acting on "
                        "the initiator, nor a different character owning the action or the props?"},
        "prop_ownership_as_expected": {
            "enum": PFN, "maps_to": ["action_role_verification.prop_ownership"],
            "question": "For every entry in expectations.props, is the prop held / carried / "
                        "positioned by the character the entry_state and primary_action imply "
                        "(list who owns what in observed_prop_owners)?  NOT_APPLICABLE when "
                        "expectations.props is empty."},
        "creature_locomotion_matches_card": {
            "enum": PFN, "maps_to": ["ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"],
            "question": "If a creature with a card is in the frame (expectations.creature_cards), does "
                        "its locomotion (biped / quadruped) and eye colour match the card?  "
                        "NOT_APPLICABLE when no carded creature is in the frame."},
    },
    "post_gen_plot": {
        # exactly the five checks post_generation_qa_scope_gate.py ALLOWS as
        # basic-plot checks — no sixth, and nothing from its forbidden list.
        "episode_scene_correspondence": {
            "enum": PF, "maps_to": ["post_generation_qa.basic_plot.episode_scene_correspondence"],
            "question": "Does the clip depict expectations.scene_id / narrative_beat, i.e. the "
                        "scene the script assigns to this unit and not another scene?"},
        "principal_character_presence": {
            "enum": PFN, "maps_to": ["post_generation_qa.basic_plot.principal_character_presence"],
            "question": "Is every name in expectations.principal_characters present in the clip? "
                        "NOT_APPLICABLE for a unit with no character."},
        "major_event_presence": {
            "enum": PF, "maps_to": ["post_generation_qa.basic_plot.major_event_presence"],
            "question": "Does every ordered_beats primary_action actually happen, ending in its "
                        "completion_state?"},
        "major_dialogue_presence": {
            "enum": PFN, "maps_to": ["post_generation_qa.basic_plot.major_dialogue_presence"],
            "question": "Is every line in expectations.expected_dialogue spoken by the right "
                        "character?  NOT_APPLICABLE for a unit with no dialogue."},
        "chronological_unit_order": {
            "enum": PF, "maps_to": ["post_generation_qa.basic_plot.chronological_unit_order"],
            "question": "Do the beats run in the script's order (expectations.ordered_beats), with "
                        "no reordering, loop or replay, consistent with "
                        "expectations.chronological_position?"},
        # seq=19 (E04 review): "does the contract hold up" questions the audience answers in
        # 3 seconds.  Automatic detection is NOT_IMPLEMENTED; the reviewer answers from the clip.
        "action_outcome_visible": {
            "enum": PFN, "maps_to": ["post_generation_qa.basic_plot.action_outcome_visible"],
            "question": "If this unit ends an ACTION beat (expectations.beat_type == action), is the "
                        "declared outcome (expectations.action_outcome: hit / injury / escape / loss / "
                        "win) actually visible on screen by the end of the clip, so a viewer knows what "
                        "the action achieved?  NOT_APPLICABLE when the unit is not an action beat."},
        "antagonist_motive_readable": {
            "enum": PFN, "maps_to": ["post_generation_qa.basic_plot.antagonist_motive_readable"],
            "question": "If an antagonist group acts for the first time in this unit "
                        "(expectations.antagonist_first_action), can a first-time viewer tell WHO they "
                        "are and WHY they act, from what the episode has shown or said so far?  "
                        "NOT_APPLICABLE otherwise."},
        "new_entity_purpose_readable": {
            "enum": PFN, "maps_to": ["post_generation_qa.basic_plot.new_entity_purpose_readable"],
            "question": "If an entity (person, creature, animal, prop) appears for the first time in "
                        "this unit (expectations.new_entities), does the clip or the episode so far make "
                        "its purpose readable (set-up or pay-off), rather than looking like footage "
                        "from another story?  NOT_APPLICABLE when nothing new appears."},
    },
    # ----------------------------------------------------------- Q2 video
    # The Q2 VIDEO_ASSEMBLY content review (D-7).  shot_media_admission_gate.py
    # in VIDEO_ASSEMBLY mode needs a VLM_STRUCTURED_STATE_QA_V1 objective block
    # for ACTION-SHOT-DESIGN-AND-STATE-HANDOFF and a closed-set anachronism
    # answer for PERIOD-ANACHRONISM-LOCK, and a SCENE-AUTHORITY-LOCK finding.
    # Every question below is inside post_generation_qa_scope_gate.py's allowed
    # scope: none of its sixteen FORBIDDEN_POST_GENERATION_CHECKS (gesture,
    # microexpression, choreography, prop trajectory, camera action detail,
    # optical flow, motion energy, velocity, freeze-ratio families) is asked.
    # Reviewed at ORIGINAL RESOLUTION: the request carries the 720x1280 mp4
    # itself plus the extracted original-resolution frames, not only a sheet.
    "video_q2": {
        "cast_exactly_as_declared": {
            "enum": PF, "maps_to": ["ACTION-SHOT-DESIGN-AND-STATE-HANDOFF",
                                    "CHARACTER-IDENTITY-ADMISSION"],
            "question": "Across the whole clip, is exactly the declared cast present — every "
                        "name in expectations.required_visible_characters visible and NO "
                        "additional or duplicated person?"},
        "each_visible_character_identity_recognisable": {
            "enum": PFN, "maps_to": ["CHARACTER-IDENTITY-ADMISSION"],
            "question": "Is every visible character the same person as its canonical identity "
                        "plate for the entire clip (no face swap, no age/sex drift, no "
                        "double)?  "
                        "NOT_APPLICABLE only for a unit with no declared visible character."},
        "space_anchors_match": {
            "enum": PF, "maps_to": ["SCENE-AUTHORITY-LOCK"],
            "question": "Do the mapped space anchors in expectations.required_space_anchors stay "
                        "the declared place for the whole clip, with no cut to another location?"},
        "camera_axis_stable_and_declared": {
            "enum": PF, "maps_to": ["SCENE-AUTHORITY-LOCK",
                                    "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"],
            "question": "Does the clip keep the declared camera axis and framing "
                        "(expectations.camera / camera_start_framing) without an axis jump or a "
                        "180-degree flip?  This asks about the AXIS only, not motion detail."},
        "lighting_palette_and_time_match": {
            "enum": PF, "maps_to": ["SCENE-AUTHORITY-LOCK"],
            "question": "Do key light, palette and time-of-day match expectations.key_light / "
                        "palette / scene_state for the whole clip?"},
        "declared_state_handoff_completes": {
            "enum": PF, "maps_to": ["ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"],
            "question": "Does the clip START in expectations.entry_state and END in "
                        "expectations.required_completion_state, running the ordered_beats "
                        "primary_action in between?  This asks WHETHER the declared state "
                        "handoff happens, never how well any gesture is performed."},
        "props_present_and_end_state_as_declared": {
            "enum": PFN, "maps_to": ["ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"],
            "question": "Is every prop in expectations.required_visible_props present, in the "
                        "declared count, and in its declared end state?  This asks about "
                        "PRESENCE, COUNT and END STATE only — not trajectory precision.  "
                        "NOT_APPLICABLE for a unit with no declared prop."},
        "wardrobe_matches_bible": {
            "enum": PFN, "maps_to": ["ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"],
            "question": "Does every visible character wear the wardrobe_bible garment in "
                        "expectations.wardrobe throughout, with no mid-clip change?  "
                        "NOT_APPLICABLE for a unit with no visible character."},
        "no_anachronism_from_closed_set": {
            "enum": PF, "maps_to": ["PERIOD-ANACHRONISM-LOCK"],
            "question": "Is every term in closed_vocabulary.forbidden_terms absent from every "
                        "frame of the clip (no modern object, no out-of-period material)?"},
        "no_burned_in_text_or_subtitle": {
            "enum": PF, "maps_to": ["PERIOD-ANACHRONISM-LOCK"],
            "question": "Is the clip free of any burned-in caption, subtitle, watermark, logo, "
                        "pseudo-glyph or Latin lettering in every frame?"},
        "no_extra_scene_or_replayed_beat": {
            "enum": PF, "maps_to": ["ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"],
            "question": "Does the clip contain only this unit's declared beats — no invented "
                        "extra scene, no beat replayed, no reset back to the entry state?"},
        # seq=19 (E04 review): perceived state / count / creature form are answered by the
        # reviewer from the clip; the engine cannot measure them (NOT_IMPLEMENTED).
        "perceived_life_state_matches_declared": {
            "enum": PFN, "maps_to": ["ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"],
            "question": "For every visible character, does the state a viewer READS from the clip "
                        "(alive / injured / unconscious / dead — a motionless body with blood reads "
                        "as dead) match expectations.life_states?  NOT_APPLICABLE when no character "
                        "is visible."},
        "visible_group_count_matches_declared": {
            "enum": PFN, "maps_to": ["ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"],
            "question": "Is the number of people of each declared group (expectations.group_counts) "
                        "exactly as declared throughout the clip — no extra body, no missing member?  "
                        "NOT_APPLICABLE when no group count is declared."},
        "creature_locomotion_matches_card": {
            "enum": PFN, "maps_to": ["ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"],
            "question": "If a creature with a card is visible (expectations.creature_cards), does its "
                        "locomotion (biped / quadruped) and eye colour match the card in every frame?  "
                        "NOT_APPLICABLE when no carded creature is visible."},
        "no_p0_or_p1_defect": {
            "enum": PF, "maps_to": ["DEFECT-TIER-TOLERANCE"],
            "question": "Is the clip free of any blocking (P0/P1) defect?  Answer FAIL and list "
                        "every defect with its severity, its 1-based shot_index inside "
                        "expectations.editorial_shot_ids and its at_seconds timestamp — "
                        "defect_tolerance_gate.py needs the location of every P2."},
    },
}

#: structured observed lists the reviewer must fill, per kind.  Values are
#: checked against the request's own closed vocabulary; anything genuinely
#: unexpected is reported with the ``UNDECLARED:`` prefix, never silently.
OBSERVED_FIELDS: dict[str, dict[str, str]] = {
    "identity": {
        "observed_views": "views",
        "observed_text_strings": "free",
    },
    "keyframe": {
        "observed_visible_characters": "characters",
        "observed_visible_props": "props",
        "observed_space_anchors": "space_anchors",
        "observed_text_strings": "free",
    },
    "start_frame": {
        "observed_visible_characters": "characters",
        "observed_visible_props": "props",
        "observed_space_anchors": "space_anchors",
    },
    "action_role": {
        "observed_initiator": "entities",
        "observed_target": "entities",
        "observed_prop_owners": "free",
    },
    "post_gen_plot": {
        "observed_principal_characters": "characters",
        "observed_missing_beats": "free",
        "observed_spoken_lines": "free",
    },
    "video_q2": {
        "observed_visible_characters": "characters",
        "observed_visible_props": "props",
        "observed_space_anchors": "space_anchors",
        "observed_text_strings": "free",
    },
}

UNDECLARED_PREFIX = "UNDECLARED:"


# --------------------------------------------------------------------------- #
# request
# --------------------------------------------------------------------------- #
def _media_row(path: Any, role: str) -> dict[str, Any]:
    path = Path(str(path)) if path else None
    return {
        "role": role,
        "path": str(path) if path else None,
        "exists": bool(path and path.is_file()),
        "sha256": sha256_file(path) if path else None,
        "media_type": ("VIDEO" if path and path.suffix.lower() in {".mp4", ".mov", ".mkv"}
                       else "IMAGE" if path else None),
    }


RUNTIME_PREPRODUCTION = Path(f"{_np.RUNTIME_ROOT}/preproduction")


def build_request(kind: str, episode: str, *, items_filter: list[str] | None = None,
                  media_override: dict[str, list[dict[str, Any]]] | None = None,
                  out: Path | None = None) -> dict[str, Any]:
    if kind not in KINDS:
        raise SystemExit(f"--kind must be one of {list(KINDS)}")
    exp = Expectations(episode)
    p = QaPaths(episode)
    vocabulary = {
        "characters": exp.character_ids() + sorted(exp.character_name_to_id()),
        "props": sorted({str(row.get("prop"))
                         for shot in exp.shots.values()
                         for row in ((shot.get("prompt_spec") or {}).get("props") or [])
                         if row.get("prop")}),
        "space_anchors": sorted({str(value)
                                 for shot in exp.shots.values()
                                 for value in ((shot.get("prompt_spec") or {}).get("space") or {}).values()
                                 if value}),
        "forbidden_terms": exp.forbidden_terms(),
        # action-role initiator/target vocabulary: characters (ids + names), prop ids,
        # the environment/space pseudo-entities the contract uses as receivers
        "entities": exp.character_ids() + sorted(exp.character_name_to_id())
                    + sorted({str(row.get("prop_id"))
                              for shot in exp.shots.values()
                              for row in ((shot.get("prompt_spec") or {}).get("props") or [])
                              if row.get("prop_id")})
                    + sorted({f"SPACE-{shot.get('scene_id')}" for shot in exp.shots.values()
                              if shot.get("scene_id")})
                    # E04: creature subjects (e.g. the mutant beast) have a locked card but the engine's
                    # editorial prop scan never lists them on a shot → include every locked prop/set id
                    + sorted({str(k) for k in ((exp.library.get("assets") or {}).get("props") or {}).keys()})
                    + ["ENVIRONMENT", "NONE_VISIBLE"],
        "views": sorted({str(value)
                         for row in exp.identity_subjects()
                         for value in row["expectations"]["card_deliverables"]}),
    }

    if kind == "identity":
        rows = exp.identity_subjects()
        # the authoritative subject list is the identity plan the engine compiled
        # (18 groups for E01: 6 characters + props); anything else in the library
        # is not a plate subject for this episode.
        plan = read_json(p.identity / "character_asset_plan.json", {}) or {}
        planned = {str(row.get("id")) for row in plan.get("new_asset_groups") or []}
        # a subject matched to an operator source reference is NOT in
        # new_asset_groups (nothing is generated for it) but it still needs
        # identity QA before it can be LOCKED, so both sets are reviewed.
        match = read_json(p.identity / "source_match_report.json", {}) or {}
        planned |= {str(value) for value in match.get("subjects_with_sources") or []}
        # E03+ cross-episode reuse (D-33): a subject whose requirement row is REUSED_FROM_PRIOR_LIBRARY has no
        # plates in this episode (library_lock_non_plate copies the prior LOCKED row); it is not a review item
        # even when it also has an operator source photo (秦铭 in E03).
        req_rows = (read_json(RUNTIME_PREPRODUCTION / episode / "asset_requirements.json", {}) or {}).get("assets") or {}
        reused = {str(row.get("asset_id")) for cat in req_rows.values() if isinstance(cat, list) for row in cat
                  if str(((row.get("reuse") or {}).get("status")) or "") == "REUSED_FROM_PRIOR_LIBRARY"}
        planned -= reused
        if planned:
            rows = [row for row in rows if row["asset_id"] in planned]
        for row in rows:
            plates = sorted(p.plates.glob(f"*{row['asset_id']}*")) if p.plates.is_dir() else []
            source = find_scoped_operator_source(row["asset_id"], p.character_sources)
            # A source-matched subject has no provider-generated plate by
            # design.  Review the real operator source as the canonical
            # identity plate instead of inventing a missing placeholder path.
            row["media"] = ([_media_row(item, "IDENTITY_PLATE") for item in plates]
                            or ([_media_row(source, "IDENTITY_PLATE")] if source else
                                [_media_row(p.plates / f"{row['asset_id']}-plate-v1.png", "IDENTITY_PLATE")]))
            if source is not None:
                row["media"].append(_media_row(source, "OPERATOR_SOURCE_REFERENCE"))
    elif kind == "keyframe":
        rows = exp.keyframe_items()
        for row in rows:
            row["media"] = [_media_row(row.pop("media_path"), "KEYFRAME")]
    elif kind == "start_frame":
        rows = exp.start_frame_items()
        for row in rows:
            row["media"] = [_media_row(row.pop("media_path"), "START_FRAME_KEYFRAME")]
    elif kind == "action_role":
        rows = exp.action_role_items()
        for row in rows:
            row["media"] = [_media_row(row.pop("media_path"), "START_FRAME_KEYFRAME")]
    elif kind == "video_q2":
        # Q2 VIDEO_ASSEMBLY: the reviewer must see the ORIGINAL-RESOLUTION asset,
        # because shot_media_admission_gate.py:628-637 requires at least one
        # evidence row with original_resolution_review true.  The request
        # therefore carries the 720x1280 mp4 itself, every original-resolution
        # frame video_q2_builder.py extracted from it (run `prepare` first), and
        # the 2-fps contact sheet as a navigation aid.
        rows = exp.video_unit_items()
        for row in rows:
            unit_id = row["unit_id"]
            media = media_override.get(unit_id) if media_override else None
            if media:
                row["media"] = media
                continue
            clip = p.video_media / f"{unit_id}.mp4"
            frame_dir = p.q2_dir / unit_id / "frames"
            frames = sorted(frame_dir.glob("*.png")) if frame_dir.is_dir() else []
            sheet = p.postgen_dir / unit_id / "contact_sheet_2fps.png"
            row["media"] = [_media_row(clip, "UNIT_VIDEO")]
            row["media"] += [_media_row(item, "ORIGINAL_RESOLUTION_FRAME") for item in frames]
            row["media"].append(_media_row(sheet, "CONTACT_SHEET_2FPS"))
    else:  # post_gen_plot
        rows = exp.unit_plot_items()
        for row in rows:
            unit_id = row["unit_id"]
            media = media_override.get(unit_id) if media_override else None
            if media:
                row["media"] = media
            else:
                clip = p.video_media / f"{unit_id}.mp4"
                sheet = p.postgen_dir / unit_id / "contact_sheet_2fps.png"
                row["media"] = [_media_row(clip, "UNIT_VIDEO"),
                                _media_row(sheet, "CONTACT_SHEET_2FPS")]

    if items_filter:
        wanted = set(items_filter)
        rows = [row for row in rows if row["item_id"] in wanted or row.get("unit_id") in wanted]
        if not rows:
            raise SystemExit(f"--items matched nothing for kind={kind}: {sorted(wanted)}")

    for row in rows:
        row["closed_vocabulary"] = {
            key: vocabulary[key] for key in OBSERVED_FIELDS[kind].values() if key in vocabulary}
        if kind in {"keyframe", "video_q2"}:
            row["closed_vocabulary"]["forbidden_terms"] = vocabulary["forbidden_terms"]

    request_id = f"{episode}-{kind}-{run_id()}"
    out = Path(out) if out else REVIEWS_ROOT / episode / f"{request_id}_request.json"
    payload = {
        "schema": SCHEMA_REQUEST,
        "request_id": request_id,
        "kind": kind,
        "episode": episode,
        "created_at": now(),
        "created_by": TOOL_ID,
        "reviewer_contract": {
            "reviewer": REVIEWER_ID,
            "review_method": REVIEW_METHOD,
            "who_reviews": "A Claude reviewer process that actually opens every media path "
                           "listed below and answers the questionnaire from what it sees.",
            "rules": [
                "Look at the media.  Every answer must be grounded in the pixels, not in the "
                "expectations block — the expectations are what SHOULD be there.",
                f"Answer every question of every item with one of its enumerated values.",
                f"Write a free-text observation of at least {MIN_OBSERVATION_CHARS} characters per "
                "item, describing what you actually saw, including what was right.",
                "List every defect you found with a code, a severity (P0/P1/P2) and a "
                f"description of at least {MIN_OBSERVATION_CHARS} characters.",
                "UNCERTAIN is not a pass: use it when the media does not let you decide, and the "
                "item will be rejected for human arbitration or a reroll.",
                "Fill the observed_* lists from the closed_vocabulary.  If you see something that "
                f"is not in the vocabulary, write '{UNDECLARED_PREFIX}<what you saw>'.",
                "Never copy an expectation into an observed_* list without seeing it.",
            ],
        },
        "questionnaire": {
            key: {"question": row["question"], "enum": row["enum"], "maps_to": row["maps_to"]}
            for key, row in QUESTIONNAIRES[kind].items()},
        "observed_fields": OBSERVED_FIELDS[kind],
        "identity_measurement_decision": ({
            "decision_ref": "SUPERVISOR_ORDERS seq=4 / D-13 operator call 2026-09-09",
            "decided_by": "line owner (Roger), recorded by Claude Code as operator",
            "decision_text": "For STILL keyframes (S5 Q1) identity is measured as a "
                             "single-still cosine between the keyframe face crop and the "
                             "LOCKED identity plate embedding, sample_frames_per_source_min "
                             "= 1, InsightFace thresholds unchanged; no corpus scoping. "
                             "Video units (S6 Q2) keep the engine's 3-frame minimum.",
            "affects": "the CHARACTER-IDENTITY-ADMISSION objective_verification block only; "
                       "it does not change what the reviewer is asked",
        } if kind == "keyframe" else None),
        "answer_rules": {
            "pass_answers": sorted(PASS_ANSWERS),
            "fail_answers": sorted(FAIL_ANSWERS),
            "uncertain_answers": sorted(UNCERTAIN_ANSWERS),
            "defect_severities": list(SEVERITIES),
            "min_observation_chars": MIN_OBSERVATION_CHARS,
            "item_verdict_rule": "PASS iff no FAIL answer, no UNCERTAIN answer and no P0/P1 "
                                 "defect.  Otherwise REJECT.",
        },
        "item_count": len(rows),
        "items": rows,
        "answers_schema": SCHEMA_ANSWERS,
        "next_commands": {
            "template": f"{TOOL_ID} example-answers --request <this file>",
            "submit": f"{TOOL_ID} submit --request <this file> --answers <answers.json>",
        },
    }
    write_json(out, payload)
    payload["_written_to"] = str(out)
    return payload


# --------------------------------------------------------------------------- #
# example answers (all null — cannot be mistaken for a review)
# --------------------------------------------------------------------------- #
def example_answers(request: dict[str, Any]) -> dict[str, Any]:
    kind = request["kind"]
    return {
        "schema": SCHEMA_ANSWERS,
        TEMPLATE_MARKER: True,
        "_refusal": "This is an EMPTY TEMPLATE, not a review.  Every value is null.  "
                    "vlm_review_protocol.py submit rejects this file until a reviewer has "
                    "actually looked at every media path and replaced every null.",
        "request_path": None,
        "request_sha256": None,
        "reviewer": None,
        "reviewed_at": None,
        "items": [
            {
                "item_id": row["item_id"],
                "media_reviewed": [media["path"] for media in row.get("media") or []],
                "answers": {key: None for key in request["questionnaire"]},
                "observed": {field: None for field in OBSERVED_FIELDS[kind]},
                "observation": None,
                "defects": None,
            }
            for row in request["items"]
        ],
    }


# --------------------------------------------------------------------------- #
# submit — validation
# --------------------------------------------------------------------------- #
def validate_answers(request: dict[str, Any], request_sha: str,
                     answers: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Return (failures, per-item verdict rows).  Empty failures == valid."""
    failures: list[str] = []
    kind = request["kind"]
    questions = request["questionnaire"]
    observed_fields = OBSERVED_FIELDS[kind]

    if answers.get("schema") != SCHEMA_ANSWERS:
        failures.append(f"answers_schema_invalid:{answers.get('schema')}")
    if answers.get(TEMPLATE_MARKER):
        failures.append("answers_are_the_untouched_template_no_review_happened")
    if str(answers.get("reviewer") or "") != REVIEWER_ID:
        failures.append(f"reviewer_not_{REVIEWER_ID}:{answers.get('reviewer')}")
    if not str(answers.get("reviewed_at") or "").strip():
        failures.append("reviewed_at_missing")
    declared_sha = str(answers.get("request_sha256") or "")
    if declared_sha != request_sha:
        failures.append(f"request_sha256_mismatch:declared={declared_sha or 'MISSING'}")

    rows = answers.get("items")
    if not isinstance(rows, list) or not rows:
        failures.append("answer_items_missing")
        return failures, []

    expected_ids = [row["item_id"] for row in request["items"]]
    seen: list[str] = []
    verdicts: list[dict[str, Any]] = []
    by_id = {row["item_id"]: row for row in request["items"]}

    for index, row in enumerate(rows, 1):
        item_id = str(row.get("item_id") or "")
        prefix = f"item_{index}:{item_id or 'UNKNOWN'}"
        if item_id not in by_id:
            failures.append(f"{prefix}:unknown_item_id")
            continue
        if item_id in seen:
            failures.append(f"{prefix}:duplicate_item")
            continue
        seen.append(item_id)
        item_failures: list[str] = []

        given = row.get("answers")
        if not isinstance(given, dict):
            item_failures.append("answers_not_object")
            given = {}
        for key, spec in questions.items():
            if key not in given:
                item_failures.append(f"answer_missing:{key}")
                continue
            value = given[key]
            if value is None:
                item_failures.append(f"answer_null:{key}")
            elif str(value) not in spec["enum"]:
                item_failures.append(f"answer_not_enumerated:{key}={value!r}")
        for key in set(given) - set(questions):
            item_failures.append(f"answer_unknown_question:{key}")

        observation = str(row.get("observation") or "").strip()
        if len(observation) < MIN_OBSERVATION_CHARS:
            item_failures.append(
                f"observation_too_short:{len(observation)}<{MIN_OBSERVATION_CHARS}")

        obs = row.get("observed")
        if not isinstance(obs, dict):
            item_failures.append("observed_not_object")
            obs = {}
        vocabulary = by_id[item_id].get("closed_vocabulary") or {}
        for field, vocab_key in observed_fields.items():
            if field not in obs or obs[field] is None:
                item_failures.append(f"observed_missing:{field}")
                continue
            values = obs[field]
            if not isinstance(values, list):
                item_failures.append(f"observed_not_list:{field}")
                continue
            allowed = vocabulary.get(vocab_key)
            if vocab_key == "free" or allowed is None:
                continue
            for value in values:
                text = str(value)
                if text not in allowed and not text.startswith(UNDECLARED_PREFIX):
                    item_failures.append(f"observed_outside_closed_vocabulary:{field}:{text}")

        defects = row.get("defects")
        if defects is None or not isinstance(defects, list):
            item_failures.append("defects_missing_use_empty_list_when_none")
            defects = []
        for d_index, defect in enumerate(defects, 1):
            if not isinstance(defect, dict):
                item_failures.append(f"defect_{d_index}_not_object")
                continue
            if not str(defect.get("code") or "").strip():
                item_failures.append(f"defect_{d_index}_code_missing")
            if str(defect.get("severity") or "") not in SEVERITIES:
                item_failures.append(
                    f"defect_{d_index}_severity_invalid:{defect.get('severity')}")
            if len(str(defect.get("description") or "").strip()) < MIN_OBSERVATION_CHARS:
                item_failures.append(f"defect_{d_index}_description_too_short")

        # descriptive yes/no questions: "NO" is an observation, not a failure (e.g. a frame
        # with a character is correctly NOT an empty establishing frame)
        descriptive = {"empty_establishing_frame", "interaction_state"}
        failed_answers = sorted(key for key, value in given.items() if key not in descriptive
                                if str(value) in FAIL_ANSWERS)
        uncertain = sorted(key for key, value in given.items()
                           if str(value) in UNCERTAIN_ANSWERS)
        blocking_defects = [d for d in defects if isinstance(d, dict)
                            and str(d.get("severity")) in {"P0", "P1"}]
        p2_defects = [d for d in defects if isinstance(d, dict)
                      and str(d.get("severity")) == "P2"]
        if (failed_answers or uncertain) and not defects:
            item_failures.append("fail_or_uncertain_answer_without_a_defect_entry")

        verdict = "PASS"
        if failed_answers or uncertain or blocking_defects:
            verdict = "REJECT"
        elif p2_defects:
            verdict = "PASS_WITH_P2"

        failures.extend(f"{prefix}:{value}" for value in item_failures)
        verdicts.append({
            "item_id": item_id,
            "verdict": verdict,
            "answers": given,
            "observed": obs,
            "observation": observation,
            "defects": defects,
            "failed_answers": failed_answers,
            "uncertain_answers": uncertain,
            "blocking_defects": blocking_defects,
            "p2_defects": p2_defects,
            "validation_failures": item_failures,
        })

    for item_id in expected_ids:
        if item_id not in seen:
            failures.append(f"item_not_answered:{item_id}")
    return failures, verdicts


def submit(request_path: Path, answers_path: Path, *, out: Path | None = None,
           materialise: bool = True) -> tuple[int, dict[str, Any]]:
    request = read_json(request_path)
    if not isinstance(request, dict) or request.get("schema") != SCHEMA_REQUEST:
        raise SystemExit(f"not a {SCHEMA_REQUEST}: {request_path}")
    request_sha = sha256_file(request_path)
    answers = read_json(answers_path)
    if not isinstance(answers, dict):
        raise SystemExit(f"unreadable answers: {answers_path}")

    failures, verdicts = validate_answers(request, request_sha, answers)
    episode, kind = request["episode"], request["kind"]
    out = Path(out) if out else (
        Path(request_path).with_name(Path(request_path).name.replace("_request.json",
                                                                    "_submitted.json")))
    record = {
        "schema": SCHEMA_SUBMITTED,
        "request_id": request["request_id"],
        "kind": kind,
        "episode": episode,
        "reviewer": answers.get("reviewer"),
        "review_method": REVIEW_METHOD,
        "reviewed_at": answers.get("reviewed_at"),
        "submitted_at": now(),
        "submitted_by": TOOL_ID,
        "request_path": str(request_path),
        "request_sha256": request_sha,
        "answers_path": str(answers_path),
        "answers_sha256": sha256_file(answers_path),
        "questionnaire": request["questionnaire"],
        "validation": {
            "status": "PASS" if not failures else "FAIL",
            "failure_count": len(failures),
            "failures": failures,
        },
        "items": verdicts,
        "verdict_counts": {},
        "materialisation": None,
    }
    if failures:
        record["verdict_counts"] = {"VALIDATION_FAILED": len(verdicts)}
        write_json(out, record)
        record["_written_to"] = str(out)
        return 2, record

    counts: dict[str, int] = {}
    for row in verdicts:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    record["verdict_counts"] = counts
    # bind the request items alongside the verdicts so a materialiser never has
    # to re-read the request (and can never drift from what was reviewed)
    by_id = {row["item_id"]: row for row in request["items"]}
    for row in record["items"]:
        row["request_item"] = by_id[row["item_id"]]
    write_json(out, record)

    exit_code = 0 if not counts.get("REJECT") else 5
    if materialise:
        try:
            record["materialisation"] = materialise_kind(kind, episode, record, out)
        except Exception as exc:  # noqa: BLE001 — report, never half-write a verdict
            record["materialisation"] = {
                "status": "MATERIALISATION_ERROR",
                "error": f"{type(exc).__name__}: {exc}",
            }
            write_json(out, record)
            record["_written_to"] = str(out)
            return 3, record
        write_json(out, record)
    record["_written_to"] = str(out)
    return exit_code, record


def materialise_kind(kind: str, episode: str, submitted: dict[str, Any],
                     submitted_path: Path) -> dict[str, Any]:
    """Dispatch to the per-kind ENGINE-FORMAT evidence materialiser."""
    if kind == "identity":
        import identity_qa_lock
        return identity_qa_lock.materialise(episode, submitted, submitted_path)
    if kind == "keyframe":
        import keyframe_q1_builder
        return keyframe_q1_builder.materialise(episode, submitted, submitted_path)
    if kind == "start_frame":
        import start_frame_evidence_writer
        return start_frame_evidence_writer.materialise(episode, submitted, submitted_path)
    if kind == "action_role":
        import action_role_evidence_writer
        return action_role_evidence_writer.materialise(episode, submitted, submitted_path)
    if kind == "post_gen_plot":
        import post_generation_qa_runner
        return post_generation_qa_runner.materialise_plot(episode, submitted, submitted_path)
    if kind == "video_q2":
        import video_q2_builder
        return video_q2_builder.materialise(episode, submitted, submitted_path)
    raise ValueError(f"unknown kind {kind}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    req = sub.add_parser("request", help="write a review request file")
    req.add_argument("--kind", required=True, choices=list(KINDS))
    req.add_argument("--episode", required=True)
    req.add_argument("--items", help='JSON list of item ids to restrict the request to, '
                                     'e.g. \'["E01-S01-01"]\'')
    req.add_argument("--media", help="JSON {unit_id: [media rows]} override (post_gen_plot)")
    req.add_argument("--out", type=Path)

    tpl = sub.add_parser("example-answers", help="emit an all-null answers template")
    tpl.add_argument("--request", required=True, type=Path)
    tpl.add_argument("--out", type=Path)

    sbm = sub.add_parser("submit", help="validate answers and materialise the evidence")
    sbm.add_argument("--request", required=True, type=Path)
    sbm.add_argument("--answers", required=True, type=Path)
    sbm.add_argument("--out", type=Path)
    sbm.add_argument("--no-materialise", action="store_true")

    qst = sub.add_parser("questionnaire", help="print the closed questionnaire for a kind")
    qst.add_argument("--kind", required=True, choices=list(KINDS))

    args = parser.parse_args()

    if args.command == "questionnaire":
        print(json.dumps({"kind": args.kind,
                          "questionnaire": QUESTIONNAIRES[args.kind],
                          "observed_fields": OBSERVED_FIELDS[args.kind]},
                         ensure_ascii=False, indent=2))
        return 0

    if args.command == "request":
        items = json.loads(args.items) if args.items else None
        media = json.loads(args.media) if args.media else None
        payload = build_request(args.kind, args.episode, items_filter=items,
                                media_override=media, out=args.out)
        missing = [media_row["path"] for row in payload["items"]
                   for media_row in row.get("media") or [] if not media_row["exists"]]
        print(json.dumps({
            "status": "REVIEW_REQUIRED",
            "request": payload["_written_to"],
            "request_sha256": sha256_file(payload["_written_to"]),
            "kind": args.kind, "episode": args.episode,
            "items": payload["item_count"],
            "media_missing": len(missing),
            "media_missing_examples": missing[:3],
        }, ensure_ascii=False))
        return 0

    if args.command == "example-answers":
        request = read_json(args.request)
        if not isinstance(request, dict) or request.get("schema") != SCHEMA_REQUEST:
            raise SystemExit(f"not a {SCHEMA_REQUEST}: {args.request}")
        out = args.out or Path(str(args.request).replace("_request.json",
                                                        "_answers_TEMPLATE.json"))
        write_json(out, example_answers(request))
        print(json.dumps({"status": "TEMPLATE_ONLY_NOT_A_REVIEW", "out": str(out),
                          "items": len(request["items"]),
                          "questions_per_item": len(request["questionnaire"])},
                         ensure_ascii=False))
        return 0

    code, record = submit(args.request, args.answers, out=args.out,
                          materialise=not args.no_materialise)
    print(json.dumps({
        "status": record["validation"]["status"],
        "exit": code,
        "verdicts": record["verdict_counts"],
        "validation_failures": record["validation"]["failures"][:8],
        "submitted": record["_written_to"],
        "materialisation": (record.get("materialisation") or {}).get("status"),
    }, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
