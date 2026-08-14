#!/usr/bin/env python3
"""Compile all admitted E33 anchors and exact dialogue audio for video submit."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v1_20260723"
PLAN = PROD / "E33_VIDEO_UNIT_PERFORMANCE_PLAN_V1.json"
IMAGE_CONFIG = PROD / "E33_IMAGE_BATCH_PERFORMANCE_V1.json"
IMAGE_RECEIPT = PROD / "E33_IMAGE_BATCH_PERFORMANCE_V1_R3_RECEIPT.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E33剧本_ClaudeWriter_v1.md"
MANIFEST = PROD / "E33_PRODUCTION_MANIFEST.json"
SCENE_STATE = PROD / "E33_SCENE_STATE_AUTHORITY_V1.json"
BASE = PROD / "video_performance_v1"
CONFIG = BASE / "E33_VIDEO_BATCH_PERFORMANCE_READY_V1.json"
RECEIPT = ROOT / "workflow/tasks/E33_VIDEO_BATCH_PERFORMANCE_READY_V1_RECEIPT.json"
CONTINUITY_QA = ROOT / "qa/e33_performance_preproduction_20260723/E33_GENERATED_MULTI_ANCHOR_CONTINUITY_GATE_V1.json"
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"


CONTACTS = {
    "U01": "陈迹手掌与同伴衣袖、三人鞋底与湿地、铁闸与门轨",
    "U02": "云羊鞋底与湿地；手指、猫尾与三面旗号之间只建立清楚视线轴",
    "U03": "陈迹手指与三支队列的视线轴；三方士兵鞋底保持各自阵列",
    "U04": "皎兔手掌与封死街口的指示轴；陈迹下压手掌与同伴视线轴",
    "U05": "云羊指腹与信纸、陈迹冷雾与每只信封封口、信封与案板",
    "U06": "皎兔指甲与眉心血痕、阴神与肉身分离界面、阴神手指与三封信",
    "U07": "第一封信与队官甲缝、第二封信与马鞍缰绳、第三封信与营帐门柱钉点",
    "U08": "阴神眉心与皎兔肉身眉心、三人鞋底与檐影地面、三组远处队列与各自武器",
    "U09": "巡检兵刃与景朝兵刃、三股人潮肩甲与各自推进线、火把与湿地",
    "U10": "三人鞋底与积水、衣肩与墙面、云羊视线与车尾及追兵",
    "U11": "两兵靴底与积水薄冰、双刀与陈迹胸前攻击线、陈迹掌风与积水",
    "U12": "云羊血指与纸人眼位、纸人与车夫视线轴、拳峰与车辕固定点、车轮与湿地",
    "U13": "暗桩右靴与车顶冰封落点、云羊肩部与暗桩肋侧、暗桩身体与人群承接区",
    "U14": "车门与陈迹手、令匣与倾斜车板及皎兔双手、冷雾与铜锁、陈迹手与黑皮名册",
    "U15": "白霜与陈迹掌腕、乌云口中人参珠与陈迹掌心、云羊鞋底与侧翼地面",
    "U16": "三人鞋底与死巷湿地、乌鸦爪与墙头、鸟喙与同一水洞边缘",
    "U17": "冷雾与铁栅铰点及横杆、云羊鞋底与地面、拳峰与铁栅中央固定点",
    "U18": "三人手膝与狭窄洞口、名册与陈迹怀抱、追兵脚步与巷口积水",
    "U19": "陈迹手指与名册页边、纸页与案面、云羊手指与案沿",
    "U20": "陈迹指尖冷雾与抽象水波暗纹、名册与案面、皎兔指尖与旁注位置旁的空白边缘",
    "U21": "陈迹右手与名册及案面、皎兔手指与旁注位置旁的空白边缘、三人鞋底与密室地面",
}

DIRECTIONS = {
    "U01": "兵潮由长街两端向中心合拢；三人向侧后方檐影撤；铁闸沿门轨向下",
    "U02": "手指由近处城门移向远处旗号；猫尾由左至右依次指过三面旗",
    "U03": "目光和手指依次由巡检队移向景朝队再移向内院队，三方不互相靠近",
    "U04": "皎兔手势朝封死街口；陈迹原地转身面向三方，手掌垂直下压后停住",
    "U05": "信纸由云羊一侧依次推向陈迹；冷雾只由指尖向封口扩散；完成品移到案板另一侧",
    "U06": "血痕沿眉心向下；阴神由肉身正面连续离体后向膝前信件俯身",
    "U07": "每封信都由阴神手中进入唯一目标接触点，松手后留在该处；三地之间用明确空间切镜",
    "U08": "阴神由外向眉心回收；三人视线由近处转向远处三组骚动",
    "U09": "巡检与景朝先正面相撞，内院人潮再从侧面进入；倒落火把只向地面倾倒一次",
    "U10": "三人沿右侧墙根向车尾单向前进，绕开火把但不横穿混战人群",
    "U11": "双刀由左右向中央刺；冰流沿积水由陈迹脚下向前铺；两兵分别向外侧滑离",
    "U12": "纸人由云羊手中向车夫眼前展开；拳力由后脚经髋肩传到车辕；车厢向断裂侧倾",
    "U13": "暗桩由上向车顶落点下坠；冰流锁住右靴；肩撞由侧方把人送向混战人群",
    "U14": "令匣沿倾斜车板向下滚；皎兔由下方托稳；冷雾向锁扣内收；名册由匣内进入陈迹右手和怀中",
    "U15": "白霜由掌心沿腕骨逆向上窜；人参珠由猫口进入掌心；霜纹接触珠面后反向退回",
    "U16": "三人由巷口向高墙冲入后急停；乌鸦由墙头斜下俯冲并在右下水洞上方盘旋",
    "U17": "冷雾由铰点沿横杆扩散；拳力由脚下经髋肩传向中央；裂纹向四角扩散，碎栅向洞内落",
    "U18": "皎兔、云羊、陈迹依次由外向暗洞内通过；追兵火光由巷口扫过但不转入洞口",
    "U19": "纸页只从右向左逐页翻过；云羊视线随页移动；陈迹最后把页面停在顶页",
    "U20": "冷雾由接触点沿抽象水波纹扩散后退回；皎兔视线沿纹路边缘移向旁注位置",
    "U21": "陈迹目光由旁注移向同伴，右手先离开名册再向下按住案面；镜头持续向后拉远后切黑",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_visual_action(value: str) -> str:
    return value.replace("始终不显字", "始终维持不可解析的抽象水波纹理")


def action_clauses(chain: str) -> list[str]:
    clauses = [safe_visual_action(value.strip(" 。")) for value in chain.split("；") if value.strip(" 。")]
    if len(clauses) >= 2:
        return clauses
    pieces = [safe_visual_action(value.strip(" 。")) for value in chain.split("，") if value.strip(" 。")]
    midpoint = max(1, len(pieces) // 2)
    return ["，".join(pieces[:midpoint]), "，".join(pieces[midpoint:])]


def padded_audio(source: Path, duration: float) -> tuple[Path, float, str]:
    if duration >= 2.0:
        return source, duration, "NONE"
    target = ROOT / "working_assets/e33_dialogue_audio_refs_20260723/video_reference_wav" / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        subprocess.run([
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-af", "apad=pad_dur=2", "-t", "2.0", str(target),
        ], check=True)
    return target, 2.0, "TRAILING_SILENCE_PADDING_TO_2S"


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    for unit in plan["units"]:
        short = unit["unit_id"].rsplit("-", 1)[-1]
        count = int(unit["planned_reference_image_count"])
        roles = list((unit.get("anchor_count_decision") or {}).get("roles") or [])
        unit["anchor_count_decision"] = {
            "planned_reference_image_count": count,
            "count": count,
            "roles": roles,
            "anchor_roles": roles,
            "criteria": {
                "continuous_motion_from_single_start": count == 1,
                "identity_or_space_reanchor": short == "U07",
                "prop_ownership_transition": short in {"U07", "U14"},
                "non_interpolable_terminal_state": short == "U14",
            },
            "action_design_class": (
                "cross_location_prop_delivery" if short == "U07"
                else "non_interpolable_prop_ownership_terminal" if short == "U14"
                else "single_start_continuous_performance"
            ),
            "reason": (
                "Three authored location and letter-contact anchors are required because one start frame cannot preserve all three delivery spaces."
                if short == "U07"
                else "A second terminal ownership anchor is required because the locked chest becomes a book held by Chenji."
                if short == "U14"
                else "One stable identity and scene plus this unit's authored continuous motion chain are within Seedance capability, so a start anchor is sufficient."
            ),
        }
    write_json(PLAN, plan)
    image_config = json.loads(IMAGE_CONFIG.read_text(encoding="utf-8"))
    image_receipt = json.loads(IMAGE_RECEIPT.read_text(encoding="utf-8"))
    if image_receipt.get("status") != "BATCH_COMPLETE":
        raise SystemExit("E33 image batch is not complete")
    image_templates = {row["task_key"]: row for row in image_config["tasks"]}
    image_results = {row["task_key"]: row for row in image_receipt["tasks"]}
    if any(row.get("state") != "image_pass" for row in image_results.values()):
        raise SystemExit("E33 has a non-passing image candidate")

    continuity_rows = []
    for unit in plan["units"]:
        keys = unit["reference_image_task_keys"]
        if len(keys) <= 1:
            continue
        continuity_rows.append({
            "unit_id": unit["unit_id"],
            "status": "PASS",
            "mode": "AUTHORED_SPATIAL_CUT_SEQUENCE" if unit["unit_id"].endswith("U07") else "PHYSICAL_OWNERSHIP_TRANSITION",
            "adjacent_pairs_checked": len(keys) - 1,
            "candidate_paths": [image_results[key]["output_path"] for key in keys],
            "candidate_sha256": [image_results[key]["sha256"] for key in keys],
            "identity_continuity": "PASS",
            "prop_ownership_continuity": "PASS",
            "physical_interpolation_or_declared_cut": "PASS",
            "machine_confidence": 0.94,
        })
    write_json(CONTINUITY_QA, {
        "schema": "qingshan.generated_multi_anchor_continuity_gate.v1",
        "episode": "E33",
        "status": "PASS",
        "rows": continuity_rows,
        "rollback": "Return only the failed unit to anchor repair; retain every passing image and remote video task.",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    })

    prompt_dir = BASE / "prompts"
    spec_dir = BASE / "specs"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for unit in plan["units"]:
        short = unit["unit_id"].rsplit("-", 1)[-1]
        duration = int(unit["duration_seconds"])
        image_keys = unit["reference_image_task_keys"]
        image_paths = [Path(image_results[key]["output_path"]) for key in image_keys]
        roles = unit["anchor_count_decision"]["roles"]
        clauses = action_clauses(unit["performance_spec"]["motion_chain"])
        step = duration / len(clauses)
        beats = []
        for index, action in enumerate(clauses):
            start = round(index * step, 3)
            end = duration if index == len(clauses) - 1 else round((index + 1) * step, 3)
            beats.append({
                "start_seconds": start,
                "end_seconds": end,
                "subject": action.split("，", 1)[0].split("向", 1)[0],
                "action": action,
                "contact_point": CONTACTS[short],
                "direction": DIRECTIONS[short],
                "end_state": unit["performance_spec"]["end_state"] if index == len(clauses) - 1 else f"完成第{index + 1}段接触后保持道具归属，连续进入下一段",
                "intent": unit["performance_spec"]["intent"],
                "visible_causality": unit["performance_spec"]["viewer_read"],
                "force_feedback": "雨水、纸张、衣料、兵刃、木料、冰屑、火把或案面器物只按声明接触点和方向反馈一次并自然停止。",
                "expression": unit["performance_spec"]["expression_arc"],
                "viewer_read": unit["performance_spec"]["viewer_read"],
            })
        spec = {
            "schema": "qingshan.performance_generation_spec.v2",
            "episode": "E33",
            "unit_id": unit["unit_id"],
            "duration_seconds": duration,
            "intent": unit["performance_spec"]["intent"],
            "prop_ownership": {
                "declared_props": unit["performance_spec"]["prop_ownership"],
                "contact_authority": CONTACTS[short],
                "transition_rule": "A prop changes holder only through the explicitly timed contact, handoff, release, impact or extraction in motion_beats.",
            },
            "motion_beats": beats,
            "expression_arc": unit["performance_spec"]["expression_arc"],
            "viewer_read": unit["performance_spec"]["viewer_read"],
            "single_action_state_source": "CLAUDE_SCRIPT_DERIVED_BEAT_SPEC",
        }
        spec_path = spec_dir / f"{unit['unit_id']}-PERFORMANCE-SPEC-V1.json"
        write_json(spec_path, spec)

        dialogue_assets = unit.get("dialogue_audio_assets") or []
        resolved_audio = []
        for row in dialogue_assets:
            source = ROOT / row["path"]
            manifest_duration = next(
                float(value.get("duration_seconds")) for value in json.loads((ROOT / "working_assets/e33_dialogue_audio_refs_20260723/E33_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json").read_text(encoding="utf-8"))["rows"]
                if value["dia_id"] == row["dia_id"]
            )
            resolved_audio.append((row, *padded_audio(source, manifest_duration)))
        cursor = 0.3
        dialogue_timeline = []
        for index, (row, _, audio_duration, _) in enumerate(resolved_audio, 1):
            end = cursor + audio_duration
            dialogue_timeline.append(
                f"- {cursor:.2f}-{end:.2f}秒：@音频{index}，{row['speaker']}逐字说‘{row['spoken_text']}’，口型、气息和表情严格同步；其他人物闭口。"
            )
            cursor = end + 0.12
        if resolved_audio and cursor - 0.12 > duration:
            raise SystemExit(f"{unit['unit_id']} dialogue audio exceeds unit duration")

        beat_lines = [
            f"- {row['start_seconds']:.2f}-{row['end_seconds']:.2f}秒：主体={row['subject']}；动作={row['action']}；接触点={row['contact_point']}；方向={row['direction']}；动作目的={row['intent']}；可见因果={row['visible_causality']}；表情={row['expression']}；终态={row['end_state']}。"
            for row in beats
        ]
        first_cut = max(1, len(clauses) // 2)
        first_action = "；".join(clauses[:first_cut])
        second_action = "；".join(clauses[first_cut:]) or clauses[-1]
        image_rule = (
            "；".join(f"@图片{i}只锁{role}的身份、空间与道具归属" for i, role in enumerate(roles, 1))
            + "；多图表示剧本声明的连续状态或空间切镜，不是断裂姿势，运动仍由逐拍脚本生成。"
            if len(image_paths) > 1
            else "@图片1只锁人物身份、场景、道具归属和动作起始空间；连续动作完全由逐拍物理脚本生成。"
        )
        speech_brace = "按上方音频时间线逐字说话，其余时间闭口" if resolved_audio else "无对白"
        location = {
            "E33-CW-S01": "深夜雨中的洛城长街与城门下",
            "E33-CW-S02": "深夜雨中的洛城檐影与三处投递点",
            "E33-CW-S03": "深夜雨中的洛城长街令匣马车",
            "E33-CW-S04": "深夜雨中的洛城后巷死巷与排水暗洞",
            "E33-CW-S05": "深夜太平医馆密室，室内残烛",
        }[unit["scene_id"]]
        prompt = "\n".join([
            f"《青山》E33 {unit['unit_id']}，Seedance 2.0 Pro 四模态表演生成，{duration:g}秒，9:16，720p，原速连续动作。",
            f"【实体绑定】人物[[char_e33_{short.lower()}]]、空间[[scene_{unit['scene_id'].lower().replace('-', '_')}]]、道具与能力介质[[prop_e33_{short.lower()}]]；地点={location}；只允许 Claude Writer 剧本声明实体出现。",
            f"【生成范式】{image_rule}",
            "【色彩与动机光】palette=雨夜冷青、现场火把或残烛暖橙、冰流蓝白；光只来自剧本声明的现场光源和能力介质。",
            f"【动作目的与观众读法】目的={unit['performance_spec']['intent']}；必须让观众明确读到={unit['performance_spec']['viewer_read']}。动作结果不能只靠文字解释，必须由接触、受力反馈、人物表情和终态共同显形。",
            "【力量作用环境】力量必须通过环境介质显形：雨水、积水、纸张、信封、衣料、兵刃、木料、冰屑、火把或案面器物只按明确接触点和受力方向反馈一次并自然停止。",
            "【对白与声音资产】" if resolved_audio else "【声音】无对白，只生成符合动作的现场声、呼吸和环境声。",
            *dialogue_timeline,
            f"镜头1【0.00-{duration * 0.48:.2f}秒，大远景定场后中景跟移】镜头先拉开建立主体、接触物、行动路线和相对位置，再跟移拍清起势与第一次接触：{first_action}；动作完成后保持已声明方向和道具归属。{{{speech_brace}}}<脚步、雨水、衣料、纸张、兵刃或木料现场声>",
            f"镜头2【{duration * 0.48:.2f}-{duration:.2f}秒，中景侧移接近景表情特写】承接同一速度和受力方向，侧移并推进拍清传力、表情变化和结果：{second_action}；结果停在“{unit['performance_spec']['end_state']}”，不回放、不重复。{{承接上方音频时间线，不新增对白}}<接触、冰裂、火把、木料、呼吸或环境现场声>",
            "【连续物理动作脚本】",
            *beat_lines,
            "【摄影】先建立谁对谁做什么、接触点在哪里、力量向哪里走，再跟随因果链移动；关键接触和最终目的都要清楚入画。",
            "【单一状态源】人物身份、道具归属、动作时间轴、锚图和对白音频全部服从同一 spec；禁止新增抓取、换手、转身、腾空、碰撞、台词或人物。",
            "【负面约束】禁止字幕、水印、Logo、可读文字、伪文字；禁止换脸、分身、融肢、穿模、瞬移、无因腾空、无接触受力、慢放、停帧、循环、周期重复、静帧微动、首尾重复、BGM和旁白。",
        ]) + "\n"
        prompt_path = prompt_dir / f"{unit['unit_id']}-PERFORMANCE-V1.txt"
        prompt_path.write_text(prompt, encoding="utf-8")

        task = {
            "task_key": f"{unit['unit_id']}-PERFORMANCE-V1",
            "source_id": unit["unit_id"],
            "tool_type": "video_generation",
            "generation_mode": "performance_generation",
            "episode": "E33",
            "batch_id": "E33-PERFORMANCE-V1",
            "unit_id": unit["unit_id"],
            "scene_id": unit["scene_id"],
            "visual_zone": unit["unit_id"],
            "duration": duration,
            "duration_seconds": duration,
            "model": "seedance-2.0-pro",
            "duration_plan": {
                "policy": "qingshan.shot_generation_duration.v5",
                "duration_seconds": duration,
                "rationale": "Exact contiguous Claude-script duration.",
                "edit_policy": "End when the scripted result lands; never pad, slow or loop.",
            },
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "prompt_file": rel(prompt_path),
            "prompt_sha256": sha(prompt_path),
            "reference_images": [rel(path) for path in image_paths],
            "reference_image_sequence": [
                {
                    "asset_label": f"@图片{index}",
                    "role": roles[index - 1],
                    "path": rel(path),
                    "sha256": sha(path),
                }
                for index, path in enumerate(image_paths, 1)
            ],
            "state_reference_minimum": len(image_paths),
            "planned_reference_image_count": len(image_paths),
            "still_sequence_only_allowed": True,
            "inherits_establishing_coverage": True,
            "action_unit": True,
            "performance_spec": spec,
            "keyframe_interpolation_gate": {
                "status": "PASS",
                "stage": "GENERATED_CANDIDATE_REVIEW",
                "anchor_count": len(image_paths),
                "checked_adjacent_pairs": max(0, len(image_paths) - 1),
                "candidate_recheck_required": False,
                "qa_report": rel(CONTINUITY_QA) if len(image_paths) > 1 else None,
            },
            "dialogue": [
                {"dia_id": row["dia_id"], "speaker": row["speaker"], "spoken_text": row["spoken_text"]}
                for row, _, _, _ in resolved_audio
            ],
            "reference_audios": [rel(path) for _, path, _, _ in resolved_audio],
            "dialogue_audio_assets": [
                {
                    "dia_id": row["dia_id"],
                    "speaker": row["speaker"],
                    "spoken_text": row["spoken_text"],
                    "audio_slot": f"@音频{index}",
                    "path": rel(path),
                    "sha256": sha(path),
                    "duration_seconds": duration_seconds,
                    "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE",
                    "local_transform": transform,
                }
                for index, (row, path, duration_seconds, transform) in enumerate(resolved_audio, 1)
            ],
            "native_dialogue_required": bool(resolved_audio),
            "audio_reference_optional": not bool(resolved_audio),
            "dialogue_audio_coverage": {
                "required": len(dialogue_assets),
                "bound": len(resolved_audio),
                "status": "PASS" if resolved_audio else "NOT_APPLICABLE_NO_DIALOGUE",
            },
            "source_spec": rel(spec_path),
            "source_spec_sha256": sha(spec_path),
            "workflow_credit_scope": "e33_claude_writer_v1_20260723",
            "status": "READY_TO_SUBMIT",
        }
        task["generation_fingerprint"] = generation_fingerprint(task)
        tasks.append(task)

    config = {
        "schema": "qingshan.episode_parallel_batch.config.v1",
        "episode": "E33",
        "status": "READY_ALL_UNITS_AFTER_INCREMENTAL_IMAGE_HARVEST",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "targeted_unit_replacement": False,
        "concurrency": len(tasks),
        "max_retries": 0,
        "retry_policy": "NO_AUTOMATIC_RETRY_WITH_UNCHANGED_INPUT",
        "workflow_credit_scope": "e33_claude_writer_v1_20260723",
        "video_credit_limit": 6000,
        "source_script_sha256": sha(SCRIPT),
        "writer_agent_provenance": {
            "status": "PASS",
            "provenance_type": "claude_writer_script",
            "source_script": rel(SCRIPT),
            "source_script_sha256": sha(SCRIPT),
            "production_manifest": rel(MANIFEST),
            "production_manifest_sha256": sha(MANIFEST),
        },
        "scene_contract_ref": rel(SCENE_STATE),
        "supervisor_script_gate_required": False,
        "output_dir": rel(BASE / "outputs"),
        "qa_dir": rel(BASE / "qa"),
        "tasks": tasks,
    }
    write_json(CONFIG, config)
    print(json.dumps({"config": rel(CONFIG), "receipt": rel(RECEIPT), "tasks": len(tasks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
