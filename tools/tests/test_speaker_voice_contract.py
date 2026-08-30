import unittest

from tools.speaker_voice_contract import (
    attach_speaker_voice_contract,
    compile_speaker_voice_contract,
    task_voice_transport,
    validate_speaker_voice_contract,
)


def unit(*dialogues):
    return {
        "unit_id": "E99-VU-VOICE",
        "ordered_prompt_specs": [
            {
                "cast": [{"character": "陈迹"}, {"character": "白鲤"}],
                "dialogue": raw,
            }
            for raw in dialogues
        ],
    }


def voice_bible(*names):
    return {"characters": [
        {
            "character": name,
            "entity_id": f"entity-{index}",
            "status": "LOCKED_PRODUCTION_READY",
            "remote_asset_id": f"voice-{index}",
            "remote_url": f"https://example.invalid/voice-{index}.wav",
        }
        for index, name in enumerate(names, start=1)
    ]}


class SpeakerVoiceContractTest(unittest.TestCase):
    def test_two_speakers_receive_distinct_canonical_audio_slots(self):
        payload = unit("陈迹：你来了。", "白鲤：我来迟了。")
        contract = attach_speaker_voice_contract(payload, voice_bible("陈迹", "白鲤"))

        self.assertEqual(contract["status"], "PASS")
        self.assertEqual([row["speaker"] for row in contract["bindings"]], ["陈迹", "白鲤"])
        self.assertEqual([row["audio_slot"] for row in contract["bindings"]], ["@音频1", "@音频2"])
        self.assertNotEqual(
            contract["bindings"][0]["voice_reference_asset_id"],
            contract["bindings"][1]["voice_reference_asset_id"],
        )
        self.assertEqual(validate_speaker_voice_contract(payload)["status"], "PASS")

    def test_dialogue_fails_closed_without_contract(self):
        report = validate_speaker_voice_contract(unit("陈迹：停。"))
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("SPEAKER_VOICE_CONTRACT_SCHEMA_MISSING_OR_STALE", report["failures"])

    def test_unregistered_speaker_cannot_enter_paid_generation(self):
        contract = compile_speaker_voice_contract(unit("未登记路人：借过。"))
        self.assertEqual(contract["status"], "FAIL")
        self.assertIn("SPEAKER_CANONICAL_VOICE_NOT_REGISTERED:未登记路人", contract["failures"])

    def test_transport_forwards_reference_for_every_dialogue_line(self):
        payload = unit("陈迹：第一句。", "陈迹：第二句。")
        attach_speaker_voice_contract(payload, voice_bible("陈迹"))
        rows = [
            {"dia_id": "D1", "speaker": "陈迹", "spoken_text": "第一句。"},
            {"dia_id": "D2", "speaker": "陈迹", "spoken_text": "第二句。"},
        ]
        transport = task_voice_transport(payload, rows)

        self.assertEqual(len(transport["reference_audio_asset_ids"]), 1)
        self.assertEqual([row["dia_id"] for row in transport["dialogue_audio_assets"]], ["D1", "D2"])
        self.assertTrue(all(row["audio_slot"] == "@音频1" for row in transport["dialogue_audio_assets"]))
        self.assertTrue(all(row["purpose"] == "LOCKED_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT" for row in transport["dialogue_audio_assets"]))

    def test_h3_requires_public_voice_url_and_uses_url_transport(self):
        payload = unit("陈迹：停。")
        payload["model"] = "MiniMax-H3"
        contract = attach_speaker_voice_contract(payload, voice_bible("陈迹"))
        transport = task_voice_transport(
            payload, [{"dia_id": "D1", "speaker": "陈迹", "spoken_text": "停。"}]
        )
        self.assertEqual(contract["status"], "PASS")
        self.assertEqual(transport["reference_audio_asset_ids"], [])
        self.assertEqual(len(transport["reference_audio_urls"]), 1)
        self.assertTrue(transport["reference_audio_urls"][0].startswith("https://"))


if __name__ == "__main__":
    unittest.main()
