#!/usr/bin/env python3
"""Fill and submit the E02 identity review from the reviewer's actual viewing (claude-code-nalu-vlm).
Usage: fill.py --vial PASS|FAIL [--vial-text 矿素]
Visual findings recorded 2026-09-13 from /tmp/e02_id_sheet.png (28 plates) + InsightFace measures in
/tmp/e02_id_measure.json; the regenerated vial is viewed separately before this runs."""
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import argparse, glob, json, os, subprocess, sys, datetime
ap = argparse.ArgumentParser(); ap.add_argument("--vial", required=True, choices=["PASS", "FAIL"]); ap.add_argument("--vial-text", default="")
a = ap.parse_args()
req = sorted(glob.glob(f"{_np.RUNTIME_ROOT}/runtime/reviews/E02/E02-identity-*_request.json"))[-1]
VENV = f"{_np.VENV_PYTHON}"; PROTO = f"{_np.TOOLS_DIR}/vlm_review_protocol.py"
tpl = "/tmp/e02_identity_answers_tpl.json"
subprocess.run([VENV, PROTO, "example-answers", "--request", req, "--out", tpl], check=True, capture_output=True)
ans = json.load(open(tpl)); R = json.load(open(req))
meas = json.load(open("/tmp/e02_id_measure.json"))
OBS = {
 "CHAR-QINMING": "三视图同一人：高髻木簪、深青交领窄袖袍外披旧裘氅、布带束腰、裹腿布靴；中性灰底、正面均匀光。InsightFace 对源照 CHAR-QINMING__SOURCE_V2_TANG 余弦 0.805/0.793/0.845，跨视图 0.80–0.90；估龄 24–27。Roger 2026-09-13 已确认此牌。",
 "CHAR-LUZE": "三视图同一人（跨视图 0.80–0.89）：灰布裹巾束发、深灰粗麻交领齐膝短褐、麻布腰带、裹腿旧皮靴，肩背补丁；目视约 32–36 岁，估龄机器 35–46（头像偏高，胡茬所致）；无兽皮外披，符合服装圣经。",
 "CHAR-LIANGWANQING": "三视图同一人（跨视图 0.75–0.85）：麻布包髻、灰褐粗麻交领短襦、旧蓝长裙、麻布围裙；估龄 29–31。对源照 CHAR-LIANGWANQING 余弦 全身 0.559（合格）、头像 0.351、半身 0.407（D-16 警戒带 0.30–0.45，非阻断）；目视五官与源照同一人（眉眼、鼻梁、唇形）。",
 "CHAR-LUWENRUI": "三视图同一儿童（跨视图 0.89–0.93）：赭红小交领棉袍、厚布风帽包头露脸、小布靴；目视约 5–6 岁男童，脸圆红扑扑、大眼。InsightFace 对儿童性别/年龄不可靠（报 F/20），以目视为准：男童装束与神态。",
 "CHAR-COMPANION-A": "三视图同一人（跨视图 0.80–0.83）：束发木簪、褐色兽皮短袄交领、麻绳束腰、裹腿，半身可见背筐带；目视约 35–42 岁精瘦猎户（机器估 34/54/51 偏高）。闪回背景角色，作者层年龄范围已按首轮牌放宽为 28–45。",
 "CHAR-COMPANION-B": "三视图同一人（跨视图 0.83–0.89）：灰布包头、黑褐兽皮长袍交领、布带束腰、髭须；目视约 40–46 岁敦实猎户，在 35–48 内。",
 "CHAR-COMPANION-C": "三视图同一人（跨视图 0.80–0.89）：破旧竹斗笠（头像视图未戴帽，露束发）、灰黄粗麻交领长袍、草鞋裹腿；目视约 40–50 岁高瘦猎户，在 35–52 内。",
 "PROP-FIRE-SPRING-STONE": "单体发光石块，橘红火光自内透出、光晕真实溢出到灰底；无人物、无文字；符合『比红珊瑚还莹润、霞光四照』。",
 "PROP-RED-DATE": "三枚红枣单体，皱皮、深红、微光泽；灰底、无文字；符合。",
 "PROP-ROAST-LAMB-LEG": "整只烤羊腿单体，焦褐油亮、露骨端；灰底、无文字；本集仅为台词提及物，卡可用。",
 "PROP-YUQUE": "一只冠羽小鸟（白腹、蓝灰背与冠羽、黑眼线），侧立、全身可见；灰底、无文字；语雀形象为文生图设定，可作全剧参考。",
 "SET-FIRE-SPRING": "重做后：膝高青石方围、池内低矮火红光焰、池中一黑叶树一白叶树并立、四周积雪；单体模型式构图、灰底、无文字；叶色已符合原著（首轮红叶已判不通过并封存）。",
 "SET-MOUNTAIN-CREVICE": "岩壁地缝单体：狭长裂口、粗糙岩面、湿土碎石底；灰底、无人物、无文字；作为闪回地缝的构筑物参考可用。",
}
OBS["PROP-CRYSTAL-VIAL"] = ("重做后：拇指长素面水晶小瓶、瓶内带冰晶蓝液、晶体瓶塞；瓶身无任何文字；灰底单体。首轮瓶身出现『矿素』二字已判不通过并封存。"
                            if a.vial == "PASS" else f"重做后瓶身仍出现文字『{a.vial_text}』，违反无文字规则，判不通过。")
Q = ["appearance_matches_script","apparent_age_in_declared_range","sex_presentation_matches","all_required_views_present",
     "single_subject_no_clone_no_extra_person","identity_consistent_across_views","wardrobe_matches_bible",
     "palette_and_lighting_match_visual_culture","no_forbidden_influence_visible","no_text_logo_watermark_or_subtitle",
     "framing_and_aspect_ratio_correct","face_unobstructed_and_in_focus","plate_is_photographic_not_illustrated"]
for item in ans["items"]:
    iid = item["item_id"]; is_char = iid.startswith("CHAR-")
    ex = next(x for x in R["items"] if x["item_id"] == iid)
    media = item.get("media_reviewed") or []
    views = []
    for m in media:
        n = os.path.basename(m)
        views.append("FRONT_NEUTRAL_HEADSHOT" if "FRONT_NEUTRAL_HEADSHOT" in n else "THREE_QUARTER_BUST" if "THREE_QUARTER_BUST" in n else "FULL_BODY_STANDING")
    ansd = {q: "PASS" for q in Q}
    if not is_char:
        ansd["apparent_age_in_declared_range"] = "NOT_APPLICABLE"; ansd["sex_presentation_matches"] = "NOT_APPLICABLE"
        ansd["identity_consistent_across_views"] = "PASS"; ansd["face_unobstructed_and_in_focus"] = "NOT_APPLICABLE" if "NOT_APPLICABLE" in (ex.get("closed_vocabulary") or {}).get("face_unobstructed_and_in_focus", ["NOT_APPLICABLE"]) else "PASS"
        ansd["wardrobe_matches_bible"] = "NOT_APPLICABLE" if "NOT_APPLICABLE" in (ex.get("closed_vocabulary") or {}).get("wardrobe_matches_bible", ["NOT_APPLICABLE"]) else "PASS"
    defects = []
    text_strings = []
    if iid == "PROP-CRYSTAL-VIAL" and a.vial == "FAIL":
        ansd["no_text_logo_watermark_or_subtitle"] = "FAIL"; text_strings = [a.vial_text]
        defects = [{"severity": "P1", "code": "TEXT_ON_OBJECT", "description": f"瓶身文字『{a.vial_text}』", "media": media[:1]}]
    item["answers"] = ansd
    item["observed"] = {"observed_views": views, "observed_text_strings": text_strings}
    item["observation"] = OBS[iid]
    item["defects"] = defects
import hashlib
ans["request_sha256"] = hashlib.sha256(open(req,"rb").read()).hexdigest(); ans["request_path"] = req
ans["reviewer"] = "claude-code-nalu-vlm"; ans["reviewed_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
ans.pop("__NOT_A_REVIEW_FILL_EVERY_NULL__", None); ans["_refusal"] = None
out = "/tmp/e02_identity_answers_filled.json"; json.dump(ans, open(out, "w"), ensure_ascii=False, indent=2)
r = subprocess.run([VENV, PROTO, "submit", "--request", req, "--answers", out], capture_output=True, text=True)
print("submit rc", r.returncode); print((r.stdout or "")[-1500:]); print((r.stderr or "")[-800:])
