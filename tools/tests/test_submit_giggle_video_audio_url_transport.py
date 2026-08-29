import tempfile
import unittest
from pathlib import Path

from tools.submit_giggle_video_manifest_v2 import (
    task_fingerprint,
    validate_source_caption_safe_dialogue,
)


class GiggleVideoAudioUrlTransportTests(unittest.TestCase):
    def test_exact_dialogue_requires_ordered_public_urls(self):
        task = {
            "task_key": "E40-U01-V2",
            "native_dialogue_required": True,
            "source_subtitle_policy": "FORBID",
            "dialogue_transport": "EXACT_LINE_AUDIO_REFERENCE",
            "dialogue_lines": ["别动。"],
            "exact_dialogue_audio_urls": ["https://assets.giggle.pro/public/a.mp3"],
        }
        validate_source_caption_safe_dialogue(task, "自然说话，不显示字幕")

    def test_provider_asset_id_without_url_is_admitted(self):
        task = {
            "task_key": "E40-U01-V2",
            "native_dialogue_required": True,
            "source_subtitle_policy": "FORBID",
            "dialogue_transport": "EXACT_LINE_AUDIO_REFERENCE",
            "dialogue_lines": ["别动。"],
            "exact_dialogue_audio_asset_ids": ["legacy-id"],
        }
        validate_source_caption_safe_dialogue(task, "自然说话，不显示字幕")

    def test_asset_id_count_must_cover_every_dialogue_line(self):
        task = {
            "task_key": "E40-U01-V2",
            "native_dialogue_required": True,
            "source_subtitle_policy": "FORBID",
            "dialogue_transport": "EXACT_LINE_AUDIO_REFERENCE",
            "dialogue_lines": ["别动。", "退后。"],
            "exact_dialogue_audio_asset_ids": ["provider-id-1"],
        }
        with self.assertRaisesRegex(ValueError, "per dialogue line"):
            validate_source_caption_safe_dialogue(task, "自然说话，不显示字幕")

    def test_audio_url_changes_submission_fingerprint(self):
        task = {"task_key": "E40-U01-V2", "exact_dialogue_audio_urls": ["https://assets/a.mp3"]}
        first = task_fingerprint(task)
        task["exact_dialogue_audio_urls"] = ["https://assets/b.mp3"]
        self.assertNotEqual(first, task_fingerprint(task))


if __name__ == "__main__":
    unittest.main()
