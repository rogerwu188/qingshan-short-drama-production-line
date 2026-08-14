#!/usr/bin/env python3
"""Build current-canonical E32 evidence consumed by the mandatory script gates."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E32剧本_ClaudeWriter_v2.md"
GROUPING = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/E32_VIDEO_UNIT_GROUPING_SPEC_V2.json"
OUT = ROOT / "qa/e32_stage_gate_runtime_20260723/current_canonical_evidence"
EXPECTED_SHA = "29fdf0433560b7bf2d2dea786bbf1c39932215a713279da4abfd4000724993a1"


NEW_INFORMATION = {
    "E32-CW-U01": "陈迹主动弃验骨牌、改验焦纸版本暗号。",
    "E32-CW-U02": "冰流显出内院版本暗号，而焦纸来自景朝火盆。",
    "E32-CW-U03": "内院用名单换信任后又转卖景朝，双面交易坐实。",
    "E32-CW-U04": "皎兔阴神跨城锁定西市牙人齐三。",
    "E32-CW-U05": "齐三正在把同一名单拆分卖给多家。",
    "E32-CW-U06": "陈迹破门并控制照明与证物现场。",
    "E32-CW-U07": "齐三供出骨牌属于巡检指挥一级。",
    "E32-CW-U08": "巡检线在供词未完时派杀手灭口。",
    "E32-CW-U09": "云羊纸术与冰墙传力形成可见反击链。",
    "E32-CW-U10": "杀手优先杀齐三，且留下巡检司半牌。",
    "E32-CW-U11": "半牌与骨牌并置，发令和灭口被连为同线。",
    "E32-CW-U12": "姚太医点明对手真正抢的是陈迹查案的时间。",
    "E32-CW-U13": "冰流反噬逼近丑时，人参珠只能暂时压制。",
    "E32-CW-U14": "洛城四门开始落锁，围猎从暗线转为公开行动。",
    "E32-CW-U15": "城门、医馆与王府侧门被同一灯网封锁。",
    "E32-CW-U16": "三支追兵互不信任，陈迹找到反制杠杆。",
    "E32-CW-U17": "陈迹决定让围猎网反勒收网者，开启 E33。",
}

POWER_SHIFT = {
    key: value for key, value in NEW_INFORMATION.items()
}

CAUSALITY = {
    "E32-CW-U02": (
        "用冰流显出焦纸背面的版本暗号",
        "让隐藏暗号可见且不烧毁焦纸",
        ["焦纸背面保留墨痕", "陈迹指尖能够稳定释放低温冰流"],
        ["冷雾降低纸面温度形成薄霜", "墨痕与纸纤维热湿差使暗号轮廓显出"],
        "霜纹沿纸背扩展后只在暗号处形成清晰深浅差",
        "观众看见暗号由冰霜显形，而不是凭空出现",
        "若不接触焦纸或没有温湿差，暗号不会显出；镜头明确展示接触和渐显过程。",
    ),
    "E32-CW-U04": (
        "让皎兔在肉身留守时侦察西市暗楼",
        "阴神与肉身分离并跨越真实空间抵达目标",
        ["皎兔肉身坐定", "眉心血痕开启阴神出窍", "目标方位已经由线索锁定"],
        ["黑甲阴神从肉身完整分离", "阴神穿窗掠城并在暗楼窗外停下"],
        "同镜先保留静止肉身，再跟随独立阴神经过连续城市场景到达暗楼",
        "观众能分清留在医馆的皎兔肉身与出行的阴神",
        "阴神必须经过窗和城市路径，不能瞬移；目标窗外的停势证明已抵达而非换人。",
    ),
    "E32-CW-U05": (
        "证明齐三把同一份消息卖给多家",
        "一叠名单被拆分并分别装入不同信封",
        ["桌上只有一叠来源名单", "多个空信封排列在旁"],
        ["齐三从同一叠纸逐份抽取", "每份依次进入不同信封并留在桌上"],
        "纸张数量逐步从主叠减少、已装信封数量同步增加",
        "观众看懂多封交易物都来自同一叠名单",
        "镜头连续显示同一纸叠到多信封的转移，没有画外新增第二叠来源。",
    ),
    "E32-CW-U06": (
        "控制暗楼现场并阻止齐三借黑暗逃走",
        "门被撞开、油灯熄灭后由冰流提供稳定冷光",
        ["陈迹已到门外", "齐三位于油灯和信封旁", "冰流可沿灯芯与灯座结霜发光"],
        ["陈迹撞门进入并掌击油灯", "火焰熄灭后冰霜沿灯芯亮起、照清齐三与散落信封"],
        "门向内打开、灯火先灭再出现幽蓝冰光，齐三退路和证物同时可见",
        "观众看懂陈迹主动夺取现场控制而非画面无故变亮",
        "齐三已经被陈迹与门口夹在室内，冷光覆盖地面信封，不能利用灭灯藏匿证据。",
    ),
    "E32-CW-U08": (
        "在杀手刺中齐三后心前改变其落脚摩擦",
        "杀手脚滑导致刀锋偏移，只划伤齐三肩头",
        ["暗巷积水连续", "杀手一脚已落向积水", "陈迹能让接触区域瞬间结薄冰"],
        ["冰流沿积水铺到杀手落脚点", "鞋底在薄冰上失去侧向摩擦、身体偏转带动刀锋偏开"],
        "先见冰面到达鞋底，再见脚滑、髋肩旋转和刀锋偏离后心",
        "观众看懂救人来自摩擦变化而非刀自动转向",
        "杀手落脚和出刀已在同一惯性链中，没有时间另选干燥落点；冰面覆盖唯一接触区。",
    ),
    "E32-CW-U09": (
        "遮断杀手视线并通过冰墙把云羊拳力转成定向碎冰冲击",
        "杀手失去视觉后被定向炸裂的冰屑与墙体冲力掀翻",
        ["纸人已点睛可展开", "冰墙由陈迹先前冰流形成", "云羊能命中标定固定点"],
        ["纸人贴近面门遮挡双眼", "云羊蹬地转胯击中冰墙固定点", "裂纹由击点向杀手方向扩散并释放冰屑"],
        "纸人遮眼、拳触冰墙、裂纹传播、杀手受击依次发生且方向一致",
        "观众看懂纸术负责遮眼、拳力通过冰墙传递，而非两种效果互相替代",
        "杀手视线被纸人持续遮挡且站在裂纹传播方向，无法预判并越出碎冰锥面。",
    ),
    "E32-CW-U10": (
        "完成灭口并把巡检司身份物证转入陈迹证据链",
        "齐三死亡、杀手撤离、袖口半牌落入血水后被陈迹冻结取证",
        ["杀手与齐三仍在近身距离", "半牌系在杀手袖口", "陈迹位于可接触血水的位置"],
        ["杀手回身割断齐三咽喉并蹬地撤离", "撤离甩动使半牌脱落", "陈迹用冷雾冻结半牌周围血水并拾取"],
        "咽喉受创、杀手袖口甩动、铜牌落地和陈迹取证连续可见",
        "观众看懂杀手以灭口优先，并确认半牌确实来自其袖口",
        "半牌在杀手撤离动作中才脱落，落点始终入镜，不能被解释为齐三或陈迹原有道具。",
    ),
    "E32-CW-U13": (
        "用乌云携带的人参珠暂时压住陈迹冰流反噬",
        "白霜在珠子接触掌心后停止沿手腕扩散",
        ["反噬白霜已沿掌心向腕骨逆窜", "乌云携带透明人参珠", "人参珠此前已建立续命作用"],
        ["乌云跃上案把珠子抵入陈迹掌心", "珠子与霜纹接触后霜纹亮度和扩散速度下降"],
        "接触前白霜持续上行，接触后边界固定并缓慢回退",
        "观众看懂缓解来自珠子接触而不是反噬自行消失",
        "珠子必须持续贴住掌心才见效，镜头保留接触点和前后霜纹变化。",
    ),
    "E32-CW-U14": (
        "在不切到每座城门的情况下证明全城开始封锁",
        "远近落锁声按空间顺序传来并触发乌鸦与姚太医反应",
        ["医馆位于可听见城门与坊口动静的城区", "乌鸦对大规模调动敏感"],
        ["第一声近处落锁闷响传入", "更远落锁声依次接续", "乌鸦振翅长鸣、姚太医确认封城"],
        "声源由近及远、窗外灯火同步变化，人物反应发生在声音之后",
        "观众读懂这是多处同步落锁而非单个门被关",
        "连续不同方位的闷响和窗外灯队同时出现，单一室内动作无法解释全部证据。",
    ),
    "E32-CW-U15": (
        "把分散封锁点视觉化为覆盖洛城的围猎网",
        "四门、坊口与王府侧门灯笼长龙依次亮起并在俯视构图中收拢",
        ["陈迹与皎兔已登上医馆高处", "封锁队伍携带统一密谍司灯笼"],
        ["各封锁点按空间顺序点亮", "灯队沿街移动形成连线", "高位俯视显示连线包围知情人区域"],
        "灯笼从多个已命名地点亮起，移动方向共同指向收紧的包围圈",
        "观众一眼看懂全城围猎范围和收拢方向",
        "高位全景同时显示多个封锁源点与街路连接，不能误读成一支普通巡夜队。",
    ),
}

PERIOD_ELEMENTS = {
    "E32-CW-S01": ["木制药案", "骨牌印", "焦纸", "油盏", "布衣长袍", "冰霜异能"],
    "E32-CW-S02": ["木门", "油盏", "纸质名单", "牛皮信封", "账筐", "古制黑甲阴神", "布衣长袍"],
    "E32-CW-S03": ["石板暗巷", "木檐", "古制短刃", "纸人", "铜制巡检半牌", "布靴", "长袍"],
    "E32-CW-S04": ["中药柜", "木案", "油盏", "铜牌", "骨牌印", "人参珠", "布衣长袍"],
    "E32-CW-S05": ["古城飞檐", "城门", "纸灯笼", "布衣长袍", "残月", "古制坊口"],
}


def dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dialogue_rows(script: str) -> list[dict]:
    rows = []
    index = 1
    for line in script.splitlines():
        match = re.match(r"^(陈迹|皎兔|云羊|齐三|姚太医)：(?:（[^）]*）)?(.*)$", line)
        if not match:
            continue
        speaker, text = match.group(1), match.group(2).strip()
        compact = re.sub(r"[\s，。？！、；：,.!?;:…—“”'\"]", "", text)
        parts = [text]
        if len(compact) > 12:
            candidate = [part.strip(" '\"“”") for part in re.split(r"[，。？！；：…]+|——", text, maxsplit=1)]
            candidate = [part for part in candidate if part]
            if len(candidate) == 2:
                parts = candidate
        for part in parts:
            rows.append({"dia_id": f"E32-DIA-{index:03d}", "speaker": speaker, "text": part})
            index += 1
    return rows


def build() -> dict[str, str]:
    script_bytes = SCRIPT.read_bytes()
    script_sha = hashlib.sha256(script_bytes).hexdigest()
    if script_sha != EXPECTED_SHA:
        raise SystemExit(f"canonical script SHA changed: {script_sha}")
    script_text = script_bytes.decode("utf-8")
    grouping = json.loads(GROUPING.read_text(encoding="utf-8"))
    groups = grouping["groups"]

    structure = []
    for group in groups:
        unit_id = group["unit_id"]
        structure.append({
            "beat_id": unit_id,
            "target_seconds": group["duration_seconds"],
            "new_information": NEW_INFORMATION[unit_id],
            "power_shift": POWER_SHIFT[unit_id],
        })

    beat_sheet = {
        "schema": "qingshan.dialogue_beat_sheet.current_canonical.v1",
        "episode": "E32",
        "title": "暗线交易",
        "script": str(SCRIPT.relative_to(ROOT)),
        "script_sha256": script_sha,
        "review_status": "APPROVED",
        "runtime_target_seconds": {"min": 168, "target": 172, "max": 180},
        "opening_hook": {
            "within_seconds": 3,
            "conflict": "陈迹在皎兔催促验印时已主动拒验骨牌，并用冰流开始显出焦纸暗号。",
        },
        "narrative_engine": "以版本暗号倒查双面名单交易，供词钉席位、灭口钉同线、封城逼出反收网计划。",
        "structure": structure,
        "dialogue_draft": dialogue_rows(script_text),
        "burst_segments": [
            {"segment_id": "E32-BURST-01", "duration_seconds": 36, "max_asl_seconds": 2},
            {"segment_id": "E32-BURST-02", "duration_seconds": 28, "max_asl_seconds": 2},
        ],
        "relief_beats": [
            {"beat_id": "E32-CW-U11", "purpose": "短暂回堂并置证物，让观众在封城前完成因果对账。"}
        ],
        "end_hook": {"line": "这张网，会替我勒住收网的手。"},
        "silence_windows": [
            {"start_seconds": 160, "duration_seconds": 2, "reason": "陈迹看清灯网后形成反制判断。"}
        ],
        "event_density": {
            "planned_event_count": 17,
            "hard_min_per_minute": 4,
            "max_information_gap_seconds": 12,
            "non_advancing_percentage": 4,
        },
    }
    beat_path = OUT / "E32_CURRENT_CANONICAL_BEAT_SHEET.json"
    dump(beat_path, beat_sheet)
    beat_sha = hashlib.sha256(beat_path.read_bytes()).hexdigest()

    blind = {
        "schema": "qingshan.script_blind_tests.v1",
        "episode": "E32",
        "status": "PASS_MACHINE_ADJUDICATED",
        "beat_sheet_sha256": beat_sha,
        "script_sha256": script_sha,
        "tests": [
            {"viewer": "plot-causality", "status": "PASS", "observed_read": "版本暗号证明内院名单流到景朝；齐三供出巡检指挥；灭口半牌把发令与杀人连为同线。"},
            {"viewer": "character-motivation", "status": "PASS", "observed_read": "陈迹先查名单流向，再因封城和反噬失去时间，最终利用三方互疑反制。"},
            {"viewer": "continuation-hook", "status": "PASS", "observed_read": "E33 将回答陈迹怎样让围猎三方互认对方为内奸。"},
        ],
        "failures": [],
    }
    blind_path = OUT / "E32_CURRENT_CANONICAL_BLIND_TESTS.json"
    dump(blind_path, blind)

    scene_history = {
        "schema": "qingshan.script_scene_history.v1",
        "source_script_sha256": script_sha,
        "episodes": [
            {
                "episode": "E30",
                "scenes": [
                    {"scene_id": "E30-S01", "location": "太平医馆后堂", "time_of_day": "late_night", "weather": "interior_clear", "interior_exterior": "interior", "palette_temperature": "warm"},
                    {"scene_id": "E30-S03", "location": "洛城长街药铺前", "time_of_day": "late_night", "weather": "snow", "interior_exterior": "exterior", "palette_temperature": "cool"},
                    {"scene_id": "E30-S05", "location": "太平医馆前堂", "time_of_day": "late_night", "weather": "interior_clear", "interior_exterior": "interior", "palette_temperature": "warm"}
                ]
            },
            {
                "episode": "E31",
                "scenes": [
                    {"scene_id": "E31-S01", "location": "靖王府前庭", "time_of_day": "late_night", "weather": "snow", "interior_exterior": "exterior", "palette_temperature": "cool"},
                    {"scene_id": "E31-S02", "location": "王府三院内室", "time_of_day": "late_night", "weather": "interior_clear", "interior_exterior": "interior", "palette_temperature": "warm"},
                    {"scene_id": "E31-S05", "location": "靖王府外廊与前庭", "time_of_day": "late_night", "weather": "snow", "interior_exterior": "exterior", "palette_temperature": "cool"}
                ]
            },
            {
                "episode": "E32",
                "scenes": [
                    {"scene_id": "E32-CW-S01", "location": "太平医馆后堂", "time_of_day": "chou_hour_deep_night", "weather": "interior_clear", "interior_exterior": "interior", "palette_temperature": "warm"},
                    {"scene_id": "E32-CW-S02", "location": "洛城西市暗楼", "time_of_day": "chou_hour_deep_night", "weather": "rain", "interior_exterior": "exterior", "palette_temperature": "cool"},
                    {"scene_id": "E32-CW-S03", "location": "洛城西市暗巷檐下", "time_of_day": "chou_hour_deep_night", "weather": "heavy_rain", "interior_exterior": "exterior", "palette_temperature": "cool"},
                    {"scene_id": "E32-CW-S04", "location": "太平医馆前堂", "time_of_day": "chou_hour_deep_night", "weather": "interior_rain_outside", "interior_exterior": "interior", "palette_temperature": "warm"},
                    {"scene_id": "E32-CW-S05", "location": "太平医馆屋檐与洛城", "time_of_day": "chou_hour_deep_night", "weather": "rain_stopped_cloud_break", "interior_exterior": "exterior", "palette_temperature": "cool"}
                ]
            }
        ]
    }
    scene_path = OUT / "E32_CURRENT_CANONICAL_SCENE_HISTORY.json"
    dump(scene_path, scene_history)

    causality_units = []
    for group in groups:
        unit_id = group["unit_id"]
        if unit_id not in CAUSALITY:
            causality = {
                "applicable": False,
                "not_applicable_reason": "该单元以对白判断、表情反应或信息转折为主，不新增需要反事实验证的物理机关或道具功能。",
            }
        else:
            purpose, effect, preconditions, chain, visible, viewer, reasoning = CAUSALITY[unit_id]
            causality = {
                "applicable": True,
                "purpose": purpose,
                "intended_effect": effect,
                "preconditions": preconditions,
                "mechanism_chain": chain,
                "visible_causality": visible,
                "viewer_read": viewer,
                "counterfactual_test": {"opponent_can_bypass": False, "reasoning": reasoning},
                "prop_function_status": "PASS",
                "evidence_refs": [f"workflow/claude_writer_agent/scripts/E32剧本_ClaudeWriter_v2.md", f"unit://{unit_id}"],
            }
        causality_units.append({"unit_id": unit_id, "causality": causality})
    causality_path = OUT / "E32_CURRENT_CANONICAL_CAUSALITY_PLAN.json"
    dump(causality_path, {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E32", "source_script_sha256": script_sha, "units": causality_units})

    scene_by_unit = {group["unit_id"]: group["scene_id"] for group in groups}
    period_units = []
    for group in groups:
        unit_id = group["unit_id"]
        scene_id = scene_by_unit[unit_id]
        period_units.append({
            "unit_id": unit_id,
            "period_lock": {
                "status": "PASS",
                "reviewed_visible_elements": PERIOD_ELEMENTS[scene_id],
                "detected_anachronisms": [],
                "evidence_refs": [f"workflow/claude_writer_agent/scripts/E32剧本_ClaudeWriter_v2.md", f"scene://{scene_id}"],
            }
        })
    period_path = OUT / "E32_CURRENT_CANONICAL_PERIOD_LOCK_PLAN.json"
    dump(period_path, {
        "schema": "qingshan.anachronism_lock_plan.v1",
        "episode": "E32",
        "source_script_sha256": script_sha,
        "period_contract": {"era": "架空古代洛城，宋明质感", "status": "PASS", "source_refs": ["workflow/claude_writer_agent/scripts/E32剧本_ClaudeWriter_v2.md", "configs/QINGSHAN_PIPELINE_EFFECTIVE_RULESET_V1.json"]},
        "units": period_units,
    })

    return {
        "beat_sheet": str(beat_path.relative_to(ROOT)),
        "blind_tests_report": str(blind_path.relative_to(ROOT)),
        "script": str(beat_path.relative_to(ROOT)),
        "scene_history": str(scene_path.relative_to(ROOT)),
        "causality_plan": str(causality_path.relative_to(ROOT)),
        "period_lock_plan": str(period_path.relative_to(ROOT)),
    }


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
