#!/usr/bin/env python3
"""Materialize E37's failed prompt design and corrected atomic replacement plan."""

from __future__ import annotations

import json
from pathlib import Path

from action_shot_design_gate import contract_sha256, prompt_marker


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa/e37_agentcut_20260803/direct_motion_audit_20260803"
PROMPTS = ROOT / "working_assets/e37_prompt_repair_20260803/compiled_prompts_v1"
OLD_PLAN = QA / "E37_V1_PROMPT_COMPOSITION_BACKTEST_PLAN_V1.json"
NEW_PLAN = QA / "E37_V3_ATOMIC_ACTION_AND_OPENING_REPAIR_PLAN_V1.json"


def non_action(
    shot_id: str,
    beats: list[str],
    family: str,
    entry: str,
    exit_state: str,
    *,
    group: str = "OPENING",
) -> dict:
    return {
        "shot_id": shot_id,
        "action_unit": False,
        "visual_tier": "CORE",
        "information_beats": beats,
        "camera": {"family": family, "moves": []},
        "primary_contacts": [],
        "result_read_seconds": 0.0,
        "reset_or_replay_allowed": False,
        "continuity_group": group,
        "entry_state_token": entry,
        "exit_state_token": exit_state,
    }


def action(
    shot_id: str,
    beat: str,
    family: str,
    axis: str,
    direction: str,
    entry: str,
    exit_state: str,
    contract: dict,
) -> dict:
    return {
        "shot_id": shot_id,
        "action_unit": True,
        "visual_tier": "CORE",
        "information_beats": [beat],
        "camera": {
            "family": family,
            "moves": [],
            "axis": axis,
            "screen_direction": direction,
            "contact_readable": True,
        },
        "primary_contacts": [contract],
        "result_read_seconds": 0.55,
        "reset_or_replay_allowed": False,
        "continuity_group": "FIRE_ESCAPE",
        "entry_state_token": entry,
        "exit_state_token": exit_state,
    }


def corrected_plan() -> dict:
    shots = [
        non_action(
            "E37-R-O01",
            ["地契与看守账同框，霜纹只揭示每月看守银这一条新证据"],
            "locked_object_detail",
            "OPEN_00_LEDGER_CLOSED_CHENJI_HAND_ABOVE_PAGE",
            "OPEN_01_LEDGER_OPEN_WATCH_SILVER_REVEALED",
        ),
        non_action(
            "E37-R-O02",
            ["陈迹侧脸低声确认死者仍在领钱"],
            "locked_profile_dialogue",
            "OPEN_01_LEDGER_OPEN_WATCH_SILVER_REVEALED",
            "OPEN_02_CHENJI_GAZE_ON_LEDGER_FINGER_AT_ENTRY",
        ),
        non_action(
            "E37-R-O03",
            ["皎兔阴神从里屋返回并报告热茶与牌位"],
            "over_shoulder_return",
            "OPEN_02_CHENJI_GAZE_ON_LEDGER_FINGER_AT_ENTRY",
            "OPEN_03_JIAOTU_RETURNED_CHENJI_TURNS_TO_HER",
        ),
        non_action(
            "E37-R-O04",
            ["陈迹识认拆日期规矩，反应只落在呼吸与指节"],
            "locked_reaction_closeup",
            "OPEN_03_JIAOTU_RETURNED_CHENJI_TURNS_TO_HER",
            "OPEN_04_LEDGER_IN_CHENJI_HANDS_GROUP_ALERTED",
        ),
        action(
            "E37-R-A01",
            "外部暗桩掷入的火把点燃灯油，封住正门退路",
            "locked_low_contact",
            "正屋门口横轴，人物始终在轴线内侧",
            "火把由画面右上落向左下，火线沿地面向右扩展",
            "FIRE_00_GUARD_LUNGING_LEDGER_HELD_TORCH_AIRBORNE",
            "FIRE_01_OIL_IGNITED_GUARD_ONE_STEP_FROM_CHENJI",
            {
                "pre_state": "火把在半空，灯油地面尚未着火，守宅人正扑向陈迹手中账册",
                "actor": "宅外暗桩掷入的火把",
                "action": "落向门内灯油",
                "contact_point": "火把头撞上门内右侧灯油地面",
                "force_direction": "由右上向左下落地，火线贴地向右侧退路扩展",
                "force_feedback": "火把弹停，灯油瞬间轰燃，守宅人与陈迹被橙光照亮",
                "result_state": "门口火线已起，守宅人距陈迹一步，账册仍在陈迹手中",
            },
        ),
        action(
            "E37-R-A02",
            "陈迹侧避后冰屏截停守宅人，守宅人明确撞退",
            "locked_side_contact",
            "陈迹至守宅人左到右横轴，严禁越轴",
            "守宅人由左向右扑，冰屏在两者之间竖起，反作用把他推回左侧",
            "FIRE_01_OIL_IGNITED_GUARD_ONE_STEP_FROM_CHENJI",
            "FIRE_02_GUARD_RECOILED_ICE_SCREEN_UP_BEAM_CRACKING",
            {
                "pre_state": "门口火线已起，守宅人左肩向前扑账，陈迹右脚正侧移",
                "actor": "守宅人",
                "action": "扑空后肩胸撞上陈迹升起的薄冰屏",
                "contact_point": "守宅人左肩与冰屏中心",
                "force_direction": "守宅人由左向右，冰屏反力由右向左",
                "force_feedback": "冰屏震出裂纹和白汽，守宅人上身折回半步",
                "result_state": "守宅人退在画面左侧，冰屏仍立，右上方燃梁开始开裂",
            },
        ),
        action(
            "E37-R-A03",
            "纸人双掌承住坠落火梁，为三人保住逃生空间",
            "locked_front_contact",
            "正对东厢梁架的纵深轴，纸人居中，人物在其后",
            "火梁由上向下，纸人双臂由下向上，严禁横向摇镜",
            "FIRE_02_GUARD_RECOILED_ICE_SCREEN_UP_BEAM_CRACKING",
            "FIRE_03_BEAM_SUPPORTED_PAPER_BURNING_WALL_VISIBLE",
            {
                "pre_state": "燃梁已断并向三人头顶下坠，纸人双臂尚低于梁底",
                "actor": "云羊点睛唤出的巨幅纸人",
                "action": "双臂上举迎住坠梁",
                "contact_point": "纸人双掌与燃梁下沿中央",
                "force_direction": "燃梁向下，纸人双臂向上",
                "force_feedback": "纸人肘部下沉、双脚后滑，纸面从掌缘开始燃穿",
                "result_state": "燃梁停在头顶，纸人撑住但正在燃烧，右后方酥墙清晰可见",
            },
        ),
        action(
            "E37-R-A04",
            "云羊一拳击穿烧酥土墙，形成唯一逃生缺口",
            "locked_three_quarter_contact",
            "云羊与东墙的左到右攻击轴，纸人承梁保持背景连续",
            "拳由左向右，墙体碎屑继续向右外侧飞散",
            "FIRE_03_BEAM_SUPPORTED_PAPER_BURNING_WALL_VISIBLE",
            "FIRE_04_WALL_OPEN_EXIT_VISIBLE_BEAM_STILL_SUPPORTED",
            {
                "pre_state": "纸人仍在后景撑梁，云羊左脚踏稳，右拳收在肋侧，酥墙完整",
                "actor": "云羊",
                "action": "右拳直击烧酥土墙",
                "contact_point": "云羊右拳拳面与土墙胸口高度中心",
                "force_direction": "由左向右贯穿墙体",
                "force_feedback": "拳面停在破口边，土块向屋外飞，云羊肩背前压",
                "result_state": "墙上形成一人宽缺口并露出雨夜，纸人仍在后景撑梁",
            },
        ),
        action(
            "E37-R-A05",
            "陈迹把看守账抛给皎兔阴神，阴神双手接稳",
            "locked_handoff_medium",
            "陈迹到阴神的左到右交接轴，与墙洞方向一致",
            "账册由左向右飞入阴神双手，接住后继续朝墙洞方向",
            "FIRE_04_WALL_OPEN_EXIT_VISIBLE_BEAM_STILL_SUPPORTED",
            "FIRE_05_LEDGER_IN_SPIRIT_HANDS_CHENJI_TURNS_TO_FLOOR",
            {
                "pre_state": "墙洞已开，陈迹左手持焦边账册，皎兔阴神在右侧张开双手",
                "actor": "陈迹",
                "action": "将账册平抛给皎兔阴神",
                "contact_point": "账册书脊落入阴神双掌",
                "force_direction": "由左向右，朝墙洞逃生方向",
                "force_feedback": "阴神双臂随账册后撤半尺并立刻抱紧胸前",
                "result_state": "账册已由阴神护住，陈迹空手转向脚下开裂地板",
            },
        ),
        action(
            "E37-R-A06",
            "陈迹冰流封住开裂地板，暂时撑出最后三步",
            "locked_floor_contact",
            "墙洞至屋内的纵深逃生轴，镜头保持低位固定",
            "冰流由屋内前景向墙洞方向延伸，裂缝停止反向扩展",
            "FIRE_05_LEDGER_IN_SPIRIT_HANDS_CHENJI_TURNS_TO_FLOOR",
            "FIRE_06_FLOOR_FROZEN_EXIT_LANE_STABLE_GROUP_READY",
            {
                "pre_state": "账册已在阴神手中，陈迹右掌贴近开裂地板，裂缝朝墙洞延伸",
                "actor": "陈迹释放的冰流",
                "action": "贴地追上裂缝并封住松动木板",
                "contact_point": "冰流前缘与墙洞前最后一块翘起地板",
                "force_direction": "由屋内向墙洞推进并向两侧锁紧木板",
                "force_feedback": "翘起木板压回原位，裂缝停止，霜纹横向咬合",
                "result_state": "三步宽冰封通道稳定，三人面向墙洞准备通过",
            },
        ),
        action(
            "E37-R-A07",
            "三人沿冰封通道依次穿过墙洞落到雨地",
            "locked_exit_profile",
            "墙洞内外横轴，人物只能由左向右离开火宅",
            "三人依次由左向右，落地后不得回到屋内位置",
            "FIRE_06_FLOOR_FROZEN_EXIT_LANE_STABLE_GROUP_READY",
            "FIRE_07_GROUP_OUTSIDE_LEDGER_SAFE_HOUSE_STILL_UP",
            {
                "pre_state": "冰封通道已稳，墙洞在右，皎兔阴神护账先行，陈迹和云羊紧随",
                "actor": "陈迹、皎兔、云羊三人",
                "action": "依次冲过墙洞并滚落雨地",
                "contact_point": "三人手掌与膝部先后触及墙外湿地",
                "force_direction": "持续由左向右离开火宅",
                "force_feedback": "湿泥溅起，三人顺势滚停，阴神始终把账册护在上方",
                "result_state": "三人都在屋外右侧，账册安全，燃屋尚未总塌",
            },
        ),
        action(
            "E37-R-A08",
            "刘宅屋架向内总塌并吞没未逃出的守宅人",
            "locked_wide_collapse",
            "屋外正面固定轴，三人在右前景，屋架在左后景",
            "屋架垂直向内下塌，三人保持屋外位置不逆行",
            "FIRE_07_GROUP_OUTSIDE_LEDGER_SAFE_HOUSE_STILL_UP",
            "FIRE_08_HOUSE_COLLAPSED_GROUP_SAFE_GUARD_LOST",
            {
                "pre_state": "三人在雨地右前景回望，燃屋屋架仍立，守宅人影停在门内",
                "actor": "烧断的刘宅主屋架",
                "action": "整体向内坍塌",
                "contact_point": "主屋架砸入门内燃烧地面与守宅人所在区域",
                "force_direction": "垂直向下并向屋心内收",
                "force_feedback": "火星与雨汽向上爆开，屋顶轮廓彻底消失，三人被冲击风压低身",
                "result_state": "刘宅塌成雨中火海，三人在屋外，账册仍在，守宅人未能出来",
            },
        ),
    ]
    return {
        "schema": "qingshan.action_shot_design_plan.v1",
        "episode": "E37",
        "source_script_sha256": "07a63a0c286be656feac59a0f31ea1bb159f3f7ce56f1172bb202832edf9db3a",
        "source_manifest_sha256": "9082f9d3b45bf0466476e98cb194d91d00d6775c2b762b5253c8f7557d31c33e",
        "maximum_information_beats_per_shot": 2,
        "maximum_camera_family_share": 0.35,
        "maximum_consecutive_camera_family": 2,
        "shots": shots,
    }


def old_failed_plan() -> dict:
    rows = []
    for index in range(1, 7):
        rows.append(
            non_action(
                f"E37-OLD-OVERHEAD-{index}",
                ["同一人物组再次从高位显露", "重复前一镜构图", "再追加一条对白或证据"],
                "camera.overhead_reveal",
                f"OLD_{index}_ENTRY",
                f"OLD_{index}_EXIT",
                group=f"OLD_OPEN_{index}",
            )
        )
    overloaded = action(
        "E37-OLD-U05-S2",
        "火梁落下、纸人承梁、纸面燃烧、云羊拳开墙、三人开始逃离",
        "camera.domino_chain",
        "未锁定",
        "未锁定",
        "OLD_ACTION_ENTRY",
        "OLD_ACTION_EXIT",
        {
            "pre_state": "火梁下落",
            "actor": "纸人和云羊",
            "action": "承梁并击墙",
            "contact_point": "梁与纸人、拳与墙",
            "force_direction": "多个方向",
            "force_feedback": "多个反馈",
            "result_state": "墙开并开始逃离",
        },
    )
    overloaded["visual_tier"] = "NON_CORE"
    overloaded["information_beats"] = ["梁落", "纸人承梁", "云羊开墙", "三人逃离"]
    overloaded["primary_contacts"].append(
        {
            "pre_state": "墙完整",
            "actor": "云羊",
            "action": "击墙",
            "contact_point": "拳与墙",
            "force_direction": "向外",
            "force_feedback": "墙碎",
            "result_state": "墙开",
        }
    )
    overloaded["result_read_seconds"] = 1.2
    rows.append(overloaded)
    return {
        "schema": "qingshan.action_shot_design_plan.v1",
        "episode": "E37",
        "maximum_information_beats_per_shot": 2,
        "maximum_camera_family_share": 0.35,
        "maximum_consecutive_camera_family": 2,
        "shots": rows,
    }


def compile_prompt(shot: dict) -> str:
    contact = shot["primary_contacts"][0]
    camera = shot["camera"]
    return "\n".join(
        [
            prompt_marker(shot),
            f"镜头编号：{shot['shot_id']}。单一连续镜头，实速，禁止慢镜、插帧、回放或动作重置。",
            f"本镜唯一信息：{shot['information_beats'][0]}。本镜不得提前表现下一镜事件。",
            f"入场状态必须逐项成立：{contact['pre_state']}。",
            f"唯一主动作：{contact['actor']}{contact['action']}。",
            f"唯一接触点必须清楚可见：{contact['contact_point']}。",
            f"力向：{contact['force_direction']}；受力反馈：{contact['force_feedback']}。",
            f"出场状态必须保持至少{shot['result_read_seconds']:.2f}秒：{contact['result_state']}。",
            f"动作轴：{camera['axis']}；屏幕方向：{camera['screen_direction']}。",
            f"机位族：{camera['family']}，固定机位，无摇摆、无环绕、无无动机推拉。",
            f"连续性令牌：{shot['entry_state_token']} -> {shot['exit_state_token']}。",
            "环境生命层只允许雨、火、白汽、碎屑响应主接触；不得用镜头运动代替动作，不得生成字幕、水印或可读文字。",
        ]
    ) + "\n"


def main() -> int:
    QA.mkdir(parents=True, exist_ok=True)
    PROMPTS.mkdir(parents=True, exist_ok=True)
    old = old_failed_plan()
    new = corrected_plan()
    OLD_PLAN.write_text(json.dumps(old, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for shot in new["shots"]:
        shot["action_design_contract_sha256"] = contract_sha256(shot)
        if shot["action_unit"]:
            prompt_path = PROMPTS / f"{shot['shot_id']}.txt"
            prompt_path.write_text(compile_prompt(shot), encoding="utf-8")
            shot["compiled_prompt_path"] = str(prompt_path.relative_to(ROOT))
    NEW_PLAN.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "old_plan": str(OLD_PLAN),
        "corrected_plan": str(NEW_PLAN),
        "corrected_shots": len(new["shots"]),
        "compiled_action_prompts": sum(row["action_unit"] for row in new["shots"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
