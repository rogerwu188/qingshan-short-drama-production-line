import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "audit_e18r_multimodal_pilot.py"
SPEC = importlib.util.spec_from_file_location("audit_e18r_multimodal_pilot", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_exact_asr_does_not_require_manual_review():
    assert MODULE.manual_review_reason("官府已经验过了。", "官府已经验过了", 1.0) is None


def test_recall_below_point_nine_requires_manual_review():
    reason = MODULE.manual_review_reason("官府已经验过了。", "官府已经宴过了", 0.857)
    assert reason == "asr_recall_below_0_9_possible_homophone_or_missing_word"


def test_high_score_text_difference_still_requires_manual_review():
    reason = MODULE.manual_review_reason("验过就不会用草席。", "咽过就不会用草席", 0.93)
    assert reason == "asr_text_differs_possible_homophone"
