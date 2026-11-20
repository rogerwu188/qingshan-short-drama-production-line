#!/usr/bin/env python3
"""Video-native final review pass (line owner 2026-11-19; benchmark ~/Desktop/终审测试/REPORT.md).

Before the Codex final-audience reviewer starts (codex_production.launch_reviewer), one Gemini call WATCHES and
HEARS the SHA-bound final MP4 and answers ONE checklist prompt ("Pass B"): the six must-check items of
nalu_qa_defect_checklist (QA-*), letterboxed shots, a character's look drifting, and anything else -- with the
local evidence pack's summary and the locally measured C2 (line tail) / C6 (music fragment) suspects to confirm or
dismiss (the model alone does not hear those reliably; the measurement does not see them).

  transcode   432x768, H.264 CRF 30, AAC 64k (a 100 s episode is ~5 MB; the request limit is 20 MB)
  call        HopsAPI ``POST /v1/models/<model>:generateContent`` with ``inline_data`` (base64) and
              ``video_metadata.fps`` 2; model ``gemini-3.8-flash`` (NALU_GEMINI_REVIEW_MODEL)
  cost        ~1.1-1.4 credits per episode (benchmark).  The tool estimates the call before sending it and lowers
              the sampling fps (2 -> 1.5 -> 1) to stay under NALU_GEMINI_REVIEW_MAX_CREDITS (1.5); if even 1 fps
              does not fit, it skips.  The recorded cost is computed from the response's usage.
  output      ``final_reviewer/gemini_review.json``: findings (ids G1..), suspect checks, usage and cost, bound to the
              request and final-video SHA.

Authority: ADVISORY.  On ANY failure (no key, transcode error, HTTP error, unparsable answer, over budget) the tool
records why and exits 0 -- it never blocks the review.  Codex stays the reviewer and the submitter: it verifies every
Gemini finding against the frames and records confirmed ones (problems + the qa_defect_checklist block) and a reason
for each dismissal.

Key: the line's HopsAPI key, resolved like paid_stage.sh does -- ``HOPSAPI_API_KEY`` from the environment, else the
engine ``.env``, else ``$NALU_RUNTIME_ROOT/credentials/llm_provider.json`` when that provider is HopsAPI.  The key is
only ever put in the Authorization header; it is never printed, logged or written.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

SCHEMA = "nalu.gemini_video_review.v1"
TOOL_ID = "gemini_video_review.v1"
DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_BASE_URL = "https://hopsapi.com/v1"
DEFAULT_FPS = 2.0
FPS_STEPS = (2.0, 1.5, 1.0)
MAX_CREDITS_DEFAULT = 1.5
#: credits per 1M tokens (input, output incl. thinking) -- HopsAPI list prices used by the benchmark
PRICES = {"gemini-3.8-flash": (50.25, 251.25), "gemini-3.1-pro-preview": (134.0, 804.0)}
#: measured on the benchmark (fps 2, default media resolution): video 66 tokens / frame, audio 25 tokens / s
VIDEO_TOKENS_PER_FRAME = 66
AUDIO_TOKENS_PER_S = 25
EXPECTED_OUTPUT_TOKENS = 1800       # answer + thinking, benchmark mean ~1.6k
MAX_OUTPUT_TOKENS = 8192
MAX_UPLOAD_BYTES = 14_500_000       # raw bytes: base64 inflates by 4/3 and the request limit is 20 MB
HTTP_TIMEOUT_S = 600
CLASSES = ("QA-BURNED-TEXT", "QA-DIALOGUE-TAIL-CUT", "QA-OVERSIZED-MASK", "QA-LOOKALIKE-CAST", "QA-SUBTITLE-WRAP",
           "QA-BGM-DISCONTINUOUS", "QA-SKIN-SHEEN-DRIFT", "LETTERBOX", "LOOK-DRIFT", "OTHER")
SEVERITIES = ("P0", "P1", "P2", "P3")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def _num(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


# ------------------------------------------------------------------------------------------------ key
def _env_file_value(path: Path, name: str) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        m = re.match(rf"^\s*(?:export\s+)?{re.escape(name)}\s*=\s*(.*)$", line)
        if m:
            return m.group(1).strip().strip("'\"")
    return ""


def resolve_key(environ: dict[str, str] | None = None) -> tuple[str, str]:
    """(key, source label).  Order as paid_stage.sh: env, engine .env, the Codex provider when it is HopsAPI."""
    env = os.environ if environ is None else environ
    key = str(env.get("HOPSAPI_API_KEY") or "").strip()
    if key:
        return key, "ENV:HOPSAPI_API_KEY"
    engine = Path(env.get("NALU_ENGINE_ROOT") or Path(__file__).resolve().parents[4]).expanduser()
    key = _env_file_value(engine / ".env", "HOPSAPI_API_KEY")
    if key:
        return key, "ENGINE_DOTENV:HOPSAPI_API_KEY"
    for root in [env.get("NALU_RUNTIME_ROOT") or "~/nalu_runtime"]:
        try:
            data = json.loads((Path(root).expanduser() / "credentials" / "llm_provider.json").read_text())
        except (OSError, ValueError):
            continue
        if "hopsapi" in str(data.get("base_url") or "").lower() and data.get("api_key"):
            return str(data["api_key"]).strip(), "LLM_PROVIDER:HOPSAPI"
    return "", "NONE"


# ------------------------------------------------------------------------------------------------ media
def transcode(video: Path, out: Path, *, crf: int = 30) -> Path:
    ffmpeg = os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg") or "ffmpeg"
    out.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(video), "-vf", "scale=432:768", "-c:v", "libx264",
                          "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
                          "-ac", "1", "-movflags", "+faststart", str(out)],
                         capture_output=True, text=True, timeout=900)
    if run.returncode != 0 or not out.is_file():
        raise RuntimeError(f"transcode failed: {(run.stderr or '')[-300:]}")
    return out


def media_duration(video: Path) -> float:
    ffprobe = os.environ.get("FFPROBE_BIN") or shutil.which("ffprobe") or "ffprobe"
    run = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(video)],
                         capture_output=True, text=True, timeout=60)
    return float((json.loads(run.stdout or "{}").get("format") or {}).get("duration") or 0.0)


# ------------------------------------------------------------------------------------------------ cost
def estimate_credits(model: str, duration: float, prompt_chars: int, fps: float) -> float:
    pin, pout = PRICES.get(model, PRICES[DEFAULT_MODEL])
    tokens_in = duration * fps * VIDEO_TOKENS_PER_FRAME + duration * AUDIO_TOKENS_PER_S + prompt_chars / 1.6 + 300
    return round(tokens_in * pin / 1e6 + EXPECTED_OUTPUT_TOKENS * pout / 1e6, 3)


def choose_fps(model: str, duration: float, prompt_chars: int, cap: float, preferred: float = DEFAULT_FPS) -> float | None:
    for fps in [f for f in FPS_STEPS if f <= preferred] or [preferred]:
        if estimate_credits(model, duration, prompt_chars, fps) <= cap:
            return fps
    return None


def actual_credits(model: str, usage: dict[str, Any]) -> float:
    pin, pout = PRICES.get(model, PRICES[DEFAULT_MODEL])
    tin = int(usage.get("promptTokenCount") or 0)
    tout = int(usage.get("candidatesTokenCount") or 0) + int(usage.get("thoughtsTokenCount") or 0)
    return round(tin * pin / 1e6 + tout * pout / 1e6, 3)


# ------------------------------------------------------------------------------------------------ prompt
ITEM_TEXT = {
    "QA-BURNED-TEXT": "画面里视频模型自己烧进去的文字：大号台词字、第二行字幕、乱码字、字幕上下多出的单个大字（片头剧名卡和片尾卡不算）。",
    "QA-DIALOGUE-TAIL-CUT": "台词尾音被切：一句话最后一个字在切镜处被截断，或一句说完没有自然停顿就切走/下一句立刻压上。",
    "QA-OVERSIZED-MASK": "过大的遮罩/模糊框：明显的矩形模糊、马赛克或遮挡块，比字幕区大，盖住脸、手或动作。",
    "QA-LOOKALIKE-CAST": "两个不同角色长着几乎同一张脸（脸型、五官一样，只靠衣服区分）。",
    "QA-SUBTITLE-WRAP": "我方字幕排版：标点（！？。）或一两个字单独占一行、超过两行、我方字幕和画面里其它文字重叠压字。",
    "QA-BGM-DISCONTINUOUS": "背景音乐突兀：音乐只响一两个镜头就停，或在切镜处生硬起停、没有淡入淡出。",
    "QA-SKIN-SHEEN-DRIFT": "皮肤/头发质感突变：相邻镜头间人物脸突然油光、出汗、高光反光，头发变湿，或皮肤纹理突然过锐（场景没有雨水、汗水、眼泪的理由）。",
    "LETTERBOX": "画幅：竖屏 9:16 成片里混入横版镜头（上下黑边）或左右黑边。",
    "LOOK-DRIFT": "同一角色前后造型不一致（胡子、发型、服装、配饰在同一场里变了）。",
    "OTHER": "其它任何观众会注意到的问题（口型对不上、穿帮、重复台词、跳帧、节奏拖沓等）。",
}


def _compact_suspects(pack_summary: dict[str, Any], measurements: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """S-ids for the measured suspects the model must confirm or dismiss (C2 tails, C6 music; letterbox shots)."""
    out: dict[str, list[dict[str, Any]]] = {"tail": [], "bgm": [], "letterbox": []}
    seen: set[float] = set()
    for row in pack_summary.get("tail_cut_suspects") or []:
        if _num(row.get("cut")) is not None and round(float(row["cut"]), 1) not in seen:
            seen.add(round(float(row["cut"]), 1))
            out["tail"].append({"at": round(float(row["cut"]), 2), "why": f"切点前人声缺口 {row.get('gap_s')}s，"
                                f"切点处人声高出底噪 {row.get('level_db')}dB"})
    for row in (measurements.get("dialogue_tail") or {}).get("flagged") or []:
        cut = _num(row.get("next_cut"))
        if cut is not None and round(cut, 1) not in seen:
            seen.add(round(cut, 1))
            out["tail"].append({"at": round(cut, 2), "why": f"台词结束到切点只有 {row.get('gap_seconds')}s"})
    for row in pack_summary.get("bgm_suspects") or []:
        out["bgm"].append({"window": row.get("window"), "why": ",".join(row.get("reasons") or [])})
    for row in pack_summary.get("letterbox_shots") or []:
        out["letterbox"].append({"window": row.get("window"),
                                 "why": f"{row.get('kind')} content aspect {row.get('content_aspect')}"})
    ids = 0
    for key in ("tail", "bgm", "letterbox"):
        out[key] = out[key][:20]
        for row in out[key]:
            ids += 1
            row["id"] = f"S{ids}"
    return out


def build_prompt(*, duration: float, pack_summary: dict[str, Any] | None, measurements: dict[str, Any] | None,
                 anime: bool = False) -> tuple[str, dict[str, list[dict[str, Any]]]]:
    pack_summary, measurements = pack_summary or {}, measurements or {}
    suspects = _compact_suspects(pack_summary, measurements)
    leads = {
        "burned_text_ocr": [{"window": r.get("window"), "text": r.get("text"), **({"garbled": True}
                            if r.get("garbled") else {})} for r in (pack_summary.get("burned_text_runs") or [])[:25]],
        "subtitle_wrap": (pack_summary.get("wrap_suspects") or [])[:10],
        "lookalike_faces": (pack_summary.get("lookalike") or {}).get("suspects", [])[:6],
    }
    lines = [
        f"你是竖屏 9:16 短剧平台的终审审片员。请完整观看并收听这一集（约 {duration:.0f} 秒，画面+声音），按清单逐项检查。"
        "每发现一处单独列一条，不合并、不编造；没有就不列。时间用秒，保留 1 位小数。",
        "我方字幕：画面底部居中的小号白字黑边，一到两行。除此之外画面里的字都不是我方加的。" +
        ("本剧是 2D 动画风格，画风本身不算问题。" if anime else ""),
        "", "清单：",
    ]
    lines += [f"{cid}：{ITEM_TEXT[cid]}" for cid in CLASSES]
    lines += ["", "本地免费测量给出的线索（OCR/人脸/字幕像素，供参考，以你看到的为准）：",
              json.dumps(leads, ensure_ascii=False, separators=(",", ":"))]
    if any(suspects.values()):
        lines += ["", "本地测量的可疑点，必须逐个用耳朵/眼睛核实并在 suspect_checks 里给结论（CONFIRMED 确有其事 / "
                  "DISMISSED 听看都正常 / UNSURE），给出你听到或看到的理由：",
                  json.dumps(suspects, ensure_ascii=False, separators=(",", ":"))]
    lines += ["", "只输出 JSON：",
              '{"findings":[{"class":"QA-BURNED-TEXT","start":0.0,"end":0.0,"severity":"P0|P1|P2|P3",'
              '"description":"","evidence":"你具体看到/听到了什么"}],'
              '"suspect_checks":[{"id":"S1","decision":"CONFIRMED|DISMISSED|UNSURE","reason":""}],'
              '"class_summary":{"QA-BURNED-TEXT":"found|not_found"},"verdict":"PASS|REJECT_RECUT"}',
              "severity：P0 必须返工 / P1 严重 / P2 一般 / P3 轻微。"]
    return "\n".join(lines), suspects


# ------------------------------------------------------------------------------------------------ call + parse
def http_post(url: str, body: bytes, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 -- fixed https base
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def call_gemini(*, video_bytes: bytes, prompt: str, model: str, fps: float, key: str, base_url: str,
                post: Callable[[str, bytes, dict[str, str], float], tuple[int, bytes]] = http_post) -> dict[str, Any]:
    body = {"contents": [{"role": "user", "parts": [
        {"inline_data": {"mime_type": "video/mp4", "data": base64.b64encode(video_bytes).decode()},
         "video_metadata": {"fps": fps}},
        {"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json",
                             "maxOutputTokens": MAX_OUTPUT_TOKENS}}
    started = time.time()
    status, raw = post(f"{base_url.rstrip('/')}/models/{model}:generateContent", json.dumps(body).encode(),
                       {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, HTTP_TIMEOUT_S)
    latency = round(time.time() - started, 1)
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace") or "{}")
    except ValueError:
        payload = {}
    return {"http_status": status, "latency_s": latency, "payload": payload,
            "error_body": None if status == 200 else _redact(raw.decode("utf-8", errors="replace")[:600], key)}


def _redact(text: str, key: str) -> str:
    return text.replace(key, "<redacted>") if key else text


def response_text(payload: dict[str, Any]) -> str:
    try:
        parts = payload["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        return ""
    return "".join(str(p.get("text") or "") for p in parts if isinstance(p, dict) and not p.get("thought"))


def parse_answer(text: str, *, duration: float | None, suspects: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Lenient: well-formed findings kept (ids G1..), others dropped with a note."""
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except ValueError:
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else None
    if not isinstance(data, dict):
        raise ValueError("answer is not a JSON object")
    findings, notes = [], []
    for pos, row in enumerate(data.get("findings") or []):
        if not isinstance(row, dict):
            continue
        cls = str(row.get("class") or "").strip().upper()
        cls = {"C1": "QA-BURNED-TEXT", "C2": "QA-DIALOGUE-TAIL-CUT", "C3": "QA-OVERSIZED-MASK",
               "C4": "QA-LOOKALIKE-CAST", "C5": "QA-SUBTITLE-WRAP", "C6": "QA-BGM-DISCONTINUOUS"}.get(cls, cls)
        if cls not in CLASSES:
            cls = "OTHER"
        start, end = _num(row.get("start")), _num(row.get("end"))
        if start is None or start < 0 or (duration and start > duration + 1):
            notes.append(f"findings.{pos}:bad_start")
            continue
        end = start if end is None or end < start else end
        sev = str(row.get("severity") or "P2").strip().upper()
        findings.append({"id": f"G{len(findings) + 1}", "item": cls, "start": round(start, 1), "end": round(end, 1),
                         "severity": sev if sev in SEVERITIES else "P2",
                         "description": str(row.get("description") or "")[:300],
                         "evidence": str(row.get("evidence") or "")[:300]})
    known = {row["id"]: row for rows in suspects.values() for row in rows}
    checks = []
    for row in data.get("suspect_checks") or []:
        if isinstance(row, dict) and str(row.get("id")) in known:
            decision = str(row.get("decision") or "").strip().upper()
            checks.append({"id": str(row["id"]), "decision": decision if decision in ("CONFIRMED", "DISMISSED", "UNSURE")
                           else "UNSURE", "reason": str(row.get("reason") or "")[:300],
                           "suspect": known[str(row["id"])]})
    answered = {c["id"] for c in checks}
    checks += [{"id": sid, "decision": "NOT_ANSWERED", "suspect": row} for sid, row in known.items()
               if sid not in answered]
    verdict = str(data.get("verdict") or "").strip().upper()
    return {"findings": findings[:60], "suspect_checks": checks, "class_summary": data.get("class_summary") or {},
            "verdict": verdict if verdict in ("PASS", "REJECT_RECUT") else None, "parse_notes": notes}


# ------------------------------------------------------------------------------------------------ run
def _pack_summary(request: dict[str, Any]) -> dict[str, Any]:
    row = (request.get("evidence") or {}).get("av_evidence_pack") or {}
    path = Path(str(row.get("path") or ""))
    if not path.is_file() or (row.get("sha256") and _sha(path) != row.get("sha256")):
        return {}
    try:
        return (json.loads(path.read_text(encoding="utf-8")) or {}).get("summary") or {}
    except (OSError, ValueError):
        return {}


def run(*, request_path: Path, out: Path, model: str | None = None, fps: float | None = None,
        max_credits: float | None = None, post: Callable[..., tuple[int, bytes]] = http_post,
        transcoder: Callable[[Path, Path], Path] = transcode, environ: dict[str, str] | None = None) -> dict[str, Any]:
    """Write ``out`` and return the record.  Never raises; status OK | SKIPPED | ERROR."""
    env = os.environ if environ is None else environ
    model = model or env.get("NALU_GEMINI_REVIEW_MODEL") or DEFAULT_MODEL
    cap = max_credits if max_credits is not None else float(env.get("NALU_GEMINI_REVIEW_MAX_CREDITS")
                                                             or MAX_CREDITS_DEFAULT)
    preferred = fps or float(env.get("NALU_GEMINI_REVIEW_FPS") or DEFAULT_FPS)
    record: dict[str, Any] = {"schema": SCHEMA, "tool": TOOL_ID, "recorded_at": _now(), "model": model,
                              "authority": "ADVISORY_NOT_A_GATE: Codex verifies every finding; a failure never blocks",
                              "request": str(request_path), "request_sha256": _sha(request_path)}

    def finish(status: str, **extra: Any) -> dict[str, Any]:
        record.update({"status": status, **extra})
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".part")
            tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, out)
        except OSError as exc:
            record["write_error"] = str(exc)[:200]
        return record

    try:
        if str(env.get("NALU_GEMINI_REVIEW") or "").strip().lower() in ("off", "0", "false"):
            return finish("SKIPPED", reason="DISABLED_BY_NALU_GEMINI_REVIEW")
        request = json.loads(request_path.read_text(encoding="utf-8"))
        media = request.get("media") or {}
        video = Path(str(media.get("path") or ""))
        record["final_video_sha256"] = media.get("sha256")
        if not video.is_file() or _sha(video) != media.get("sha256"):
            return finish("SKIPPED", reason="FINAL_VIDEO_MISSING_OR_SHA_CHANGED")
        key, source = resolve_key(env)
        record["key_source"] = source
        if not key:
            return finish("SKIPPED", reason="NO_HOPSAPI_KEY")
        duration = float((request.get("objective_summary") or {}).get("duration_seconds") or 0) or media_duration(video)
        measurements = ((request.get("qa_defect_checklist_request") or {}).get("measurements") or {})
        prompt, suspects = build_prompt(duration=duration, pack_summary=_pack_summary(request),
                                        measurements=measurements, anime=request.get("render_style") == "anime")
        chosen = choose_fps(model, duration, len(prompt), cap, preferred)
        estimate = estimate_credits(model, duration, len(prompt), chosen or min(FPS_STEPS))
        record.update({"duration_s": round(duration, 2), "estimated_credits": estimate, "max_credits": cap})
        if chosen is None:
            return finish("SKIPPED", reason="ESTIMATE_OVER_BUDGET")
        record["fps"] = chosen
        with tempfile.TemporaryDirectory(prefix="nalu_gemini_") as tmp:
            small = transcoder(video, Path(tmp) / "review_432x768.mp4")
            if small.stat().st_size > MAX_UPLOAD_BYTES and transcoder is transcode:
                small = transcode(video, Path(tmp) / "review_432x768_crf34.mp4", crf=34)
            if small.stat().st_size > MAX_UPLOAD_BYTES:
                return finish("SKIPPED", reason="UPLOAD_TOO_LARGE", upload_bytes=small.stat().st_size)
            data = small.read_bytes()
        record["upload_bytes"] = len(data)
        base = (env.get("HOPSAPI_BASE_URL") or DEFAULT_BASE_URL)
        result = call_gemini(video_bytes=data, prompt=prompt, model=model, fps=chosen, key=key, base_url=base,
                             post=post)
        usage = (result["payload"] or {}).get("usageMetadata") or {}
        record.update({"latency_s": result["latency_s"], "http_status": result["http_status"],
                       "usage": {k: usage.get(k) for k in ("promptTokenCount", "candidatesTokenCount",
                                                            "thoughtsTokenCount", "totalTokenCount")},
                       "cost_credits": actual_credits(model, usage) if usage else 0.0})
        if result["http_status"] != 200:
            return finish("ERROR", reason=f"HTTP_{result['http_status']}", error_body=result["error_body"])
        text = response_text(result["payload"])
        try:
            parsed = parse_answer(text, duration=duration, suspects=suspects)
        except (ValueError, TypeError) as exc:
            return finish("ERROR", reason=f"UNPARSABLE_ANSWER:{type(exc).__name__}", raw_text=text[:2000])
        return finish("OK", **parsed, prompt_chars=len(prompt))
    except Exception as exc:  # noqa: BLE001 -- advisory: record and move on
        return finish("ERROR", reason=f"{type(exc).__name__}:{str(exc)[:200]}")


def summary_lines(record: dict[str, Any]) -> list[str]:
    """Short human lines (the reviewer prompt / logs); no key, no dialogue beyond the model's own notes."""
    if record.get("status") != "OK":
        return [f"Gemini 视频终审未运行或失败：{record.get('status')} {record.get('reason') or ''}".strip()]
    out = [f"Gemini 视频终审（{record.get('model')}，{record.get('cost_credits')} credits）："
           f"{len(record.get('findings') or [])} 条发现，{len(record.get('suspect_checks') or [])} 个本地可疑点复核"]
    for f in (record.get("findings") or [])[:40]:
        out.append(f"- {f['id']} {f['item']} {f['start']}-{f['end']}s {f['severity']}: {f['description'][:80]}")
    for c in (record.get("suspect_checks") or [])[:30]:
        where = c["suspect"].get("at", c["suspect"].get("window"))
        out.append(f"- {c['id']} @ {where}: {c['decision']} {str(c.get('reason') or '')[:60]}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--request", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--fps", type=float, default=None)
    ap.add_argument("--max-credits", type=float, default=None)
    args = ap.parse_args(argv)
    record = run(request_path=args.request, out=args.out, model=args.model, fps=args.fps, max_credits=args.max_credits)
    print(json.dumps({k: record.get(k) for k in ("status", "reason", "model", "fps", "cost_credits", "latency_s")}
                     | {"findings": len(record.get("findings") or [])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
