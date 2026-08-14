import unittest

from tools.compile_e18r_coverage_manifest import compile_manifest


class E18RCoverageManifestTest(unittest.TestCase):
    def fixtures(self):
        structure = []
        dialogue = []
        voice_lines = []
        locks = {
            "B01": ["E18R-VL-PASTRY-BOX"],
            "B02": ["E18R-VL-NIGHT-ROAD-STRETCHER", "E18R-VL-BRUISED-HAND-INSERT"],
            "B03": [],
            "B04": ["E18R-VL-CARRIAGE-TEST"],
            "B05": ["E18R-VL-RED-JADE-PENDANT"],
            "B06": [],
        }
        types = ["dialogue", "burst", "dialogue", "dialogue_burst", "burst", "hook"]
        for index, (beat_id, required) in enumerate(locks.items(), start=1):
            structure.append({"beat_id": beat_id, "name": beat_id, "target_seconds": 20, "segment_type": types[index - 1], "must_show": []})
            line = {"dia_id": f"DIA-{index:03d}", "beat_id": beat_id}
            dialogue.append(line)
            voice_lines.append({"dia_id": line["dia_id"]})
        beat_sheet = {"structure": structure, "dialogue_draft": dialogue, "runtime_target_seconds": {"min": 165, "target": 174, "max": 185}}
        voice = {"lines": voice_lines}
        status = {"submitted": [{"view_id": item} for values in locks.values() for item in values]}
        return beat_sheet, voice, status

    def test_all_dialogue_and_locks_are_covered(self):
        result = compile_manifest(*self.fixtures())
        self.assertEqual(result["dialogue_count"], 6)
        self.assertEqual(result["beat_count"], 6)
        self.assertTrue(result["coverage_checks"]["all_new_static_locks_submitted"])

    def test_voice_order_mismatch_fails(self):
        beat_sheet, voice, status = self.fixtures()
        voice["lines"].reverse()
        with self.assertRaises(ValueError):
            compile_manifest(beat_sheet, voice, status)


if __name__ == "__main__":
    unittest.main()
