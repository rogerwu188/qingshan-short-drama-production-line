#!/usr/bin/env python3
"""
Build E11 Giggle API run plan from the director-coverage continuity config.

Hard locks:
- Chenji generation uploads use only the young grey apprentice stage reference.
- Chenji speaking shots include native multimodal voice asset cypqud0bu7t.
- Long Chinese prop text is forbidden in generation and reserved for compositing.
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
STREET = ROOT / "assets/reference/e08_api_fallback_20260709/scenes/SCENE-luocheng-stone-street-clean-20260709.jpg"
YAO_CARD = ROOT / "assets/reference/e08_api_fallback_20260709/characters/CHAR-yao-taiyi-card-clean-20260709.jpg"

VOICE_CHENJI_SAMPLE = ROOT / "libraries/audio/voice_refs/native_multimodal_20260709/VOICE-陈迹-古装/e09_shot01_chenji_native_voice_ref.wav"
VOICE_WUYUN_SAMPLE = ROOT / "libraries/audio/voice_refs/e09_voice_locked_20260709/shot_20_VOICE-乌云-猫-final-hook-only.wav"

VOICE_CHENJI = {
    "asset_id": "cypqud0bu7t",
    "url": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/yzp8lyx7vw.wav",
    "label": "VOICE-陈迹-古装 原生多模态样本 E09 shot01",
    "local_sample": str(VOICE_CHENJI_SAMPLE),
}
VOICE_WUYUN = {
    "label": "VOICE-乌云-猫 final hook",
    "local_sample": str(VOICE_WUYUN_SAMPLE),
}
AMB_TAIPING = {
    "asset_id": "2qmyh0s1y4u",
    "url": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/e62k24lugn.wav",
    "label": "AMB-太平医馆夜间",
}
SFX_COLD_STING = {
    "asset_id": "mqqctllu0t",
    "url": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/yx2utk1xpfj.wav",
    "label": "MUSIC/SFX-命案悬疑低频",
}
SFX_BEAD = {
    "asset_id": "kaf7n6ahi3",
    "url": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/w0fyi60slrc.wav",
    "label": "SFX-证据冷光",
}

COMMON_RULES = """中文真人古装竖屏短剧，9:16，720p，电影级写实画面。高节奏但不快切，平均镜头 5-7 秒，镜头必须推进剧情。严格保持角色、猫、道具、场景、服装、声音一致。禁止模型自带字幕、英文、乱码文字、现代物件、欧美人物、随机换脸、道具漂移、场景漂移。长中文道具文字必须生成为空白纸/空白书页，后期合成真字。对白必须普通话中文、声音与口型同步，不能静音，不能只靠字幕。"""

SHOT_PROMPTS: Dict[str, str] = {
    "01": "前 3 秒硬钩子。夜半太平医馆门外，木轮急停，湿草席裹着疑似尸体滑到门槛；乌云在门槛暗处低声说“他回来了。”镜头压低，草席、猫眼、门灯灭亮形成危机，不出现标题卡。",
    "02": "two-shot。陈迹和乌云同在门槛边，陈迹穿年轻灰布学徒袍，手中水晶珠微亮，草席在脚边。风吹灯影，陈迹不说话但立刻进入判断，不能是单人肖像。",
    "03": "insert evidence。湿草席结口、灰白药粉、黑灰痕迹近景；绝对禁止任何文字、符号、假汉字。纸草纤维、湿痕、药粉和绳结清楚，声音有草席摩擦和夜风。",
    "04": "OTS-A。从乌云肩后看陈迹，陈迹看向画面右下的草席和猫，低声说“死人怎么会自己回来？”视线轴线清楚，表情从惊疑到克制。陈迹必须是参考图里的年轻灰布学徒脸：约 20 岁、清瘦、脸部干净、无法令纹、无中年掌柜感。为了避免成熟化，使用侧脸或三分之二侧脸、半身中景，不要正面大特写，不要强硬掌柜表情。",
    "05": "OTS-B。从陈迹肩后或低角度看乌云，灰黑长毛猫不人化，耳侧旧伤可见。乌云说“被人送回来的。”与上一镜视线方向匹配。",
    "06": "group blocking。太平医馆正堂被吵醒，姚太医、瘦高师兄、陈迹形成三角站位，灯、药柜、门槛地理清楚。众人看到草席，医馆恐慌但不乱切。",
    "07": "arrival pressure。刘家来人冲入正堂，和陈迹同框但不要借用陈迹脸。刘家来人急声说“这不是刘家的人。”陈迹观察他而不是立刻辩解。",
    "08": "reaction。陈迹注意到刘家来人袖口黑灰，视线落点明确。中景保留刘家来人半身和药柜背景，表情从怀疑到抓住线索。",
    "09": "macro clue。袖口黑灰、灰白药粉、细黑线、小银针近景。无文字，无乱码，无血腥；手部动作真实，药粉和线不要穿模。",
    "10": "two-shot conflict。姚太医压低声音对陈迹说“今夜的事，一个字都别往外说。”陈迹侧身听，压迫感来自两人距离和药柜阴影，保持空间连续。陈迹必须年轻，不要成熟化、掌柜化、胡茬重或脸型变宽。",
    "11": "medical action。陈迹跪在草席边检查脉象和肤色，说“这人死过，也活过。”声音必须使用陈迹原生多模态参考，口型同步，手法克制专业。镜头保留年轻灰布学徒脸，不能变成中年医师。",
    "12": "cat action insert。乌云用猫爪拨开衣领边缘，不人化，找到结口异样。猫爪、布料、黑线局部真实，避免可爱摆拍。",
    "13": "macro clue reversal。衣领下隐藏针孔、细黑线和药粉冷光，珠子轻响。不能出现文字或字幕；证据表达为“同一药痕，却不是同一个死人”。",
    "14": "surveillance OTS。夜街暗处密谍司暗桩看向医馆门口，黑牌只可出现单字“密”或空牌。低调威胁，不要大面积文字。",
    "15": "group pressure。医馆门口一镜容纳刘家来人、姚太医、陈迹、暗桩方向和草席，空间关系明确。所有人都想把尸体移走，陈迹被夹在中间。",
    "16": "insert prop bead。陈迹趁乱把黑线样本收入袖中，水晶珠在掌心冷亮。手、袖口、珠子、线样本必须连贯，声音有细线摩擦和冷响。",
    "17": "two-shot warning。陈迹和乌云在柜台阴影处同框，乌云说“他们不是查案，是查你。”陈迹听后没有慌，眼神转为设局。陈迹必须与年轻灰布学徒参考图一致，脸部干净年轻，不能成熟掌柜化。用中景、侧脸或低头听猫的构图，避免正面肖像感和中年化五官。",
    "18": "decision medium。夜街边，陈迹拿着药粉痕迹低声说“那就让他们看见我想让他们看见的。”必须是年轻灰布学徒，不成熟化，不华服。",
    "19": "tracking geography。陈迹沿车轮印和灰迹走向冷色官方暗巷，远处暗桩压迫。保留街巷地理、车轮痕、方向感，不能变成单人正脸封面。",
    "20": "cliffhanger insert。正堂草席忽然轻动，乌云回头说“下一个，轮到太平医馆。”灯芯一灭，留强悬念；不要把字幕烘焙进画面。"
}

CHENJI_SPEAKING = {"04", "11", "18"}
WUYUN_SPEAKING = {"01", "05", "17", "20"}


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
    if room in {"ROOM-古装-太平医馆正堂-A", "ZONE-太平医馆门口-A"}:
        add_if_exists(refs, FRONT_HALL)
    if room in {"SCENE-古装-洛城夜街-A", "ALLEY-密谍司暗巷-A"}:
        add_if_exists(refs, STREET)
    return [str(path.resolve()) for path in refs[:9]]


def audio_references_for(shot: Dict[str, Any]) -> List[Any]:
    shot_id = str(shot["id"]).zfill(2)
    refs: List[Any] = [AMB_TAIPING]
    if shot_id in CHENJI_SPEAKING:
        refs.insert(0, VOICE_CHENJI)
    if shot_id in WUYUN_SPEAKING:
        refs.insert(0, VOICE_WUYUN)
    if shot_id in {"01", "13", "16", "20"}:
        refs.append(SFX_BEAD)
    if shot_id in {"01", "14", "19", "20"}:
        refs.append(SFX_COLD_STING)
    return refs


def normalize_audio_refs(refs: List[Any]) -> List[Any]:
    normalized: List[Any] = []
    for ref in refs:
        if isinstance(ref, dict):
            if ref.get("asset_id") or ref.get("url"):
                normalized.append({key: ref[key] for key in ("asset_id", "url") if ref.get(key)})
            else:
                # Giggle's omni-video endpoint currently rejects base64 audio
                # in the audios array; keep local-only samples as prompt
                # guidance but do not submit them as API audio references.
                continue
        elif str(ref).startswith(("http://", "https://")):
            normalized.append(str(ref))
        else:
            path = Path(str(ref)).expanduser()
            if path.exists():
                normalized.append(str(path.resolve()))
    return normalized


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
    dialogue = shot.get("dialogue") or "无对白"
    return f"""{COMMON_RULES}

《青山》E11《死人回门》API 镜头 {shot_id}

参考图片：
{image_lines}

声音参考：
{audio_lines}

连续性锚点：
- 场景：{shot.get("room_id") or shot.get("zone_id")}
- 覆盖类型：{shot.get("coverage")}
- 角色：{chars}
- 道具：{props}
- 本镜对白：{dialogue}

本镜头导演指令：
{SHOT_PROMPTS[shot_id]}

执行硬规则：
1. 陈迹出现时，视频生成上传参考图只能使用 E10 年轻灰布学徒阶段图，不得同时上传主参考脸或其他年龄阶段图；主参考脸只作为身份根锚点用于文字规则和 QA，不作为本阶段视频生成图片输入。陈迹必须约 20 岁、清瘦、灰布学徒袍、束发、无眼镜，不能成熟中年化，不能穿贵气华服。
2. 乌云出现时必须是灰黑长毛猫，毛色、头身比例、耳侧旧伤和聪明冷眼一致，绝不人化。
3. 陈迹说话镜头必须用 `VOICE-陈迹-古装` / asset `cypqud0bu7t` 作为多模态声音参考，声音和口型原生同步，不能后期配音感。
4. 画面内长中文必须为空白纸、空白牌或不可读留白；字幕不要烘焙进视频画面。黑牌只允许单字“密”，不稳则留空后期合成。
   背景招牌不要生成任何汉字或伪字，招牌区域宁可空白木牌；“概不赊”等短字由后期真字合成。
5. 必须有环境声和动作拟音：草席、车轮、药柜、衣料、猫爪、脚步、灯芯、珠子冷响按镜头需要出现；BGM 只轻铺，不盖对白。
6. 镜头语言不能退回居中单人肖像。按覆盖类型执行 two-shot、OTS、group、insert、reaction、tracking 或 macro clue。
7. 结尾留出 0.3-0.5 秒动作或声音接点，便于剪辑衔接。
8. 若本镜头是病案、药账、草席线索、令牌等文字道具特写，表面必须保持空白或只出现单个明确短字；禁止模型生成任何长文字、伪汉字、点阵、乱码、行状墨迹。
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build E11 API run plan.")
    parser.add_argument("--continuity", default=str(ROOT / "configs/e11_continuity_config_20shots_20260710.json"))
    parser.add_argument("--out-dir", default=str(ROOT / "working_assets/e11_api_20260710"))
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
        normalized_audio_refs = normalize_audio_refs(audio_refs)
        prompt_path = prompt_dir / f"e11_shot_{shot_id}.txt"
        prompt_path.write_text(prompt_for(shot, refs, audio_refs), encoding="utf-8")
        plan.append({
            "shot_id": shot_id,
            "title": f"E11 Shot{shot_id}",
            "duration": shot_duration(shot),
            "prompt_file": str(prompt_path),
            "references": refs,
            "audio_references": normalized_audio_refs,
            "out_dir": str((out_dir / "videos" / f"shot_{shot_id}").resolve()),
            "models": ["seedance-2.0-pro", "sora2", "veo3.1", "wan2.7", "kling"],
        })

    plan_path = out_dir / "run_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"shots": len(plan), "run_plan": str(plan_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
