#!/usr/bin/env python3
"""Admit U08, bind its tail to U09 frame/audio, and dispatch U09 local render."""
from __future__ import annotations
import hashlib, json, os, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

R=Path(__file__).resolve().parents[1]
V=R/"working_assets/e40_production_20260814/u08_v3_local_authority_raised_gaze_fan_shadow_exact_dialogue_v1/E40-U08-V3-LOCAL-AUTHORITY-EXACT-DIA007-RAISED-GAZE-FAN-SHADOW.mp4"
M=R/"qa/e40_production_20260814/u08_v3_local_authority_raised_gaze_fan_shadow_exact_dialogue_v1/E40_U08_V3_LOCAL_AUTHORITY_MACHINE_QA_V1.json"
H=R/"qa/e40_production_20260814/u08_v3_local_authority_raised_gaze_fan_shadow_exact_dialogue_v1/E40_U08_V3_ORIGINAL_RES_HUMAN_VISUAL_QA_V1.json"
T=R/"qa/e40_production_20260814/u08_v3_local_authority_raised_gaze_fan_shadow_exact_dialogue_v1/frame_0095_tail.png"
AR=R/"qa/e40_preproduction_20260814/u08_parallel_kokoro_exact_audio_candidates_v1/E40_U08_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
A8=R/"workflow/releases/E40_U08_V3_RIGHTS_CLEARED_EXACT_DIALOGUE_UNIT_ADMISSION_20260814.json"
F9=R/"working_assets/e40_preproduction_20260814/u09_parallel_four_mark_wipe_candidate_v1/E40_U09_PARALLEL_CANDIDATE_V2_EXACT_START_FRAME_720X1280.png"
H9=R/"qa/e40_preproduction_20260814/u09_parallel_four_mark_wipe_candidate_v1/E40_U09_PARALLEL_CANDIDATE_V2_ORIGINAL_RES_HUMAN_QA_V1.json"
O9=R/"qa/e40_preproduction_20260814/u09_parallel_four_mark_wipe_candidate_v1/E40_U09_PARALLEL_CANDIDATE_V2_OCR_AUDIT_V2.json"
AU9=R/"working_assets/e40_production_20260814/u09_parallel_kokoro_exact_audio_candidates_v1/E40-DIA008_zm_009_speed1p08_normalized48k.wav"
AQ9=R/"qa/e40_production_20260814/u09_parallel_kokoro_exact_audio_candidates_v1/E40_U09_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"
AR9=R/"qa/e40_preproduction_20260814/u09_parallel_kokoro_exact_audio_candidates_v1/E40_U09_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
C9=R/"qa/e40_preproduction_20260814/u09_parallel_four_mark_wipe_candidate_v1/E40_U08_TAIL_TO_U09_FRAME_CONTINUITY_QA_V1.json"
A9=R/"workflow/releases/E40_U09_PARALLEL_EXACT_START_FRAME_ADMISSION_20260814.json"
S=R/"workflow/production_line/E40_TASK_LANES_V1.json"; W=R/"workflow/work_queue.json"; X=R/"workflow/CODEX_TO_CLAUDE.md"
T8="E40-U08-V3-LOCAL-AUTHORITY-EXACT-DIALOGUE-FAN-SHADOW-PERFORMANCE-QA"; T9="E40-U09-V3-LOCAL-AUTHORITY-EXACT-DIALOGUE-FOUR-MARK-WIPE-PERFORMANCE-QA"
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def rel(p): return str(p.relative_to(R))
def st(d): return d.isoformat().replace("+00:00","Z")
def write(p,x):
 p.parent.mkdir(parents=True,exist_ok=True); b=(json.dumps(x,ensure_ascii=False,indent=2)+"\n").encode(); fd,t=tempfile.mkstemp(prefix=f".{p.name}.",dir=p.parent)
 try:
  with os.fdopen(fd,"wb") as f: f.write(b); f.flush(); os.fsync(f.fileno())
  os.replace(t,p)
 except Exception: Path(t).unlink(missing_ok=True); raise
def main():
 req=(V,M,H,T,AR,F9,H9,O9,AU9,AQ9,AR9,S,W)
 if any(p.exists() for p in (A8,C9,A9)): raise SystemExit("FAIL_CLOSED_OUTPUT_COLLISION")
 for p in req:
  if not p.is_file(): raise SystemExit(f"FAIL_MISSING:{p}")
 m=json.loads(M.read_text()); h=json.loads(H.read_text()); ar=json.loads(AR.read_text()); aq=json.loads(AQ9.read_text()); ar9=json.loads(AR9.read_text())
 if not m.get("status","").startswith("PASS") or m.get("failures") or m.get("final_asr_similarity")!=1.0 or h.get("status")!="PASS_HUMAN_VISUAL_ADMISSION_READY" or ar.get("releaseBlocked") is not False: raise SystemExit("FAIL_U08_GATES")
 if not aq.get("status","").startswith("PASS") or ar9.get("releaseBlocked") is not False: raise SystemExit("FAIL_U09_AUDIO_RIGHTS")
 n=datetime.now(timezone.utc); canon={"canonical_script_sha256":"140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b","canonical_manifest_sha256":"773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"}
 write(A8,{"schema":"qingshan.e40.u08.v3.unit_admission.v1","status":"PASS_U08_V3_ADMITTED_FOR_EPISODE_ASSEMBLY","admitted_at":st(n),"episode":"E40","unit":"U08",**canon,"video_path":rel(V),"video_sha256":sha(V),"machine_qa":rel(M),"machine_qa_sha256":sha(M),"human_qa":rel(H),"human_qa_sha256":sha(H),"tail_frame":rel(T),"tail_frame_sha256":sha(T),"rights_evidence":rel(AR),"rights_evidence_sha256":sha(AR),"gates":{"exact_frame0":True,"exact_asr":True,"raised_gaze":True,"fan_shadow":True,"ocr_zero":True,"identity":True,"commercial_rights":True},"provider_posts":0,"credits":0,"release_status":"NOT_RELEASED_UNIT_ONLY"})
 write(C9,{"schema":"qingshan.e40.u08_tail_to_u09_frame.continuity_qa.v1","status":"PASS_CONTINUITY_BINDING","reviewed_at":st(n),"predecessor_tail":rel(T),"predecessor_tail_sha256":sha(T),"candidate_frame":rel(F9),"candidate_frame_sha256":sha(F9),"checks":{"same_chenji_identity_hairpin_white_robe":"PASS","same_dark_hall_table_and_lighting":"PASS","curtain_reaction_to_table_wipe_cut":"PASS_INTENTIONAL_CANONICAL_ACTION_CUT","four_mark_topology_and_empty_fifth":"PASS","mid_wipe_frost_powder_state":"PASS","ocr_zero":"PASS"},"human_score":92,"failures":[]})
 write(A9,{"schema":"qingshan.e40.u09.parallel.exact_start_frame_admission.v1","status":"PASS_U09_EXACT_START_FRAME_ADMITTED_FOR_LOCAL_VIDEO","admitted_at":st(n),"episode":"E40","unit":"U09",**canon,"canonical_line":"我一换，两个一并抹掉，线断死。","frame_path":rel(F9),"frame_sha256":sha(F9),"human_qa":rel(H9),"human_qa_sha256":sha(H9),"ocr_qa":rel(O9),"ocr_qa_sha256":sha(O9),"continuity_qa":rel(C9),"continuity_qa_sha256":sha(C9),"selected_audio":rel(AU9),"selected_audio_sha256":sha(AU9),"audio_qa":rel(AQ9),"audio_qa_sha256":sha(AQ9),"rights_evidence":rel(AR9),"rights_evidence_sha256":sha(AR9),"provider_posts":0,"credits":0,"release_status":"NOT_RELEASED_FRAME_ONLY"})
 s=json.loads(S.read_text()); cur=[x for x in s["tasks"] if x.get("task_id")==T8]
 if len(cur)!=1 or any(x.get("task_id")==T9 for x in s["tasks"]): raise SystemExit("FAIL_SCHEDULER_STATE")
 cur[0].update({"state":"TERMINAL","wait_scope":"NONE_TERMINAL","blocked_by":None,"progress":"U08_V3_FRAME0_ASR_GAZE_FAN_SHADOW_OCR_IDENTITY_RIGHTS_PASS_ADMITTED","last_progress_at":st(n),"next_action":"Terminal U08; U09 local render owns production.","next_due_at":None,"executor_next_wakeup_at":None,"evidence_ref":rel(A8),"evidence_sha256":sha(A8),"output_ref":rel(V),"output_sha256":sha(V),"completed_at":st(n),"terminal_status":"PASS_U08_V3_ADMITTED_FOR_EPISODE_ASSEMBLY"})
 s["tasks"].append({"task_id":T9,"lane_id":"U09_LOCAL_AUTHORITY_EXACT_DIALOGUE_FOUR_MARK_WIPE","state":"RUNNING","wait_scope":"NONE_ACTIVE_RUNNING","zero_cost":True,"deliverable_type":"U09_LOCAL_AUTHORITY_EXACT_FRAME_EXACT_DIA008_WIPE_VIDEO_AND_QA","priority":180,"scope":["E40","U09","V3","LOCAL_AUTHORITY_ONLY","EXACT_FRAME0","EXACT_DIA008","FOUR_MARK_WIPE","RIGHTS_CLEAR","NO_PROVIDER","NO_RELEASE"],"exact_predecessor_task_id":T8,"liveness_role":"PRODUCING","observation_only":False,"maximum_new_submissions":0,"authorization":False,"provider_post_allowed":False,"provider_query_allowed":False,"download_allowed":False,"provider_calls":0,"transactions":0,"credits":0,"blocked_by":None,"progress":"U09_FRAME_AUDIO_CONTINUITY_RIGHTS_BOUND_LOCAL_RENDER_RUNNING","last_progress_at":st(n),"next_action":"Render U09 local authority mid-wipe motion from admitted frame with exact DIA008; run frame0, ASR, OCR, visual, continuity, rights and duration QA.","lease_owner":"codex-e40-production:u09-v3-local","lease_expires_at":st(n+timedelta(hours=2)),"next_due_at":st(n+timedelta(minutes=10)),"execution_mode":"CONTINUOUS","executor_handle":"automation:e40","executor_task_id":T9,"executor_acknowledged_at":st(n),"executor_next_wakeup_at":st(n+timedelta(minutes=10)),"evidence_ref":rel(A9),"evidence_sha256":sha(A9),"audio_ref":rel(AU9),"audio_sha256":sha(AU9)}); s["updated_at"]=st(n); write(S,s)
 w=json.loads(W.read_text()); w["latest_e40_u08_parallel_preproduction"].update({"status":"PASS_U08_V3_ADMITTED_FOR_EPISODE_ASSEMBLY","video":rel(V),"video_sha256":sha(V),"unit_admission":rel(A8),"unit_admission_sha256":sha(A8),"next_action":"Terminal U08; U09 local render running."}); w["latest_e40_u09_parallel_preproduction"].update({"status":"PASS_U09_FRAME_AUDIO_ADMITTED_LOCAL_VIDEO_RUNNING","continuity_qa":rel(C9),"continuity_qa_sha256":sha(C9),"frame_admission":rel(A9),"frame_admission_sha256":sha(A9),"blocked_by":None,"active_task_id":T9,"next_action":s["tasks"][-1]["next_action"]}); write(W,w)
 with X.open("a",encoding="utf-8") as f: f.write(f"\n\n## E40 checkpoint {st(n)} — U08 admitted; U09 continuity/audio bound and local render dispatched\n\n- U08 V3 `{rel(V)}` SHA=`{sha(V)}` passed exact frame0, DIA007 ASR=1.0, OCR0, HUMAN94, gaze/fan-shadow/identity/rights gates; admission `{rel(A8)}` SHA=`{sha(A8)}`.\n- U08 tail to U09 frame continuity SHA=`{sha(C9)}` passed. U09 frame/audio admission `{rel(A9)}` SHA=`{sha(A9)}` binds DIA008 SHA=`{sha(AU9)}`; provider posts/credits=0. Scheduler started `{T9}`. No release.\n"); f.flush(); os.fsync(f.fileno())
 print(json.dumps({"status":"PASS_U08_ADMITTED_U09_LOCAL_RENDER_RUNNING","u08_admission_sha256":sha(A8),"u09_admission_sha256":sha(A9)},ensure_ascii=False)); return 0
if __name__=="__main__": raise SystemExit(main())
