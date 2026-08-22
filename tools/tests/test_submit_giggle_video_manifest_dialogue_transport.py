import unittest

from tools.submit_giggle_video_manifest_v2 import validate_source_caption_safe_dialogue


class SourceCaptionSafeDialogueTest(unittest.TestCase):
    def test_rejects_literal_dialogue_with_style_reference_only(self):
        task = {
            "task_key": "E99-U01-R1",
            "native_dialogue_required": True,
            "source_subtitle_policy": "FORBID",
            "dialogue_lines": ["别动。"],
            "reference_audio_asset_ids": ["voice-style"],
        }
        with self.assertRaisesRegex(ValueError, "EXACT_LINE_AUDIO_REFERENCE"):
            validate_source_caption_safe_dialogue(task, '角色说准确台词“别动。”')

    def test_rejects_literal_leak_even_with_exact_audio(self):
        task = {
            "task_key": "E99-U01-R2",
            "native_dialogue_required": True,
            "source_subtitle_policy": "FORBID",
            "dialogue_transport": "EXACT_LINE_AUDIO_REFERENCE",
            "dialogue_lines": ["别动。"],
            "exact_dialogue_audio_urls": ["https://assets.giggle.pro/public/exact-line.mp3"],
        }
        with self.assertRaisesRegex(ValueError, "literal dialogue leaked"):
            validate_source_caption_safe_dialogue(task, '音轨说“别 动”且画面无字幕')

    def test_accepts_audio_only_transport_without_literal_copy(self):
        task = {
            "task_key": "E99-U01-R2",
            "native_dialogue_required": True,
            "source_subtitle_policy": "FORBID",
            "dialogue_transport": "EXACT_LINE_AUDIO_REFERENCE",
            "dialogue_lines": ["别动。"],
            "exact_dialogue_audio_urls": ["https://assets.giggle.pro/public/exact-line.mp3"],
        }
        validate_source_caption_safe_dialogue(task, "角色按音频1同步口型，紧张耳语；画面不出现任何转写文字")

    def test_accepts_same_task_native_text_dialogue_with_canonical_copy(self):
        task = {
            "task_key": "E99-U01-R3",
            "native_dialogue_required": True,
            "source_subtitle_policy": "FORBID",
            "dialogue_transport": "MODEL_NATIVE_TEXT_DIALOGUE",
            "model_native_text_dialogue": True,
            "dialogue_lines": ["别动。"],
        }
        validate_source_caption_safe_dialogue(
            task,
            "角色自然说：‘别动。’ 同一生成任务保留原生声音与口型，画面禁止字幕。",
        )


if __name__ == "__main__":
    unittest.main()
