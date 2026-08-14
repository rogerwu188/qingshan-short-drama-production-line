import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "build_e17_real_ambience_bed", ROOT / "tools/build_e17_real_ambience_bed.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class E17RealAmbienceBedTest(unittest.TestCase):
    def test_output_must_be_explicitly_non_final(self):
        MODULE.validate_output_path(Path("E17_DIAGNOSTIC_NOT_FINAL.wav"))
        with self.assertRaises(ValueError):
            MODULE.validate_output_path(Path("E17_final.wav"))

    def test_adjacent_digital_zero_rows_merge(self):
        self.assertEqual(
            MODULE.merge_windows([(1.0, 2.0), (2.001, 3.0), (5.0, 6.0)]),
            [(1.0, 3.0), (5.0, 6.0)],
        )

    def test_cut_mapping_removes_only_approved_interval(self):
        self.assertEqual(
            MODULE.map_interval_after_cut(39.533008, 42.366341, 9.725, 15.1),
            [(34.158008, 36.991341)],
        )
        self.assertEqual(
            MODULE.map_interval_after_cut(8.0, 16.0, 9.725, 15.1),
            [(8.0, 9.725), (9.725, 10.625)],
        )

    def test_multi_cut_mapping_uses_original_source_coordinates(self):
        cuts = [(9.725, 15.1), (103.5, 109.2916666667)]
        self.assertEqual(
            MODULE.map_interval_after_cuts(100.0, 112.0, cuts),
            [
                (94.625, 98.125),
                (98.125, 100.83333333330001),
            ],
        )

    def test_alignment_cuts_prefers_multi_edit_report(self):
        alignment = {
            "audio_edit": {"approved_cut_seconds": [9.725, 15.1]},
            "audio_edits": [
                {"approved_cut_seconds": [9.725, 15.1]},
                {"approved_cut_seconds": [103.5, 109.2916666667]},
            ],
        }
        self.assertEqual(
            MODULE.alignment_cuts(alignment),
            [(9.725, 15.1), (103.5, 109.2916666667)],
        )

    def test_audit_rows_map_to_six_aligned_windows(self):
        audit = {
            "digital_zero_shots": [
                {"start_sec": 39.533008, "end_sec": 42.366341},
                {"start_sec": 58.733008, "end_sec": 61.066341},
                {"start_sec": 61.066341, "end_sec": 62.266341},
                {"start_sec": 159.833008, "end_sec": 170.62},
            ]
        }
        alignment = {
            "audio_edit": {"approved_cut_seconds": [9.725, 15.1]},
            "output": {"expected_duration_seconds": 165.25},
        }
        self.assertEqual(
            MODULE.mapped_digital_zero_windows(audit, alignment),
            [
                (34.158008, 36.991341),
                (53.358008, 56.891341),
                (154.458008, 165.245),
            ],
        )

    def test_verified_windows_cover_every_audited_target_silence_intersection(self):
        audit = {
            "digital_zero_shots": [
                {"start_sec": 39.533008, "end_sec": 42.366341}
            ],
            "unmotivated_silence_segments": [
                {"start_sec": 0.0, "end_sec": 2.5},
                {"start_sec": 39.484479, "end_sec": 52.921583}
            ],
        }
        alignment = {
            "audio_edit": {"approved_cut_seconds": [9.725, 15.1]},
            "output": {"expected_duration_seconds": 165.25},
        }
        self.assertEqual(
            MODULE.verified_fill_windows(
                audit,
                alignment,
                [(0.0, 2.54), (34.306312, 47.76925)],
                0.02,
            ),
            [(0.02, 2.48), (34.326312, 47.526583)],
        )

    def test_filter_uses_single_sample_accurate_gate(self):
        graph = MODULE.build_filter_graph(
            20.0, 192000, [(2.0, 4.0), (8.0, 10.0)], 9.0, 0.15
        )
        self.assertIn("aloop=loop=-1:size=192000", graph)
        self.assertIn("aeval=exprs=", graph)
        self.assertNotIn("adelay=", graph)
        self.assertNotIn("asplit=", graph)


if __name__ == "__main__":
    unittest.main()
