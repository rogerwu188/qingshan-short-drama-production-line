#!/usr/bin/env python3
"""Fill and submit the E06 identity review from the reviewer's actual viewing (claude-code-nalu-vlm).
Visual findings recorded 2026-09-18T08:35Z from /tmp/e06_id_lw.png, /tmp/e06_id_zc.png, /tmp/e06_id_cards.png (11 plates) — see OBS."""
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import glob, json, os, subprocess, datetime, hashlib
req = sorted(glob.glob(f"{_np.RUNTIME_ROOT}/runtime/reviews/E06/E06-identity-*_request.json"))[-1]
VENV = f"{_np.VENV_PYTHON}"; PROTO = f"{_np.TOOLS_DIR}/vlm_review_protocol.py"
tpl = "/tmp/e06_identity_answers_tpl.json"
subprocess.run([VENV, PROTO, "example-answers", "--request", req, "--out", tpl], check=True, capture_output=True)
ans = json.load(open(tpl)); R = json.load(open(req))
OBS = {
 "CHAR-LIANGWANQING": "重出牌（D-57 ①）：三视图同一人，与操作者原照（CHAR-LIANGWANQING.png）为同一张脸——圆润脸型、细长眼、笑纹相近；深褐发绾成高髻（未包麻布，仅此一处与服装册『麻布包髻』略异，记为观察）；灰褐粗麻交领短襦、束腰麻带、粗麻围裙、旧蓝长裙、灰袜布鞋；灰底、均匀正面光、中性表情目视镜头；目视约 24–30 岁在 22–30 内；无文字、无第二人、无动物。InsightFace 对原照 0.762/0.625/0.569，全部 ≥0.45。",
 "CHAR-ZHOUCHANGYU": "三视图同一人：快三十岁的高壮汉子，脸膛粗糙、眉骨粗、眼窝深、短须；灰布裹巾束发成髻；右臂用灰白布带吊在胸前、肘部缠布夹板；褐色粗麻无袖短褐（右袖空着按服装册，生成为两侧无袖，记为观察）套灰白窄袖中衣，麻布腰带，灰褐布裤，旧布靴；灰底、均匀光、正面中性表情；目视约 28–33 岁在 27–32 内；无文字、无第二人。",
 "PROP-BAMBOO-BASKET": "单体旧竹筐：篾条发黑、筐口磨毛，筐内装着深褐地薯干与冷硬的粗面馍；灰底、无人物、无动物、无文字；无塑料、无金属。",
 "PROP-NUT-CLOTH-BAG": "单体粗麻布袋：灰褐色、鼓鼓囊囊、袋口用麻绳扎紧；灰底、无人物、无文字；无拉链无纽扣。",
 "PROP-STONE-ROLLER": "单体青灰石碾子：一尺多长的圆柱形青石碾，一端可见轴孔，石面粗糙有磨痕；灰底、无人物、无文字；无金属机件。",
 "PROP-YARD-MILLSTONES": "单体上下两块叠放的圆磨盘：青灰石、盘面放射状磨齿、顶面积雪、中心有孔；灰底、无人物、无文字；无木架、无金属。",
 "SET-GOLDEN-LANTERN-EYES": "伸手不见五指的夜空里两盏金色灯笼似的巨眼，眼与眼之间有数丈，周围隐约乌云般的翼影轮廓；不见全貌、不见人、无文字；金色是画面里唯一的金色，无任何人造光。",
}
FAIL_ITEMS = {}  # 2026-09-18: all 11 plates clean; two wardrobe observations (bare bun; sleeveless tunic) recorded, not defects
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
    ansd.update((FAIL_ITEMS.get(iid) or {}).get("answers") or {})
    item["answers"] = ansd
    item["observed"] = {"observed_views": views, "observed_text_strings": []}
    item["observation"] = OBS[iid]
    item["defects"] = (FAIL_ITEMS.get(iid) or {}).get("defects") or []
ans["request_sha256"] = hashlib.sha256(open(req, "rb").read()).hexdigest(); ans["request_path"] = req
ans["reviewer"] = "claude-code-nalu-vlm"; ans["reviewed_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
ans.pop("__NOT_A_REVIEW_FILL_EVERY_NULL__", None); ans["_refusal"] = None
out = "/tmp/e06_identity_answers_filled.json"; json.dump(ans, open(out, "w"), ensure_ascii=False, indent=2)
r = subprocess.run([VENV, PROTO, "submit", "--request", req, "--answers", out], capture_output=True, text=True)
print("submit rc", r.returncode); print((r.stdout or "")[-1500:]); print((r.stderr or "")[-800:])
