import hashlib,json
import pytest
from tools.keyframe_entry_scene_projection import validate_projection

def fixture(tmp_path):
    shot={'shot_id':'shot-a','scene_id':'scene-a','entry_state':'curtain remains closed'}
    scene={'time_id':'night','weather':'indoors; brighter after curtain opens','lighting':'soft light becomes bright later'}
    prompt='indoors soft light'
    data={'schema':'qingshan.reviewed_entry_scene_projection.v1',**shot,
          'source_fields':scene,'entry_fields':{'weather':'indoors','lighting':'soft light'},
          'reviewer':'test reviewer','reviewed_at':'2026-01-01T00:00:00Z','reason':'Entry precedes authored lighting transition',
          'review_status':'PASS','prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest()}
    p=tmp_path/'projection.json';p.write_text(json.dumps(data))
    ref={'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    return p,ref,shot,scene,prompt,data

def test_valid_reviewed_excerpt(tmp_path):
    p,ref,shot,scene,prompt,data=fixture(tmp_path)
    assert validate_projection(ref,shot=shot,scene=scene,prompt_text=prompt)==data['entry_fields']

@pytest.mark.parametrize('change',['hash','prompt','source','entry','review','invented'])
def test_fail_closed(tmp_path,change):
    p,ref,shot,scene,prompt,data=fixture(tmp_path)
    if change=='hash':ref['sha256']='0'*64
    elif change=='prompt':prompt+=' changed'
    elif change=='source':scene=dict(scene,weather='rain')
    elif change=='entry':shot=dict(shot,entry_state='curtain open')
    else:
        if change=='review':data['reviewer']=''
        if change=='invented':data['entry_fields']['lighting']='moonlight'
        p.write_text(json.dumps(data));ref['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    with pytest.raises(ValueError):validate_projection(ref,shot=shot,scene=scene,prompt_text=prompt)
