#!/usr/bin/env python3
"""Build the independent U11-R1B exact-dialogue envelope-transfer package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
SOURCE_DIR = BASE / "recovery_10000_20260730/u11_r1a_video"
SOURCE = SOURCE_DIR / "E36_U11_R1A_RECOVERY_EPISODE_PARALLEL_BATCH_V1.json"
OUT = BASE / "recovery_10000_20260730/u11_r1b_video"
QA = ROOT / "qa/e36_agentcut_20260730/u11_r1b_video_runtime"
CONFIG = OUT / "E36_U11_R1B_RECOVERY_EPISODE_PARALLEL_BATCH_V1.json"
PROMPT = OUT / "E36-CW-U11-R1B-RECOVERY.txt"
PROMPT_MANIFEST = OUT / "E36_U11_R1B_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
DIALOGUE_MANIFEST = OUT / "E36_U11_R1B_DIALOGUE_MANIFEST_V1.json"
DIALOGUE_GATE = QA / "E36_U11_R1B_DIALOGUE_PROMPT_GATE_V1.json"
ANCHOR_PLAN = QA / "E36_U11_R1B_ANCHOR_COUNT_PLAN_V1.json"
CAUSALITY_PLAN = QA / "E36_U11_R1B_COMMON_SENSE_CAUSALITY_PLAN_V1.json"
PERIOD_PLAN = QA / "E36_U11_R1B_PERIOD_LOCK_PLAN_V1.json"

CHENJI = ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png"
YUNYANG = ROOT / "assets/reference/e36_20260729/characters/CHAR-yunyang-age17-canonical-v1-20260729.png"
A1 = ROOT / "working_assets/e36_v2_stills_20260728/repair_v2_candidates/E36_E36-CW-U11-A1-STILL-V2_e3678bd0-6888-41ab-8d4f-4a68bbe2aea9.png"
A2 = ROOT / "working_assets/e36_v2_stills_20260728/repair_v3_candidates/E36_E36-CW-U11-A2-STILL-V3.png"
A2_QA = ROOT / "qa/e36_v2_stills_repair_20260729/u11_video_runtime/E36_U11_A2_IMAGE_QA_V1.json"
AUDIO = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u11_r1/E36-U11-R1-D02.wav"
AUDIO_QA = ROOT / "qa/e36_agentcut_20260730/u11_r1_video_runtime/E36-U11-R1-D02_EXACT_DIALOGUE_AUDIO_QA_V1.json"
AUDIO_RECEIPT = ROOT / "workflow/tasks/E36_U11_R1_D02_CHENJI_EXACT_DIALOGUE_AUDIO_GENERATION_V1.json"
TEXT = "规矩之外的事，才藏着真东西。把那信封拿来。"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"
MAILBOX_SHA = "62e0a3ca7414a87cc8c258cc78b78eba0e0c5f900cd14dee479e34501f4e85b5"
CHENJI_VOICE_ASSET_ID = "cypqud0bu7t"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    audio_qa = json.loads(AUDIO_QA.read_text(encoding="utf-8"))
    audio_receipt = json.loads(AUDIO_RECEIPT.read_text(encoding="utf-8"))
    a2_qa = json.loads(A2_QA.read_text(encoding="utf-8"))
    if audio_qa.get("status") != "PASS" or audio_qa.get("asr_similarity") != 1.0:
        raise SystemExit("U11-R1B exact Chenji audio is not ASR1.0 PASS")
    if sha(AUDIO) != audio_qa.get("wav_sha256") or not audio_receipt.get("task_id"):
        raise SystemExit("U11-R1B exact audio provenance mismatch")
    if a2_qa.get("status") != "PASS" or sha(A2) != a2_qa.get("asset_sha256"):
        raise SystemExit("U11-R1B A2 terminal anchor is not accepted exact-SHA authority")

    prompt = f"""【E36-CW-U11-R1B｜6秒｜规矩之外取信｜Seedance Fast原生普通话｜独立转录恢复单元】

@图片1只锁定十七岁陈迹身份；@图片2只锁定十七岁云羊身份；@图片3是已通过图片QA的U11-A1首帧、密室轴线、人物站位、旧木案与唯一无字空信封权威；@图片4是已通过图片QA的U11-A2终态权威，锁定同一信封最终只由陈迹双手持有。@音频1是陈迹逐字说出“{TEXT}”的精确普通话参考；视频模型必须让画面内陈迹现场原生说出该句，音频只作逐字、声线、气息和节奏参考，不得作为画外音或后配音播放。云羊全段闭口。

【天气硬合同】weather=INTERIOR_CLEAR_HARSH_SUN。6秒，竖屏9:16，720p，写实古装悬疑电影质感。中国古代架空洛城，太平医馆密室午后。禁止现代物件、民国妆发、字幕、水印、任何可读文字或伪文字。

【色彩与动机光】旧木深褐、灰旧布衣、低饱和暖烛与冷白窗光；画面右后直棂窗硬日光与左下桌面古式烛焰共同塑形。陈迹完整脸和嘴在0.20-4.65秒持续清楚，禁止无来源轮廓光。

【实体绑定】[[scene:太平医馆密室]]；[[char:十七岁陈迹]]；[[char:十七岁云羊]]；[[prop:唯一无字空信封]]；[[prop:旧木案]]。本镜继承U11既有空间权威，不新增人物、灵物或道具。

镜头1【双人中近景同轴承接，0.00-0.20秒】：主体=陈迹、云羊、旧木案、唯一空信封；动作=严格从@图片3起动，陈迹右手拇指与食指正在夹住信封近侧纸边并短吸气，云羊在后景闭口看信封；接触点=陈迹右手指腹与信封近侧纸边、信封底面与桌面；方向=陈迹右手由画面左下向桌中收拢，信封尚未离桌；终态=陈迹嘴部清晰并立即开口，指腹已夹紧纸边。{{无对白}}<音效：短吸气、指腹擦纸、烛焰与衣料环境声>。

镜头2【陈迹胸上近景，手和信封同框，0.20-2.75秒】：主体=陈迹、唯一空信封；动作=陈迹按@音频1自然普通话说出“规矩之外的事，才藏着真东西。”，同时拇指食指夹住纸边把信封由案面提离；接触点=右手拇指与食指夹住信封近侧纸边；方向=信封由桌中向陈迹胸前下方上提并后收；终态=信封完全离案，仍只由陈迹右手持有，云羊闭口且不触碰。{{对白：陈迹连续说出前半句}}<音效：@音频1精确参考、纸张离桌、衣袖摩擦、烛焰>。

镜头3【陈迹胸上近景极缓推近，2.75-4.65秒】：主体=陈迹、唯一空信封；动作=陈迹不中断地按@音频1继续说“把那信封拿来。”，左手从信封下方托住另一侧纸边，双手把信封稳到胸前并低眼检查折痕；接触点=右手夹近侧纸边、左手托远侧下缘；方向=左手由胸前下方上托，信封由单手过渡为陈迹双手持有但不翻面；终态=“来”字完整落下，陈迹闭口，信封唯一由陈迹双手持有并对应@图片4终态。{{对白：陈迹仅继续说完后半句}}<音效：@音频1连续精确参考、指腹压纸、自然呼吸>。

镜头4【双人证物中近景停稳，4.65-6.00秒】：主体=陈迹、云羊、唯一空信封；动作=陈迹闭口短呼气并双手检查无字信封折痕，云羊闭口微向前倾但双手垂下不碰信封；接触点=仅陈迹双手与信封两侧纸边、云羊双脚与地面；方向=陈迹视线沿折痕向下移动，云羊视线由陈迹脸移向信封；终态=陈迹唯一持有信封，云羊不接触，证物进入鉴证。{{无对白}}<音效：短呼气、纸边轻响、窗光尘埃与烛焰环境声>。

【原生对白硬合同】唯一可听台词是“{TEXT}”。陈迹0.20-4.65秒只说一遍，不增字、不减字、不改字、不重复；完整嘴部清楚，口型、气息、眉眼、表情与起止时间同步。云羊全程闭口。禁止串台、旁白、画外音、后配替换、现代播音腔、字幕。

【首帧动势与环境生命层】第一帧不是完成态：陈迹手指正在夹紧纸边、信封尚未离桌、嘴正要吸气开口；烛焰持续微颤、窗格硬日光缓慢移动、空气尘埃缓慢移动、衣料随呼吸牵动，后景云羊视线正在落向信封。背景不得冻结。

【力量作用于环境介质】指腹夹纸先让纸边轻弯，再让信封完整离桌；左手只托下缘，不穿模、不吸附、不复制、不撕裂、不翻面。云羊不得碰信封。禁止信封离手悬空、瞬移、复制或出现文字。

【身份与连续性】陈迹严格十七岁、云羊严格十七岁；使用E36身份参考，不得成年化、换脸、分身、同脸复制、肢体融合或嘴部遮挡。唯一无字空信封由案面连续转移至陈迹双手，终态对应@图片4。禁止降速填时、插帧填时、循环动作、字幕、水印、Logo。
"""
    PROMPT.write_text(prompt, encoding="utf-8")
    prompt_sha = sha(PROMPT)
    audio_sha = sha(AUDIO)

    config = json.loads(SOURCE.read_text(encoding="utf-8"))
    config.update({
        "status": "READY_TO_SUBMIT",
        "episode_paid_credits_before": 7489,
        "output_dir": "working_assets/e36_recovery_10000_20260730/u11_r1b_video",
        "qa_dir": rel(QA),
        "anchor_count_plan_ref": rel(ANCHOR_PLAN),
        "common_sense_causality_plan_ref": rel(CAUSALITY_PLAN),
        "period_lock_plan_ref": rel(PERIOD_PLAN),
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST),
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "dialogue_prompt_gate_ref": rel(DIALOGUE_GATE),
    })
    task = config["tasks"][0]
    task.update({
        "task_key": "E36-CW-U11-R1B-EXACT-AUDIO-RECOVERY-10000",
        "source_id": "E36-CW-U11-R1B-EXACT-AUDIO-RECOVERY-10000",
        "batch_id": "E36-U11-R1B-EXACT-AUDIO-RECOVERY-10000",
        "source_segment_id": "U11-R1B",
        "visual_zone": "E36-U11-CLINIC-ENVELOPE-TRANSFER",
        "duration_seconds": 6,
        "duration": 6,
        "edit_target_duration_seconds": 6,
        "status": "READY_TO_SUBMIT",
        "model": "seedance-2.0-fast",
        "prompt_path": rel(PROMPT),
        "prompt_file": rel(PROMPT),
        "prompt_sha256": prompt_sha,
        "reference_images": [rel(CHENJI), rel(YUNYANG), rel(A1), rel(A2)],
        "reference_image_asset_ids": ["fxmrcf57zd7", "4628tw7x1kh", "g7vyo26qdg9", "iw1o3d53u5k"],
        "reference_audios": [rel(AUDIO)],
        "reference_audio_asset_ids": [],
        "planned_reference_image_count": 2,
        "state_reference_minimum": 2,
        "native_dialogue_required": True,
        "visible_speaker_required": True,
        "temporal_visual_qa_required": True,
        "visual_entity_ids": ["chenji", "yunyang"],
        "targeted_unit_replacement": True,
        "changed_input_repair": False,
        "unchanged_retry": False,
        "max_retries": 0,
        "anchor_image_qa_ref": rel(A2_QA),
    })
    task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 6, "rationale": "Exact4.423417s Chenji line fits0.20-4.65 with1.35s closed-mouth inspection tail.", "edit_policy": "Preserve exact native line and continuous table-to-hands transfer; no retiming, post-dub, filler or repeated frames."}
    task["reference_image_sequence"] = [
        {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": rel(CHENJI), "sha256": sha(CHENJI), "identity_reference": True},
        {"asset_label": "@图片2", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "yunyang", "path": rel(YUNYANG), "sha256": sha(YUNYANG), "identity_reference": True},
        {"asset_label": "@图片3", "role": "ACCEPTED_START_MOTION_LAYOUT_AND_PROP_AUTHORITY", "state_id": "U11-A1", "path": rel(A1), "sha256": sha(A1), "identity_reference": False},
        {"asset_label": "@图片4", "role": "ACCEPTED_TERMINAL_PROP_OWNERSHIP_AUTHORITY", "state_id": "U11-A2", "path": rel(A2), "sha256": sha(A2), "identity_reference": False},
    ]
    task["dialogue"] = [{"dia_id": "E36-U11-R1-D02", "speaker": "陈迹", "spoken_text": TEXT, "start_seconds": 0.20, "end_seconds": 4.65, "breath_after_seconds": 0.0, "expression": "沉声判断规矩之外才有真东西并接管证物", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}]
    task["dialogue_audio_assets"] = [{"dia_id": "E36-U11-R1-D02", "speaker_id": "chenji", "character_name": "陈迹", "spoken_text": TEXT, "audio_slot": "@音频1", "path": rel(AUDIO), "sha256": audio_sha, "duration_seconds": audio_qa["duration_seconds"], "reference_segment_start_seconds": 0.0, "reference_segment_end_seconds": audio_qa["duration_seconds"], "voice_reference_asset_id": CHENJI_VOICE_ASSET_ID, "voice_derivation_status": "PASS", "source_voice": f"AGENTCUT_SPEECH_GENERATION:{audio_receipt['task_id']}", "voice_gender": "male", "mode": "exact_dialogue_audio_reference", "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE"}]
    task["performance_spec"] = {"schema": "qingshan.performance_generation_spec.v2", "prop_ownership": {"唯一无字空信封": "由旧木案连续转移至陈迹双手；云羊全段不接触"}, "motion_beats": [
        {"start_seconds": 0.0, "end_seconds": 0.20, "subject": "陈迹、云羊、空信封", "action": "陈迹夹紧近侧纸边并吸气，云羊闭口看信封", "contact_point": "陈迹右手指腹与纸边；信封底面与桌面", "direction": "右手由左下向桌中收拢", "end_state": "指腹夹紧且陈迹准备开口", "intent": "接管证物", "visible_causality": "前句异常判断促使陈迹取信", "expression": "冷静判断", "viewer_read": "陈迹将回应并取信"},
        {"start_seconds": 0.20, "end_seconds": 2.75, "subject": "陈迹、空信封", "action": "陈迹说前半句并夹住纸边把信封提离案面", "contact_point": "右手拇指食指与近侧纸边", "direction": "信封由桌中向胸前下方上提后收", "end_state": "信封离案且仅由陈迹右手持有", "intent": "指出规矩之外藏真相", "visible_causality": "判断落定后开始鉴证", "expression": "克制笃定", "viewer_read": "证物已被陈迹接管"},
        {"start_seconds": 2.75, "end_seconds": 4.65, "subject": "陈迹、空信封", "action": "陈迹连续说完后半句，左手托住下缘形成双手持有", "contact_point": "右手夹近侧纸边，左手托远侧下缘", "direction": "左手由下向上托，信封稳到胸前", "end_state": "末字落下闭口，陈迹双手唯一持有信封", "intent": "下令拿信并立即检查", "visible_causality": "取信动作兑现对白要求", "expression": "沉着专注", "viewer_read": "规矩谜面转入证物鉴定"},
        {"start_seconds": 4.65, "end_seconds": 6.0, "subject": "陈迹、云羊、空信封", "action": "陈迹闭口检查折痕，云羊闭口微倾但不触碰", "contact_point": "仅陈迹双手与信封两侧纸边", "direction": "陈迹视线沿折痕向下，云羊视线移向信封", "end_state": "陈迹唯一持有信封，云羊不接触", "intent": "建立鉴证终态", "visible_causality": "信封到手后开始检查", "expression": "专注、警觉", "viewer_read": "下一拍将读出纸张线索"},
    ]}
    task["multimodal_entity_bindings"] = [
        {"entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装", "visual_reference": rel(CHENJI), "visual_reference_sha256": sha(CHENJI), "identity_image_slot": "@图片1", "voice_reference": rel(AUDIO), "voice_reference_sha256": audio_sha, "voice_reference_asset_id": CHENJI_VOICE_ASSET_ID, "audio_slot": "@音频1", "dialogue_audio_slots": ["@音频1"], "visible_speaker": True, "lip_sync": True, "prop_owners": {"唯一无字空信封": "终态双手唯一持有"}, "ability_owners": []},
        {"entity_id": "yunyang", "character_name": "云羊", "registry_id": "CHAR-云羊-古装", "visual_reference": rel(YUNYANG), "visual_reference_sha256": sha(YUNYANG), "identity_image_slot": "@图片2", "visible_speaker": False, "lip_sync": False, "prop_owners": {"唯一无字空信封": "全段不接触"}, "ability_owners": []},
    ]
    task["multimodal_binding_sha256"] = digest(task["multimodal_entity_bindings"])
    task["keyframe_interpolation_gate"] = {"status": "PASS", "stage": "CANDIDATE_PREFLIGHT", "anchor_count": 2, "adjacent_pairs_checked": 1, "checked_adjacent_pairs": 1, "candidate_recheck_required": True, "physical_interpolation_or_declared_cut": "PASS_CONTINUOUS_TABLE_TO_CHENJI_HANDS_TRANSFER", "reason": "Accepted A1 and A2 share axis, identities and room; the explicit pinch-lift-support chain physically reaches Chenji-only terminal ownership.", "qa_reference": rel(A2_QA)}

    prompt_manifest = json.loads((SOURCE_DIR / "E36_U11_R1A_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json").read_text(encoding="utf-8"))
    next(row for row in prompt_manifest["rows"] if row["unit_id"] == "U11").update({"scene_id": "E36-CW-S02", "weather": "INTERIOR_CLEAR_HARSH_SUN", "prompt_path": rel(PROMPT), "prompt_sha256": prompt_sha})
    write(PROMPT_MANIFEST, prompt_manifest)
    dialogue_manifest = json.loads((SOURCE_DIR / "E36_U11_R1A_DIALOGUE_MANIFEST_V1.json").read_text(encoding="utf-8"))
    dialogue_manifest["rows"] = [row for row in dialogue_manifest["rows"] if row.get("video_unit_id") != "U11"]
    dialogue_manifest["rows"].append({"video_unit_id": "U11", "dia_id": "E36-U11-R1-D02", "status": "PASS", "speaker": "陈迹", "speaker_id": "chenji", "spoken_text": TEXT, "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "path": rel(AUDIO), "sha256": audio_sha, "start_seconds": 0.20, "end_seconds": 4.65, "breath_after_seconds": 0.0, "expression": "沉声判断规矩之外才有真东西并接管证物"})
    write(DIALOGUE_MANIFEST, dialogue_manifest)
    write(DIALOGUE_GATE, {"schema": "qingshan.dialogue_prompt_gate.v1", "episode": "E36", "unit_id": "U11", "source_segment_id": "U11-R1B", "source_cl2x": "CL2X-834", "source_mailbox_sha256": MAILBOX_SHA, "status": "PASS", "canonical_script_sha256": SCRIPT_SHA, "manifest_sha256": MANIFEST_SHA, "dialogue": task["dialogue"], "checks": {"canonical_and_manifest_sha_match": "PASS", "exact_text_in_prompt": "PASS", "exact_audio_asr": "PASS_1P0", "source_speech_duration": "PASS_4P423417_WITHIN6S", "single_visible_speaker": "PASS_CHENJI_ONLY", "silent_yunyang": "PASS_BOUND_CLOSED_MOUTH", "native_mandarin_required": "PASS", "lip_breath_expression_sync": "PASS", "closed_mouth_tail": "PASS_1P35", "action_contract": "PASS_SUBJECT_ACTION_CONTACT_DIRECTION_END_STATE", "first_frame_motion_state": "PASS", "environment_life": "PASS", "period_weather_continuity": "PASS_INTERIOR_CLEAR_HARSH_SUN", "visible_text": "PASS_FORBIDDEN_ALL", "credit_limit": "PASS_7489_PLUS96_LE10000", "independent_transcript_recovery": "PASS_U11_R1B_FIRST_ATTEMPT"}, "failures": [], "blocked_by": None, "submission_allowed_after_supervisor_precheck": True})
    write(ANCHOR_PLAN, {"schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E36", "planned_reference_image_count": 2, "units": [{"unit_id": "U11", "source_segment_id": "U11-R1B", "planned_reference_image_count": 2, "reference_image_task_keys": ["U11-A1", "U11-A2"], "keyframe_interpolation_gate": task["keyframe_interpolation_gate"], "anchor_count_decision": {"planned_reference_image_count": 2, "reason": "The blank envelope changes ownership from tabletop to Chenji-only hands, so accepted start and terminal authorities are both required.", "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": True, "non_interpolable_terminal_state": True}, "anchor_roles": ["accepted_start_motion_and_tabletop_prop_authority", "accepted_terminal_chenji_only_prop_ownership_authority"], "action_design_class": "two_anchor_native_dialogue_prop_transfer"}}]})
    write(CAUSALITY_PLAN, {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E36", "units": [{"unit_id": "U11", "source_segment_id": "U11-R1B", "causality": {"applicable": True, "purpose": "陈迹回应规矩异常并接管空信封鉴证。", "intended_effect": "信封由案面连续转移为陈迹唯一持有。", "visible_causality": "指腹夹纸、提离案面、左手托边、双手持稳。", "viewer_read": "规矩之外的真东西将从纸张本身被查出。", "preconditions": ["A1和A2图片QA通过", "陈迹和云羊均17岁", "信封唯一且无字"], "mechanism_chain": ["右手夹近侧纸边", "信封提离案面", "左手托远侧下缘", "陈迹双手持稳检查折痕"], "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若缺少夹纸、离案和托边过程，A1到A2的物权转移没有可见原因。"}, "prop_function_status": "PASS", "evidence_refs": [rel(PROMPT), rel(A2_QA), rel(AUDIO_QA)]}}]})
    write(PERIOD_PLAN, {"schema": "qingshan.anachronism_lock_plan.v1", "episode": "E36", "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "canonical_script_sha256": SCRIPT_SHA, "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", f"{config['scene_contract_ref']}#E36-CW-S02"]}, "units": [{"unit_id": "U11", "source_segment_id": "U11-R1B", "period_lock": {"status": "PASS", "reviewed_visible_elements": ["太平医馆密室旧木案", "古代交领布衣", "裸蜡烛古式烛台", "直棂木窗", "唯一无字空信封"], "detected_anachronisms": [], "forbidden_elements": ["现代物件", "现代文字", "玻璃罩煤油灯", "民国灯具"], "exception_approvals": {}, "evidence_refs": [rel(A1), rel(A2), rel(PROMPT)]}}]})
    write(CONFIG, config)
    print(json.dumps({"status": "PASS", "config": str(CONFIG), "config_sha256": sha(CONFIG), "prompt": str(PROMPT), "prompt_sha256": prompt_sha, "audio_sha256": audio_sha, "a1_sha256": sha(A1), "a2_sha256": sha(A2)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
