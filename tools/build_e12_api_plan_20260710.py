#!/usr/bin/env python3
"""
Build E12 Giggle API run plan from the director-coverage continuity config.

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
BAILI_CARD = ROOT / "assets/reference/characters_canonical_20260709/images/CHAR-baili-ancient-card-20260709.jpg"
FRONT_HALL = ROOT / "assets/reference/e08_api_fallback_20260709/scenes/SCENE-taiping-front-hall-clean-20260709.jpg"
STREET = ROOT / "assets/reference/e08_api_fallback_20260709/scenes/SCENE-luocheng-stone-street-clean-20260709.jpg"
YAO_CARD = ROOT / "assets/reference/e08_api_fallback_20260709/characters/CHAR-yao-taiyi-card-clean-20260709.jpg"
E12_SHOT16_VISUAL_LOCK = ROOT / "assets/reference/e12_visual_locks_20260710/shot_16_visual_lock.png"
E12_SHOT17_VISUAL_LOCK = ROOT / "assets/reference/e12_visual_locks_20260710/shot_17_visual_lock.png"
E12_SHOT18_VISUAL_LOCK = ROOT / "assets/reference/e12_visual_locks_20260710/shot_18_visual_lock.png"
E12_SHOT19_VISUAL_LOCK = ROOT / "assets/reference/e12_visual_locks_20260710/shot_19_visual_lock.png"
E12_SHOT20_VISUAL_LOCK = ROOT / "assets/reference/e12_visual_locks_20260710/shot_20_visual_lock.png"

VOICE_CHENJI_SAMPLE = ROOT / "libraries/audio/voice_refs/native_multimodal_20260709/VOICE-陈迹-古装/e09_shot01_chenji_native_voice_ref.wav"
VOICE_WUYUN_SAMPLE = ROOT / "libraries/audio/voice_refs/e09_voice_locked_20260709/shot_20_VOICE-乌云-猫-final-hook-only.wav"
AUDIO_ASSET_REGISTRY = ROOT / "configs/e12_audio_asset_registry_20260710.json"

VOICE_CHENJI = {
    "asset_id": "cypqud0bu7t",
    "url": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/yzp8lyx7vw.wav",
    "label": "VOICE-陈迹-古装 原生多模态样本 E09 shot01",
    "local_sample": str(VOICE_CHENJI_SAMPLE),
}
def registered_audio_ref(asset_key: str, local_sample: Path, label: str) -> Dict[str, Any]:
    ref: Dict[str, Any] = {
        "label": label,
        "local_sample": str(local_sample),
        "submit_local_sample": True,
    }
    if not AUDIO_ASSET_REGISTRY.exists():
        return ref
    registry = json.loads(AUDIO_ASSET_REGISTRY.read_text(encoding="utf-8"))
    asset = (registry.get("assets") or {}).get(asset_key) or {}
    remote_asset_id = asset.get("remote_asset_id") or asset.get("giggle_asset_id") or asset.get("asset_id")
    remote_url = asset.get("remote_url") or asset.get("url")
    source_urls = (asset.get("source") or {}).get("urls") or []
    if not remote_url and source_urls:
        remote_url = source_urls[0]
    if remote_asset_id or remote_url:
        ref.pop("submit_local_sample", None)
        if remote_asset_id:
            ref["asset_id"] = remote_asset_id
        if remote_url:
            ref["url"] = remote_url
    return ref


VOICE_WUYUN = registered_audio_ref(
    "VOICE-乌云-猫-final-hook-only",
    VOICE_WUYUN_SAMPLE,
    "VOICE-乌云-猫 final hook",
)
VOICE_BAILI = {
    "label": "VOICE-白鲤-古装 待从 E12 合格原生多模态片段提取",
    "voice_design": "young controlled female voice, calm but dangerous, ancient diction, no modern accent, no breathy idol tone",
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
    "01": "前 3 秒硬钩子。太平医馆灯刚灭，门缝下滑入一张被黑药汁染过的旧药方；门外帷帽女子白鲤只露袖口和影子，低声说“别救他，救你自己。”镜头压低贴地，药方、门缝、女客影子同时构成危机。药方必须是完全空白破旧宣纸：没有汉字、没有英文、没有表格线、没有横线、没有印刷痕、没有符号、没有伪字；只允许黑药汁污迹和烧焦边缘。若需要文字，后期再合成。",
    "02": "two-shot。陈迹和乌云在油灯旁同时停住，陈迹穿年轻灰布学徒袍，乌云是灰黑长毛猫。两者都看向门缝药方，空间必须连着太平医馆正堂和门口，不要单人封面式特写。原生声场是本镜硬交付：清晰可听到灯芯噼啪、陈迹衣料轻响、乌云猫爪抓木与短促低鸣、门外风声和纸张摩擦；不得静音，不得只有微弱底噪。",
    "03": "insert evidence。黑染药方、灰白药粉、细黑线三者近景；纸面必须完全空白，不能有表格线、横线、伪字、印刷痕或任何文字。原生拟音必须清晰可听：纸张拖过木桌、药粉细落、细线刮过纸面、远处药柜木响和灯芯噼啪；不得静音或只有微弱底噪。",
    "04": "OTS-A。从白鲤帷帽影子后看陈迹半开门缝，陈迹低声问“你到底是谁？”陈迹必须约 20 岁、清瘦、灰布学徒脸，不能成熟中年化。白鲤只露帷帽、肩线和袖口，保持神秘。",
    "05": "OTS-B。从陈迹肩后看门外白鲤，帷帽遮脸但轮廓稳定，声音冷静说“刘家死的，不是刘家人。”视线方向与上一镜匹配，门缝构图制造压迫。",
    "06": "reaction two-shot。乌云挡在门前，陈迹手按水晶珠，灯影在药柜上抖动。乌云不人化，用四足正常站立或蹲伏的灰黑长毛猫姿态挡住门，猫爪只能落在地面/门槛/木柜，绝不双足站立、绝不举起前爪做人的手势。陈迹看向门缝，乌云身体阻止他贸然开门，表现它闻到危险。原生声场必须清晰可听：乌云短促低鸣和猫爪抓木、陈迹袖口擦过柜台、珠子一声冷响、门外风雨与灯芯噼啪；不得静音或只有微弱底噪。",
    "07": "two-shot doorway。画面中只能有陈迹和白鲤两人：陈迹只把门开一条缝，白鲤站在湿冷街边，二人同框但保持距离；乌云留在室内画外，绝不出现在画面。白鲤不是装饰性美女，她掌握证据和节奏。门、药方、街灯、药柜方向清楚。原生声场必须有门轴、雨声、二人衣料和远处街灯风声，清晰可听，不得静音。",
    "08": "insert identity clue。白鲤袖口边缘有小小烧痕或隐印，不能出现长字；可出现抽象鲤纹或单个短符号但不强求。镜头只给一瞬，作为后续身份线索。",
    "09": "female medium reveal。白鲤在洛城夜街半身中景，帷帽遮住部分脸但身份锚稳定，低声说“有人要借你的手，洗掉官巷的血。”她的语气冷静危险，不是柔弱求助。她不递出、手持或展示任何写字纸条、信件、令签、告示或可读文字道具；双手保持空手或收在袖中，画面中任何纸张必须背面朝镜头且完全空白。",
    "10": "reaction。陈迹在正堂内把药粉、黑线、药方三条线索连起来，眼神从疑惑转成判断。必须年轻灰布学徒，不要成熟掌柜脸，不要单纯凝视。",
    "11": "group blocking。刘家来人带人闯进太平医馆，白鲤在门外阴影旁观察，陈迹被夹在药柜、来人、门口之间。多人空间清楚，白鲤仍在控制局面。",
    "12": "OTS-servant。刘家来人指向陈迹，急声说“太平医馆藏了证据。”来人必须是与陈迹明确不同的四十岁左右富户管事：略胖方脸、短须、深靛蓝管事袍、不同发髻和不同眉眼；禁止复用年轻灰布陈迹脸、服装、体型或发型。",
    "13": "OTS-chenji。陈迹反压刘家来人，说“证据不是我藏的，是你带来的。”声音必须用陈迹原生多模态参考，口型同步；镜头保留来人反应，形成正反打。画面绝对不能出现任何烧录字幕、台词文字、说话人标签、汉字、英文或假字；对白只存在于原生音轨，字幕后期统一添加。",
    "14": "macro clue reversal。袖口黑灰、药粉、黑线银针和黑染药方近景串联。药方纸面必须完全空白，不能有表格线、横线、伪字、印刷痕或任何文字；手部动作真实，证据关系一眼看懂。",
    "15": "female surveillance medium。白鲤在巷口看着医馆冲突，手中袖印一闪。她不是旁观者，而是在确认陈迹是否会被诱导。街雾、灯影、帷帽稳定。此镜是无对白声场镜头：输出中必须有前景清晰可闻、持续且有动态的雨落青石和雨檐声，配合近处湿石脚步、风掠帷帽、巷口灯笼轻响和压低的人声；声场不得低于正常对白以下的背景级，不得静音、远景闷响或只有微弱底噪。",
    "16": "two-shot warning。陈迹和乌云在柜台阴影处，陈迹闻到白鲤袖口残留的官墨和血腥气，低声判断“她身上有官墨味，也有血味。”乌云不说话，只用猫爪按住水晶珠、抬眼看向门外来确认危险。猫保持真实四足姿态，不人化；本镜用猫爪、珠子冷响、风雨、衣料和药柜声推进剧情。",
    "17": "decision medium。陈迹把黑染药方收进袖中，决定追官巷线索。年轻灰布学徒造型、珠子、药方位置必须连贯，不要变成华服主角海报。此镜无对白但必须有清晰可闻的原生声场：雨落门外、袖口摩擦、纸张入袖、湿石脚步、珠子轻碰、远处更鼓和风声层次完整，不能静音、不能只有极弱底噪。",
    "18": "female clue drop。白鲤在夜街转身，帷帽微抬一瞬，和陈迹同框，说“去官巷，别信密谍司。”她给出方向但不完全暴露身份，保留权力感。",
    "19": "insert secret mark。白鲤袖口或令签影子出现密谍司相关烧痕/黑牌暗影；只允许单字“密”或完全留空后期合成。不要长中文，不要假字。",
    "20": "cliffhanger wide。陈迹站在通向官巷的冷色窄巷口，远处密谍司暗桩一闪，灯火灭，画外低声“今夜，别信密谍司。”空间方向通往 E13，不要字幕烘焙进画面。"
}

CHENJI_SPEAKING = {"04", "13", "16"}
BAILI_SPEAKING = {"01", "05", "09", "18"}
WUYUN_SPEAKING: set[str] = set()


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
    if "CHAR-白鲤-古装" in chars:
        add_if_exists(refs, BAILI_CARD)
    if "CHAR-姚太医-古装" in chars:
        add_if_exists(refs, YAO_CARD)
    if room in {"ROOM-古装-太平医馆正堂-A", "ZONE-太平医馆门口-A"}:
        add_if_exists(refs, FRONT_HALL)
    if room in {"SCENE-古装-洛城夜街-A", "ALLEY-密谍司暗巷-A"}:
        add_if_exists(refs, STREET)
    if str(shot["id"]).zfill(2) == "16":
        add_if_exists(refs, E12_SHOT16_VISUAL_LOCK)
    if str(shot["id"]).zfill(2) == "17":
        add_if_exists(refs, E12_SHOT17_VISUAL_LOCK)
    if str(shot["id"]).zfill(2) == "18":
        add_if_exists(refs, E12_SHOT18_VISUAL_LOCK)
    if str(shot["id"]).zfill(2) == "19":
        add_if_exists(refs, E12_SHOT19_VISUAL_LOCK)
    if str(shot["id"]).zfill(2) == "20":
        add_if_exists(refs, E12_SHOT20_VISUAL_LOCK)
    return [str(path.resolve()) for path in refs[:9]]


def audio_references_for(shot: Dict[str, Any]) -> List[Any]:
    shot_id = str(shot["id"]).zfill(2)
    refs: List[Any] = [AMB_TAIPING]
    if shot_id in CHENJI_SPEAKING:
        refs.insert(0, VOICE_CHENJI)
    if shot_id in BAILI_SPEAKING:
        refs.insert(0, VOICE_BAILI)
    if shot_id in WUYUN_SPEAKING:
        refs.insert(0, VOICE_WUYUN)
    if shot_id in {"03", "08", "14", "19"}:
        refs.append(SFX_BEAD)
    if shot_id in {"01", "09", "18", "20"}:
        refs.append(SFX_COLD_STING)
    return refs


def normalize_audio_refs(refs: List[Any]) -> List[Any]:
    normalized: List[Any] = []
    for ref in refs:
        if isinstance(ref, dict):
            if ref.get("submit_local_sample") and ref.get("local_sample"):
                path = Path(str(ref["local_sample"])).expanduser()
                if not path.exists():
                    raise SystemExit(f"Missing required local audio reference: {path}")
                normalized.append(str(path.resolve()))
            elif ref.get("asset_id") or ref.get("url"):
                normalized.append({key: ref[key] for key in ("asset_id", "url") if ref.get(key)})
            else:
                # Descriptive voice designs are allowed only for new characters
                # that do not yet have a locked sample. Locked roles must submit
                # concrete audio assets or local audio files.
                continue
        elif str(ref).startswith(("http://", "https://")):
            normalized.append(str(ref))
        else:
            path = Path(str(ref)).expanduser()
            if path.exists():
                normalized.append(str(path.resolve()))
    return normalized


def validate_locked_voice_refs(shot_id: str, normalized_audio_refs: List[Any]) -> None:
    if shot_id in WUYUN_SPEAKING:
        required = str(VOICE_WUYUN_SAMPLE.resolve())
        present = any(str(ref) == required for ref in normalized_audio_refs)
        present = present or any(
            isinstance(ref, dict) and (ref.get("asset_id") or ref.get("url"))
            for ref in normalized_audio_refs
        )
        if not present:
            raise SystemExit(
                f"E12 shot {shot_id} has Wuyun dialogue but is missing the locked "
                f"Wuyun audio reference: {required} or a registered Giggle asset_id/url"
            )
    if shot_id in CHENJI_SPEAKING:
        present = any(isinstance(ref, dict) and ref.get("asset_id") == "cypqud0bu7t" for ref in normalized_audio_refs)
        if not present:
            raise SystemExit(f"E12 shot {shot_id} has Chenji dialogue but is missing voice asset cypqud0bu7t")


def audio_name(ref: Any) -> str:
    if isinstance(ref, dict):
        return ref.get("label") or ref.get("asset_id") or ref.get("voice_design") or "audio asset"
    return Path(str(ref)).name


def prompt_for(shot: Dict[str, Any], refs: List[str], audio_refs: List[Any]) -> str:
    shot_id = str(shot["id"]).zfill(2)
    image_lines = "\n".join(f"- 图片{idx}: {Path(path).name}" for idx, path in enumerate(refs, 1)) or "- 无图片参考，按文字锚点生成。"
    audio_lines = "\n".join(f"- 音频{idx}: {audio_name(ref)}" for idx, ref in enumerate(audio_refs, 1)) or "- 无声音参考。"
    chars = "、".join(shot.get("characters") or []) or "无"
    props = "、".join(shot.get("props") or []) or "无"
    dialogue = shot.get("dialogue") or "无对白"
    return f"""{COMMON_RULES}

《青山》E12《灯下女客》API 镜头 {shot_id}

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
2. 白鲤出现时必须使用白鲤古装 canonical 参考图作为身份锚。她是帷帽女客、证据携带者和隐藏权力角色，不是装饰性美女；不得混用张霞、云妃、皎兔、溪冰或其他女性脸。
3. 乌云出现时必须是灰黑长毛猫，毛色、头身比例、耳侧旧伤和聪明冷眼一致，绝不人化。
4. 陈迹说话镜头必须用 `VOICE-陈迹-古装` / asset `cypqud0bu7t` 作为多模态声音参考，声音和口型原生同步，不能后期配音感。乌云每个说话镜头必须实际提交 `libraries/audio/voice_refs/e09_voice_locked_20260709/shot_20_VOICE-乌云-猫-final-hook-only.wav` 作为 API audio reference；prompt-only 的“女声/猫声”一律视为未绑定、不得发行。白鲤说话镜头本轮用多模态原生女声生成，QA 通过后从最佳片段提取 `VOICE-白鲤-古装` 样本入资产库。
5. 画面内长中文必须为空白纸、空白牌或不可读留白；字幕不要烘焙进视频画面。黑牌只允许单字“密”，不稳则留空后期合成。
   背景装饰性招牌/牌匾的模型伪中文允许保留；只有观众必须读懂且会影响剧情的文字才使用空白道具与后期真字合成。
6. 必须有环境声和动作拟音：纸张、门轴、药柜、衣料、猫爪、脚步、灯芯、珠子冷响按镜头需要出现；BGM 只轻铺，不盖对白。
7. 镜头语言不能退回居中单人肖像。按覆盖类型执行 two-shot、OTS、group、insert、reaction、tracking 或 macro clue。
8. 结尾留出 0.3-0.5 秒动作或声音接点，便于剪辑衔接。
9. 若本镜头是药方、袖印、黑牌、线索等文字道具特写，表面必须保持空白或只出现单个明确短字；禁止模型生成任何长文字、伪汉字、点阵、乱码、行状墨迹。
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build E12 API run plan.")
    parser.add_argument("--continuity", default=str(ROOT / "configs/e12_continuity_config_20shots_20260710.json"))
    parser.add_argument("--out-dir", default=str(ROOT / "working_assets/e12_api_20260710"))
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
        validate_locked_voice_refs(shot_id, normalized_audio_refs)
        prompt_path = prompt_dir / f"e12_shot_{shot_id}.txt"
        prompt_path.write_text(prompt_for(shot, refs, audio_refs), encoding="utf-8")
        plan.append({
            "shot_id": shot_id,
            "title": f"E12 Shot{shot_id}",
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
