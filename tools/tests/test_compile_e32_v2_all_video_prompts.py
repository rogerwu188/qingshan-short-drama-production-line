import json
import unittest
from pathlib import Path

from tools.compile_e32_v2_all_video_prompts import (
    DIALOGUE_PATH,
    ROOT,
    VOICE_REGISTRY_PATH,
    validate_dialogue_audio_rows,
)


class E32DialogueAudioPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dialogue = json.loads(DIALOGUE_PATH.read_text(encoding="utf-8"))
        registry = json.loads(VOICE_REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.registry = {row["entity_id"]: row for row in registry["major_roles"]}
        cls.chenji = next(row for row in dialogue["rows"] if row["speaker_id"] == "chenji")
        cls.exact = next(
            row for row in dialogue["rows"]
            if row["audio_mode"] == "EXACT_DIALOGUE_AUDIO_REFERENCE"
        )

    def test_locked_native_voice_reference_is_allowed_with_exact_text(self):
        blocked, native_style = validate_dialogue_audio_rows([self.chenji], self.registry)
        self.assertEqual([], blocked)
        self.assertEqual([self.chenji["dia_id"]], native_style)

    def test_unregistered_native_voice_asset_is_blocked(self):
        row = {**self.chenji, "remote_asset_id": "wrong-asset"}
        blocked, native_style = validate_dialogue_audio_rows([row], self.registry)
        self.assertEqual([row["dia_id"]], blocked)
        self.assertEqual([], native_style)

    def test_exact_line_audio_remains_allowed_for_other_roles(self):
        self.assertTrue((ROOT / Path(self.exact["path"])).is_file())
        blocked, native_style = validate_dialogue_audio_rows([self.exact], self.registry)
        self.assertEqual([], blocked)
        self.assertEqual([], native_style)


if __name__ == "__main__":
    unittest.main()
