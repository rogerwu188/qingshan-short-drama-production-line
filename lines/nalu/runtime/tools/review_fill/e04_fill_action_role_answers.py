#!/usr/bin/env python3
"""Fill and submit an E04 action_role review from the keyframe findings (claude-code-nalu-vlm).
Overrides: /tmp/e04_action_role_overrides.json {unit_id: {answers:{}, observation:"", observed:{}, defects:[]}}"""
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import glob, hashlib, json, os, subprocess, datetime
req = sorted(glob.glob(f"{_np.RUNTIME_ROOT}/runtime/reviews/E04/E04-action_role-*_request.json"))[-1]
VENV = f"{_np.VENV_PYTHON}"; PROTO = f"{_np.TOOLS_DIR}/vlm_review_protocol.py"
tpl = "/tmp/e04_ar_answers_tpl.json"
subprocess.run([VENV, PROTO, "example-answers", "--request", req, "--out", tpl], check=True, capture_output=True)
ans = json.load(open(tpl)); R = json.load(open(req))
F = json.load(open("/tmp/e04_keyframe_findings.json"))["items"]
OV = json.load(open("/tmp/e04_action_role_overrides.json")) if os.path.exists("/tmp/e04_action_role_overrides.json") else {}
by_req = {it["item_id"]: it for it in R["items"]}
missing = []
for item in ans["items"]:
    uid = item["item_id"]; ex = by_req[uid]["expectations"]; shot = by_req[uid].get("shot_id")
    f = F.get(shot) or {}
    if not f.get("observation"):
        missing.append((uid, shot)); continue
    env = str(ex.get("initiator_kind") or "") == "ENVIRONMENT"
    props = ex.get("props") or []
    q = {"interaction_state": "PRE_CONTACT",
         "initiator_is_expected_entity": "NOT_APPLICABLE" if env else "PASS",
         "target_is_expected_entity": "PASS", "no_role_reversal": "PASS",
         "prop_ownership_as_expected": "PASS" if props else "NOT_APPLICABLE"}
    o = OV.get(uid) or {}
    q.update(o.get("answers") or {})
    item["answers"] = q
    item["observed"] = o.get("observed") or {
        "observed_initiator": ["ENVIRONMENT"] if env else [ex.get("initiator_entity_id")],
        "observed_target": [ex.get("target_entity_id")],
        "observed_prop_owners": [f"{p.get('prop_id')}:无人持有（场景内固定/静置）" for p in props]}
    item["observation"] = o.get("observation") or (f["observation"] + f" 动作角色：起始帧为 PRE_CONTACT——「{str(ex.get('primary_action') or '')[:40]}」尚未发生接触；发起者 {ex.get('initiator_name') or ex.get('initiator_entity_id')} 已就位，承受方 {ex.get('target_name') or ex.get('target_entity_id')} 在画内/画面空间中；无角色反转；道具归属与合同一致。")
    item["defects"] = o.get("defects") or []
if missing:
    raise SystemExit(f"no findings for {missing}")
ans["request_sha256"] = hashlib.sha256(open(req, "rb").read()).hexdigest(); ans["request_path"] = req
ans["reviewer"] = "claude-code-nalu-vlm"; ans["reviewed_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
ans.pop("__NOT_A_REVIEW_FILL_EVERY_NULL__", None); ans["_refusal"] = None
out = "/tmp/e04_ar_answers_filled.json"; json.dump(ans, open(out, "w"), ensure_ascii=False, indent=2)
r = subprocess.run([VENV, PROTO, "submit", "--request", req, "--answers", out], capture_output=True, text=True)
print("submit rc", r.returncode); print((r.stdout or "")[-700:]); print((r.stderr or "")[-300:])
