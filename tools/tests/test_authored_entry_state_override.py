import pytest

from lines.nalu.runtime.tools.adapt_v4_layers_to_runtime import authored_entry_state


def test_no_override_preserves_source():
    assert authored_entry_state("source", {}) == "source"


def test_explicit_override_preserves_input():
    correction = {"original": "source", "replacement": "corrected posture",
                  "reason": "match approved camera", "evidence_ref": "contract#camera"}
    assert authored_entry_state("source", {"entry_state_override": correction}) == "corrected posture"
    assert correction["original"] == "source"


@pytest.mark.parametrize("correction", [{}, "new", {"replacement": "new"},
    {"original": "source", "replacement": "new", "reason": "", "evidence_ref": "ref"}])
def test_missing_evidence_rejected(correction):
    with pytest.raises(ValueError, match="EVIDENCE_REQUIRED"):
        authored_entry_state("source", {"entry_state_override": correction})


def test_stale_override_rejected():
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        authored_entry_state("changed", {"entry_state_override": {
            "original": "source", "replacement": "new", "reason": "reason", "evidence_ref": "ref"}})
