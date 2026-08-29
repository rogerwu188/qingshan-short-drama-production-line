#!/usr/bin/env python3
"""Register the S10-06 A1 cast-duplication failure and build one A2 retry."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
QA = ROOT / "qa/e44_v5_preproduction_20260828"
SOURCE = PROD / "E44_V5_MIDDLE_ANCHOR_SUPPLEMENT_PRECHECK_V1.json"
HARVEST = QA / "E44_V5_MIDDLE_ANCHOR_SUPPLEMENT_HARVEST_STATUS_V1.json"
PROMPT_DIR = PROD / "keyframe_prompts_retry_a2_v1"
FAILURE = QA / "E44_S10_06_MIDDLE_ANCHOR_A1_CONTENT_FAILURE_V1.json"
OUT = PROD / "E44_V5_S10_06_MIDDLE_ANCHOR_A2_PRECHECK_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    harvest = json.loads(HARVEST.read_text(encoding="utf-8"))
    original = next(task for task in source["tasks"] if task["task_key"] == "E44-S10-06-KF-V1")
    result = next(row for row in harvest["results"] if row["task_key"] == "E44-S10-06-KF-V1")
    candidate = Path(result["output_path"])
    original_prompt = ROOT / original["prompt_file"]
    if result.get("remote_status") != "completed" or sha(candidate) != result.get("sha256"):
        raise ValueError("S10-06 A1 completed-media binding is invalid")
    if sha(original_prompt) != original.get("prompt_sha256"):
        raise ValueError("S10-06 A1 prompt SHA mismatch")

    failure = {
        "schema": "qingshan.image_content_failure_memory.v1",
        "episode": "E44",
        "version": "v5",
        "shot_id": "E44-S10-06",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "RECORDED_CONTENT_FAILURE_RETRY_ALLOWED",
        "failure_classification": "PROVIDER_HEALTHY_CONTENT_FAILURE_EXTRA_DUPLICATED_CAST",
        "provider_healthy": True,
        "media_produced": True,
        "prior_task_key": result["task_key"],
        "prior_task_id": result["task_id"],
        "prior_prompt": rel(original_prompt),
        "prior_prompt_sha256": sha(original_prompt),
        "candidate": rel(candidate),
        "candidate_sha256": sha(candidate),
        "reason": (
            "The frame contains Baili, Zhu Lingyun, the heir and the little monk, but also renders "
            "three additional black-clothed people on the wall. This violates the exact four-person "
            "visible-cast contract and breaks identity/plot continuity."
        ),
        "root_cause": (
            "The static keyframe prompt simultaneously placed all four canonical people at the wall root "
            "and described three people actively descending, allowing the model to duplicate the three arrivals."
        ),
        "do_not_repeat": [
            "Do not reuse the A1 prompt SHA.",
            "Do not show the three arrivals both on the wall and on the ground in one static frame.",
            "Do not add guards, soldiers, servants, passersby, intruders, silhouettes or background people.",
            "Do not interpret the source action as seven total people; the arriving three are Zhu Lingyun, the heir and the little monk themselves.",
        ],
        "content_attempt_consumed": 1,
        "next_content_attempt": 2,
        "maximum_content_attempts": 10,
    }
    write(FAILURE, failure)

    text = original_prompt.read_text(encoding="utf-8")
    census = (
        "【A2全画面人数硬锁】本张静帧采用动作完成后的结果态。全画面从前景到最远背景严格且只能出现四个人："
        "白鲤一人，以及刚刚落地并已站稳的朱灵韵、世子、小和尚三人。朱灵韵、世子、小和尚就是源动作中从墙头下来的三个人，"
        "不得在墙头、屋顶、门洞、远景或阴影里再次复制他们。墙头与屋顶必须完全空；严禁守卫、黑衣人、士兵、仆从、路人、"
        "闯入者、人影、剪影或第五个人。画面中人物总数必须精确等于4。\n"
    )
    marker = "9:16竖版构图。"
    if marker not in text:
        raise ValueError("cannot place A2 cast census contract")
    text = text.replace(marker, census + "\n" + marker, 1)
    old_action = (
        "源剧本本镜动作必须准确承载：墙头上又下来三个人。。动作起点/完成态："
        "三人先后自墙脊持续下落至地面，落点各差半步。"
    )
    new_action = (
        "源剧本本镜动作必须准确承载：墙头上又下来三个人。。本静帧只呈现该动作完成后的唯一结果态："
        "朱灵韵、世子、小和尚三人已经从墙头落地并各差半步站稳；墙头上不再有人。白鲤仍在原位。"
        "不得把同一组三人复制为墙上三人加地面三人。"
    )
    if old_action not in text:
        raise ValueError("cannot rewrite A2 source-action rendering")
    text = text.replace(old_action, new_action, 1)
    text += (
        "\n【A2防复犯收束】最终静帧人物清点必须为4/4：白鲤、朱灵韵、世子、小和尚各且仅一人；"
        "背景墙头、屋顶、门洞和庭院远景无人。若出现任何额外人物、重复身份或黑衣剪影即为失败。\n"
    )
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    prompt_path = PROMPT_DIR / "E44-S10-06-KF-V1-A2-CAST-EXACT.txt"
    prompt_path.write_text(text, encoding="utf-8")
    if sha(prompt_path) == sha(original_prompt):
        raise ValueError("A2 prompt is not materially changed")

    task = copy.deepcopy(original)
    task.update({
        "task_key": "E44-S10-06-KF-V1-A2-CAST-EXACT",
        "prompt_file": rel(prompt_path),
        "prompt_sha256": sha(prompt_path),
        "status": "PRECHECK_ONLY",
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "retry_attempt": 2,
        "creative_attempt_ordinal": 2,
        "attempt_index": 2,
        "paid_attempt": 2,
        "prior_failure_classifications": ["PROVIDER_HEALTHY_CONTENT_FAILURE_EXTRA_DUPLICATED_CAST"],
        "prior_prompt_sha256": [sha(original_prompt)],
        "failure_memory": {"ref": rel(FAILURE), "sha256": sha(FAILURE)},
        "material_change_from_prior_attempt": (
            "Changed the static moment from simultaneous four-person blocking plus active descent to the settled "
            "post-landing state, added an exact four-person census, emptied every background plane, and explicitly "
            "identified the three arrivals as Zhu Lingyun, the heir and the little monk rather than additional people."
        ),
        "do_not_repeat": failure["do_not_repeat"],
        "same_creative_prompt_intentional": False,
        "no_further_automatic_retry": False,
    })
    task["prompt_contract"] = copy.deepcopy(task["prompt_contract"])
    task["prompt_contract"]["retry_attempt"] = 2
    task["prompt_contract"]["exact_visible_person_count"] = 4
    task["prompt_contract"]["forbidden_background_people"] = True

    manifest = {
        key: copy.deepcopy(value)
        for key, value in source.items()
        if key not in {"tasks", "authorization_binding"}
    }
    manifest.update({
        "schema": "qingshan.giggle_image_content_retry_manifest.v1",
        "status": "PRECHECK_ONLY",
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "authorization_ref": "ROGER-20260828-CONTINUE-E44-PRODUCTION",
        "consumer_contract": {
            **(source.get("consumer_contract") or {}),
            "planned_anchor_count": 1,
            "full_episode_planned_anchor_count": 57,
            "already_bound_anchor_count": 57,
            "replacement_for_failed_anchor_count": 1,
        },
        "dependent_anchor_specs": [],
        "blocked_tasks": [],
        "content_failure_evidence": rel(FAILURE),
        "content_failure_evidence_sha256": sha(FAILURE),
        "tasks": [task],
    })
    write(OUT, manifest)
    print(json.dumps({
        "status": "PASS_ZERO_POST_BUILD",
        "task_key": task["task_key"],
        "prior_prompt_sha256": sha(original_prompt),
        "retry_prompt_sha256": sha(prompt_path),
        "failure_memory": rel(FAILURE),
        "manifest": rel(OUT),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
