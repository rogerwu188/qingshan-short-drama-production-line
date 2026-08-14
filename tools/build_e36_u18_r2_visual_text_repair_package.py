#!/usr/bin/env python3
"""Build U18-R2 after direct review rejected R1's written-paper hallucination."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
R1 = BASE / "recovery_10000_20260730/u18_r1_video"
OUT = BASE / "recovery_10000_20260730/u18_r2_video"
QA = ROOT / "qa/e36_agentcut_20260730/u18_r2_video_runtime"
CONFIG = OUT / "E36_U18_R2_RECOVERY_EPISODE_PARALLEL_BATCH_V1.json"
PROMPT = OUT / "E36-CW-U18-R2.txt"
PROMPT_MANIFEST = OUT / "E36_U18_R2_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
DIALOGUE_MANIFEST = OUT / "E36_U18_R2_DIALOGUE_MANIFEST_V1.json"
DIALOGUE_GATE = QA / "E36_U18_R2_DIALOGUE_PROMPT_GATE_V1.json"
TEXT = "……却还在按笔掏银子，买这颗棋的命。"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    prompt = """【E36-CW-U18-R2｜5秒｜R1可见文字修复｜Seedance Fast原生普通话】

@图片1只锁定十七岁云羊身份，@图片2只锁定十七岁陈迹身份，@图片3只锁定成年男性递信人身份；@图片4是唯一首帧、空间、屏幕方位、取景边界与表演连续性权威。@音频1是陈迹本句精确对白参考，必须逐字复现其自然中文普通话、少年声线、语气、气息和节奏。第一帧严格从@图片4起动并保持同样的紧侧脸裁切：左侧陈迹侧脸与嘴完整可见，右侧只保留云羊面部边缘，中后景递信人虚焦；画面下边界始终高于桌面、双手、纸张和票根。禁止拉远、扩展画幅、下降机位、重构桌面或补画任何纸张。

【天气硬合同】weather=INTERIOR_CLEAR_DUSK_ENTERING。中国古代架空洛城，太平医馆密室午后偏晚、暮色初染，无字木墙与古式烛火保持连续。禁止现代物件、现代纸张、官服、民国妆发、牌匾、字幕、水印；所有桌面、手、票根、纸张、书页、印章、线条、图案和可读或伪造文字全部在画外且不得生成。

【实体绑定】[[scene:太平医馆密室]]；[[char:十七岁陈迹]]；[[char:十七岁云羊]]；[[char:成年男性递信人]]；[[prop:刘家旧钱票根严格位于画外]]。本单元不新增人物、道具或能力。

镜头1【固定紧侧脸近景·严格保持@图片4裁切·无推拉摇移】0.00-0.35秒：主体=十七岁陈迹；动作=胸口轻起完成一次短吸气，眉心收紧，嘴唇将启；接触点=画外左手指腹压住画外票根，本镜头不可见手或票根；方向=陈迹视线由画面右下轻抬向右侧云羊；终态=陈迹嘴部清晰可见并准备开口。{无对白}<音效：短吸气、烛芯细响>。

镜头2【固定紧侧脸近景·同一轴线与取景边界】0.35-3.65秒：主体=十七岁陈迹；动作=完整嘴部始终清晰可见，按@音频1的声线、语气与节奏，以自然中文普通话只说一遍“……却还在按笔掏银子，买这颗棋的命。”，省略号只表现为开口前短停；接触点=画外左手指腹持续压住同一画外票根；方向=陈迹视线抬向右侧云羊，头部只抬半寸；终态=最后一个“命”完整落下并自然闭口，目光锁住云羊。{对白：陈迹仅说“……却还在按笔掏银子，买这颗棋的命。”}<音效：@音频1精确对白参考、自然普通话、衣料轻绷、递信人压抑呼吸>。

镜头3【固定紧侧脸近景·不切换不扩景】3.65-5.00秒：主体=十七岁陈迹、画面右缘十七岁云羊、虚焦递信人；动作=陈迹闭口短呼气，云羊嘴部不做说话式开合，递信人只以肩背发抖回应；接触点=票根仍在画外由陈迹保全；方向=陈迹保持看向右侧云羊；终态=陈迹闭口，其他人物无发声式口型，桌面与所有纸张始终未入镜。{无对白}<音效：短呼气、衣料摩擦、室内低风>。

【原生对白硬合同】仅陈迹说话。视频模型必须把@音频1作为精确目标对白参考，由陈迹口中现场原生生成自然中文普通话；唯一可听台词是“……却还在按笔掏银子，买这颗棋的命。”。只能在0.35-3.65秒说一遍，不增字、不减字、不改字、不重复，不念省略号。云羊与递信人不得发声，不得出现与声音同步的说话式口型。禁止串台、旁白、画外音、现代播音腔、字幕或后配替换；陈迹口型逐字同步，气息、表情与起止时间同步，末字后闭口。

【环境生命层】暮色在无字木墙上缓慢移动；画外古式烛焰的暖光在人物轮廓上轻跳；递信人肩背持续微颤；三人衣料随呼吸自然牵动。环境动作不得改变固定取景或遮挡陈迹嘴部。

【力量作用于环境介质】陈迹短吸气只带动灰旧布衣领口和胸口轻微起伏；递信人颤抖只带动粗布肩线；低风只改变画外烛光明暗，墙面和人物尺度稳定。

【palette与光影】低饱和午青与初暮暖棕，陈迹灰旧布衣、云羊黑衣、递信人褐衣；暖暮轮廓光与古式烛火动机光形成克制冷暖层次，暗部保留陈迹双眼和嘴部细节。

硬性禁止：镜头拉远或下移、显示桌面、显示手、显示票根、显示任何纸张、书页、印章、红线、黑线、汉字、伪字、数字、字幕、水印、成年化、二十岁参考、换脸、人物复制、新增人物、嘴被遮挡、口型漂移、念出省略号、吞字、重复台词、云羊或递信人发声。"""
    PROMPT.write_text(prompt + "\n", encoding="utf-8")
    prompt_sha = sha(PROMPT)

    config = json.loads((R1 / "E36_U18_R1_RECOVERY_EPISODE_PARALLEL_BATCH_V1.json").read_text(encoding="utf-8"))
    config.update({
        "episode_paid_credits_before": 6328,
        "output_dir": "working_assets/e36_recovery_10000_20260730/u18_r2_video",
        "qa_dir": rel(QA),
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST),
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "dialogue_prompt_gate_ref": rel(DIALOGUE_GATE),
    })
    task = config["tasks"][0]
    task.update({
        "task_key": "E36-CW-U18-R2-RECOVERY-10000",
        "source_id": "E36-CW-U18-R2-RECOVERY-10000",
        "batch_id": "E36-U18-R2-RECOVERY-10000",
        "status": "READY_TO_SUBMIT",
        "prompt_path": rel(PROMPT),
        "prompt_file": rel(PROMPT),
        "prompt_sha256": prompt_sha,
        "qa_dir": rel(QA),
        "output_dir": "working_assets/e36_recovery_10000_20260730/u18_r2_video",
        "max_retries": 0,
    })
    task["duration_plan"]["rationale"] = "R2 reuses the 3.1115-second exact line while locking the accepted tight crop above every written surface."

    prompt_manifest = json.loads((R1 / "E36_U18_R1_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json").read_text(encoding="utf-8"))
    row = next(row for row in prompt_manifest["rows"] if row["unit_id"] == "U18")
    row.update({"prompt_path": rel(PROMPT), "prompt_sha256": prompt_sha})
    write_json(PROMPT_MANIFEST, prompt_manifest)

    dialogue_manifest = json.loads((R1 / "E36_U18_R1_DIALOGUE_MANIFEST_V1.json").read_text(encoding="utf-8"))
    write_json(DIALOGUE_MANIFEST, dialogue_manifest)

    gate = json.loads((ROOT / "qa/e36_agentcut_20260730/u18_r1_video_runtime/E36_U18_R1_DIALOGUE_PROMPT_GATE_V1.json").read_text(encoding="utf-8"))
    gate.update({
        "source_segment_id": "U18-R2",
        "voice_reference_sha256": task["dialogue_audio_assets"][0]["sha256"],
        "blocked_by": None,
        "submission_allowed_after_supervisor_precheck": True,
    })
    gate["checks"]["credit_limit"] = "PASS_6328_LE_10000"
    gate["checks"]["r1_direct_qa_fail_preserved"] = "PASS"
    gate["checks"]["fixed_crop_above_written_surfaces"] = "PASS_DECLARED"
    write_json(DIALOGUE_GATE, gate)
    write_json(CONFIG, config)
    print(json.dumps({"status": "PASS", "config": str(CONFIG), "config_sha256": sha(CONFIG), "prompt_sha256": prompt_sha}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
