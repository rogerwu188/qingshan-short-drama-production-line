"""SPACE-<scene> (the acting entity of an all-environment unit) is in the prop namespace (field device …1324 E03-VU-008)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.provider_scope_projection import binding_role_for  # noqa: E402


class SpaceEntityBindingRoleTest(unittest.TestCase):
    def test_space_entity_namespace_matches_its_object_reference_role(self):
        self.assertEqual(binding_role_for("SPACE-E03-S02", None), "PROP")
        self.assertEqual(binding_role_for("SPACE-E03-S02", "OBJECT_REFERENCE"), binding_role_for("SPACE-E03-S02", None))

    def test_other_namespaces_unchanged(self):
        self.assertEqual(binding_role_for("CHAR-A", None), "IDENTITY")
        self.assertEqual(binding_role_for("SUBSPACE-E03-S02-07", None), "NON_IDENTITY")
        self.assertEqual(binding_role_for("PROP-BAMBOO", None), "PROP")


if __name__ == "__main__":
    unittest.main()
