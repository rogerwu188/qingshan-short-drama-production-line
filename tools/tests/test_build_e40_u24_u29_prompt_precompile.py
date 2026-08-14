import hashlib
import json
import unittest
from pathlib import Path

from tools.build_e40_u24_u29_prompt_precompile import (
    MANIFEST_SHA,
    MODEL,
    SCRIPT_SHA,
    UNITS,
    atomic_windows,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_MANIFEST = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u24_u29_prompt_precompile_v1/E40_U24_U29_STANDARD_VIDEO_PROMPT_MANIFEST_V1.json"
QA_REPORT = ROOT / "qa/e40_preproduction_20260808/E40_U24_U29_PROMPT_STATIC_QA_V1.json"


class E40U24U29PromptPrecompileTests(unittest.TestCase):
    def test_scope_durations_dialogue_and_canonical_shas(self):
        self.assertEqual([row["unit_id"] for row in UNITS], [f"U{i:02d}" for i in range(24, 30)])
        self.assertEqual([row["seconds"] for row in UNITS], [6, 7, 6, 7, 5, 8])
        self.assertEqual(
            hashlib.sha256((ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md").read_bytes()).hexdigest(),
            SCRIPT_SHA,
        )
        self.assertEqual(
            hashlib.sha256((ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json").read_bytes()).hexdigest(),
            MANIFEST_SHA,
        )
        expected = {
            "U24": ["你，不是本宫能买的棋子。"],
            "U25": ["查借印的手，你我同路。阿栓，我带走。"],
            "U26": ["带走罢。官面上，他无案可押。"],
            "U27": ["是否替他下注——你自己拿主意。"],
        }
        self.assertEqual(
            {row["unit_id"]: [text for _speaker, text in row["dialogue"]] for row in UNITS if row["dialogue"]},
            expected,
        )

    def test_atomic_windows_are_dense_native_and_non_repeating(self):
        for spec in UNITS:
            windows = atomic_windows(spec)
            self.assertEqual(windows[0]["start_seconds"], 0.0)
            self.assertLessEqual(windows[0]["end_seconds"], 0.5)
            self.assertEqual(windows[-1]["end_seconds"], spec["seconds"])
            for index, window in enumerate(windows):
                self.assertGreater(window["end_seconds"] - window["start_seconds"], 0)
                self.assertLessEqual(window["end_seconds"] - window["start_seconds"], 1.2)
                if index:
                    self.assertLessEqual(window["start_seconds"] - windows[index - 1]["end_seconds"], 0.25)
                    self.assertNotEqual(window["action"], windows[index - 1]["action"])

    def test_manifest_is_standard_only_and_transport_locked(self):
        manifest = json.loads(OUTPUT_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["tasks"]), 6)
        for task in manifest["tasks"]:
            self.assertEqual(task["model"], MODEL)
            self.assertFalse(task["paid_submission_allowed"])
            self.assertTrue(task["performance_tempo_contract"]["real_time_1x"])
            self.assertIn("WHITE_TEXT_BLACK_STROKE_NO_BLACK_BOX", task["subtitle_transport"])
            prompt = Path(task["prompt_file"])
            self.assertEqual(hashlib.sha256(prompt.read_bytes()).hexdigest(), task["prompt_sha256"])
        u27 = next(task for task in manifest["tasks"] if task["unit_id"] == "U27")
        self.assertIn("VISIBLE_BAILI_SILENT_NO_LIP_MOVEMENT", u27["dialogue_transport"])

    def test_static_qa_passes_with_paid_and_reference_gates_closed(self):
        qa = json.loads(QA_REPORT.read_text(encoding="utf-8"))
        self.assertEqual(qa["status"], "PASS_STATIC_PROMPTS_REFERENCE_BINDING_PENDING")
        self.assertEqual(qa["failures"], [])
        self.assertFalse(qa["paid_submission_allowed"])
        self.assertIn("6_OF_6_EXACT_START_FRAME_AND_ORDERED_REFERENCE_BINDINGS_PENDING", qa["blocked_by"])


if __name__ == "__main__":
    unittest.main()
