"""Reference transport count: shared-file bindings and protected authorities.

Converted from bare pytest functions to unittest so the portable CI command
(``python -m unittest <portable_test_modules>``) actually collects it — before this it
reported ``Ran 0 tests`` while appearing to pass.
"""
import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lines/nalu/runtime/tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from build_keyframe_manifest import cap_non_character_bindings  # noqa: E402


class TransportCount(unittest.TestCase):
    def test_shared_authority_file_does_not_drop_wardrobe(self):
        rows = [
            {"role": "subspace_layout", "path": "map.png"},
            {"role": "scene", "path": "map.png"},
            {"role": "character", "path": "face.png"},
            {"role": "character_wardrobe", "path": "costume.png"},
        ]
        original = deepcopy(rows)
        kept, dropped = cap_non_character_bindings(rows, total_limit=3)
        self.assertEqual(kept, original)
        self.assertEqual(dropped, [])
        self.assertEqual(rows, original)

    def test_actual_overflow_retains_protected_authorities(self):
        rows = [
            {"role": "subspace_layout", "path": "map.png"},
            {"role": "scene", "path": "scene.png"},
            {"role": "character", "path": "face.png"},
            {"role": "character_wardrobe", "path": "costume.png"},
        ]
        kept, dropped = cap_non_character_bindings(rows, total_limit=3)
        self.assertEqual(kept, rows[:3])
        self.assertEqual([row["role"] for row in dropped], ["character_wardrobe"])
        # The downstream provider-count guard must reject protected overflow;
        # this helper must never silently discard faces or maps to make it fit.
        kept, _ = cap_non_character_bindings(rows[:3], total_limit=2)
        self.assertEqual(kept, rows[:3])

    def test_overflow_may_drop_only_explicit_background_identity_after_wardrobe(self):
        rows = [
            {"role": "subspace_layout", "path": "map.png"},
            {"role": "scene", "path": "scene.png"},
            {"role": "character", "entity_id": "PRIMARY", "path": "primary.png"},
            {"role": "character", "entity_id": "BACKGROUND", "path": "background.png"},
            {"role": "character_wardrobe", "entity_id": "PRIMARY", "path": "primary-costume.png"},
        ]
        kept, dropped = cap_non_character_bindings(
            rows, total_limit=3, optional_character_ids={"BACKGROUND"}
        )
        self.assertEqual({r["entity_id"] for r in kept if r["role"] == "character"}, {"PRIMARY"})
        self.assertEqual([r["dropped_reason"] for r in dropped],
                         ["REFERENCE_TOTAL_MAX_3", "REFERENCE_TOTAL_MAX_3_OPTIONAL_BACKGROUND_IDENTITY"])


if __name__ == "__main__":
    unittest.main()
