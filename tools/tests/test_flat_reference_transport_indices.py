from tools.image_model_adapter import (
    compile_labeled_flat_identity_transport, validate_flat_reference_indices,
)


def test_duplicate_semantic_file_uses_actual_wire_index():
    rows = [
        {'path': '/map.png', 'role': 'subspace_layout', 'entity_id': 'MAP'},
        {'path': '/face.png', 'role': 'character', 'entity_id': 'CHAR-A'},
        {'path': '/map.png', 'role': 'scene', 'entity_id': 'ROOM'},
        {'path': '/chair.png', 'role': 'prop', 'entity_id': 'CHAIR'},
    ]
    sequence, contract, prompt = compile_labeled_flat_identity_transport('UNIT', rows, '')
    assert [r['asset_label'] for r in sequence] == ['@图片1', '@图片2', '@图片2', '@图片3']
    assert contract['authority_map'] == {'CHAR-A': '@图片1'}
    task = {'reference_image_sequence': sequence,
            'reference_images': ['/face.png', '/map.png', '/chair.png']}
    assert validate_flat_reference_indices(task, prompt_text=prompt) == []
    sequence[-1]['asset_label'] = '@图片4'
    assert any('LABEL_MISMATCH' in f for f in validate_flat_reference_indices(task))


def test_wrong_order_and_dangling_prompt_index_fail():
    task = {'reference_image_sequence': [
        {'path': '/a', 'asset_label': '@图片1'},
        {'path': '/b', 'asset_label': '@图片2'}], 'reference_images': ['/b', '/a']}
    failures = validate_flat_reference_indices(task, prompt_text='主体参考@图片3')
    assert 'REFERENCE_TRANSPORT_ARRAY_MISMATCH' in failures
    assert 'PROMPT_REFERENCE_INDEX_OUT_OF_RANGE:3' in failures
