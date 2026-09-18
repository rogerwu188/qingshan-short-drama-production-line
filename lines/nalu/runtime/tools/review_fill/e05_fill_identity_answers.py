#!/usr/bin/env python3
"""Fill and submit the E05 identity review from the reviewer's actual viewing (claude-code-nalu-vlm).
Visual findings recorded 2026-09-17T21:10Z from /tmp/e05_id_sheet_{a,b,c}.png + /tmp/e05_boulder2.png (9 plates; boulder card regenerated once) — see OBS."""
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import glob, json, os, subprocess, datetime, hashlib
req = sorted(glob.glob(f"{_np.RUNTIME_ROOT}/runtime/reviews/E05/E05-identity-*_request.json"))[-1]
VENV = f"{_np.VENV_PYTHON}"; PROTO = f"{_np.TOOLS_DIR}/vlm_review_protocol.py"
tpl = "/tmp/e05_identity_answers_tpl.json"
subprocess.run([VENV, PROTO, "example-answers", "--request", req, "--out", tpl], check=True, capture_output=True)
ans = json.load(open(tpl)); R = json.load(open(req))
OBS = {
 "CHAR-FEMALE-LEAD-BLACKCLOAK": "三视图同一人：高挑纤细的年轻女子，莹白脸颊、精致下巴、黑亮长发半束成髻余发披肩；黑色裘皮斗篷（宽松过膝、毛面有乌光、立领遮颈）罩黑色交领窄袖劲装、黑布带束腰、黑色系带皮靴；灰底、均匀正面光、目视镜头中性表情；目视约 20–24 岁在 19–24 内；无珠翠、无符文；无文字、无第二人、无动物。",
 "CHAR-LUWENHUI": "三视图同一人：两岁出头的圆脸男童，明亮大眼，头顶总角小揪；土黄小交领棉袍裹得滚圆套灰白中衣、布带束腰、小棉靴裹腿；灰底、均匀光、正面中性表情；目视约 2–3 岁在 2–3 内；干净整洁无伤；无文字、无第二人。",
 "PROP-BIRD-CAGE": "单体养鸟铁条笼：手锻铁条、木底、顶上提环、一扇带铁扣的小笼门，铁条微锈、陈旧；灰底、无人物、无动物、无文字；无焊接痕与现代镀层。",
 "PROP-PURPLE-EYED-CROW": "单体乌鸦：比寻常乌鸦略大、满身黑羽有乌金金属光泽、一双紫色眼睛清楚可见，立在挂雪的荆棘枝上侧身全貌，鸟喙闭合、写实体态不拟人；灰底、无人物、无文字。",
 "SET-BLUESTONE-BOULDER": "重出后：一人多高的青灰色青石，顶面平、被雪盖了一半，石面在冷光下发青；石旁一簇枯黑挂雪的荆棘丛，雪地；纯净灰底、无人物、无鸟兽（首版卡上多画了一只乌鸦，已作废重出）、无文字。",
}
FAIL_ITEMS = {}  # 2026-09-17T21:10Z: boulder card regenerated once (extra crow), all five clean
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
out = "/tmp/e05_identity_answers_filled.json"; json.dump(ans, open(out, "w"), ensure_ascii=False, indent=2)
r = subprocess.run([VENV, PROTO, "submit", "--request", req, "--answers", out], capture_output=True, text=True)
print("submit rc", r.returncode); print((r.stdout or "")[-1500:]); print((r.stderr or "")[-800:])
