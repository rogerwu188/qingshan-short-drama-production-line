#!/usr/bin/env python3
"""Build U07 zero-credit source-isolation evidence; never a start frame."""

from __future__ import annotations
import hashlib, json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "working_assets/e40_preproduction_20260808/u07_asset_isolation_preflight_v1"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
CM = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
PROMPT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u01_u16_prompt_precompile_v1/prompts/E40-U07-STANDARD-SEEDANCE2-PROMPT-V1.txt"
BINDING = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/reference_binding/E40_INDEPENDENT_SHOT_REFERENCE_BINDING_MATRIX_V1.json"
HALL = ROOT / "working_assets/e40_preproduction_20260808/scene_assets/SCENE-E40-13-HALL-CURTAIN-AXIS_6ca121ab-f635-4bc4-9f21-8708c58e7cfe.png"
WARDROBE = ROOT / "assets/reference/e40_wardrobe_variants_20260808/characters/CHAR-chenji-age20-plain-white-fine-linen-turnaround-v1-20260808.png"
HAND = ROOT / "working_assets/e39_keyframes_v3/candidates/E39_E39-U02-A1-STILL-R3_144cbcab-86eb-4ff1-856f-0123e29d47f5.png"
U06 = ROOT / "working_assets/e40_preproduction_20260808/u06_table_frost_isolation_v1/E40_U06_TABLE_FROST_COMPONENT_NOT_A_START_FRAME_V1.png"
EXPECTED = {SCRIPT:"140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",CM:"773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",PROMPT:"eedb0d0de592c7833b9d105e7a5be4833ce085037a76ea4a28e38ff197c1f860",BINDING:"14881afec26242067f57fd1e5560f75a3ea3b90ef6515341c91b94610ea4ad34",HALL:"affcdf75edd4719b69b3fefad3cffb271c87794fdfc0cba029d8d26af6654b88",WARDROBE:"f0be95313bbfc29f09b702f31e6b83fef52035117aa41dc551f3c3f02831d021",HAND:"5b3ad2337e400653fb3067557f438fa6c9cb7295c35398774b2a494d12760293",U06:"85f0c857bac4ebd1f4a15063daaea9585cdac283b95c4172c9cea1bef096b055"}

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def rel(p): return str(p.relative_to(ROOT))
def ft(n,b=False):
    p=Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if b else "/System/Library/Fonts/Supplemental/Arial.ttf")
    return ImageFont.truetype(str(p),n) if p.exists() else ImageFont.load_default()
def panel(p, wh): return ImageOps.fit(Image.open(p).convert("RGB"),wh,method=Image.Resampling.LANCZOS)

def main():
    for p,e in EXPECTED.items():
        if sha(p)!=e: raise SystemExit(f"SHA mismatch {rel(p)}")
    OUT.mkdir(parents=True,exist_ok=True)
    im=Image.new("RGB",(1440,2560),(15,18,22)); d=ImageDraw.Draw(im)
    d.rectangle((0,0,1440,180),fill=(93,17,23)); d.text((50,32),"E40 U07 SOURCE ISOLATION",font=ft(54,True),fill="white"); d.text((50,110),"NOT A START FRAME - FAIL CLOSED",font=ft(31,True),fill=(255,195,195))
    items=[(HALL,(50,230,700,1030),"HALL/TABLE"),(HAND,(740,230,1390,1030),"ADMITTED HAND - WRONG CAMERA/ROBE"),(U06,(50,1100,700,2050),"FROST PLATE - CONTACT FAILED"),(WARDROBE,(740,1100,1390,2050),"WHITE WARDROBE - STUDIO ONLY")]
    for p,(x1,y1,x2,y2),lab in items:
        im.paste(panel(p,(x2-x1,y2-y1)),(x1,y1)); d.rectangle((x1,y1,x2,y2),outline=(220,225,232),width=4); d.rectangle((x1,y2-70,x2,y2),fill=(5,7,9)); d.text((x1+16,y2-54),lab,font=ft(24,True),fill="white")
    d.rectangle((50,2140,1390,2495),fill=(22,25,30),outline=(235,92,98),width=5)
    d.text((80,2170),"MISSING ONE NATURAL COHERENT SOURCE",font=ft(36,True),fill=(255,155,155))
    lines=["white-robed Chenji + moving fingertip + four physical frost marks", "empty fifth position + readable tabletop plane + visible speaking face", "Baili/curtain reactions in the same camera and candle light"]
    y=2240
    for s in lines: d.text((90,y),s,font=ft(27),fill=(238,240,244)); y+=62
    d.text((90,2430),"Candidate: NONE | Paid submit: BLOCKED | Credits: 0",font=ft(27,True),fill=(255,220,175))
    board=OUT/"E40_U07_SOURCE_ISOLATION_BOARD_NOT_A_START_FRAME_V1.png"; im.save(board)
    m={"schema":"qingshan.e40.asset_isolation_preflight.v1","episode":"E40","unit":"U07","status":"FAIL_CLOSED_NO_NATURAL_UNIFIED_ACTION_SOURCE","candidate":None,"candidate_admitted":False,"warning":"Board is QA evidence only, never a start frame.","canonical":{"script_sha256":sha(SCRIPT),"manifest_sha256":sha(CM),"prompt_sha256":sha(PROMPT),"reference_binding_sha256":sha(BINDING)},"isolated_sources":[{"role":"HALL_TABLE","path":rel(HALL),"sha256":sha(HALL)},{"role":"WHITE_WARDROBE_STUDIO_ONLY","path":rel(WARDROBE),"sha256":sha(WARDROBE)},{"role":"ADMITTED_HAND_TOPOLOGY_WRONG_ROBE_CAMERA","path":rel(HAND),"sha256":sha(HAND)},{"role":"U06_FROST_COMPONENT_SURFACE_CONTACT_FAILED","path":rel(U06),"sha256":sha(U06)}],"required_cooccurrence":{"existing_frost_marks":{"owner":"Chenji","count":4},"fifth_mark":{"owner":"NONE","count":0,"must_remain_absent":True},"start_state":"Chenji fingertip moving toward empty fifth position, hovering without landing","visible_performance":"white-robed age20 Chenji speaking face, fingertip and gaze; Baili blink and curtain/fan living response"},"feasibility":{"natural_unified_source_found":False,"table_surface_contact":"FAIL_FROM_U06_ORIGINAL_VIEW","finger_owner":"FAIL_NO_MATCHING_SOURCE","visible_lip_sync_face":"FAIL_NO_MATCHING_SOURCE","collage_workaround":"FORBIDDEN_U04_FAILURE_PATTERN","overall":"FAIL_CLOSED"},"outputs":{"isolation_board_not_a_start_frame":{"path":rel(board),"sha256":sha(board)}},"credits":{"pay":0,"refund":0,"net":0},"paid_submission":False,"next_action":"Acquire one natural cinematic U07 performance source in the admitted hall geometry; then original-image human QA >=80."}
    mp=OUT/"E40_U07_ASSET_ISOLATION_PREFLIGHT_MANIFEST_V1.json"; mp.write_text(json.dumps(m,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":m["status"],"board":rel(board),"board_sha256":sha(board),"manifest":rel(mp),"manifest_sha256":sha(mp),"credits":m["credits"]},ensure_ascii=False)); return 0
if __name__=="__main__": raise SystemExit(main())
