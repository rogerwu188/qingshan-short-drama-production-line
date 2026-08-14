import hashlib
import json
import unittest
from pathlib import Path

from tools.build_e40_u01_u16_prompt_precompile import (
    MANIFEST_SHA,
    MODEL,
    SCRIPT_SHA,
    UNITS,
    atomic_windows,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_MANIFEST = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u01_u16_prompt_precompile_v1/E40_U01_U16_STANDARD_VIDEO_PROMPT_MANIFEST_V1.json"
QA_REPORT = ROOT / "qa/e40_preproduction_20260808/E40_U01_U16_PROMPT_STATIC_QA_V1.json"


class E40U01U16PromptPrecompileTests(unittest.TestCase):
    def test_scope_and_canonical_shas_are_exact(self):
        self.assertEqual([row["unit_id"] for row in UNITS], [f"U{i:02d}" for i in range(1, 17)])
        self.assertEqual([row["seconds"] for row in UNITS], [8, 6, 5, 5, 6, 7, 5, 5, 6, 4, 4, 7, 6, 6, 6, 6])
        self.assertEqual(
            hashlib.sha256((ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md").read_bytes()).hexdigest(),
            SCRIPT_SHA,
        )
        self.assertEqual(
            hashlib.sha256((ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json").read_bytes()).hexdigest(),
            MANIFEST_SHA,
        )

    def test_atomic_windows_are_native_speed_dense_and_non_repeating(self):
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

    def test_generated_manifest_is_standard_only_and_never_submit_ready(self):
        manifest = json.loads(OUTPUT_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["tasks"]), 16)
        for task in manifest["tasks"]:
            self.assertEqual(task["model"], MODEL)
            self.assertFalse(task["paid_submission_allowed"])
            self.assertTrue(task["performance_tempo_contract"]["real_time_1x"])
            self.assertTrue(task["first_frame_continuation_contract"])
            prompt = Path(task["prompt_file"])
            self.assertEqual(hashlib.sha256(prompt.read_bytes()).hexdigest(), task["prompt_sha256"])

    def test_static_qa_passes_but_reference_gates_remain_closed(self):
        qa = json.loads(QA_REPORT.read_text(encoding="utf-8"))
        self.assertEqual(qa["status"], "PASS_STATIC_PROMPTS_REFERENCE_BINDING_PENDING")
        self.assertEqual(qa["failures"], [])
        self.assertFalse(qa["paid_submission_allowed"])
        self.assertIn("16_OF_16_EXACT_START_FRAME_AND_REFERENCE_UPLOAD_BINDINGS_PENDING", qa["blocked_by"])


if __name__ == "__main__":
    unittest.main()
