#!/usr/bin/env python3
"""Build and machine-QA the fresh E40 U01-U16 runtime-repaired prefix."""
from __future__ import annotations

import hashlib, json, subprocess, tempfile, os
from datetime import datetime, timezone
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "working_assets/e40_assembly_20260814/u01_u16_runtime_repaired_prefix_v1"
QAD = ROOT / "qa/e40_assembly_20260814/u01_u16_runtime_repaired_prefix_v1"
VIDEO = OUT / "E40_U01_U16_RUNTIME_REPAIRED_IMMUTABLE_PREFIX_720X1280_V1.mp4"
PCM = OUT / "E40_U01_U16_RUNTIME_REPAIRED_48K_STEREO_PCM_S24_MASTER_V1.wav"
MACHINE = QAD / "E40_U01_U16_RUNTIME_REPAIRED_PREFIX_MACHINE_QA_V1.json"
TIMELINE = QAD / "E40_U01_U16_RUNTIME_REPAIRED_TIMELINE_CONTACT_SHEET_V1.png"
BOUNDARY = QAD / "E40_U01_U16_RUNTIME_REPAIRED_BOUNDARY_CONTACT_SHEET_V1.png"

U = [
 ("U01", "working_assets/e40_assembly_20260814/u01_u16_parallel_prefix_v2/E40_U01_U16_LOCAL_PREVIEW_HARDCUT_720X1280_V2.mp4",192,True,None),
 ("U02", "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u02_v14_agentcut_rights_cleared_assembly_v1/E40_U02_V14_AGENTCUT_RIGHTS_CLEARED_ASSEMBLY_NOT_FINAL.mp4",96,True,"workflow/releases/E40_U02_V14_RIGHTS_CLEARED_AUDIOVISUAL_UNIT_ADMISSION_20260814.json"),
 ("U03", "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u03_v4_local_authority_motion_cadence_repair_v1/E40_U03_V4_LOCAL_AUTHORITY_MOTION_ASSEMBLY_NOT_FINAL.mp4",96,True,"workflow/releases/E40_U03_V4_RIGHTS_CLEARED_AUDIOVISUAL_UNIT_ADMISSION_20260814.json"),
 ("U04", "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u04_v6_local_semantic_mask_repair_v1/E40_U04_V6_LOCAL_SEMANTIC_MASK_REPAIR_CANDIDATE_V1.mp4",96,False,"workflow/releases/E40_U04_V6_SILENT_VISUAL_UNIT_ADMISSION_20260814.json"),
 ("U05", "working_assets/e40_production_20260814/final_runtime_vnext_local_v1/u05_v5_144f_r2/E40-U05-V5-FINAL-RUNTIME-144F.mp4",144,True,"qa/e40_production_20260814/final_runtime_vnext_local_v1/u05_v5_144f_r2/E40_U05_V5_ADMISSION_V1.json"),
 ("U06", "working_assets/e40_production_20260814/u06_v4_local_irregular_frost_exact_dialogue_v1/E40-U06-V4-LOCAL-AUTHORITY-EXACT-DIA005-IRREGULAR-FROST.mp4",168,True,"workflow/releases/E40_U06_V4_RIGHTS_CLEARED_EXACT_DIALOGUE_UNIT_ADMISSION_20260814.json"),
 ("U07", "working_assets/e40_production_20260814/final_runtime_vnext_local_v1/u07_v4_120f_r2/E40-U07-V4-FINAL-RUNTIME-120F.mp4",120,True,"qa/e40_production_20260814/final_runtime_vnext_local_v1/u07_v4_120f_r2/E40_U07_V4_ADMISSION_V1.json"),
 ("U08", "working_assets/e40_production_20260814/final_runtime_vnext_local_v1/u08_v4_120f_r2/E40-U08-V4-FINAL-RUNTIME-120F.mp4",120,True,"qa/e40_production_20260814/final_runtime_vnext_local_v1/u08_v4_120f_r2/E40_U08_V4_ADMISSION_V1.json"),
 ("U09", "working_assets/e40_production_20260814/final_runtime_vnext_local_v1/u09_v4_144f_r2/E40-U09-V4-FINAL-RUNTIME-144F.mp4",144,True,"qa/e40_production_20260814/final_runtime_vnext_local_v1/u09_v4_144f_r2/E40_U09_V4_ADMISSION_V1.json"),
 ("U10", "working_assets/e40_production_20260814/u10_v3_local_authority_hidden_face_fan_lower_exact_dialogue_v1/E40-U10-V3-LOCAL-AUTHORITY-EXACT-DIA009-HIDDEN-FACE-FAN-LOWER.mp4",96,True,"workflow/releases/E40_U10_V3_RIGHTS_CLEARED_EXACT_DIALOGUE_UNIT_ADMISSION_20260814.json"),
 ("U11", "working_assets/e40_production_20260814/u11_v3_local_authority_side_room_cat_alert_silent_v1/E40-U11-V3-LOCAL-AUTHORITY-SIDE-ROOM-CAT-ALERT-SILENT.mp4",96,False,"workflow/releases/E40_U11_V3_SILENT_VISUAL_UNIT_ADMISSION_20260814.json"),
 ("U12", "working_assets/e40_production_20260814/u12_v3_local_authority_exact_dialogue_rubbing_throw_v1/E40-U12-V3-LOCAL-AUTHORITY-EXACT-DIA010-RUBBING-THROW.mp4",168,True,"workflow/releases/E40_U12_V3_RIGHTS_CLEARED_EXACT_DIALOGUE_UNIT_ADMISSION_20260814.json"),
 ("U13", "working_assets/e40_production_20260814/u13_v4_local_authority_half_rise_denial_exact_dialogue_v1/E40-U13-V4-LOCAL-AUTHORITY-EXACT-DIA011-HALF-RISE-DENIAL-PROP-LOCKED.mp4",144,True,"workflow/releases/E40_U13_V4_RIGHTS_CLEARED_EXACT_DIALOGUE_UNIT_ADMISSION_20260814.json"),
 ("U14", "working_assets/e40_production_20260814/u14_v3_local_authority_hand_press_exact_dialogue_v1/E40-U14-V3-LOCAL-AUTHORITY-EXACT-DIA012-HAND-SHADOW-PRESS.mp4",144,True,"workflow/releases/E40_U14_V3_RIGHTS_CLEARED_EXACT_DIALOGUE_UNIT_ADMISSION_20260814.json"),
 ("U15", "working_assets/e40_production_20260814/u15_v6_local_authority_two_dialogue_reveal_organic_fan_shadow_v1/E40-U15-V6-LOCAL-AUTHORITY-EXACT-DIA013-DIA014-REVEAL-ORGANIC-FAN-SHADOW.mp4",168,True,"workflow/releases/E40_U15_V6_TWO_DIALOGUE_UNIT_ADMISSION_20260814.json"),
 ("U16", "working_assets/e40_production_20260814/final_runtime_vnext_local_v1/u16_v5_144f_r2/E40-U16-V5-FINAL-RUNTIME-144F.mp4",144,False,"qa/e40_production_20260814/final_runtime_vnext_local_v1/u16_v5_144f_r2/E40_U16_V5_ADMISSION_V1.json")]

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rel(p): return str(Path(p).relative_to(ROOT))
def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def atomic_json(p,obj):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.'+p.name+'.',dir=p.parent)
    with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(obj,f,ensure_ascii=False,indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,p)

def sheet(video, indices, path, cols=4):
    cap=cv2.VideoCapture(str(video)); thumbs=[]
    for n in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES,n); ok,fr=cap.read()
        if not ok: raise RuntimeError(f'frame {n}')
        cv2.putText(fr,str(n),(18,45),cv2.FONT_HERSHEY_SIMPLEX,1.1,(0,255,255),2,cv2.LINE_AA)
        thumbs.append(cv2.resize(fr,(180,320),interpolation=cv2.INTER_AREA))
    cap.release(); rows=[]
    for i in range(0,len(thumbs),cols):
        row=thumbs[i:i+cols]
        while len(row)<cols: row.append(np.zeros_like(row[0]))
        rows.append(np.hstack(row))
    cv2.imwrite(str(path),np.vstack(rows))

def main():
    if VIDEO.exists() or PCM.exists() or MACHINE.exists(): raise SystemExit('FAIL_CLOSED_OUTPUT_COLLISION')
    OUT.mkdir(parents=True); QAD.mkdir(parents=True)
    sources=[]; failures=[]
    for unit,path,frames,has_audio,admission in U:
        p=ROOT/path
        if not p.exists(): failures.append(f'{unit}_SOURCE_MISSING'); continue
        entry={'unit':unit,'path':path,'sha256':sha(p),'frames':frames,'seconds':frames/24,'has_audio':has_audio}
        if admission:
            ap=ROOT/admission
            entry['admission']=admission; entry['admission_sha256']=sha(ap)
            status=json.loads(ap.read_text()).get('status','')
            entry['admission_status']=status
            if 'PASS' not in status: failures.append(f'{unit}_ADMISSION_NOT_PASS')
        sources.append(entry)
    if failures: raise SystemExit(json.dumps(failures))
    args=[]
    for _,path,_,_,_ in U: args += ['-i',str(ROOT/path)]
    parts=[]; labels=[]
    for i,(unit,_,frames,has_audio,_) in enumerate(U):
        sec=frames/24
        parts.append(f'[{i}:v]trim=start_frame=0:end_frame={frames},setpts=PTS-STARTPTS,fps=24,scale=720:1280:flags=lanczos,format=yuv420p[v{i}]')
        if has_audio: parts.append(f'[{i}:a]atrim=duration={sec:.9f},asetpts=PTS-STARTPTS,aformat=sample_fmts=s32:sample_rates=48000:channel_layouts=stereo,apad=pad_dur={sec:.9f},atrim=duration={sec:.9f}[a{i}]')
        else: parts.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={sec:.9f},asetpts=PTS-STARTPTS[a{i}]')
        labels.append(f'[v{i}][a{i}]')
    parts.append(''.join(labels)+'concat=n=16:v=1:a=1[vcat][acat]')
    parts.append('[acat]asplit=2[aac][pcm]')
    graph=';'.join(parts)
    total=sum(x[2] for x in U); duration=total/24
    cmd=['ffmpeg','-y','-v','error']+args+['-filter_complex',graph,'-map','[vcat]','-map','[aac]','-frames:v',str(total),'-c:v','libx264','-preset','fast','-crf','16','-pix_fmt','yuv420p','-r','24','-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-t',f'{duration:.9f}','-movflags','+faststart',str(VIDEO),'-map','[pcm]','-c:a','pcm_s24le','-ar','48000','-ac','2','-t',f'{duration:.9f}',str(PCM)]
    subprocess.run(cmd,check=True)
    decode=subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(VIDEO),'-f','null','-'],capture_output=True,text=True)
    probe=json.loads(subprocess.run(['ffprobe','-v','error','-count_frames','-show_entries','format=duration:stream=codec_type,codec_name,pix_fmt,width,height,r_frame_rate,nb_read_frames,sample_rate,channels','-of','json',str(VIDEO)],capture_output=True,text=True,check=True).stdout)
    vs=next(x for x in probe['streams'] if x['codec_type']=='video'); au=next(x for x in probe['streams'] if x['codec_type']=='audio')
    decoded=int(vs['nb_read_frames'])
    cuts=[]; cursor=0; mids=[]
    for unit,_,frames,_,_ in U:
        mids.append(cursor+frames//2); cursor+=frames
        if cursor<total: cuts += [cursor-1,cursor]
    sheet(VIDEO,mids,TIMELINE,4); sheet(VIDEO,cuts,BOUNDARY,4)
    failures=[]
    if decode.returncode: failures.append('FULL_DECODE')
    if decoded!=total: failures.append('FRAME_COUNT')
    if (vs['width'],vs['height'],vs['r_frame_rate'],vs['pix_fmt'])!=(720,1280,'24/1','yuv420p'): failures.append('VIDEO_FORMAT')
    if (au.get('sample_rate'),au.get('channels'))!=('48000',2): failures.append('AUDIO_FORMAT')
    result={'schema':'qingshan.e40.u01_u16.runtime_repaired_prefix.machine_qa.v1','created_at':now(),'status':'PASS' if not failures else 'FAIL','failures':failures,'canonical_order':[x[0] for x in U],'sources':sources,'replacement_units':['U05_V5','U07_V4','U08_V4','U09_V4','U16_V5'],'output':{'path':rel(VIDEO),'sha256':sha(VIDEO),'bytes':VIDEO.stat().st_size,'decoded_frames':decoded,'duration_seconds':float(probe['format']['duration'])},'video':{'codec':vs['codec_name'],'pixel_format':vs['pix_fmt'],'width':vs['width'],'height':vs['height'],'fps':vs['r_frame_rate']},'audio':{'codec':au['codec_name'],'sample_rate':int(au['sample_rate']),'channels':au['channels'],'pcm_master_path':rel(PCM),'pcm_master_sha256':sha(PCM),'pcm_master_bytes':PCM.stat().st_size,'retime_filters_used':[],'normalization_only':['atrim','asetpts','aformat','apad','anullsrc_for_silent_units']},'full_decode':'PASS' if decode.returncode==0 else 'FAIL','timeline_contact_sheet':{'path':rel(TIMELINE),'sha256':sha(TIMELINE)},'boundary_contact_sheet':{'path':rel(BOUNDARY),'sha256':sha(BOUNDARY)},'provider_posts':0,'provider_queries':0,'paid_credits':0}
    atomic_json(MACHINE,result)
    atomic_json(QAD/'E40_U01_U16_RUNTIME_REPAIRED_HUMAN_QA_V1.json',{'schema':'qingshan.e40.u01_u16.runtime_repaired_prefix.human_qa.v1','status':'QA_PENDING_HUMAN','checks':{'canonical_order':None,'all_15_boundaries':None,'identity_continuity':None,'new_artifacts':None,'runtime_repaired_units':None}})
    atomic_json(QAD/'E40_U01_U16_RUNTIME_REPAIRED_IMMUTABLE_REGISTRATION_V1.json',{'schema':'qingshan.e40.u01_u16.runtime_repaired_prefix.immutable_registration.v1','status':'QA_PENDING_HUMAN','machine_qa':result['status'],'prefix_sha256':result['output']['sha256'],'may_bind':False})
    print(json.dumps({'status':result['status'],'frames':decoded,'seconds':result['output']['duration_seconds'],'sha256':result['output']['sha256'],'pcm_sha256':result['audio']['pcm_master_sha256']}))
    return 0 if not failures else 2

if __name__=='__main__': raise SystemExit(main())
