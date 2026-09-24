import copy
from tools.event_boundary_continuity_contract import provider_shot_state_lock_texts

def test_missing_persistent_delta_does_not_prohibit_authored_action():
    plan={'shot_state_contracts':[{'shot_id':'S1','persistent_state_contract':{'characters':[]},'camera_state':{}}]}
    before=copy.deepcopy(plan)
    zh=provider_shot_state_lock_texts(plan,language='ZH')[0]
    en=provider_shot_state_lock_texts(plan,language='EN')[0]
    assert '无授权人物状态变化' not in zh
    assert '动作与表演照常执行' in zh
    assert 'no authorized character-state change' not in en
    assert "execute this shot's declared action" in en
    assert plan==before
