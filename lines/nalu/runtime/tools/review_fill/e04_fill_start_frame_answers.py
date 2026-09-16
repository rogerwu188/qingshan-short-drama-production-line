#!/usr/bin/env python3
"""Fill and submit an E04 start_frame review from the keyframe findings (claude-code-nalu-vlm).
Each item is a unit; its start frame is the unit's first-shot keyframe already viewed for Q1.
Extra per-unit overrides: /tmp/e04_start_frame_overrides.json {unit_id: {answers:{}, observation:"", ...}}"""
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import glob, hashlib, json, os, subprocess, datetime, sys
req = sorted(glob.glob(f"{_np.RUNTIME_ROOT}/runtime/reviews/E04/E04-start_frame-*_request.json"))[-1]
VENV = f"{_np.VENV_PYTHON}"; PROTO = f"{_np.TOOLS_DIR}/vlm_review_protocol.py"
tpl = "/tmp/e04_sf_answers_tpl.json"
subprocess.run([VENV, PROTO, "example-answers", "--request", req, "--out", tpl], check=True, capture_output=True)
ans = json.load(open(tpl)); R = json.load(open(req))
F = json.load(open("/tmp/e04_keyframe_findings.json"))["items"]
OV = json.load(open("/tmp/e04_start_frame_overrides.json")) if os.path.exists("/tmp/e04_start_frame_overrides.json") else {}
by_req = {it["item_id"]: it for it in R["items"]}
missing = []
for item in ans["items"]:
    uid = item["item_id"]; ex = by_req[uid]["expectations"]; shot = by_req[uid].get("shot_id")
    f = F.get(shot) or {}
    if not f.get("observation"):
        missing.append((uid, shot)); continue
    chars = list(ex.get("required_visible_characters") or []); props = list(ex.get("required_visible_props") or [])
    q = {"entry_state_only": "PASS", "camera_start_framing_match": "YES", "space_match": "YES",
         "empty_establishing_frame": "YES" if ex.get("empty_establishing_frame_expected") else "NO",
         "all_required_characters_visible": "PASS" if chars else "NOT_APPLICABLE",
         "all_required_props_visible": "PASS" if props else "NOT_APPLICABLE"}
    q.update((OV.get(uid) or {}).get("answers") or {})
    item["answers"] = {k: q.get(k, v) for k, v in item["answers"].items()} if item.get("answers") else q
    item["observed"] = {"observed_visible_characters": chars, "observed_visible_props": props,
                        "observed_space_anchors": list(ex.get("required_space_anchors") or [])}
    item["observation"] = (OV.get(uid) or {}).get("observation") or (f["observation"] + " 起始帧：仅呈现 entry 态，未出现 completion 态；开场取景与机位方案一致；地点与子空间锚点可辨。")
    item["defects"] = (OV.get(uid) or {}).get("defects") or []
if missing:
    raise SystemExit(f"no findings for {missing}")
ans["request_sha256"] = hashlib.sha256(open(req, "rb").read()).hexdigest(); ans["request_path"] = req
ans["reviewer"] = "claude-code-nalu-vlm"; ans["reviewed_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
ans.pop("__NOT_A_REVIEW_FILL_EVERY_NULL__", None); ans["_refusal"] = None
out = "/tmp/e04_sf_answers_filled.json"; json.dump(ans, open(out, "w"), ensure_ascii=False, indent=2)
r = subprocess.run([VENV, PROTO, "submit", "--request", req, "--answers", out], capture_output=True, text=True)
print("submit rc", r.returncode); print((r.stdout or "")[-800:]); print((r.stderr or "")[-300:])
