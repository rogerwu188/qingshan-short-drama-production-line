from tools.shot_duration_policy import (
    POLICY_VERSION,
    action_cue_count,
    plan_dialogue_duration,
    validate_duration_task,
)


def test_english_action_cues_require_whole_words():
    assert action_cue_count("medical hall threshold") == 0
    assert action_cue_count("hold at the threshold, then react") == 2


def test_story_driven_duration_varies_with_performance_need():
    short = plan_dialogue_duration("开。", "slow", "授权实际开棺")
    long = plan_dialogue_duration("活人是自己爬出去的。", "medium", "合成证据并完成翻转")
    assert 4 <= short["duration_seconds"] <= 15
    assert 4 <= long["duration_seconds"] <= 15
    assert short["duration_seconds"] != 4 or short["action_seconds"] > 1.0
    assert long["duration_seconds"] > 4


def test_multi_action_performance_uses_estimated_action_budget_without_floor():
    plan = plan_dialogue_duration(
        "东西，我带走了！",
        "fast",
        "翻脸动手",
        performance_context="亮出短刃，逼近，撞翻灯笼，扑向门口，逃入窄巷，对手追出",
    )
    assert 4 <= plan["duration_seconds"] <= 15
    assert plan["context_actions_detected"] >= 6
    assert plan["performance_floor_seconds"] == 4


def test_script_locked_performance_context_does_not_create_eight_second_floor():
    plan = plan_dialogue_duration(
        "今夜先守住第一个",
        "medium",
        "playable evidence response",
        performance_context="高位俯拍，人物把三件证物依次放上案台",
    )
    assert plan["duration_seconds"] < 8
    assert plan["performance_floor_seconds"] == 4


def test_missing_duration_plan_is_blocked():
    problems = validate_duration_task({"source_id": "SHOT-1", "duration": 4})
    assert "FAIL_SHOT_DURATION_PLAN_MISSING:SHOT-1" in problems


def test_duration_plan_must_match_task_duration():
    task = {
        "source_id": "SHOT-2",
        "duration": 4,
        "duration_plan": {
            "policy": POLICY_VERSION,
            "duration_seconds": 5,
            "rationale": "story action",
            "edit_policy": "trim on action",
        },
    }
    assert "FAIL_SHOT_DURATION_PLAN_MISMATCH:SHOT-2" in validate_duration_task(task)
