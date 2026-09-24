from tools.identity_pose_reference import supplement_pose_references
from tools.image_model_adapter import compile_labeled_flat_identity_transport


def fixture():
    face = {'role': 'character', 'entity_id': 'CHAR-A', 'entity_name': '甲',
            'path': '/front', 'sha256': 'aaa'}
    library = {'assets': {'characters': {'a': {'status': 'LOCKED', 'qa': {'status': 'PASS'},
        'artifacts': [{'path': '/front', 'sha256': 'aaa'},
                      {'path': '/angle', 'sha256': 'bbb', 'view': 'THREE_QUARTER_BUST'}]}}}}
    return face, library


def test_actual_transport_preserves_map_reindexes_body_and_supplement():
    face, library = fixture()
    rows = [{'role': 'scene', 'entity_id': 'ROOM', 'path': '/map'}, face]
    rows, report = supplement_pose_references(rows, library, '甲低头书写')
    sequence, contract, prompt = compile_labeled_flat_identity_transport(
        'TASK', rows, '地图@图片1，人物@图片2')
    assert [r['path'] for r in sequence] == ['/front', '/angle', '/map']
    assert '地图@图片3，人物@图片1' in prompt
    assert contract['authority_map'] == {'CHAR-A': '@图片1'}
    assert '同一人的补充视角' in prompt
    assert report[0]['automatic_paid_regeneration'] is False
    assert len(rows) == 3


def test_missing_reference_is_not_fake_coverage_or_paid_retry():
    face, library = fixture()
    library['assets']['characters']['a']['artifacts'].pop()
    rows, report = supplement_pose_references([face], library, '甲低头书写')
    assert rows == [face]
    assert report[0]['coverage'] == 'MISSING_APPROVED_OBLIQUE_REFERENCE'
    assert report[0]['status'] == 'ADVISORY'
    assert report[0]['automatic_paid_regeneration'] is False


def test_does_not_assign_another_characters_pose():
    face, library = fixture()
    rows, report = supplement_pose_references([face], library, '甲平视；乙低头书写')
    assert rows == [face] and report == []


def test_unapproved_library_or_cap_cannot_silently_add_reference():
    face, library = fixture()
    rows, report = supplement_pose_references([face], library, '甲侧脸', limit=1)
    assert rows == [face] and report[0]['coverage'] == 'REFERENCE_CAP_NO_ROOM_FOR_SUPPLEMENT'
    library['assets']['characters']['a']['status'] = 'HOLD'
    rows, report = supplement_pose_references([face], library, '甲侧脸')
    assert rows == [face]


def test_no_mutation_and_deduplication():
    face, library = fixture()
    rows, _ = supplement_pose_references([face], library, '甲低头')
    again, _ = supplement_pose_references(rows, library, '甲低头')
    assert len(again) == 2
    assert face['role'] == 'character'


def test_unresolved_name_never_claims_pose_verified():
    face, library = fixture()
    rows, report = supplement_pose_references([face], library, '别名持笔')
    assert len(rows) == 2
    assert report[0]['pose_assessment'] == 'NOT_VERIFIED_NAME_OR_POSE_UNRESOLVED'


def test_builder_really_calls_selector_before_transport():
    import ast
    from pathlib import Path
    source = Path(__file__).resolve().parents[2] / 'lines/nalu/runtime/tools/build_keyframe_manifest.py'
    tree = ast.parse(source.read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'compile_task')
    calls = {n.func.id: n.lineno for n in ast.walk(function)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert calls['supplement_pose_references'] < calls['compile_labeled_flat_identity_transport']
    assert 'identity_pose_reference_review' in ast.get_source_segment(source.read_text(), function)
