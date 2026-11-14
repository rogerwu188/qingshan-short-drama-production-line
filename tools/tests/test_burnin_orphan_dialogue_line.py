import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[2] / "lines/nalu/runtime/tools/build_burnin_subtitles.py"
spec = importlib.util.spec_from_file_location("burnin_orphan_line", MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

CONTRACT = {"audio_contract": {"dialogue_units": [
    {"shot_id": "E03-S03-01", "speaker_id": "CHAR-A", "text": "An Eclipse Weaver."},
    {"shot_id": "E03-S03-02", "speaker_id": "CHAR-A", "text": "Stay behind me."},
    {"shot_id": "E03-S03-03", "speaker_id": "CHAR-B", "text": "I will not."},
    {"shot_id": "E03-S03-03", "speaker_id": "CHAR-N", "text": "She never did."},
]}}
SHOT2UNIT = {"E03-S03-02": "E03-VU-009", "E03-S03-03": "E03-VU-009", "E03-S03-04": "E03-VU-010"}
NAMES = {"CHAR-A": "Aria", "CHAR-B": "Bram", "CHAR-N": "Narrator"}


class OrphanDialogueLineTests(unittest.TestCase):
    def test_line_on_a_shot_in_no_unit_is_reported_not_fatal(self):
        by_unit, unmapped = module.contract_lines_by_unit(CONTRACT, SHOT2UNIT, NAMES, {})
        self.assertEqual([row["shot_id"] for row in unmapped], ["E03-S03-01"])
        self.assertEqual(unmapped[0]["text"], "An Eclipse Weaver.")
        self.assertEqual(unmapped[0]["reason"], "DIALOGUE_SHOT_IN_NO_VIDEO_UNIT")
        self.assertEqual([ln["text"] for ln in by_unit["E03-VU-009"]],
                         ["Stay behind me.", "I will not.", "She never did."])

    def test_mapped_lines_keep_contract_order_and_voice_over_is_left_out(self):
        by_unit, unmapped = module.contract_lines_by_unit(CONTRACT, dict(SHOT2UNIT, **{"E03-S03-01": "E03-VU-008"}),
                                                          NAMES, {3: {"start": 1.0, "end": 2.0}})
        self.assertEqual(unmapped, [])
        self.assertEqual(by_unit["E03-VU-008"], [{"shot_id": "E03-S03-01", "speaker": "Aria",
                                                  "text": "An Eclipse Weaver."}])
        self.assertEqual([ln["speaker"] for ln in by_unit["E03-VU-009"]], ["Aria", "Bram"])


if __name__ == "__main__":
    unittest.main()
