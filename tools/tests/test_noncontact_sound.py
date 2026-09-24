import copy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lines/nalu/runtime/tools'))
from build_nalu_preproduction import constrain_noncontact_sound
from build_nalu_preproduction import scope_shot_sound

def test_sound_scope_survives_flattening_without_changing_ambience():
    sound = {'ambience': '夜风', 'foley': '衣料声', 'action_sound': '不生成接触音效'}
    scoped = scope_shot_sound(sound, 'S1')
    assert scoped['ambience'] == sound['ambience']
    assert scoped['action_sound'] == '仅分镜S1适用：不生成接触音效'
    assert scope_shot_sound(scoped, 'S1') == scoped
    assert sound['foley'] == '衣料声'

def test_no_touch_wording_is_noncontact_too():
    sound = {'action_sound': '只强化「观察」一次因果接触声；无配乐'}
    action = {'physical_causality': '没有触碰陈迹'}
    result = constrain_noncontact_sound(sound, action)
    assert '不添加人物接触音效' in result['action_sound']
    assert '道具接触拟音保留' in result['action_sound']
    assert constrain_noncontact_sound(result, action) == result

def test_noncontact_removes_template_impact_preserving_authored_policy():
    sound = {'ambience': 'wind', 'foley': '接触声',
             'action_sound': '只强化「俯身；观察」一次因果接触声；无外置BGM'}
    before = copy.deepcopy(sound)
    result = constrain_noncontact_sound(sound, {'physical_causality': '观察对方，未触碰', 'contact_point': ''})
    assert result['action_sound'].endswith('；无外置BGM')
    assert '不添加人物接触音效' in result['action_sound']
    assert result['ambience'] == 'wind'
    assert sound == before

def test_explicit_contact_and_undeclared_contact_are_not_reinterpreted():
    sound = {'action_sound': '已批准接触声'}
    for action in ({'contact_point': '桌面', 'physical_causality': '不接触人物'}, {}):
        assert constrain_noncontact_sound(sound, action) == sound

def test_structured_none_suppresses_template_impact_not_declared_prop_contact():
    sound = {'action_sound': '只强化「睁眼」一次因果接触声；无配乐'}
    action = {'interaction_mode': 'NONE', 'contact_point': '', 'physical_causality': '不增加接触对象'}
    assert '只强化' not in constrain_noncontact_sound(sound, action)['action_sound']
    action['contact_point'] = '砚台'
    assert constrain_noncontact_sound(sound, action) == sound
