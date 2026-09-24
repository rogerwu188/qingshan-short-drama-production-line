"""Original approved source wins over generated derivatives, fail closed.

Every reference asset is exactly one of four types (never inferred from
filename, resolution or ingestion order):

- APPROVED_ORIGINAL: the approved original identity source itself.
- PIXEL_CROP: a lossless crop of the original; original pixels, no resampling.
- DETERMINISTIC_TRANSFORM: a declared, parameterized resize/transcode of the
  original; verified structurally (dimensions/format), never assumed to be
  original pixels.
- GENERATED_DERIVATIVE: anything else (regenerated, retouched, re-posed,
  re-costumed). Never an identity authority; may only assist geometry, pose
  or wardrobe of the same already-established person.
"""
import hashlib
from pathlib import Path

DETERMINISTIC_TRANSFORM_OPS = {'RESIZE', 'TRANSCODE'}


def original_reference(record):
    authority = record.get('original_identity_authority')
    if authority is None:
        return None
    if authority.get('mode') != 'APPROVED_ORIGINAL_SOURCE' or not authority.get('approval_basis'):
        raise ValueError('ORIGINAL_IDENTITY_AUTHORITY_INVALID')
    path = Path(authority['path'])
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != authority.get('sha256'):
        raise ValueError('ORIGINAL_IDENTITY_SOURCE_MISSING_OR_CHANGED')
    crop = authority.get('transport_pixel_crop')
    transform = authority.get('transport_deterministic_transform')
    if crop is not None and transform is not None:
        raise ValueError('ORIGINAL_IDENTITY_TRANSPORT_AMBIGUOUS')
    if crop is not None:
        from PIL import Image
        if crop.get('source_sha256') != authority['sha256'] or not crop.get('review_basis'):
            raise ValueError('ORIGINAL_IDENTITY_CROP_PROVENANCE_INVALID')
        target = Path(crop['path'])
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != crop.get('sha256'):
            raise ValueError('ORIGINAL_IDENTITY_CROP_MISSING_OR_CHANGED')
        with Image.open(path) as source, Image.open(target) as actual:
            box = crop.get('box_xyxy')
            if (not isinstance(box, list) or len(box) != 4
                    or any(type(v) is not int for v in box)
                    or not (0 <= box[0] < box[2] <= source.width and 0 <= box[1] < box[3] <= source.height)):
                raise ValueError('ORIGINAL_IDENTITY_CROP_BOUNDS_INVALID')
            expected = source.crop(tuple(box))
            if actual.size != expected.size or actual.mode != expected.mode or actual.tobytes() != expected.tobytes():
                raise ValueError('ORIGINAL_IDENTITY_CROP_PIXELS_CHANGED')
        return {'path': str(target), 'sha256': crop['sha256'], 'role': 'ORIGINAL_IDENTITY_SOURCE',
                'view': 'VERIFIED_SOURCE_PIXEL_CROP', 'asset_type': 'PIXEL_CROP',
                'source_path': str(path), 'source_sha256': authority['sha256'], 'box_xyxy': box}
    if transform is not None:
        from PIL import Image
        op = transform.get('operation')
        params = transform.get('params')
        if (op not in DETERMINISTIC_TRANSFORM_OPS or not isinstance(params, dict) or not params
                or transform.get('source_sha256') != authority['sha256'] or not transform.get('review_basis')):
            raise ValueError('ORIGINAL_IDENTITY_TRANSFORM_PROVENANCE_INVALID')
        target = Path(transform['path'])
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != transform.get('sha256'):
            raise ValueError('ORIGINAL_IDENTITY_TRANSFORM_MISSING_OR_CHANGED')
        with Image.open(target) as actual:
            if op == 'RESIZE':
                size = params.get('target_size')
                if (not isinstance(size, list) or len(size) != 2
                        or any(type(v) is not int or v <= 0 for v in size)
                        or actual.size != tuple(size)):
                    raise ValueError('ORIGINAL_IDENTITY_TRANSFORM_DIMENSIONS_INVALID')
            elif op == 'TRANSCODE':
                fmt = params.get('format')
                if not fmt or (actual.format or '').upper() != str(fmt).upper():
                    raise ValueError('ORIGINAL_IDENTITY_TRANSFORM_FORMAT_INVALID')
        return {'path': str(target), 'sha256': transform['sha256'], 'role': 'ORIGINAL_IDENTITY_SOURCE',
                'view': 'VERIFIED_DETERMINISTIC_TRANSFORM', 'asset_type': 'DETERMINISTIC_TRANSFORM',
                'source_path': str(path), 'source_sha256': authority['sha256'],
                'operation': op, 'params': params}
    return {'path': str(path), 'sha256': authority['sha256'], 'role': 'ORIGINAL_IDENTITY_SOURCE',
            'view': 'APPROVED_SOURCE_CARD', 'asset_type': 'APPROVED_ORIGINAL'}


def classify_reference_asset(entry):
    """Classify a flat reference-transport entry into the four asset types.

    Anything that cannot be verified as APPROVED_ORIGINAL/PIXEL_CROP/
    DETERMINISTIC_TRANSFORM against its own declared provenance is
    GENERATED_DERIVATIVE by default (fail closed toward the weakest claim,
    never toward identity authority).
    """
    try:
        resolved = original_reference({'original_identity_authority': entry}) if entry else None
    except ValueError:
        return 'GENERATED_DERIVATIVE'
    return resolved['asset_type'] if resolved else 'GENERATED_DERIVATIVE'


def measurement_paths(record):
    source = original_reference(record)
    return [source['path']] if source else list(record.get('canonical_reference_paths') or [])
