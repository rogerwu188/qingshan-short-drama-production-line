import unittest

from tools.bgm_authenticity_gate import validate_bgm_contract


class BgmAuthenticityContractTests(unittest.TestCase):
    @staticmethod
    def layered_project(contract):
        return {
            "metadata": {
                "audio_profile_id": "LAYERED_POST_WITH_BGM",
                "audio_profile_contract": "configs/audio_postproduction_profiles_v1_20260821.json",
                "source_audio_policy": "NO_NATIVE_DIALOGUE_WITH_EVIDENCE",
                "native_dialogue_absence_evidence": {"status": "PASS", "report": "qa/no_native_dialogue.json"},
                "sound_design_contract": {
                    "mode": "LAYERED_CUES",
                    "required_layers": ["AMBIENCE", "FOLEY", "SFX"],
                    "external_bgm_allowed": True,
                },
                "bgm_contract": contract,
            },
            "output": {"audioSampleRate": 48000},
            "masterAudioPolicy": {"sampleRateHz": 48000},
            "timeline": {"audioTracks": [{"id": "Audio.BGM", "clips": []}]},
        }

    def test_generated_bgm_contract_passes(self):
        project = self.layered_project({
            "source_type": "GENERATED_EPISODE_BGM",
            "dialogue_duck_db": -8,
            "generation_task_id": "task-1",
            "generation_receipt": "workflow/tasks/bgm.json",
            "source_sha256": "a" * 64,
            "credit_evidence": "workflow/credit_reports/bgm.json",
        })
        self.assertEqual(validate_bgm_contract(project), [])

    def test_generated_bgm_ignores_unrelated_metadata(self):
        project = self.layered_project({
            "source_type": "GENERATED_EPISODE_BGM",
            "dialogue_duck_db": -8,
            "generation_task_id": "task-1",
            "generation_receipt": "workflow/tasks/bgm.json",
            "source_sha256": "b" * 64,
            "credit_evidence": "workflow/credit_reports/bgm.json",
            "unrelated_metadata": None,
        })
        self.assertEqual(validate_bgm_contract(project), [])

    def test_library_fallback_needs_reason_and_similarity(self):
        project = self.layered_project({
            "source_type": "LIBRARY_FALLBACK",
            "dialogue_duck_db": -8,
            "music_id": "MUSIC-1",
        })
        failures = validate_bgm_contract(project)
        self.assertIn("LIBRARY_BGM_FALLBACK_REASON_MISSING", failures)
        self.assertIn("LIBRARY_BGM_CROSS_EPISODE_SIMILARITY_NOT_PASS", failures)

    def test_missing_source_priority_contract_fails(self):
        failures = validate_bgm_contract({})
        self.assertIn("AUDIO_PROFILE_NOT_DECLARED", failures)
        self.assertIn("BGM_SOURCE_PRIORITY_CONTRACT_MISSING", failures)

    def test_native_profile_cannot_silently_add_bgm(self):
        project = self.layered_project({
            "source_type": "GENERATED_EPISODE_BGM",
            "dialogue_duck_db": -8,
            "generation_task_id": "task-1",
            "generation_receipt": "workflow/tasks/bgm.json",
            "source_sha256": "c" * 64,
            "credit_evidence": "workflow/credit_reports/bgm.json",
        })
        project["metadata"]["audio_profile_id"] = "NATIVE_MULTIMODAL_NO_EXTERNAL_BGM"
        failures = validate_bgm_contract(project)
        self.assertIn("AUDIO_BGM_TRACK_FORBIDDEN_BY_PROFILE", failures)
        self.assertIn("BGM_CONTRACT_FORBIDDEN_BY_PROFILE", failures)
        self.assertIn("BGM_GATE_CALLED_FOR_NO_EXTERNAL_BGM_PROFILE", failures)


if __name__ == "__main__":
    unittest.main()
