import pytest

from tools.long_take_score_gate import adjudicate


def test_long_take_at_60_is_retained():
    result = adjudicate(60)
    assert result["decision"] == "PASS"
    assert result["at_threshold_retained"] is True


def test_long_take_below_60_fails():
    assert adjudicate(59.9)["decision"] == "FAIL"


def test_hard_failure_overrides_high_score():
    result = adjudicate(95, ["IDENTITY"])
    assert result["decision"] == "FAIL"


def test_unknown_hard_failure_is_rejected():
    with pytest.raises(ValueError, match="unsupported hard failures"):
        adjudicate(90, ["CAMERA_TASTE"])
