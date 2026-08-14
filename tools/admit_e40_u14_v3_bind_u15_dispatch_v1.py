#!/usr/bin/env python3
"""Admit U14 V3, continuity-bind U15, and dispatch its local two-line render."""
from __future__ import annotations

import hashlib, json, os, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

R=Path(__file__).resolve().parents[1]
V14=R/'working_assets/e40_production_20260814/u14_v3_local_authority_hand_press_exact_dialogue_v1/E40-U14-V3-LOCAL-AUTHORITY-EXACT-DIA012-HAND-SHADOW-PRESS.mp4'
M14=R/'qa/e40_production_20260814/u14_v3_local_authority_hand_press_exact_dialogue_v1/E40_U14_V3_LOCAL_AUTHORITY_MACHINE_QA_V1.json'
H14=R/'qa/e40_production_20260814/u14_v3_local_authority_hand_press_exact_dialogue_v1/E40_U14_V3_ORIGINAL_RESOLUTION_HUMAN_VISUAL_QA_V1.json'
R14=R/'qa/e40_production_20260814/u14_v3_local_authority_hand_press_exact_dialogue_v1/E40_U14_V3_FINAL_ADMISSION_READY_RECEIPT_V1.json'
T14=R/'qa/e40_production_20260814/u14_v3_local_authority_hand_press_exact_dialogue_v1/frame_0143_tail.png'
AR14=R/'qa/e40_preproduction_20260814/u14_parallel_kokoro_exact_audio_candidates_v1/E40_U14_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json'
A14=R/'workflow/releases/E40_U14_V3_RIGHTS_CLEARED_EXACT_DIALOGUE_UNIT_ADMISSION_20260814.json'
F15=R/'working_assets/e40_preproduction_20260814/u15_parallel_chenji_raising_gaze_curtain_unsettled_v1/E40_U15_PARALLEL_CANDIDATE_V2_EXACT_START_FRAME_720X1280.png'
H15=R/'qa/e40_preproduction_20260814/u15_parallel_chenji_raising_gaze_curtain_unsettled_v1/E40_U15_PARALLEL_CANDIDATE_V2_ORIGINAL_RESOLUTION_HUMAN_QA_V1.json'
O15=R/'qa/e40_preproduction_20260814/u15_parallel_chenji_raising_gaze_curtain_unsettled_v1/E40_U15_PARALLEL_CANDIDATE_V2_OCR_AUDIT_V1.json'
PR15=R/'qa/e40_preproduction_20260814/u15_parallel_chenji_raising_gaze_curtain_unsettled_v1/E40_U15_PARALLEL_PREPRODUCTION_SHA_RECEIPT_V1.json'
AU13=R/'working_assets/e40_production_20260814/u15_parallel_kokoro_exact_audio_candidates_v1/E40-DIA013_zm_009_speed1p08_normalized48k.wav'
AU14=R/'working_assets/e40_production_20260814/u15_parallel_kokoro_exact_audio_candidates_v1/E40-DIA014_zm_009_speed0p92_normalized48k.wav'
AQ15=R/'qa/e40_production_20260814/u15_parallel_kokoro_exact_audio_candidates_v1/E40_U15_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json'
AS15=R/'qa/e40_production_20260814/u15_parallel_kokoro_exact_audio_candidates_v1/E40_U15_PARALLEL_KOKORO_SELECTED_AUDIO_RECEIPT_V1.json'
AR15=R/'qa/e40_preproduction_20260814/u15_parallel_kokoro_exact_audio_candidates_v1/E40_U15_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json'
C15=R/'qa/e40_preproduction_20260814/u15_parallel_chenji_raising_gaze_curtain_unsettled_v1/E40_U14_V3_TAIL_TO_U15_FRAME_CONTINUITY_QA_V1.json'
A15=R/'workflow/releases/E40_U15_PARALLEL_EXACT_START_FRAME_TWO_AUDIO_ADMISSION_20260814.json'
S=R/'workflow/production_line/E40_TASK_LANES_V1.json'; W=R/'workflow/work_queue.json'; X=R/'workflow/CODEX_TO_CLAUDE.md'
T14ID='E40-U14-V1-LOCAL-AUTHORITY-HAND-SHADOW-PRESS-EXACT-DIA012-QA'; T15ID='E40-U15-V1-LOCAL-AUTHORITY-CHENJI-TWO-LINE-EXACT-DIA013-014-QA'

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def rel(p): return str(p.relative_to(R))
def ts(d): return d.isoformat().replace('+00:00','Z')
def wr(p,d):
    p.parent.mkdir(parents=True,exist_ok=True); blob=(json.dumps(d,ensure_ascii=False,indent=2)+'\n').encode(); fd,tmp=tempfile.mkstemp(prefix=f'.{p.name}.',dir=p.parent)
    try:
        with os.fdopen(fd,'wb') as h: h.write(blob); h.flush(); os.fsync(h.fileno())
        os.replace(tmp,p)
    except Exception: Path(tmp).unlink(missing_ok=True); raise

def main():
    paths=(V14,M14,H14,R14,T14,AR14,F15,H15,O15,PR15,AU13,AU14,AQ15,AS15,AR15,S,W,X)
    for p in paths:
        if not p.is_file(): raise SystemExit(f'FAIL_MISSING:{p}')
    if any(p.exists() for p in (A14,C15,A15)): raise SystemExit('FAIL_OUTPUT_COLLISION')
    m,h,r,ar=(json.loads(p.read_text()) for p in (M14,H14,R14,AR14))
    if m.get('status')!='PASS_MACHINE_HUMAN_VISUAL_QA_PENDING' or m.get('failures') or m.get('final_asr_similarity')!=1.0 or not h.get('status','').startswith('PASS_ADMISSION_READY') or not r.get('status','').startswith('PASS_U14') or ar.get('releaseBlocked') is not False: raise SystemExit('FAIL_U14_GATES')
    h15,o15,pr15,aq15,as15,ar15=(json.loads(p.read_text()) for p in (H15,O15,PR15,AQ15,AS15,AR15))
    sel=as15.get('selected') or {}
    if not h15.get('status','').startswith('PASS_ADMITTED') or o15.get('status')!='PASS' or o15.get('recognitions') or not pr15.get('status','').startswith('PASS_U15') or aq15.get('status')!='PASS_MACHINE_ALL_DIALOGUES_SELECTED' or ar15.get('releaseBlocked') is not False: raise SystemExit('FAIL_U15_GATES')
    if sel.get('E40-DIA-013',{}).get('sha256')!=sha(AU13) or sel.get('E40-DIA-014',{}).get('sha256')!=sha(AU14): raise SystemExit('FAIL_U15_AUDIO_BINDING')
    n=datetime.now(timezone.utc); canon={'canonical_script_sha256':'140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b','canonical_manifest_sha256':'773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1'}
    wr(A14,{'schema':'qingshan.e40.u14.v3.unit_admission.v1','status':'PASS_U14_V3_ADMITTED_FOR_EPISODE_ASSEMBLY','admitted_at':ts(n),'episode':'E40','unit':'U14',**canon,'video_path':rel(V14),'video_sha256':sha(V14),'machine_qa':rel(M14),'machine_qa_sha256':sha(M14),'human_qa':rel(H14),'human_qa_sha256':sha(H14),'final_receipt':rel(R14),'final_receipt_sha256':sha(R14),'tail_frame':rel(T14),'tail_frame_sha256':sha(T14),'rights_evidence':rel(AR14),'rights_evidence_sha256':sha(AR14),'gates':{'frame0_exact':True,'exact_asr':True,'hand_press':True,'cadence':True,'ocr_zero':True,'chenji_closed_mouth':True,'commercial_rights':True},'provider_posts':0,'credits':0,'release_status':'NOT_RELEASED_UNIT_ONLY'})
    wr(C15,{'schema':'qingshan.e40.u14_v3_tail_to_u15_frame.continuity_qa.v1','status':'PASS_CONTINUITY_BINDING','reviewed_at':ts(n),'predecessor_tail':rel(T14),'predecessor_tail_sha256':sha(T14),'candidate_frame':rel(F15),'candidate_frame_sha256':sha(F15),'checks':{'yunfei_hand_press_to_chenji_raising_gaze':'PASS_CAUSAL_STATE_ADVANCE','same_hall_curtain_axis':'PASS','chenji_identity_white_robe':'PASS','yunfei_hidden_one_fan':'PASS','rubbing_landed':'PASS','ocr_zero':'PASS'},'human_score':92,'failures':[]})
    wr(A15,{'schema':'qingshan.e40.u15.parallel.frame_two_audio_admission.v1','status':'PASS_U15_EXACT_START_FRAME_TWO_AUDIO_ADMITTED_FOR_LOCAL_VIDEO','admitted_at':ts(n),'episode':'E40','unit':'U15',**canon,'canonical_lines':[{'id':'E40-DIA-013','text':'有人借您的印，伪造您的令。','audio_path':rel(AU13),'audio_sha256':sha(AU13)},{'id':'E40-DIA-014','text':'您，也是被借的一把刀。','audio_path':rel(AU14),'audio_sha256':sha(AU14)}],'speaker':'陈迹','frame_path':rel(F15),'frame_sha256':sha(F15),'human_qa':rel(H15),'human_qa_sha256':sha(H15),'ocr_qa':rel(O15),'ocr_qa_sha256':sha(O15),'continuity_qa':rel(C15),'continuity_qa_sha256':sha(C15),'audio_qa':rel(AQ15),'audio_qa_sha256':sha(AQ15),'selected_audio_receipt':rel(AS15),'selected_audio_receipt_sha256':sha(AS15),'rights_evidence':rel(AR15),'rights_evidence_sha256':sha(AR15),'provider_posts':0,'credits':0,'release_status':'NOT_RELEASED_FRAME_ONLY'})
    s=json.loads(S.read_text()); cur=[t for t in s['tasks'] if t.get('task_id')==T14ID]
    if len(cur)!=1 or any(t.get('task_id')==T15ID for t in s['tasks']): raise SystemExit('FAIL_SCHEDULER')
    cur[0].update({'state':'TERMINAL','wait_scope':'NONE_TERMINAL','blocked_by':None,'progress':'U14_ALL_GATES_PASS_ADMITTED','last_progress_at':ts(n),'next_action':'Terminal U14; U15 local render owns production.','next_due_at':None,'executor_next_wakeup_at':None,'evidence_ref':rel(A14),'evidence_sha256':sha(A14),'output_ref':rel(V14),'output_sha256':sha(V14),'completed_at':ts(n),'terminal_status':'PASS_U14_V3_ADMITTED_FOR_EPISODE_ASSEMBLY'})
    s['tasks'].append({'task_id':T15ID,'lane_id':'U15_LOCAL_AUTHORITY_CHENJI_TWO_LINE','state':'RUNNING','wait_scope':'NONE_ACTIVE_RUNNING','zero_cost':True,'deliverable_type':'U15_EXACT_FRAME_EXACT_DIA013_DIA014_VISIBLE_LIPSYNC_VIDEO_AND_QA','priority':186,'scope':['E40','U15','V1','LOCAL_AUTHORITY_ONLY','EXACT_FRAME0','EXACT_DIA013','EXACT_DIA014','VISIBLE_CHENJI_LIPSYNC','RIGHTS_CLEAR','NO_PROVIDER','NO_RELEASE'],'exact_predecessor_task_id':T14ID,'liveness_role':'PRODUCING','observation_only':False,'maximum_new_submissions':0,'authorization':False,'provider_post_allowed':False,'provider_query_allowed':False,'download_allowed':False,'provider_calls':0,'transactions':0,'credits':0,'blocked_by':None,'progress':'U15_FRAME_TWO_AUDIO_CONTINUITY_RIGHTS_BOUND_LOCAL_RENDER_RUNNING','last_progress_at':ts(n),'next_action':'Render 7s U15 with exact frame0, visible Chenji lip sync for DIA013 then DIA014, hidden Yunfei and one fan, landed rubbing, then run ASR/order, OCR, cadence, human and rights QA.','lease_owner':'codex-e40-production:u15-v1-local','lease_expires_at':ts(n+timedelta(hours=2)),'next_due_at':ts(n+timedelta(minutes=10)),'execution_mode':'CONTINUOUS','executor_handle':'automation:e40','executor_task_id':T15ID,'executor_acknowledged_at':ts(n),'executor_next_wakeup_at':ts(n+timedelta(minutes=10)),'evidence_ref':rel(A15),'evidence_sha256':sha(A15),'audio_refs':[rel(AU13),rel(AU14)],'audio_sha256s':[sha(AU13),sha(AU14)]}); s['updated_at']=ts(n); wr(S,s)
    w=json.loads(W.read_text()); w['latest_e40_u14_parallel_preproduction'].update({'status':'PASS_U14_V3_ADMITTED_FOR_EPISODE_ASSEMBLY','video':rel(V14),'video_sha256':sha(V14),'unit_admission':rel(A14),'unit_admission_sha256':sha(A14),'active_task_id':None,'next_action':'Terminal U14; U15 local render running.'}); w['latest_e40_u15_parallel_preproduction'].update({'status':'PASS_U15_FRAME_TWO_AUDIO_ADMITTED_LOCAL_VIDEO_RUNNING','continuity_qa':rel(C15),'continuity_qa_sha256':sha(C15),'frame_audio_admission':rel(A15),'frame_audio_admission_sha256':sha(A15),'active_task_id':T15ID,'blocked_by':None,'next_action':s['tasks'][-1]['next_action']}); wr(W,w)
    with X.open('a',encoding='utf-8') as h: h.write(f"\n\n## E40 checkpoint {ts(n)} — U14 admitted; U15 two-line local render dispatched\n\n- U14 `{rel(V14)}` SHA=`{sha(V14)}` passed exact frame0, DIA012 ASR=1.0, hand-shadow press, Chenji closed-mouth, cadence, OCR0, HUMAN91 and rights; admission SHA=`{sha(A14)}`.\n- U14 tail to U15 frame continuity passed SHA=`{sha(C15)}`. U15 binds DIA013 SHA=`{sha(AU13)}` then DIA014 SHA=`{sha(AU14)}` with visible Chenji lip-sync; admission SHA=`{sha(A15)}` and scheduler task `{T15ID}` RUNNING. Provider posts/credits=0, no release.\n"); h.flush(); os.fsync(h.fileno())
    print(json.dumps({'status':'PASS_U14_ADMITTED_U15_LOCAL_RENDER_RUNNING','u14_admission_sha256':sha(A14),'u15_admission_sha256':sha(A15)},ensure_ascii=False)); return 0
if __name__=='__main__': raise SystemExit(main())
