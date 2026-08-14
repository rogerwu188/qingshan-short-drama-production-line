import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.performance_unit_split_gate import evaluate


class PerformanceUnitSplitGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.audio = self.base / "voice.wav"
        self.audio.write_bytes(b"voice")
        self.video_a = self.base / "a.mp4"
        self.video_b = self.base / "b.mp4"
        self.video_a.write_bytes(b"video-a")
        self.video_b.write_bytes(b"video-b")

    def tearDown(self):
        self.temp.cleanup()

    def unit(self, unit_id, order, dialogue_ids):
        return {
            "unit_id": unit_id,
            "replaces_unit_id": "U16",
            "split_order": order,
            "duration_seconds": 4,
            "dialogue_ids": dialogue_ids,
            "same_speaker_contiguous_dialogue": len(dialogue_ids) > 1,
            "dialogue_audio_strategy": "SINGLE_BEAT_ALIGNED_CONTIGUOUS_AUDIO",
            "dialogue_audio_bindings": [
                {
                    "dialogue_id": dialogue_id,
                    "audio_slot": "@audio1",
                    "path": "voice.wav",
                    "sha256": hashlib.sha256(b"voice").hexdigest(),
                }
                for dialogue_id in dialogue_ids
            ],
            "reference_plan": {
                "policy": "DYNAMIC_BY_MODEL_CAPABILITY_AND_ACTION_DESIGN",
                "selected_count": 1,
                "rationale": "One identity anchor is sufficient for this simple performance.",
            },
            "motion_beats": [{
                "start_seconds": 0,
                "end_seconds": 4,
                "subject": "speaker",
                "action": "speaks and turns",
                "contact_point": "feet on roof",
                "direction": "left to right",
                "end_state": "faces listener",
                "expression": "alert",
                "intent": "warn listener",
            }],
        }

    def contract(self):
        return {
            "episode": "E32",
            "source_unit_id": "U16",
            "source_dialogue_ids": ["D1", "D2", "D3"],
            "split_boundary_evidence": ["speaker_transition", "action_purpose_transition"],
            "duration_policy": "NATURAL_PERFORMANCE_SECONDS_NO_ORIGINAL_DURATION_FLOOR",
            "reference_count_policy": "DYNAMIC_BY_MODEL_CAPABILITY_AND_ACTION_DESIGN",
            "streaming_submission_policy": "SUBMIT_EACH_UNIT_IMMEDIATELY_WHEN_ITS_OWN_DEPENDENCIES_PASS",
            "unit_order": ["U16A", "U16B"],
            "units": [self.unit("U16A", 1, ["D1", "D2"]), self.unit("U16B", 2, ["D3"])],
        }

    def admission(self):
        common = {
            "preserved_passes": {
                "identity": "PASS",
                "scene_authority": "PASS",
                "audio_stream": "PASS",
                "frame_cadence": "PASS",
                "story_facts": "PASS",
            }
        }
        return {
            "units": [
                {
                    **common,
                    "unit_id": "U16A",
                    "decision": "CONDITIONAL_MACHINE_ADMISSION",
                    "candidate_path": "a.mp4",
                    "candidate_sha256": hashlib.sha256(b"video-a").hexdigest(),
                    "dialogue_ids_asr_pass": ["D1", "D2"],
                    "original_qa_status": "FAIL",
                    "original_failures": ["minor spatial clarity"],
                    "selection_reason": "All facts remain legible in dialogue.",
                    "confidence": 0.9,
                    "rollback_point": "a.mp4",
                    "replacement_condition": "Replace only with a stronger already-paid candidate.",
                },
                {
                    **common,
                    "unit_id": "U16B",
                    "decision": "PASS",
                    "candidate_path": "b.mp4",
                    "candidate_sha256": hashlib.sha256(b"video-b").hexdigest(),
                    "dialogue_ids_asr_pass": ["D3"],
                },
            ]
        }

    def test_accepts_natural_streaming_split_with_conditional_item(self):
        result = evaluate(self.contract(), admission=self.admission(), base=self.base)
        self.assertEqual(result["status"], "PASS")

    def test_blocks_episode_wide_wait(self):
        contract = self.contract()
        contract["streaming_submission_policy"] = "WAIT_FOR_ALL_UNITS"
        result = evaluate(contract, base=self.base)
        self.assertIn("episode_wide_wait_or_non_streaming_submission_policy", result["failures"])

    def test_blocks_equal_duration_split_without_natural_boundary(self):
        contract = self.contract()
        contract["split_boundary_evidence"] = ["equal_duration_partition"]
        result = evaluate(contract, base=self.base)
        self.assertIn("split_not_bound_to_authored_natural_boundary", result["failures"])

    def test_blocks_separate_audio_modalities_for_contiguous_lines(self):
        contract = self.contract()
        contract["units"][0]["dialogue_audio_bindings"][1]["audio_slot"] = "@audio2"
        result = evaluate(contract, base=self.base)
        self.assertIn("contiguous_dialogue_split_across_modalities:U16A", result["failures"])

    def test_blocks_missing_post_generation_replacement(self):
        admission = self.admission()
        admission["units"].pop()
        result = evaluate(self.contract(), admission=admission, base=self.base)
        self.assertIn("post_generation_replacement_coverage_mismatch", result["failures"])


if __name__ == "__main__":
    unittest.main()
