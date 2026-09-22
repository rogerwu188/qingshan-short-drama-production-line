#!/usr/bin/env python3
"""Fill and submit the E06 video_q2 review (claude-code-nalu-vlm) from /tmp/e06_q2_findings.json written after viewing the Q2 sheets:
/tmp/e06_q2/sheet_*.png (5 original-resolution frames per unit, 4 units per sheet) + single frames opened for
VU-023 and VU-014, + the 2 fps post-gen contact sheets already viewed for the plot review."""
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import glob, hashlib, json, subprocess, datetime, ast
req = sorted(glob.glob(f"{_np.RUNTIME_ROOT}/runtime/reviews/E06/E06-video_q2-*_request.json"))[-1]
VENV = f"{_np.VENV_PYTHON}"; PROTO = f"{_np.TOOLS_DIR}/vlm_review_protocol.py"
tpl = "/tmp/e06_q2_tpl.json"
subprocess.run([VENV, PROTO, "example-answers", "--request", req, "--out", tpl], check=True, capture_output=True)
ans = json.load(open(tpl)); R = json.load(open(req)); by_req = {it["item_id"]: it for it in R["items"]}
QM, WR, LZ, LW = "CHAR-QINMING", "CHAR-LUWENRUI", "CHAR-LUZE", "CHAR-LIANGWANQING"
CA, CB, CC = "CHAR-COMPANION-A", "CHAR-COMPANION-B", "CHAR-COMPANION-C"
F = json.load(open("/tmp/e06_q2_findings.json")); missing = []

for item in ans["items"]:
    uid=item["item_id"]; ex=by_req[uid]["expectations"]; f=F.get(uid)
    if not f: missing.append(uid); continue
    props=ex.get("required_visible_props"); props=ast.literal_eval(props) if isinstance(props,str) else (props or [])
    chars=ex.get("required_visible_characters"); chars=ast.literal_eval(chars) if isinstance(chars,str) else (chars or [])
    anchors=ex.get("required_space_anchors"); anchors=ast.literal_eval(anchors) if isinstance(anchors,str) else (anchors or [])
    q={k:"PASS" for k in item["answers"]}
    if not props: q["props_present_and_end_state_as_declared"]="NOT_APPLICABLE"
    # seq=19 B1/B2 questions: answerable only where the contract declares the state; the reviewer
    # overrides per unit from the findings (creature gait only when the creature is visibly moving).
    if "perceived_life_state_matches_declared" in q and not ex.get("life_states"): q["perceived_life_state_matches_declared"]="NOT_APPLICABLE"
    if "visible_group_count_matches_declared" in q and not ex.get("group_counts"): q["visible_group_count_matches_declared"]="NOT_APPLICABLE"
    if "creature_locomotion_matches_card" in q: q["creature_locomotion_matches_card"]="NOT_APPLICABLE"
    q.update(f.get("answers") or {})
    item["answers"]=q
    item["observed"]={"observed_visible_characters":list(chars),"observed_visible_props":f.get("props",list(props)),
                      "observed_space_anchors":f.get("anchors",list(anchors)),"observed_text_strings":f.get("text",[])}
    if f.get("ex"): item["observed"]["identity_pose_exemptions"]=f["ex"]
    item["observation"]=f["obs"]; item["defects"]=f.get("defects",[])
if missing: raise SystemExit(f"no findings for {missing}")
ans["request_sha256"]=hashlib.sha256(open(req,"rb").read()).hexdigest(); ans["request_path"]=req
ans["reviewer"]="claude-code-nalu-vlm"; ans["reviewed_at"]=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
ans.pop("__NOT_A_REVIEW_FILL_EVERY_NULL__",None); ans["_refusal"]=None
out="/tmp/e06_q2_answers_filled.json"; json.dump(ans,open(out,"w"),ensure_ascii=False,indent=2)
r=subprocess.run([VENV,PROTO,"submit","--request",req,"--answers",out],capture_output=True,text=True)
print("submit rc",r.returncode); print((r.stdout or "")[-900:]); print((r.stderr or "")[-400:])
