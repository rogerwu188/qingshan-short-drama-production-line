import hashlib
from pathlib import Path
import pytest
from PIL import Image
from tools.original_identity_authority import original_reference, classify_reference_asset


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def source_fixture(tmp_path):
    source = tmp_path / 'original.png'
    Image.new('RGB', (40, 60), (80, 90, 100)).save(source)
    return source


def test_plain_original_is_approved_original(tmp_path):
    source = source_fixture(tmp_path)
    row = {'original_identity_authority': dict(
        mode='APPROVED_ORIGINAL_SOURCE', path=str(source), sha256=sha(source),
        approval_basis='synthetic approval')}
    result = original_reference(row)
    assert result['asset_type'] == 'APPROVED_ORIGINAL'
    assert classify_reference_asset(row['original_identity_authority']) == 'APPROVED_ORIGINAL'


def test_resize_transform_verifies_declared_dimensions(tmp_path):
    source = source_fixture(tmp_path)
    target = tmp_path / 'resized.png'
    with Image.open(source) as im:
        im.resize((20, 30)).save(target)
    transform = dict(operation='RESIZE', params={'target_size': [20, 30]},
                      source_sha256=sha(source), review_basis='synthetic resize review',
                      path=str(target), sha256=sha(target))
    row = {'original_identity_authority': dict(
        mode='APPROVED_ORIGINAL_SOURCE', path=str(source), sha256=sha(source),
        approval_basis='synthetic approval', transport_deterministic_transform=transform)}
    result = original_reference(row)
    assert result['asset_type'] == 'DETERMINISTIC_TRANSFORM'
    assert result['view'] == 'VERIFIED_DETERMINISTIC_TRANSFORM'
    assert classify_reference_asset(row['original_identity_authority']) == 'DETERMINISTIC_TRANSFORM'


def test_resize_transform_rejects_dimension_mismatch(tmp_path):
    source = source_fixture(tmp_path)
    target = tmp_path / 'resized.png'
    with Image.open(source) as im:
        im.resize((20, 30)).save(target)
    transform = dict(operation='RESIZE', params={'target_size': [21, 30]},
                      source_sha256=sha(source), review_basis='synthetic resize review',
                      path=str(target), sha256=sha(target))
    row = {'original_identity_authority': dict(
        mode='APPROVED_ORIGINAL_SOURCE', path=str(source), sha256=sha(source),
        approval_basis='synthetic approval', transport_deterministic_transform=transform)}
    with pytest.raises(ValueError, match='DIMENSIONS_INVALID'):
        original_reference(row)


def test_crop_and_transform_declared_together_is_ambiguous(tmp_path):
    source = source_fixture(tmp_path)
    crop_target = tmp_path / 'crop.png'
    with Image.open(source) as im:
        im.crop((0, 0, 10, 10)).save(crop_target)
    resize_target = tmp_path / 'resized.png'
    with Image.open(source) as im:
        im.resize((20, 30)).save(resize_target)
    row = {'original_identity_authority': dict(
        mode='APPROVED_ORIGINAL_SOURCE', path=str(source), sha256=sha(source),
        approval_basis='synthetic approval',
        transport_pixel_crop=dict(path=str(crop_target), sha256=sha(crop_target),
                                   source_sha256=sha(source), box_xyxy=[0, 0, 10, 10],
                                   review_basis='synthetic crop review'),
        transport_deterministic_transform=dict(
            operation='RESIZE', params={'target_size': [20, 30]}, source_sha256=sha(source),
            review_basis='synthetic resize review', path=str(resize_target), sha256=sha(resize_target)))}
    with pytest.raises(ValueError, match='TRANSPORT_AMBIGUOUS'):
        original_reference(row)


def test_unverifiable_entry_classifies_as_generated_derivative(tmp_path):
    assert classify_reference_asset(None) == 'GENERATED_DERIVATIVE'
    assert classify_reference_asset({'mode': 'GENERATED_DERIVATIVE'}) == 'GENERATED_DERIVATIVE'


def _pixel_crop_row(tmp_path):
    source = source_fixture(tmp_path)
    crop_target = tmp_path / 'crop.png'
    with Image.open(source) as im:
        im.crop((0, 0, 10, 10)).save(crop_target)
    return source, crop_target, {'original_identity_authority': dict(
        mode='APPROVED_ORIGINAL_SOURCE', path=str(source), sha256=sha(source),
        approval_basis='synthetic approval',
        transport_pixel_crop=dict(path=str(crop_target), sha256=sha(crop_target),
                                   source_sha256=sha(source), box_xyxy=[0, 0, 10, 10],
                                   review_basis='synthetic crop review'))}


def test_pixel_crop_is_measured_against_its_source_photo(tmp_path):
    # nalu E13 Q1/Q2: the tight transport crop had no detectable face (FACE_COUNT_ZERO); identity is measured
    # on the verified source photo the crop was cut from, in every consumer.
    from tools.original_identity_authority import measurement_paths, measurement_reference
    source, crop_target, row = _pixel_crop_row(tmp_path)
    assert original_reference(row)['path'] == str(crop_target)  # transport still sends the crop
    assert measurement_reference(original_reference(row)) == {'path': str(source), 'sha256': sha(source)}
    assert measurement_paths(row)[0] == str(source)


def test_admission_gate_measures_pixel_crop_source(tmp_path):
    # End to end through evaluate(): the registry carries the transport crop as the approved original; the gate
    # must embed the source photo the crop was cut from, not the crop (nalu E13 Q2 FACE_COUNT_ZERO).
    from tools.character_identity_admission_gate import evaluate

    source = source_fixture(tmp_path)
    crop_target = tmp_path / 'transport-crop.png'
    with Image.open(source) as im:
        im.crop((0, 0, 10, 10)).save(crop_target)
    seen = []

    class Backend:
        def embed(self, path):
            seen.append(Path(path).name)
            return [1.0, 0.0]

    samples = []
    for index in range(3):
        path = tmp_path / f'sample-{index}.png'
        path.write_bytes(b'x')
        samples.append(path)
    row = {
        'character_id': 'CHAR-A',
        'canonical_reference_paths': [],
        'sample_frame_paths': [str(p) for p in samples],
        'sample_frame_sha256': {str(p): sha(p) for p in samples},
    }
    registry = {'characters': {'CHAR-A': {
        'status': 'LOCKED_RETURNING',
        'original_identity_authority': dict(
            mode='APPROVED_ORIGINAL_SOURCE', path=str(source), sha256=sha(source),
            approval_basis='synthetic approval',
            transport_pixel_crop=dict(path=str(crop_target), sha256=sha(crop_target),
                                       source_sha256=sha(source), box_xyxy=[0, 0, 10, 10],
                                       review_basis='synthetic crop review'))}},
        'parameters': {'canonical_views_min': 3, 'sample_frames_per_source_min': 3,
                       'embedding_cosine_pass_threshold': 0.45,
                       'embedding_cosine_fail_threshold': 0.3,
                       'embedding_cosine_boundary_auto_decision_midpoint': 0.375,
                       'boundary_human_timeout_minutes': 15}}
    evaluate({'sources': [{'source_id': 'S1', 'characters': [row]}]}, registry, Backend())
    assert source.name in seen
    assert crop_target.name not in seen
