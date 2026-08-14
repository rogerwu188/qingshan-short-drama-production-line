#!/usr/bin/env python3
"""Build E30 U01 as an audio-driven continuous performance generation task."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e30_claude_writer_v1_20260722/u01_performance_r2"
PROMPT = BASE / "E30-CW-U01-PERFORMANCE-R2.txt"
SPEC = BASE / "E30-CW-U01-PERFORMANCE-SPEC-R2.json"
CONFIG = BASE / "E30-CW-U01-PERFORMANCE-BATCH-R2.json"
ANCHOR = ROOT / "working_assets/e30_claude_writer_v1_stills_20260722/repair_r1_candidates/E30_E30-CW-S01-SH01-C1-STILL-R1_454035d4-2dd0-48ed-81d3-870efd028e67.png"
AUDIO = ROOT / "working_assets/e30_dialogue_v10_20260722/fitted/E30-DIA-001.wav"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    if not ANCHOR.is_file() or not AUDIO.is_file():
        raise SystemExit("identity/scene anchor or exact dialogue audio missing")
    BASE.mkdir(parents=True, exist_ok=True)
    beats = [
        {
            "start_seconds": 0.0, "end_seconds": 0.8,
            "subject": "刺客右手与短刃", "action": "维持已经形成的贴喉威胁，不挥砍",
            "contact_point": "短刃平直刀锋停在陈迹下颌与喉结之间、距皮肤约两厘米",
            "direction": "刀尖水平朝陈迹左侧，刺客前臂从陈迹左后方伸入",
            "end_state": "短刃仍由刺客右手握持，陈迹双手未碰刀",
            "intent": "刺客以近距离刀锋建立必杀威胁并压制陈迹",
            "visible_causality": "刀锋稳定停在喉前，刺客握柄指节收紧，刀面映出烛光；此时尚无法术",
            "expression": "刺客眼神冷硬自信；陈迹呼吸平稳、神情警觉但不慌乱",
            "viewer_read": "刺客掌握主动，短刃下一刻即可刺入陈迹喉部",
        },
        {
            "start_seconds": 0.8, "end_seconds": 4.9,
            "subject": "刺客", "action": "身体留在陈迹左后方，嘴靠近陈迹左耳，以气声完整说出参考音频中的一句话",
            "contact_point": "刺客右手握柄；短刃保持在陈迹喉前；双方身体不交换位置",
            "direction": "刺客口型与@音频1同步，右腕只做维持压力的微小肌肉运动",
            "end_state": "台词完整说完一次，刺客仍持刀，陈迹保持镇定且闭口",
            "intent": "刺客宣告死亡名单并以语言确认杀意",
            "visible_causality": "刺客嘴靠近陈迹左耳说话，呼气轻拂耳侧；短刃随呼吸产生极小颤动但不前进",
            "expression": "刺客由冷漠转为轻蔑；陈迹眼神从前方缓慢聚焦到刀锋，镇定判断",
            "viewer_read": "刺客确实在说目标台词，陈迹在寻找反制时机而非僵住",
        },
        {
            "start_seconds": 4.9, "end_seconds": 6.4,
            "subject": "陈迹右手", "action": "从右袖内缓慢抬起食指，靠近短刃刀身中段的平面，不抓刀柄",
            "contact_point": "陈迹右食指指尖轻触刀身平面中段；刺客右手持续握住刀柄",
            "direction": "指尖由下向上移动约十厘米后停止",
            "end_state": "陈迹指尖接触刀身，短刃归属仍是刺客",
            "intent": "陈迹以最小动作启动护住喉部的冰系防御",
            "visible_causality": "指尖接近刀身时亮起冷蓝微光；一层半透明蓝色弧形光幕从指尖展开到陈迹喉前，位于刀锋与皮肤之间",
            "expression": "陈迹眉眼平静、嘴角不动；刺客余光察觉蓝光，轻蔑开始变成疑惑",
            "viewer_read": "陈迹正在主动生成一面保护喉部的能量屏障，不是在徒手接刀",
        },
        {
            "start_seconds": 6.4, "end_seconds": 9.4,
            "subject": "陈迹指尖、蓝色弧形光幕与短刃", "action": "稳固喉前光幕；短刃首次接触光幕时激起蓝色弧形涟漪，冷霜再从碰撞点沿同一把短刃连续蔓延",
            "contact_point": "刀锋接触光幕外表面，光幕距陈迹喉部约一厘米；冷霜只附着金属刀身",
            "direction": "光幕由指尖向上弯曲包住喉部正面；蓝色涟漪从刀锋接触点向弧面扩散，白霜由刀身中段向刀尖与护手传播",
            "end_state": "弧形光幕完整挡在喉前，整段刀身覆霜，刺客仍握柄，刀锋未穿透光幕",
            "intent": "把抽象的受阻转化为观众可见的防御碰撞与冻结结果",
            "visible_causality": "刀锋碰到半透明蓝色弧面立即出现同心涟漪和接触亮斑；光幕内侧与喉部保持清晰空气间隙，刀身随后结霜",
            "expression": "陈迹目光稳定、对法术有完全控制；刺客眉头收紧，第一次显出惊疑",
            "viewer_read": "蓝色光幕是刀无法靠近喉部的直接原因，结霜是碰撞后的持续控制效果",
        },
        {
            "start_seconds": 9.4, "end_seconds": 11.8,
            "subject": "刺客右腕、冻结短刃与蓝色弧形光幕", "action": "刺客咬牙加力把刀推向陈迹喉部；刀锋压弯光幕外缘但无法穿透，光幕产生更强蓝色波纹并把反作用力传回刺客手腕",
            "contact_point": "刀锋持续抵住光幕外表面的同一接触点；光幕内表面仍不接触陈迹皮肤",
            "direction": "刺客向前推刀；光幕弧面向内轻微弹性形变后恢复，反作用力沿刀身反向震回刺客右腕",
            "end_state": "刀锋停在光幕外，刺客手腕被震得短促后挫，陈迹喉部毫发无伤",
            "intent": "刺客试图完成刺杀，陈迹的防御必须以明确反作用力挫败这一目的",
            "visible_causality": "接触点蓝光骤亮，弧面涟漪加速扩散，刀身高频颤动但刀尖没有越过光幕；刺客袖口与手腕同步后震",
            "expression": "刺客咬牙发力、额角绷紧，随后瞳孔放大；陈迹始终从容，眼神转向刺客",
            "viewer_read": "刺客确实用力刺了，但被可见的蓝色屏障弹回，而不是主动停手",
        },
        {
            "start_seconds": 11.8, "end_seconds": 14.0,
            "subject": "陈迹、刺客与稳定的蓝色弧形光幕", "action": "陈迹保持光幕稳定并平静侧目；刺客看见覆霜短刃和未被刺伤的陈迹，因反杀失败露出惊惧",
            "contact_point": "陈迹指尖悬在光幕边缘维持法术；刺客仍握刀柄，冻结刀锋停在光幕外",
            "direction": "陈迹视线由前方转向左后方刺客，身体和刀具不换位",
            "end_state": "画面自然停在蓝色弧形光幕护住喉部、冻结短刃被挡在外侧、刺客持刀惊惧、陈迹镇定的明确结果",
            "intent": "用两人的表情反差落下攻守逆转",
            "visible_causality": "蓝色光幕余波逐渐平息但保持可见，覆霜刀身停止颤动，陈迹皮肤与光幕之间仍有安全间隙",
            "expression": "陈迹冷静侧目、带有掌控局面的克制；刺客呼吸一滞、眼神惊惧不敢置信",
            "viewer_read": "陈迹已经完全化解刺杀并掌握主动，刺客意识到目标远强于预期",
        },
    ]
    spec = {
        "schema": "qingshan.performance_generation_spec.v2",
        "episode": "E30", "unit_id": "E30-CW-U01", "duration_seconds": 14,
        "source": "Claude Writer E30 scene 4-1, first two contiguous editorial shots",
        "identity_scene_anchor": relative(ANCHOR),
        "dialogue": [{
            "dia_id": "E30-DIA-001", "speaker": "刺客",
            "spoken_text": "名单上有你。今夜，你不该活着。",
            "audio_slot": "@音频1", "reference_audio": relative(AUDIO),
            "reference_audio_sha256": sha256(AUDIO),
        }],
        "prop_ownership": {
            "short_blade_0.0_to_14.0": "刺客右手持续握持；陈迹从不抓取、接管或挥动短刃",
            "arc_barrier_4.9_to_14.0": "陈迹右食指生成并维持位于短刃与喉部之间的半透明蓝色弧形光幕",
            "frost_6.4_to_14.0": "短刃接触蓝色弧形光幕后，冷霜从接触点附着并沿同一把短刃扩散",
        },
        "motion_beats": beats,
        "forbidden_transitions": [
            "短刃换到陈迹手中", "刺客与陈迹交换位置", "无前置动作的转身、腾空、抓取或击打",
            "刀锋穿过皮肤", "动作循环、慢放、停帧或重复首帧",
        ],
    }
    SPEC.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    beat_lines = [
        f"- {row['start_seconds']:.1f}-{row['end_seconds']:.1f}秒：主体={row['subject']}；动作={row['action']}；"
        f"接触点={row['contact_point']}；方向={row['direction']}；意图={row['intent']}；"
        f"可见因果={row['visible_causality']}；表情={row['expression']}；"
        f"观众读法={row['viewer_read']}；终态={row['end_state']}。"
        for row in beats
    ]
    prompt = "\n".join([
        "《青山》E30《以笔为刀》U01，Seedance 2.0 Pro 表演生成，14秒，9:16，720p，原速连续动作。",
        "【实体绑定】陈迹[[char_chenji]]、刺客[[char_assassin]]、漆黑药堂[[scene_medical_back_hall]]、短刃[[prop_short_blade]]。",
        "【生成范式】@图片1只锁定陈迹、刺客、漆黑药堂、服装和初始空间关系；不要逐图命中姿势，不要把画面做成静态图微动。由以下唯一逐拍动作 spec 驱动完整表演。",
        "【色彩与动机光】palette=暖烛琥珀、药柜暗木、法术冷蓝；环境动机光来自案头烛火，唯一超自然光源是陈迹右食指生成的半透明冷蓝弧形光幕。蓝光只照亮喉前、指尖、刀身和两人邻近面部，不添加无来源粒子。力量作用反馈到环境介质：短刃撞上光幕时案头烛焰朝外短促偏转，药柜前已有的薄尘被弧面冲击轻微推开，反馈只发生一次且随碰撞衰减。",
        "【对白音频】@音频1是刺客本句精确目标对白参考。刺客必须以自然中文普通话气声完整说一次“名单上有你。今夜，你不该活着。”，台词、音色、语速、节奏、气息与@音频1一致，口型和起止时间同步；陈迹全程闭口。",
        "【摄影】0-4.9秒近景手持维持贴喉压力并看清刺客说话表情；4.9-9.4秒平滑移向指尖、刀锋与喉部之间，必须完整看见蓝色弧形光幕从无到有、刀锋撞上光幕的接触点；9.4-14秒带回刺客发力受挫和两人表情反差。镜头运动服务因果，不统一慢推。",
        "镜头1【0.0-4.9秒，近景手持，陈迹左前侧反打】刺客从陈迹左后方持刀贴近，抬腕维持刀锋安全间隙，靠近左耳按@音频1完整说话；陈迹保持镇定闭口。{刺客：名单上有你。今夜，你不该活着。}<刀锋轻鸣、药戥轻响、压低呼吸>",
        "镜头2【4.9-14.0秒，近特写平滑侧移后回到双人近景】陈迹抬起右手食指，在喉前生成半透明蓝色弧形光幕；短刃撞上光幕，接触点泛起蓝色同心涟漪并沿刀身结霜。刺客咬牙推刀，弧面轻微形变后恢复并把反作用力震回手腕，刀锋始终无法穿透；陈迹从容侧目，刺客由惊疑转为惊惧。{无对白}<低沉能量共振、光幕涟漪、金铁结霜细裂、手腕受震、短促呼吸>",
        "【连续物理动作脚本】",
        *beat_lines,
        "【单一状态源】短刃从0到14秒始终由刺客右手握持。陈迹只用右食指生成并维持喉前蓝色弧形光幕，绝不接管刀柄、挥刀或把刀指向刺客。光幕始终位于刀锋与陈迹皮肤之间，刀锋不得穿透光幕。所有文本、动作、法术、表情和终态以本段规则为唯一真源。",
        "【声音】保留@音频1对白；补充刀锋余响、药戥轻响、蓝色光幕低沉共振、碰撞涟漪、金铁结霜细裂、刺客手腕受震和两人呼吸；禁止BGM、旁白、额外对白。",
        "【负面约束】禁止字幕、水印、Logo、可读文字；禁止额外人物、换脸、分身、融肢、穿模、刀具归属跳变、瞬移、腾空、循环、慢放、停帧和周期重复；禁止光幕出现在人物身后、禁止光幕变成实体盾牌、禁止刀锋穿过光幕或皮肤、禁止陈迹抓刀。",
    ]) + "\n"
    PROMPT.write_text(prompt, encoding="utf-8")
    task = {
        "task_key": "E30-CW-U01-PERFORMANCE-R2",
        "source_id": "E30-CW-U01", "tool_type": "video_generation",
        "generation_mode": "performance_generation", "still_sequence_only_allowed": True,
        "audio_reference_optional": False, "native_dialogue_required": True,
        "episode": "E30", "batch_id": "E30-U01-PERFORMANCE-R2",
        "unit_id": "E30-CW-U01", "scene_id": "E30-CW-S01-MEDICAL-BACK-HALL-ATTACK",
        "visual_zone": "E30-CW-U01",
        "duration": 14, "duration_seconds": 14, "model": "seedance-2.0-pro",
        "duration_plan": {
            "policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 14,
            "rationale": "Exact sum of the first two contiguous Claude-script editorial shots.",
            "edit_policy": "End when the frozen-blade action result lands; never pad, slow or loop.",
        },
        "aspect_ratio": "9:16", "resolution": "720p",
        "prompt_file": relative(PROMPT), "prompt_sha256": sha256(PROMPT),
        "reference_images": [relative(ANCHOR)],
        "reference_image_sequence": [{
            "asset_label": "@图片1", "role": "IDENTITY_SCENE_AND_INITIAL_CONTACT_ANCHOR",
            "path": relative(ANCHOR), "sha256": sha256(ANCHOR),
        }],
        "state_reference_minimum": 1, "planned_reference_image_count": 1,
        "inherits_establishing_coverage": True,
        "action_unit": True, "performance_spec": spec,
        "keyframe_interpolation_gate": {
            "status": "PASS", "anchor_count": 1,
            "decision": "NOT_APPLICABLE_SINGLE_IDENTITY_SCENE_ANCHOR",
            "checked_adjacent_pairs": 0,
            "rejected_candidate": "E30-CW-S01-SH02-C3",
            "reason": "Rejected because it transfers the short blade from the assassin to Chenji, contradicting script prop ownership.",
        },
        "dialogue": [{
            "dia_id": "E30-DIA-001", "speaker": "刺客",
            "spoken_text": "名单上有你。今夜，你不该活着。",
        }],
        "reference_audios": [relative(AUDIO)],
        "dialogue_audio_assets": [{
            "dia_id": "E30-DIA-001", "speaker": "刺客",
            "spoken_text": "名单上有你。今夜，你不该活着。",
            "audio_slot": "@音频1", "path": relative(AUDIO), "sha256": sha256(AUDIO),
            "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE",
        }],
        "dialogue_audio_coverage": {"required": 1, "bound": 1, "status": "PASS"},
        "source_spec": relative(SPEC), "source_spec_sha256": sha256(SPEC),
        "workflow_credit_scope": "e30_claude_writer_v1_20260722",
        "status": "READY_TO_SUBMIT",
    }
    task["generation_fingerprint"] = generation_fingerprint(task)
    config = {
        "schema": "qingshan.episode_parallel_batch.config.v1", "episode": "E30",
        "status": "READY_SINGLE_UNIT_PERFORMANCE_REGEN", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "targeted_unit_replacement": True,
        "concurrency": 1, "max_retries": 0,
        "retry_policy": "CHANGED_GENERATION_INPUT_APPROVED_BY_USER",
        "workflow_credit_scope": "e30_claude_writer_v1_20260722", "video_credit_limit": 6000,
        "source_script_sha256": "83e11239b286b926ec736d304aa91722632ebd1ab4bdb1adae3102a09c34e2a2",
        "writer_agent_provenance": {
            "status": "PASS", "provenance_type": "claude_writer_script",
            "source_script": "workflow/claude_writer_agent/scripts/E30剧本_ClaudeWriter_v1.md",
            "source_script_sha256": "83e11239b286b926ec736d304aa91722632ebd1ab4bdb1adae3102a09c34e2a2",
            "production_manifest": "workflow/claude_writer_agent/production/e30_claude_writer_v1_20260722/E30_PRODUCTION_MANIFEST.json",
            "production_manifest_sha256": "7602ba22511db955ac68511482f6d7eec6182d255a11df2948da61ce5e34af26",
        },
        "scene_contract_ref": "workflow/claude_writer_agent/production/e30_claude_writer_v1_20260722/E30_SCENE_AUTHORITY_STATE_V1.json",
        "supervisor_script_gate_required": False,
        "output_dir": relative(BASE / "outputs"), "qa_dir": relative(BASE / "qa"),
        "tasks": [task],
    }
    CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"config": relative(CONFIG), "prompt": relative(PROMPT), "spec": relative(SPEC), "fingerprint": task["generation_fingerprint"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
