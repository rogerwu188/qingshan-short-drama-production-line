import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lines/nalu/runtime/tools'))
from visual_review_policy import advisory_questions


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
