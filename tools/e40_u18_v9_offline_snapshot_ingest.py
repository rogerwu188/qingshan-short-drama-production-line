#!/usr/bin/env python3
"""Offline-only closed-set validator for future U18 result/credit snapshots."""
from __future__ import annotations
import argparse,hashlib,json,os
from pathlib import Path

EXPECTED={
 '17939df6-4f2c-4148-91c3-38f26870b6dc':('E40-U18-ISO-LOW-AXIS-ARROW-V5-CN','9c30d6f2df49d060c554e84220ca2a7b3917086eaf0ac177e83a8cf0bf8f3dea'),
 'bac46b24-b9a2-4a17-ab48-c2327b82b67a':('E40-U18-ISO-TORN-CURTAIN-SOURCE-V5-CN','23efa6a39dfe8c7d79be2a6340da613909447fd9a708f3c997dca0f12da86adf')}
TEMPLATES={'download':'2a524d738a51dbde381eef8aee020a9c6209fc22fd06fcccf35d87f75e7d9544','credit':'6971b3048cbd37669bb2ec36907eb3f6bd72705cb1ebd24733954ee177a097ae','machine':'90ab967ad6a21c5df636a6eaf8a800cc6a1e4889c0b1cb2234e21953a5fc9033'}
def sha(p:Path):return hashlib.sha256(p.read_bytes()).hexdigest()
def safe_snapshot(path:Path,root:Path,kind:str,failures:list[str]):
 try: resolved=path.resolve(strict=True); base=root.resolve(strict=True)
 except Exception:failures.append(f'MISSING_OR_PARTIAL_{kind}:{path.name}');return False
 if path.is_symlink() or resolved.is_symlink():failures.append(f'SYMLINK_REJECTED:{path.name}');return False
 try: resolved.relative_to(base)
 except ValueError:failures.append(f'PATH_TRAVERSAL_REJECTED:{path.name}');return False
 if path.name.endswith('.part') or path.name.startswith('.') or path.suffix!='.json':failures.append(f'PARTIAL_OR_INVALID_NAME_REJECTED:{path.name}');return False
 return True
def validate(result_paths:list[Path],credit_path:Path,snapshot_root:Path|None=None)->dict:
 failures=[];rows=[]
 root=snapshot_root or result_paths[0].parent
 for p in [*result_paths,credit_path]:safe_snapshot(p,root,'SNAPSHOT',failures)
 if len(result_paths)!=2:failures.append('EXACTLY_TWO_RESULT_SNAPSHOTS_REQUIRED')
 seen=set()
 for p in result_paths:
  try:d=json.loads(p.read_text())
  except Exception:failures.append(f'INVALID_RESULT_JSON:{p.name}');continue
  tid=d.get('task_id');seen.add(tid);exp=EXPECTED.get(tid)
  if not exp:failures.append(f'SIBLING_OR_HISTORY_TASK_REJECTED:{tid}');continue
  if d.get('source')!='EXACT_TASK_RESULT_SNAPSHOT':failures.append(f'HISTORY_OR_NONEXACT_SOURCE_REJECTED:{tid}')
  if d.get('task_key')!=exp[0] or d.get('submission_fingerprint')!=exp[1]:failures.append(f'TASK_BINDING_MISMATCH:{tid}')
  if d.get('download_template_sha256')!=TEMPLATES['download'] or d.get('machine_contract_sha256')!=TEMPLATES['machine']:failures.append(f'TEMPLATE_SHA_MISMATCH:{tid}')
  out=d.get('output') or {}
  if d.get('status')=='SUCCESS' and (not out.get('path') or not out.get('sha256')):failures.append(f'UNBOUND_OUTPUT_SHA:{tid}')
  rows.append({'task_id':tid,'snapshot_sha256':sha(p),'output_sha256':out.get('sha256')})
 if seen!=set(EXPECTED):failures.append('EXACT_TASK_ID_CLOSED_SET_MISMATCH')
 try:c=json.loads(credit_path.read_text())
 except Exception:c={};failures.append('INVALID_CREDIT_JSON')
 if c.get('source')!='AUTHORITATIVE_CREDIT_STATEMENT_SNAPSHOT':failures.append('NON_AUTHORITATIVE_CREDIT_SOURCE')
 if c.get('credit_template_sha256')!=TEMPLATES['credit']:failures.append('CREDIT_TEMPLATE_SHA_MISMATCH')
 if set(c.get('task_ids') or [])!=set(EXPECTED):failures.append('CREDIT_TASK_ID_SET_MISMATCH')
 credit_rows=c.get('rows') or []
 row_ids=[r.get('row_id') for r in credit_rows]
 if len(row_ids)!=len(set(row_ids)):failures.append('DUPLICATE_CREDIT_ROW_REJECTED')
 cls=c.get('classification') or {}
 if any(cls.get(k) is None for k in ('pay','refund','net','status')):failures.append('MISSING_PAY_REFUND_NET_CLASSIFICATION')
 elif cls.get('net')!=cls.get('pay')-cls.get('refund'):failures.append('CREDIT_ARITHMETIC_MISMATCH')
 return {'schema':'qingshan.e40.u18.v9.offline_snapshot_ingest_result.v1','status':'PASS' if not failures else 'FAIL_CLOSED','network_capability':False,'result_rows':rows,'credit_snapshot_sha256':sha(credit_path) if credit_path.is_file() else None,'failures':sorted(set(failures)),'execution_permitted':False,'provider_post_allowed':False,'maximum_new_submissions':0}
def main():
 p=argparse.ArgumentParser();p.add_argument('--result',action='append',type=Path,required=True);p.add_argument('--credit',type=Path,required=True);p.add_argument('--snapshot-root',type=Path,required=True);p.add_argument('--out',type=Path);a=p.parse_args();r=validate(a.result,a.credit,a.snapshot_root);text=json.dumps(r,ensure_ascii=False,indent=2)+'\n';
 if a.out:a.out.write_text(text)
 else:print(text,end='')
 return 0 if r['status']=='PASS' else 2
if __name__=='__main__':raise SystemExit(main())
