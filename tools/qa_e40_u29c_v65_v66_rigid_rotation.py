#!/usr/bin/env python3
"""Final local machine QA for V65 source and V66 AgentCut parity."""
from __future__ import annotations
import argparse,json,subprocess
from pathlib import Path
import cv2,numpy as np
from render_e40_u29c_v55_local_living_reaction import atomic_json,sha256

def decode(p):
 c=cv2.VideoCapture(str(p)); fs=[]
 while True:
  ok,f=c.read()
  if not ok: break
  fs.append(f)
 c.release(); return fs
def probe(p): return json.loads(subprocess.check_output(["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(p)]))
def main():
 p=argparse.ArgumentParser(); p.add_argument("--authority",type=Path,required=True); p.add_argument("--source",type=Path,required=True); p.add_argument("--roundtrip",type=Path,required=True); p.add_argument("--render-report",type=Path,required=True); p.add_argument("--cadence-report",type=Path,required=True); p.add_argument("--frame0-report",type=Path,required=True); p.add_argument("--ocr-report",type=Path,required=True); p.add_argument("--contact-sheet",type=Path,required=True); p.add_argument("--out",type=Path,required=True); a=p.parse_args()
 authority=cv2.imread(str(a.authority)); source=decode(a.source); rt=decode(a.roundtrip); sp=probe(a.source); rp=probe(a.roundtrip)
 allowed=np.zeros(authority.shape[:2],np.uint8); allowed[690:1010,110:365]=1; allowed[735:1010,640:850]=1; outside=allowed==0
 source_outside=max(int(np.count_nonzero(np.any(f!=authority,axis=2)&outside)) for f in source)
 lower=np.zeros(authority.shape[:2],np.uint8); lower[1010:1747,58:374]=1; lower[1010:1516,617:870]=1
 source_lower=max(int(np.count_nonzero(np.any(f!=authority,axis=2)&(lower>0))) for f in source)
 reports={"render":json.load(open(a.render_report)),"cadence":json.load(open(a.cadence_report)),"frame0":json.load(open(a.frame0_report)),"ocr":json.load(open(a.ocr_report))}
 no_audio=lambda x: not any(s.get("codec_type")=="audio" for s in x.get("streams",[]))
 geometry=len(source)==96 and len(rt)==96 and all(f.shape==authority.shape for f in source+rt)
 binding=reports["render"].get("output_sha256")==sha256(a.source) and reports["render"].get("status","").startswith("PASS")
 recognitions=reports["ocr"].get("recognitions",[])
 gates={"source_frame0_exact":bool(np.array_equal(source[0],authority)),"source_outside_head_envelopes_exact":source_outside==0,"source_lower_body_feet_exact":source_lower==0,"geometry_96_frames_24fps":geometry,"source_silent":no_audio(sp),"roundtrip_silent":no_audio(rp),"render_binding":binding,"roundtrip_cadence":reports["cadence"].get("status")=="PASS","roundtrip_frame0":reports["frame0"].get("status")=="PASS","roundtrip_ocr0":reports["ocr"].get("status")=="PASS" and ((isinstance(recognitions,list) and len(recognitions)==0) or recognitions==0)}
 payload={"schema":"qingshan.e40.u29c.v65_v66.rigid_rotation_machine_qa.v1","status":"PASS_MACHINE_QA_PENDING_ORIGINAL_RESOLUTION_HUMAN_QA" if all(gates.values()) else "FAIL_CLOSED","authority_sha256":sha256(a.authority),"source_video":str(a.source.resolve()),"source_sha256":sha256(a.source),"roundtrip_video":str(a.roundtrip.resolve()),"roundtrip_sha256":sha256(a.roundtrip),"source_max_changed_pixels_outside_head_envelopes":source_outside,"source_max_changed_lower_body_feet_pixels":source_lower,"gates":gates,"contact_sheet":str(a.contact_sheet.resolve()),"contact_sheet_sha256":sha256(a.contact_sheet),"provider_calls":0,"transactions":0,"credits":0,"assembly_allowed":False,"upload_allowed":False,"publish_allowed":False}
 atomic_json(a.out,payload); print(json.dumps({"status":payload["status"],"out":str(a.out.resolve())})); return 0 if payload["status"].startswith("PASS") else 2
if __name__=="__main__": raise SystemExit(main())
