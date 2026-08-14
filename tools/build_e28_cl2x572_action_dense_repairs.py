#!/usr/bin/env python3
"""Build changed-input U02/U03/U11 prompts for CL2X-572."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from video_prompt_action_density_gate import require_action_timeline
from shot_duration_policy import POLICY_VERSION


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e28_cl2x517_20260721"
BASE_CONFIG = PRODUCTION / "E28_13_VIDEO_UNIT_PROMPT_BATCH_V3.json"
PROMPT_DIR = PRODUCTION / "video_prompts_multireference_v4_cl2x572"
CONFIG_OUT = PRODUCTION / "E28_U02_U03_U11_ACTION_DENSE_R1_BATCH_CL2X572.json"
RECEIPT_OUT = ROOT / "workflow/tasks/CL2X572_E28_ACTION_DENSE_PROMPT_BUILD_RECEIPT_20260722.json"


REPAIRS = {
    "E28-CW-U02": [
        (0.0, 2.5, "@图片1", ["活口蜷紧抓住袖口的手指，抬眼寻找梁上的冰线", "活口吸气后开始说出誊抄训令的供词"], "活口由畏缩沉默转为主动供述，视线明确指向梁上。"),
        (2.5, 5.0, "@图片1", ["活口说完供词并垂下头", "陈迹翻过名册一页，用拇指压住连续的不可读墨点条目"], "供词结束，名册从背景道具变成陈迹手中的证据。"),
        (5.0, 7.5, "@图片2", ["陈迹沿名册上的名字移动指尖，同时说出碰过训令者都被写上册", "陈迹合拢名册并转腕查看手背"], "陈迹完成判断，注意力从名册转到手背反噬。"),
        (7.5, 10.0, "@图片2", ["皎兔走到门边，以刀背依次轻叩门闩和窗框", "皎兔说出门窗封死，随后抬刀指向梁槽"], "门、窗、梁三处布防被逐项验证，而非保持静态构图。"),
        (10.0, 12.5, "@图片2", ["皎兔沿冰线移动刀尖并继续说出先碰断线的判断", "薄霜从陈迹指节向手背和手腕连续爬行"], "皎兔完成防线说明，陈迹的反噬由指节扩展到手腕。"),
        (12.5, 15.0, "@图片2", ["陈迹屈伸被霜包住的手指，随即攥拳压下寒气", "拳缝冰晶崩裂落下，皎兔收刀回望陈迹"], "反噬被暂时压住，冰晶落地形成明确结束按钮。"),
    ],
    "E28-CW-U03": [
        (0.0, 2.0, "@图片1", ["梁上冰线由松弛转为绷直，细小冰晶沿线向屋脊疾跑", "云羊仰头急喊线断在梁上"], "预警从静态冰线变为朝屋脊传导的异常拉力。"),
        (2.0, 4.0, "@图片1", ["冰线在梁角崩断，断口甩回并刮落木屑", "镜头跟随断线方向迅速下倾到垂索入口"], "预警完成，画面由梁上证据转向入侵者的垂索。"),
        (4.0, 6.0, "@图片2", ["蒙面教习双手控索从梁间滑下，绳索受重向下绷直", "教习双脚蹬过梁柱调整身体朝向"], "教习从高处进入室内并完成朝向活口的转体。"),
        (6.0, 8.0, "@图片2", ["教习放开一手拔刀，肩胯同向压低", "刀锋沿可追踪弧线逼近活口咽喉"], "威胁由垂降转成清晰的刺杀轨迹。"),
        (8.0, 9.5, "@图片3", ["皎兔跨入刀路，拔刀横格", "皎兔肩部撞开活口，使活口向她身后退半步"], "皎兔进入两人之间，活口脱离刀锋直线。"),
        (9.5, 11.0, "@图片3", ["双刀正面相撞并迸出火星", "皎兔压刀向外推开教习刀锋，二人脚下各退半步"], "刀锋分离，第一轮接触以双方重新拉开距离结束。"),
    ],
    "E28-CW-U11": [
        (0.0, 2.0, "@图片1", ["单一蒙面黑影沿第一道雪檐疾跑，每一步踢起新雪", "黑影在檐角压低重心并起跳"], "黑影从第一道屋脊离地，雪粉留在起跳点。"),
        (2.0, 4.0, "@图片1", ["黑影越过窄巷落到第二道屋脊", "落脚处瓦面抖落积雪，黑影借势向前翻滚起身"], "追逃路线从第一道屋脊推进到第二道屋脊。"),
        (4.0, 6.0, "@图片1", ["黑影再次蹬瓦跃向更远飞檐，斗篷被侧风拉直", "黑影落到屋脊背面并从视野中消失"], "目标越过遮挡离开画面，远景追逃段立即结束。"),
        (6.0, 8.0, "@图片2", ["云羊从巷墙翻下，双脚落雪后向前滑出", "云羊急转身体并反手举起火把"], "云羊由高处追击转为落地勘查。"),
        (8.0, 10.0, "@图片2", ["云羊转腕抬高火把，火光横扫雪面并照出前深后浅的两种步幅", "云羊沿两组脚印移动火把，再俯身指向分叉方向"], "雪地由空白变为可辨认的双步幅证据。"),
        (10.0, 11.5, "@图片3", ["陈迹跑入火光，收步后单膝滑跪到脚印旁", "陈迹从袖中抽出无字拓纸并展开"], "陈迹抵达证据点，拓纸由收纳状态展开。"),
        (11.5, 13.0, "@图片3", ["陈迹用右掌把拓纸压平在两组脚印旁", "薄霜沿纸边勾出两种步距，陈迹抬头望向黑影消失的屋脊"], "两种步幅被固定为证据，陈迹的视线把线索重新指向屋脊。"),
    ],
}

CAMERA_SPECS = {
    "E28-CW-U02": [
        "景别=近景；机位与运动=手持贴近活口手部后抬到眼线",
        "景别=中近景；机位与运动=跟随名册翻页横移到陈迹拇指",
        "景别=手部特写；机位与运动=从名册短摇到陈迹手腕",
        "景别=中景；机位与运动=跟随皎兔由门闩移动到窗框",
        "景别=双人近景；机位与运动=刀尖引导视线由梁槽下移到陈迹手背",
        "景别=手部大特写；机位与运动=锁定攥拳与冰晶崩落后短抬至皎兔视线",
    ],
    "E28-CW-U03": [
        "景别=梁上特写；机位与运动=沿绷紧冰线快速横移",
        "景别=近景转中景；机位与运动=跟随断线甩回后快速下倾",
        "景别=全景；机位与运动=垂直跟随教习沿索下降",
        "景别=中近景；机位与运动=贴随肩胯转体和刀锋下降",
        "景别=双人中景；机位与运动=横移跟随皎兔切入刀路",
        "景别=交刃特写转中景；机位与运动=碰撞瞬间短震后拉开二人距离",
    ],
    "E28-CW-U11": [
        "景别=航拍大远景；机位与运动=侧向跟随第一道雪檐疾跑",
        "景别=远景；机位与运动=跨巷跟随起跳、落瓦与翻滚",
        "景别=远景定场；机位与运动=追随第二次跃檐并停在遮挡边缘",
        "景别=全景转中景；机位与运动=俯跟云羊翻墙落雪和滑行",
        "景别=雪面近景；机位与运动=随火把光横扫两组脚印",
        "景别=中近景；机位与运动=跟随陈迹跑入后下沉到跪姿",
        "景别=俯拍特写；机位与运动=锁定拓纸压平后抬向屋脊",
    ],
}

DIALOGUE_SLOTS = {
    "E28-CW-U02": [
        "{对白：活口开始并完整说出‘我……替教习誊抄过训令。’}",
        "{无对白：活口闭口，禁止新增台词}",
        "{对白：陈迹完整说出‘碰过那份训令的人，一个个都被写上了册。’}",
        "{对白：皎兔说‘门窗封死，梁上有线。’}",
        "{对白：皎兔接续说‘他要动这个人，先得碰断我的线。’}",
        "{无对白：只保留压抑呼吸}",
    ],
    "E28-CW-U03": [
        "{对白：云羊完整急喊‘线断在梁上——’}",
        "{无对白}", "{无对白}", "{无对白}", "{无对白}", "{无对白}",
    ],
    "E28-CW-U11": ["{无对白}"] * 7,
}

SFX_SPECS = {
    "E28-CW-U02": ["<音效：袖料收紧、急促吸气>", "<音效：名册翻页、纸页合拢>", "<音效：指尖擦纸、细霜脆响>", "<音效：刀背叩木两声、脚步横移>", "<音效：刀尖划过冰线、冰霜爬肤>", "<音效：攥拳闷响、冰晶落地>"],
    "E28-CW-U03": ["<音效：冰线绷紧、急促喊声>", "<音效：冰线崩断、木屑落下>", "<音效：索具受力、靴底擦梁>", "<音效：拔刀、刀锋破空>", "<音效：脚步切入、衣料碰撞>", "<音效：双刀碰撞、火星迸裂、退步>"],
    "E28-CW-U11": ["<音效：踏雪、风声、雪粉扬起>", "<音效：落瓦闷响、积雪坠落>", "<音效：蹬瓦、斗篷破风>", "<音效：落雪、滑行、火把噼啪>", "<音效：火把噼啪、雪面擦响>", "<音效：跑步、膝落雪地、纸张展开>", "<音效：掌压纸面、薄霜结晶>"],
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timeline_rows(spec: list[tuple]) -> list[dict]:
    return [
        {
            "start_seconds": start,
            "end_seconds": end,
            "reference_anchor": reference,
            "actions": actions,
            "state_change": state_change,
            "action_budget_seconds": round(end - start, 3),
        }
        for start, end, reference, actions, state_change in spec
    ]


def replace_action_section(unit_id: str, original: str, rows: list[dict]) -> str:
    lines = original.splitlines()
    first_shot = next(index for index, line in enumerate(lines) if line.startswith("镜头1【"))
    audio_section = next(index for index, line in enumerate(lines) if line.startswith("【对白与声音资产】"))
    prefix = lines[:first_shot]
    suffix = lines[audio_section:]
    action_lines = [
        "【逐时段动作密度硬锁】以下每段都必须完整执行；不得省略中间动作，不得以站定、慢推、静止表情或循环动作填充任何秒数。"
    ]
    for index, row in enumerate(rows, 1):
        action_lines.append(
            f"镜头{index}【{row['start_seconds']:.1f}-{row['end_seconds']:.1f}秒；参考锚={row['reference_anchor']}；{CAMERA_SPECS[unit_id][index - 1]}】："
            f"{'；'.join(row['actions'])}；动作结果：{row['state_change']}"
            f"{DIALOGUE_SLOTS[unit_id][index - 1]}{SFX_SPECS[unit_id][index - 1]}"
        )
    action_lines.extend([
        "【时长退出条件】最后一个结果一旦完成立即结束镜头；禁止补静帧、慢放、重复动作或无信息空镜。",
        "",
    ])
    return "\n".join(prefix + action_lines + suffix) + "\n"


def clean_task(base: dict, prompt_path: Path, rows: list[dict], gate: dict) -> dict:
    task = copy.deepcopy(base)
    prior_task_id = task.get("task_id")
    prior_prompt_sha = task.get("prompt_sha256")
    for key in (
        "task_id", "state", "remote_status", "submitted_at", "submit_response",
        "credit_attempts", "last_polled_at", "output_path", "output_sha256",
        "output_size_bytes", "output_duration_seconds", "remote_short_url",
        "remote_asset_id", "qa_decision", "qa_confidence", "qa_report", "qa_failures",
        "generation_fingerprint",
    ):
        task.pop(key, None)
    task.update({
        "task_key": f"{task['unit_id']}-VIDEO-CL2X572-R1",
        "prompt_file": str(prompt_path.relative_to(ROOT)),
        "prompt_sha256": sha256(prompt_path),
        "action_timeline": rows,
        "action_density_gate": gate,
        "duration": task["duration_seconds"],
        "duration_plan": {
            "policy": POLICY_VERSION,
            "duration_seconds": task["duration_seconds"],
            "speech_seconds_estimate": None,
            "action_seconds": task["duration_seconds"],
            "reaction_or_button_seconds": 0.0,
            "raw_seconds": task["duration_seconds"],
            "tool_minimum_floor_applied": False,
            "edit_policy": "End immediately after the last scripted state change; no hold, slow motion, loop, or filler.",
            "rationale": "CL2X-572 action timeline covers every second with concrete playable movement; duration equals the audited action budget.",
        },
        "status": "READY_FOR_PARALLEL_SUBMIT",
        "prior_candidate_task_id": prior_task_id,
        "prior_prompt_sha256": prior_prompt_sha,
        "changed_input_reason": "CL2X-572: replace sparse or static intervals with concrete 1.5-2.5 second actions and state changes across the full native duration",
    })
    return task


def main() -> int:
    base = json.loads(BASE_CONFIG.read_text(encoding="utf-8"))
    by_unit = {task["unit_id"]: task for task in base["tasks"]}
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    gates = []
    for unit_id, spec in REPAIRS.items():
        base_task = by_unit[unit_id]
        duration = float(base_task["duration_seconds"])
        rows = timeline_rows(spec)
        gate = require_action_timeline(rows, duration, source_id=unit_id)
        original = ROOT / base_task["prompt_file"]
        prompt_path = PROMPT_DIR / f"{unit_id}.txt"
        prompt_path.write_text(replace_action_section(unit_id, original.read_text(encoding="utf-8"), rows), encoding="utf-8")
        task = clean_task(base_task, prompt_path, rows, gate)
        if task["prompt_sha256"] == task["prior_prompt_sha256"]:
            raise RuntimeError(f"prompt did not change: {unit_id}")
        tasks.append(task)
        gates.append(gate)

    config = {
        "schema": "qingshan.episode_parallel_batch.config.v1",
        "episode": "E28",
        "status": "READY_FOR_PARALLEL_SUBMIT_CHANGED_INPUT_ONLY",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "concurrency": 3,
        "max_retries": 0,
        "retry_policy": "NO_AUTOMATIC_RETRY; EACH FUTURE RETRY REQUIRES NEW PLAYABLE ACTION INPUT",
        "source_script_sha256": base["source_script_sha256"],
        "final_still_plan": base["final_still_plan"],
        "final_still_plan_sha256": base["final_still_plan_sha256"],
        "cl2x_instruction": "CL2X-572",
        "tasks": tasks,
    }
    CONFIG_OUT.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "schema": "qingshan.cl2x572.execution_receipt.v1",
        "episode": "E28",
        "status": "PASS_CHANGED_INPUT_PROMPTS_READY_NOT_YET_SUBMITTED",
        "config": str(CONFIG_OUT),
        "config_sha256": sha256(CONFIG_OUT),
        "units": [task["unit_id"] for task in tasks],
        "duration_seconds": {task["unit_id"]: task["duration_seconds"] for task in tasks},
        "action_density_gates": gates,
        "prompt_sha256": {task["unit_id"]: task["prompt_sha256"] for task in tasks},
        "prior_prompt_sha256": {task["unit_id"]: task["prior_prompt_sha256"] for task in tasks},
        "remote_calls": 0,
        "credit_spent": 0,
    }
    RECEIPT_OUT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "config": str(CONFIG_OUT), "units": receipt["units"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
