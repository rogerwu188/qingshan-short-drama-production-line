"""combat_density — cut density arithmetic and the silhouette similarity metric."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import combat_density_check as density  # noqa: E402


def test_cut_density_requires_a_cut_per_window():
    assert density.cut_density([], 7.3)["status"] == "FAIL"
    assert density.cut_density([2.0], 7.3)["status"] == "PASS"
    assert density.cut_density([], 7.3, declared_cuts=1)["status"] == "PASS"


def test_long_unit_needs_more_cuts():
    result = density.cut_density([1.0], 12.0)
    assert result["windows"] == 3 and result["required_cuts"] == 2
    assert result["status"] == "FAIL"


def test_shape_similarity_identical_is_one():
    sig = {"area": 0.2, "aspect": 0.3, "fill": 0.7}
    assert density.shape_similarity(sig, sig) == 1.0


def test_shape_similarity_penalises_different_aspect():
    card = {"area": 0.2, "aspect": 0.15, "fill": 0.7}   # a long shaft
    frame = {"area": 0.2, "aspect": 0.9, "fill": 0.7}   # a broad blade
    assert density.shape_similarity(card, frame) < density.MIN_SHAPE_SIMILARITY


def test_missing_signature_is_zero():
    assert density.shape_similarity({"area": 0, "aspect": 0, "fill": 0}, {"area": 1, "aspect": 1, "fill": 1}) == 0.0
