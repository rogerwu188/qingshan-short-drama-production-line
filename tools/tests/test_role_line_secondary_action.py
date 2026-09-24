from tools.sd2_provider_prompt_renderer import _role_line

def test_primary_actor_does_not_disable_declared_secondary_action():
    row={'shot_id':'S1','primary_actor':'甲','entity_names':{'a':'甲','b':'乙'},
         'entity_states':{'a':'喝水','b':'夹菜'}}
    text=_role_line(row)
    assert '唯一动作执行者' not in text
    assert '乙的独立状态：夹菜' in text
    assert '不生成可辨人声' in text
    assert '所有人物闭口' not in text

def test_dialogue_still_has_exact_speaker_and_listener():
    text=_role_line({'primary_actor':'甲','dialogue_speaker':'甲','dialogue_listener':'乙'})
    assert '只有甲开口' in text
    assert '乙闭口聆听' in text
