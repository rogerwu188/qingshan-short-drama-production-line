import unittest

from tools.h3_crossmodal_speaker_gate import evaluate


def _unit(*, model: str = "MiniMax-H3", speakers: tuple[str, ...] = ("陈迹",)) -> dict:
    ids = {"陈迹": "CHAR-CHENJI", "姚老头": "CHAR-YAO"}
    image_indices = {"陈迹": 3, "姚老头": 2}
    audio_indices = {"陈迹": 1, "姚老头": 2}
    labels = {"陈迹": "Chen Ji", "姚老头": "Elder Yao"}
    subjects = {"陈迹": "SUBJECT_2", "姚老头": "SUBJECT_1"}
    return {
        "unit_id": "E56-VU-002",
        "model": model,
        "ordered_prompt_specs": [
            {"dialogue": f"{speaker}：测试台词。"} for speaker in speakers
        ],
        "provider_entity_token_map": subjects,
        "speaker_voice_contract": {"bindings": [
            {
                "speaker": speaker,
                "character_id": ids[speaker],
                "audio_slot": f"@音频{audio_indices[speaker]}",
                "voice_reference_asset_id": f"VOICE-{speaker}",
                "visible_speaker": True,
                "lip_sync": True,
            }
            for speaker in speakers
        ]},
        "provider_scope_projection": {"reference_identity_bindings": [
            {
                "reference_index": image_indices[speaker],
                "entity_id": ids[speaker],
                "provider_entity_label": labels[speaker],
            }
            for speaker in speakers
        ]},
    }


class H3CrossmodalSpeakerGateTests(unittest.TestCase):
    def test_resolves_independent_ordinals_by_canonical_character_id(self):
        result = evaluate(_unit())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["bindings"][0]["image_slot"], "@Image3")
        self.assertEqual(result["bindings"][0]["subject_token"], "SUBJECT_2")
        self.assertEqual(result["bindings"][0]["speaker_slot"], "SPEAKER_1")
        self.assertEqual(result["bindings"][0]["audio_slot"], "@Audio1")

    def test_h3_speaker_change_fails_closed_even_when_each_mapping_exists(self):
        result = evaluate(_unit(speakers=("陈迹", "姚老头")))
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any(
            "H3_SPEAKER_CHANGE_REQUIRES_ATOMIC_VIDEO_UNIT" in failure
            for failure in result["failures"]
        ))

    def test_sd2_is_not_modified_by_h3_gate(self):
        result = evaluate(_unit(model="seedance-2.0-pro", speakers=("陈迹", "姚老头")))
        self.assertEqual(result["status"], "NOT_APPLICABLE")


if __name__ == "__main__":
    unittest.main()
