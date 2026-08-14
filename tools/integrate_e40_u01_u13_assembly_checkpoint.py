#!/usr/bin/env python3
from __future__ import annotations

import hashlib, json, os, tempfile
from datetime import datetime, timezone
from pathlib import Path

R = Path(__file__).resolve().parents[1]
W = R / "workflow/work_queue.json"; X = R / "workflow/CODEX_TO_CLAUDE.md"
P = R / "working_assets/e40_assembly_20260814/u01_u13_parallel_prefix_v1/E40_U01_U13_LOCAL_PREVIEW_HARDCUT_720X1280_V1.mp4"
Q = R / "qa/e40_assembly_20260814/u01_u13_parallel_prefix_v1/E40_U01_U13_LOCAL_PREFIX_MACHINE_AND_HUMAN_QA_V1.json"

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def rel(p): return str(p.relative_to(R))
def wr(p, d):
    blob=(json.dumps(d,ensure_ascii=False,indent=2)+"\n").encode(); fd,tmp=tempfile.mkstemp(prefix=f".{p.name}.",dir=p.parent)
    try:
        with os.fdopen(fd,"wb") as h: h.write(blob); h.flush(); os.fsync(h.fileno())
        os.replace(tmp,p)
    except Exception: Path(tmp).unlink(missing_ok=True); raise

def main():
    for p in (W,X,P,Q):
        if not p.is_file(): raise SystemExit(f"FAIL_MISSING:{p}")
    q=json.loads(Q.read_text())
    if q.get("status")!="PASS_IMMUTABLE_PREFIX_U01_U13" or q.get("failures"): raise SystemExit("FAIL_QA_GATE")
    w=json.loads(W.read_text()); w["latest_e40_u01_u13_assembly_prefix"]={"status":q["status"],"path":rel(P),"sha256":sha(P),"duration_seconds":64.166667,"qa":rel(Q),"qa_sha256":sha(Q),"provider_posts":0,"credits":0,"next_action":"Append U14 after U14 exact audiovisual admission; preserve U01-U13 order."}; wr(W,w)
    n=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    with X.open("a",encoding="utf-8") as h:
        h.write(f"\n\n## E40 checkpoint {n} — parallel assembly prefix advanced through admitted U13\n\n- U01-U13 prefix `{rel(P)}` SHA=`{sha(P)}` is 64.166667s, 720x1280/24fps, AAC 48k stereo, matched A/V and full-decode PASS. Human QA confirms the U12 airborne rubbing to U13 landed-rubbing/half-rise causal cut; QA SHA=`{sha(Q)}`. Provider posts/credits=0; not final or released.\n"); h.flush(); os.fsync(h.fileno())
    print(json.dumps({"status":"PASS_U01_U13_ASSEMBLY_CHECKPOINT","prefix_sha256":sha(P),"qa_sha256":sha(Q)},ensure_ascii=False)); return 0
if __name__=="__main__": raise SystemExit(main())
