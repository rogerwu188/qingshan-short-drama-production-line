#!/usr/bin/env python3
"""Pinned V44 regression over V43 closed-keyset/cross-field authority."""
from __future__ import annotations

import argparse, hashlib, importlib.util, json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as base

AUDITOR = ROOT / "tools/audit_e40_u29c_v43_projection_keyset_crossfield_integrity.py"
AUDITOR_SHA = "f34a587dec39d5d8e08f8430a61d40b1c8074000f02e773f076ff65d3e52f530"
AUDIT = ROOT / "qa/e40_preproduction_20260808/u29c_v43_projection_keyset_crossfield_integrity_v1/E40_U29C_V43_PROJECTION_KEYSET_CROSSFIELD_INTEGRITY_AUDIT_V1.json"
AUDIT_SHA = "d07461ee37047d986514824d1f55d04163257ac35c1040e8a1763cfbd3f70232"
MEMORY = ROOT / "workflow/prompt_memory/E40_U29C_V41_QA_FALSE_NEGATIVE_MEMORY_V1.md"
MEMORY_SHA = "ac9e7b03d1362d185d17b7ab436306fd5ceb407a0b0f88be495c52a2462da00f"
SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v44_pinned_projection_keyset_crossfield_regression_v1/E40_U29C_V44_PINNED_PROJECTION_KEYSET_CROSSFIELD_REGRESSION_SPEC_V1.json"
SPEC_SHA = "364e27fcbef93f1f4f356aa9086559627f7d48fb241e328b777b576402aab729"
CANON = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
CANON_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
MANIFEST_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"
SCHED = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
REPORT = SPEC.parent / "E40_U29C_V44_PINNED_PROJECTION_KEYSET_CROSSFIELD_REGRESSION_MATRIX_V1.json"
PASS = "PASS_PINNED_V43_EXACT_15_KEY_CROSSFIELD_16_OF_16_MEMORY_PRESERVED_NO_MUTATION_NO_SUBMIT"


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def ident(path):
    s=os.lstat(path); return {"path":str(path.relative_to(ROOT)),"sha256":sha(path),"device":s.st_dev,"inode":s.st_ino,"mode":oct(s.st_mode&0o7777),"nlink":s.st_nlink,"uid":s.st_uid,"gid":s.st_gid,"size":s.st_size,"mtime_ns":s.st_mtime_ns,"ctime_ns":s.st_ctime_ns}
def load_module():
    spec=importlib.util.spec_from_file_location("v43_fixed",AUDITOR)
    if spec is None or spec.loader is None: raise RuntimeError("V43_IMPORT_UNAVAILABLE")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
def negs():
    out=[]
    for flag in ("--auditor","--audit","--memory","--spec","--scheduler","--canonical","--canonical-manifest"):
        p=subprocess.run([sys.executable,str(Path(__file__).resolve()),flag,"/tmp/forbidden-substitution"],cwd=ROOT,text=True,capture_output=True,check=False)
        out.append({"argument":flag,"exit_code":p.returncode,"rejected_before_regression":p.returncode==2,"report_created":REPORT.exists()})
    return out


def main():
    argparse.ArgumentParser(description="Fixed V44 pinned keyset regression; substitutions forbidden.",allow_abbrev=False).parse_args()
    if REPORT.exists(): raise SystemExit("REPORT_ALREADY_EXISTS")
    pins=[(AUDITOR,AUDITOR_SHA),(AUDIT,AUDIT_SHA),(MEMORY,MEMORY_SHA),(SPEC,SPEC_SHA),(CANON,CANON_SHA),(MANIFEST,MANIFEST_SHA)]
    before=[ident(p) for p,_ in pins]; matches=[row["sha256"]==expected for row,(_,expected) in zip(before,pins)]
    if not all(matches): print(json.dumps({"status":"FAIL_CLOSED_PIN_MISMATCH","pin_matches":matches}));return 1
    fail=[]; negatives=negs()
    if REPORT.exists() or not all(x["rejected_before_regression"] and not x["report_created"] for x in negatives): fail.append("SUBSTITUTION_NOT_REJECTED")
    v43=load_module(); authority=json.loads(AUDIT.read_text())
    authority_ok=authority.get("status")==v43.PASS and authority.get("failures")==[] and authority.get("projection_task_count")==16 and authority.get("exact_closed_15_keyset_count")==16 and authority.get("terminal_crossfield_count")==16 and authority.get("evidence_crossfield_count")==16 and authority.get("predecessor_topology_count")==16 and authority.get("zero_authority_count")==16
    memory_ok="status syntax is exactly `^PASS_[A-Z0-9_]+$`" in MEMORY.read_text()
    if not authority_ok: fail.append("V43_AUTHORITY_NOT_EXACT")
    if not memory_ok: fail.append("V41_MEMORY_NOT_EXACT")
    sched=json.loads(SCHED.read_text()); tm={t["task_id"]:t for t in sched["tasks"]}; expected=authority.get("projection_after") or []; projection_before=[]; rows=[]
    exact_keys=set(load_module().load_v41().FIELDS)
    for i,e in enumerate(expected):
        t=tm.get(e.get("task_id")); proj=load_module().load_v41().project(t); projection_before.append(proj); pred="E40-U29C-V22-RECOVERED-SUCCESS-RECEIPT-AND-CRASH-BOUNDARY-AUDIT-NO-SUBMIT" if i==0 else expected[i-1]["task_id"]
        keyset=proj is not None and set(proj)==exact_keys and len(proj)==15 and all(v is not None for v in proj.values()); terminal=bool(t and t["state"]=="TERMINAL" and load_module().load_v41().parse_utc(t["completed_at"]) and load_module().load_v41().STATUS_RE.fullmatch(t["terminal_status"])); evidence=bool(t and load_module().load_v41().canonical_repo_json_path(t["evidence_ref"]) and sha(ROOT/t["evidence_ref"])==t["evidence_sha256"]); topology=bool(t and t["exact_predecessor_task_id"]==pred); zero=bool(t and t["zero_cost"] is True and t["maximum_new_submissions"]==0 and t["authorization"] is False and t["provider_post_allowed"] is False and t["provider_calls"]==t["transactions"]==t["credits"]==0); exact=proj==e; passed=all((keyset,terminal,evidence,topology,zero,exact));rows.append({"ordinal":i+23,"task_id":e.get("task_id"),"exact_closed_15_key_no_null":keyset,"terminal_crossfield":terminal,"evidence_crossfield":evidence,"predecessor_topology":topology,"zero_authority":zero,"v43_snapshot_exact":exact,"passed":passed,"projection":proj})
    if len(rows)!=16 or not all(x["passed"] for x in rows): fail.append("PINNED_CROSSFIELD_NOT_16_OF_16")
    canonical=sched.get("canonical_script_sha256")==CANON_SHA and sched.get("canonical_manifest_sha256")==MANIFEST_SHA
    if not canonical: fail.append("CANONICAL_NOT_EXACT")
    current=json.loads(SCHED.read_text()); am={t["task_id"]:t for t in current["tasks"]}; v41=load_module().load_v41(); projection_after=[v41.project(am.get(e.get("task_id"))) for e in expected]; after=[ident(p) for p,_ in pins]
    if projection_before!=projection_after: fail.append("PROJECTION_MUTATION")
    if before!=after: fail.append("PIN_MUTATION")
    status=PASS if not fail else "FAIL"; payload={"schema":"qingshan.e40.u29c.v44.pinned_projection_keyset_crossfield_regression_matrix.v1","episode":"E40","unit_id":"U29C","recorded_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"status":status,"execution_permitted":False,"provider_post_allowed":False,"maximum_new_submissions":0,"pins_before":before,"pin_expected_sha256":[e for _,e in pins],"pin_match_count":sum(matches),"pins_after":after,"v43_authority_valid":authority_ok,"v41_failure_memory_exact":memory_ok,"canonical_binding_exact":canonical,"projection_task_count":len(rows),"exact_closed_15_keyset_count":sum(x["exact_closed_15_key_no_null"] for x in rows),"terminal_crossfield_count":sum(x["terminal_crossfield"] for x in rows),"evidence_crossfield_count":sum(x["evidence_crossfield"] for x in rows),"predecessor_topology_count":sum(x["predecessor_topology"] for x in rows),"zero_authority_count":sum(x["zero_authority"] for x in rows),"v43_snapshot_exact_count":sum(x["v43_snapshot_exact"] for x in rows),"projection_rows":rows,"projection_before":projection_before,"projection_after":projection_after,"no_authority_elevation":True,"substitution_negatives":negatives,"substitution_negative_count":sum(x["rejected_before_regression"] for x in negatives),"blind_replay_allowed":False,"failures":fail,"side_effects":{"provider_calls":0,"transactions":0,"credits":0,"retries":0,"agentcut":0,"assembly":0},"next_action":"Register V45 projection evidence basename/schema correlation audit."}
    fd=os.open(REPORT,base.create_flags(),0o600);base.write_all(fd,(json.dumps(payload,indent=2)+"\n").encode());os.fsync(fd);os.close(fd);print(json.dumps({"status":status,"pins":sum(matches),"projection":len(rows),"keysets":payload["exact_closed_15_keyset_count"],"terminal":payload["terminal_crossfield_count"],"evidence":payload["evidence_crossfield_count"],"topology":payload["predecessor_topology_count"],"zero":payload["zero_authority_count"],"substitutions":payload["substitution_negative_count"],"failures":fail}));return 0 if not fail else 1
if __name__=="__main__": raise SystemExit(main())
