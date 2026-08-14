#!/usr/bin/env python3
"""
Build E09 high-tempo Giggle API run plan.

Reads E09 continuity + asset manifest and writes one prompt per shot plus a
run_plan.json for tools/run_giggle_api_plan.py. API keys are never read here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]

CHENJI_FACE = ROOT / "ref_images/male_lead_chenji_ancient_face_ref_20260621.png"
CHENJI_GREY_APPRENTICE = ROOT / "assets/reference/e08_api_fallback_20260709/characters/CHAR-chenji-grey-apprentice-card-clean-20260709.jpg"
WUYUN_MAIN = ROOT / "ref_images/cat_wuyun_reference.jpg"
WUYUN_BODY = ROOT / "ref_images/cat_wuyun_body_ref.jpg"
WUYUN_HEAD = ROOT / "ref_images/cat_wuyun_head_ref.jpg"
YAO_CARD = ROOT / "assets/reference/e08_api_fallback_20260709/characters/CHAR-yao-taiyi-card-clean-20260709.jpg"
FRONT_HALL = ROOT / "assets/reference/e08_api_fallback_20260709/scenes/SCENE-taiping-front-hall-clean-20260709.jpg"
DORM = ROOT / "assets/reference/e08_api_fallback_20260709/scenes/SCENE-taiping-apprentice-dorm-clean-20260709.jpg"
STREET = ROOT / "assets/reference/e08_api_fallback_20260709/scenes/SCENE-luocheng-stone-street-clean-20260709.jpg"
VOICE_CHENJI_NATIVE_SAMPLE = ROOT / "libraries/audio/voice_refs/native_multimodal_20260709/VOICE-陈迹-古装/e09_shot01_chenji_native_voice_ref.wav"
VOICE_CHENJI = {
    "asset_id": "cypqud0bu7t",
    "url": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/yzp8lyx7vw.wav",
    "label": "VOICE-陈迹-古装 原生样本 E09 shot01",
    "local_sample": str(VOICE_CHENJI_NATIVE_SAMPLE),
}
VOICE_SHENDENGKE = ROOT / "libraries/audio/voice_refs/e09_voice_locked_20260709/shot_09_VOICE-佘登科.wav"
VOICE_WUYUN = ROOT / "libraries/audio/voice_refs/e09_voice_locked_20260709/shot_20_VOICE-乌云-猫-final-hook-only.wav"
AMB_TAIPING = {
    "asset_id": "2qmyh0s1y4u",
    "url": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/e62k24lugn.wav",
    "label": "AMB-太平医馆-晨夜空间",
}
SFX_BEAD = {
    "asset_id": "mqqctllu0t",
    "url": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/yx2utk1xpfj.wav",
    "label": "SFX-水晶珠-震动",
}
SFX_CONTRACT = {
    "asset_id": "kaf7n6ahi3",
    "url": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/w0fyi60slrc.wav",
    "label": "SFX-聘猫书-燃契",
}


COMMON_RULES = """中文真人古装竖屏短剧，9:16，720p，电影级写实画面。全片高节奏，镜头必须推进剧情，不要纯氛围空镜。普通话中文对白必须完整说完，不能英文，不能外语，不能无对白，不能模型自带字幕或乱码文字。严格保持角色、猫、道具、场景和服装一致。画面目标精美绝伦：清晰人物/猫主体，考究灯光，古装真实质感，封面级构图，但每个漂亮画面都必须推动剧情。禁止静态照片推拉、故事板表格入镜、现代物件、欧美人物、随机换脸、道具漂移、场景漂移。"""

SHOT_PROMPTS: Dict[str, str] = {
    "01": "清晨学徒寝房，陈迹猛地醒来，手摸向枕边却摸空，脸上从迷茫变成清醒和失落。对白：陈迹低声说“手机没了……我真在这里。”镜头从手部摸空推到陈迹年轻清瘦的脸。",
    "02": "陈迹抓起木扁担和水桶出门，丹田寒意袭来，他按住胸腹强行压下，脚步没有停。对白：陈迹咬牙说“先活下去。”木门吱呀和鸡鸣做声桥。",
    "03": "洛城安西街晨雾，陈迹挑水走过青石街，房檐上深灰长毛猫乌云无声跟随。陈迹抬头看见它：“你又跟来了？”画面要有封面级晨雾屋檐和一人一猫平行构图。",
    "04": "街巷对峙，陈迹停下逗乌云：“喵喵？丧彪？”乌云居高临下冷眼俯视，表情聪明嫌弃，像在骂人。镜头正反切，节奏轻快。",
    "05": "陈迹摊开小水晶珠，珠中有细灰雾，乌云立刻前探想靠近。陈迹故意合掌收回，乌云僵住，忍住不叫。重点是珠子诱惑和猫的克制。",
    "06": "水井边，陈迹把水晶珠放在青石地上，自己退后三步。乌云从屋檐跳到井边，小心靠近，一边看珠子一边警惕陈迹。动作要真实。",
    "07": "爆点镜头：乌云张嘴去叼水晶珠，珠中灰雾暴起，一股无形力量把乌云震退半步。陈迹脸色骤变：“这珠子在防你？”不要夸张魔法，只做克制神秘震动。",
    "08": "急促马蹄撞破晨雾，刘家金丝雀纹古装马车从街口冲向太平医馆。陈迹立刻捡起水晶珠：“师父那边出事了。”镜头跟随马车压迫感推进。",
    "09": "太平医馆门口，姚太医上车，刘家人催得很急。佘登科凑近低声说：“刘家死人了，密谍司干的。”陈迹眼神一沉，想起危险。",
    "10": "马车远去，陈迹回头，看见乌云藏在檐下阴影里还没走。陈迹低声：“你也没地方去？”猫影与医馆门形成孤独但紧张的构图。",
    "11": "包子铺蒸汽翻涌，乌云盯着热包子。陈迹看懂它饿了，掏出仅有两枚铜钱递给伙计：“来一个。”画面温暖但节奏快。",
    "12": "医馆门槛，陈迹把包子放下后转身进门。乌云先高傲走开，几步后突然回头叼走包子。这个动作必须清楚可爱但不拖沓。",
    "13": "时间压缩快切感：药斗开合、方子落柜、陈迹称药、正堂空了。师父不在，医馆只剩陈迹守着。对白：陈迹对病患说“按方抓药，诊脉等师父回来。”",
    "14": "夜里正堂，油灯将灭，陈迹趴柜台惊醒，乌云带着新伤蹲在柜台上。陈迹抬眼：“又输了？”灯光暖橙，猫毛凌乱，伤口克制不血腥。",
    "15": "陈迹飞快翻旧医书，抓蛇床子研粉。乌云警惕炸毛，听见陈迹温和声音后慢慢放松。对白：陈迹“别动，我给你止血。”",
    "16": "柜台上药特写，陈迹扒开乌云浓密猫毛轻轻上药。乌云疼得眯眼，却没有躲。手、猫毛、药粉、灯光都要精美细腻。",
    "17": "情感锚点，乌云睡着，脑袋靠在陈迹掌心。陈迹低声：“我在这边，好像也没什么人能信。”只一句，不长独白，暖点必须克制。",
    "18": "陈迹突然做决定，抽出药方纸写聘猫书，把水晶珠放在纸边。对白：陈迹“跟我走吧，聘礼就这颗珠子。”画面要能看出纸、珠、灯、猫。",
    "19": "乌云睁眼，抬爪沾朱砂，在聘猫书上按下红色猫爪印。陈迹怔住：“你真听得懂？”爪印必须是猫爪，不是手印或印章。",
    "20": "终极钩子，镜头必须先看到桌上的聘猫书边缘和小小红色猫爪印，随后纸张边缘无火自燃成星点，立刻切到乌云深灰长毛猫的真实猫脸近景。乌云第一次开口，低声说：“哪不正常？”陈迹只在旁边震惊回头，不能抢画面。重点是猫开口和契约燃烧，不要纸面大特写。神秘、惊艳、克制。"
}


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def shot_duration(shot: Dict[str, Any]) -> int:
    start = int(shot.get("start", 0))
    end = int(shot.get("end", start + 6))
    return max(4, min(8, end - start))


def add_if_exists(refs: List[Path], path: Path) -> None:
    if path.exists() and path not in refs:
        refs.append(path)


def references_for(shot: Dict[str, Any]) -> List[str]:
    chars = set(shot.get("characters") or [])
    props = set(shot.get("props") or [])
    room_id = shot.get("room_id") or ""
    refs: List[Path] = []
    if "CHAR-陈迹-古装" in chars:
        add_if_exists(refs, CHENJI_FACE)
        add_if_exists(refs, CHENJI_GREY_APPRENTICE)
    if "CHAR-乌云-猫" in chars:
        add_if_exists(refs, WUYUN_MAIN)
        add_if_exists(refs, WUYUN_BODY)
        add_if_exists(refs, WUYUN_HEAD)
    if "CHAR-姚太医-古装" in chars:
        add_if_exists(refs, YAO_CARD)
    if room_id == "ROOM-古装-太平医馆学徒寝房-A":
        add_if_exists(refs, DORM)
    if room_id == "ROOM-古装-太平医馆正堂-A":
        add_if_exists(refs, FRONT_HALL)
    if room_id == "SCENE-古装-洛城安西街水井-A":
        add_if_exists(refs, STREET)
    if "PROP-古装-聘猫书" in props or "PROP-古装-朱砂爪印" in props:
        add_if_exists(refs, WUYUN_HEAD)
    return [str(path.resolve()) for path in refs[:9]]


def add_audio_ref(refs: List[Any], ref: Any) -> None:
    if isinstance(ref, Path):
        add_if_exists(refs, ref)
    elif ref and ref not in refs:
        refs.append(ref)


def audio_references_for(shot: Dict[str, Any]) -> List[Any]:
    shot_id = str(shot["id"]).zfill(2)
    chars = set(shot.get("characters") or [])
    refs: List[Any] = []
    if shot_id == "20":
        add_audio_ref(refs, VOICE_WUYUN)
        add_audio_ref(refs, SFX_CONTRACT)
    elif shot_id == "09":
        add_audio_ref(refs, VOICE_SHENDENGKE)
    elif "CHAR-陈迹-古装" in chars:
        add_audio_ref(refs, VOICE_CHENJI)
    add_audio_ref(refs, AMB_TAIPING)
    if shot_id == "07":
        add_audio_ref(refs, SFX_BEAD)
    normalized = []
    for ref in refs:
        if isinstance(ref, Path):
            normalized.append(str(ref.resolve()))
        else:
            normalized.append(ref)
    return normalized


def audio_ref_name(ref: Any) -> str:
    if isinstance(ref, dict):
        return ref.get("label") or ref.get("asset_id") or ref.get("url") or "audio asset"
    return Path(str(ref)).name


def prompt_for(shot: Dict[str, Any], refs: List[str], audio_refs: List[str]) -> str:
    shot_id = str(shot["id"]).zfill(2)
    ref_lines = "\n".join(f"- 图片{idx}: {Path(path).name}" for idx, path in enumerate(refs, 1))
    if not ref_lines:
        ref_lines = "- 无本地图片参考，严格按文字锚点。"
    audio_ref_lines = "\n".join(f"- 音频{idx}: {audio_ref_name(ref)}" for idx, ref in enumerate(audio_refs, 1))
    if not audio_ref_lines:
        audio_ref_lines = "- 无音频参考，本镜头只能环境声或动作声。"
    chars = "、".join(shot.get("characters") or []) or "无"
    props = "、".join(shot.get("props") or []) or "无"
    return f"""{COMMON_RULES}

《青山》E09《聘猫入局》高节奏 API 镜头 {shot_id}

参考图片顺序：
{ref_lines}

声音参考顺序：
{audio_ref_lines}

连续性锚点：
- 场景：{shot.get("room_id")}
- 角色：{chars}
- 道具：{props}

本镜头内容：
{SHOT_PROMPTS[shot_id]}

执行硬规则：
1. 陈迹若出现，必须同时锁定陈迹原始古装参考脸和灰布学徒参考卡：20岁左右、清瘦、少年感、脸部柔和但警觉、灰布学徒长衫、发髻朴素、无眼镜；不得成熟中年化、不得额头发际线老化、不得换脸、不得穿深绿/深黑正式长袍。
2. 乌云若出现，必须是深灰/乌黑长毛猫，脖颈毛蓬松，聪明冷淡，眉骨有新伤；绝不能生成人、白猫、橘猫、短毛纯黑猫、卡通猫或红眼妖兽。
3. 本镜头不能有模型自带字幕、英文、乱码、现代物件或欧美人物。
4. 必须使用随请求提供的音频参考作为本镜头的声音锚点：同一 VOICE-ID 的音色、年龄感、语速和口音必须继承，不能随机换声线。
5. 台词必须由视频模型原生生成中文普通话，并与可见嘴形同步；不能后配、不能无口型、不能只靠字幕，不能英文或外语。
6. 本镜头必须同时生成真实环境声、动作拟音和必要的轻 BGM/SFX；对白优先，BGM 不盖台词。猫在第20镜前不能开口，只能用猫呼吸、爪步、轻叫和动作声。
7. 第20镜的爪印必须是小猫爪印，绝不能像人手掌印；第20镜必须出现乌云猫脸开口说话和聘猫书燃烧，不能只拍纸或陈迹正脸。
8. 画面要精美绝伦但节奏快，镜头结尾留半秒动作或声音接点，便于剪辑。
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build E09 high-tempo API run_plan.")
    parser.add_argument("--continuity", default=str(ROOT / "configs/e09_continuity_config_v2_20shots_fast_20260709.json"))
    parser.add_argument("--out-dir", default=str(ROOT / "working_assets/e09_api_20260709"))
    parser.add_argument("--shots", nargs="*", default=[f"{i:02d}" for i in range(1, 21)])
    args = parser.parse_args()

    continuity = load_json(Path(args.continuity))
    requested = {shot.zfill(2) for shot in args.shots}
    out_dir = Path(args.out_dir).resolve()
    prompt_dir = out_dir / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)

    shots_by_id = {str(shot.get("id")).zfill(2): shot for shot in continuity["shots"]}
    plan: List[Dict[str, Any]] = []
    for shot_id in sorted(requested):
        shot = shots_by_id.get(shot_id)
        if not shot:
            raise SystemExit(f"Missing continuity shot {shot_id}")
        refs = references_for(shot)
        audio_refs = audio_references_for(shot)
        prompt_path = prompt_dir / f"e09_shot_{shot_id}.txt"
        prompt_path.write_text(prompt_for(shot, refs, audio_refs), encoding="utf-8")
        plan.append({
            "shot_id": shot_id,
            "title": f"E09 Shot{shot_id}",
            "duration": shot_duration(shot),
            "prompt_file": str(prompt_path),
            "references": refs,
            "audio_references": audio_refs,
            "out_dir": str((out_dir / "videos" / f"shot_{shot_id}").resolve()),
            "models": ["seedance-2.0-pro", "sora2", "veo3.1", "wan2.7", "kling"]
        })

    plan_path = out_dir / "run_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"shots": len(plan), "run_plan": str(plan_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
