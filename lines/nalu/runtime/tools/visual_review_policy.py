"""Narrow weak-post-QA classifications; never turn unknown evidence into PASS."""
import os

MINOR_QUESTIONS = {
    'COMPOSITION_VARIATION': {'screen_slots_and_depth_planes_match',
                              'camera_framing_and_axis_match'},
    'MINOR_LIGHTING_VARIATION': {'lighting_palette_and_time_match'},
    'MINOR_GARMENT_HEM_VARIATION': {'wardrobe_matches_bible'},
}


def selected_profile():
    value = os.environ.get('NALU_VISUAL_POST_QA_PROFILE', 'STRICT')
    if value not in {'STRICT', 'WEAK'}:
        raise ValueError('UNKNOWN_VISUAL_POST_QA_PROFILE')
    return value


def advisory_questions(item, profile=None):
    profile = profile or os.environ.get('NALU_VISUAL_POST_QA_PROFILE', 'STRICT')
    if profile not in {'STRICT', 'WEAK'}:
        raise ValueError('UNKNOWN_VISUAL_POST_QA_PROFILE')
    if profile == 'STRICT':
        return set()
    result = set()
    for defect in item.get('defects') or []:
        if defect.get('severity') != 'P2':
            continue
        if defect.get('code') == 'MINOR_GARMENT_HEM_VARIATION':
            # Only an actually reviewed hem-length deviation; never identity,
            # garment ownership, color, material, or plot-state continuity.
            preserved = set(defect.get('preserved_dimensions') or [])
            if not {'identity', 'garment_owner', 'color', 'material', 'plot_state'} <= preserved:
                continue
        allowed = MINOR_QUESTIONS.get(defect.get('code'), set())
        for key in defect.get('question_ids') or []:
            # UNCERTAIN stays unverified, even when attached to a minor defect.
            if key in allowed and (item.get('answers') or {}).get(key) == 'FAIL':
                result.add(key)
    return result
