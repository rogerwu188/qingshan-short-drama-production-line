#!/usr/bin/env python3
"""Pinned V21 recovery, reader, contention, residue and substitution matrix."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as base  # noqa: E402
import run_e40_u29c_v20_post_link_recovery_publish_gate as writer  # noqa: E402


INVOKER = ROOT / "tools/run_e40_u29c_v21_pinned_post_link_recovery_regression.py"
INVOKER_SHA256 = "1569d2575d4654c780641484b2d7b75f937fdb1b003696e02ddff4313c7ec8f4"
V20_WRITER = ROOT / "tools/run_e40_u29c_v20_post_link_recovery_publish_gate.py"
V20_WRITER_SHA256 = "6b61cf37134e1a3a2fa16f95140db82efaf5fe164a52e5373ed324890cde227e"
V20_MATRIX = ROOT / "qa/e40_preproduction_20260808/u29c_v20_post_link_recovery_writer_v1/E40_U29C_V20_POST_LINK_RECOVERY_BOUNDED_MATRIX_V1.json"
V20_MATRIX_SHA256 = "6264a06504f9f9dc88da98a60a0fe1053e8abe420714ce9fa78f54714f3a0c81"
V19_AUDIT = ROOT / "qa/e40_preproduction_20260808/u29c_v19_atomic_link_exception_safety_audit_v1/E40_U29C_V19_ATOMIC_LINK_EXCEPTION_SAFETY_AUDIT_V1.json"
V19_AUDIT_SHA256 = "5b872fe948e6516bbfa571dd135fd8e02216800658a87a0c9f2ade8155b76ca5"
V21_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v21_pinned_recovery_regression_v1/E40_U29C_V21_PINNED_POST_LINK_RECOVERY_REGRESSION_SPEC_V1.json"
V21_SPEC_SHA256 = "48c399a938aa74a57cbb41104ba82406d388cc54fb7b45dff3f8845fe35a2526"
REPORT = ROOT / "qa/e40_preproduction_20260808/u29c_v21_pinned_recovery_regression_v1/E40_U29C_V21_PINNED_RECOVERY_REGRESSION_MATRIX_V1.json"
CANONICAL = writer.FINAL_ROOT / "E40_U29C_V20_CANONICAL_RECOVERY_GATE_V1.json"
READER_NAME = "E40_U29C_V21_PINNED_READER_GATE_V1.json"
SHARED_NAME = "E40_U29C_V21_PINNED_SHARED_CONTENTION_GATE_V1.json"
CONTENDERS = 8
MAX_WORKERS = 4


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def valid_public(path: Path) -> bool:
    try:
        payload = path.read_bytes()
        report = base.validate_report_bytes(payload)
        value = os.stat(path, follow_symlinks=False)
        return bool(payload) and stat.S_ISREG(value.st_mode) and value.st_nlink == 1 and report.get("execution_permitted") is False
    except (OSError, base.GateError):
        return False


def root_identity(path: Path) -> list[int]:
    value = os.stat(path, follow_symlinks=False)
    return [value.st_dev, value.st_ino, stat.S_IMODE(value.st_mode)]


def residues() -> dict[str, list[str]]:
    return {
        "hidden": sorted(path.name for path in writer.FINAL_ROOT.iterdir() if path.name.startswith(".u29c-v20-hidden-")),
        "stage": sorted(path.name for path in writer.STAGING_ROOT.iterdir()),
    }


def reader_case() -> dict[str, Any]:
    target = writer.FINAL_ROOT / READER_NAME
    process = subprocess.Popen([sys.executable, str(INVOKER), "--output-name", READER_NAME], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, close_fds=True)
    observations: list[bool] = []
    while process.poll() is None:
        if target.exists() or target.is_symlink(): observations.append(valid_public(target))
        time.sleep(0.001)
    stdout, stderr = process.communicate()
    observations.append(valid_public(target))
    result = json.loads(stdout) if process.returncode == 0 else {}
    return {"case_id":"PINNED_READER_ONLY_OBSERVES_COMPLETE_PUBLICATION","passed":process.returncode==0 and all(observations) and result.get("invoker_status")=="PASS_PINNED_V20_POST_LINK_RECOVERY_NO_SUBMIT" and result.get("post_link_recovered") is False,"observation_count":len(observations),"all_observations_valid":all(observations),"stderr":stderr.strip()}


def fixture(base_path: Path, name: str, action: Callable[[base.RootBinding, Path], dict[str, Any]]) -> dict[str, Any]:
    path = base_path / name
    binding = base.open_bound_root(path)
    try: return action(binding, path)
    finally: os.close(binding.fd)


def malformed(binding: base.RootBinding, path: Path) -> dict[str, Any]:
    error = None
    try: writer.publish_complete_payload(binding, "public.json", b"{bad")
    except base.GateError as exc: error = str(exc)
    entries = sorted(item.name for item in path.iterdir())
    return {"case_id":"PINNED_MALFORMED_PRE_LINK_NO_PUBLICATION","passed":error=="STAGED_REPORT_INVALID_JSON" and entries==[],"error":error,"entries_after":entries}


def write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        size = os.write(fd, view)
        if size <= 0: raise RuntimeError("FIXTURE_WRITE_FAILED")
        view = view[size:]


def competitor(binding: base.RootBinding, path: Path, payload: bytes) -> dict[str, Any]:
    sentinel = b"PINNED_COMPETITOR\n"
    fd = os.open("public.json", base.create_flags(), 0o600, dir_fd=binding.fd)
    try: write_all(fd, sentinel); os.fsync(fd)
    finally: os.close(fd)
    error = None
    try: writer.publish_complete_payload(binding, "public.json", payload)
    except base.GateError as exc: error = str(exc)
    entries = sorted(item.name for item in path.iterdir()); preserved=(path/"public.json").read_bytes()==sentinel
    return {"case_id":"PINNED_COMPETITOR_PRESERVED_NOT_RECOVERED","passed":error=="PUBLICATION_TARGET_EXISTS" and preserved and entries==["public.json"],"error":error,"competitor_preserved":preserved,"entries_after":entries}


def fsync_recovery(binding: base.RootBinding, path: Path, payload: bytes) -> dict[str, Any]:
    original=writer.os.fsync; fired=False
    def inject(fd: int) -> None:
        nonlocal fired
        if fd==binding.fd and not fired: fired=True; raise OSError("PINNED_FSYNC_INTERRUPT")
        original(fd)
    writer.os.fsync=inject
    try: report,recovered,cause=writer.publish_complete_payload(binding,"public.json",payload)
    finally: writer.os.fsync=original
    entries=sorted(item.name for item in path.iterdir())
    return {"case_id":"PINNED_POST_LINK_FSYNC_EXACT_OWNED_RECOVERY","passed":fired and recovered and cause=="OSError" and report.get("execution_permitted") is False and valid_public(path/"public.json") and entries==["public.json"],"recovered":recovered,"recovery_cause":cause,"entries_after":entries}


def cleanup_recovery(binding: base.RootBinding, path: Path, payload: bytes) -> dict[str, Any]:
    original=writer.cleanup_owned_hidden; calls=0
    def inject(hidden: base.HiddenInode) -> bool:
        nonlocal calls
        calls+=1
        if calls==1: raise OSError("PINNED_CLEANUP_INTERRUPT")
        return original(hidden)
    writer.cleanup_owned_hidden=inject
    try: report,recovered,cause=writer.publish_complete_payload(binding,"public.json",payload)
    finally: writer.cleanup_owned_hidden=original
    entries=sorted(item.name for item in path.iterdir())
    return {"case_id":"PINNED_CLEANUP_INTERRUPT_EXACT_OWNED_RECOVERY","passed":calls==2 and recovered and cause=="OSError" and report.get("execution_permitted") is False and valid_public(path/"public.json") and entries==["public.json"],"cleanup_calls":calls,"recovered":recovered,"recovery_cause":cause,"entries_after":entries}


def contender(index: int) -> dict[str, Any]:
    completed=subprocess.run([sys.executable,str(INVOKER),"--output-name",SHARED_NAME],cwd=ROOT,capture_output=True,text=True,close_fds=True,check=False)
    return {"contender":index,"returncode":completed.returncode,"stdout":completed.stdout.strip(),"stderr":completed.stderr.strip()}


def contention() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    results=[]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures=[pool.submit(contender,i) for i in range(1,CONTENDERS+1)]
        for future in as_completed(futures): results.append(future.result())
    results.sort(key=lambda x:x["contender"]); winners=[x for x in results if x["returncode"]==0]; losers=[x for x in results if x["returncode"]==1 and x["stderr"]=="PUBLICATION_TARGET_EXISTS"]
    return ({"case_id":"PINNED_EIGHT_SAME_BASENAME_ONE_WINNER_SEVEN_LOSERS","passed":len(winners)==1 and len(losers)==7 and valid_public(writer.FINAL_ROOT/SHARED_NAME),"winner_count":len(winners),"publication_target_exists_loser_count":len(losers)},results)


def substitutions() -> dict[str, Any]:
    results=[]
    for flag in ["--writer","--validator","--contract","--final-root","--staging-root"]:
        name=f"E40_U29C_V21_REJECT_{flag[2:].replace('-','_').upper()}.json";completed=subprocess.run([sys.executable,str(INVOKER),"--output-name",name,flag,"/tmp/forbidden"],cwd=ROOT,capture_output=True,text=True,close_fds=True,check=False);results.append({"flag":flag,"returncode":completed.returncode,"output_absent":not (writer.FINAL_ROOT/name).exists()})
    return {"case_id":"PINNED_ALL_CALLER_SUBSTITUTIONS_REJECTED","passed":all(x["returncode"]==2 and x["output_absent"] for x in results),"results":results}


def write_report(payload: dict[str, Any]) -> None:
    REPORT.parent.mkdir(parents=True,exist_ok=True);fd=os.open(REPORT,base.create_flags(),0o600)
    try: data=(json.dumps(payload,ensure_ascii=False,indent=2)+"\n").encode();write_all(fd,data);os.fsync(fd)
    finally: os.close(fd)


def main() -> int:
    if REPORT.exists() or REPORT.is_symlink(): raise SystemExit("REPORT_ALREADY_EXISTS")
    writer.FINAL_ROOT.mkdir(mode=0o700,parents=True,exist_ok=True);writer.STAGING_ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    for name in [READER_NAME,SHARED_NAME]:
        if (writer.FINAL_ROOT/name).exists() or (writer.FINAL_ROOT/name).is_symlink(): raise SystemExit(f"OUTPUT_ALREADY_EXISTS_{name}")
    pins=[INVOKER,V20_WRITER,V20_MATRIX,V19_AUDIT,V21_SPEC];expected={str(INVOKER.relative_to(ROOT)):INVOKER_SHA256,str(V20_WRITER.relative_to(ROOT)):V20_WRITER_SHA256,str(V20_MATRIX.relative_to(ROOT)):V20_MATRIX_SHA256,str(V19_AUDIT.relative_to(ROOT)):V19_AUDIT_SHA256,str(V21_SPEC.relative_to(ROOT)):V21_SPEC_SHA256};pins_before={str(p.relative_to(ROOT)):digest(p) for p in pins};roots_before={"final":root_identity(writer.FINAL_ROOT),"staging":root_identity(writer.STAGING_ROOT)};residue_before=residues();payload=CANONICAL.read_bytes();base.validate_report_bytes(payload)
    with tempfile.TemporaryDirectory(prefix=".u29c-v21-",dir=writer.QA_EPISODE_ROOT) as temporary:
        temp=Path(temporary);cases=[reader_case(),fixture(temp,"malformed",malformed),fixture(temp,"competitor",lambda b,p:competitor(b,p,payload)),fixture(temp,"fsync",lambda b,p:fsync_recovery(b,p,payload)),fixture(temp,"cleanup",lambda b,p:cleanup_recovery(b,p,payload))]
    contention_case,results=contention();cases.extend([contention_case,substitutions()]);pins_after={str(p.relative_to(ROOT)):digest(p) for p in pins};roots_after={"final":root_identity(writer.FINAL_ROOT),"staging":root_identity(writer.STAGING_ROOT)};residue_after=residues();failures=[c["case_id"] for c in cases if not c["passed"]];failures.extend(name for name,value in expected.items() if pins_before.get(name)!=value)
    if pins_before!=pins_after: failures.append("PINNED_INPUT_MUTATION")
    if roots_before!=roots_after: failures.append("ROOT_IDENTITY_OR_MODE_DRIFT")
    if residue_before!={"hidden":[],"stage":[]} or residue_after!={"hidden":[],"stage":[]}: failures.append("OWNED_RESIDUE_NONZERO")
    status="PASS_PINNED_RECOVERY_EXCEPTION_READER_CONTENTION_ZERO_RESIDUE_NO_SUBMIT" if not failures else "FAIL";report={"schema":"qingshan.e40.u29c.v21.pinned_recovery_regression_matrix.v1","episode":"E40","unit_id":"U29C","recorded_at":stamp(),"status":status,"execution_permitted":False,"provider_post_allowed":False,"maximum_new_submissions":0,"bounded_load":{"contenders":CONTENDERS,"maximum_workers":MAX_WORKERS},"pins_before":pins_before,"pins_after":pins_after,"roots_before":roots_before,"roots_after":roots_after,"residue_before":residue_before,"residue_after":residue_after,"cases":cases,"contention_results":results,"failures":failures,"side_effects":{"provider_calls":0,"transactions":0,"credits":0,"retries":0,"agentcut":0,"assembly":0},"next_action":"Keep execution closed. Register a V22 local recovered-success receipt binding and crash-boundary audit."};write_report(report);print(json.dumps({"status":status,"report":str(REPORT),"failures":failures},ensure_ascii=False));return 0 if not failures else 1


if __name__=="__main__": raise SystemExit(main())
