"""An excluded prop plate keeps its semantic evidence (device ...0736 E09 S5, 2026-11-13).

A prop reference the provider refuses is declared ``transmitted: false`` and leaves
``reference_image_sequence``; its binding stays in ``reference_bindings`` as authority.  The anchor check
accepted it, the semantic-evidence loop only read the transmitted sequence and reported the prop missing.
"""
from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.shot_media_admission_gate import precheck_submission_inputs


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ExcludedPropSemanticEvidenceTest(unittest.TestCase):
    def task(self, root: Path, **prop_overrides) -> dict:
        face, mask, qa = root / "face.png", root / "mask.png", root / "qa.json"
        face.write_bytes(b"face")
        mask.write_bytes(b"mask")
        qa.write_text("{}", encoding="utf-8")
        character = {"role": "character", "entity_id": "CHAR-A", "path": str(face), "sha256": digest(face),
                     "qa_report": str(qa), "asset_origin": "EPISODE_NEW_ASSET"}
        prop = {"role": "prop", "entity_id": "PROP-MASK", "path": str(mask), "sha256": digest(mask),
                "qa_report": str(qa), "asset_origin": "EPISODE_NEW_ASSET", "transmitted": False,
                "transport_excluded_reason": "HOPSAPI_DETERMINISTIC_424_SINGLE_REFERENCE"}
        prop.update(prop_overrides)
        return {
            "media_stage": "KEYFRAME", "require_semantic_anchor_evidence": True,
            "canonical_characters": ["CHAR-A"], "canonical_props": ["PROP-MASK"],
            "reference_bindings": [character, prop],
            "reference_image_sequence": [dict(character)],
        }

    def test_excluded_prop_with_retained_evidence_passes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            report = precheck_submission_inputs(self.task(root), root=root)
            self.assertEqual(report["status"], "PASS", report["failures"])
            self.assertEqual(report["semantic_evidence_missing"], [])

    def test_excluded_prop_without_valid_evidence_still_fails(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            report = precheck_submission_inputs(self.task(root, sha256="0" * 64), root=root)
            self.assertEqual(report["semantic_evidence_missing"], ["PROP-MASK"])
            self.assertIn("SEMANTIC_ANCHOR_EVIDENCE_MISSING", report["failures"])

    def test_untransmitted_prop_without_declared_reason_is_not_evidence(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            report = precheck_submission_inputs(self.task(root, transport_excluded_reason=""), root=root)
            self.assertEqual(report["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
