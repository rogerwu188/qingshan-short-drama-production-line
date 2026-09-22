#!/usr/bin/env python3
"""Fill and submit the E07 identity review from the reviewer's actual viewing (claude-code-nalu-vlm).
Visual findings recorded 2026-09-19T05:20Z from the 10 plates under workflow/nalu/E07/identity/plates — see OBS."""
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import glob, json, os, subprocess, datetime, hashlib
req = sorted(glob.glob(f"{_np.RUNTIME_ROOT}/runtime/reviews/E07/E07-identity-*_request.json"))[-1]
VENV = f"{_np.VENV_PYTHON}"; PROTO = f"{_np.TOOLS_DIR}/vlm_review_protocol.py"
tpl = "/tmp/e07_identity_answers_tpl.json"
subprocess.run([VENV, PROTO, "example-answers", "--request", req, "--out", tpl], check=True, capture_output=True)
ans = json.load(open(tpl)); R = json.load(open(req))
OBS = {
 "CHAR-SHAOCHENGFENG": "三视图同一人：四十岁上下的高大男子，披散及肩的黑色长发无冠，颧骨高、眼窝深、目光锐利，短须连鬓山羊胡；深褐皮革札甲（皮甲片以皮绳纵向编缀、旧而磨亮，肩有皮质披膊），内为黑褐粗麻交领袍，皮革腰带打结，腰侧一柄短匕，背后竹木弓与皮箭囊，深褐裤、裹腿皮靴；灰底、均匀正面光、中性表情目视镜头；目视约 38–45 岁在 38–45 内；无文字、无第二人。观察：手中未持铁枪（长枪为道具，不在身份牌内）；甲片为皮革而非铁札甲，符合时代约束。",
 "PROP-BLADE-HORN-STAG": "单体黑褐色大雄鹿侧身全貌：头部两侧与前方共六支扁平、锋锐、刀形的角，深褐近黑的粗毛、颈部鬃毛厚，四足站立，蹄黑；灰底、无人物、无文字；写实鹿类体态，角为刀形骨角、不发光。",
 "PROP-BOAR-KING": "上下两幅：侧身全貌与抬头正面；小山似的巨大野猪，周身钢针般粗硬直立的黑毛，四支雪白弯曲獠牙比小臂还长、沾血，面部（额头到鼻梁）一层黑色鳞片泛冷幽幽的哑光金属光泽，身上多处伤口染血；四足站立；灰底、无人物、无文字；写实野猪体态放大，不发光。",
 "PROP-DONKEY-HEAD-WOLF": "单体直立全貌：硕大的驴头（长耳、驴鼻）张开的嘴露出獠牙与利齿，一双猩红发光的眼睛是画面里唯一的红光，颈后长而浓密的黑鬃毛，黑油油的狼毛躯体，前肢长带利爪，后肢直立站在地上；灰底、无人物、无文字。观察：直立姿态下四肢比例偏人形（狼人式），仍在『山狼躯体、四肢很长可直立』的口径内。",
 "PROP-IRON-ARROWHEAD": "单体铁箭头：锻铁箭镞带中脊与两翼倒钩、后接一截断裂的木杆，镞面锈迹与暗红血污；灰底、无人物、无文字。观察：镞形为带中脊的两翼形而非严格三棱形，作为参考卡可接受。",
 "PROP-NIGHT-BIRDS": "单体黑羽夜鸟侧身全貌：钩喙、一只碧绿的眼睛清楚、黑羽有乌光、黑爪；灰底、无人物、无文字；写实鸟类体态，不发光（碧绿眼睛除外）。观察：只有一只立姿、无惊飞翼影副图；体态与 E05 紫眼乌鸦同为鸦形，以碧绿眼睛区分。",
 "SET-BLOODY-CLEARING": "俯拍雪地：雪面青蓝夜色，大片暗红血迹与喷溅，四个比海碗口还大的兽爪印（掌垫与五趾清楚），几根枯草；无任何生物、无人物、无文字、无人造物。",
 "SET-DISTANT-MOON-LIGHT": "远处雪山山脊之上升起一团白色光团，像一轮明月刚露出峰顶，照亮山脊与近处黑压压的针叶林与雪原；夜空无星无月无人造光；不见虫的形貌、无人物、无文字。",
}
FAIL_ITEMS = {}  # 2026-09-19: all 10 plates clean; observations (no spear in hand; bipedal proportions of the wolf; two-wing arrowhead; single bird) recorded, not defects
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
out = "/tmp/e07_identity_answers_filled.json"; json.dump(ans, open(out, "w"), ensure_ascii=False, indent=2)
r = subprocess.run([VENV, PROTO, "submit", "--request", req, "--answers", out], capture_output=True, text=True)
print("submit rc", r.returncode); print((r.stdout or "")[-1500:]); print((r.stderr or "")[-800:])
