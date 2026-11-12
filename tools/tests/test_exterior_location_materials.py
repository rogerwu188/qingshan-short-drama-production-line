"""An exterior shot's 材质细节 comes from its own space map (Abandoned at the Altar E01, 2026-11-12).

Every *-EXT location used to get a fixed 积雪/树皮与松针/雪面反光/粗布与皮革 list, so a contemporary
chapel entrance in daylight was prompted with snow, pine needles and coarse period cloth and S5
prompt review held the whole batch.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import build_nalu_preproduction as bp  # noqa: E402

VCC = {"production_design": "木构屋架、瓦顶、夯土院墙、粗布帷幔、铜灯"}


class ExteriorLocationMaterialsTest(unittest.TestCase):
    def test_exterior_uses_declared_elements_not_snow(self) -> None:
        materials = bp.location_materials("CHAPEL-ENTRANCE-EXT", VCC,
                                          ["木门", "浅色石阶", "白色花槽"], ["教堂入口"])
        self.assertEqual(materials[:3], ["木门的真实材质", "浅色石阶的真实材质", "白色花槽的真实材质"])
        joined = "".join(materials)
        for leaked in ("积雪", "松针", "粗布", "瓦顶", "屋架"):
            self.assertNotIn(leaked, joined)

    def test_exterior_without_declared_objects_stays_neutral(self) -> None:
        self.assertEqual(bp.location_materials("forest-edge-ext", VCC, [], []), ["场景已声明的室外真实材质"])

    def test_interior_keeps_production_design(self) -> None:
        self.assertEqual(bp.location_materials("HALL-INT", VCC, ["木门"], ["大厅"]),
                         ["木构屋架", "瓦顶", "夯土院墙", "粗布帷幔"])


if __name__ == "__main__":
    unittest.main()
