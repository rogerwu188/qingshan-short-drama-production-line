import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lines/nalu/runtime/tools'))
from visual_review_policy import (
    advisory_questions, policy_snapshot, verify_policy_snapshot, resolve_profile,
    POLICY_ID, POLICY_VERSION)


def item(answer='FAIL', key='screen_slots_and_depth_planes_match', code='COMPOSITION_VARIATION', severity='P2'):
    return {'answers': {key: answer}, 'defects': [
        {'code': code, 'severity': severity, 'question_ids': [key]}]}


def test_weak_only_accepts_explicit_cosmetic_classification():
    assert advisory_questions(item(), 'WEAK') == {'screen_slots_and_depth_planes_match'}
    assert advisory_questions(item(), 'STRICT') == set()
    assert advisory_questions(item(severity='P0'), 'WEAK') == set()
    assert advisory_questions(item(code='WRONG_PERSON'), 'WEAK') == set()


def test_unverified_and_technical_questions_never_become_advisory_pass():
    assert advisory_questions(item(answer='UNCERTAIN'), 'WEAK') == set()
    assert advisory_questions(item(key='no_burned_in_text_or_subtitle'), 'WEAK') == set()
    assert advisory_questions(item(key='each_visible_character_identity_recognisable'), 'WEAK') == set()
    with pytest.raises(ValueError):
        advisory_questions(item(), 'UNKNOWN')

def test_hem_only_requires_explicit_preserved_identity_and_story_dimensions():
    row=item(key='wardrobe_matches_bible',code='MINOR_GARMENT_HEM_VARIATION')
    assert advisory_questions(row,'WEAK')==set()
    row['defects'][0]['preserved_dimensions']=['identity','garment_owner','color','material','plot_state']
    assert advisory_questions(row,'WEAK')=={'wardrobe_matches_bible'}
    assert advisory_questions(row,'STRICT')==set()
    row['answers']['wardrobe_matches_bible']='UNCERTAIN'
    assert advisory_questions(row,'WEAK')==set()


def test_policy_snapshot_round_trips_through_verify():
    snapshot = policy_snapshot('WEAK')
    assert snapshot['policy_id'] == POLICY_ID
    assert snapshot['policy_version'] == POLICY_VERSION
    assert verify_policy_snapshot(snapshot) == 'WEAK'


def test_verify_policy_snapshot_rejects_missing_or_drifted():
    with pytest.raises(ValueError, match='SNAPSHOT_MISSING'):
        verify_policy_snapshot(None)
    with pytest.raises(ValueError, match='SNAPSHOT_MISSING'):
        verify_policy_snapshot({})
    stale = policy_snapshot('WEAK')
    stale['policy_sha256'] = 'not-the-live-hash'
    with pytest.raises(ValueError, match='POLICY_DRIFT'):
        verify_policy_snapshot(stale)
    stale = policy_snapshot('WEAK')
    stale['policy_version'] = 'v0'
    with pytest.raises(ValueError, match='POLICY_DRIFT'):
        verify_policy_snapshot(stale)


def test_resolve_profile_prefers_bound_snapshot_over_legacy_field():
    container = {'visual_post_qa_profile': 'STRICT', 'visual_post_qa_policy': policy_snapshot('WEAK')}
    profile, error = resolve_profile(container)
    assert (profile, error) == ('WEAK', None)


def test_resolve_profile_falls_back_to_legacy_field_when_no_snapshot():
    assert resolve_profile({'visual_post_qa_profile': 'WEAK'}) == ('WEAK', None)
    assert resolve_profile({}) == ('STRICT', None)


def test_resolve_profile_surfaces_drift_as_an_error_not_a_silent_default():
    stale = policy_snapshot('WEAK')
    stale['policy_sha256'] = 'not-the-live-hash'
    profile, error = resolve_profile({'visual_post_qa_policy': stale})
    assert profile is None
    assert isinstance(error, ValueError) and 'POLICY_DRIFT' in str(error)
