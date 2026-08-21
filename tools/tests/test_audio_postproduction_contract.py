import copy
import unittest

from tools.audio_postproduction_contract import validate_audio_profile


def native_project():
    return {
        "metadata": {
            "audio_profile_id": "NATIVE_MULTIMODAL_NO_EXTERNAL_BGM",
            "audio_profile_contract": "configs/audio_postproduction_profiles_v1_20260821.json",
            "source_audio_policy": "PRESERVE_NATIVE_MULTIMODAL_AUDIO",
            "sound_design_contract": {
                "mode": "NATIVE_EMBEDDED",
                "required_layers": ["DIALOGUE", "FOLEY", "AMBIENCE", "SFX"],
                "source_track_ids": ["E99_NATIVE_AUDIO"],
                "external_bgm_allowed": False,
            },
        },
        "output": {"audioSampleRate": 48000},
        "masterAudioPolicy": {"sampleRateHz": 48000},
        "timeline": {"audioTracks": [{"id": "E99_NATIVE_AUDIO", "clips": []}]},
    }


class AudioPostproductionContractTests(unittest.TestCase):
    def test_native_profile_passes_without_bgm(self):
        self.assertEqual(validate_audio_profile(native_project()), [])

    def test_profile_is_mandatory(self):
        self.assertEqual(validate_audio_profile({}), ["AUDIO_PROFILE_NOT_DECLARED"])

    def test_native_profile_rejects_bgm_track_and_contract(self):
        project = native_project()
        project["timeline"]["audioTracks"].append({"id": "Audio.BGM", "clips": []})
        project["metadata"]["bgm_contract"] = {"source_type": "LIBRARY_FALLBACK"}
        failures = validate_audio_profile(project)
        self.assertIn("AUDIO_BGM_TRACK_FORBIDDEN_BY_PROFILE", failures)
        self.assertIn("BGM_CONTRACT_FORBIDDEN_BY_PROFILE", failures)

    def test_layered_profile_requires_bgm_track_and_contract(self):
        project = native_project()
        project["metadata"]["audio_profile_id"] = "LAYERED_POST_WITH_BGM"
        project["metadata"]["source_audio_policy"] = "NO_NATIVE_DIALOGUE_WITH_EVIDENCE"
        project["metadata"]["native_dialogue_absence_evidence"] = {"status": "PASS", "report": "qa/no_native_dialogue.json"}
        project["metadata"]["sound_design_contract"]["mode"] = "LAYERED_CUES"
        project["metadata"]["sound_design_contract"]["external_bgm_allowed"] = True
        failures = validate_audio_profile(project)
        self.assertIn("AUDIO_BGM_TRACK_REQUIRED_BY_PROFILE", failures)
        self.assertIn("BGM_CONTRACT_REQUIRED_BY_PROFILE", failures)

    def test_native_multimodal_selective_bgm_is_optional_but_motivated(self):
        project = native_project()
        project["metadata"]["audio_profile_id"] = "NATIVE_MULTIMODAL_SELECTIVE_BGM"
        project["metadata"]["sound_design_contract"]["external_bgm_allowed"] = True
        self.assertEqual(validate_audio_profile(project), [])
        project["metadata"]["bgm_contract"] = {
            "usage_mode": "SELECTIVE_NARRATIVE_CUES",
            "cues": [{
                "cue_id": "MU-1",
                "timeline_start": 3.0,
                "duration": 4.0,
                "narrative_function": "Reveal the threat under the dialogue.",
            }],
        }
        project["timeline"]["audioTracks"].append({"id": "Audio.BGM", "clips": []})
        self.assertEqual(validate_audio_profile(project), [])

    def test_selective_bgm_without_narrative_cue_fails(self):
        project = native_project()
        project["metadata"]["audio_profile_id"] = "NATIVE_MULTIMODAL_SELECTIVE_BGM"
        project["metadata"]["sound_design_contract"]["external_bgm_allowed"] = True
        project["metadata"]["bgm_contract"] = {"usage_mode": "SELECTIVE_NARRATIVE_CUES"}
        project["timeline"]["audioTracks"].append({"id": "Audio.BGM", "clips": []})
        self.assertIn("SELECTIVE_BGM_CUES_REQUIRED", validate_audio_profile(project))

    def test_44100_is_rejected_in_both_declared_locations(self):
        project = copy.deepcopy(native_project())
        project["output"]["audioSampleRate"] = 44100
        project["masterAudioPolicy"]["sampleRateHz"] = 44100
        failures = validate_audio_profile(project)
        self.assertIn("OUTPUT_AUDIO_SAMPLE_RATE_MUST_BE_48000", failures)
        self.assertIn("MASTER_AUDIO_SAMPLE_RATE_MUST_BE_48000", failures)

    def test_speaking_native_audio_must_come_from_same_video_source(self):
        project = native_project()
        project["timeline"]["videoTracks"] = [{"clips": [{
            "id": "V-1", "source": "/tmp/video-a.mp4", "metadata": {"source_id": "SRC-1", "multimodal_task_id": "TASK-A"}
        }]}]
        project["timeline"]["audioTracks"][0]["clips"] = [{
            "id": "A-1", "source": "/tmp/video-b.mp4",
            "metadata": {
                "source_id": "SRC-1", "expected_text": "台词",
                "dialogue_classification": "SPEAKING",
                "audio_origin": "EXTERNAL_TTS",
                "multimodal_task_id": "TASK-B",
            },
        }]
        failures = validate_audio_profile(project)
        self.assertIn("SPEAKING_AUDIO_NOT_NATIVE_MULTIMODAL:A-1", failures)
        self.assertIn("SPEAKING_AUDIO_VIDEO_SOURCE_MISMATCH:A-1", failures)
        self.assertIn("SPEAKING_AUDIO_VIDEO_TASK_ID_MISMATCH:A-1", failures)

    def test_native_audio_cannot_omit_dialogue_classification(self):
        project = native_project()
        project["timeline"]["audioTracks"][0]["clips"] = [{
            "id": "A-1", "source": "/tmp/video-a.mp4",
            "metadata": {"source_id": "SRC-1"},
        }]
        self.assertIn("DIALOGUE_CLASSIFICATION_REQUIRED:A-1", validate_audio_profile(project))

    def test_speaking_native_audio_same_source_and_task_passes(self):
        project = native_project()
        project["timeline"]["videoTracks"] = [{"clips": [{
            "id": "V-1", "source": "/tmp/video-a.mp4",
            "metadata": {"source_id": "SRC-1", "multimodal_task_id": "TASK-A"},
        }]}]
        project["timeline"]["audioTracks"][0]["clips"] = [{
            "id": "A-1", "source": "/tmp/video-a.mp4",
            "metadata": {
                "source_id": "SRC-1", "multimodal_task_id": "TASK-A",
                "expected_text": "台词", "dialogue_classification": "SPEAKING",
                "audio_origin": "NATIVE_MULTIMODAL_SOURCE",
            },
        }]
        self.assertEqual(validate_audio_profile(project), [])


if __name__ == "__main__":
    unittest.main()
