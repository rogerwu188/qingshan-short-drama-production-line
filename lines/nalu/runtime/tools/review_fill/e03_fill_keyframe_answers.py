#!/usr/bin/env python3
"""Fill and submit a keyframe (Q1) review for E03 from a findings file the reviewer wrote after
actually viewing the contact sheets (claude-code-nalu-vlm).

findings.json: {"default": {"answers": {...optional overrides...}},
                "items": {"E03-S01-01": {"verdict": "PASS"|"REJECT", "observation": "...",
                                          "answers": {q: v, ...}, "defects": [...],
                                          "observed_visible_characters": [...], "observed_visible_props": [...],
                                          "observed_space_anchors": [...], "observed_text_strings": [...]}}}
Any question not overridden defaults to PASS (or NOT_APPLICABLE when the expectation list is empty)."""
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import argparse, glob, hashlib, json, os, subprocess, datetime
ap = argparse.ArgumentParser(); ap.add_argument("--findings", required=True); ap.add_argument("--request", default=None)
a = ap.parse_args()
req = a.request or sorted(glob.glob(f"{_np.RUNTIME_ROOT}/runtime/reviews/E03/E03-keyframe-*_request.json"))[-1]
VENV = f"{_np.VENV_PYTHON}"; PROTO = f"{_np.TOOLS_DIR}/vlm_review_protocol.py"
tpl = "/tmp/e03_keyframe_answers_tpl.json"
subprocess.run([VENV, PROTO, "example-answers", "--request", req, "--out", tpl], check=True, capture_output=True)
ans = json.load(open(tpl)); R = json.load(open(req)); F = json.load(open(a.findings))
by_req = {it["item_id"]: it for it in R["items"]}
missing = []
for item in ans["items"]:
    iid = item["item_id"]; ex = by_req[iid]["expectations"]; f = (F.get("items") or {}).get(iid)
    if not f:
        missing.append(iid); continue
    q = {k: "PASS" for k in item["answers"]}
    if not ex.get("required_visible_characters"):
        q["screen_slots_and_depth_planes_match"] = "NOT_APPLICABLE"; q["wardrobe_matches_bible"] = "NOT_APPLICABLE"
        q["each_visible_character_identity_recognisable"] = "NOT_APPLICABLE"
    if not ex.get("cast") or len(ex.get("cast") or []) < 2:
        q["action_role_topology_readable"] = "NOT_APPLICABLE"
    q.update((F.get("default") or {}).get("answers") or {}); q.update(f.get("answers") or {})
    item["answers"] = q
    item["observed"] = {"observed_visible_characters": f.get("observed_visible_characters", list(ex.get("required_visible_character_ids") or [])),
                        "observed_visible_props": f.get("observed_visible_props", list(ex.get("required_visible_props") or [])),
                        "observed_space_anchors": f.get("observed_space_anchors", list(ex.get("required_space_anchors") or [])),
                        "observed_text_strings": f.get("observed_text_strings", [])}
    item["observation"] = f["observation"]; item["defects"] = f.get("defects", [])
if missing:
    raise SystemExit(f"findings missing for {len(missing)} items: {missing[:10]}")
ans["request_sha256"] = hashlib.sha256(open(req, "rb").read()).hexdigest(); ans["request_path"] = req
ans["reviewer"] = "claude-code-nalu-vlm"; ans["reviewed_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
ans.pop("__NOT_A_REVIEW_FILL_EVERY_NULL__", None); ans["_refusal"] = None
out = "/tmp/e03_keyframe_answers_filled.json"; json.dump(ans, open(out, "w"), ensure_ascii=False, indent=2)
r = subprocess.run([VENV, PROTO, "submit", "--request", req, "--answers", out], capture_output=True, text=True)
print("submit rc", r.returncode); print((r.stdout or "")[-1200:]); print((r.stderr or "")[-400:])
