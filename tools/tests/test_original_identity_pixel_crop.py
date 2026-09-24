import hashlib
from pathlib import Path
import pytest
from PIL import Image
from tools.original_identity_authority import original_reference

def fixture(tmp_path):
    source, target = tmp_path/'original.png', tmp_path/'crop.png'
    im = Image.new('RGB', (16, 24), (80, 90, 100))
    im.save(source)
    im.crop((2, 3, 12, 18)).save(target)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    crop = dict(path=str(target), sha256=sha(target), source_sha256=sha(source),
                box_xyxy=[2,3,12,18], review_basis='synthetic confirmed single face region')
    return {'original_identity_authority': dict(mode='APPROVED_ORIGINAL_SOURCE',
        path=str(source), sha256=sha(source), approval_basis='synthetic approval', transport_pixel_crop=crop)}

def test_crop_keeps_original_authority(tmp_path):
    row = fixture(tmp_path)
    result = original_reference(row)
    assert result['source_path'] == row['original_identity_authority']['path']
    assert result['view'] == 'VERIFIED_SOURCE_PIXEL_CROP'

@pytest.mark.parametrize('kind', ['source_hash','bounds','pixels'])
def test_crop_rejects_invalid_provenance(tmp_path, kind):
    row = fixture(tmp_path); crop = row['original_identity_authority']['transport_pixel_crop']
    if kind == 'source_hash': crop['source_sha256'] = 'invalid'
    if kind == 'bounds': crop['box_xyxy'] = [-1, 3, 12, 18]
    if kind == 'pixels':
        target = Path(crop['path']); Image.new('RGB',(10,15),'red').save(target)
        crop['sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(ValueError): original_reference(row)
