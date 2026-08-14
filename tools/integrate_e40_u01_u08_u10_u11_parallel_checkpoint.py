#!/usr/bin/env python3
"""Persist U01-U08 assembly and U10/U11 parallel preproduction artifacts."""
from __future__ import annotations
import hashlib,json,os,tempfile
from datetime import datetime,timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1]; W=R/"workflow/work_queue.json"; X=R/"workflow/CODEX_TO_CLAUDE.md"
P=R/"working_assets/e40_assembly_20260814/u01_u08_parallel_prefix_v1/E40_U01_U08_LOCAL_PREVIEW_HARDCUT_720X1280_V1.mp4"; PQ=R/"qa/e40_assembly_20260814/u01_u08_parallel_prefix_v1/E40_U01_U08_LOCAL_PREFIX_MACHINE_AND_HUMAN_QA_V1.json"
F10=R/"working_assets/e40_preproduction_20260814/u10_parallel_curtain_shadow_fan_lower_v1/E40_U10_PARALLEL_CANDIDATE_V3_EXACT_START_FRAME_720X1280.png"; H10=R/"qa/e40_preproduction_20260814/u10_parallel_curtain_shadow_fan_lower_v1/E40_U10_PARALLEL_CANDIDATE_V3_ORIGINAL_RES_HUMAN_QA_V1.json"; O10=R/"qa/e40_preproduction_20260814/u10_parallel_curtain_shadow_fan_lower_v1/E40_U10_PARALLEL_CANDIDATE_V3_OCR_AUDIT_V1.json"; R10=R/"qa/e40_preproduction_20260814/u10_parallel_curtain_shadow_fan_lower_v1/E40_U10_PARALLEL_PREPRODUCTION_SHA_RECEIPT_V1.json"
AU10=R/"working_assets/e40_production_20260814/u10_parallel_kokoro_exact_audio_candidates_v1/E40-DIA009_zf_001_speed1p4_normalized48k.wav"; AQ10=R/"qa/e40_production_20260814/u10_parallel_kokoro_exact_audio_candidates_v1/E40_U10_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"; AR10=R/"qa/e40_preproduction_20260814/u10_parallel_kokoro_exact_audio_candidates_v1/E40_U10_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
F11=R/"working_assets/e40_preproduction_20260814/u11_parallel_wuyun_side_room_alert_v1/E40_U11_PARALLEL_CANDIDATE_V2_EXACT_START_FRAME_720X1280.png"; H11=R/"qa/e40_preproduction_20260814/u11_parallel_wuyun_side_room_alert_v1/E40_U11_PARALLEL_CANDIDATE_V2_ORIGINAL_RES_HUMAN_QA_V1.json"; O11=R/"qa/e40_preproduction_20260814/u11_parallel_wuyun_side_room_alert_v1/E40_U11_PARALLEL_CANDIDATE_V2_OCR_AUDIT_V1.json"; R11=R/"qa/e40_preproduction_20260814/u11_parallel_wuyun_side_room_alert_v1/E40_U11_PARALLEL_PREPRODUCTION_SHA_RECEIPT_V1.json"; N11=R/"qa/e40_production_20260814/u11_parallel_no_dialogue_audio_gate_v1/E40_U11_PARALLEL_NO_DIALOGUE_AUDIO_MACHINE_QA_V1.json"
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def rel(p): return str(p.relative_to(R))
def write(p,x):
 b=(json.dumps(x,ensure_ascii=False,indent=2)+"\n").encode(); fd,t=tempfile.mkstemp(prefix=f".{p.name}.",dir=p.parent)
 try:
  with os.fdopen(fd,"wb") as f:f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(t,p)
 except Exception:Path(t).unlink(missing_ok=True);raise
def main():
 fs=(P,PQ,F10,H10,O10,R10,AU10,AQ10,AR10,F11,H11,O11,R11,N11)
 for p in fs:
  if not p.is_file():raise SystemExit(f"FAIL_MISSING:{p}")
 w=json.loads(W.read_text()); w["latest_e40_u01_u08_assembly_prefix"]={"status":"PASS_IMMUTABLE_PREFIX_U01_U08","preview":rel(P),"preview_sha256":sha(P),"duration_seconds":39.166667,"qa":rel(PQ),"qa_sha256":sha(PQ),"next_action":"Append U09 only after U09 unit admission."}
 w["latest_e40_u10_parallel_preproduction"]={"status":"PASS_FRAME_HUMAN92_OCR0_AUDIO_EXACT_RIGHTS_CLEAR_U09_TAIL_BINDING_PENDING","canonical_line":"……你倒看得清楚。","speaker":"云妃","frame":rel(F10),"frame_sha256":sha(F10),"human_qa":rel(H10),"human_qa_sha256":sha(H10),"ocr_qa":rel(O10),"ocr_qa_sha256":sha(O10),"asset_receipt":rel(R10),"asset_receipt_sha256":sha(R10),"selected_audio":rel(AU10),"selected_audio_sha256":sha(AU10),"audio_qa":rel(AQ10),"audio_qa_sha256":sha(AQ10),"rights_evidence":rel(AR10),"rights_evidence_sha256":sha(AR10),"provider_posts":0,"credits":0,"blocked_by":"U09_ADMITTED_TAIL_TO_U10_FRAME_CONTINUITY_PENDING","next_action":"After U09 admission bind its tail and admit U10 only on continuity PASS."}
 w["latest_e40_u11_parallel_preproduction"]={"status":"PASS_FRAME_HUMAN91_OCR0_SILENT_VISUAL_NO_DIALOGUE_U10_TAIL_BINDING_PENDING","dialogue_transport":"SILENT_VISUAL","frame":rel(F11),"frame_sha256":sha(F11),"human_qa":rel(H11),"human_qa_sha256":sha(H11),"ocr_qa":rel(O11),"ocr_qa_sha256":sha(O11),"asset_receipt":rel(R11),"asset_receipt_sha256":sha(R11),"no_dialogue_machine_gate":rel(N11),"no_dialogue_machine_gate_sha256":sha(N11),"provider_posts":0,"credits":0,"blocked_by":"U10_ADMITTED_TAIL_TO_U11_FRAME_CONTINUITY_PENDING","next_action":"After U10 admission bind its tail; preserve ambient-only audio and do not attach U12 DIA010."};write(W,w)
 n=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
 with X.open("a",encoding="utf-8") as f:f.write(f"\n\n## E40 checkpoint {n} — U01-U08 prefix and U10/U11 parallel assets persisted\n\n- U01-U08 prefix `{rel(P)}` SHA=`{sha(P)}` is 39.166667s and full decode PASS.\n- U10 frame/audio preproduction passed HUMAN92/OCR0, exact DIA009 ASR=1.0 and release-clear `zf_001`; frame SHA=`{sha(F10)}`, audio SHA=`{sha(AU10)}`. Only U09-tail continuity remains.\n- U11 frame SHA=`{sha(F11)}` passed HUMAN91/OCR0. Canonical is `SILENT_VISUAL` with zero dialogue; no-dialogue gate SHA=`{sha(N11)}` prevents accidental U12 DIA010 binding. Only U10-tail continuity remains. Provider posts/credits=0; active main chain remains U09 local render.\n");f.flush();os.fsync(f.fileno())
 print(json.dumps({"status":"PASS_U01_U08_U10_U11_CHECKPOINT_PERSISTED","prefix_sha256":sha(P),"u10_frame_sha256":sha(F10),"u11_frame_sha256":sha(F11)},ensure_ascii=False));return 0
if __name__=="__main__":raise SystemExit(main())
