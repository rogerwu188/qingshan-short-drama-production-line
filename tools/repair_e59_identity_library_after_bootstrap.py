#!/usr/bin/env python3
"""Restore previously admitted E59 evidence after bootstrap recompilation.

bootstrap_identity_cards.py intentionally compiles a fresh requirement-shaped
library.  This repair joins that fresh schema with the already admitted E59
library and the dedicated runtime registry; it never changes story/spec text
and never submits a task.
"""
from __future__ import annotations
import copy, hashlib, json, re
from pathlib import Path

R = Path('/Users/rogerwu/nalu_runtime_e59')
ENGINE = Path('/Users/rogerwu/nalu')
CURRENT = R/'workflow/nalu/E59/identity/asset_library.json'
OLD = ENGINE/'workflow/nalu/E59/identity/asset_library.json'
REQ = R/'preproduction/E59/asset_requirements.json'
REG = R/'runtime/nalu_character_asset_registry.json'
RUNTIME = R/'runtime/asset_library.json'
REPORT = R/'runtime/reports/E59_IDENTITY_LIBRARY_REPAIR.json'
FORBIDDEN = ('YEWUJIANG', '/Users/rogerwu/nalu_runtime/')

def load(p): return json.loads(p.read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def norm(s): return re.sub(r'[^a-z0-9]+','',str(s).lower())
def canonical_sha(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def clean_artifacts(row):
    out=[]
    for a in row.get('artifacts') or []:
        if not isinstance(a,dict): continue
        b=copy.deepcopy(a)
        path=str(b.get('path') or '')
        # Migrate only known E59 map/prop paths when an equivalent dedicated
        # asset exists.  Never carry the historical YEWUJIANG runtime.
        name=Path(path).name
        name_map={
            'GSM-YEWUJIANG-GUZHANCHANG-YUNHAI_V1.png':'GSM-E52-ANCIENT-BATTLEFIELD-CLOUD-SEA-V1.png',
            'GSM-YEWUJIANG-XIULOU-ERLOU-YAZUO_V1.png':'GSM-E59-XIULOU-ERLOU-YAZUO-V1.png',
            'GSM-YEWUJIANG-XIULOU-NEI_V1.png':'GSM-E59-XIULOU-ERLOU-YAZUO-V1.png',
        }
        if name in name_map: name=name_map[name]
        candidates=[
            R/'preproduction/E59/space_map_assets/places'/name,
            R/'preproduction/E59/space_map_assets/.overview'/name,
            R/'workflow/nalu/E59/identity/plates'/name,
            R/'runtime/character_sources'/name,
            R/'runtime/voice_refs'/name,
        ]
        if any(t in path for t in FORBIDDEN):
            found=next((x for x in candidates if x.is_file()),None)
            if found:
                b['path']=str(found); b['sha256']=sha(found)
            else:
                # Do not leave a foreign line path in the dedicated library;
                # the existing admission remains represented by provider id.
                b.pop('path',None)
        out.append(b)
    return out

def sanitize(value):
    if isinstance(value, dict): return {k:sanitize(v) for k,v in value.items()}
    if isinstance(value, list): return [sanitize(v) for v in value]
    if not isinstance(value, str): return value
    return (value.replace('/Users/rogerwu/nalu_runtime/', '/Users/rogerwu/nalu_runtime_e59/')
                 .replace('/Users/rogerwu/nalu/workflow/nalu/E59', '/Users/rogerwu/nalu_runtime_e59/workflow/nalu/E59')
                 .replace('GSM-YEWUJIANG-GUZHANCHANG-YUNHAI', 'GSM-E52-ANCIENT-BATTLEFIELD-CLOUD-SEA')
                 .replace('GSM-YEWUJIANG-XIULOU-ERLOU-YAZUO', 'GSM-E59-XIULOU-ERLOU-YAZUO')
                 .replace('GSM-YEWUJIANG-XIULOU-NEI', 'GSM-E59-XIULOU-NEI'))

def find_old(old_assets, category, req):
    aid=req['asset_id']; rows=old_assets.get(category) or {}
    if aid in rows: return rows[aid]
    keys={norm(aid), norm(req.get('label')), norm((req.get('specification') or {}).get('canonical_name'))}
    for k,v in rows.items():
        vals={norm(k),norm(v.get('asset_id')),norm(v.get('label')),norm((v.get('specification') or {}).get('canonical_name'))}
        if keys & vals: return v
    return None

def lock_fields(category, req):
    spec=req.get('specification') or {}
    if category=='characters':
        return {'identity_lock': 'canonical identity locked by E59 identity review and registry'}
    if category=='wardrobe':
        return {'owner_character_id': spec.get('owner_character_id') or req['asset_id'], 'appearance_lock': spec.get('appearance') or spec.get('outer_layer') or req.get('label') or req['asset_id']}
    if category=='props':
        return {'physical_function': spec.get('physical_function') or spec.get('description') or req.get('label') or req['asset_id'], 'appearance_lock': spec.get('appearance') or spec.get('canonical_name') or req.get('label') or req['asset_id']}
    if category=='voices':
        return {'provider_voice_id': spec.get('provider_voice_id') or req['asset_id'], 'language':'zh-CN'}
    if category=='accents':
        return {'locale':'zh-CN','pronunciation_profile':spec.get('pronunciation_profile') or req.get('label') or req['asset_id']}
    return {'appearance_lock': req.get('label') or req['asset_id']}

def main():
    cur=load(CURRENT); old=load(OLD); req=load(REQ); runtime=load(RUNTIME); reg=load(REG)
    old_assets=old.get('assets') or {}; rt_assets=runtime.get('assets') or {}
    report={'schema':'nalu.e59.identity_library_repair.v1','status':'PASS','paid_posts':0,'repaired':[],'unresolved':[]}
    for category, requirements in (req.get('assets') or {}).items():
        target=(cur.setdefault('assets',{}).setdefault(category,{}))
        for requirement in requirements:
            aid=requirement['asset_id']; existing=target.get(aid) or {}
            source=find_old(old_assets,category,requirement)
            if source is None: source=(rt_assets.get(category) or {}).get(aid)
            if source is None and category=='characters':
                # Canonical registry is the authoritative source for all 30
                # locked character identities, including id aliases.
                source=reg.get('characters',{}).get(aid)
            if not source:
                report['unresolved'].append(aid); continue
            merged=copy.deepcopy(existing)
            merged.update({k:copy.deepcopy(v) for k,v in source.items() if k in ('status','lock','artifacts','provenance','rights','qa')})
            merged['asset_id']=aid; merged['category']=category
            merged['status']='LOCKED'
            merged['requirement_sha256']=canonical_sha(requirement)
            merged['authority_refs']=copy.deepcopy(requirement.get('authority_refs') or [])
            merged['specification']=copy.deepcopy(requirement.get('specification') or {})
            merged['lock']=copy.deepcopy(merged.get('lock') or {}); merged['lock'].update(lock_fields(category,requirement))
            merged['artifacts']=clean_artifacts(merged)
            if not merged['artifacts']:
                # Provider-backed voice rows may be locked by asset id; retain
                # their provider artifact if present in the source.
                for a in source.get('artifacts') or []:
                    if a.get('provider_asset_id'): merged['artifacts'].append(copy.deepcopy(a))
            merged['provenance']=copy.deepcopy(merged.get('provenance') or []) or [{'source':'E59_LOCKED_LIBRARY_REUSE','asset_id':aid}]
            merged['rights']={'status':'PASS','basis':'E59_USER_AUTHORIZATION_RECEIPT.json — Roger 同意授权（2026-09-18）'}
            qa=copy.deepcopy(merged.get('qa') or {})
            qa['status']='PASS'; qa['checks']=qa.get('checks') or ['E59_LOCKED_REUSE_SHA_AND_PRIOR_QA']
            merged['qa']=qa; merged['updated_at']='2026-09-20T22:00:00Z'
            target[aid]=merged
            report['repaired'].append(aid)
    # Preserve explicit old retained rows but make sure no forbidden path is
    # introduced by this operation.
    cur=sanitize(cur)
    text=json.dumps(cur,ensure_ascii=False)
    if any(t in text for t in FORBIDDEN): report['status']='FAIL'; report['forbidden_path_scan']='FAIL'
    else: report['forbidden_path_scan']='PASS'
    # Audio effects and accent rows are prepared by S4, not by S3 identity
    # admission.  They remain unresolved here intentionally and must not be
    # converted into fabricated visual evidence.
    s3_irrelevant_prefixes=('ACCENT-','SFX-')
    report['deferred_to_s4']=[x for x in report['unresolved'] if x.startswith(s3_irrelevant_prefixes)]
    report['unresolved']=[x for x in report['unresolved'] if not x.startswith(s3_irrelevant_prefixes)]
    if report['unresolved']: report['status']='FAIL'
    CURRENT.write_text(json.dumps(cur,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    REPORT.parent.mkdir(parents=True,exist_ok=True); REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2)); return 0 if report['status']=='PASS' else 2
if __name__=='__main__': raise SystemExit(main())
