#!/usr/bin/env python3
"""Atomically register submitted E40 U02 V3 and sync work_queue."""
from __future__ import annotations
import hashlib, json, os, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEDULER = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"
NOW = "2026-08-14T05:55:00Z"
EXPECTED = "e89dcfc0b14ce56bb171325e0fc39f373619db32a6d25000729defec9ef4bcf3"
PACKAGE = "E40-U02-V3-LOW-HEM-SCENE-AUTHORITY-REMEDIATION-PACKAGE-QA"
REMOTE = "E40-U02-V3-LOW-HEM-SCENE-AUTHORITY-REMOTE-RETRY1"
PROVIDER = "52180a09-d3ef-47d0-afc1-44d30147c8a2"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def atomic_json(path: Path, value: object) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(value, out, ensure_ascii=False, indent=2); out.write("\n"); out.flush(); os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

def main() -> None:
    if sha(SCHEDULER) != EXPECTED: raise SystemExit(f"scheduler CAS mismatch: {sha(SCHEDULER)}")
    scheduler = json.loads(SCHEDULER.read_text(encoding="utf-8"))
    matches = [t for t in scheduler["tasks"] if t.get("task_id") == PACKAGE]
    if len(matches) != 1 or matches[0].get("state") != "QA": raise SystemExit("V3 package task is not uniquely active QA")
    if any(t.get("task_id") == REMOTE for t in scheduler["tasks"]): raise SystemExit("V3 remote successor already exists")
    matches[0].update({
        "state":"TERMINAL","wait_scope":"NONE_TERMINAL",
        "progress":"PASS_UNIQUE_MANIFEST_STATIC_NEGATIVE_6_OF_6_TWO_INSTALLED_PRECHECKS_AND_PAID_RETRY_GO_GATE",
        "last_progress_at":NOW,"next_due_at":None,"executor_next_wakeup_at":None,
        "evidence_ref":"qa/e40_preproduction_20260814/u02_v3_low_hem_authority_package_qa_v1/E40_U02_V3_PAID_RETRY_INSTALLED_PRECHECK_V1.json",
        "evidence_sha256":"433b46a9667123130294d8623b1c45555763797c9eb72ca248bd15083662494b",
        "completed_at":NOW,"terminal_status":"PASS_V3_RETRY_PACKAGE_AND_EXECUTION_GATES",
        "terminal_outcome":"PASS_V3_RETRY_PACKAGE_AND_EXECUTION_GATES",
        "next_action":"Terminal package QA; task-local remote successor owns the one submitted V3 task and forbids replay."})
    scheduler["tasks"].append({
        "task_id":REMOTE,"provider_task_id":PROVIDER,"lane_id":"ASSET_ACQUISITION_REMOTE","state":"REMOTE_WAIT","wait_scope":"TASK_LOCAL",
        "zero_cost":False,"deliverable_type":"U02_V3_LOW_HEM_AUTHORITY_EXACT_START_FRAME","priority":164,
        "scope":["E40","U02","V3","PF-032","EXACTLY_ONE_RETRY","IMAGE_GENERATION","TASK_LOCAL_REMOTE_WAIT"],
        "exact_predecessor_task_id":PACKAGE,"liveness_role":"PRODUCING","observation_only":False,
        "maximum_new_submissions":0,"authorization":True,"authorization_consumed":True,"provider_post_allowed":False,
        "provider_query_allowed":True,"download_allowed":True,"provider_calls":1,"provider_posts_consumed":1,
        "transactions":1,"credits":5,"pay":5,"refund":0,"net":5,
        "blocked_by":"REMOTE_GENERATION_NOT_YET_HARVESTED_OR_QA_ADMITTED",
        "progress":"SUBMITTED_TASK_ID_BOUND_PAY5_CLASSIFIED_REMOTE_WAIT_NO_REPLAY","last_progress_at":NOW,
        "next_action":"At next bounded checkpoint, query only this task id, download at most once on terminal success, classify credit/refund, and run original-resolution QA before video use. Never resubmit.",
        "lease_owner":"codex-e40-production:u02-v3-remote-retry1","lease_expires_at":"2026-08-14T07:55:00Z",
        "next_due_at":"2026-08-14T06:05:00Z","execution_mode":"CONTINUOUS","executor_handle":"automation:e40",
        "executor_task_id":REMOTE,"executor_acknowledged_at":NOW,"executor_next_wakeup_at":"2026-08-14T06:05:00Z",
        "evidence_ref":"workflow/tasks/E40_U02_V3_LOW_HEM_AUTHORITY_IMAGE_SUBMIT_20260814.json",
        "evidence_sha256":"48eae0cb4cc11cd65b92528e5114158b56676d4e25b0f6426ea3ff6a0ff573d9",
        "transaction_ref":"workflow/tasks/giggle_submit_transactions/E40/E40-U02-EXACT-START-FRAME-V3-LOW-HEM-AUTHORITY-RETRY1__01f0d1789be556c1.json",
        "transaction_sha256":"b778cfcbaa6f2f9098d718096d5fa43752f3767eee1f646ab02f2980abf47215",
        "submission_receipt_ref":"workflow/tasks/E40_U02_V3_LOW_HEM_AUTHORITY_IMAGE_SUBMIT_20260814_receipts/E40-U02-EXACT-START-FRAME-V3-LOW-HEM-AUTHORITY-RETRY1_submit_receipt.json",
        "submission_receipt_sha256":"0535c79cf57c7cb4154d02b978649bd0becfa1e7efb26509c3d9ce6843df8e4d"})
    scheduler["updated_at"] = NOW
    atomic_json(SCHEDULER, scheduler); scheduler_sha = sha(SCHEDULER)

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue.update({"updated_at":NOW,"mode":"E40_CONTINUOUS_EPISODE_PRODUCTION_U29_ASSEMBLED_U02_V3_REMOTE_GENERATION_ACTIVE",
        "status":"E40_U29_V77_ASSEMBLY_PASS_U02_V3_SUBMITTED_TASK_ID_BOUND_PAY5_REMOTE_WAIT",
        "updated_note_latest":"U02 V3 passed unique-manifest, static, six negative, installed and paid retry gates. Exactly one changed-input task was submitted; task id 52180a09-d3ef-47d0-afc1-44d30147c8a2 is bound, Pay 5 is authoritatively classified, and replay is forbidden. TASK_LOCAL REMOTE_WAIT is active for bounded harvest and original-resolution QA.",
        "next_action":"Bounded exact-task harvest for U02 V3 task 52180a09-d3ef-47d0-afc1-44d30147c8a2; download at most once on terminal success, classify refund/pay, then original-resolution hard-gate QA before video generation."})
    queue["e40_credits"].update({"gross_pay":1447,"net":1319,"remaining":8681,"active_remote_image_pay":5,"image_pay":389,
        "status":"AUTHORITATIVE_TOTALS_1447_128_1319_U02_V3_RETRY1_PAY5_BOUND_REMOTE_PLUS_U18_V5_TWO_TASK_CLASSIFICATION_PENDING",
        "totals_fresh_through":"U02_V3_RETRY1_SUBMITTED_TASK_ID_BOUND_PAY5_RECONCILED","active_remote_image_task_id":PROVIDER,
        "pending_remote_image_task_count":3,"pending_remote_image_task_ids":["17939df6-4f2c-4148-91c3-38f26870b6dc","bac46b24-b9a2-4a17-ab48-c2327b82b67a",PROVIDER],"pending_remote_image_credit_amount":5})
    queue["latest_e40_u02_v3_low_hem_authority_remediation"].update({
        "package_manifest":"workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u02_v3_low_hem_scene_authority_remediation_v1/E40_U02_V3_LOW_HEM_AUTHORITY_IMAGE_MANIFEST_V1.json","package_manifest_sha256":"c7f992d3726eadba07b90829be9a1356e512825b1e01cd778c52ca2eece821b8",
        "execution_manifest":"workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u02_v3_low_hem_scene_authority_remediation_v1/E40_U02_V3_LOW_HEM_AUTHORITY_PAID_RETRY_MANIFEST_V1.json","execution_manifest_sha256":"018248698bd364f2ffb7a88e2b5bac4b9fdc40a0f79d824f6def4777deb6e049",
        "static_negative_gate":"qa/e40_preproduction_20260814/u02_v3_low_hem_authority_package_qa_v1/E40_U02_V3_STATIC_AND_NEGATIVE_GATE_V1.json","static_negative_gate_sha256":"59201f9613c133a9e1683fa3927dfb3384d0b71fef0027939cfa18abff92ce56",
        "installed_precheck":"qa/e40_preproduction_20260814/u02_v3_low_hem_authority_package_qa_v1/E40_U02_V3_PAID_RETRY_INSTALLED_PRECHECK_V1.json","installed_precheck_sha256":"433b46a9667123130294d8623b1c45555763797c9eb72ca248bd15083662494b",
        "provider_task_id":PROVIDER,"transaction":"workflow/tasks/giggle_submit_transactions/E40/E40-U02-EXACT-START-FRAME-V3-LOW-HEM-AUTHORITY-RETRY1__01f0d1789be556c1.json","transaction_sha256":"b778cfcbaa6f2f9098d718096d5fa43752f3767eee1f646ab02f2980abf47215",
        "submit_report":"workflow/tasks/E40_U02_V3_LOW_HEM_AUTHORITY_IMAGE_SUBMIT_20260814.json","submit_report_sha256":"48eae0cb4cc11cd65b92528e5114158b56676d4e25b0f6426ea3ff6a0ff573d9",
        "provider_calls":1,"transactions":1,"credits":5,"pay":5,"refund":0,"net":5,"status":"SUBMITTED_TASK_ID_BOUND_PAY5_CLASSIFIED_TASK_LOCAL_REMOTE_WAIT_NO_REPLAY"})
    queue["task_lane_scheduler"].update({"observed_sha256":scheduler_sha,"status":"DYNAMIC_SNAPSHOT_U29_V77_ASSEMBLED_U02_V3_TASK_LOCAL_REMOTE_WAIT_U18_TASK_LOCAL_REMOTE_WAIT","episode_terminal":False,"stale_leases_detected":False})
    atomic_json(QUEUE, queue)
    print(json.dumps({"status":"PASS","scheduler_sha256":scheduler_sha,"work_queue_sha256":sha(QUEUE),"provider_task_id":PROVIDER}))

if __name__ == "__main__": main()
