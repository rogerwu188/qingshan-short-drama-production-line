"""A measurement that found no canonical plate must not be reported as a verdict on an image.

E11 (2026-10-09): a submit run started without NALU_RUNTIME_ROOT read another work's character
registry, measured nothing, and the empty result became 26 identity P0 failures against keyframes
that measure 0.63-0.87 when the runtime root is set.  The gate said "not admitted"; nothing in it
said "nothing was measured".
"""
import importlib
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


class CanonicalPlatesAbsentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("keyframe_q1_builder")

    def test_a_registry_without_the_declared_character_is_named_not_scored(self) -> None:
        with TemporaryDirectory() as tmp:
            registry = Path(tmp) / "registry.json"
            registry.write_text(json.dumps({
                "schema": "nalu.character_asset_registry.v1", "series_id": "OTHER-WORK",
                "characters": {"else": {"character_id": "CHAR-ELSE", "status": "LOCKED",
                                        "canonical_reference_paths": []}}}), encoding="utf-8")
            keyframe = Path(tmp) / "E99-S01-01-keyframe-v1.png"
            keyframe.write_bytes(b"not-a-real-png")
            result = self.mod.measure_still_identity(
                "E99", {"E99-S01-01": keyframe}, {"E99-S01-01": ["CHAR-QINMING"]},
                registry_path=registry)
        self.assertEqual(result["status"], "CANONICAL_PLATES_ABSENT_FOR_DECLARED_CHARACTERS")
        joined = " ".join(result["failures"])
        self.assertIn("IDENTITY_MEASUREMENT_NO_CANONICAL_PLATES:CHAR-QINMING", joined)
        self.assertIn("registry=", joined)
        # and it must NOT claim that the image itself failed anything
        self.assertNotIn("DECLARED_CHARACTER_FACE_NOT_FOUND", joined)

    def test_a_shot_with_no_declared_character_is_untouched(self) -> None:
        with TemporaryDirectory() as tmp:
            registry = Path(tmp) / "registry.json"
            registry.write_text(json.dumps({
                "schema": "nalu.character_asset_registry.v1", "series_id": "S",
                "characters": {"qin": {"character_id": "CHAR-QINMING", "status": "LOCKED",
                                       "canonical_reference_paths": []}}}), encoding="utf-8")
            result = self.mod.measure_still_identity("E99", {}, {}, registry_path=registry)
        self.assertEqual(result["status"], "NO_CHARACTER_SOURCE_MEASURED")
        # a locked character with no plate file is a plate problem, reported as one
        self.assertTrue(any("CANONICAL_VIEWS_BELOW_POLICY" in f for f in result["failures"]))

    def test_an_empty_registry_is_reported_as_a_registry_problem(self) -> None:
        """No characters at all fails earlier and more plainly: the registry is the problem."""
        with TemporaryDirectory() as tmp:
            registry = Path(tmp) / "registry.json"
            registry.write_text(json.dumps({"schema": "x", "series_id": "S",
                                            "characters": {}}), encoding="utf-8")
            result = self.mod.measure_still_identity("E99", {}, {}, registry_path=registry)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("CHARACTER_REGISTRY_ABSENT_OR_EMPTY" in f for f in result["failures"]))


if __name__ == "__main__":
    unittest.main()
