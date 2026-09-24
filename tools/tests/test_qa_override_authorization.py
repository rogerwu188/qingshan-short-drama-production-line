import copy
import pytest
from tools.qa_override_authorization import validate_override, consume_override


def override(**overrides):
    base = dict(reason='synthetic side-profile accepted by line owner',
                scope=['E01-VU-003'], author='roger', timestamp='2026-09-24T00:00:00Z',
                expiry='2026-10-01T00:00:00Z', input_sha256=['deadbeef' * 8],
                risk='low: cosmetic angle only, no identity/story impact', max_uses=1)
    base.update(overrides)
    return base


def test_valid_override_passes_through_unchanged():
    record = override()
    assert validate_override(record) is record


@pytest.mark.parametrize('field', list(
    ('reason', 'scope', 'author', 'timestamp', 'expiry', 'input_sha256', 'risk', 'max_uses')))
def test_missing_required_field_is_rejected(field):
    record = override()
    del record[field]
    with pytest.raises(ValueError, match='MISSING_FIELDS'):
        validate_override(record)


def test_scope_and_input_sha256_must_be_nonempty_lists():
    with pytest.raises(ValueError, match='SCOPE_MUST_BE_A_NONEMPTY_LIST'):
        validate_override(override(scope='E01-VU-003'))
    with pytest.raises(ValueError, match='SCOPE_MUST_BE_A_NONEMPTY_LIST'):
        validate_override(override(scope=[]))
    with pytest.raises(ValueError, match='INPUT_SHA256_MUST_BE_A_NONEMPTY_LIST'):
        validate_override(override(input_sha256='deadbeef'))


def test_max_uses_must_be_a_positive_int():
    with pytest.raises(ValueError, match='MAX_USES'):
        validate_override(override(max_uses=0))
    with pytest.raises(ValueError, match='MAX_USES'):
        validate_override(override(max_uses=-1))
    with pytest.raises(ValueError, match='MAX_USES'):
        validate_override(override(max_uses='unlimited'))
    with pytest.raises(ValueError, match='MAX_USES'):
        validate_override(override(max_uses=True))


def test_expiry_must_be_after_timestamp():
    with pytest.raises(ValueError, match='EXPIRY_NOT_AFTER_TIMESTAMP'):
        validate_override(override(expiry='2026-09-24T00:00:00Z', timestamp='2026-09-24T00:00:00Z'))
    with pytest.raises(ValueError, match='EXPIRY_NOT_AFTER_TIMESTAMP'):
        validate_override(override(expiry='2026-09-01T00:00:00Z'))


def test_consume_never_mutates_the_original_record():
    record = override()
    frozen = copy.deepcopy(record)
    updated = consume_override(record, scope='E01-VU-003', input_sha256='deadbeef' * 8)
    assert record == frozen
    assert updated is not record
    assert updated['used_count'] == 1
    assert 'used_count' not in record


def test_consume_enforces_scope_and_sha_binding():
    record = override(scope=['E01-VU-003'], input_sha256=['deadbeef' * 8])
    with pytest.raises(ValueError, match='SCOPE_MISMATCH'):
        consume_override(record, scope='E01-VU-999', input_sha256='deadbeef' * 8)
    with pytest.raises(ValueError, match='INPUT_SHA256_MISMATCH'):
        consume_override(record, scope='E01-VU-003', input_sha256='wrong-sha')


def test_consume_respects_expiry():
    record = override(expiry='2026-09-25T00:00:00Z')
    with pytest.raises(ValueError, match='OVERRIDE_EXPIRED'):
        consume_override(record, scope='E01-VU-003', input_sha256='deadbeef' * 8,
                          now='2026-09-26T00:00:00Z')
    consume_override(record, scope='E01-VU-003', input_sha256='deadbeef' * 8,
                      now='2026-09-24T12:00:00Z')


def test_consume_exhausts_after_max_uses():
    record = override(max_uses=2)
    once = consume_override(record, scope='E01-VU-003', input_sha256='deadbeef' * 8)
    twice = consume_override(once, scope='E01-VU-003', input_sha256='deadbeef' * 8)
    assert twice['used_count'] == 2
    with pytest.raises(ValueError, match='OVERRIDE_EXHAUSTED'):
        consume_override(twice, scope='E01-VU-003', input_sha256='deadbeef' * 8)


def test_does_not_authorize_unlimited_subsequent_attempts_by_default():
    # A single-use exception (the common case: one accepted cosmetic deviation)
    # must not be reusable for a second, unrelated retry.
    record = override(max_uses=1)
    once = consume_override(record, scope='E01-VU-003', input_sha256='deadbeef' * 8)
    with pytest.raises(ValueError, match='OVERRIDE_EXHAUSTED'):
        consume_override(once, scope='E01-VU-003', input_sha256='deadbeef' * 8)
