#!/usr/bin/env python3
from __future__ import annotations
import argparse,copy,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; SCHEDULER=ROOT/"workflow/production_line/E40_TASK_LANES_V1.json"; sys.path.insert(0,"/Users/rogerwu/.local/share/backlotos/share/pipeline-tools")
from task_lane_state_store import commit_task_updates,read_scheduler_snapshot  # noqa: E402
PREVIOUS="E40-U29C-V63-THRESHOLD-CROSSING-SOURCE-REDESIGN"; CURRENT="E40-U29C-V65-RIGID-HEAD-ROTATION-AND-PARITY-QA"
def iso(v): return v.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
def main():
 p=argparse.ArgumentParser(); p.add_argument("--failure-memory-ref",required=True); p.add_argument("--failure-memory-sha256",required=True); p.add_argument("--spec-ref",required=True); p.add_argument("--spec-sha256",required=True); a=p.parse_args(); now=datetime.now(timezone.utc); snap=read_scheduler_snapshot(SCHEDULER); ts={t["task_id"]:copy.deepcopy(t) for t in snap.payload["tasks"]}; prev=ts[PREVIOUS]
 if prev.get("state")!="RUNNING" or prev.get("maximum_new_submissions")!=0: raise SystemExit("V63 not expected active")
 prev.update({"state":"TERMINAL","wait_scope":"NONE_TERMINAL","next_due_at":None,"completed_at":iso(now),"terminal_status":"FAIL_V64_SINGLE_0P708_CADENCE_WINDOW_REPRESENTATION_CHANGE_REQUIRED","progress":"FAIL_SHEAR_NEAR_THRESHOLD_RIGID_ROTATION_REQUIRED","evidence_ref":a.failure_memory_ref,"evidence_sha256":a.failure_memory_sha256})
 for k in ("execution_mode","executor_handle","executor_task_id","executor_acknowledged_at","executor_next_wakeup_at"): prev.pop(k,None)
 cur={"task_id":CURRENT,"lane_id":"U29_VIDEO_QA","state":"RUNNING","zero_cost":True,"deliverable_type":"LOCAL_RIGID_HEAD_ROTATION_AND_AGENTCUT_PARITY_QA","priority":149,"scope":["E40","U29C","V65","LOCAL_ONLY","RIGID_ROTATION","MATERIAL_CHANGE","NO_ASSEMBLY","NO_PROVIDER","NO_SUBMIT","NO_TRANSACTION","NO_CREDITS"],"exact_predecessor_task_id":PREVIOUS,"liveness_role":"PRODUCING","observation_only":False,"maximum_new_submissions":0,"authorization":False,"provider_post_allowed":False,"provider_query_allowed":False,"download_allowed":False,"provider_calls":0,"transactions":0,"credits":0,"wait_scope":"NONE_ACTIVE_RUNNING","blocked_by":None,"progress":"REGISTERED_RIGID_ROTATION_AFTER_V64_FAILURE_MEMORY","last_progress_at":iso(now),"next_action":"Render rigid head rotations with early counterturns; inspect seams/plausibility; run isolated AgentCut exact-frame0 cadence OCR QA.","lease_owner":"codex-e40-next-unit-audit:u29c-v65","lease_expires_at":iso(now+timedelta(hours=2)),"next_due_at":iso(now+timedelta(minutes=20)),"execution_mode":"CONTINUOUS","executor_handle":"agent:/root/e40_next_unit_audit","executor_task_id":CURRENT,"executor_acknowledged_at":iso(now),"executor_next_wakeup_at":iso(now+timedelta(minutes=10)),"evidence_ref":a.spec_ref,"evidence_sha256":a.spec_sha256}
 print(commit_task_updates(SCHEDULER,base_snapshot=snap,task_updates={PREVIOUS:prev,CURRENT:cur},writer_id="codex-e40-next-unit-audit:u29c-v63-v65")); return 0
if __name__=="__main__": raise SystemExit(main())
