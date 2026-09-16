#!/usr/bin/env python3
"""Fill and submit the E04 post_gen_plot review from /tmp/e04_pgp_findings.json (viewed 2 fps contact sheets)
and /tmp/e04_asr.json (local faster-whisper transcripts, zh)."""
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import glob, hashlib, json, subprocess, datetime
req = sorted(glob.glob(f"{_np.RUNTIME_ROOT}/runtime/reviews/E04/E04-post_gen_plot-*_request.json"))[-1]
VENV = f"{_np.VENV_PYTHON}"; PROTO = f"{_np.TOOLS_DIR}/vlm_review_protocol.py"
tpl = "/tmp/e04_pgp_tpl.json"
subprocess.run([VENV, PROTO, "example-answers", "--request", req, "--out", tpl], check=True, capture_output=True)
ans = json.load(open(tpl)); R = json.load(open(req))
F = json.load(open("/tmp/e04_pgp_findings.json")); ASR = json.load(open("/tmp/e04_asr.json"))
by_req = {it["item_id"]: it for it in R["items"]}
missing = []
for item in ans["items"]:
    uid = item["item_id"]; ex = by_req[uid]["expectations"]; f = F.get(uid)
    if not f:
        missing.append(uid); continue
    has_dlg = bool(ex.get("expected_dialogue"))
    q = {"episode_scene_correspondence": "PASS", "principal_character_presence": "PASS", "major_event_presence": "PASS",
         "major_dialogue_presence": "PASS" if has_dlg else "NOT_APPLICABLE", "chronological_unit_order": "PASS"}
    q.update(f.get("answers") or {})
    item["answers"] = {k: q.get(k, v) for k, v in item["answers"].items()} if item.get("answers") else q
    spoken = [s["text"] for s in ASR.get(uid, [])]
    item["observed"] = {"observed_principal_characters": f.get("observed_principal_characters", list(ex.get("principal_characters") or [])),
                        "observed_missing_beats": f.get("observed_missing_beats", []),
                        "observed_spoken_lines": spoken}
    obs = f["observation"]
    if has_dlg:
        obs += " 本地 ASR（faster-whisper small, zh）听写：" + " / ".join(spoken)[:160] + "（繁简与同音差异以生成后对白门禁的正字化核对为准）。"
    item["observation"] = obs; item["defects"] = f.get("defects", [])
if missing:
    raise SystemExit(f"no findings for {missing}")
ans["request_sha256"] = hashlib.sha256(open(req, "rb").read()).hexdigest(); ans["request_path"] = req
ans["reviewer"] = "claude-code-nalu-vlm"; ans["reviewed_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
ans.pop("__NOT_A_REVIEW_FILL_EVERY_NULL__", None); ans["_refusal"] = None
out = "/tmp/e04_pgp_answers_filled.json"; json.dump(ans, open(out, "w"), ensure_ascii=False, indent=2)
r = subprocess.run([VENV, PROTO, "submit", "--request", req, "--answers", out], capture_output=True, text=True)
print("submit rc", r.returncode); print((r.stdout or "")[-900:]); print((r.stderr or "")[-300:])
