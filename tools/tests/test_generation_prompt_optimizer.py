from tools.generation_prompt_optimizer import optimize_prompt, validate_batch


def task() -> dict:
    return {
        "task_key": "ACTION-ICE-SCREEN-RISE",
        "prompt_optimizer_required": True,
        "performance_tempo_contract": {
            "primary_action_complete_by_seconds": 1.8,
            "result_hold_seconds": 0.5,
        },
        "action_sequence_contract": {
            "entry_state_token": "ENTRY",
            "exit_state_token": "SCREEN_UP",
        },
        "action_prop_function_contract": {
            "required_function_class": "落地环境冰屏",
            "forbidden_function_classes": ["手持盾牌", "掌前护盾"],
            "required_prompt_terms": ["冰屏下缘与地板连续相接"],
            "forbidden_prompt_terms": ["小型透明冰盾", "四边都可见"],
        },
        "action_causality_contract": {
            "visible_phases": ["陈迹侧避并令冰屏从地面升起"],
            "maximum_phases_per_shot": 1,
            "required_prompt_terms": ["本镜不发生撞击"],
        },
        "action_scale_contract": {
            "required_relational_terms": ["高度约到成年男子肩部", "宽度足以隔开一人和火墙"],
            "frame_ratio_is_secondary_check": True,
        },
        "action_movement_lane_contract": {
            "lanes": [
                {"actor": "陈迹", "corridor": "画面左侧后撤走廊"},
                {"actor": "守宅人", "corridor": "画面中部前冲走廊"},
            ],
            "minimum_lateral_clearance": "一个成年男子肩宽",
            "required_prompt_terms": ["两人轮廓完全分离"],
            "forbidden_prompt_terms": ["贴身擦过", "从背后穿过"],
        },
        "action_terminal_support_contract": {
            "result_hold_requires_stable_support": True,
            "required_support_points": ["双脚落地"],
            "required_prompt_terms": ["双脚完整踩住木地板"],
            "forbidden_prompt_terms": ["单脚悬空保持到结尾"],
        },
        "performance_spec": {"motion_beats": [{"subject": "陈迹", "action": "升起冰屏"}]},
    }


def valid_prompt() -> str:
    return (
        "陈迹侧避，冰屏下缘与地板连续相接，高度约到成年男子肩部，"
        "宽度足以隔开一人和火墙。本镜不发生撞击。"
        "两人轮廓完全分离。"
        "双脚完整踩住木地板。"
    )


def test_environment_screen_contract_passes_and_compiles_rules():
    row = task()
    prompt, receipt = optimize_prompt(row, valid_prompt())
    row["prompt_optimizer_receipt"] = receipt
    report = validate_batch([row], {row["task_key"]: prompt})
    assert report["status"] == "PASS"
    assert {"PF-013", "PF-014", "PF-015", "PF-016", "PF-017"}.issubset(receipt["applied_failure_memory_rules"])


def test_handheld_tablet_rewrite_fails_closed():
    row = task()
    bad = valid_prompt() + " 小型透明冰盾，四边都可见。"
    prompt, receipt = optimize_prompt(row, bad)
    row["prompt_optimizer_receipt"] = receipt
    report = validate_batch([row], {row["task_key"]: prompt})
    codes = {failure["code"] for failure in report["failures"]}
    assert report["status"] == "FAIL"
    assert "PROP_FUNCTION_CLASS_REWRITTEN" in codes


def test_multi_phase_action_is_rejected_before_generation():
    row = task()
    row["action_causality_contract"]["visible_phases"] = ["侧避", "撞击"]
    prompt, receipt = optimize_prompt(row, valid_prompt())
    row["prompt_optimizer_receipt"] = receipt
    report = validate_batch([row], {row["task_key"]: prompt})
    assert "ACTION_PHASE_BUDGET_EXCEEDED" in {failure["code"] for failure in report["failures"]}


def test_authored_body_overlap_fails_closed():
    row = task()
    prompt, receipt = optimize_prompt(row, valid_prompt() + "守宅人从背后穿过陈迹。")
    row["prompt_optimizer_receipt"] = receipt
    report = validate_batch([row], {row["task_key"]: prompt})
    assert "MOVEMENT_LANE_OVERLAP_AUTHORED" in {failure["code"] for failure in report["failures"]}


def test_suspended_terminal_pose_fails_closed():
    row = task()
    prompt, receipt = optimize_prompt(row, valid_prompt() + "单脚悬空保持到结尾。")
    row["prompt_optimizer_receipt"] = receipt
    report = validate_batch([row], {row["task_key"]: prompt})
    assert "SUSPENDED_TERMINAL_POSE_AUTHORED" in {failure["code"] for failure in report["failures"]}
