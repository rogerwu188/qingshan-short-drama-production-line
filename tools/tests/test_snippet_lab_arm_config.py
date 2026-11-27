"""snippet_lab: per-arm LAB.json overrides and the device-parity input warnings (BURN_BISECT2, 2026-11-26)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

LAB = Path(__file__).resolve().parents[1] / "lab" / "snippet_lab.py"
spec = importlib.util.spec_from_file_location("snippet_lab_under_test", LAB)
sl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sl)


def _lab(tmp_path: Path) -> Path:
    (tmp_path / "LAB.json").write_text(json.dumps({
        "duration": 4,
        "characters": {"CHAR-A": {"face": "a.png", "voice": "", "wardrobe_en": "red robe"},
                       "CHAR-B": {"face": "b.png", "voice": ""}},
        "first_frames": {"S01-05": "frame.png", "S01-03": "frame.png"}}))
    return tmp_path


def test_arm_without_override_reads_lab_json(tmp_path):
    lab = _lab(tmp_path)
    (lab / "base").mkdir()
    assert sl.arm_config(lab, lab / "base")["characters"]["CHAR-A"]["face"] == "a.png"


def test_arm_override_deep_merges(tmp_path):
    lab = _lab(tmp_path)
    arm = lab / "clean"
    arm.mkdir()
    (arm / "LAB.json").write_text(json.dumps({"duration": 6, "first_frames": {"S01-05": "clean.png"},
                                              "characters": {"CHAR-A": {"voice": "a.wav"}}}))
    cfg = sl.arm_config(lab, arm)
    assert cfg["duration"] == 6
    assert cfg["first_frames"] == {"S01-05": "clean.png", "S01-03": "frame.png"}
    assert cfg["characters"]["CHAR-A"] == {"face": "a.png", "voice": "a.wav", "wardrobe_en": "red robe"}
    assert cfg["characters"]["CHAR-B"]["face"] == "b.png"


def test_warnings_flag_inputs_a_device_never_sends():
    row = {"speaker": "CHAR-A"}
    cfg = {"characters": {"CHAR-A": {"voice": ""}}, "generate_audio": False}
    warnings = sl.input_warnings(row, cfg)
    assert any("no voice anchor" in w for w in warnings)
    assert any("generate_audio" in w for w in warnings)


def test_device_like_inputs_have_no_warning():
    row = {"speaker": "CHAR-A"}
    cfg = {"characters": {"CHAR-A": {"voice": "a.wav"}}}
    assert sl.input_warnings(row, cfg) == []
