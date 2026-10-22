"""A character-free insert showing an undeclared figure must still yield an acceptable detector
(Twelve Gazes E01-VU-004, 2026-10-22): otherwise the default acceptance can never bind."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2]


def _pipeline():
    spec = importlib.util.spec_from_file_location("nalu_pipeline_q1det", ENGINE / "lines/nalu/runtime/tools/nalu_pipeline.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["nalu_pipeline_q1det"] = module
    spec.loader.exec_module(module)
    return module


ROW = {"item_id": "E01-S02-03", "admission_request": ""}
GATE = "CHARACTER-IDENTITY-ADMISSION"


def test_character_free_insert_failure_gets_a_gate_level_detector():
    p = _pipeline()
    failures = ["FAIL:STRUCTURED_NO_VISIBLE_CHARACTER_V1: no canonical character declared visible; "
                "structured no-character scope failures cast_exactly_as_declared,CHARACTER_OBSERVED_IN_CHARACTER_FREE_INSERT"]
    assert p.q1_gate_detectors(ROW, GATE, failures, []) == ["E01-S02-03:CHARACTER-IDENTITY-ADMISSION"]


def test_declared_character_detectors_are_unchanged():
    p = _pipeline()
    decisions = [{"source_id": "E01:STILL:E01-S02-03", "character_id": "CHAR-ELIAS", "decision": "FAIL"}]
    assert p.q1_gate_detectors(ROW, GATE, ["FAIL:low cosine"], decisions) == ["E01-S02-03:CHAR-ELIAS"]


def test_identity_failure_without_measurable_face_gets_the_gate_detector():
    # E01-VU-009: declared character, reviewer UNCERTAIN, NO_FACE_MEASURED -> no per-character row
    p = _pipeline()
    assert p.q1_gate_detectors(ROW, GATE, ["FAIL:UNCERTAIN:NO_FACE_MEASURED"], []) == [
        "E01-S02-03:CHARACTER-IDENTITY-ADMISSION"]
