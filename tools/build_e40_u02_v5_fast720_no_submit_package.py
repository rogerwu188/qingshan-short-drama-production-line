#!/usr/bin/env python3
"""Persist PF-033 and build E40 U02 V5 Fast720 precheck-only package."""
from __future__ import annotations
import hashlib, json, os, struct, tempfile
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u02_v5_fast720_causal_beats_v1'
PROMPT = BASE / 'E40_U02_V5_FAST720_SILENT_VISUAL_PROMPT_V1.txt'
MANIFEST = BASE / 'E40_U02_V5_FAST720_NO_SUBMIT_MANIFEST_V1.json'
GATE = ROOT / 'qa/e40_preproduction_20260814/u02_v5_fast720_no_submit_package_qa_v1/E40_U02_V5_FAST720_STATIC_GATE_V1.json'
MEMORY = ROOT / 'workflow/claude_writer_agent/GENERATION_PROMPT_FAILURE_MEMORY.json'
FRAME = ROOT / 'working_assets/e40_production_20260814/u02_v3_low_hem_authority_exact_start_frame_retry1/E40_E40-U02-EXACT-START-FRAME-V3-LOW-HEM-AUTHORITY-RETRY1_52180a09-d3ef-47d0-afc1-44d30147c8a2.png'
FRAME_QA = ROOT / 'qa/e40_preproduction_20260814/u02_v3_low_hem_authority_human_qa_v1/E40_U02_V3_LOW_HEM_AUTHORITY_EXACT_START_FRAME_HUMAN_QA_V1.json'
SCRIPT = ROOT / 'workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md'
CANON = ROOT / 'workflow/claude_writer_agent/scripts/E40_manifest_v3.json'
EXPECTED_SCRIPT = '140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b'
EXPECTED_CANON = '773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1'
EXPECTED_FRAME = '2f8841136030bd4f691ddb9faa77badfe52e7caf207f6f6975030703894fe725'

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def portable(path): return str(Path(path).relative_to(ROOT))
def write(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2); handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)
def raw_rgb_sha(path):
    with Image.open(path) as image:
        rgb = image.convert('RGB'); width, height = rgb.size
        digest = hashlib.sha256(struct.pack('>QQ', width, height) + rgb.tobytes()).hexdigest()
    return digest, width, height

def main():
    memory = json.loads(MEMORY.read_text())
    existing = [row for row in memory['rules'] if row.get('id') == 'PF-033']
    pf = {
        'id': 'PF-033',
        'failure': 'U02 V4 used a six-second provider clip and declared the single fan-closing primary action complete at 5.2 seconds. The installed paid-entrypoint precheck rejected it locally with ATOMIC_ACTION_COMPLETION_WINDOW_INVALID and ATOMIC_ACTION_DURATION_INVITES_SLOW_MOTION; no provider request, transaction, task ID or credit occurred.',
        'first_pass_prompt_rule': 'For an action-like Seedance unit, author the provider clip at no more than four seconds and complete the primary atomic action within two seconds; use the stricter U02 target of 1.2 seconds. Any remaining time must contain explicit, independently causal, non-looping state changes rather than stretching, holding or repeating the primary action. A rejected prompt/task key/fingerprint is closed against unchanged replay.',
        'pre_submit_check': 'PROVIDER_DURATION_LE_4S_PRIMARY_ACTION_COMPLETE_LE_1_2S_INDEPENDENT_CAUSAL_WINDOWS_NO_UNCHANGED_REPLAY'
    }
    if existing and existing != [pf]: raise SystemExit('PF-033 collision')
    if not existing:
        memory['rules'].append(pf); memory['updated_at'] = '2026-08-14T06:25:00Z'; write(MEMORY, memory)

    text = PROMPT.read_text()
    checks = {
        'canonical_script_sha_match': sha(SCRIPT) == EXPECTED_SCRIPT,
        'canonical_manifest_sha_match': sha(CANON) == EXPECTED_CANON,
        'exact_start_frame_sha_match': sha(FRAME) == EXPECTED_FRAME,
        'human_qa_pass': json.loads(FRAME_QA.read_text()).get('status') == 'PASS_ADMITTED_EXACT_START_FRAME_ONLY',
        'pf033_memory_bound': any(row.get('id') == 'PF-033' for row in json.loads(MEMORY.read_text())['rules']),
        'prompt_fast_only': 'seedance-2.0-fast' in text and 'seedance-2.0-pro' not in text.lower() and 'seedance-2.0-mini' not in text.lower(),
        'prompt_720p': '720p' in text,
        'prompt_four_seconds': '4秒' in text and '6秒' not in text,
        'prompt_primary_1_2_seconds': '1.20秒内完成' in text,
        'prompt_independent_causal_beats': text.count('独立后继动作') == 3,
        'prompt_silent_visual': '无声视觉源' in text and '不得生成口型' in text,
        'prompt_low_hem_lock': '画高不超过2%' in text and '帘脚继续贴底' in text,
    }
    if not all(checks.values()): raise SystemExit('static prebuild failed ' + json.dumps(checks, ensure_ascii=False))
    prompt_sha = sha(PROMPT); raw, width, height = raw_rgb_sha(FRAME)
    gate = {'schema':'qingshan.e40.u02.v5.fast720_static_gate.v1','recorded_at':'2026-08-14T06:25:00Z','status':'PASS','checks':checks,
            'model':'seedance-2.0-fast','resolution':'720p','duration_seconds':4,'primary_action_complete_by_seconds':1.2,
            'exact_start_frame_sha256':EXPECTED_FRAME,'prompt_sha256':prompt_sha,'failure_memory_id':'PF-033',
            'provider_posts':0,'provider_queries':0,'transactions':0,'credits':0,'maximum_new_submissions':0}
    write(GATE, gate)
    task = {
        'task_key':'E40-U02-V5-FAST720-LOW-HEM-EXACT-FIRST-FRAME-CAUSAL-BEATS-SILENT-V1','unit_id':'U02','scene_id':'13-1','kind':'hidden_speaker_silent_visual_closeup',
        'action_unit':True,'combat_or_chase':False,'model':'seedance-2.0-fast','resolution':'720p','delivery_target_resolution':'1080p','delivery_transform':'DETERMINISTIC_UPSCALE_ONLY_DO_NOT_CLAIM_NATIVE_1080P',
        'aspect_ratio':'9:16','duration_seconds':4,'generating_count':1,'prompt_file':portable(PROMPT),'prompt_sha256':prompt_sha,
        'failure_memory_ids':['PF-021','PF-032','PF-033'],'material_change_from':'E40-U02-V4-FAST720-LOW-HEM-EXACT-FIRST-FRAME-SILENT-V1',
        'reference_images':[portable(FRAME)],'reference_sha256':[EXPECTED_FRAME],'reference_roles':['EXACT_FIRST_FRAME'],'exact_first_frame_sha256':EXPECTED_FRAME,
        'video_transport':{'mode':'image_to_video_start_frame','endpoint':'/api/v1/generation/image-to-video','start_frame_path':portable(FRAME),'start_frame_sha256':EXPECTED_FRAME,'ordinary_images':[]},
        'frame0_authority_contract':{'source_sha256':EXPECTED_FRAME,'pre_encode_raw_rgb_sha256_required':True,'raw_rgb_sha256':raw,'width':width,'height':height,'semantic_start_frame_human_score':88},
        'post_harvest_exact_frame_gate':{'required':True,'single_frame_prepend_allowed':False,'single_frame_replacement_allowed':False,'frame0_thresholds':{'minimum_ssim':0.98,'maximum_mae':3.0,'maximum_phash_hamming':3},'frame0_to_frame1_continuity_required':True,'frame0_to_frame1_static_freeze_forbidden':True},
        'performance_tempo_contract':{'playback_speed':'REAL_TIME_1X','first_visible_displacement_by_seconds':0.20,'primary_action_complete_by_seconds':1.2,'result_hold_seconds':0.0,'maximum_atomic_window_seconds':1.2,'maximum_action_gap_seconds':0.0,'slow_motion_interpolation_post_speedup_forbidden':True,'atomic_action_windows':[
            {'start_seconds':0.0,'end_seconds':1.2,'action':'半合扇骨短弧收拢、拇指压紧并轻叩一次','state_change':'主动作完成为约三分之二收拢'},
            {'start_seconds':1.2,'end_seconds':2.4,'action':'轻叩因果驱动手腕下降半掌','state_change':'持扇点明显下移'},
            {'start_seconds':2.4,'end_seconds':3.2,'action':'下降后的手腕内旋','state_change':'扇骨投影进一步压窄'},
            {'start_seconds':3.2,'end_seconds':4.0,'action':'腕部内旋的短促气流轻鼓帘中段一次','state_change':'帘中段位移且帘脚仍贴底'}]},
        'identity_owner_count_contract':{'visible_entities':['云妃右手腕与少量袖口'],'right_hand_count':1,'fan_count':1,'fan_owner':'云妃','fan_transfer':'NONE','second_person_allowed':False,'head_face_torso_allowed':False},
        'native_dialogue_required':False,'dialogue_lines':[],'dialogue_transport':'SILENT_VISUAL_WITH_POST_EXACT_AUDIO_NONVISIBLE_MOUTH','reference_audio_asset_ids':[],'exact_dialogue_audio_asset_ids':[],'source_subtitle_policy':'FORBID',
        'video_audio_contract':{'request_audio_inputs':[],'request_dialogue_text':[],'provider_audio_stream_allowed':False,'returned_audio_stream_is_hard_fail':True,'deterministic_audio_strip_allowed_as_remediation':False,'future_agentcut_audio_binding_only_after_visual_pass':True},
        'source_audio_contract':{'source_audio_required_absent':True,'audio_stream_required_absent':True,'low_volume_audio_still_fails':True,'post_harvest_audio_strip_as_admission_fix':False},
        'submission_authorization':{'precheck_only':True,'authorized':False,'paid_submission_allowed':False,'transaction_creation_allowed':False,'maximum_new_submissions':0}}
    manifest = {'schema':'qingshan.e40.u02.v5.fast720_no_submit_manifest.v1','episode':'E40','recorded_at':'2026-08-14T06:25:00Z','status':'READY_LOCAL_PRECHECK_ONLY_NO_PAID_AUTHORIZATION','provider':'giggle',
        'allowed_video_models':['seedance-2.0-fast'],'forbidden_video_models':['seedance-2.0-pro','seedance-2.0-mini','seedance-2.0'],
        'canonical':{'script_path':portable(SCRIPT),'script_sha256':EXPECTED_SCRIPT,'manifest_path':portable(CANON),'manifest_sha256':EXPECTED_CANON},
        'machine_gate_reports':[portable(GATE)],'tasks':[task],
        'submission_policy':{'precheck_only':True,'paid_submission_allowed':False,'provider_post_allowed':False,'durable_transaction_allowed':False,'maximum_new_submissions':0,'same_round_retry_forbidden':True},
        'credits':{'pay':0,'refund':0,'net':0},'blocked_by':'NO_PAID_VIDEO_READINESS_OR_EXECUTION_AUTHORIZATION; U02_VISUAL_NOT_YET_GENERATED_OR_QA_ADMITTED',
        'next_action':'Run installed submitter once with --precheck-only. If it passes, separately certify price, collision, exact-first-frame transport and exactly-once paid readiness before any provider POST.'}
    write(MANIFEST, manifest)
    print(json.dumps({'status':'PASS','memory_sha256':sha(MEMORY),'prompt_sha256':prompt_sha,'gate_sha256':sha(GATE),'manifest_sha256':sha(MANIFEST),'raw_rgb_sha256':raw}))

if __name__ == '__main__': main()
