#!/usr/bin/env python3
"""Fill and submit the E04 identity review from the reviewer's actual viewing (claude-code-nalu-vlm).
Visual findings recorded 2026-09-15T17:35Z from /tmp/e04_id_sheet_{a,b,c,d,e}.png (14 plates; 胡勇/王佑平 regenerated after the injury-leak rejection) — see OBS."""
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import glob, json, os, subprocess, datetime, hashlib
req = sorted(glob.glob(f"{_np.RUNTIME_ROOT}/runtime/reviews/E04/E04-identity-*_request.json"))[-1]
VENV = f"{_np.VENV_PYTHON}"; PROTO = f"{_np.TOOLS_DIR}/vlm_review_protocol.py"
tpl = "/tmp/e04_identity_answers_tpl.json"
subprocess.run([VENV, PROTO, "example-answers", "--request", req, "--out", tpl], check=True, capture_output=True)
ans = json.load(open(tpl)); R = json.load(open(req))
OBS = {
 "CHAR-HUYONG": "重出后三视图同一人：二十多岁中等身材男子，下巴微扬眼神横；灰褐粗麻交领短褐外罩破旧黑褐皮袄（毛面稀疏、袖口磨毛）、布带束腰腰后别短棍、旧布靴裹腿、麻布包髻歪斜；灰底、均匀光；目视约 24–28 岁在 22–28 内；面部干净无伤（首版泄漏的瘀伤已消除）；无文字、无第二人。",
 "CHAR-MAYANG": "三视图同一人：二十多岁瘦长缩肩男子，眼神多疑；灰黄粗麻交领右衽膝下长袍（前襟方形补丁）套褐色中衣、麻绳腰带别短棍、旧布鞋裹腿；灰布裹头；灰底、均匀光；目视约 23–27 岁在 22–28 内；面部干净无伤；无文字、无第二人。",
 "CHAR-WANGYOUPING": "重出后三视图同一人：二十多岁矮胖圆肩男子、缩着脖子；灰褐粗麻交领右衽膝下棉袍（鼓鼓囊囊、前襟油渍）套灰白中衣、布带束腰挂短刀、旧布靴；兽皮护耳帽压得很低；灰底；目视约 22–26 岁在 22–28 内；衣服完好、面部无伤（首版泄漏的胸口伤已消除）；无文字、无第二人。",
 "PROP-DONKEY": "单体灰毛驴：写实家驴、无鞍无缰、立姿平静，灰底、无人物、无文字；符合『对前路很熟、淡淡一瞥』的沉静气质。",
 "PROP-IRON-ROD": "单体粗锻短铁棍：表面锻打纹与锈蚀、无现代金属管光泽；灰底、无文字。",
 "PROP-MUTANT-BEAST": "全身黑影剪影：块头很大、直立、长臂利爪、通体黑毛，只有两点猩红的眼光，面目不可辨；灰底、无文字；符合『只给轮廓、不给全貌、不做怪兽特效』——作为参考卡它给出了体态与眼睛，画面里仍按剧本只在黑暗中隐现。",
 "PROP-WHITE-WEASEL": "单体纯白鼬科小兽：通体雪白无杂毛、黑眼、坐姿沉静、尾巴盘在身前；写实、不拟人；灰底、无文字。",
 "SET-SNOW-HOLLOW": "一人深的雪坑：雪壁粗糙、坑口被风吹得毛糙、坑底平；无工具痕迹之外的人造物、无人物、无文字；符合三人挖出的挡风雪窟窿。",
}
FAIL_ITEMS = {}  # second submission 2026-09-15T17:35Z: both regenerated plates are clean
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
out = "/tmp/e04_identity_answers_filled.json"; json.dump(ans, open(out, "w"), ensure_ascii=False, indent=2)
r = subprocess.run([VENV, PROTO, "submit", "--request", req, "--answers", out], capture_output=True, text=True)
print("submit rc", r.returncode); print((r.stdout or "")[-1500:]); print((r.stderr or "")[-800:])
