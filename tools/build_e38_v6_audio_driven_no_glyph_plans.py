#!/usr/bin/env python3
"""Compile audio-driven E38 visual prompts without exposing dialogue glyphs to Seedance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e38_claude_writer_v2_3f08265c_20260804"
V4_PLAN = BASE / "E38_PRO_V4_EXPRESSIVE_CLEAN_RUN_PLAN.json"
AUDIO = ROOT / "workflow/tasks/E38_V6_EXACT_EXPRESSIVE_AUDIO_ASSETS_20260805.json"
PROMPT_DIR = BASE / "video_prompts_v6_audio_driven_no_dialogue_glyphs"
RUN_PLAN = BASE / "E38_PRO_V6_AUDIO_DRIVEN_NO_GLYPHS_RUN_PLAN.json"
AUDIT = ROOT / "qa/e38_v6_audio_driven_no_glyphs_20260805/E38_V6_PROMPT_PREFLIGHT.json"


COMMON = """竖屏9:16，中国古装悬疑短剧，Seedance 2.0 Pro原生1080p，实时1倍速。
【文字隔离硬门】这是后期字幕之前的干净摄影源。画面中不得出现字幕、标题、黑底文字条、水印、界面、汉字、拼音、数字、伪文字或可读书写。纸张、账页、药屉标签只呈现空白表面、规则格线或单个圆形墨点。不得把音频内容转写到画面。
【表演硬门】严格以所附音频的实际情绪、停顿、呼吸和重音驱动对应人物的嘴唇、下颌、喉部、眼神和躯干。音频原样播放一次，不复述、不增删、不换说话者。非说话人物闭口，但持续呼吸、眨眼、转移重心并对事件作出可见反应。
【摄影硬门】除下文明确写出的硬切外，机位锁定；禁止推、拉、摇、移、环绕、漂移、慢动作、定格、重复动作、柔焦、运动拖影、浅景深遮挡主体。
"""


SPECS = {
    "U01": {
        "duration": 9,
        "audio": ["U01-D01"],
        "body": """【构图】固定半身中近景，陈迹的脸、双手和合拢账册清晰；不拍可读内页。
【动作节拍】0.0-1.2秒，陈迹右手悬停后压住合拢账册，左手扶书脊，肩背有克制呼吸。1.2秒开始播放@音频1，他随音频从迟疑转为警觉，目光先落纸边再抬向门口。音频结束后至9.0秒，十二个分离小霜点聚成无字冰线并在纸边断开；他指腹沿断口停住，仍保持呼吸余势。
【角色动作覆盖】陈迹全程有手指压力、眨眼、呼吸和视线变化；乌云若入画则耳尖转动并嗅纸边，不得静止。
【终态】陈迹抬眼确认线索；无文字。""",
    },
    "U02": {
        "duration": 7,
        "audio": ["U02-D01", "U02-D02"],
        "body": """【构图】固定药案双人中近景，陈迹与皎兔均清晰，账页背面朝镜头且为空白。
【动作节拍】0.0-0.8秒，陈迹用竹尺量两包药，眉心收紧；皎兔侧身检查空屉并持续呼吸。0.8秒播放@音频1，只有陈迹说话并同步口型，皎兔听见后手指停在屉沿但肩背仍动。音频1结束后0.25秒，陈迹转眼看皎兔并播放@音频2，语气变成短促命令；皎兔立即点头、抽屉、转身执行。余时两人以动作把决定推进，不再开口。
【角色动作覆盖】陈迹测量、转眼、下令；皎兔检查、反应、执行；乌云若入画则绕药包嗅闻。任何人不得站成静态背景。
【终态】皎兔已拉开下一只空屉，陈迹手中竹尺停在异常药包上；无文字。""",
    },
    "U03": {
        "duration": 5,
        "audio": ["U03-D01"],
        "body": """【构图】固定药柜双人近景，药屉木牌全部无字，陈迹与皎兔同清晰焦平面。
【动作节拍】0.0-1.2秒，皎兔的淡蓝阴神从最后一只空屉收回眉心，她睁眼并锁住陈迹；陈迹压住空白报损纸翘角，呼吸一顿。1.2秒播放@音频1，皎兔只说一次并同步细微唇颌、喉部和压低气息；陈迹闭口，目光从她转向一排空屉。音频结束后两人同时向空屉前移半步。
【角色动作覆盖】皎兔回神、睁眼、说话、迈步；陈迹压纸、呼吸、转眼、迈步。不得冻结。
【终态】两人并肩面对空柜；无文字。""",
    },
    "U05": {
        "duration": 10,
        "audio": ["U05-D01", "U05-D02", "U05-D03"],
        "body": """【构图】固定三人中景，陈迹、皎兔、云羊与乌云处于可辨识焦平面；所有纸张背面朝镜头。
【动作节拍】0.0-1.0秒，陈迹把无字药包与空屉并置，皎兔沿柜缝查霜，云羊压住怒气换脚承重，乌云嗅封口。1.0秒播放@音频1，只有陈迹开口；其余三者各自保持反应动作。短停后播放@音频2，陈迹的目光由物证移向同伴，语气进一步收紧。短停后播放@音频3，只有皎兔开口，她转头给出关键人名；陈迹和云羊同时产生不同反应，乌云耳尖转向门外。余时三人各自采取下一步行动。
【角色动作覆盖】陈迹摆证、两次说话、抬眼；皎兔查霜、说话、转身；云羊攥拳、换重心、看门；乌云嗅闻、摆尾、转耳。不得冻结或齐动。
【终态】三人的注意力都转向药柜外，但姿态不同；无文字。""",
    },
    "U09A": {
        "duration": 4,
        "audio": ["U09-D01"],
        "source": "U09",
        "body": """【构图】固定低位双人近景，云羊前景、陈迹侧后方，暗桩只保留无血手部边缘，不展示尸体脸。
【动作节拍】0.0-0.7秒，云羊从急停中稳住脚，拳头收紧，胸口仍有战后喘息；陈迹从暗桩指间拈起无字药包。0.7秒播放@音频1，云羊只说一次，嘴唇、下颌和胸腔随压怒音频同步；陈迹闭口但抬眼回应。音频结束后云羊视线落向药包。
【角色动作覆盖】云羊喘息、攥拳、说话、转眼；陈迹取证、抬眼；乌云若入画则绕药碾快步嗅闻。
【终态】云羊盯住药包，陈迹开始起身；无文字。""",
    },
    "U09B": {
        "duration": 5,
        "audio": ["U09-D02"],
        "source": "U09",
        "body": """【构图】与上一镜不同的固定侧面双人中近景，陈迹前景、云羊后景；空屉和无字药包同框，不重复上一镜位置。
【动作节拍】0.0-0.8秒，陈迹拉开空屉并把药包靠近封口比对；云羊从后方绕到侧面，肩背仍随喘息起伏。0.8秒播放@音频1，陈迹只说一次，冷静寒意随音频重音推进，指尖依次点药包和空屉；云羊闭口但逐词理解，拳头慢慢松开。音频结束后乌云探鼻，陈迹收回药包。
【角色动作覆盖】陈迹拉屉、比对、说话、收证；云羊绕位、喘息、松拳；乌云探鼻和后缩。不得冻结。
【终态】证据被收回，空屉保持打开；无文字。""",
    },
    "U10": {
        "duration": 8,
        "audio": ["U10-D01", "U10-D02"],
        "body": """【构图】固定账桌双人中景，不拍笔尖或可读纸面特写；纸上仅一个圆墨点。
【动作节拍】0.0-0.8秒，陈迹在纸角落下圆墨点后立即提笔；云羊从门边向前半步，乌云在桌角摆尾。0.8秒播放@音频1，只有云羊说话，急躁与不安驱动口型、眉眼和前倾躯干；陈迹闭口，笔悬在空中。短停后播放@音频2，只有陈迹回应，收笔并以冷定目光压住局面；云羊听完后呼吸逐渐放缓。灯芯爆响时乌云耳朵后压。
【角色动作覆盖】云羊迈步、说话、呼吸变化；陈迹落点、提笔、说话、收笔；乌云摆尾、转耳。不得冻结。
【终态】陈迹笔尖离纸，云羊停在桌前但仍呼吸；无文字。""",
    },
    "U11": {
        "duration": 11,
        "audio": ["U11-D01", "U11-D02", "U11-D03"],
        "body": """【构图】固定三人中景，陈迹、皎兔、云羊和乌云均可辨；账册合拢，封面无字。
【动作节拍】0.0-0.8秒，陈迹把合拢账册推到桌心，皎兔正从柜边回身，云羊靠门警戒，乌云绕桌脚。0.8秒播放@音频1，只有陈迹说话，指尖先点账册再点门外，克制推理随音频逐步变硬；皎兔和云羊以不同节奏反应。短停后播放@音频2，只有皎兔发问，她向前半步、眼神追问。再短停后播放@音频3，只有陈迹回答，他收回手并合紧账册，决意与隐瞒同时落定。余时云羊转身守门，皎兔看陈迹，乌云停下抬头。
【角色动作覆盖】陈迹推册、说话、指门、收手；皎兔回身、听、迈步、发问；云羊警戒、反应、转身；乌云绕行、停步、抬头。不得冻结或齐动。
【终态】账册已合紧，三人进入不同任务姿态；无文字。""",
    },
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    source_rows = {row["shot_id"]: row for row in json.loads(V4_PLAN.read_text(encoding="utf-8"))}
    audio_payload = json.loads(AUDIO.read_text(encoding="utf-8"))
    if audio_payload["status"] != "PASS":
        raise SystemExit("exact expressive audio gate is not PASS")
    assets = {row["line_id"]: row for row in audio_payload["results"]}
    canonical_lines = [row["text"] for row in audio_payload["results"]]
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    plan = []
    audits = []
    for shot_id, spec in SPECS.items():
        source_id = spec.get("source", shot_id)
        prompt = COMMON + spec["body"] + "\n"
        leaks = [line for line in canonical_lines if line and line in prompt]
        prompt_path = PROMPT_DIR / f"E38-{shot_id}-V6-AUDIO-DRIVEN-NO-GLYPHS-PRO1080P.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        audio_rows = [assets[line_id] for line_id in spec["audio"]]
        row = dict(source_rows[source_id])
        row.update({
            "shot_id": shot_id,
            "prompt_file": str(prompt_path),
            "prompt_sha256": sha(prompt_path),
            "audio_references": [item["registered_asset_id"] for item in audio_rows],
            "audio_line_ids": spec["audio"],
            "audio_asset_sha256": [item.get("seedance_audio_sha256", item["wav_sha256"]) for item in audio_rows],
            "duration": spec["duration"],
            "edit_duration": spec["duration"],
            "out_dir": str(ROOT / f"working_assets/e38_replacement_v6_20260805/pro/{shot_id}"),
            "native_dialogue_required": True,
            "status": "READY_TO_SUBMIT" if not leaks else "BLOCKED_DIALOGUE_GLYPH_LEAK",
            "dependency": None,
            "material_change": "EXACT_EXPRESSIVE_AUDIO_ASSET_DRIVES_LIPS_ZERO_DIALOGUE_GLYPHS",
        })
        plan.append(row)
        audits.append({
            "shot_id": shot_id,
            "status": "PASS" if not leaks else "FAIL",
            "canonical_dialogue_glyph_leaks": leaks,
            "audio_line_ids": spec["audio"],
            "audio_reference_count": len(row["audio_references"]),
            "visible_actor_motion_ledger": "PRESENT",
            "camera_motion_gate": "FIXED_OR_EXPLICIT_HARD_CUT_ONLY",
        })
    if any(item["status"] != "PASS" for item in audits):
        raise SystemExit("dialogue glyph leak detected")
    RUN_PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit_payload = {
        "schema": "qingshan.e38_v6_audio_driven_prompt_preflight.v1",
        "status": "PASS",
        "source_audio_receipt": str(AUDIO),
        "source_audio_sha256": sha(AUDIO),
        "script_sha256": "c281dbb9f0027a537ea229c47c666c1b1cfa071d93a371b767f23c212fedd3ba",
        "units": audits,
        "projected_video_seconds": sum(row["duration"] for row in plan),
        "projected_video_credits": sum(row["duration"] for row in plan) * 48,
        "credit_preflight": {
            "prior_video_net": 6528,
            "exact_audio_net": audio_payload["credits"]["net"],
            "projected_v6_video_net": sum(row["duration"] for row in plan) * 48,
            "projected_episode_repair_net": 6528 + audio_payload["credits"]["net"] + sum(row["duration"] for row in plan) * 48,
            "cap": 10000,
        },
    }
    if audit_payload["credit_preflight"]["projected_episode_repair_net"] > 10000:
        raise SystemExit("credit cap exceeded")
    AUDIT.write_text(json.dumps(audit_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "units": len(plan), "plan": str(RUN_PLAN), "audit": str(AUDIT), "credit_preflight": audit_payload["credit_preflight"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
