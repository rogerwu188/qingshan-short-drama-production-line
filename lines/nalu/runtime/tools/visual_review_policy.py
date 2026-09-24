"""Narrow weak-post-QA classifications; never turn unknown evidence into PASS."""
import hashlib
import json
import os

POLICY_ID = 'nalu.visual_post_qa_profile'
POLICY_VERSION = 'v1'

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


def policy_sha256():
    """Hash the live rule content, not just the version label, so an edited
    MINOR_QUESTIONS table is detected even if POLICY_VERSION was forgotten."""
    canonical = {code: sorted(fields) for code, fields in MINOR_QUESTIONS.items()}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


def policy_snapshot(profile=None):
    """A task-bindable record of exactly which policy produced a decision."""
    profile = profile or selected_profile()
    if profile not in {'STRICT', 'WEAK'}:
        raise ValueError('UNKNOWN_VISUAL_POST_QA_PROFILE')
    return {'policy_id': POLICY_ID, 'policy_version': POLICY_VERSION,
            'policy_sha256': policy_sha256(), 'profile': profile}


def verify_policy_snapshot(snapshot):
    """Fail closed: a stale, foreign or missing snapshot must not silently
    drive an admission decision.  Returns the verified profile string."""
    if not isinstance(snapshot, dict) or not snapshot.get('policy_id'):
        raise ValueError('VISUAL_POST_QA_POLICY_SNAPSHOT_MISSING')
    current = policy_snapshot(snapshot.get('profile'))
    if (snapshot.get('policy_id') != current['policy_id']
            or snapshot.get('policy_version') != current['policy_version']
            or snapshot.get('policy_sha256') != current['policy_sha256']):
        raise ValueError('VISUAL_POST_QA_POLICY_DRIFT')
    return current['profile']


def resolve_profile(container):
    """Resolve the effective QA profile from a request/submitted record.

    Prefers the bound `visual_post_qa_policy` snapshot (verified against the
    live policy); falls back to the legacy bare `visual_post_qa_profile`
    field for records written before snapshots existed. Returns
    ``(profile, error)`` — `error` is `None` on success, or the ValueError
    raised by verification on drift/an invalid snapshot (in which case the
    caller decides whether to fail closed to STRICT or stop entirely).
    """
    policy = container.get('visual_post_qa_policy') if isinstance(container, dict) else None
    if policy:
        try:
            return verify_policy_snapshot(policy), None
        except ValueError as exc:
            return None, exc
    profile = container.get('visual_post_qa_profile', 'STRICT') if isinstance(container, dict) else 'STRICT'
    return profile, None


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
