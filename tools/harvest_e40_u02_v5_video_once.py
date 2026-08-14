#!/usr/bin/env python3
"""Query bound E40 U02 V5 task once and download once if completed."""
from __future__ import annotations
import hashlib, json, os, tempfile, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from giggle_api_client import query_task
from submit_giggle_task_manifest import ensure_giggle_api_key

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = '85c0018e-32bb-4f38-aa78-9db07d2cdde4'
TASK_KEY = 'E40-U02-V5-FAST720-LOW-HEM-EXACT-FIRST-FRAME-CAUSAL-BEATS-SILENT-V1'
TX = ROOT / 'workflow/tasks/giggle_video_submit_transactions/E40/E40-U02-V5-FAST720-LOW-HEM-EXACT-FIRST-FRAME-CAUSAL-BEATS-SILENT-V1__bf9c35e79327303e.json'
RAW = ROOT / f'working_assets/e40_production_20260814/raw_u02_v5_fast720/{TASK_KEY}_{TASK_ID}.json'
OUTPUT = ROOT / f'working_assets/e40_production_20260814/u02_v5_fast720/{TASK_KEY}_{TASK_ID}.mp4'
REPORT = ROOT / 'workflow/tasks/E40_U02_V5_FAST720_HARVEST_20260814.json'

def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def portable(path): return str(Path(path).relative_to(ROOT))
def write(path, payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2); handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)
def download_once(url, output):
    if output.exists(): raise RuntimeError('output already exists; repeat download forbidden')
    output.parent.mkdir(parents=True, exist_ok=True); partial = output.with_suffix('.mp4.part')
    if partial.exists(): raise RuntimeError('partial output exists; manual classification required')
    request = urllib.request.Request(url, headers={'User-Agent':'qingshan-e40-u02-v5-harvester/1.0'})
    try:
        with urllib.request.urlopen(request, timeout=600) as response, partial.open('wb') as handle:
            for chunk in iter(lambda: response.read(1024 * 1024), b''): handle.write(chunk)
        if partial.stat().st_size <= 0: raise RuntimeError('empty downloaded video')
        os.replace(partial, output)
    except Exception:
        if partial.exists(): partial.unlink()
        raise

def main():
    if REPORT.exists() or RAW.exists() or OUTPUT.exists(): raise SystemExit('harvest artifact already exists; repeat query/download forbidden')
    if ensure_giggle_api_key() in {'MISSING','UNSAFE_FILE_PERMISSIONS'}: raise SystemExit('GIGGLE_API_KEY unavailable')
    tx = json.loads(TX.read_text())
    if tx.get('state') != 'SUBMITTED_TASK_ID_BOUND' or tx.get('task_id') != TASK_ID: raise SystemExit('transaction binding mismatch')
    queried_at = now(); response = query_task(SimpleNamespace(task_id=TASK_ID)); write(RAW, response)
    data = response.get('data') or {}; status = str(data.get('status') or 'unknown').lower()
    report = {'schema':'qingshan.e40.u02.v5.fast720_video_harvest.v1','recorded_at':queried_at,'task_key':TASK_KEY,'task_id':TASK_ID,
              'transaction':portable(TX),'transaction_sha256':sha(TX),'query_count':1,'download_count':0,'remote_status':status,
              'raw_response':portable(RAW),'raw_response_sha256':sha(RAW),'provider_posts':0,'new_transactions':0,'new_credits':0}
    if status == 'completed':
        assets = data.get('asset_info') or []
        if len(assets) != 1: raise SystemExit(f'completed task asset count must be 1, got {len(assets)}')
        asset = assets[0]; url = asset.get('download_url') or asset.get('signed_url')
        if not url: raise SystemExit('completed task missing signed download URL')
        download_once(url, OUTPUT)
        report.update({'status':'COMPLETED_DOWNLOADED_PENDING_QA','download_count':1,'output_path':portable(OUTPUT),'output_sha256':sha(OUTPUT),
                       'output_size_bytes':OUTPUT.stat().st_size,'remote_asset_id':asset.get('asset_id'),'next_action':'Run mandatory technical, exact-frame, cadence, OCR and original-resolution human QA.'})
    elif status in {'failed','error','cancelled','canceled'}:
        report.update({'status':'REMOTE_TERMINAL_FAILURE_NO_RETRY','failure_reason':data.get('err_msg') or status,
                       'next_action':'Classify authoritative terminal/refund, persist failure memory and materially change prompt before any retry.'})
    else:
        report.update({'status':'REMOTE_RUNNING_NO_DOWNLOAD','next_action':'Keep task-local REMOTE_WAIT and query this exact task_id once at the next scheduled wakeup.'})
    write(REPORT, report); print(json.dumps(report, ensure_ascii=False))

if __name__ == '__main__': main()
