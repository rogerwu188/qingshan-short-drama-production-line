#!/usr/bin/env python3
from __future__ import annotations
import argparse,copy,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; SCHEDULER=ROOT/"workflow/production_line/E40_TASK_LANES_V1.json"; sys.path.insert(0,"/Users/rogerwu/.local/share/backlotos/share/pipeline-tools")
from task_lane_state_store import commit_task_updates,read_scheduler_snapshot  # noqa: E402
PREVIOUS="E40-U29C-V65-RIGID-HEAD-ROTATION-AND-PARITY-QA"; CURRENT="E40-V67-NEXT-GENERATABLE-UNIT-DEPENDENCY-AUDIT"
def iso(v): return v.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
def main():
 p=argparse.ArgumentParser(); p.add_argument("--final-qa-ref",required=True); p.add_argument("--final-qa-sha256",required=True); a=p.parse_args(); now=datetime.now(timezone.utc); snap=read_scheduler_snapshot(SCHEDULER); ts={t["task_id"]:copy.deepcopy(t) for t in snap.payload["tasks"]}; prev=ts[PREVIOUS]
 if prev.get("state")!="RUNNING" or prev.get("maximum_new_submissions")!=0: raise SystemExit("V65 not expected active")
 prev.update({"state":"TERMINAL","wait_scope":"NONE_TERMINAL","next_due_at":None,"completed_at":iso(now),"terminal_status":"PASS_EXACT_SHA_AGENTCUT_ISOLATED_SOURCE_ADMISSION_NO_ASSEMBLY","progress":"PASS_V65_V66_FRAME0_CADENCE_OCR_BODY_ANCHOR_AND_HUMAN_80_OF_80","evidence_ref":a.final_qa_ref,"evidence_sha256":a.final_qa_sha256})
 for k in ("execution_mode","executor_handle","executor_task_id","executor_acknowledged_at","executor_next_wakeup_at"): prev.pop(k,None)
 cur={"task_id":CURRENT,"lane_id":"NEXT_UNIT_READINESS_QA","state":"QA","zero_cost":True,"deliverable_type":"NEXT_GENERATABLE_UNIT_DEPENDENCY_AUDIT","priority":150,"scope":["E40","V67","LOCAL_ONLY","CANONICAL_MANIFEST","DEPENDENCY_GRAPH","NO_ASSEMBLY","NO_PROVIDER","NO_SUBMIT","NO_TRANSACTION","NO_CREDITS"],"exact_predecessor_task_id":PREVIOUS,"liveness_role":"PRODUCING","observation_only":False,"maximum_new_submissions":0,"authorization":False,"provider_post_allowed":False,"provider_query_allowed":False,"download_allowed":False,"provider_calls":0,"transactions":0,"credits":0,"wait_scope":"NONE_ACTIVE_QA","blocked_by":None,"progress":"REGISTERED_AFTER_U29C_EXACT_SHA_ADMISSION","last_progress_at":iso(now),"next_action":"Bind exact V66 QA into the dependency inventory and select the next safe generatable E40 unit without assembling, uploading, publishing, polling or touching E38/E39.","lease_owner":"codex-e40-next-unit-audit:v67","lease_expires_at":iso(now+timedelta(hours=2)),"next_due_at":iso(now+timedelta(minutes=20)),"execution_mode":"CONTINUOUS","executor_handle":"agent:/root/e40_next_unit_audit","executor_task_id":CURRENT,"executor_acknowledged_at":iso(now),"executor_next_wakeup_at":iso(now+timedelta(minutes=10)),"evidence_ref":a.final_qa_ref,"evidence_sha256":a.final_qa_sha256}
 print(commit_task_updates(SCHEDULER,base_snapshot=snap,task_updates={PREVIOUS:prev,CURRENT:cur},writer_id="codex-e40-next-unit-audit:u29c-v65-v67")); return 0
if __name__=="__main__": raise SystemExit(main())
