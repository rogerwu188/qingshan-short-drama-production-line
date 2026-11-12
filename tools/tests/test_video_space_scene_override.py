"""S6 video transaction tasks keep the subspace task's space_scene_id override (field E06 2026-11-12)."""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "tools", ROOT):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
P = importlib.import_module("build_nalu_preproduction")


class VideoSpaceSceneOverrideTests(unittest.TestCase):
    def test_override_is_carried(self) -> None:
        self.assertEqual(P.video_space_scene_override({"space_scene_id": "E06-S05", "room_id": "ROOM-COURTYARD"}),
                         {"space_scene_id": "E06-S05"})

    def test_no_override_adds_nothing(self) -> None:
        self.assertEqual(P.video_space_scene_override({"room_id": "R"}), {})
        self.assertEqual(P.video_space_scene_override({"space_scene_id": None}), {})

    def test_transaction_task_spreads_the_override(self) -> None:
        source = Path(P.__file__).read_text(encoding="utf-8")
        body = source[source.index('"task_key": unit["unit_id"],'):]
        body = body[:body.index('"global_space_map_id"')]
        self.assertIn("**video_space_scene_override(task_map)", body)

    def test_gate_accepts_override_mapping(self) -> None:
        try:
            gate = importlib.import_module("global_space_layout_gate")
        except ModuleNotFoundError:
            self.skipTest("gate module unavailable")
        self.assertIn('task.get("space_scene_id") or task.get("scene_id")',
                      Path(gate.__file__).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
