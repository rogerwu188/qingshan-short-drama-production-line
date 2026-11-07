"""combat_execution (Roger 2026-11-07): pose-keypoint stillness on COMBAT units only."""
from __future__ import annotations

import builtins
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "tools", ROOT / "lines" / "nalu" / "runtime" / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import combat_execution_check as cec  # noqa: E402
import post_generation_qa_scope_gate as scope  # noqa: E402

#: measured with RTMO-s on the real E15 clips (2026-11-07); kept here so a threshold change must face them
CALIBRATION = {
    "E15-VU-020 (one spark, then side-by-side stand)": (1.38, "FAIL"),
    "E15 original 1:20-1:25 side-by-side pose": (1.50, "FAIL"),
    "E15-VU-014 (spear knocked aside)": (0.88, "PASS"),
    "E15-VU-019 reroll (dodge, sabre into snow)": (0.75, "PASS"),
    "E15 original 1:43-1:46": (0.75, "PASS"),
    "E15-VU-021 (cleaver on bracer, retreat)": (0.25, "PASS"),
    "E15-VU-027 reroll (lunge, grapple, woods)": (0.12, "PASS"),
}


def person(x, y, h=400.0):
    k = np.stack([np.array([x + i * 3.0, y + i * h / 17]) for i in range(17)])
    return {"k": k, "s": np.ones(17), "h": h, "cx": x}


def test_calibration_table_is_separated_by_the_threshold():
    for name, (still, expected) in CALIBRATION.items():
        assert cec.verdict({"longest_still_seconds": still})["status"] == expected, name


def test_fighters_standing_still_for_more_than_a_second_fail():
    frames = [[person(100, 100), person(400, 100)] for _ in range(16)]           # 2 s at 8 fps, no motion
    result = cec.verdict(cec.summarise(frames))
    assert result["status"] == "FAIL" and result["reasons"] == ["COMBAT_TABLEAU_STILL"]
    assert result["on_fail"] == "REDESIGN_UNIT_NOT_REROLL"


def test_an_exchange_that_keeps_moving_passes():
    frames = [[person(100 + 12 * i, 100), person(400 - 12 * i, 100 + 4 * i)] for i in range(16)]
    assert cec.verdict(cec.summarise(frames))["status"] == "PASS"


def test_missing_pose_backend_is_never_a_pass(monkeypatch, tmp_path):
    real_import = builtins.__import__

    def fake(name, *args, **kwargs):
        if name == "rtmlib":
            raise ModuleNotFoundError("No module named 'rtmlib'", name="rtmlib")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake)
    result = cec.measure(tmp_path / "x.mp4")
    assert result["status"] == "NOT_MEASURED"


def test_scope_gate_admits_only_the_narrow_combat_check():
    assert scope.evaluate(["freeze", "combat_execution"])["status"] == "PASS"
    assert scope.evaluate(["motion_energy"])["status"] == "FAIL"
    assert scope.evaluate(["optical_flow"])["status"] == "FAIL"


def test_runner_routes_a_tableau_to_redesign_and_only_measures_combat_units():
    import post_generation_qa_runner as runner
    assert "UNIT_REDESIGN_REQUIRED" in runner.required_prompt_change_for("combat_execution:COMBAT_TABLEAU_STILL:1.4s")
    shots = {"a": {"prompt_spec": {"action": {"action_kind": "COMBAT"}}},
             "b": {"prompt_spec": {"action": {"action_kind": ""}}}}
    assert runner.is_combat_unit(["b", "a"], shots) and not runner.is_combat_unit(["b"], shots)
