#!/usr/bin/env python3
"""identity_reference_overrides.json rows are bound by id namespace: a character row stays a
CHARACTER_REFERENCE (unchanged), a prop row is a PROP_REFERENCE, so shot_media_admission_gate no longer
raises REFERENCE_ROLE_NAMESPACE_CONFLICT for it (fleet device ...1342 E04-VU-011, 2026-11-14)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NALU_TOOLS = ROOT / "lines/nalu/runtime/tools"
sys.path.insert(0, str(ROOT))

from tools.provider_scope_projection import binding_role_for  # noqa: E402


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ReferenceOverridePropBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.bnp = load("bnp_override_binding", NALU_TOOLS / "build_nalu_preproduction.py")
        except Exception as exc:  # noqa: BLE001 - the module needs the full engine tree
            raise unittest.SkipTest(f"build_nalu_preproduction not importable: {exc}")

    def test_prop_row_binds_as_prop_reference(self):
        extra = {"character_id": "PROP-TABLE", "path": "/plates/table.png", "role": "PROP_REFERENCE"}
        row = self.bnp.override_reference_binding(extra, path="/plates/table.png", sha256="ab", english_names=True)
        self.assertEqual(row["role"], "PROP_REFERENCE")
        self.assertEqual(row["provider_entity_label"], "Table")
        self.assertEqual(row["sha256"], "ab")
        # the declared role and the id namespace agree, which is what the admission gate compares
        self.assertEqual(binding_role_for("PROP-TABLE", row["role"]), binding_role_for("PROP-TABLE", None))
        self.assertEqual(self.bnp.override_reference_role(extra), "PROP_REFERENCE")
        self.assertEqual(self.bnp.override_reference_role({"character_id": "PROP-TABLE"}), "PROP_REFERENCE")

    def test_character_row_is_unchanged(self):
        extra = {"character_id": "CHAR-A", "path": "/plates/a.png"}
        row = self.bnp.override_reference_binding(extra, path="/plates/a.png", sha256="cd", english_names=False)
        self.assertEqual(row, {"entity_id": "CHAR-A", "role": "CHARACTER_REFERENCE", "path": "/plates/a.png",
                               "sha256": "cd", "source": "IDENTITY_REFERENCE_OVERRIDE_LOCKED_PLATE"})
        self.assertEqual(list(row), ["entity_id", "role", "path", "sha256", "source"])
        self.assertEqual(self.bnp.override_reference_role(extra), "CHARACTER_IDENTITY_REFERENCE")
        self.assertEqual(binding_role_for("CHAR-A", row["role"]), binding_role_for("CHAR-A", None))


if __name__ == "__main__":
    unittest.main()
