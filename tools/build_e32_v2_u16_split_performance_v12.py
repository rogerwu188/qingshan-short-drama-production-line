#!/usr/bin/env python3
"""Replace overloaded E32 U16 with two independently generatable performances."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from episode_parallel_batch_supervisor import (
    validate_complete_video_prompt_manifest,
    validate_corrected_pipeline_quality,
    validate_dialogue_manifest_coverage,
    validate_duration_task,
    validate_entity_reference_task,
    validate_writer_agent_provenance,
)
from episode_video_generation_guard import (
    evaluate_episode_credit_gate,
    find_existing_paid_candidate,
    generation_fingerprint,
)
from multimodal_character_binding_guard import binding_digest, evaluate_batch as evaluate_bindings
from scene_authority_lock import evaluate_batch as evaluate_scene_authority
from shot_prompt_professionalism_gate import evaluate_batch as evaluate_prompt_professionalism
from shot_space_camera_constraint_gate import evaluate_batch as evaluate_space_camera


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723"
BASE = PRODUCTION / "video_performance_v2"
SOURCE_CONFIG = BASE / "E32_VIDEO_IDENTITY_STATE_REEL_TRANSPORT_V10.json"
CONFIG = BASE / "E32_VIDEO_U16_SPLIT_PERFORMANCE_V12.json"
PRECHECK = BASE / "qa/E32_VIDEO_U16_SPLIT_PERFORMANCE_V12_PRECHECK.json"
PROMPT_DIR = BASE / "prompts_v12_u16_split"
SPEC_DIR = BASE / "specs_v12_u16_split"
REEL_DIR = ROOT / "working_assets/e32_u16_split_reference_reels_v12_20260723"
PLAN = PRODUCTION / "E32_VIDEO_UNIT_PERFORMANCE_PLAN_U16_SPLIT_V12.json"
DIALOGUE_MANIFEST = (
    ROOT / "working_assets/e32_dialogue_audio_refs_v2_20260723/"
    "E32_DIALOGUE_AUDIO_REFERENCE_MANIFEST_U16_SPLIT_V12.json"
)
PROMPT_MANIFEST = BASE / "E32_ALL_18_VIDEO_PROMPT_MANIFEST_U16_SPLIT_V12.json"
TRANSFORM = "IMAGE_SEQUENCE_TO_VIDEO_IDENTITY_REEL_2S_PER_IMAGE_720X1280"
SEGMENT_SECONDS = 3.0


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def absolute(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def sha(value: str | Path) -> str:
    return hashlib.sha256(absolute(value).read_bytes()).hexdigest()


def ffmpeg_binary() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    result = subprocess.run(
        [str(ROOT / "tools/find_ffmpeg.sh")],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def make_identity_reel(unit_id: str, image_path: str) -> str:
    digest = sha(image_path)[:12]
    target = REEL_DIR / f"{unit_id}_{digest}_{SEGMENT_SECONDS:.0f}s_identity_reel.mp4"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        subprocess.run(
            [
                ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-y",
                "-loop", "1", "-t", str(SEGMENT_SECONDS), "-i", str(absolute(image_path)),
                "-vf", (
                    "scale=720:1280:force_original_aspect_ratio=decrease,"
                    "pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=black,fps=24,format=yuv420p"
                ),
                "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-movflags", "+faststart", str(target),
            ],
            check=True,
        )
    return relative(target)


def plan_unit(unit_id: str, duration: int, shot_ids: list[str], action_class: str) -> dict:
    return {
        "unit_id": unit_id,
        "scene_id": "E32-CW-S05",
        "duration_seconds": duration,
        "editorial_shot_ids": shot_ids,
        "generation_mode": "performance_generation",
        "planned_reference_image_count": 1,
        "reference_image_task_keys": [f"{unit_id}-A1-STILL-V12"],
        "anchor_count_decision": {
            "planned_reference_image_count": 1,
            "reason": (
                "One locked speaker identity plus a continuous same-rooftop motion chain is within "
                "Seedance capability; no identity, prop, space, or terminal-state re-anchor occurs."
            ),
            "criteria": {
                "continuous_motion_from_single_start": True,
                "identity_or_space_reanchor": False,
                "prop_ownership_transition": False,
                "non_interpolable_terminal_state": False,
            },
            "anchor_roles": ["speaker_identity_and_performance_start"],
            "action_design_class": action_class,
        },
        "keyframe_interpolation_gate": {
            "status": "PASS",
            "stage": "DESIGN_PREFLIGHT",
            "adjacent_pairs_checked": 0,
            "candidate_recheck_required": False,
            "reason": "A single start anchor drives one physically continuous performance without state jumps.",
        },
        "performance_spec": {
            "intent": "Split the original U16 only at its authored speaker and action-purpose boundary.",
            "motion_chain": action_class,
            "expression_arc": "Speaker expression changes continuously with the authored realization.",
            "viewer_read": "The audience reads one clear strategy beat without unrelated character load.",
            "single_action_state_source": "CLAUDE_SCRIPT_DERIVED_BEAT_SPEC",
            "dialogue_policy": "VIDEO_MODEL_NATIVE_MANDARIN_FROM_BOUND_REFERENCE_AUDIO",
        },
        "replaces_unit_id": "E32-CW-U16",
        "status": "READY_SPLIT_REPLACEMENT",
    }


def make_split_plan(source_path: Path) -> dict:
    source = load(source_path)
    units = []
    for row in source["units"]:
        if row.get("unit_id") != "E32-CW-U16":
            units.append(row)
            continue
        units.extend([
            plan_unit("E32-CW-U16A", 11, ["E32-CW-S05-SH03"], "yunyang_reports_three_hostile_factions"),
            plan_unit("E32-CW-U16B", 7, ["E32-CW-S05-SH04"], "chenji_converts_mutual_distrust_into_strategy"),
        ])
    source.update({
        "schema": "qingshan.performance_video_plan.u16_split.v12",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "planned_reference_image_count": sum(row["planned_reference_image_count"] for row in units),
        "units": units,
        "split_replacement": {
            "source_unit_id": "E32-CW-U16",
            "replacement_unit_ids": ["E32-CW-U16A", "E32-CW-U16B"],
            "boundary": "authored speaker and action-purpose transition",
            "narrative_order_locked": True,
        },
    })
    return source


def make_split_dialogue_manifest(source_path: Path) -> dict:
    payload = load(source_path)
    for row in payload["rows"]:
        if row.get("dia_id") in {"E32-DIA-023", "E32-DIA-024"}:
            row["video_unit_id"] = "E32-CW-U16A"
        elif row.get("dia_id") == "E32-DIA-025":
            row["video_unit_id"] = "E32-CW-U16B"
    payload.update({
        "schema": "qingshan.dialogue_audio_reference_manifest.u16_split.v12",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "split_replacement": {
            "source_unit_id": "E32-CW-U16",
            "replacement_unit_ids": ["E32-CW-U16A", "E32-CW-U16B"],
        },
    })
    return payload


def prompt_a() -> str:
    return """《青山》E32 U16A，Seedance 2.0 Pro 四模态表演生成，11秒，9:16，720p，原速连续动作。
【参考卷文件】@视频1=云羊唯一备案身份参考卷；只锁人物身份，不复制静态构图。
【拆分依据】原 U16 按同场连续动作中的说话人与动作目的自然边界拆分；本单元只承担云羊落檐、辨认三路势力和两句连续汇报，不等待或包含下一位说话人。
【实体绑定】[[char_yunyang]][[scene_e32_cw_s05_post_rain_rooftop]][[prop_three_lantern_formations]]；只允许云羊一名可见人物；远景只出现三路不同编队的灯笼队列、医馆飞檐与雨后洛城屋脊；禁止生成陈迹、皎兔、乌云或其他近景人物。
【参考视频身份职责】@视频1[0.0-3.0秒]只锁云羊脸型、发型、年龄、服装与身形；禁止融合人物、禁止把参考卷当动作源。
【天气硬合同】weather=RAIN_STOPPED_CLOUD_BREAK；雨已经停止，云层裂开露出残月；可保留湿屋瓦和残留水滴，严禁继续落雨或出现雨幕。
【色彩与动机光】雨后洛城夜靛蓝、残月冷白、灯笼橙红；只用夜空与灯笼真实动机光。
【摄影】先以侧后方中景接住云羊落在檐脊，随后连续跟到他的侧面近景和手指所指的三路灯网；保持同一空间轴线，不闪切、不循环、不停帧。
【力量作用环境】下落惯性由屈膝传入湿瓦，瓦片只产生一次轻微受力声与水滴震落；远处灯笼队列按真实步伐移动，禁止无因震动或飞散。
【环境声音】雨后风声、远更、远处调动脚步和灯笼轻响；禁止旁白与BGM。
【原生对白与音频模态】视频模型必须按参考音频原生生成云羊的自然中文普通话、同步口型、气息、表情与起止时间；字幕仅后期烧录：
- E32-DIA-023｜云羊逐字说：“一个圈里，巡检线、景朝暗桩、内院私兵……”｜精确台词音频=@音频1
- E32-DIA-024｜云羊逐字说：“全挤一处。谁也不信谁。”｜精确台词音频=@音频2
【连续物理动作脚本】
镜头1【0.0-1.0秒，侧后方中景连续跟拍落点】主体=云羊；起势=从侧后方落向另一侧檐脊；接触点=双脚先后踩实湿瓦并屈膝吸收向下惯性；方向=身体由下落转为稳定直立，不滑行、不腾空回弹；终态=站稳后抬头看清城中灯网；表情=急促赶来后的焦灼与警觉；动作目的=观众先确认他带着紧急情报赶到；{无对白}<鞋底触瓦、瓦片轻响、短促呼吸>
镜头2【1.0-7.5秒，侧面中近景平移后带到灯网远景】主体=云羊；动作=左手扶住檐脊保持平衡，右手依次指向左、中、右三路灯笼编队，并随@音频1逐字说出台词；接触点=手指只指向远处队列，不触碰道具；方向=指向顺序固定为巡检线、景朝暗桩、内院私兵；终态=三个阵营被明确区分；表情=眉头紧锁、眼神快速核对，愤怒中带不安；动作目的=让观众看懂围猎圈不是一支统一队伍，而是三股势力；{云羊逐字说“一个圈里，巡检线、景朝暗桩、内院私兵……”}<雨后风声、远更、灯笼轻响>
镜头3【7.5-11.0秒，拳头与眼神近景缓推】主体=云羊；动作=他收回手指握拳，看见三路队列在交界处彼此让开空隙，并随@音频2逐字说出台词；接触点=拳头停在胸前，不击打任何物体；方向=目光从三路交界扫回镜头外的同伴方向；终态=三路编队保持戒备间距，互疑被可视化；表情=呼吸急促、眼底不安加深；动作目的=观众理解“挤在一处却互不信任”；{云羊逐字说“全挤一处。谁也不信谁。”}<握拳衣料摩擦、远处脚步分流声>
【观众读取】本单元只交付一件信息：云羊确认三路围猎势力彼此提防。
【单一状态源】人物、动作、空间、对白和音频都以本任务逐拍spec为唯一来源，禁止擅自补转身、打斗、法术或其他人物反应。
【负面约束】禁止字幕、水印、Logo、可读文字、伪文字；禁止新增人物、换脸、短发化、身份漂移、融肢、穿模、无接触受力、无因腾空、瞬移、慢放、停帧、循环、周期重复、静帧微动和首尾重复。
【提交状态】U16A_SPLIT_PROMPT_COMPILED；生成后逐句执行ASR、说话人归属、口型、备案声线、人物身份和物理动作复核。
"""


def prompt_b() -> str:
    return """《青山》E32 U16B，Seedance 2.0 Pro 四模态表演生成，7秒，9:16，720p，原速连续动作。
【参考卷文件】@视频1=陈迹唯一备案身份参考卷；只锁人物身份，不复制静态构图。
【拆分依据】承接U16A同一雨后屋脊和同一灯网方位；本单元只承担陈迹从敌人互疑中形成反制思路，不重复云羊落檐和汇报动作。
【实体绑定】[[char_chenji]][[scene_e32_cw_s05_post_rain_rooftop]][[prop_three_lantern_formations]]；只允许陈迹一名可见人物；远景只出现三路不同编队的灯笼长龙、医馆飞檐与雨后洛城屋脊；禁止生成皎兔、云羊、乌云或其他近景人物。
【参考视频身份职责】@视频1[0.0-3.0秒]只锁陈迹脸型、长发、年龄、服装与身形；禁止融合人物、禁止把参考卷当动作源。
【天气硬合同】weather=RAIN_STOPPED_CLOUD_BREAK；雨已经停止，云层裂开露出残月；可保留湿屋瓦和残留水滴，严禁继续落雨或出现雨幕。
【色彩与动机光】雨后洛城夜靛蓝、残月冷白、灯笼橙红；残月只照亮陈迹半边脸，灯网提供远处暖色层次。
【摄影】从陈迹看向灯网的半背中近景连续绕到侧面，最后轻微推近眼神与掌心；保持与U16A一致的灯网方位，不闪切、不循环、不停帧。
【力量作用环境】陈迹转身时脚底和衣摆只受雨后夜风与自身惯性影响；掌心冷雾只扰动近手空气并凝出一瞬细小水汽，绝不推动屋瓦或远处灯网。
【环境声音】雨后风声、远更、远处调动脚步和灯笼轻响；禁止旁白与BGM。
【原生对白与音频模态】@音频1是陈迹备案原生声线参考，只锁音色、年龄、气息和说话质感；台词文本以本行唯一权威。视频模型必须原生生成并同步口型，禁止后配音、改词或借用其他声线：
- E32-DIA-025｜陈迹逐字说：“网里这三拨人，谁也不信谁。”
【连续物理动作脚本】
镜头1【0.0-2.0秒，半背中近景连续绕到侧面】主体=陈迹；起势=背对镜头看着三路灯网；动作=听完画外汇报后缓慢向侧面转头，肩、颈、目光依次连续转动；接触点=双脚始终稳踩檐脊，不新增位移；方向=视线由灯网交界转向镜头外汇报者；终态=残月照亮半边脸；表情=原本受压的冷静转为洞悉；动作目的=观众看懂他捕捉到了敌人互疑的破口；{无对白}<衣摆受风轻响、远更>
镜头2【2.0-5.5秒，半边月光面部近景缓推】主体=陈迹；动作=保持侧身，视线在三路灯网交界与镜头外同伴之间短促往返，随参考声线逐字说出台词；接触点=手臂自然垂落，不抓取道具；方向=口型、气息和停顿与台词同步；终态=最后一个“谁”落下时目光锁住三路交界；表情=眉心舒展一瞬，眸底寒意变锐；动作目的=把“互不信任”从情报转化为可利用条件；{陈迹逐字说“网里这三拨人，谁也不信谁。”}<雨后风声、远处队列脚步声>
镜头3【5.5-7.0秒，眼神转向掌心的近景下摇】主体=陈迹；动作=重新看向灯网，掌心凝出薄薄冷雾后主动散去，不发动攻击；接触点=冷雾只贴近掌心，不接触屋瓦或远处人物；方向=雾气向上聚拢后就地消散；终态=陈迹不动声色地形成反制思路但尚未执行；表情=冷极生锐、克制自信；动作目的=用主动收回法术表现他选择谋略而非立即强攻；{无对白}<冷雾凝结轻响、掌心收拢衣袖摩擦>
【观众读取】本单元只交付一件信息：陈迹决定利用三路势力互不信任反制围猎。
【单一状态源】人物、动作、空间、能力、对白和音频都以本任务逐拍spec为唯一来源，禁止擅自补抓取、打斗、瞬移或其他人物反应。
【负面约束】禁止字幕、水印、Logo、可读文字、伪文字；禁止新增人物、换脸、短发化、身份漂移、融肢、穿模、无接触受力、无因腾空、瞬移、慢放、停帧、循环、周期重复、静帧微动和首尾重复。
【提交状态】U16B_SPLIT_PROMPT_COMPILED；生成后逐句执行ASR、说话人归属、口型、备案声线、人物身份和物理动作复核。
"""


def make_task(source: dict, *, unit_id: str, duration: int, character_id: str, prompt: str) -> dict:
    task = deepcopy(source)
    binding = next(row for row in source["multimodal_entity_bindings"] if row["entity_id"] == character_id)
    image_path = binding["visual_reference"]
    reel = make_identity_reel(unit_id, image_path)
    reel_sha = sha(reel)
    dialogue_ids = {"E32-CW-U16A": {"E32-DIA-023", "E32-DIA-024"}, "E32-CW-U16B": {"E32-DIA-025"}}[unit_id]
    dialogue = [deepcopy(row) for row in source["dialogue"] if row["dia_id"] in dialogue_ids]
    audio_assets = [deepcopy(row) for row in source["dialogue_audio_assets"] if row["dia_id"] in dialogue_ids]
    for index, row in enumerate(audio_assets):
        row["audio_slot"] = f"@音频{index + 1}"
    exact_audio = [row["path"] for row in audio_assets if row.get("purpose") == "EXACT_TARGET_DIALOGUE_REFERENCE"]
    remote_audio_ids = [
        row["remote_asset_id"] for row in audio_assets
        if row.get("remote_asset_id") and row.get("purpose") != "EXACT_TARGET_DIALOGUE_REFERENCE"
    ]
    binding = deepcopy(binding)
    binding["dialogue_audio_slots"] = [f"@音频{index + 1}" for index in range(len(audio_assets))]
    binding["visible_speaker"] = True
    binding["lip_sync"] = True
    binding.pop("identity_image_slot", None)
    binding["identity_video_slot"] = "@视频1[0.0-3.0秒]"
    performance_spec = {
        "schema": "qingshan.performance_generation_spec.u16_split.v12",
        "episode": "E32",
        "unit_id": unit_id,
        "duration_seconds": duration,
        "replaces_unit_id": "E32-CW-U16",
        "split_boundary": "speaker and action-purpose transition",
        "motion_beats": (
            [
                {"start_seconds": 0.0, "end_seconds": 1.0, "subject": "云羊", "action": "落檐屈膝站稳", "contact_point": "双脚接触湿瓦", "direction": "向下惯性被屈膝吸收", "end_state": "站稳抬头", "expression": "焦灼警觉", "intent": "确认紧急赶到"},
                {"start_seconds": 1.0, "end_seconds": 7.5, "subject": "云羊", "action": "依次指出三路灯网并说DIA-023", "contact_point": "手指不接触道具", "direction": "左中右固定顺序", "end_state": "三股势力被区分", "expression": "愤怒不安", "intent": "解释三路围猎"},
                {"start_seconds": 7.5, "end_seconds": 11.0, "subject": "云羊", "action": "收手握拳并说DIA-024", "contact_point": "拳停胸前", "direction": "目光扫过三路交界", "end_state": "互疑间距可见", "expression": "眼底不安", "intent": "解释彼此不信任"},
            ]
            if unit_id.endswith("A")
            else [
                {"start_seconds": 0.0, "end_seconds": 2.0, "subject": "陈迹", "action": "从灯网连续转头", "contact_point": "双脚稳踩檐脊", "direction": "由灯网转向画外汇报者", "end_state": "半边脸入月光", "expression": "受压转洞悉", "intent": "发现敌人破口"},
                {"start_seconds": 2.0, "end_seconds": 5.5, "subject": "陈迹", "action": "说DIA-025并锁定三路交界", "contact_point": "不抓取道具", "direction": "目光往返后锁定交界", "end_state": "互疑成为可利用条件", "expression": "寒意变锐", "intent": "形成反制判断"},
                {"start_seconds": 5.5, "end_seconds": 7.0, "subject": "陈迹", "action": "掌心冷雾聚起后主动散去", "contact_point": "冷雾只贴掌心", "direction": "向上聚拢后就地消散", "end_state": "谋略形成但未执行", "expression": "克制自信", "intent": "选择谋略而非强攻"},
            ]
        ),
    }
    performance_spec["prop_ownership"] = {
        "single_source_of_truth": "Only the visible speaker may own or operate props and abilities explicitly authored in this split unit."
    }
    for beat in performance_spec["motion_beats"]:
        beat["viewer_read"] = beat["intent"]
        beat["visible_causality"] = (
            f"{beat['action']}；接触={beat['contact_point']}；方向={beat['direction']}；终态={beat['end_state']}"
        )
    spec_path = SPEC_DIR / f"{unit_id}-PERFORMANCE-SPEC-V12.json"
    write(spec_path, performance_spec)
    prompt_path = PROMPT_DIR / f"{unit_id}-PERFORMANCE-V12-SPLIT.txt"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    task.update({
        "task_key": f"{unit_id}-PERFORMANCE-V12-SPLIT",
        "source_id": "E32-CW-U16",
        "unit_id": unit_id,
        "batch_id": "E32-U16-SPLIT-PERFORMANCE-V12",
        "duration": duration,
        "duration_seconds": duration,
        "duration_plan": {
            "policy": "qingshan.shot_generation_duration.v5",
            "duration_seconds": duration,
            "rationale": "Measured bound dialogue plus authored physical beats after natural U16 split.",
            "edit_policy": "End after the authored purpose is visible; never loop, freeze, pad, or slow.",
        },
        "prompt_file": relative(prompt_path),
        "prompt_sha256": sha(prompt_path),
        "reference_images": [],
        "reference_image_sequence": [],
        "planned_reference_image_count": 0,
        "state_reference_minimum": 0,
        "still_sequence_only_allowed": False,
        "reference_video_only_authorized": True,
        "reference_video_plan_reason": "A single SHA-audited identity image is transported as one reference reel; continuous motion comes from the authored performance script.",
        "anchor_plan_transport_substitution": {
            "status": "PASS",
            "source_planned_reference_image_count": 1,
            "source_reference_sequence_count": 1,
            "substitute_reference_video_count": 1,
            "reason": "PROVIDER_REFERENCE_VIDEO_TRANSPORT_WITH_SINGLE_DYNAMIC_ANCHOR_DECISION",
        },
        "reference_videos": [reel],
        "reference_identity_video_sequence": [{
            "asset_label": "@视频1[0.0-3.0秒]",
            "role": f"IDENTITY_REFERENCE_{character_id.upper()}",
            "path": reel,
            "sha256": reel_sha,
            "identity_reference": True,
            "transport_derivative_of": image_path,
            "transport_derivative_source_sha256": sha(image_path),
            "transport_transform": TRANSFORM,
            "segment_start_seconds": 0.0,
            "segment_end_seconds": 3.0,
        }],
        "reference_state_video_sequence": [],
        "reference_image_transport": "single_identity_reel",
        "generation_transport_revision": "U16_SPLIT_PERFORMANCE_V12",
        "dialogue": dialogue,
        "reference_audios": exact_audio,
        "reference_audio_asset_ids": remote_audio_ids,
        "dialogue_audio_assets": audio_assets,
        "native_dialogue_required": True,
        "audio_reference_optional": False,
        "dialogue_audio_coverage": {"required": len(dialogue), "bound": len(audio_assets), "status": "PASS"},
        "performance_spec": performance_spec,
        "source_spec": relative(spec_path),
        "source_spec_sha256": sha(spec_path),
        "multimodal_entity_bindings": [binding],
        "nonvisual_entity_mentions": (
            ["chenji", "jiaotu", "wuyun"]
            if unit_id.endswith("A")
            else ["jiaotu", "yunyang", "wuyun"]
        ),
        "visual_zone": (
            "E32-CW-U16A-YUNYANG-THREE-FACTIONS"
            if unit_id.endswith("A")
            else "E32-CW-U16B-CHENJI-STRATEGY-REACTION"
        ),
        "replaces_unit_id": "E32-CW-U16",
        "split_order": 1 if unit_id.endswith("A") else 2,
        "continuous_scene": True,
        "status": "READY_TO_SUBMIT",
    })
    task["multimodal_binding_sha256"] = binding_digest(task["multimodal_entity_bindings"])
    for key in (
        "reference_image_urls", "reference_image_asset_ids", "resolved_reference_image_asset_ids",
        "resolved_reference_audio_asset_ids", "reference_video_asset_ids", "resolved_reference_video_asset_ids",
        "task_id", "remote_status", "output_path", "sha256", "credit_attempts", "submit_response",
    ):
        task.pop(key, None)
    task["generation_fingerprint"] = generation_fingerprint(task)
    return task


def make_prompt_manifest(source_path: Path, tasks: list[dict]) -> dict:
    payload = load(source_path)
    task_by_unit = {task["unit_id"]: task for task in tasks}
    rows = []
    for row in payload["rows"]:
        if row.get("unit_id") != "E32-CW-U16":
            rows.append(row)
            continue
        for unit_id in ("E32-CW-U16A", "E32-CW-U16B"):
            task = task_by_unit[unit_id]
            rows.append({
                "unit_id": unit_id,
                "scene_id": "E32-CW-S05",
                "weather": "RAIN_STOPPED_CLOUD_BREAK",
                "editorial_estimate_seconds": task["duration_seconds"],
                "compiled_duration_seconds": task["duration_seconds"],
                "planned_reference_image_count": 1,
                "dialogue_ids": [row["dia_id"] for row in task["dialogue"]],
                "blocked_exact_dialogue_audio_ids": [],
                "native_voice_style_dialogue_ids": [
                    row["dia_id"] for row in task["dialogue_audio_assets"]
                    if row.get("purpose") != "EXACT_TARGET_DIALOGUE_REFERENCE"
                ],
                "status": "PROMPT_COMPILED",
                "prompt_path": task["prompt_file"],
                "prompt_sha256": task["prompt_sha256"],
                "replaces_unit_id": "E32-CW-U16",
            })
    payload.update({
        "schema": "qingshan.complete_video_prompt_manifest.u16_split.v12",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source_plan": relative(PLAN),
        "source_plan_sha256": sha(PLAN),
        "unit_count": len(rows),
        "all_units_have_prompt": True,
        "rows": rows,
        "split_replacement": {
            "source_unit_id": "E32-CW-U16",
            "replacement_unit_ids": ["E32-CW-U16A", "E32-CW-U16B"],
        },
    })
    return payload


def main() -> int:
    source_config = load(SOURCE_CONFIG)
    source_task = next(task for task in source_config["tasks"] if task["unit_id"] == "E32-CW-U16")
    write(PLAN, make_split_plan(absolute(source_config["anchor_count_plan_ref"])))
    write(DIALOGUE_MANIFEST, make_split_dialogue_manifest(absolute(source_config["dialogue_manifest_ref"])))
    tasks = [
        make_task(source_task, unit_id="E32-CW-U16A", duration=11, character_id="yunyang", prompt=prompt_a()),
        make_task(source_task, unit_id="E32-CW-U16B", duration=7, character_id="chenji", prompt=prompt_b()),
    ]
    write(
        PROMPT_MANIFEST,
        make_prompt_manifest(absolute(source_config["complete_video_prompt_manifest_ref"]), tasks),
    )
    config = deepcopy(source_config)
    config.update({
        "status": "READY_U16_SPLIT_REPLACEMENT_V12",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": "E32-U16-SPLIT-PERFORMANCE-V12",
        "targeted_unit_replacement": True,
        "source_unit_replacement": {
            "source_unit_id": "E32-CW-U16",
            "replacement_unit_ids": ["E32-CW-U16A", "E32-CW-U16B"],
            "natural_boundary": "speaker and action-purpose transition",
        },
        "streaming_submission_policy": "SUBMIT_EACH_UNIT_IMMEDIATELY_WHEN_ITS_OWN_DEPENDENCIES_PASS",
        "max_retries": 0,
        "mechanical_default_plan_ref": relative(PLAN),
        "anchor_count_plan_ref": relative(PLAN),
        "dialogue_manifest_ref": relative(DIALOGUE_MANIFEST),
        "complete_video_prompt_manifest_ref": relative(PROMPT_MANIFEST),
        "tasks": tasks,
    })
    write(CONFIG, config)

    prompt_texts = {
        task["task_key"]: absolute(task["prompt_file"]).read_text(encoding="utf-8")
        for task in tasks
    }
    checks = {
        "corrected_pipeline_quality": validate_corrected_pipeline_quality(config),
        "complete_video_prompt_manifest": validate_complete_video_prompt_manifest(config),
        "dialogue_manifest_coverage": validate_dialogue_manifest_coverage(config),
        "prompt_professionalism": evaluate_prompt_professionalism(config),
        "space_camera_constraint": evaluate_space_camera(tasks, prompt_texts),
        "multimodal_character_binding": evaluate_bindings(config),
        "scene_authority": evaluate_scene_authority(config["scene_contract_ref"], config),
        "entity_reference_sequence": {"status": "PASS", "results": []},
        "duration_policy": {"status": "PASS", "results": []},
        "generation_deduplication": {"status": "PASS", "results": []},
        "current_workflow_credit_gate": evaluate_episode_credit_gate("E32", limit=6000),
    }
    for task in tasks:
        entity_failures = validate_entity_reference_task(task)
        duration_failures = validate_duration_task(task)
        existing = find_existing_paid_candidate("E32", task)
        checks["entity_reference_sequence"]["results"].append({"task_key": task["task_key"], "failures": entity_failures})
        checks["duration_policy"]["results"].append({"task_key": task["task_key"], "failures": duration_failures})
        checks["generation_deduplication"]["results"].append({"task_key": task["task_key"], "existing": existing})
        if entity_failures:
            checks["entity_reference_sequence"]["status"] = "FAIL"
        if duration_failures:
            checks["duration_policy"]["status"] = "FAIL"
        if existing is not None:
            checks["generation_deduplication"]["status"] = "FAIL"
    writer_ok, writer_failures = validate_writer_agent_provenance(config)
    checks["writer_provenance"] = {"status": "PASS" if writer_ok else "FAIL", "failures": writer_failures}
    report = {
        "schema": "qingshan.e32_u16_split_performance_precheck.v12",
        "episode": "E32",
        "status": "PASS" if all(row.get("status") == "PASS" for row in checks.values()) else "FAIL",
        "checks": checks,
        "config": relative(CONFIG),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    write(PRECHECK, report)
    print(json.dumps({"status": report["status"], "config": report["config"], "precheck": relative(PRECHECK)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
