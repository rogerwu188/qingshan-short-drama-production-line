"""Original approved source wins over generated derivatives, fail closed."""
import hashlib
from pathlib import Path


def original_reference(record):
    authority = record.get('original_identity_authority')
    if authority is None:
        return None
    if authority.get('mode') != 'APPROVED_ORIGINAL_SOURCE' or not authority.get('approval_basis'):
        raise ValueError('ORIGINAL_IDENTITY_AUTHORITY_INVALID')
    path = Path(authority['path'])
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != authority.get('sha256'):
        raise ValueError('ORIGINAL_IDENTITY_SOURCE_MISSING_OR_CHANGED')
    return {'path': str(path), 'sha256': authority['sha256'], 'role': 'ORIGINAL_IDENTITY_SOURCE',
            'view': 'APPROVED_SOURCE_CARD'}


def measurement_paths(record):
    source = original_reference(record)
    return [source['path']] if source else list(record.get('canonical_reference_paths') or [])
