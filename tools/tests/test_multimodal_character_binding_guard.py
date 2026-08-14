import hashlib
import atexit
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools import multimodal_character_binding_guard as guard
from tools.multimodal_character_binding_guard import binding_digest, evaluate_batch, evaluate_task


ROOT = guard.ROOT
CHENJI_IMAGE = "fixtures/chenji.jpg"
CHENJI_AUDIO = "fixtures/chenji.wav"
_PORTABLE_ROOT: Path | None = None


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def setUpModule() -> None:
    global ROOT, CHENJI_IMAGE, CHENJI_AUDIO, _PORTABLE_ROOT
    _PORTABLE_ROOT = Path(tempfile.mkdtemp(prefix="multimodal-binding-portable-"))
    ROOT = _PORTABLE_ROOT
    CHENJI_IMAGE = "fixtures/chenji.jpg"
    CHENJI_AUDIO = "fixtures/chenji.wav"
    chenji_image = ROOT / CHENJI_IMAGE
    chenji_audio = ROOT / CHENJI_AUDIO
    yao_image_rel = "assets/reference/e08_api_fallback_20260709/characters/CHAR-yao-taiyi-card-clean-20260709.jpg"
    yao_image = ROOT / yao_image_rel
    for path, payload in ((chenji_image, b"portable-chenji-image"), (chenji_audio, b"portable-chenji-audio"), (yao_image, b"portable-yao-image")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    guard.ROOT = ROOT
    guard.VOICE_REGISTRY = ROOT / "configs/voice.json"
    guard.AGENTCUT_VOICE_POLICY = ROOT / "configs/voice_policy.json"
    guard.CHARACTER_REGISTRY = ROOT / "configs/characters.json"

    yao_policy = {
        "entity_id": "yao_taiyi",
        "identity": "portable physician",
        "social_position": "trusted elder",
        "temperament": "calm",
        "dramatic_function": "judgment",
        "voice_id": "portable-voice",
        "voice_name": "portable elder",
        "sample_text": "portable sample",
        "emotion": "calm",
        "speed": 0.9,
    }
    yao_brief_sha = guard._performance_brief_sha256(yao_policy)
    _write_json(guard.VOICE_REGISTRY, {"major_roles": [
        {
            "entity_id": "chenji", "gender": "male", "status": "LOCKED_PRODUCTION_READY",
            "remote_asset_id": "cypqud0bu7t", "forbidden_replacements": ["zh-CN-YunxiNeural"],
        },
        {
            "entity_id": "yao_taiyi", "gender": "male",
            "status": "AGENTCUT_GENERATED_REGISTERED_PRODUCTION_READY",
            "remote_asset_id": "portable-yao-voice", "source_generator": "AGENTCUT_SPEECH_GENERATION",
            "agentcut_capability": "AGENTCUT-SPEECH-001", "generation_task_id": "portable-task",
            "registration_receipt": "portable-registration.json", "qa_receipt": "portable-qa.json",
            "generation_voice_id": yao_policy["voice_id"], "generation_voice_name": yao_policy["voice_name"],
            "performance_brief_sha256": yao_brief_sha,
        },
    ]})
    _write_json(guard.AGENTCUT_VOICE_POLICY, {"roles": [yao_policy]})
    _write_json(guard.CHARACTER_REGISTRY, {"characters": {
        "CHAR-陈迹-古装": {"generation_reference_image": CHENJI_IMAGE},
        "CHAR-姚太医-古装": {"generation_reference_image": yao_image_rel},
    }})

    role_swap = correct_chenji_task()
    role_swap.update({"task_key": "E32-CW-U10B", "prompt": "黑衣陈迹面向镜头自然说话。"})
    _write_json(
        ROOT / "workflow/test_fixtures/multimodal_binding/ROLE_SWAP.json",
        {"episode": "PORTABLE", "tasks": [role_swap]},
    )
    unbound_tasks = [
        {"task_key": key, "tool_type": "video_generation", "prompt": "陈迹与云羊同框对话。"}
        for key in ("E32-CW-U16B-PERFORMANCE-V1", "E32-CW-U16C-PERFORMANCE-V1")
    ]
    _write_json(
        ROOT / "workflow/test_fixtures/multimodal_binding/UNBOUND_DIALOGUE.json",
        {"episode": "PORTABLE", "tasks": unbound_tasks},
    )
    _write_json(
        ROOT / "workflow/test_fixtures/multimodal_binding/LEGACY_UNBOUND.json",
        {"episode": "PORTABLE", "tasks": [{"task_key": "PORTABLE-U01", "tool_type": "video_generation", "prompt": "陈迹走入房间。"}]},
    )


def tearDownModule() -> None:
    if _PORTABLE_ROOT is not None:
        shutil.rmtree(_PORTABLE_ROOT, ignore_errors=True)


def file_sha(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def correct_chenji_task() -> dict:
    bindings = [{
        "entity_id": "chenji",
        "character_name": "陈迹",
        "registry_id": "CHAR-陈迹-古装",
        "visual_reference": CHENJI_IMAGE,
        "visual_reference_sha256": file_sha(CHENJI_IMAGE),
        "identity_image_slot": "@图片1",
        "voice_reference_asset_id": "cypqud0bu7t",
        "dialogue_audio_slots": ["@音频1"],
        "visible_speaker": True,
        "lip_sync": True,
        "prop_owners": {},
        "ability_owners": [],
    }]
    return {
        "task_key": "E99-U01-VIDEO",
        "tool_type": "video_generation",
        "prompt": "灰衣青年陈迹面向镜头自然说话，其他人物闭口。",
        "reference_images": [CHENJI_IMAGE],
        "reference_image_sequence": [{
            "asset_label": "@图片1",
            "role": "IDENTITY_REFERENCE_CHENJI",
            "path": CHENJI_IMAGE,
            "sha256": file_sha(CHENJI_IMAGE),
        }],
        "dialogue": [{"dia_id": "DIA-001", "speaker": "陈迹", "spoken_text": "先查清楚。"}],
        "dialogue_audio_assets": [{
            "dia_id": "DIA-001",
            "speaker": "陈迹",
            "audio_slot": "@音频1",
            "path": CHENJI_AUDIO,
            "voice_reference_asset_id": "cypqud0bu7t",
            "voice_derivation_status": "PASS",
            "voice_gender": "male",
        }],
        "multimodal_entity_bindings": bindings,
        "multimodal_binding_sha256": binding_digest(bindings),
    }


def test_correct_single_speaker_binding_passes():
    report = evaluate_task(correct_chenji_task())
    assert report["status"] == "PASS", report["failures"]


def test_verified_inline_transport_derivative_preserves_canonical_identity_binding():
    task = correct_chenji_task()
    with TemporaryDirectory() as tmp:
        derivative = Path(tmp) / "chenji-inline.jpg"
        derivative.write_bytes(b"verified transport derivative")
        task["reference_images"] = [str(derivative)]
        task["reference_image_sequence"][0].update({
            "path": str(derivative),
            "sha256": hashlib.sha256(derivative.read_bytes()).hexdigest(),
            "transport_derivative_of": CHENJI_IMAGE,
            "transport_derivative_source_sha256": file_sha(CHENJI_IMAGE),
            "transport_transform": "JPEG_Q92_S444_MAX_1440X2560",
        })
        report = evaluate_task(task)
    assert report["status"] == "PASS", report["failures"]


def test_unverified_transport_derivative_is_blocked():
    task = correct_chenji_task()
    with TemporaryDirectory() as tmp:
        derivative = Path(tmp) / "unknown.jpg"
        derivative.write_bytes(b"unverified")
        task["reference_images"] = [str(derivative)]
        task["reference_image_sequence"][0].update({
            "path": str(derivative),
            "sha256": hashlib.sha256(derivative.read_bytes()).hexdigest(),
            "transport_derivative_of": CHENJI_IMAGE,
            "transport_derivative_source_sha256": "wrong",
            "transport_transform": "JPEG_Q92_S444_MAX_1440X2560",
        })
        report = evaluate_task(task)
    codes = {failure["code"] for failure in report["failures"]}
    assert "IDENTITY_IMAGE_SLOT_PATH_MISMATCH" in codes
    assert "CANONICAL_VISUAL_NOT_FORWARDED_TO_MODEL" in codes


def test_e32_u10b_role_swap_is_blocked():
    path = ROOT / "workflow/test_fixtures/multimodal_binding/ROLE_SWAP.json"
    report = evaluate_batch(json.loads(path.read_text(encoding="utf-8")))
    codes = {failure["code"] for result in report["results"] for failure in result["failures"]}
    assert report["status"] == "FAIL"
    assert "PROMPT_ROLE_APPEARANCE_CONTRADICTION" in codes


def test_e32_two_person_dialogue_without_entity_table_is_blocked():
    path = ROOT / "workflow/test_fixtures/multimodal_binding/UNBOUND_DIALOGUE.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config["tasks"] = [task for task in config["tasks"] if task["task_key"] in {
        "E32-CW-U16B-PERFORMANCE-V1", "E32-CW-U16C-PERFORMANCE-V1"
    }]
    report = evaluate_batch(config)
    codes = {failure["code"] for result in report["results"] for failure in result["failures"]}
    assert report["status"] == "FAIL"
    assert "MISSING_MULTIMODAL_ENTITY_BINDINGS" in codes


def test_episode_local_chenji_tts_is_blocked():
    task = correct_chenji_task()
    task["dialogue_audio_assets"][0]["source_voice"] = "zh-CN-YunxiNeural"
    report = evaluate_task(task)
    codes = {failure["code"] for failure in report["failures"]}
    assert "FORBIDDEN_EPISODE_LOCAL_VOICE" in codes
    assert "GENERIC_TTS_REFERENCE_FORBIDDEN" in codes


def test_overlong_dialogue_is_blocked():
    task = correct_chenji_task()
    task["dialogue"][0]["spoken_text"] = "这是一个明显超过三十个字而且应该在编剧阶段拆成多句或者改成动作表达的冗长说明台词"
    report = evaluate_task(task)
    codes = {failure["code"] for failure in report["failures"]}
    assert "DIALOGUE_LINE_TOO_LONG" in codes


def test_voice_gender_mismatch_is_blocked():
    task = correct_chenji_task()
    task["dialogue_audio_assets"][0]["voice_gender"] = "female"
    report = evaluate_task(task)
    codes = {failure["code"] for failure in report["failures"]}
    assert "SPEAKER_VOICE_GENDER_MISMATCH" in codes


def test_unsourced_visual_effect_is_blocked():
    task = correct_chenji_task()
    task["prompt"] += " 陈迹面前凭空出现蓝色光幕。"
    report = evaluate_task(task)
    codes = {failure["code"] for failure in report["failures"]}
    assert "UNSOURCED_VISUAL_EFFECT" in codes


def test_script_sourced_visual_effect_passes():
    task = correct_chenji_task()
    task["prompt"] += " 陈迹面前出现蓝色光幕。"
    task["effect_provenance"] = [{
        "effect": "光幕",
        "source_type": "CLAUDE_SCRIPT",
        "source_ref": "scripts/E99.md#beat-1",
    }]
    report = evaluate_task(task)
    assert report["status"] == "PASS", report["failures"]


def test_pose_first_and_unmotivated_slow_motion_are_blocked():
    task = correct_chenji_task()
    task["prompt"] += " 陈迹先摆姿势，随后以慢动作转身。"
    report = evaluate_task(task)
    codes = {failure["code"] for failure in report["failures"]}
    assert "POSE_FIRST_ACTION_DIRECTIVE" in codes
    assert "UNMOTIVATED_SLOW_MOTION_DIRECTIVE" in codes


def test_explicit_slow_motion_prohibition_is_not_a_positive_directive():
    task = correct_chenji_task()
    task["prompt"] += " 实速，禁止慢镜头。\nNEGATIVE_PROMPT: slow motion, replay."
    report = evaluate_task(task)
    codes = {failure["code"] for failure in report["failures"]}
    assert "UNMOTIVATED_SLOW_MOTION_DIRECTIVE" not in codes


def test_explicit_nonvisual_name_mention_does_not_require_face_binding():
    task = correct_chenji_task()
    task["prompt"] += " 陈迹说明这道命令不走云羊那条线。"
    task["nonvisual_entity_mentions"] = ["yunyang"]
    report = evaluate_task(task)
    assert report["status"] == "PASS", report["failures"]


def test_nonvisual_declaration_cannot_hide_authored_character_action():
    task = correct_chenji_task()
    task["prompt"] += " 云羊从门外走入。"
    task["nonvisual_entity_mentions"] = ["yunyang"]
    task["performance_spec"] = {
        "motion_beats": [{
            "subject": "云羊",
            "action": "云羊从门外走入",
            "end_state": "云羊站在陈迹身侧",
            "expression": "警觉",
        }]
    }
    report = evaluate_task(task)
    codes = {failure["code"] for failure in report["failures"]}
    assert "MISSING_ENTITY_BINDING" in codes


def test_explicit_visual_cast_is_authority_for_offscreen_documentary_motion_mention():
    task = correct_chenji_task()
    task["prompt"] += " 陈迹指着卷宗上严敬的位置，不生成严敬本人。"
    task["visual_entity_ids"] = ["chenji"]
    task["nonvisual_entity_mentions"] = ["yanjing"]
    task["performance_spec"] = {
        "motion_beats": [{
            "subject": "陈迹",
            "action": "陈迹指向卷宗上的严敬位置",
            "end_state": "手指停在记录处，严敬不出镜",
            "expression": "专注",
        }]
    }
    report = evaluate_task(task)
    assert report["status"] == "PASS", report["failures"]


def test_yao_taiyi_cannot_speak_without_binding_registered_voice():
    yao_image = "assets/reference/e08_api_fallback_20260709/characters/CHAR-yao-taiyi-card-clean-20260709.jpg"
    bindings = [{
        "entity_id": "yao_taiyi",
        "character_name": "姚太医",
        "registry_id": "CHAR-姚太医-古装",
        "visual_reference": yao_image,
        "visual_reference_sha256": file_sha(yao_image),
        "identity_image_slot": "@图片1",
        "voice_reference_asset_id": None,
        "dialogue_audio_slots": ["@音频1"],
        "visible_speaker": True,
        "lip_sync": True,
        "prop_owners": {},
        "ability_owners": [],
    }]
    task = {
        "task_key": "E99-YAO-VIDEO",
        "tool_type": "video_generation",
        "prompt": "姚太医开口说话。",
        "reference_images": [yao_image],
        "reference_image_sequence": [{"asset_label": "@图片1", "role": "IDENTITY_REFERENCE_YAO_TAIYI", "path": yao_image}],
        "dialogue": [{"dia_id": "DIA-YAO", "speaker": "姚太医", "spoken_text": "臣明白。"}],
        "dialogue_audio_assets": [{"dia_id": "DIA-YAO", "speaker": "姚太医", "audio_slot": "@音频1"}],
        "multimodal_entity_bindings": bindings,
        "multimodal_binding_sha256": binding_digest(bindings),
    }
    report = evaluate_task(task)
    codes = {failure["code"] for failure in report["failures"]}
    assert "CANONICAL_VOICE_BINDING_MISMATCH" in codes
    assert "DIALOGUE_AUDIO_CANONICAL_VOICE_PROVENANCE_MISSING" in codes


def test_e34_cannot_resume_with_legacy_unbound_character_task():
    path = ROOT / "workflow/test_fixtures/multimodal_binding/LEGACY_UNBOUND.json"
    report = evaluate_batch(json.loads(path.read_text(encoding="utf-8")))
    codes = {failure["code"] for result in report["results"] for failure in result["failures"]}
    assert report["status"] == "FAIL"
    assert "MISSING_MULTIMODAL_ENTITY_BINDINGS" in codes


def load_tests(loader, tests, pattern):
    if _PORTABLE_ROOT is None:
        setUpModule()
        atexit.register(tearDownModule)
    suite = unittest.TestSuite()
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            suite.addTest(unittest.FunctionTestCase(value))
    return suite
