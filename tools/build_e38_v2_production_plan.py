#!/usr/bin/env python3
"""Build E38 v2 Pro/1080p production units with upstream motion gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E38剧本_ClaudeWriter_v2.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E38_manifest_v2.json"
GATE = ROOT / "qa/e38_writer_v2_supervisor_script_gate_20260804/E38_SUPERVISOR_SCRIPT_GATE_V2_RESULT.json"
OUT = ROOT / "workflow/claude_writer_agent/production/e38_claude_writer_v2_3f08265c_20260804"
PROMPTS = OUT / "video_prompts_v1"
RESULTS = ROOT / "working_assets/e38_video_20260804/pro_v1"

REFS = {
    "陈迹": ROOT / "assets/reference/e37_plus_20260729/characters/CHAR-chenji-age20-user-turnaround-canonical-v1-20260729.png",
    "皎兔": ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v2_e19276d4_20260723/video_performance_v2/identity_transport_v2/jiaotu_267bbaa9f472_1440x2560.png",
    "云羊": ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v2_e19276d4_20260723/video_performance_v2/identity_transport_v2/yunyang_df033400d993_1440x2560.png",
    "乌云": ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v2_e19276d4_20260723/video_performance_v2/identity_transport_v2/wuyun_7c709fe66b53_1440x2560.png",
}

COMMON = (
    "竖屏9:16，Seedance 2.0 Pro，原生1080p，实时1倍速，中国古装悬疑短剧。"
    "人物动作遵守重力、关节活动范围、接触点和遮挡关系；先因后果，不瞬移，不穿模，不重复上一动作。"
    "固定机位或有明确叙事动机的单次位移；禁止smooth roam、slow push、orbit、overhead reveal、左右摇摆、呼吸式漂移。"
    "禁止慢动作、速度拉伸、插帧、定格活人、背景人物冻结、展示式站定、看镜头、现代物件、可读乱码字、字幕和水印。"
)


def motion(name: str, micro: str, reaction: str) -> dict:
    return {
        "actor": name,
        "continuous_micro_action": micro,
        "event_reaction": reaction,
        "positive_motion_cues": [micro, reaction],
    }


UNITS = [
    dict(id="U01", scene="11-1", duration=13, actors=["陈迹"], refs=["陈迹"],
         camera="两段明确硬切：手与脸的近景，切到账页俯角特写；两段机位均锁定。",
         action="陈迹悬手后压住账册翻开；冷雾从指尖只爬半页，十二笔报损逐月亮起，霜线汇流到页缘断掉。",
         dialogue="陈迹低声准确说：{救我养我的地方，头一回拿查贼的眼看。}",
         motions=[motion("陈迹", "手指持续下落、翻页、呼吸牵动肩背", "见到断流后眼神由迟疑转为惊疑并收紧下颌")]),
    dict(id="U02", scene="11-1", duration=11, actors=["陈迹", "乌云"], refs=["陈迹", "乌云"],
         camera="同一桌边固定侧轴，猫嗅辨后硬切陈迹指节与门缝，不横摇追人。",
         action="乌云鼻尖触页立即缩回、压耳低鸣并退入灯影；陈迹合眼再睁，指节收紧，抬眼望药房。",
         dialogue="陈迹先说：{这不是治病的量。} 稍后说：{皎兔，核库。}",
         motions=[motion("陈迹", "视线跟随乌云后转向药房、手指持续压紧", "猫退缩时合眼一瞬，随后决断抬头"), motion("乌云", "持续嗅页、缩颈、压耳、后退，尾尖保持警觉摆动", "闻到异常药味立即低鸣并避开账页")]),
    dict(id="U03", scene="11-2", duration=12, actors=["陈迹", "皎兔"], refs=["陈迹", "皎兔"],
         camera="门内固定中景硬切药柜前近景，禁止推镜。",
         action="陈迹推门到一半，报损单被风掀角；皎兔睫毛颤动，阴神从眉心逸出并逐屉检查后回归。",
         dialogue="皎兔寒声准确说：{一屉都没剩。}",
         motions=[motion("陈迹", "持续推门、压住纸角、侧身让出视线", "听见库存全空时呼吸停顿并望向药柜"), motion("皎兔", "睫毛颤动、阴神离体巡查、本体胸口保持呼吸", "阴神归窍后睁眼并因空库轻微震动")]),
    dict(id="U04", scene="11-2", duration=12, actors=["陈迹", "乌云"], refs=["陈迹", "乌云"],
         camera="药屉正侧固定近景硬切灯下纸张特写，轴线不变。",
         action="陈迹拉开安神药屉露出灰圈；乌云凑近低鸣。随后陈迹将报损单与姚太医旧方笺举灯叠映，霜纹回放两字运笔先后并显示错拍。",
         dialogue="陈迹低声准确说：{描的。不是他的手。}",
         motions=[motion("陈迹", "持续拉屉、取笺、举纸对光并移动指尖", "看见运笔错拍后眉峰收紧、声音压低"), motion("乌云", "沿屉沿探头嗅闻、耳尖轮转、尾巴低扫", "嗅到残留药味后低鸣并退半步")]),
    dict(id="U05", scene="11-2", duration=10, actors=["陈迹", "皎兔", "乌云"], refs=["陈迹", "皎兔", "乌云"],
         camera="日期栏特写硬切皎兔近景，均为锁定机位。",
         action="陈迹指尖从签名滑到秘密更换日期；乌云跳上柜台带响铜环；皎兔目光逐排扫过药屉并落到小铜锁。",
         dialogue="陈迹说：{这个日子，外人不会知道。} 接着说：{偷账的，在这个家里。} 皎兔低声说：{今夜守柜的，是阿栓。}",
         motions=[motion("陈迹", "指尖持续横移、眼神跟随日期栏、肩背缓慢前倾", "铜环响时迅速侧目后钉死内鬼结论"), motion("皎兔", "头部和目光连续扫过药屉，手指轻触小锁", "听到家里人后身体微震并给出阿栓信息"), motion("乌云", "跃上柜台后四爪调整重心、耳尖追随说话方向", "陈迹点到日期时用尾巴碰响铜环")]),
    dict(id="U06", scene="11-3", duration=10, actors=["陈迹", "皎兔", "云羊", "乌云", "暗桩"], refs=["陈迹", "皎兔", "云羊", "乌云"],
         camera="药柜侧面固定广角，暗桩入窗时硬切陈迹按住云羊的手臂近景。",
         action="三人藏在阴影中保持真实呼吸和重心调整；乌云耳朵竖起、尾指后窗；暗桩翻窗落地后直接摸向固定药屉；云羊将起，陈迹半途按住。",
         dialogue="陈迹气声准确说：{要活口。别惊了病人。}",
         motions=[motion("陈迹", "贴墙呼吸、眼睛追踪暗桩、手臂伸出按住云羊", "暗桩摸屉时前倾蓄势并及时制止突袭"), motion("皎兔", "阴影中持续侧移视线、手指预备结印", "暗桩落地时压低身体并盯住退路"), motion("云羊", "膝盖发力欲起、肩膀前送、随后被按住回收", "看见暗桩后立即启动又服从约束停在半程"), motion("乌云", "伏梁调整四爪、竖耳、尾尖转向后窗", "窗轴响时背毛轻立并锁定入侵者"), motion("暗桩", "翻窗屈膝落地、连续贴地移步并伸手摸屉", "听见细响时短暂停头但不站定")]),
    dict(id="U07", scene="11-3", duration=14, generation_duration=15, actors=["陈迹", "皎兔", "云羊", "乌云", "暗桩"], refs=["陈迹", "皎兔", "云羊", "乌云"], dependency=None,
         camera="15秒动作长镜A，药案与药屉之间锁定同一180度轴；仅为保持五人接触关系做一次短横移，立刻停稳，无摇摆。",
         action="0-4秒冰流贴地爬上屉脚，只冻结屉环和暗桩手腕，薄冰贴物不形成墙盾；4-9秒暗桩用肘崩碎薄冰，与云羊在药案间近身错步，悬秤急转，乌云按住滚向案边的药碾；9-15秒暗桩扬药粉转扑后窗，皎兔阴神半出窍替云羊看位，云羊点睛放出薄纸人贴地糊窗，暗桩撞上软纸墙弹回。动作一次完成，不重演。",
         dialogue="无对白，只有低音量冰裂、秤链、药粉和纸撞窗声。",
         motions=[motion("陈迹", "指尖牵引贴地冰流并随暗桩位置小幅转腕", "薄冰崩碎后立即改为守住药屉和静音控场"), motion("皎兔", "持续结印、阴神半出窍并追随粉雾中的轮廓", "药粉遮眼时立刻替云羊提供方位"), motion("云羊", "连续错步、短手错骨、避让后重新逼近", "被粉雾罩住时咬指点睛并改变进攻线"), motion("乌云", "沿梁跟跑后跃到案边按住药碾，尾巴保持平衡", "药碾滚落时立刻出爪阻止噪声"), motion("暗桩", "崩冰、肘击、侧身避让、扬粉、扑窗连续推进", "每次受阻都即时换方向，不停摆不重复")]),
    dict(id="U08", scene="11-3", duration=9, actors=["陈迹", "皎兔", "云羊", "暗桩"], refs=["陈迹", "皎兔", "云羊"], dependency="U07_ACCEPTED_EXACT_TAIL_FRAME",
         camera="动作长镜B必须用U07验收尾帧作唯一首帧；保持同一轴线和人物位置，固定近中景。",
         action="暗桩从纸墙回弹的未完成状态继续，云羊从粉雾中欺身拿住肩井按向药案；药戥将翻时陈迹细冰钉住；皎兔阴神立刻搜衣，暗桩咬碎齿间毒物，陈迹冰封后颈却慢半息。不得重置架势。",
         dialogue="无对白，动作全实速。",
         motions=[motion("陈迹", "持续跟随药戥和暗桩颈部移动指尖", "药戥将翻时先静音钉住，齿裂后立即抢救"), motion("皎兔", "阴神沿暗桩衣襟快速搜查、本体手势持续引导", "察觉咬合时猛然加速但晚一步"), motion("云羊", "从回弹落点连续进身、扣肩、压案并稳住下盘", "暗桩身体变软时及时卸力防止砸响"), motion("暗桩", "回弹后失衡挣扎、肩被扣仍转颈咬合", "被制住后选择自绝并逐步失去肌力")]),
    dict(id="U09", scene="11-3", duration=7, actors=["陈迹", "云羊", "乌云"], refs=["陈迹", "云羊", "乌云"],
         camera="药案旁锁定近景，不展示尸体细节，不推拉。",
         action="陈迹从暗桩僵指间拈起药包，再拉开身后空屉让二者同框；粉雾余尘持续落下，乌云绕过药碾嗅药包。",
         dialogue="云羊气声说：{死士，进了你的家。} 陈迹冷声说：{报损一笔，就是一声“来取”。}",
         motions=[motion("陈迹", "俯身拈包、转腕、拉屉并持续检查封口", "看见空屉与药包对应后眼神冷下来"), motion("云羊", "压住喘息、擦过眼角药粉、肩膀仍随呼吸起伏", "确认死士身份后咬牙低声提醒陈迹"), motion("乌云", "绕过药碾、低头嗅药包、耳尖追随两人声音", "药包靠近时立即后缩鼻尖警觉低鸣")]),
    dict(id="U10", scene="11-4", duration=13, actors=["陈迹", "云羊", "乌云"], refs=["陈迹", "云羊", "乌云"],
         camera="账桌固定中景硬切笔尖特写，禁止推镜。",
         action="陈迹蘸墨并写下一笔新报损，墨未干时掺入极淡霜痕；云羊倚门但持续换重心观察；乌云蜷案角摆尾。",
         dialogue="云羊低声说：{人都死了，还写什么？} 陈迹边写边说：{收货的那头，还在等。}",
         motions=[motion("陈迹", "蘸墨、运笔、停顿、收笔连续完成", "听到追问不抬头，只在霜痕隐没时眼神定住"), motion("云羊", "抱臂后换脚承重、头随笔锋移动", "看到陈迹继续造账时眉头收紧并发问"), motion("乌云", "尾尖缓慢摆动、耳尖在两人之间轮转", "灯芯爆响时耳朵短促后压")]),
    dict(id="U11", scene="11-4", duration=13, actors=["陈迹", "皎兔", "云羊", "乌云"], refs=["陈迹", "皎兔", "云羊", "乌云"],
         camera="账册合拢近景硬切皎兔转头与陈迹反应双人近景，机位锁定。",
         action="陈迹合上账册并压住霜痕位置；皎兔转向前院想问；云羊从门边放下手臂靠近半步；灯花爆尽，乌云抬头。",
         dialogue="陈迹说：{他来取这笔假药，路就自己走出来了。} 皎兔低声问：{姚太医呢？} 陈迹极轻说：{钓到头之前，谁都不告诉。}",
         motions=[motion("陈迹", "合册、压封面、抬眼后缓慢收紧手指", "姚太医被提及时眼底翻涌再压平"), motion("皎兔", "持续转头看向前院、唇部起势后回看陈迹", "得到隐瞒命令后呼吸变浅并轻点头"), motion("云羊", "放下抱臂、前移半步、视线在二人间切换", "听到谁都不告诉时停步并接受安排"), motion("乌云", "案角蜷卧中尾尖摆动、灯爆时抬头眨眼", "房间变暗后瞳孔放大并转向门口")]),
    dict(id="U12", scene="11-5", duration=10, actors=["陈迹", "皎兔", "云羊", "乌云", "阿栓"], refs=["陈迹", "皎兔", "云羊", "乌云"],
         camera="柜前固定近景硬切梁上猫的侧面，禁止摇镜跟随尾巴。",
         action="15岁阿栓蹲下查点药屉并将铜锁插入柜环；三人在暗处持续呼吸观察；乌云尾尖从后窗方向快速摆向前堂。",
         dialogue="无对白。",
         motions=[motion("陈迹", "暗处持续跟随阿栓手部、手掌缓慢张合", "乌云改指前堂时立即凝视门口"), motion("皎兔", "半蹲换重心、手指预备结印", "方向变化后侧头看前堂并屏住呼吸"), motion("云羊", "膝盖弹性微调、肩部随呼吸起伏", "猫尾转向后身体前倾准备截人"), motion("乌云", "伏梁挪动前爪、耳朵竖起、尾尖转向前堂", "檐马停响时全身骤然警觉"), motion("阿栓", "蹲下、插锁、逐屉点数、翻药簿连续进行", "远处门响前茫然抬头但不定格")]),
    dict(id="U13", scene="11-5", duration=11, actors=["陈迹", "皎兔", "云羊", "阿栓", "差役群"], refs=["陈迹", "皎兔", "云羊"],
         camera="前堂门口固定广角硬切陈迹明暗交界近景，不做推镜。",
         action="大门推开一半，数名差役持火把和盖印文书齐步进入；每名差役各自踏步、转头、调整火把和队形，不得冻结。阿栓从柜前转身，三人暗处分别压低身体。火光边界爬过陈迹半张脸。",
         dialogue="陈迹气声准确说：{他把官府的手，借来了。}",
         motions=[motion("陈迹", "随火光转头、后撤半步、手指扣紧柜沿", "认出官差后瞳孔收缩并压低声音"), motion("皎兔", "侧移让出视线、手势收回、目光逐个核对差役", "看见文书后由攻击准备转为克制"), motion("云羊", "重心前送又收回、拳头松开再握紧", "官差齐步逼近时被迫停在暗处"), motion("阿栓", "从蹲姿起身到一半、药簿随动作晃动", "门响时茫然转头并后退半步"), motion("差役群", "持续齐步、分别调整火把高度、文书手随步伐摆动", "进入药房后各自转头确认柜台和阿栓位置")]),
    dict(id="U14", scene="11-5", duration=15, actors=["陈迹", "皎兔", "云羊", "阿栓", "领头差役", "差役群"], refs=["陈迹", "皎兔", "云羊"],
         camera="前7秒固定近景；一次明确硬切后，后8秒摄影机仅做缓慢垂直升高来揭示包围关系，禁止左右摇摆和旋转。",
         action="领头差役边走边展开文书，火把光落到阿栓脸上；其他差役持续合拢但每人保持踏步、转头和火把动作。阿栓药簿掉地，转向暗处发抖。硬切广景：火把圈继续收紧，院内病房有人影起身走近窗边；陈迹半步踏出又收回，靴尖碾住火光，皎兔和云羊各自克制跟进动作。",
         dialogue="领头差役冷声说：{奉命查案。看管药柜的，跟我们走一趟。} 阿栓发颤说：{迹哥……}",
         motions=[motion("陈迹", "半步踏出、脚尖落地、立即收回并攥拳", "阿栓求救时身体先响应再强行克制"), motion("皎兔", "从暗处前倾后被陈迹动作带停、手指缓慢收回", "听见带走阿栓时眼神急转陈迹"), motion("云羊", "肩膀前冲、脚掌挪动又压回原位", "官差合围时咬紧牙关并控制出手冲动"), motion("阿栓", "抱簿、簿落地、后退、转头求救、嘴唇持续发抖", "文书点到自己时从茫然变为惊惶"), motion("领头差役", "持续前行、展开文书、抬手点向阿栓", "阿栓退缩时侧身示意同伴合围"), motion("差役群", "每人持续踏步、转头、收紧间距和调整火把", "领头发令后从纵队变为半圆包围")]),
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate() -> None:
    expected = {
        SCRIPT: "3f08265c97e618f24ff0a1210dc593456f3ec19d50f71fe9a8bd73579fc3d818",
        MANIFEST: "926ca2f008172e7cc81b4c308bf03271da1793c826dcfed555533db7246fd7a8",
        GATE: "c480fde55ab0629022ef8b35f0067e0809ae3bb443256a1af448c9480950a03d",
        REFS["陈迹"]: "e5bb8c90683120b2b02e113dc2a12b8530f8c66feaeee7657172807adb8e3373",
    }
    for path, digest in expected.items():
        if not path.is_file() or sha(path) != digest:
            raise SystemExit(f"Canonical binding failed: {path}")
    if sum(unit["duration"] for unit in UNITS) != 160:
        raise SystemExit("Unit duration sum must be 160 seconds")
    ids = {unit["id"] for unit in UNITS}
    for unit in UNITS:
        if unit.get("dependency") and not unit["dependency"].startswith("U07_"):
            raise SystemExit(f"Unsupported dependency: {unit['id']}")
        roster = {row["actor"] for row in unit["motions"]}
        if roster != set(unit["actors"]):
            raise SystemExit(f"Visible actor motion coverage mismatch: {unit['id']}")
        for row in unit["motions"]:
            if len(row["positive_motion_cues"]) < 2:
                raise SystemExit(f"Insufficient motion cues: {unit['id']} {row['actor']}")
    if {unit["id"] for unit in UNITS} != ids:
        raise SystemExit("Duplicate unit id")


def prompt_for(unit: dict) -> str:
    roster = "；".join(
        f"{row['actor']}：持续动作={row['continuous_micro_action']}；事件反应={row['event_reaction']}"
        for row in unit["motions"]
    )
    return (
        COMMON
        + f"\n【单元】E38-{unit['id']}，场{unit['scene']}，生成{unit.get('generation_duration', unit['duration'])}秒，成片使用{unit['duration']}秒。\n"
        + f"【摄影】{unit['camera']}\n"
        + f"【动作因果链】{unit['action']}\n"
        + f"【声音与对白】{unit['dialogue']} 只有当前说话者口型运动；其他角色闭口但身体与视线持续反应。\n"
        + f"【全可见角色运动职责】{roster}。任何可见角色不得成为静止背景板。\n"
        + "【空间与尺度】药屉、药案、门窗、人体均保持成人真实尺度；冰只贴附接触物，禁止变成盾牌、墙板、平板或巨大特效。\n"
        + "【输出】动作首帧必须是进行态，结尾保留自然动作余势供剪辑；不生成片内字幕。\n"
    )


def main() -> int:
    validate()
    PROMPTS.mkdir(parents=True, exist_ok=True)
    run_plan = []
    compiled_units = []
    for unit in UNITS:
        prompt_path = PROMPTS / f"E38-{unit['id']}-PRO1080P.txt"
        prompt_path.write_text(prompt_for(unit), encoding="utf-8")
        references = [str(REFS[name]) for name in unit["refs"]]
        run_plan.append({
            "shot_id": unit["id"],
            "prompt_file": str(prompt_path),
            "references": references,
            "audio_references": [],
            "duration": unit.get("generation_duration", unit["duration"]),
            "edit_duration": unit["duration"],
            "out_dir": str(RESULTS / unit["id"]),
            "dependency": unit.get("dependency"),
        })
        compiled_units.append({
            **unit,
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "prompt_sha256": sha(prompt_path),
            "reference_bindings": [
                {"character": name, "path": str(REFS[name].relative_to(ROOT)), "sha256": sha(REFS[name])}
                for name in unit["refs"]
            ],
            "visible_actor_motion_gate": "PASS",
            "model": "seedance-2.0-pro",
            "resolution": "1080p",
            "speed": "REAL_TIME_1X",
        })
    (OUT / "E38_PRO_V1_RUN_PLAN.json").write_text(json.dumps(run_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "schema": "qingshan.e38_production_plan.v1",
        "episode": "E38",
        "canonical_script_sha256": sha(SCRIPT),
        "canonical_manifest_sha256": sha(MANIFEST),
        "script_gate_sha256": sha(GATE),
        "status": "PASS_READY_TO_SUBMIT_INDEPENDENT_UNITS",
        "unit_count": len(compiled_units),
        "duration_seconds": sum(unit["duration"] for unit in compiled_units),
        "independent_units": [unit["id"] for unit in compiled_units if not unit.get("dependency")],
        "serial_units": [unit["id"] for unit in compiled_units if unit.get("dependency")],
        "concurrency": {"independent_max": 6, "action_chain": 1},
        "credits": {"episode_cap": 10000, "pay": 0, "refund": 0, "net": 0},
        "units": compiled_units,
    }
    (OUT / "E38_PRODUCTION_PLAN_V1.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "units": len(compiled_units), "duration": report["duration_seconds"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
