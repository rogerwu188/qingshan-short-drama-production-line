"""S1 R5A accepts the HopsAPI 4 s floor for a short CAMERA_GRAMMAR_V1 line (lab E09); R11 still warns."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))
import nalu_writer_selfcheck_seq29 as sc  # noqa: E402

FIXTURE = ROOT / "workflow/nalu/E09/preproduction/reports/E09_SHORT_LINE_REPRO_CONTRACT.json"


class ProviderFloorTests(unittest.TestCase):
    def test_spoken_strips_long_fullwidth_speaker_label(self) -> None:
        self.assertEqual(sc._spoken("Spaulding：Third right, fourth left,"), "Third right, fourth left,")

    @unittest.skipUnless(FIXTURE.is_file(), "lab fixture not present")
    def test_short_line_at_floor_passes_with_warning(self) -> None:
        report = sc.evaluate(json.loads(FIXTURE.read_text(encoding="utf-8")))
        failures = report.get("failures") or []
        self.assertFalse([f for f in failures if str(f).startswith("R5A_DIALOGUE_SHOT_TEMPLATE_DURATION")], failures)
        self.assertTrue(any(str(w).startswith("R11_SHORT_SPEAKING_LINE") for w in report.get("warnings") or []))

    def test_unstamped_contract_has_no_floor(self) -> None:
        self.assertEqual(sc.provider_floor_seconds({"episode": "E99", "shots": []}), 0.0)


if __name__ == "__main__":
    unittest.main()
