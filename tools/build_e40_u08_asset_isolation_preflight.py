#!/usr/bin/env python3
"""Build U08 zero-credit source-isolation evidence; not a start frame."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageOps
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/"working_assets/e40_preproduction_20260808/u08_asset_isolation_preflight_v1"
SCRIPT=ROOT/"workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"; CM=ROOT/"workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
PROMPT=ROOT/"workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u01_u16_prompt_precompile_v1/prompts/E40-U08-STANDARD-SEEDANCE2-PROMPT-V1.txt"
BINDING=ROOT/"workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/reference_binding/E40_INDEPENDENT_SHOT_REFERENCE_BINDING_MATRIX_V1.json"
HALL=ROOT/"working_assets/e40_preproduction_20260808/scene_assets/SCENE-E40-13-HALL-CURTAIN-AXIS_6ca121ab-f635-4bc4-9f21-8708c58e7cfe.png"; WARDROBE=ROOT/"assets/reference/e40_wardrobe_variants_20260808/characters/CHAR-chenji-age20-plain-white-fine-linen-turnaround-v1-20260808.png"; YUNFEI=ROOT/"ref_images/female_yunfei_ref_20260703.jpg"
EXPECTED={SCRIPT:"140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",CM:"773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",PROMPT:"51a1847ba78d3c25d23a9e2d90a638d9c19d8a3802a45d32a5b059fd520f7a42",BINDING:"14881afec26242067f57fd1e5560f75a3ea3b90ef6515341c91b94610ea4ad34",HALL:"affcdf75edd4719b69b3fefad3cffb271c87794fdfc0cba029d8d26af6654b88",WARDROBE:"f0be95313bbfc29f09b702f31e6b83fef52035117aa41dc551f3c3f02831d021",YUNFEI:"be2c351d58946e8dac12260636ed79b4e76812064fe129ec051bfe434161ad28"}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rel(p):return str(p.relative_to(ROOT))
def ft(n,b=False):
 p=Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if b else "/System/Library/Fonts/Supplemental/Arial.ttf");return ImageFont.truetype(str(p),n) if p.exists() else ImageFont.load_default()
def panel(p,wh):return ImageOps.fit(ImageOps.exif_transpose(Image.open(p)).convert("RGB"),wh,method=Image.Resampling.LANCZOS)
def main():
 for p,e in EXPECTED.items():
  if sha(p)!=e:raise SystemExit(f"SHA mismatch {rel(p)}")
 OUT.mkdir(parents=True,exist_ok=True); im=Image.new("RGB",(1440,2560),(15,18,22));d=ImageDraw.Draw(im);d.rectangle((0,0,1440,180),fill=(93,17,23));d.text((50,32),"E40 U08 SOURCE ISOLATION",font=ft(54,True),fill="white");d.text((50,110),"NOT A START FRAME - FAIL CLOSED",font=ft(31,True),fill=(255,195,195))
 items=[(HALL,(50,230,700,1510),"HALL + CURTAIN AUTHORITY"),(WARDROBE,(740,230,1390,1040),"CHENJI WHITE - STUDIO ONLY"),(YUNFEI,(740,1110,1390,1920),"YUNFEI ID ONLY - MODERN / NO FAN")]
 for p,(x1,y1,x2,y2),lab in items:
  im.paste(panel(p,(x2-x1,y2-y1)),(x1,y1));d.rectangle((x1,y1,x2,y2),outline=(220,225,232),width=4);d.rectangle((x1,y2-72,x2,y2),fill=(5,7,9));d.text((x1+16,y2-55),lab,font=ft(23,True),fill="white")
 d.rectangle((50,1600,700,2050),fill=(25,28,33),outline=(235,92,98),width=5);d.text((75,1630),"MISSING FAN PERFORMANCE",font=ft(31,True),fill=(255,155,155));ys=1705
 for s in ["one period round fan", "Yunfei hand/wrist owner", "half-closing start state", "curtain-contact shadow", "same candle direction"]:d.text((85,ys),s,font=ft(26),fill=(238,240,244));ys+=62
 d.rectangle((50,2130,1390,2495),fill=(22,25,30),outline=(235,92,98),width=5);d.text((80,2160),"NO NATURAL UNIFIED CAMERA/LIGHT SOURCE",font=ft(36,True),fill=(255,155,155));d.text((90,2240),"Visible Chenji speaking face + locked gaze + curtain/fan reaction",font=ft(28),fill=(238,240,244));d.text((90,2305),"cannot be assembled from studio/modern identity cards without collage.",font=ft(28),fill=(238,240,244));d.text((90,2425),"Candidate: NONE | Paid submit: BLOCKED | Credits: 0",font=ft(28,True),fill=(255,220,175))
 board=OUT/"E40_U08_SOURCE_ISOLATION_BOARD_NOT_A_START_FRAME_V1.png";im.save(board)
 m={"schema":"qingshan.e40.asset_isolation_preflight.v1","episode":"E40","unit":"U08","status":"FAIL_CLOSED_NO_NATURAL_CHENJI_CURTAIN_FAN_REACTION_SOURCE","candidate":None,"candidate_admitted":False,"warning":"Board is QA evidence only, never a start frame.","canonical":{"script_sha256":sha(SCRIPT),"manifest_sha256":sha(CM),"prompt_sha256":sha(PROMPT),"reference_binding_sha256":sha(BINDING)},"isolated_sources":[{"role":"HALL_CURTAIN_AUTHORITY","path":rel(HALL),"sha256":sha(HALL)},{"role":"CHENJI_WHITE_STUDIO_ONLY","path":rel(WARDROBE),"sha256":sha(WARDROBE)},{"role":"YUNFEI_IDENTITY_ONLY_MODERN_NO_PERIOD_WARDROBE_OR_FAN","path":rel(YUNFEI),"sha256":sha(YUNFEI)}],"required_cooccurrence":{"chenji":"white-robed age20, visible speaking face, gaze locked to curtain","fan":{"owner":"Yunfei","count":1,"start":"half-closing","transfer":"NONE"},"reaction":"Yunfei wrist/fan continues closing behind curtain; Baili/observers remain alive"},"feasibility":{"natural_unified_source_found":False,"period_fan_owner_source":"FAIL_MISSING","curtain_shadow_contact":"FAIL_MISSING","visible_chenji_lips_and_gaze":"FAIL_MISSING","vector_fan_shadow_without_owner":"FORBIDDEN_FALSE_EVIDENCE","cross_paste":"FORBIDDEN_U04_FAILURE_PATTERN","overall":"FAIL_CLOSED"},"outputs":{"isolation_board_not_a_start_frame":{"path":rel(board),"sha256":sha(board)}},"credits":{"pay":0,"refund":0,"net":0},"paid_submission":False,"next_action":"Acquire one natural cinematic U08 performance source with white-robed Chenji and a period Yunfei-owned half-closing fan shadow in the admitted hall; then original-image human QA >=80."}
 mp=OUT/"E40_U08_ASSET_ISOLATION_PREFLIGHT_MANIFEST_V1.json";mp.write_text(json.dumps(m,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(json.dumps({"status":m["status"],"board":rel(board),"board_sha256":sha(board),"manifest":rel(mp),"manifest_sha256":sha(mp),"credits":m["credits"]},ensure_ascii=False));return 0
if __name__=="__main__":raise SystemExit(main())
