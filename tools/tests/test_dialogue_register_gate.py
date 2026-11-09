"""DIALOGUE_REGISTER_V1 — the reported E15 lines fail, and a rewritten line passes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import dialogue_register_gate as gate  # noqa: E402

SOURCE = "血竹林中的火泉要熄灭了，正是对付那种灵性之物的好时机，得提前安排。你是谁，为何针对我等？"


def _line(shot, speaker, text):
    return {"shot_id": shot, "speaker": speaker, "text": text}


def test_verbatim_run_detected_at_threshold():
    report = gate.analyse([_line("S01", "甲", "你是谁，为何针对我等？")], SOURCE)
    assert report["status"] == "FAIL"
    assert "DIALOGUE_SOURCE_VERBATIM:1" in report["failures"]
    assert report["verbatim"][0]["run_chars"] >= gate.VERBATIM_MIN_RUN


def test_short_shared_run_is_not_verbatim():
    report = gate.analyse([_line("S02", "甲", "刀先收着，别出声。")], SOURCE)
    assert report["verbatim"] == []


def test_written_register_markers_block():
    report = gate.analyse([_line("S03", "傅恩涛", "正是对付那种灵性之物的好时机。")], "")
    assert any(row["code"] == "DIALOGUE_WRITTEN_REGISTER" for row in report["written_register"])


def test_judged_comparison_is_written_register():
    report = gate.analyse([_line("S04", "秦铭", "我的力气比他大，速度比他慢。")], "")
    assert "JUDGED_COMPARISON" in report["written_register"][0]["markers"]


def test_spoken_line_passes_clean():
    lines = [_line(f"S{i:02d}", "秦铭", "风偏左。") for i in range(1, 4)]
    report = gate.analyse(lines, SOURCE)
    assert report["status"] == "PASS", report


def test_one_voice_detected_between_clone_speakers():
    a = [_line(f"A{i}", "甲", "刀先收着，别出声。") for i in range(3)]
    b = [_line(f"B{i}", "乙", "刀先收着，别出声！") for i in range(3)]
    report = gate.analyse(a + b, "")
    assert report["one_voice"], report
    assert report["failures"][0].startswith("DIALOGUE_ONE_VOICE")


def test_distinct_voices_pass():
    a = [_line(f"A{i}", "秦铭", "风偏左。") for i in range(3)]
    b = [_line(f"B{i}", "傅恩涛", "你们几个把他围起来，今晚谁都别想走，我要活的。") for i in range(3)]
    report = gate.analyse(a + b, "")
    assert report["one_voice"] == []


def test_fingerprint_max_chars_and_banned_word():
    lines = [_line("S01", "秦铭", "今天晚上谁都别想从这里走出去")]
    report = gate.analyse(lines, "", fingerprints={"秦铭": {"max_chars": 10, "banned_words": ["都"]}})
    codes = {row["code"] for row in report["fingerprint_drift"]}
    assert codes == {"FINGERPRINT_MAX_CHARS", "FINGERPRINT_BANNED_WORD"}


def test_policy_active_from_episode_and_contract_declaration():
    policy = {"enabled_from_episode": "E16"}
    assert gate.policy_active({}, episode="E16", policy=policy) is True
    assert gate.policy_active({}, episode="E15", policy=policy) is False
    assert gate.policy_active({"dialogue_register_policy": "DIALOGUE_REGISTER_V1"}, episode="E15",
                              policy=policy) is True


def test_contract_lines_split_into_per_sentence_rows():
    contract = {"shots": [{"shot_id": "E15-S01-02",
                           "prompt_spec": {"dialogue": "秦铭：缴来的弓，软也一样用。四杆都带上。"}}]}
    rows = gate.lines_from_contract(contract)
    assert [row["speaker"] for row in rows] == ["秦铭", "秦铭"]
    assert rows[0]["text"].endswith("。")
