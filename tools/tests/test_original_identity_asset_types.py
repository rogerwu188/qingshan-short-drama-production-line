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
