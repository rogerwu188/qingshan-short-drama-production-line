#!/usr/bin/env python3
"""
Build E10 Giggle API run plan from the passed director-coverage continuity config.

This script writes one prompt per shot and a run_plan.json for
tools/run_giggle_api_plan.py. API keys are not read or written here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]

CHENJI_YOUNG = ROOT / "assets/reference/e10_20260709/characters/CHAR-chenji-young-apprentice-canonical-v2-20260709.jpg"
WUYUN_MAIN = ROOT / "ref_images/cat_wuyun_reference.jpg"
WUYUN_BODY = ROOT / "ref_images/cat_wuyun_body_ref.jpg"
WUYUN_HEAD = ROOT / "ref_images/cat_wuyun_head_ref.jpg"
FRONT_HALL = ROOT / "assets/reference/e08_api_fallback_20260709/scenes/SCENE-taiping-front-hall-clean-20260709.jpg"
DORM = ROOT / "assets/reference/e08_api_fallback_20260709/scenes/SCENE-taiping-apprentice-dorm-clean-20260709.jpg"
STREET = ROOT / "assets/reference/e08_api_fallback_20260709/scenes/SCENE-luocheng-stone-street-clean-20260709.jpg"
YAO_CARD = ROOT / "assets/reference/e08_api_fallback_20260709/characters/CHAR-yao-taiyi-card-clean-20260709.jpg"

VOICE_CHENJI_SAMPLE = ROOT / "libraries/audio/voice_refs/native_multimodal_20260709/VOICE-陈迹-古装/e09_shot01_chenji_native_voice_ref.wav"
VOICE_SHIXIONG_SAMPLE = ROOT / "libraries/audio/voice_refs/e09_voice_locked_20260709/shot_09_VOICE-佘登科.wav"

VOICE_CHENJI = {
    "asset_id": "cypqud0bu7t",
    "url": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/yzp8lyx7vw.wav",
    "label": "VOICE-陈迹-古装 原生多模态样本 E09 shot01",
    "local_sample": str(VOICE_CHENJI_SAMPLE),
}
AMB_TAIPING = {
    "asset_id": "2qmyh0s1y4u",
    "url": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/e62k24lugn.wav",
    "label": "AMB-太平医馆晨夜空间",
}
SFX_BEAD = {
    "asset_id": "mqqctllu0t",
    "url": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/yx2utk1xpfj.wav",
    "label": "SFX-水晶珠冷光震动",
}
SFX_CONTRACT = {
    "asset_id": "kaf7n6ahi3",
    "url": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/w0fyi60slrc.wav",
    "label": "SFX-契约纸页与悬疑点",
}

COMMON_RULES = """中文真人古装竖屏短剧，9:16，720p，电影级写实画面。高节奏但不快切，平均镜头 5-7 秒，镜头必须推进剧情。严格保持角色、猫、道具、场景、服装、声音一致。禁止模型自带字幕、英文、乱码文字、现代物件、欧美人物、随机换脸、道具漂移、场景漂移。长中文道具文字必须生成为空白纸/空白书页，后期合成真字。对白必须普通话中文、声音与口型同步，不能静音，不能只靠字幕。"""

SHOT_PROMPTS: Dict[str, str] = {
    "01": "危机钩子。夜灯下，乌云的灰黑猫爪按住一页旧病案，病案纸必须空白无乱码。猫抬头低声说“这人，不是病死的。”陈迹的手只在画面边缘猛地停住。猫爪纸响、灯芯轻爆，3 秒内给出命案危险。",
    "02": "two-shot。陈迹和乌云同在学徒寝房桌边，油灯、珠子、聘猫契约、旧病案在桌上，空间连续。陈迹压低声音说“你再说一遍。”情绪从惊到警觉再到强压慌乱，手指按住珠子。",
    "03": "OTS-A。从乌云肩后看陈迹，陈迹看向画面左下的猫和病案，手指压着珠子。陈迹说“刘家死人，跟太平医馆有什么关系？”保持视线方向，不能正面卡片化。",
    "04": "OTS-B。从陈迹肩后看乌云，灰黑长毛猫坐在桌上，耳侧旧伤可见，猫尾扫过纸边。乌云低声说“关系在药里。”保持与上一镜的轴线和视线匹配。",
    "05": "insert。旧病案/药账近景，纸面必须完全空白，只保留纸张纤维、折痕、污渍和边缘磨损；绝对不能出现任何汉字、假汉字、点阵、行列、符号、墨迹、类似文字的纹理或图案。陈迹指尖只沿空白位置划过，纸张和指腹摩擦声必须清楚，油灯环境声可听见。后期将另行合成真字。",
    "06": "establishing。清晨太平医馆正堂，药柜、门口晨光、柜台、姚太医背影和瘦高师兄在远处忙碌，地理关系清楚。无长文字，药柜抽屉声做声桥。",
    "07": "group blocking。医馆里陈迹、瘦高师兄、姚太医形成三角站位。瘦高师兄急道“刘家又来人了。”陈迹藏住珠子，姚太医观察他，空间不能塌成单人特写。",
    "08": "reaction。陈迹听到刘家二字后短促抬眼，手指收紧，表情从克制到怀疑再到决意。不是大特写，保留药柜背景和晨光。",
    "09": "two-shot。医馆门口刘家来人递上旧病案/药账，陈迹接过，姚太医在旁边观察。刘家来人说“昨夜三更，人没了。”纸面不要乱码。",
    "10": "insert reversal。病案/旧书页近景，珠子在纸边泛冷光。纸面必须完全空白，只能有纸张纤维、折痕、污渍、光影和珠子冷光；绝对不能出现任何汉字、假汉字、点阵、行列、符号、墨迹、印刷线、类似文字的纹理或图案。画面表达：这不是寒毒，是有人借寒毒杀人。后期会另行合成“寒热错杂、脉沉而乱”。",
    "11": "OTS-A。陈迹对姚太医，视线向右，低声试探说“若是寒毒，脉不该乱成这样。”情绪从试探到确认，声音必须继承陈迹原生样本。",
    "12": "OTS-B。姚太医看向陈迹，视线向左，表情一沉，说“谁教你看的？”保持上一镜 180 度轴线，不要换场景。",
    "13": "reaction insert。桌下乌云轻叫，猫爪碰陈迹鞋边，提醒他闭嘴。只要猫爪、衣摆、鞋边和药包局部，动作真实，不人化。",
    "14": "low two-shot。陈迹蹲下假装捡药包，和桌下乌云同框。陈迹低声说“你想让我查？”乌云盯向门外，猫眼聪明冷静。",
    "15": "group pressure。医馆门口密谍司暗桩或黑牌一闪，瘦高师兄挡在门口，陈迹在后方意识到压力。黑牌只允许单字“密”或空牌，不能出现乱码。",
    "16": "tracking。陈迹跟着刘家来人和药包走出医馆，乌云从屋檐或墙根跟随，空间方向和上一镜一致。街市、脚步、猫爪声清楚。",
    "17": "insert second evidence。药包里露出不该出现的灰白药粉或药渣，珠子反应更强。证据升级，不血腥，手和药粉不能穿模。",
    "18": "mini OTS pair / two-shot。晨街边陈迹对乌云低声说“有人在拿太平医馆做局。”乌云看向相反方向回答“也在拿你做饵。”陈迹声音和猫声都要自然，避免快切晃眼。",
    "19": "reaction geography。陈迹站在晨街人群边，意识到自己被盯上；远处有深色车影或密谍司暗桩，手中黑牌只作为小面积视觉压力，不要可读长字。不是单人大特写，必须保留街道地理、人群和威胁方向。绝对禁止画面中出现任何字幕、对白文字、提示字、汉字浮层、烧录字样或类似“来了”的文字。",
    "20": "cliffhanger。乌云跳上墙头回头说“今晚别睡，死人会回来找你。”陈迹抬头，远处太平医馆门内灯忽然灭。结尾钩子明确进入 E11。"
}


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def shot_duration(shot: Dict[str, Any]) -> int:
    return max(4, min(8, int(shot.get("end", 0)) - int(shot.get("start", 0))))


def add_if_exists(refs: List[Path], path: Path) -> None:
    if path.exists() and path not in refs:
        refs.append(path)


def references_for(shot: Dict[str, Any]) -> List[str]:
    chars = set(shot.get("characters") or [])
    room = shot.get("room_id") or shot.get("zone_id") or ""
    refs: List[Path] = []
    if "CHAR-陈迹-古装" in chars:
        add_if_exists(refs, CHENJI_YOUNG)
    if "CHAR-乌云-猫" in chars:
        add_if_exists(refs, WUYUN_MAIN)
        add_if_exists(refs, WUYUN_BODY)
        add_if_exists(refs, WUYUN_HEAD)
    if "CHAR-姚太医-古装" in chars:
        add_if_exists(refs, YAO_CARD)
    if room == "ROOM-古装-太平医馆学徒寝房-A":
        add_if_exists(refs, DORM)
    if room == "ROOM-古装-太平医馆正堂-A" or room == "ZONE-太平医馆门口-A":
        add_if_exists(refs, FRONT_HALL)
    if room == "SCENE-古装-洛城晨街-A":
        add_if_exists(refs, STREET)
    return [str(path.resolve()) for path in refs[:9]]


def audio_references_for(shot: Dict[str, Any]) -> List[Any]:
    shot_id = str(shot["id"]).zfill(2)
    chars = set(shot.get("characters") or [])
    refs: List[Any] = [AMB_TAIPING]
    if "CHAR-陈迹-古装" in chars and shot_id in {"02", "03", "11", "14", "18"}:
        refs.insert(0, VOICE_CHENJI)
    if "CHAR-乌云-猫" in chars and shot_id in {"01", "04", "18", "20"}:
        refs.append(SFX_CONTRACT)
    if "CHAR-太平医馆瘦高师兄" in chars and shot_id == "07":
        refs.append(AMB_TAIPING)
    if shot_id in {"10", "17"}:
        refs.append(SFX_BEAD)
    if shot_id in {"01", "20"}:
        refs.append(SFX_CONTRACT)
    return refs


def audio_name(ref: Any) -> str:
    if isinstance(ref, dict):
        return ref.get("label") or ref.get("asset_id") or "audio asset"
    return Path(str(ref)).name


def prompt_for(shot: Dict[str, Any], refs: List[str], audio_refs: List[Any]) -> str:
    shot_id = str(shot["id"]).zfill(2)
    image_lines = "\n".join(f"- 图片{idx}: {Path(path).name}" for idx, path in enumerate(refs, 1)) or "- 无图片参考，按文字锚点生成。"
    audio_lines = "\n".join(f"- 音频{idx}: {audio_name(ref)}" for idx, ref in enumerate(audio_refs, 1)) or "- 无声音参考。"
    chars = "、".join(shot.get("characters") or []) or "无"
    props = "、".join(shot.get("props") or []) or "无"
    return f"""{COMMON_RULES}

《青山》E10《猫口命案》API 镜头 {shot_id}

参考图片：
{image_lines}

声音参考：
{audio_lines}

连续性锚点：
- 场景：{shot.get("room_id") or shot.get("zone_id")}
- 覆盖类型：{shot.get("coverage")}
- 角色：{chars}
- 道具：{props}

本镜头导演指令：
{SHOT_PROMPTS[shot_id]}

执行硬规则：
1. 陈迹出现时，视频生成上传参考图只能使用 E10 年轻灰布学徒阶段图，不得同时上传主参考脸或其他年龄阶段图；主参考脸只作为身份根锚点用于文字规则和人工 QA，不作为本阶段视频生成图片输入。陈迹必须约 20 岁、清瘦、灰布学徒袍、束发、无眼镜，不能成熟中年化，不能穿贵气华服。
   陈迹镜头必须优先复制 E10 年轻灰布学徒三视图的年龄、脸型、发际线和衣服旧损；禁止生成 35 岁以上成熟男、法令纹重、贵气掌柜脸、深色正式袍或不同演员脸。
2. 乌云出现时必须是灰黑长毛猫，毛色、头身比例、伤口状态一致，绝不人化。
3. 陈迹说话镜头必须用 `VOICE-陈迹-古装` / asset `cypqud0bu7t` 作为多模态声音参考，声音和口型原生同步，不能后期配音感。
4. 画面内长中文必须为空白纸或不可读留白；字幕不要烘焙进视频画面。
5. 必须有环境声和动作拟音：纸张、药柜、衣料、猫爪、脚步、灯芯、珠子冷响按镜头需要出现；BGM 只轻铺，不盖对白。
6. 镜头语言不能退回居中单人肖像。按覆盖类型执行 two-shot、OTS、group、insert、reaction 或 tracking。
7. 结尾留出 0.3-0.5 秒动作或声音接点，便于剪辑衔接。
8. 若本镜头是病案、药账、聘猫契约、医书、令牌等文字道具特写，纸面必须保持空白或只出现单个明确短字；禁止模型生成任何长文字、伪汉字、点阵、乱码、行状墨迹。
"""


def normalize_audio_refs(refs: List[Any]) -> List[Any]:
    normalized: List[Any] = []
    for ref in refs:
        if isinstance(ref, dict):
            normalized.append(ref)
        elif str(ref).startswith(("http://", "https://")):
            normalized.append(str(ref))
        else:
            path = Path(str(ref)).expanduser()
            if path.exists():
                normalized.append(str(path.resolve()))
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(description="Build E10 API run plan.")
    parser.add_argument("--continuity", default=str(ROOT / "configs/e10_continuity_config_20shots_director_coverage_20260709.json"))
    parser.add_argument("--out-dir", default=str(ROOT / "working_assets/e10_api_20260709"))
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
        audio_refs = normalize_audio_refs(audio_references_for(shot))
        prompt_path = prompt_dir / f"e10_shot_{shot_id}.txt"
        prompt_path.write_text(prompt_for(shot, refs, audio_refs), encoding="utf-8")
        plan.append({
            "shot_id": shot_id,
            "title": f"E10 Shot{shot_id}",
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
