"""The paid-boundary / finalizer re-render keeps an English episode's dialogue language
(Twelve Gazes E01-VU-011, 2026-10-22: <d>[English] became <d>[Chinese] at the submit entry)."""
from tools.submit_giggle_video_manifest_v2 import provider_prompt_unit


def _task(**extra):
    return {"task_key": "E01-VU-011", "model": "MiniMax-H3", "machine_contract": {}, **extra}


def test_english_task_keeps_its_dialogue_language():
    assert provider_prompt_unit(_task(dialogue_language="en")).get("dialogue_language") == "en"


def test_chinese_task_is_unchanged():
    assert "dialogue_language" not in provider_prompt_unit(_task())
