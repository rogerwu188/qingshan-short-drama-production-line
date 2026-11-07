#!/usr/bin/env python3
"""Roger 2026-11-07 (E15 fight redesign ①): a prop the writer flags ``video_reference_card`` joins its H3 unit's
references as the LOCKED prop card (role PROP_REFERENCE, entity-bound), after the identity plates; unflagged
units keep their reference set; a flagged prop without a LOCKED card is reported, never fabricated."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
NALU_TOOLS = ROOT / "lines/nalu/runtime/tools"
sys.path.insert(0, str(ROOT))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class PropReferenceCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.bnp = load("bnp_prop_cards", NALU_TOOLS / "build_nalu_preproduction.py")
        except Exception as exc:  # noqa: BLE001 - the module needs the full engine tree
            raise unittest.SkipTest(f"build_nalu_preproduction not importable: {exc}")

    def editorial(self, *, flagged: bool):
        prop = {"prop_id": "PROP-FUENTAO-SABRE", "prop": "弧背大刀", **({"video_reference_card": True} if flagged else {})}
        return {"shots": [{"shot_id": "S1", "prompt_spec": {"cast": [], "props": [prop]}}]}

    def anchor(self):
        return {"units": [{"unit_id": "U1", "reference_image_paths": ["/kf/S1.png"],
                           "reference_image_task_keys": ["S1"],
                           "anchor_count_decision": {"anchor_roles": ["ADMITTED_NEW_EVENT_ENTRY_STATE"]},
                           "reference_entity_bindings": [None], "planned_reference_image_count": 1}]}

    def test_flagged_prop_appends_the_locked_card_after_the_anchors(self):
        plan = {"units": [{"unit_id": "U1", "editorial_shot_ids": ["S1"]}]}
        anchor = self.anchor()
        with patch.object(self.bnp, "_locked_prop_plate", return_value=Path("/cards/PROP-FUENTAO-SABRE.png")):
            missing = self.bnp.append_h3_prop_plates(anchor, plan, self.editorial(flagged=True), episode="E15")
        unit = anchor["units"][0]
        self.assertEqual(missing, [])
        self.assertEqual(unit["reference_image_paths"], ["/kf/S1.png", "/cards/PROP-FUENTAO-SABRE.png"])
        self.assertEqual(unit["reference_image_task_keys"], ["S1", "PROP_PLATE:PROP-FUENTAO-SABRE"])
        self.assertEqual(unit["anchor_count_decision"]["anchor_roles"],
                         ["ADMITTED_NEW_EVENT_ENTRY_STATE", "PROP_REFERENCE"])
        self.assertEqual(unit["reference_entity_bindings"],
                         [None, {"entity_id": "PROP-FUENTAO-SABRE", "provider_entity_label": "Fuentao Sabre"}])
        self.assertEqual(unit["planned_reference_image_count"], 2)
        self.assertEqual(unit["h3_prop_reference_cards"], ["PROP-FUENTAO-SABRE"])

    def test_unflagged_prop_leaves_the_unit_untouched(self):
        plan = {"units": [{"unit_id": "U1", "editorial_shot_ids": ["S1"]}]}
        anchor = self.anchor()
        with patch.object(self.bnp, "_locked_prop_plate", return_value=Path("/cards/PROP-FUENTAO-SABRE.png")):
            missing = self.bnp.append_h3_prop_plates(anchor, plan, self.editorial(flagged=False), episode="E15")
        self.assertEqual(missing, [])
        self.assertEqual(anchor["units"][0]["reference_image_paths"], ["/kf/S1.png"])
        self.assertNotIn("h3_prop_reference_cards", anchor["units"][0])

    def test_flagged_prop_without_a_locked_card_is_reported_not_fabricated(self):
        plan = {"units": [{"unit_id": "U1", "editorial_shot_ids": ["S1"]}]}
        anchor = self.anchor()
        with patch.object(self.bnp, "_locked_prop_plate", return_value=None):
            missing = self.bnp.append_h3_prop_plates(anchor, plan, self.editorial(flagged=True), episode="E15")
        self.assertEqual(missing, ["U1:PROP-FUENTAO-SABRE"])
        self.assertEqual(anchor["units"][0]["reference_image_paths"], ["/kf/S1.png"])

    def test_locked_prop_plate_requires_lock_pass_and_matching_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = Path(tmp) / "card.png"
            card.write_bytes(b"png")
            sha = hashlib.sha256(b"png").hexdigest()
            library = {"assets": {"props": {
                "PROP-OK": {"status": "LOCKED", "qa": {"status": "PASS"}, "artifacts": [{"path": str(card), "sha256": sha}]},
                "PROP-UNLOCKED": {"status": "REQUIRED_UNCREATED", "artifacts": [{"path": str(card), "sha256": sha}]},
                "PROP-BAD-SHA": {"status": "LOCKED", "qa": {"status": "PASS"}, "artifacts": [{"path": str(card), "sha256": "0" * 64}]},
            }}}
            lib_path = Path(tmp) / "asset_library.json"
            with patch.object(self.bnp, "_scoped_asset_library_path", return_value=lib_path), \
                    patch.dict(self.bnp._ASSET_LIBRARY_CACHE, {str(lib_path.resolve()): library}, clear=False):
                self.assertEqual(self.bnp._locked_prop_plate("PROP-OK", episode="E15"), card)
                self.assertIsNone(self.bnp._locked_prop_plate("PROP-UNLOCKED", episode="E15"))
                self.assertIsNone(self.bnp._locked_prop_plate("PROP-BAD-SHA", episode="E15"))
                self.assertIsNone(self.bnp._locked_prop_plate("PROP-ABSENT", episode="E15"))


if __name__ == "__main__":
    unittest.main()
