import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lines/nalu/runtime/tools'))
import prompt_batch_finalize as finalizer

def test_isolated_batch_and_transaction_are_read_without_default_state(tmp_path):
    batch = tmp_path / 'batch.json'
    tx = tmp_path / 'tx.json'
    batch.write_text(json.dumps({'episode': 'EP', 'execution_id': 'EX', 'rows': [{'unit_id': 'U'}]}))
    tx.write_text(json.dumps({'tasks': [{'unit_id': 'U'}]}))
    ctx = finalizer.load_ctx('EP', 'EX', batch_path=batch, transaction_path=tx)
    assert ctx[2] == tx
    assert set(ctx[4]) == {'U'}
    with pytest.raises(AssertionError, match='episode mismatch'):
        finalizer.load_ctx('OTHER', 'EX', batch_path=batch, transaction_path=tx)
    with pytest.raises(AssertionError, match='execution id mismatch'):
        finalizer.load_ctx('EP', 'OTHER', batch_path=batch, transaction_path=tx)

def test_half_override_is_rejected(tmp_path):
    with pytest.raises(ValueError, match='Both'):
        finalizer.load_ctx('EP', 'EX', batch_path=tmp_path / 'batch.json')
