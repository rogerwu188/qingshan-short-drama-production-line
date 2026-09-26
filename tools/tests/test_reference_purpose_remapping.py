from tools.image_model_adapter import compile_labeled_flat_identity_transport


def test_purpose_table_and_identity_header_use_same_provider_order():
    rows = [
        {'path': 'map.png', 'role': 'global_space_map', 'entity_id': 'MAP'},
        {'path': 'face.png', 'role': 'character', 'entity_id': 'CHAR-A'},
        {'path': 'map.png', 'role': 'scene', 'entity_id': 'SCENE'},
    ]
    _, contract, prompt = compile_labeled_flat_identity_transport(
        'TEST', rows, '@图片1 地图；@图片2 人物；参考图1 地图；参考图2 人物；参考图3 场景'
    )
    assert contract['authority_map']['CHAR-A'] == '@图片1'
    assert prompt.endswith('@图片2 地图；@图片1 人物；参考图2 地图；参考图1 人物；参考图2 场景')
