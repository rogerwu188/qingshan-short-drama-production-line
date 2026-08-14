#!/usr/bin/env python3
"""One-shot, offline U18-local snapshot readiness check. Never watches."""
from __future__ import annotations
import argparse,hashlib,json,os,time
from pathlib import Path
from tools.e40_u18_v9_offline_snapshot_ingest import validate
NAMES=['result_17939df6-4f2c-4148-91c3-38f26870b6dc.json','result_bac46b24-b9a2-4a17-ab48-c2327b82b67a.json','credit_authoritative_exact_two.json']
def ident(p):
 s=p.lstat();return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest())
def check(root:Path,stability_delay:float=0.0):
 missing=[n for n in NAMES if not (root/n).is_file()];partials=sorted(p.name for p in root.glob('*') if p.name.endswith(('.part','.tmp','.download')) or p.name.startswith('.')) if root.is_dir() else []
 if missing or partials:return {'schema':'qingshan.e40.u18.v15.snapshot_readiness.v1','status':'TASK_LOCAL_REMOTE_WAIT','scope':'U18_ONLY','blocks_other_lanes':False,'missing':missing,'partial_files':partials,'admission_permitted':False}
 paths=[root/n for n in NAMES]
 if any(p.is_symlink() for p in paths):return {'schema':'qingshan.e40.u18.v15.snapshot_readiness.v1','status':'TASK_LOCAL_REMOTE_WAIT','scope':'U18_ONLY','blocks_other_lanes':False,'failures':['SYMLINK_REJECTED'],'admission_permitted':False}
 a=[ident(p) for p in paths]
 if stability_delay:time.sleep(stability_delay)
 b=[ident(p) for p in paths]
 if a!=b:return {'schema':'qingshan.e40.u18.v15.snapshot_readiness.v1','status':'TASK_LOCAL_REMOTE_WAIT','scope':'U18_ONLY','blocks_other_lanes':False,'failures':['MTIME_SIZE_INODE_SHA_NOT_STABLE'],'admission_permitted':False}
 result=validate(paths[:2],paths[2],root)
 return {'schema':'qingshan.e40.u18.v15.snapshot_readiness.v1','status':'READY_FOR_LOCAL_OUTPUT_QA' if result['status']=='PASS' else 'TASK_LOCAL_REMOTE_WAIT','scope':'U18_ONLY','blocks_other_lanes':False,'stability':{'observations':2,'identities_equal':True},'ingest':result,'admission_permitted':False}
def main():
 p=argparse.ArgumentParser();p.add_argument('--snapshot-root',type=Path,required=True);p.add_argument('--stability-delay-seconds',type=float,default=2);p.add_argument('--out',type=Path);a=p.parse_args();r=check(a.snapshot_root,a.stability_delay_seconds);s=json.dumps(r,ensure_ascii=False,indent=2)+'\n';a.out.write_text(s) if a.out else print(s,end='');return 0 if r['status']=='READY_FOR_LOCAL_OUTPUT_QA' else 3
if __name__=='__main__':raise SystemExit(main())
