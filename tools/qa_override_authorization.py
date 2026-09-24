"""Structured, expiring exceptions to a QA/admission decision — never a
silent bypass.

An override changes only the admission outcome for a bounded scope and a
bounded number of uses. It never rewrites, deletes or replaces the QA
result it overrides: the original QA facts and this override record are
kept side by side, and callers surface both. Authorizing one exception
never authorizes unlimited subsequent attempts — every consumption is
counted and budget-limited.
"""
import datetime as _dt

REQUIRED_FIELDS = ('reason', 'scope', 'author', 'timestamp', 'expiry',
                    'input_sha256', 'risk', 'max_uses')


def _parse_ts(value):
    text = str(value)
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f'OVERRIDE_TIMESTAMP_INVALID:{value}') from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed


def validate_override(record):
    """Raise if the override record is structurally invalid. Never inspects
    QA content — callers decide whether a valid override actually applies
    to a given failure."""
    if not isinstance(record, dict):
        raise ValueError('OVERRIDE_NOT_AN_OBJECT')
    missing = [field for field in REQUIRED_FIELDS
               if record.get(field) is None or record.get(field) == '']
    if missing:
        raise ValueError(f'OVERRIDE_MISSING_FIELDS:{",".join(missing)}')
    if not isinstance(record['scope'], (list, tuple)) or not record['scope']:
        raise ValueError('OVERRIDE_SCOPE_MUST_BE_A_NONEMPTY_LIST')
    if not isinstance(record['input_sha256'], (list, tuple)) or not record['input_sha256']:
        raise ValueError('OVERRIDE_INPUT_SHA256_MUST_BE_A_NONEMPTY_LIST')
    if not isinstance(record['max_uses'], int) or isinstance(record['max_uses'], bool) or record['max_uses'] <= 0:
        raise ValueError('OVERRIDE_MAX_USES_MUST_BE_A_POSITIVE_INT')
    used = record.get('used_count', 0)
    if not isinstance(used, int) or isinstance(used, bool) or used < 0:
        raise ValueError('OVERRIDE_USED_COUNT_INVALID')
    created = _parse_ts(record['timestamp'])
    expires = _parse_ts(record['expiry'])
    if expires <= created:
        raise ValueError('OVERRIDE_EXPIRY_NOT_AFTER_TIMESTAMP')
    return record


def consume_override(record, *, scope, input_sha256, now=None):
    """Check the override still applies and has budget left; return a NEW
    record with used_count incremented. Never mutates the input record and
    never touches any QA result the caller holds alongside it — that
    result is preserved by the caller exactly as originally produced."""
    validate_override(record)
    now = _parse_ts(now) if now is not None else _dt.datetime.now(_dt.timezone.utc)
    if now >= _parse_ts(record['expiry']):
        raise ValueError('OVERRIDE_EXPIRED')
    if scope not in record['scope']:
        raise ValueError('OVERRIDE_SCOPE_MISMATCH')
    if input_sha256 not in record['input_sha256']:
        raise ValueError('OVERRIDE_INPUT_SHA256_MISMATCH')
    used = record.get('used_count', 0)
    if used >= record['max_uses']:
        raise ValueError('OVERRIDE_EXHAUSTED')
    updated = dict(record)
    updated['used_count'] = used + 1
    return updated
