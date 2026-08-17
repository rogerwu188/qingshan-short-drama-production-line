#!/usr/bin/env python3
"""Harvest bound E40 remake video tasks exactly once and write source intake receipt."""
from __future__ import annotations
import argparse, hashlib, json, urllib.request
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor, as_completed
from giggle_api_client import query_task

ROOT = Path(__file__).resolve().parents[1]

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()

def download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.part')
    req = urllib.request.Request(url, headers={'User-Agent':'qingshan-e40-remake-harvester/1.0'})
    with urllib.request.urlopen(req, timeout=300) as r: tmp.write_bytes(r.read())
    tmp.replace(path)

def one(row: dict, out_dir: Path, raw_dir: Path) -> dict:
    task_id = row['remote_task_id']
    response = query_task(SimpleNamespace(task_id=task_id))
    raw = (raw_dir / f"{row['task_id']}_{task_id}.json").resolve(); raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(json.dumps(response, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    data = response.get('data') or {}; status = str(data.get('status') or 'UNKNOWN')
    result = {**row, 'remote_status': status, 'raw_response': str(raw.relative_to(ROOT))}
    assets = data.get('asset_info') or []; asset = assets[0] if assets else {}
    url = asset.get('download_url') or asset.get('signed_url') or ((data.get('urls') or [None])[0])
    if status == 'completed' and url:
        target = out_dir / f"{row['task_id']}_{task_id}.mp4"
        if not target.exists(): download(url, target)
        result.update({'output_path': str(target.resolve().relative_to(ROOT)), 'output_sha256': sha(target), 'bytes': target.stat().st_size, 'asset_id': asset.get('asset_id')})
    elif status in {'failed','error','cancelled','canceled'}:
        result['error'] = data.get('err_msg') or status
    return result

def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument('--scheduler', required=True); ap.add_argument('--out-dir', required=True); ap.add_argument('--out', required=True); ap.add_argument('--workers', type=int, default=7); args = ap.parse_args()
    scheduler = json.loads(Path(args.scheduler).read_text(encoding='utf-8'))
    out_dir = Path(args.out_dir).resolve(); raw_dir = out_dir.parent / (out_dir.name + '_raw')
    rows = [x for x in scheduler.get('tasks',[]) if x.get('remote_task_id') and x.get('state') == 'REMOTE_WAIT']
    results=[]
    with ThreadPoolExecutor(max_workers=max(1,args.workers)) as pool:
        futures=[pool.submit(one,row,out_dir,raw_dir) for row in rows]
        for f in as_completed(futures): results.append(f.result())
    results.sort(key=lambda x:x['task_id'])
    counts={}
    for x in results: counts[x['remote_status']] = counts.get(x['remote_status'],0)+1
    payload={'schema':'qingshan.e40.remake.video_wave_harvest.v1','episode':'E40-REMAKE-V1','status':'PASS_ALL_COMPLETED_SOURCE_INTAKE' if counts.get('completed',0)==len(results) else 'PARTIAL_REMOTE_WAIT','counts':counts,'results':results,'old_e40_media_reuse':False}
    out=Path(args.out).resolve(); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':payload['status'],'counts':counts,'out':str(out)},ensure_ascii=False)); return 0
if __name__=='__main__': raise SystemExit(main())
