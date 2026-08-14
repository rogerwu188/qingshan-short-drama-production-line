#!/usr/bin/env python3
"""Bounded V23 persisted-receipt, restart, crash and competitor matrix."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as base  # noqa: E402
import run_e40_u29c_v20_post_link_recovery_publish_gate as recovery  # noqa: E402
import run_e40_u29c_v23_persisted_recovery_receipt_gate as writer  # noqa: E402


WRITER = ROOT / "tools/run_e40_u29c_v23_persisted_recovery_receipt_gate.py"
WRITER_SHA256 = "3f5af7ba788f1b62015da87826033ca5ba77995da9537d2b2bdca7044403f175"
V22_AUDIT = ROOT / "qa/e40_preproduction_20260808/u29c_v22_recovery_receipt_crash_boundary_audit_v1/E40_U29C_V22_RECOVERED_SUCCESS_RECEIPT_AND_CRASH_BOUNDARY_AUDIT_V1.json"
V22_AUDIT_SHA256 = "09943bbd534f3f69567f98609bbb2a86ca7740062c8e5b036e2321c46725ed85"
V23_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v23_persisted_recovery_receipt_writer_v1/E40_U29C_V23_PERSISTED_OWNED_INODE_RECOVERY_RECEIPT_WRITER_SPEC_V1.json"
V23_SPEC_SHA256 = "0b23cb7fa1ec9e8a9963472e14dcdca0fc31d953957a08b838302cce5fd7c7a0"
REPORT = ROOT / "qa/e40_preproduction_20260808/u29c_v23_persisted_recovery_receipt_writer_v1/E40_U29C_V23_PERSISTED_RECOVERY_RECEIPT_BOUNDED_MATRIX_V1.json"
NORMAL_NAME = "E40_U29C_V23_NORMAL_NO_RECEIPT_GATE_V3.json"
RECOVERED_NAME = "E40_U29C_V23_RECOVERED_WITH_RECEIPT_GATE_V3.json"
COMPETITOR_NAME = "E40_U29C_V23_COMPETITOR_PRESERVED_GATE_V3.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def receipt_hidden() -> list[str]:
    return sorted(path.name for path in writer.RECEIPT_ROOT.iterdir() if path.name.startswith(".u29c-v23-receipt-hidden-"))


def data_hidden() -> list[str]:
    return sorted(path.name for path in recovery.FINAL_ROOT.iterdir() if path.name.startswith(".u29c-v20-hidden-"))


def normal_case() -> dict[str, Any]:
    result = writer.execute(NORMAL_NAME)
    output = Path(str(result["output"]))
    return {"case_id":"NORMAL_PATH_REQUIRES_NO_RECOVERY_RECEIPT","passed":result["post_link_recovered"] is False and result["receipt_required"] is False and result["receipt"] is None and output.is_file(),"output_sha256":digest(output)}


def recovered_case() -> tuple[dict[str, Any], dict[str, Any]]:
    output = recovery.FINAL_ROOT / RECOVERED_NAME
    original = recovery.os.fsync
    fired = False
    final_token = base.identity(os.stat(recovery.FINAL_ROOT, follow_symlinks=False))
    def inject(fd: int) -> None:
        nonlocal fired
        if output.exists() and not fired:
            try: token = base.identity(os.fstat(fd))
            except OSError: token = (-1, -1)
            if token == final_token:
                fired = True
                raise OSError("V23_POST_LINK_FSYNC_INTERRUPT")
        original(fd)
    recovery.os.fsync = inject
    try: result = writer.execute(RECOVERED_NAME)
    finally: recovery.os.fsync = original
    receipt = Path(str(result["receipt"])); record=writer.validate_restart(receipt); value=os.stat(output,follow_symlinks=False)
    required=["output","output_sha256","owned_inode_token","recovery_cause","validator_status","writer_sha256","output_link_count"]
    case={"case_id":"RECOVERED_SUCCESS_PERSISTS_EXACT_OWNED_INODE_RECEIPT","passed":fired and result["post_link_recovered"] is True and result["receipt_required"] is True and receipt.is_file() and all(k in record for k in required) and record["owned_inode_token"]==[value.st_dev,value.st_ino] and record["output_sha256"]==digest(output) and result["receipt_sha256"]==digest(receipt),"receipt":str(receipt.relative_to(ROOT)),"receipt_sha256":digest(receipt),"owned_inode_token":[value.st_dev,value.st_ino],"recovery_cause":record["recovery_cause"]}
    return case, record


def restart_negative_case(record: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=".u29c-v23-restart-",dir=recovery.QA_EPISODE_ROOT) as temporary:
        bad=Path(temporary)/"tampered.json"; changed=dict(record);changed["owned_inode_token"]=[0,0];bad.write_text(json.dumps(changed),encoding="utf-8")
        error=None
        try: writer.validate_restart(bad)
        except base.GateError as exc: error=str(exc)
    return {"case_id":"RESTART_REJECTS_TAMPERED_OWNED_INODE_TOKEN","passed":error=="RECOVERY_RECEIPT_RESTART_BINDING_MISMATCH","error":error,"blind_replay_allowed":False}


def competitor_case() -> dict[str, Any]:
    recovery.FINAL_ROOT.mkdir(mode=0o700,parents=True,exist_ok=True);target=recovery.FINAL_ROOT/COMPETITOR_NAME;sentinel=b"V23_COMPETITOR\n";fd=os.open(target,base.create_flags(),0o600)
    try: base.write_all(fd,sentinel);os.fsync(fd)
    finally: os.close(fd)
    completed=subprocess.run([sys.executable,str(WRITER),"--output-name",COMPETITOR_NAME],cwd=ROOT,capture_output=True,text=True,close_fds=True,check=False)
    receipt=writer.RECEIPT_ROOT/writer.receipt_name(COMPETITOR_NAME)
    return {"case_id":"COMPETING_PUBLIC_PRESERVED_WITHOUT_RECEIPT","passed":completed.returncode==1 and completed.stderr.strip()=="PUBLICATION_TARGET_EXISTS" and target.read_bytes()==sentinel and not receipt.exists(),"competitor_preserved":target.read_bytes()==sentinel,"receipt_absent":not receipt.exists()}


def crash_boundaries() -> dict[str, Any]:
    boundaries=["BEFORE_DATA_LINK","AFTER_DATA_LINK_BEFORE_DATA_DIR_FSYNC","AFTER_DATA_HIDDEN_UNLINK","AFTER_RECEIPT_HIDDEN_FSYNC_BEFORE_RECEIPT_LINK","AFTER_RECEIPT_LINK_BEFORE_RECEIPT_DIR_FSYNC","BEFORE_CALLER_RETURN"]
    rules={name:("RESTART_VALIDATE_PERSISTED_RECEIPT_AND_CURRENT_EXACT_OWNED_OUTPUT" if name=="BEFORE_CALLER_RETURN" else "NO_RECOVERED_SUCCESS_WITHOUT_DURABLE_VALID_RECEIPT") for name in boundaries}
    return {"case_id":"SIX_DATA_AND_RECEIPT_CRASH_BOUNDARIES_FAIL_CLOSED","passed":len(boundaries)==6 and all(rules.values()),"boundaries":rules,"blind_replay_allowed":False}


def substitutions() -> dict[str, Any]:
    results=[]
    for flag in ["--writer","--validator","--contract","--final-root","--receipt-root"]:
        name=f"E40_U29C_V23_REJECT_{flag[2:].replace('-','_').upper()}.json";completed=subprocess.run([sys.executable,str(WRITER),"--output-name",name,flag,"/tmp/forbidden"],cwd=ROOT,capture_output=True,text=True,close_fds=True,check=False);results.append({"flag":flag,"returncode":completed.returncode,"output_absent":not (recovery.FINAL_ROOT/name).exists(),"receipt_absent":not (writer.RECEIPT_ROOT/writer.receipt_name(name)).exists()})
    return {"case_id":"CALLER_SUBSTITUTIONS_REJECTED_BEFORE_CHILD","passed":all(x["returncode"]==2 and x["output_absent"] and x["receipt_absent"] for x in results),"results":results}


def write_report(payload: dict[str, Any]) -> None:
    REPORT.parent.mkdir(parents=True,exist_ok=True);fd=os.open(REPORT,base.create_flags(),0o600)
    try:data=(json.dumps(payload,ensure_ascii=False,indent=2)+"\n").encode();base.write_all(fd,data);os.fsync(fd)
    finally:os.close(fd)


def main() -> int:
    if REPORT.exists() or REPORT.is_symlink():raise SystemExit("REPORT_ALREADY_EXISTS")
    for name in [NORMAL_NAME,RECOVERED_NAME,COMPETITOR_NAME]:
        if (recovery.FINAL_ROOT/name).exists():raise SystemExit(f"OUTPUT_ALREADY_EXISTS_{name}")
    writer.RECEIPT_ROOT.mkdir(mode=0o700,parents=True,exist_ok=True);pins=[WRITER,V22_AUDIT,V23_SPEC];expected={str(WRITER.relative_to(ROOT)):WRITER_SHA256,str(V22_AUDIT.relative_to(ROOT)):V22_AUDIT_SHA256,str(V23_SPEC.relative_to(ROOT)):V23_SPEC_SHA256};before={str(p.relative_to(ROOT)):digest(p) for p in pins};hidden_before={"data":data_hidden(),"receipt":receipt_hidden()};normal=normal_case();recovered,record=recovered_case();cases=[normal,recovered,restart_negative_case(record),competitor_case(),crash_boundaries(),substitutions()];after={str(p.relative_to(ROOT)):digest(p) for p in pins};hidden_after={"data":data_hidden(),"receipt":receipt_hidden()};failures=[c["case_id"] for c in cases if not c["passed"]];failures.extend(name for name,value in expected.items() if before.get(name)!=value)
    if before!=after:failures.append("PINNED_INPUT_MUTATION")
    if hidden_before!={"data":[],"receipt":[]} or hidden_after!={"data":[],"receipt":[]}:failures.append("OWNED_HIDDEN_RESIDUE_NONZERO")
    status="PASS_PERSISTED_OWNED_INODE_RECEIPT_RESTART_CRASH_COMPETITOR_ZERO_RESIDUE_NO_SUBMIT" if not failures else "FAIL";report={"schema":"qingshan.e40.u29c.v23.persisted_recovery_receipt_bounded_matrix.v1","episode":"E40","unit_id":"U29C","recorded_at":stamp(),"status":status,"execution_permitted":False,"provider_post_allowed":False,"maximum_new_submissions":0,"pins_before":before,"pins_after":after,"hidden_before":hidden_before,"hidden_after":hidden_after,"cases":cases,"failures":failures,"side_effects":{"provider_calls":0,"transactions":0,"credits":0,"retries":0,"agentcut":0,"assembly":0},"next_action":"Keep execution closed. Register exact-SHA V24 persisted receipt restart regression."};write_report(report);print(json.dumps({"status":status,"report":str(REPORT),"failures":failures},ensure_ascii=False));return 0 if not failures else 1


if __name__=="__main__":raise SystemExit(main())
