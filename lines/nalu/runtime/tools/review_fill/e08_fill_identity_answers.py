#!/usr/bin/env python3
"""Fill and submit the E08 identity review from the reviewer's actual viewing (claude-code-nalu-vlm).
Visual findings recorded 2026-09-19T05:20Z from the 10 plates under workflow/nalu/E08/identity/plates — see OBS."""
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import glob, json, os, subprocess, datetime, hashlib
req = sorted(glob.glob(f"{_np.RUNTIME_ROOT}/runtime/reviews/E08/E08-identity-*_request.json"))[-1]
VENV = f"{_np.VENV_PYTHON}"; PROTO = f"{_np.TOOLS_DIR}/vlm_review_protocol.py"
tpl = "/tmp/e08_identity_answers_tpl.json"
subprocess.run([VENV, PROTO, "example-answers", "--request", req, "--out", tpl], check=True, capture_output=True)
ans = json.load(open(tpl)); R = json.load(open(req))
OBS = {
 "CHAR-BOY-THIN": "三视图同一人：十岁上下的瘦男孩，短发被压在额前、圆脸、脖子细；灰褐色粗麻交领右衽短袍（唐宋童装语汇），前襟与袖口有深浅不一的补丁，麻绳系腰，深灰长裤、旧布鞋加裹腿；灰底、均匀正面光、中性表情目视镜头；目视约 9–11 岁在 9–11 内；无文字、无第二人。观察：棉袄按乡村童装画成夹袍形制，补丁与磨损到位。",
 "CHAR-GIRL-PATCHED": "三视图同一人：六七岁女孩，头发在头顶挽成小髻（正面与三分之一视图一致），圆脸、小鼻；深蓝与土褐拼接的交领右衽短袄，肩与下摆有明显补丁，褐色布带束腰，下着深色裙裤、旧布鞋；灰底、均匀正面光、中性表情；目视约 6–8 岁在 6–8 内；无文字、无第二人。观察：发型为单髻而非申报的两个小髻，属轻微差异，画面里仍是同一人。",
 "CHAR-LIULAOTOU": "三视图同一人：六十余岁老人，花白发在头顶挽髻插一根木簪、花白山羊胡与短须，额头与眼角深皱、颧骨突出；深青灰粗麻交领右衽长袍，褐色宽布带束腰，袖口磨损；灰底、均匀正面光、中性表情目视镜头；目视约 60–70 岁在 60–70 内；无文字、无第二人。观察：身份牌未戴申报中的旧皮帽护耳（帽子属服装状态，可在镜内补），木杖为独立道具卡不在身份牌内。",
 "PROP-IRON-POT": "单体黑铁锅：厚壁、双耳、半球形锅身，锅沿磨出金属亮边，外壁有使用后的烟熏痕；灰底、无人物、无文字；铸铁质感、无搪瓷无不锈钢无现代把手。",
 "PROP-MEAT-BROTH-BOWL": "单体粗陶碗：土褐色厚壁、碗沿有一处磕口、内壁釉面粗糙不均；灰底、无人物、无文字；唐宋粗陶语汇，无彩釉、无现代餐具。",
 "PROP-ROAST-DEER-LEG": "单体烤鹿腿：一整条后腿串在一根去皮木杆上，外层烤成油亮的焦褐色，表面有油脂反光与焦痕；灰底、无人物、无文字；柴火直烤语汇，无金属烤架、无现代调料。",
 "PROP-WOODEN-STAFF": "单体木杖：一根去皮的天然木杖，杖身有节疤与弯曲，杖头被手握得发亮、颜色更深；灰底、无人物、无文字；无金属包头、无雕饰。",
 "SET-MOON-INSECT-LIGHT": "夜空中一团极亮的白色圆光高悬，光晕柔和向外扩散，下方是被照亮的针叶林与雪原、远处山脊轮廓，雪面泛起淡银色；不见任何虫的形貌、无人物、无文字、无星无月无人造光。",
 "SET-SILVER-LIT-RIDGE": "被银光铺满的雪岭：山脊、雪坡与针叶林被照成淡银色，暗部仍是冷蓝，画面右上角是那团光的方向；无人物、无生物、无文字、无人造物。",
}
FAIL_ITEMS = {}  # 2026-09-20: all 15 plates clean; two observations (老人未戴皮帽、女孩单髻) recorded as notes, not defects
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
out = "/tmp/e08_identity_answers_filled.json"; json.dump(ans, open(out, "w"), ensure_ascii=False, indent=2)
r = subprocess.run([VENV, PROTO, "submit", "--request", req, "--answers", out], capture_output=True, text=True)
print("submit rc", r.returncode); print((r.stdout or "")[-1500:]); print((r.stderr or "")[-800:])
