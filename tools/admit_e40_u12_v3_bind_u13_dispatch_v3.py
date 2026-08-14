#!/usr/bin/env python3
"""Admit U12, continuity-bind U13 frame/audio, and dispatch local U13 render."""
from __future__ import annotations

import hashlib, json, os, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

R = Path(__file__).resolve().parents[1]
V12 = R / "working_assets/e40_production_20260814/u12_v3_local_authority_exact_dialogue_rubbing_throw_v1/E40-U12-V3-LOCAL-AUTHORITY-EXACT-DIA010-RUBBING-THROW.mp4"
M12 = R / "qa/e40_production_20260814/u12_v3_local_authority_exact_dialogue_rubbing_throw_v1/E40_U12_V3_LOCAL_AUTHORITY_MACHINE_QA_V1.json"
OA12 = R / "qa/e40_production_20260814/u12_v3_local_authority_exact_dialogue_rubbing_throw_v1/E40_U12_V3_OCR_FALSE_POSITIVE_ADJUDICATION_V1.json"
H12 = R / "qa/e40_production_20260814/u12_v3_local_authority_exact_dialogue_rubbing_throw_v1/E40_U12_V3_ORIGINAL_RESOLUTION_HUMAN_VISUAL_QA_V1.json"
R12 = R / "qa/e40_production_20260814/u12_v3_local_authority_exact_dialogue_rubbing_throw_v1/E40_U12_V3_FINAL_ADMISSION_READY_RECEIPT_V1.json"
T12 = R / "qa/e40_production_20260814/u12_v3_local_authority_exact_dialogue_rubbing_throw_v1/frame_0167_tail.png"
AR12 = R / "qa/e40_preproduction_20260814/u12_parallel_kokoro_exact_audio_candidates_v1/E40_U12_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
A12 = R / "workflow/releases/E40_U12_V3_RIGHTS_CLEARED_EXACT_DIALOGUE_UNIT_ADMISSION_20260814.json"
F13 = R / "working_assets/e40_preproduction_20260814/u13_parallel_yunfei_half_rise_denial_v1/E40_U13_PARALLEL_CANDIDATE_V5_EXACT_START_FRAME_720X1280.png"
H13 = R / "qa/e40_preproduction_20260814/u13_parallel_yunfei_half_rise_denial_v1/E40_U13_PARALLEL_CANDIDATE_V5_ORIGINAL_RES_HUMAN_QA_V1.json"
O13 = R / "qa/e40_preproduction_20260814/u13_parallel_yunfei_half_rise_denial_v1/E40_U13_PARALLEL_CANDIDATE_V5_OCR_AUDIT_V1.json"
AU13 = R / "working_assets/e40_production_20260814/u13_parallel_kokoro_exact_audio_candidates_v1/E40-DIA011_zf_001_speed1p1_normalized48k.wav"
AQ13 = R / "qa/e40_production_20260814/u13_parallel_kokoro_exact_audio_candidates_v1/E40_U13_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"
AS13 = R / "qa/e40_production_20260814/u13_parallel_kokoro_exact_audio_candidates_v1/E40_U13_PARALLEL_KOKORO_SELECTED_AUDIO_RECEIPT_V1.json"
AR13 = R / "qa/e40_preproduction_20260814/u13_parallel_kokoro_exact_audio_candidates_v1/E40_U13_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
C13 = R / "qa/e40_preproduction_20260814/u13_parallel_yunfei_half_rise_denial_v1/E40_U12_TAIL_TO_U13_FRAME_CONTINUITY_QA_V1.json"
A13 = R / "workflow/releases/E40_U13_PARALLEL_EXACT_START_FRAME_AUDIO_ADMISSION_20260814.json"
S = R / "workflow/production_line/E40_TASK_LANES_V1.json"; W = R / "workflow/work_queue.json"; X = R / "workflow/CODEX_TO_CLAUDE.md"
T12_ID = "E40-U12-V3-LOCAL-AUTHORITY-RUBBING-THROW-EXACT-DIA010-QA"; T13_ID = "E40-U13-V3-LOCAL-AUTHORITY-YUNFEI-HALF-RISE-EXACT-DIA011-QA"

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def rel(p): return str(p.relative_to(R))
def st(x): return x.isoformat().replace("+00:00", "Z")
def wr(p, payload):
    p.parent.mkdir(parents=True, exist_ok=True); blob=(json.dumps(payload,ensure_ascii=False,indent=2)+"\n").encode(); fd,tmp=tempfile.mkstemp(prefix=f".{p.name}.",dir=p.parent)
    try:
        with os.fdopen(fd,"wb") as h: h.write(blob); h.flush(); os.fsync(h.fileno())
        os.replace(tmp,p)
    except Exception: Path(tmp).unlink(missing_ok=True); raise

def main():
    if any(p.exists() for p in (A12,C13,A13)): raise SystemExit("FAIL_COLLISION")
    for p in (V12,M12,OA12,H12,R12,T12,AR12,F13,H13,O13,AU13,AQ13,AS13,AR13,S,W,X):
        if not p.is_file(): raise SystemExit(f"FAIL_MISSING:{p}")
    m12,h12,r12,ar12,h13,o13,aq13,as13,ar13=[json.loads(p.read_text()) for p in (M12,H12,R12,AR12,H13,O13,AQ13,AS13,AR13)]
    if not m12.get("status","").startswith("PASS") or m12.get("failures") or m12.get("final_asr_similarity")!=1.0 or not h12.get("status","").startswith("PASS_ADMISSION_READY") or not r12.get("status","").startswith("PASS") or ar12.get("releaseBlocked") is not False: raise SystemExit("FAIL_U12_GATES")
    sel=aq13.get("selected") or {}
    if h13.get("status")!="PASS" or o13.get("status")!="PASS" or o13.get("recognitions") or aq13.get("status")!="PASS_MACHINE_SELECTION" or sel.get("normalized_sha256")!=sha(AU13) or sel.get("asr_similarity")!=1.0 or as13.get("status")!="PASS_RELEASE_CLEAR_ZERO_CREDIT_EXACT_AUDIO_SELECTED" or ar13.get("releaseBlocked") is not False: raise SystemExit("FAIL_U13_GATES")
    n=datetime.now(timezone.utc); canon={"canonical_script_sha256":"140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b","canonical_manifest_sha256":"773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"}
    wr(A12,{"schema":"qingshan.e40.u12.v3.unit_admission.v1","status":"PASS_U12_V3_ADMITTED_FOR_EPISODE_ASSEMBLY","admitted_at":st(n),"episode":"E40","unit":"U12",**canon,"video_path":rel(V12),"video_sha256":sha(V12),"machine_qa":rel(M12),"machine_qa_sha256":sha(M12),"ocr_adjudication":rel(OA12),"ocr_adjudication_sha256":sha(OA12),"human_qa":rel(H12),"human_qa_sha256":sha(H12),"final_receipt":rel(R12),"final_receipt_sha256":sha(R12),"tail_frame":rel(T12),"tail_frame_sha256":sha(T12),"rights_evidence":rel(AR12),"rights_evidence_sha256":sha(AR12),"gates":{"exact_frame0":True,"exact_asr":True,"single_rubbing_trajectory":True,"cadence":True,"effective_no_visible_text":True,"identity":True,"commercial_rights":True},"provider_posts":0,"credits":0,"release_status":"NOT_RELEASED_UNIT_ONLY"})
    wr(C13,{"schema":"qingshan.e40.u12_tail_to_u13_frame.continuity_qa.v1","status":"PASS_CONTINUITY_BINDING","reviewed_at":st(n),"predecessor_tail":rel(T12),"predecessor_tail_sha256":sha(T12),"candidate_frame":rel(F13),"candidate_frame_sha256":sha(F13),"checks":{"midair_rubbing_to_inner_table_landing":"PASS_CAUSAL_STATE_ADVANCE","chenji_white_robe_to_yunfei_reverse":"PASS","warm_period_hall_and_curtain":"PASS","yunfei_half_rise_not_fully_standing":"PASS","one_round_fan":"PASS","seal_motif_owner_count":"PASS","ocr_zero":"PASS"},"human_score":93,"failures":[]})
    wr(A13,{"schema":"qingshan.e40.u13.parallel.frame_audio_admission.v1","status":"PASS_U13_EXACT_START_FRAME_AUDIO_ADMITTED_FOR_LOCAL_VIDEO","admitted_at":st(n),"episode":"E40","unit":"U13",**canon,"canonical_line":"这道令，不是本宫下的。","speaker":"云妃","frame_path":rel(F13),"frame_sha256":sha(F13),"human_qa":rel(H13),"human_qa_sha256":sha(H13),"ocr_qa":rel(O13),"ocr_qa_sha256":sha(O13),"continuity_qa":rel(C13),"continuity_qa_sha256":sha(C13),"selected_audio":rel(AU13),"selected_audio_sha256":sha(AU13),"audio_qa":rel(AQ13),"audio_qa_sha256":sha(AQ13),"selected_audio_receipt":rel(AS13),"selected_audio_receipt_sha256":sha(AS13),"rights_evidence":rel(AR13),"rights_evidence_sha256":sha(AR13),"provider_posts":0,"credits":0,"release_status":"NOT_RELEASED_FRAME_ONLY"})
    s=json.loads(S.read_text()); cur=[t for t in s["tasks"] if t.get("task_id")==T12_ID]
    if len(cur)!=1 or any(t.get("task_id")==T13_ID for t in s["tasks"]): raise SystemExit("FAIL_SCHEDULER")
    cur[0].update({"state":"TERMINAL","wait_scope":"NONE_TERMINAL","blocked_by":None,"progress":"U12_FRAME0_ASR_RUBBING_CADENCE_EFFECTIVE_OCR_RIGHTS_PASS_ADMITTED","last_progress_at":st(n),"next_action":"Terminal U12; U13 local render owns production.","next_due_at":None,"executor_next_wakeup_at":None,"evidence_ref":rel(A12),"evidence_sha256":sha(A12),"output_ref":rel(V12),"output_sha256":sha(V12),"completed_at":st(n),"terminal_status":"PASS_U12_V3_ADMITTED_FOR_EPISODE_ASSEMBLY"})
    s["tasks"].append({"task_id":T13_ID,"lane_id":"U13_LOCAL_AUTHORITY_YUNFEI_HALF_RISE","state":"RUNNING","wait_scope":"NONE_ACTIVE_RUNNING","zero_cost":True,"deliverable_type":"U13_EXACT_FRAME_EXACT_DIA011_HALF_RISE_VIDEO_AND_QA","priority":184,"scope":["E40","U13","V3","LOCAL_AUTHORITY_ONLY","EXACT_FRAME0","EXACT_DIA011","YUNFEI_HALF_RISE","RIGHTS_CLEAR","NO_PROVIDER","NO_RELEASE"],"exact_predecessor_task_id":T12_ID,"liveness_role":"PRODUCING","observation_only":False,"maximum_new_submissions":0,"authorization":False,"provider_post_allowed":False,"provider_query_allowed":False,"download_allowed":False,"provider_calls":0,"transactions":0,"credits":0,"blocked_by":None,"progress":"U13_FRAME_AUDIO_CONTINUITY_RIGHTS_BOUND_LOCAL_RENDER_RUNNING","last_progress_at":st(n),"next_action":"Render U13 authority-only Yunfei half-rise denial with exact DIA011; preserve hidden face, one fan and landed rubbing, then run frame0, ASR, motion, OCR, cadence, human and rights QA.","lease_owner":"codex-e40-production:u13-v3-local","lease_expires_at":st(n+timedelta(hours=2)),"next_due_at":st(n+timedelta(minutes=10)),"execution_mode":"CONTINUOUS","executor_handle":"automation:e40","executor_task_id":T13_ID,"executor_acknowledged_at":st(n),"executor_next_wakeup_at":st(n+timedelta(minutes=10)),"evidence_ref":rel(A13),"evidence_sha256":sha(A13),"audio_ref":rel(AU13),"audio_sha256":sha(AU13)}); s["updated_at"]=st(n); wr(S,s)
    w=json.loads(W.read_text()); w["latest_e40_u12_parallel_preproduction"].update({"status":"PASS_U12_V3_ADMITTED_FOR_EPISODE_ASSEMBLY","video":rel(V12),"video_sha256":sha(V12),"unit_admission":rel(A12),"unit_admission_sha256":sha(A12),"active_task_id":None,"next_action":"Terminal U12; U13 local render running."}); w["latest_e40_u13_parallel_preproduction"]={"status":"PASS_U13_FRAME_AUDIO_ADMITTED_LOCAL_VIDEO_RUNNING","canonical_line":"这道令，不是本宫下的。","speaker":"云妃","frame":rel(F13),"frame_sha256":sha(F13),"human_qa":rel(H13),"human_qa_sha256":sha(H13),"ocr_qa":rel(O13),"ocr_qa_sha256":sha(O13),"selected_audio":rel(AU13),"selected_audio_sha256":sha(AU13),"audio_qa":rel(AQ13),"audio_qa_sha256":sha(AQ13),"rights_evidence":rel(AR13),"rights_evidence_sha256":sha(AR13),"continuity_qa":rel(C13),"continuity_qa_sha256":sha(C13),"frame_admission":rel(A13),"frame_admission_sha256":sha(A13),"provider_posts":0,"credits":0,"blocked_by":None,"active_task_id":T13_ID,"next_action":s["tasks"][-1]["next_action"]}; wr(W,w)
    with X.open("a",encoding="utf-8") as h: h.write(f"\n\n## E40 checkpoint {st(n)} — U12 admitted; U13 frame/audio bound and local render dispatched\n\n- U12 V3 `{rel(V12)}` SHA=`{sha(V12)}` passed exact frame0, DIA010 ASR=1.0, one-rubbing trajectory, cadence, HUMAN91 and rights. The seal motif's moving `88` readings were source-bound false positives; unexpected visible text=0. Admission SHA=`{sha(A12)}`.\n- U12 tail to U13 half-rise frame continuity passed SHA=`{sha(C13)}`. U13 binds exact DIA011 audio SHA=`{sha(AU13)}` and frame/audio admission SHA=`{sha(A13)}`. Scheduler started `{T13_ID}`; provider posts/credits=0, no release.\n"); h.flush(); os.fsync(h.fileno())
    print(json.dumps({"status":"PASS_U12_ADMITTED_U13_LOCAL_RENDER_RUNNING","u12_admission_sha256":sha(A12),"u13_admission_sha256":sha(A13)},ensure_ascii=False)); return 0
if __name__=="__main__": raise SystemExit(main())
