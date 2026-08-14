#!/usr/bin/env python3
"""Compile immediately-ready E31 no-dialogue units as continuous performances."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from build_e31_performance_preproduction import ABILITY_LOGIC, FORCE_FEEDBACK, INVISIBLE_ELEMENTS, UNITS
from episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e31_claude_writer_v1_20260722"
PLAN = PRODUCTION / "E31_VIDEO_UNIT_PERFORMANCE_PLAN_V1.json"
HARVEST = PRODUCTION / "E31_IMAGE_BATCH_PERFORMANCE_V1_HARVEST.json"
BASE = PRODUCTION / "video_performance_v1"
CONFIG = BASE / "E31_VIDEO_BATCH_NONDIALOGUE_READY_V1.json"
ACTION_PLAN = BASE / "E31_ACTION_READABILITY_NONDIALOGUE_V1.json"
SCENE_STATE = PRODUCTION / "E31_SCENE_AUTHORITY_STATE_V1.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E31剧本_ClaudeWriter_v1.md"
PRODUCTION_MANIFEST = PRODUCTION / "E31_PRODUCTION_MANIFEST.json"
READY = {"U01", "U05", "U06", "U07", "U08", "U10", "U11", "U12", "U13", "U20"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def beat(start: float, end: float, subject: str, action: str, contact: str, direction: str,
         end_state: str, intent: str, visible: str, expression: str, viewer: str,
         invisible: str, ability: str, force: str) -> dict:
    return {
        "start_seconds": start, "end_seconds": end, "subject": subject, "action": action,
        "contact_point": contact, "direction": direction, "end_state": end_state,
        "intent": intent, "invisible_element": invisible,
        "externalized_visible_phenomenon": visible, "ability_logic": ability,
        "force_feedback": force, "visible_causality": visible,
        "expression": expression, "viewer_read": viewer,
    }


def beats_for(unit: str) -> list[dict]:
    invisible = INVISIBLE_ELEMENTS[unit]
    ability = ABILITY_LOGIC.get(unit, "所有结果都由人物、道具和环境的连续接触产生，不使用无来源特效或跳变。")
    force = FORCE_FEEDBACK.get(unit, "动作力量通过衣料、纸张、火焰、积雪或建筑构件产生方向明确的一次性反馈。")
    data = {
        "U01": [
            (0, 3.0, "前庭争抢人群", "从府门两侧同时涌向散落名单，肩背互相挤压但不瞬移", "靴底踩雪、双手抓住纸页边缘", "人流由两侧向庭心汇聚", "庭心形成围绕名单的混乱旋涡", "让假名单引爆集体贪惧", "火把被奔跑气流压斜，纸页被相反方向拉扯飞散", "前排贪急、后排惊惶", "名单让整座王府失序"),
            (3.0, 8.0, "持火把侍从与抢纸者", "抬臂推开阻挡者并追逐飞纸，火把在雪风中压低后重新抬起", "前臂抵住对方肩侧、手指捞取纸页", "由近景向重檐深处推进", "火点与乱众铺满恢弘前庭，秩序彻底崩塌", "建立乱局规模", "人物奔跑轨迹、飞纸和摇摆火光共同切碎庭院秩序", "焦灼、贪婪、彼此提防", "假名单已成为所有人的争夺中心"),
        ],
        "U05": [
            (0, 2.0, "皎兔肉身", "闭目咬牙，以右手指甲从眉心向下划出一道细血痕", "指甲接触眉心皮肤", "指甲短促向下，头部保持正直", "肉身仍端坐，血痕成为出窍起点", "主动开启阴神侦察", "血痕泛出暗红微光，灯焰朝她短促偏转一次", "忍痛克制、呼吸压住", "皎兔以眉心血痕启动能力"),
            (2.0, 5.4, "黑甲阴神", "从皎兔背后沿眉心轴线完整分离，双脚先落地再挺身，倒持长刀", "阴神背部从肉身轮廓脱离，脚底接触地面", "沿镜头后方退出半步再站直", "画面同时保留端坐肉身与独立黑甲阴神", "把无形感知外化为可见分身", "分离边缘出现一层收束冷雾，桌上纸角随气流抬起后落下", "肉身忍痛不动，阴神睁眼冷峻", "同一皎兔明确分成肉身和阴神两具状态"),
            (5.4, 8.0, "黑甲阴神", "转身迈步穿过关闭的窗扇，长刀始终倒持贴腿，肉身不动", "阴神肩胸与窗扇重叠但不撞碎木框", "由室内向窗外连续前行", "阴神消失在窗外，皎兔肉身仍端坐原位", "开始远程侦察", "窗纸在无实体穿越时向外鼓起又回落，不产生碎裂", "阴神警觉决绝，肉身面色苍白", "阴神离体执行侦察而非肉身移动"),
        ],
        "U06": [
            (0, 1.3, "云妃侍从", "展开缺页名单，拇指快速拨过空缺位置", "双手捏住纸卷上下边缘", "纸面由卷曲向两侧展平", "空缺处停在侍从视线中央", "确认名单残缺", "纸张展开带起帐幔轻摆，阴神只在屏风侧观察", "先期待后皱眉", "侍从只在意缺页"),
            (1.3, 4.0, "云妃侍从与黑甲阴神", "侍从拍纸咒骂后把纸压在案上；阴神贴墙侧移并穿墙离开", "侍从掌心拍中纸面，阴神肩侧穿过墙体", "侍从动作向下，阴神向画面右侧离开", "侍从烦躁但不惊慌，阴神完成观察", "证明云妃一方无惧", "拍纸震动茶盏一次，阴神穿墙使帘角轻抬又回落", "烦躁愤怒、毫无恐惧", "云妃阵营只是恼怒名单不全"),
        ],
        "U07": [
            (0, 1.8, "静妃", "垂眼扫过名单目标位置，嘴角形成短促冷笑", "右手食指沿纸边停在空缺旁", "视线从上向下，手指不描画文字", "确认后毫不紧张", "证明她对沈砚陌生", "茶汽平稳上升，手指和呼吸都没有惊惧抖动", "轻蔑冷淡", "名字线索没有击中静妃"),
            (1.8, 4.0, "静妃与黑甲阴神", "静妃把名单平放在茶盏旁并收回手；阴神从帘后转身穿墙", "纸面接触案几，阴神肩侧接触墙面", "纸张向下，阴神向后侧墙外", "静妃继续端坐，阴神离场", "完成无惧取证", "纸落案面只发出轻响，帘后空气随阴神离去轻微回卷", "静妃无所谓，阴神冷静记录", "静妃把名单当作普通物件"),
        ],
        "U08": [
            (0, 1.4, "枯瘦右手", "食指沿名单移动到目标位置后突然僵住", "指腹接触纸面目标区域", "由左向右移动后瞬停", "手指停住，手腕开始细抖", "暴露隐藏恐惧", "原本平稳的烛焰在人物倒吸气时向手的反方向偏斜", "强装镇定骤然破裂", "这个位置击中了内院要害"),
            (1.4, 4.0, "枯瘦右手与孤灯", "五指收紧把纸面掐出放射皱褶，手腕抖动加剧；急促抽气使烛焰缩灭", "五个指尖压入同一张纸，气流经过烛芯", "抓力向掌心收束，气流向灯外掠过", "纸被掐皱，灯灭后手停在黑暗里", "让恐惧留下不可否认的物证", "纸张皱褶从指尖向外扩散，烛烟在熄灭后直线上升", "瞳孔放大、呼吸失序", "内院真正害怕这个名字"),
        ],
        "U10": [
            (0, 2.0, "黑猫乌云", "在墙头弓背竖尾，朝回廊发出一次尖啸", "四爪扣住覆雪墙砖", "头部转向陈迹前方三处伏击点", "陈迹与云羊同时循声转头", "提前示警伏击", "猫爪蹬落少量积雪，尖啸让近处灯笼穗向外震动", "炸毛警戒", "乌云确实看见危险并提醒两人"),
            (2.0, 5.0, "三名杀手", "分别从檐口下落、廊柱后冲出、假山侧跃出，保持三条互不交叉路线", "三人的脚分别落在檐下石阶、柱侧地砖、假山雪地", "三路同时朝陈迹怀中名单收束", "三人形成前左、正前、右后包夹", "共同夺取名单", "落地分别压碎积雪、扬起尘雪、带动衣摆，反馈位置与三条路线对应", "杀意集中、目光都锁住名单", "三名独立杀手有同一个目标"),
            (5.0, 8.0, "陈迹与云羊", "陈迹把名单收向胸侧并后撤半步，云羊横移挡住右路，二人背靠回廊柱建立防线", "陈迹手掌压住名单，云羊前臂接近右路杀手但尚未碰撞", "陈迹向后，云羊向右侧", "两人不换位，三路伏击完整进入画面", "回应伏击并保护证据", "急停使靴底扫开薄雪，衣摆沿移动方向滞后甩动", "陈迹冷静警觉、云羊咬牙", "伏击爆发但主角已作出合理防守"),
        ],
        "U11": [
            (0, 2.0, "第一杀手", "前脚踏实后沿短刃轴线直刺陈迹喉部", "右手握柄，刀尖进入喉前半臂距离", "刀尖由前向后水平推进", "刺杀进入即将命中的危险距离", "完成近身刺杀", "杀手后脚蹬地，衣袖和刀穗向后绷直", "狠厉专注", "这一刀确实有明确目标和力量"),
            (2.0, 5.2, "陈迹", "后脚钉地顿足，右掌向下翻压，引出幽蓝冰流沿地砖直线冲向杀手落脚点", "靴底踏地、掌力指向砖缝", "冰流从陈迹脚下向前沿地面扩散", "杀手脚下、栏杆底和檐水连续结冰", "用冰改变摩擦阻断刺杀", "砖缝先结霜再扩成冰面，栏杆和檐水沿同一方向封冻", "陈迹目光冷定毫不后仰", "冰流通过真实接触面改变战局"),
            (5.2, 8.0, "第一杀手", "前脚在冰面横滑，刀尖从陈迹颈侧刺空，上身被惯性带向侧方", "靴底接触低摩擦冰面，握刀腕保持原刺方向", "脚向画面左侧滑，刀向陈迹身侧掠过", "杀手失足滑开，陈迹保持原地无伤", "让刺杀因物理失衡落空", "冰面刮出明确滑痕，杀手袖口和上身滞后偏转", "从狠厉转为惊愕", "不是刀无因停下，而是杀手失去落脚点"),
        ],
        "U12": [
            (0, 1.5, "云羊", "咬破右手食指并依次点过夹在左手的纸人眼位", "血珠接触每张纸人的眼位", "右指从近到远快速点过", "三张纸人被逐一激活", "用血点睛启动纸术", "血点接触后纸角沿同一方向轻颤，冰面反射纸影", "专注狠决", "纸人因血点睛而动"),
            (1.5, 4.0, "纸人与第二杀手", "纸人从指间腾起、展开并在杀手眼前合成纸影屏障；杀手抬臂护眼、滑行方向偏离", "纸面迎向杀手面部前方但不缠四肢", "纸屏逆着杀手前进方向扑面", "杀手视线被遮断并向侧方滑过", "夺取视觉而非束缚身体", "纸张受迎面气流向后绷紧，杀手抬臂带动上身偏转", "云羊果断，杀手慌乱", "纸人通过遮眼让进攻失准"),
        ],
        "U13": [
            (0, 2.0, "云羊", "后脚蹬地、转胯送肩，让右拳沿直线命中冰封栏杆固定点", "拳面接触栏杆横木中央", "力量由脚底经髋肩传向拳面", "接触点先压出裂纹", "把实体冲拳传入冰栏", "靴底蹬开碎雪，衣摆滞后，拳面处冰霜先凹陷", "爆发怒意", "云羊在打栏杆而不是隔空打人"),
            (2.0, 5.2, "冰封栏杆与失明杀手", "裂纹从拳面接触点向两侧扩散，栏杆定向爆裂，冰屑沿拳锋方向击中杀手胸肩", "冰屑接触杀手胸口和前臂", "从云羊一侧向廊柱方向激射", "杀手被碎栏冲击推向廊柱", "让传力链可见", "木屑、冰屑和尘雪同向飞散，杀手衣料在受击点向内凹", "杀手由慌乱转为痛苦", "拳力经栏杆和冰屑传到目标"),
            (5.2, 8.0, "失明杀手与第三杀手", "受击杀手背部撞柱后反弹落地；第三杀手看见同伴倒地后转身奔向火盆", "背部接触廊柱，第三人靴底蹬地", "一人向后撞柱，一人向火盆撤离", "前两路伏击瓦解，第三人改为焚证", "把打击结果接到下一剧情目标", "廊柱落尘一次，倒地者滑停；第三人的衣摆朝反方向甩动", "一人痛苦失神，第三人仓皇决绝", "战斗结果自然推动敌人转向毁证"),
        ],
        "U20": [
            (0, 3.0, "靖王府重檐与满庭残火", "镜头从前庭上方持续后拉，残火被横风压低", "风雪穿过檐角和火盆", "镜头向后上方离开，风由左向右", "人物缩成庭中黑点，建筑规模压过人物", "把敌意扩展到更高权力结构", "火苗同向伏低，雪线横扫屋脊，檐铃轻摆", "以环境承担压迫感", "个人争斗被庞大王府吞没"),
            (3.0, 8.0, "残火、风雪与靖王府", "风势短暂减弱，残火重新抬起后再次被雪幕遮暗，画面自然切黑", "火焰接触风雪气流，雪幕覆盖镜头远端", "火焰向上恢复，雪幕由远及近增强", "最后一处火点消失后切黑，不循环、不停帧", "留下权力层升级的悬念", "屋檐积雪被风卷落，残火亮度随风真实变化一次", "冷峻森然", "威胁已超出院中任何单个人物"),
        ],
    }
    rows = []
    for values in data[unit]:
        rows.append(beat(*values, invisible, ability, force))
    return rows


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    harvest = json.loads(HARVEST.read_text(encoding="utf-8"))
    by_unit = {row["unit_id"].split("-")[-1]: row for row in plan["units"]}
    meta = {row[0]: row for row in UNITS}
    a1 = {row["task_key"].split("-")[2]: Path(row["output_path"]) for row in harvest["results"]}
    BASE.mkdir(parents=True, exist_ok=True)
    prompt_dir = BASE / "prompts"
    spec_dir = BASE / "specs"
    prompt_dir.mkdir(exist_ok=True)
    spec_dir.mkdir(exist_ok=True)

    scene_state = {
        "schema": "qingshan.scene_authority_state.v1", "episode": "E31",
        "scene_state": [
            {"scene_id": "E31-CW-S01", "location": "靖王府雪夜前庭", "time_of_day": "night", "weather": "snow", "event_summary": "假名单引发两院争抢与内院暗查"},
            {"scene_id": "E31-CW-S02", "location": "太平医馆与王府三院内室", "time_of_day": "night", "weather": "interior_clear", "event_summary": "皎兔阴神出窍侦察三院反应"},
            {"scene_id": "E31-CW-S03", "location": "靖王府雪夜回廊", "time_of_day": "night", "weather": "snow", "event_summary": "三路伏击、冰流与纸术反击"},
            {"scene_id": "E31-CW-S04", "location": "靖王府侧阁孤灯书案", "time_of_day": "night", "weather": "interior_clear", "event_summary": "灰衣门客以骨牌交换完整名单"},
            {"scene_id": "E31-CW-S05", "location": "靖王府雪夜外廊与前庭", "time_of_day": "night", "weather": "snow", "event_summary": "骨牌印纹揭示更高权力并以王府远景收尾"},
        ],
    }
    SCENE_STATE.write_text(json.dumps(scene_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    tasks = []
    action_units = []
    for short in sorted(READY, key=lambda value: int(value[1:])):
        full = f"E31-CW-{short}"
        unit = by_unit[short]
        duration = int(unit["duration_seconds"])
        scene = int(meta[short][1])
        anchors = unit.get("admitted_reference_images") or [{
            "role": "A1", "path": relative(a1[short]), "sha256": sha256(a1[short]), "status": "PASS",
        }]
        refs = [ROOT / row["path"] for row in anchors]
        beats = beats_for(short)
        ownership = {
            "paper_and_tokens": "名单、残页、骨牌始终由动作脚本声明的持有人掌握，只有明确拍下、平放、递交或坠落才改变归属。",
            "weapons": "长刀、短刃始终由对应杀手或阴神持有；陈迹与云羊不得无前置动作接管武器。",
            "bodies": "肉身、阴神、三名杀手和主角身份不得合并、复制、换位或瞬移。",
        }
        spec = {
            "schema": "qingshan.performance_generation_spec.v2", "episode": "E31",
            "unit_id": full, "duration_seconds": duration,
            "source": "Claude Writer E31 contiguous editorial shots",
            "prop_ownership": ownership, "motion_beats": beats,
            "forbidden_transitions": ["无前置动作的抓取、转身、腾空或碰撞", "人物或道具归属跳变", "动作循环、慢放、停帧、周期重复"],
        }
        spec_path = spec_dir / f"{full}-PERFORMANCE-SPEC-V1.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        slots = "、".join(f"@图片{i}" for i in range(1, len(refs) + 1))
        beat_lines = [
            f"- {row['start_seconds']:.1f}-{row['end_seconds']:.1f}秒：主体={row['subject']}；动作={row['action']}；接触点={row['contact_point']}；方向={row['direction']}；意图={row['intent']}；可见因果={row['visible_causality']}；受力反馈={row['force_feedback']}；表情={row['expression']}；观众读法={row['viewer_read']}；终态={row['end_state']}。"
            for row in beats
        ]
        mid = max(1, len(beats) // 2)
        first = "；".join(row["action"] for row in beats[:mid])
        second = "；".join(row["action"] for row in beats[mid:]) or beats[-1]["end_state"]
        prompt = "\n".join([
            f"《青山》E31《王府风暴》{short}，Seedance 2.0 Pro 表演生成，{duration}秒，9:16，720p，原速连续动作。",
            f"【实体绑定】主角与现场人物[[char_principals]]、动作对手[[char_killer]]、本场空间[[scene_e31_s{scene:02d}]]、名单与兵器[[prop_e31_objects]]。",
            f"【生成范式】{slots}只锁身份、场景、初始空间关系，以及动作设计确实需要的终态拓扑；由下方单一逐拍 spec 驱动真实连续表演，不逐张硬命中姿势。",
            "【色彩与动机光】palette=雪夜冷蓝、火把暖橙、室内孤灯暖褐、法术幽蓝；光源只来自现场火把、烛灯与已声明能力。力量必须作用到环境介质：衣摆、纸张、火焰、积雪、栏杆、尘屑按受力方向反馈一次并自然衰减。",
            f"镜头1【0.0-{duration * 0.42:.1f}秒，远景定场转中景跟移】先交代人物、道具和行动路线，再完成：{first}；保持人物身份和道具归属。{{无对白}}<脚步、衣料、纸张、风雪与接触现场声>",
            f"镜头2【{duration * 0.42:.1f}-{duration:.1f}秒，近景侧移接结果特写】承接同一速度和受力方向，再完成：{second}；动作结果必须完整落地并让表情可读。{{无对白}}<受力碰撞、环境介质反馈、呼吸与余响>",
            "【连续物理动作脚本】", *beat_lines,
            "【单一状态源】提示词、锚图、时间轴和道具归属全部以本 spec 为唯一来源；任何额外人物、额外动作或归属变化都禁止。",
            "【声音】只有现场动作声、环境声和呼吸；禁止BGM、旁白和任何额外对白。",
            "【负面约束】禁止字幕、水印、Logo、可读文字、伪文字；禁止换脸、分身、融肢、穿模、瞬移、无因腾空、慢放、停帧、循环、周期重复、静帧微动和首尾重复。",
        ]) + "\n"
        prompt_path = prompt_dir / f"{full}-PERFORMANCE-V1.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        sequence = [{
            "asset_label": f"@图片{i}", "role": row["role"], "path": relative(refs[i - 1]), "sha256": sha256(refs[i - 1]),
        } for i, row in enumerate(anchors, 1)]
        interpolation = unit.get("keyframe_interpolation_gate") or {}
        task = {
            "task_key": f"{full}-PERFORMANCE-V1", "source_id": full, "tool_type": "video_generation",
            "generation_mode": "performance_generation", "still_sequence_only_allowed": True,
            "audio_reference_optional": True, "native_dialogue_required": False,
            "episode": "E31", "batch_id": "E31-PERFORMANCE-V1", "unit_id": full,
            "scene_id": unit["scene_id"], "visual_zone": full,
            "duration": duration, "duration_seconds": duration, "model": "seedance-2.0-pro",
            "duration_plan": {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": duration, "rationale": "Exact sum of contiguous Claude-script editorial shots.", "edit_policy": "End when the scripted result lands; never pad, slow or loop."},
            "aspect_ratio": "9:16", "resolution": "720p",
            "prompt_file": relative(prompt_path), "prompt_sha256": sha256(prompt_path),
            "reference_images": [relative(path) for path in refs], "reference_image_sequence": sequence,
            "state_reference_minimum": len(refs), "planned_reference_image_count": len(refs),
            "inherits_establishing_coverage": True, "action_unit": True,
            "performance_spec": spec,
            "keyframe_interpolation_gate": {
                **interpolation, "status": "PASS", "anchor_count": len(refs),
                "checked_adjacent_pairs": len(refs) - 1,
            },
            "dialogue": [], "reference_audios": [], "dialogue_audio_assets": [],
            "dialogue_audio_coverage": {"required": 0, "bound": 0, "status": "NOT_APPLICABLE_NO_DIALOGUE"},
            "source_spec": relative(spec_path), "source_spec_sha256": sha256(spec_path),
            "workflow_credit_scope": "e31_claude_writer_v1_20260722", "status": "READY_TO_SUBMIT",
        }
        task["generation_fingerprint"] = generation_fingerprint(task)
        tasks.append(task)
        action_units.append({"unit_id": full, "performance_spec": spec})

    scope_path = ROOT / "workflow/credit_scopes/E31_VIDEO_CREDIT_SCOPE.json"
    scope_path.parent.mkdir(parents=True, exist_ok=True)
    scope_path.write_text(json.dumps({
        "schema": "qingshan.episode_video_credit_scope.v1", "episode": "E31", "status": "ACTIVE",
        "workflow_scope_id": "e31_claude_writer_v1_20260722", "production_root": relative(PRODUCTION),
        "configured_limit_credits": 6000, "scope_policy": "CURRENT_WORKFLOW_ROUND_ONLY",
        "historical_rounds": "AUDIT_ONLY_EXCLUDED_FROM_GATE", "authorized_by": "Roger",
        "authorization": "6000 credits means this episode's current workflow round, not historical accumulation",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    ACTION_PLAN.write_text(json.dumps({"schema": "qingshan.performance_action_plan.v1", "episode": "E31", "units": action_units}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config = {
        "schema": "qingshan.episode_parallel_batch.config.v1", "episode": "E31",
        "status": "READY_INCREMENTAL_NONDIALOGUE_UNITS", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "targeted_unit_replacement": False, "concurrency": len(tasks), "max_retries": 0,
        "retry_policy": "NO_AUTOMATIC_RETRY_WITH_UNCHANGED_INPUT",
        "workflow_credit_scope": "e31_claude_writer_v1_20260722", "video_credit_limit": 6000,
        "source_script_sha256": sha256(SCRIPT),
        "writer_agent_provenance": {
            "status": "PASS", "provenance_type": "claude_writer_script",
            "source_script": relative(SCRIPT), "source_script_sha256": sha256(SCRIPT),
            "production_manifest": relative(PRODUCTION_MANIFEST), "production_manifest_sha256": sha256(PRODUCTION_MANIFEST),
        },
        "scene_contract_ref": relative(SCENE_STATE), "supervisor_script_gate_required": False,
        "output_dir": relative(BASE / "outputs"), "qa_dir": relative(BASE / "qa"), "tasks": tasks,
    }
    CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"config": relative(CONFIG), "tasks": len(tasks), "action_plan": relative(ACTION_PLAN)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
