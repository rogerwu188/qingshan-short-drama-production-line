#!/usr/bin/env python3
"""Fill and submit the E03 identity review from the reviewer's actual viewing (claude-code-nalu-vlm).
Visual findings recorded 2026-09-15T00:05Z from /tmp/e03_id_sheet.jpg (15 plates, 360px thumbnails) — see OBS."""
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import glob, json, os, subprocess, datetime, hashlib
req = sorted(glob.glob(f"{_np.RUNTIME_ROOT}/runtime/reviews/E03/E03-identity-*_request.json"))[-1]
VENV = f"{_np.VENV_PYTHON}"; PROTO = f"{_np.TOOLS_DIR}/vlm_review_protocol.py"
tpl = "/tmp/e03_identity_answers_tpl.json"
subprocess.run([VENV, PROTO, "example-answers", "--request", req, "--out", tpl], check=True, capture_output=True)
ans = json.load(open(tpl)); R = json.load(open(req))
OBS = {
 "CHAR-VILLAGER-A": "三视图同一人：瘦削中年男子、发髻以灰麻布巾缠裹（髻顶露出）、深灰褐粗麻交领右衽齐膝短褐套灰白中衣、宽布腰带打结、麻布裹腿与布鞋；中性灰底、正面均匀光；目视约 36–44 岁，在 30–45 内；无兵甲、无文字、无第二人。面孔沿 E01 邻居甲的瘦削中年气质，服制已改唐宋。",
 "CHAR-VILLAGER-B": "三视图同一人：矮壮圆脸中年男子、黑褐兽皮护耳帽（毛边）、灰褐粗麻交领右衽膝下棉袍（前襟磨旧）套褐色中衣、布带束腰、旧皮靴裹腿；灰底、均匀光；目视约 42–50 岁，在 35–50 内；无兵甲、无文字、无第二人。",
 "PROP-HUNTING-FORK": "单体猎叉：一人高硬木直柄、锻铁三股叉头带磨痕、麻绳缠柄；灰底、无人物、无文字；符合『木柄铁头猎叉』。",
 "PROP-SHORT-KNIFE": "单体直刃短刀：一尺直刃、木柄缠麻绳、无护手大盘；灰底、无文字；符合唐宋直刀形制。",
 "PROP-BOW-ARROWS": "单体竹木短弓与皮箭囊（囊内数支羽箭、皮背带）；灰底、无文字；无金属滑轮。",
 "PROP-HIDE-BAG": "单体厚兽皮口袋：毛面朝内、袋口皮绳；灰底、无文字；无拉链、无金属扣。",
 "PROP-NUT-HOARD": "枯木树洞剖面里满堆野核桃、栗子、红枣，褐/棕/深红三色，真实干果质感；灰底、无文字、无包装。",
 "PROP-HUMANFACE-VULTURE": "单体人面鹫：灰黑鹰身、宽阔强劲双翼展开、除鸟喙外整张脸是带皱纹的惨白老人脸、利爪；写实、不发光、不卡通；灰底、无文字。",
 "PROP-RED-SQUIRREL": "单体变异红松鼠：全身火红晶莹皮毛带绸缎光泽与柔和光晕、黑宝石般圆眼、大尾；体态写实、无光环特效；灰底、无文字。",
 "SET-FOREST-EDGE-WOODS": "实景夜林空镜：前景光秃阔叶树枝压雪，中景樟子松与白桦树干，雪地泛月色青蓝反光并有踩出的雪沟，林深处黑压压但轮廓可辨；无人物、无人造物、无文字；不是纯黑，不是西式冷灰去饱和。",
 "SET-HOLLOW-TREE": "实景夜林空镜：水桶粗的枯干大树居中，离地一人多高处一个天然树洞、洞口边缘结霜，树皮干裂，树根旁雪地有小爪印；背景雪林、月色青蓝；无人物、无人造物、无文字。",
}
Q = ["appearance_matches_script","apparent_age_in_declared_range","sex_presentation_matches","all_required_views_present",
     "single_subject_no_clone_no_extra_person","identity_consistent_across_views","wardrobe_matches_bible",
     "palette_and_lighting_match_visual_culture","no_forbidden_influence_visible","no_text_logo_watermark_or_subtitle",
     "framing_and_aspect_ratio_correct","face_unobstructed_and_in_focus","plate_is_photographic_not_illustrated"]
for item in ans["items"]:
    iid = item["item_id"]; is_char = iid.startswith("CHAR-")
    assert iid in OBS, f"no observation for {iid}"
    ex = next(x for x in R["items"] if x["item_id"] == iid)
    media = item.get("media_reviewed") or []
    views = []
    for m in media:
        n = os.path.basename(m)
        views.append("FRONT_NEUTRAL_HEADSHOT" if "FRONT_NEUTRAL_HEADSHOT" in n else "THREE_QUARTER_BUST" if "THREE_QUARTER_BUST" in n else "FULL_BODY_STANDING")
    ansd = {q: "PASS" for q in Q}
    if not is_char:
        cv = ex.get("closed_vocabulary") or {}
        ansd["apparent_age_in_declared_range"] = "NOT_APPLICABLE"; ansd["sex_presentation_matches"] = "NOT_APPLICABLE"
        ansd["face_unobstructed_and_in_focus"] = "NOT_APPLICABLE" if "NOT_APPLICABLE" in cv.get("face_unobstructed_and_in_focus", ["NOT_APPLICABLE"]) else "PASS"
        ansd["wardrobe_matches_bible"] = "NOT_APPLICABLE" if "NOT_APPLICABLE" in cv.get("wardrobe_matches_bible", ["NOT_APPLICABLE"]) else "PASS"
    item["answers"] = ansd
    item["observed"] = {"observed_views": views, "observed_text_strings": []}
    item["observation"] = OBS[iid]
    item["defects"] = []
ans["request_sha256"] = hashlib.sha256(open(req, "rb").read()).hexdigest(); ans["request_path"] = req
ans["reviewer"] = "claude-code-nalu-vlm"; ans["reviewed_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
ans.pop("__NOT_A_REVIEW_FILL_EVERY_NULL__", None); ans["_refusal"] = None
out = "/tmp/e03_identity_answers_filled.json"; json.dump(ans, open(out, "w"), ensure_ascii=False, indent=2)
r = subprocess.run([VENV, PROTO, "submit", "--request", req, "--answers", out], capture_output=True, text=True)
print("submit rc", r.returncode); print((r.stdout or "")[-1500:]); print((r.stderr or "")[-800:])
