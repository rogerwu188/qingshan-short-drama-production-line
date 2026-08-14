import hashlib
import json

from tools.generation_first_pass_policy_gate import evaluate


def _write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path), hashlib.sha256(path.read_bytes()).hexdigest()


def test_requires_tier_and_complete_failure_disposition(tmp_path):
    policy_path, policy_sha = _write(tmp_path, "policy.json", {"status": "APPROVED_STANDING_POLICY"})
    memory_path, memory_sha = _write(tmp_path, "memory.json", {
        "status": "ACTIVE_PRE_SUBMIT_INPUT",
        "rules": [{"id": "PF-001"}, {"id": "PF-002"}],
    })
    config = {
        "generation_first_pass_policy_ref": policy_path,
        "generation_first_pass_policy_sha256": policy_sha,
        "generation_prompt_failure_memory_ref": memory_path,
        "generation_prompt_failure_memory_sha256": memory_sha,
        "tasks": [{
            "task_key": "T1",
            "tool_type": "video_generation",
            "visual_tier": "CORE",
            "minimum_score_100": 80,
            "prompt_failure_modes_applied": ["PF-001"],
            "prompt_failure_modes_not_applicable": ["PF-002"],
        }],
    }
    assert evaluate(config)["status"] == "PASS"
    config["tasks"][0]["minimum_score_100"] = 60
    assert evaluate(config)["status"] == "FAIL"


def test_missing_memory_rule_blocks(tmp_path):
    policy_path, policy_sha = _write(tmp_path, "policy.json", {"status": "APPROVED_STANDING_POLICY"})
    memory_path, memory_sha = _write(tmp_path, "memory.json", {
        "status": "ACTIVE_PRE_SUBMIT_INPUT",
        "rules": [{"id": "PF-001"}, {"id": "PF-002"}],
    })
    result = evaluate({
        "generation_first_pass_policy_ref": policy_path,
        "generation_first_pass_policy_sha256": policy_sha,
        "generation_prompt_failure_memory_ref": memory_path,
        "generation_prompt_failure_memory_sha256": memory_sha,
        "tasks": [{
            "task_key": "T1",
            "tool_type": "image_generation",
            "visual_tier": "NON_CORE",
            "minimum_score_100": 60,
            "prompt_failure_modes_applied": ["PF-001"],
            "prompt_failure_modes_not_applicable": [],
        }],
    })
    assert result["status"] == "FAIL"
    assert any(row["check"] == "failure_mode_disposition_complete" for row in result["failures"])

