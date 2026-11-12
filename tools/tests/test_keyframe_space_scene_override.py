"""Keyframe tasks keep the subspace task's space_scene_id override (field E06 2026-11-12)."""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
K = importlib.import_module("build_keyframe_manifest")


class SpaceSceneOverrideTests(unittest.TestCase):
    def test_override_is_carried(self) -> None:
        self.assertEqual(K._space_scene_override({"space_scene_id": "E06-S05", "room_id": "ROOM-COURTYARD"}),
                         {"space_scene_id": "E06-S05"})

    def test_no_override_adds_nothing(self) -> None:
        self.assertEqual(K._space_scene_override({"room_id": "R"}), {})
        self.assertEqual(K._space_scene_override({"space_scene_id": ""}), {})

    def test_compile_task_spreads_the_override(self) -> None:
        source = Path(K.__file__).read_text(encoding="utf-8")
        body = source[source.index("def compile_task("):]
        body = body[:body.index("\ndef ", 1)]
        self.assertIn("**_space_scene_override(sp_task)", body)


if __name__ == "__main__":
    unittest.main()
