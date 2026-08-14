from tools.action_causal_chain_compiler import compile_chain


def beat(key, entry, exit_state, phase):
    return {
        "task_key": key,
        "entry_state_token": entry,
        "exit_state_token": exit_state,
        "visible_phases": [phase],
        "real_time_1x": True,
    }


def test_serial_chain_preserves_parallelism_for_unrelated_work():
    result = compile_chain({"chain_id": "fight", "beats": [beat("a", "s0", "s1", "rise"), beat("b", "s1", "s2", "impact")]})
    assert result["status"] == "PASS"
    assert result["tasks"][1]["depends_on_task"] == "a"
    assert result["global_scheduling_policy"]["unrelated_generation_and_qa"] == "PARALLEL"


def test_multiple_causal_phases_fail_closed():
    row = beat("a", "s0", "s1", "rise")
    row["visible_phases"] = ["rise", "impact"]
    result = compile_chain({"chain_id": "fight", "beats": [row]})
    assert result["status"] == "FAIL"
    assert result["failures"][0]["code"] == "EXACTLY_ONE_VISIBLE_PHASE_REQUIRED"


def test_broken_tail_state_fails_closed():
    result = compile_chain({"chain_id": "fight", "beats": [beat("a", "s0", "s1", "rise"), beat("b", "wrong", "s2", "impact")]})
    assert result["status"] == "FAIL"
    assert "ENTRY_DOES_NOT_MATCH_PREDECESSOR_EXIT" in {row["code"] for row in result["failures"]}


def test_compiler_exposes_optimizer_contracts():
    row = beat("a", "s0", "s1", "rise")
    row["prop_function"] = {"required_function_class": "落地环境冰屏"}
    row["scale_contract"] = {"required_relational_terms": ["两倍肩宽"], "frame_ratio_is_secondary_check": True}
    row["movement_lane_contract"] = {
        "lanes": [{"actor": "甲", "corridor": "左侧"}, {"actor": "乙", "corridor": "中部"}],
        "minimum_lateral_clearance": "一肩宽",
    }
    row["terminal_support_contract"] = {
        "result_hold_requires_stable_support": True,
        "required_support_points": ["双脚落地"],
    }
    task = compile_chain({"chain_id": "fight", "beats": [row]})["tasks"][0]
    assert task["action_prop_function_contract"]["required_function_class"] == "落地环境冰屏"
    assert task["action_causality_contract"]["maximum_phases_per_shot"] == 1
    assert task["action_sequence_contract"]["entry_state_token"] == "s0"
    assert task["performance_tempo_contract"]["real_time_1x"] is True
    assert task["action_scale_contract"]["required_relational_terms"] == ["两倍肩宽"]
    assert len(task["action_movement_lane_contract"]["lanes"]) == 2
    assert task["action_terminal_support_contract"]["required_support_points"] == ["双脚落地"]


def test_contact_transition_rejects_precontact_reorientation():
    row = beat("a", "s0", "s1", "impact")
    row["contact_transition_contract"] = {
        "entry_pose_preserved_until_first_contact": False,
        "pre_contact_reorientation_allowed": True,
        "primary_contact": "right shoulder",
        "maximum_body_state_transitions": 2,
    }
    result = compile_chain({"chain_id": "fight", "beats": [row]})
    codes = {item["code"] for item in result["failures"]}
    assert "ENTRY_POSE_MUST_PERSIST_TO_FIRST_CONTACT" in codes
    assert "PRE_CONTACT_REORIENTATION_MUST_BE_FORBIDDEN" in codes
    assert "CONTACT_SHOT_MUST_HAVE_ONE_BODY_STATE_TRANSITION" in codes


def test_contact_transition_compiles_atomicity_gate():
    row = beat("a", "s0", "s1", "impact")
    row["contact_transition_contract"] = {
        "entry_pose_preserved_until_first_contact": True,
        "pre_contact_reorientation_allowed": False,
        "primary_contact": "both palms on one wall plane",
        "maximum_body_state_transitions": 1,
    }
    result = compile_chain({"chain_id": "fight", "beats": [row]})
    assert result["status"] == "PASS"
    task = result["tasks"][0]
    assert "ENTRY_POSE_TO_CONTACT_ATOMICITY" in task["pre_generation_gates"]
    assert task["action_contact_transition_contract"]["primary_contact"] == "both palms on one wall plane"
