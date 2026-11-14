#!/usr/bin/env python3
"""Run the NALU production contract with the OpenAI Codex CLI (the miniPC executor since 2026-10-13).

  start  --episode E02 [--brief <file>]   launch ``codex exec`` in the background with the contract
  resume --episode E02 --message <text>   continue the same Codex thread (``codex exec resume``)
  status --episode E02                    alive?  Codex's last NALU_STATUS?  pipeline stage states
  tick                                    the heartbeat: does every routine step itself and prints one
                                          ``NALU_TICK: {...}`` line telling the agent whether it is needed
  report                                  compact progress summary for the line owner

Line owner 2026-10-12/13: Claude Code is retired on the miniPCs (E01 cost about $208 through the relay);
Codex (gpt-6.1-sol by default) runs S1-S7.  Written and run on 新石头记 E02-E03 by the miniPC agent, folded in here.

Compatibility:
* Runs live in ``$NALU_RUNTIME_ROOT/claude_code/<EP>/`` (session.json + run_<ts>.jsonl).  When Codex exits,
  the runner appends ``{"type":"result","result":<Codex's last message verbatim>,...,"engine":"codex"}``
  so setup_host.sh / self_update.sh (claude_production.parse_log) still recognise an episode in flight.
* Provider: ``$NALU_RUNTIME_ROOT/credentials/llm_provider.json`` (base_url / api_key / model, mode 600,
  written by the agent from the owner's message); ``credentials/codex_api_key`` is the older layout.
  The key reaches codex only as $HOPS_API_KEY (the env_key configure_codex.py writes); the shell
  policy in ~/.codex/config.toml keeps it and GIGGLE_API_KEY out of every command Codex runs.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
STATUS_RE = re.compile(r"NALU_STATUS:\s*(\{.*\})")
KEY_ENV = "HOPS_API_KEY"
QUOTA_RE = re.compile(r"\b(401|402|403|429)\b|quota|insufficient|balance|余额|额度|invalid[_ ]api[_ ]key", re.I)
#: A transient provider throttle, not an exhausted account: the system tick resumes Codex itself after a jittered
#: backoff (fleet 2026-11-14: 19/20 devices exited on "exceeded retry limit, last status: 429 Too Many Requests"
#: and sat idle waiting for the 6-hourly agent heartbeat).  Hard quota / auth errors still go to the agent.
RATE_LIMIT_RE = re.compile(r"\b429\b|too many requests|rate[ _-]?limit", re.I)
HARD_QUOTA_RE = re.compile(r"\b(401|402|403)\b|insufficient|balance|余额|额度|quota exceeded|invalid[_ ]api[_ ]key", re.I)
RATE_LIMIT_MAX_RESUMES = 12
MAX_NO_STATUS_RESUMES = 3


def rate_limit_backoff_s(attempt: int) -> float:
    """Jittered backoff before the n-th (1-based) automatic resume after a provider throttle: 5-15 min, growing
    to at most 30 min, so a throttled fleet does not come back in lockstep."""
    import random  # noqa: PLC0415
    base = 300 * (2 ** max(0, attempt - 1))
    return min(base * random.uniform(1.0, 3.0), 1800 * random.uniform(0.85, 1.0))


def roots() -> tuple[Path, Path]:
    engine = Path(os.environ.get("NALU_ENGINE_ROOT") or "~/nalu_engine").expanduser()
    runtime = Path(os.environ.get("NALU_RUNTIME_ROOT") or "~/nalu_runtime").expanduser()
    return engine, runtime


def contract_path() -> Path:
    pinned = roots()[0] / "skills" / "nalu-claude-code" / "CLAUDE_CODE_PRODUCTION.md"
    return pinned if pinned.is_file() else HERE.parent / "CLAUDE_CODE_PRODUCTION.md"


def run_dir(episode: str) -> Path:
    d = roots()[1] / "claude_code" / episode
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # a zombie (exited, not yet reaped) is not a live run
        if Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].startswith("Z"):
            return False
    except (OSError, IndexError):
        pass
    return True


#: provider keys never handed to Codex (its own key goes in as KEY_ENV, which config.toml excludes from shells)
SECRET_ENV_NAMES = ("GIGGLE_API_KEY", "HOPSAPI_API_KEY", "X2C_API_KEY", "OPENAI_API_KEY")


CODEX_ADAPTER = """
## 执行者适配（编排代理附加，优先于合同里的工具名）
你是 OpenAI Codex CLI，不是 Claude Code；合同正文按 Claude Code 写成，按下面对应：
- 「用 Read 打开图片」= 用你的 view_image 工具打开图片。审核必须真的打开图片/联系表看过再答，不准凭文件名、提示词或日志推断。
- 视频先用 ffmpeg 抽帧拼联系表，再用 view_image 看。
- **只看缩小后的图**：任何图片（关键帧、身份牌、联系表）先用 ffmpeg 缩到长边 ≤1280 px、存成 JPEG（`-q:v 4`）再 view_image；
  不要直接 view_image 原尺寸 PNG（E02 曾被 128 MB 的全尺寸 PNG 请求体卡成死循环）。
- 编辑文件用 apply_patch 或 shell；长等待用 `sleep 240`（合同 §4 S6）。
- 审核协议 `vlm_review_protocol.py` 在代码里强制 `reviewer` 必须是 `claude-code-nalu-vlm`、`review_method` 必须是
  `CLAUDE_VLM_STRUCTURED_REVIEW`：这是本线「机器审核者」的协议常量，照填；每条审核答案的 observation 末尾加「（执行者：Codex）」以便溯源。
- 记订单时 `--recorded-by codex`（不要写 claude-code）。
- **密钥硬规则**：绝不读取或打印 `.env`/`.env.*`、`credentials/` 下文件、`*.key`/`*.pem`、`~/.codex`、`~/.claude`、`~/.ssh`；不跑 `env`/`printenv`/`set`/`export -p`/`echo $..._API_KEY`，不把 key 写进日志、报告或 NALU_STATUS。要确认 key 在不在只用 `./lines/nalu/runtime/tools/paid_stage.sh --check <EP>`（只报有/无）。付费只走 `paid_stage.sh`（它自己读 `.env`）。
- 必须在 `$NALU_ENGINE_ROOT` 下执行。
- 本轮最后一条消息的最后一行必须是合同 §6 的 `NALU_STATUS: {...}`（单行 JSON）。
"""


# ---------------------------------------------------------------------------------- independent final review
# Line owner 2026-11-09: the S7 final-audience review is run by an engine-launched, separate `codex exec`
# process (fresh thread, fixed reviewer instructions, gpt-6.1-sol via the line's HopsAPI provider) instead of a
# StoryClaw sub-agent the heartbeat had to remember to spawn (field device …1324 E02/E03: the review sat for
# hours twice).  The producer never sees or writes the answers; the reviewer submits them itself.
REVIEWER_MODEL = "gpt-6.1-sol"
REVIEWER_MODEL_ID = f"hopsapi/{REVIEWER_MODEL}"   # declared in the answers; allow-listed in final_audience_review
MAX_REVIEWER_ATTEMPTS = 2
REVIEW_REQUIRED_CODE = 10   # final_audience_review.py status: request prepared, no submitted review yet


def reviewer_prompt(episode: str, request: Path, answers: Path, process_id: str, submit_cmd: str) -> str:
    return f"""你是 NALU 短剧 {episode} 的**独立终审审核者**（观众视角），不是生产者。你只看成片和审核请求，不看、不信任何生产记录里的结论。

1. 读审核请求：`{request}`。里面的 `reviewer_contract`、`viewing_passes_required`、`shots`、`dimension_questions`、
   `subjective_checks_required`、`answer_contract` 就是你要做的全部；`media.path` 是成片（sha 已绑定）。
2. 真看成片（不准凭文件名、日志或解码器退出码推断）：
   - 有声 1x：用 ffmpeg 每 1 秒抽一帧（缩到长边 ≤1280、JPEG `-q:v 4`，放在 `$TMPDIR` 下你自己的目录），按时间顺序用 view_image 看完，
     同时对照 `evidence.asr` 的台词和时间；`evidence.contact_sheet` 也要看。
   - 静音：只凭画面判断动作是否看得懂、连贯、有没有穿帮（人数、手、身份、昼夜、跳变）。
   - 只听：读 ASR，用 `ffmpeg -af ebur128`、`silencedetect`、`volumedetect`、`astats` 等测音频，判断对白清晰度、混音、节奏。
   - 你没有耳朵：上面这套「ASR 文本 + 音频测量 + 逐帧画面」**就是**本审核规定的有声 1x 与只听方式。照做了就把
     `viewing_passes` 的 `full_1x` / `muted` / `sound` 都写 `completed: true`，`observation` 写清你实际看了哪些帧、
     测了哪些量、读到了什么（三项各写各的，不要抄同一段）。不要因为「无法真正听见」而写 false——那只会让提交无效、
     这一集卡死（…1324 E04 2026-11-10 两次提交都因此 INVALID）。拿不准的听感问题写进 problems，并据此打分。
3. 逐镜（`shots` 里每一个 shot_index）写你自己看到的内容；八项打 1–5 分并写依据；整体分单独给（不是平均）；
   每个 `subjective_checks_required` 给布尔值和依据；把观众看得见的剧情事件按时间写进 events；问题按 P0–P3 写进 problems。
   如实判断：有穿帮就判低分，判拒（REJECT_RECUT）也是正常结论，不要为了通过而改判。
4. 按 `answer_contract` 写答案 JSON 到 `{answers}`，其中：
   `reviewer.agent_id` = `storyclaw-final-audience-reviewer`，`reviewer.role` = `independent_final_audience_reviewer`，
   `reviewer.model` = `{REVIEWER_MODEL_ID}`，`reviewer.process_id` = `{process_id}`，`reviewer.reviewed_at` = 当前 UTC ISO 时间；
   `request_sha256` 用 `sha256sum` 算请求文件。
5. 自己提交：`{submit_cmd}`。退出码 0（通过）或 3（判拒）都算完成；其它退出码就读输出、修正答案格式后再提交一次。
6. 只允许写 `{answers}` 和你在 `$TMPDIR` 下的临时目录；不改引擎、剧本、订单、成片或任何其它文件；不读任何密钥文件。
最后一行输出：`REVIEW_SUBMITTED: {{"exit_code": <submit 退出码>, "verdict": "<PASS|REJECT_RECUT|...>"}}`
"""


def _review_paths(episode: str) -> tuple[Path, Path]:
    _, runtime = roots()
    base = runtime / "runtime" / "reviews" / episode
    return base / "final_audience_request.json", base / "final_audience_answers.json"


def review_status_code(episode: str) -> int:
    engine, runtime = roots()
    venv = engine / ".qingshan-venv" / "bin" / "python"
    tool = engine / "lines" / "nalu" / "runtime" / "tools" / "final_audience_review.py"
    # pass the roots explicitly: the heartbeat cron runs tick without NALU_RUNTIME_ROOT, and a machine without
    # .nalu_deployment.json then resolved another runtime and read 4 (PREPARE_REQUIRED) instead of 10
    # (field device …1324 E03, 2026-11-09: the producer was woken instead of the reviewer being launched)
    env = {**os.environ, "NALU_ENGINE_ROOT": str(engine), "NALU_RUNTIME_ROOT": str(runtime),
           "NALU_WORK_ROOT": os.environ.get("NALU_WORK_ROOT") or str(engine / "workflow" / "nalu")}
    try:
        return subprocess.run([str(venv if venv.is_file() else sys.executable), str(tool), "status", "--episode", episode],
                              cwd=engine, capture_output=True, text=True, timeout=600, env=env).returncode
    except (OSError, subprocess.SubprocessError):
        return -1


#: bump when reviewer_prompt changes in a way that can turn an EXHAUSTED review into a valid one; an updated
#: engine then gets a fresh set of reviewer attempts for the same request (…1324 E04: the sound pass rule)
REVIEWER_PROMPT_VERSION = "2"


def launch_reviewer(episode: str) -> dict[str, Any]:
    """Start (at most MAX_REVIEWER_ATTEMPTS times) the independent final-audience reviewer for one episode."""
    env = codex_env()
    exe = codex_exe(env)
    if not exe or env is None:
        return {"status": "BLOCKED", "reason": "CODEX_OR_PROVIDER_MISSING"}
    engine, _ = roots()
    d = run_dir(episode) / "final_reviewer"
    d.mkdir(parents=True, exist_ok=True)
    state = read_json(d / "reviewer.json")
    if alive(state.get("pid")):
        return {"status": "RUNNING", "pid": state.get("pid"), "log": state.get("log")}
    request, answers = _review_paths(episode)
    if not request.is_file():
        return {"status": "BLOCKED", "reason": f"REVIEW_REQUEST_MISSING:{request}"}
    request_sha = _file_sha(request)
    if state.get("request_sha256") != request_sha or state.get("prompt_version") != REVIEWER_PROMPT_VERSION:
        # a new cut / new request, or a fixed reviewer prompt from an engine update: a fresh set of attempts
        state = {"request_sha256": request_sha, "prompt_version": REVIEWER_PROMPT_VERSION,
                 "resumes": state.get("resumes") or {}}
    attempts = int(state.get("attempts") or 0)
    if attempts >= MAX_REVIEWER_ATTEMPTS:
        return {"status": "EXHAUSTED", "attempts": attempts, "log": state.get("log")}
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    process_id = f"codex-final-reviewer-{episode}-{ts}"
    venv = engine / ".qingshan-venv" / "bin" / "python"
    submit_cmd = (f"{venv} {engine}/lines/nalu/runtime/tools/final_audience_review.py submit --episode {episode} "
                  f"--request {request} --answers {answers}")
    pfile, log, last = d / f"review_{ts}.prompt.md", d / f"review_{ts}.jsonl", d / f"review_{ts}.last.txt"
    pfile.write_text(reviewer_prompt(episode, request, answers, process_id, submit_cmd), encoding="utf-8")
    argv = [exe, "exec", "--json", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check",
            "-m", REVIEWER_MODEL, "-o", str(last), "-"]
    with open(log, "w", encoding="utf-8") as out, open(pfile, encoding="utf-8") as stdin:
        proc = subprocess.Popen(argv, cwd=engine, stdout=out, stderr=subprocess.DEVNULL, stdin=stdin, env=env,
                                start_new_session=True)
    state.update({"pid": proc.pid, "attempts": attempts + 1, "log": str(log), "process_id": process_id,
                  "model": REVIEWER_MODEL_ID, "started_at": datetime.now(timezone.utc).isoformat()})
    write_json(d / "reviewer.json", state)
    note(f"{episode} 独立终审：引擎启动审核者（{REVIEWER_MODEL_ID}，第 {attempts + 1} 次，pid {proc.pid}）")
    return {"status": "STARTED", "pid": proc.pid, "attempt": attempts + 1, "log": str(log)}


MAX_RESUMES_AFTER_REVIEW = 2


def _file_sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def final_review_step(episode: str) -> dict[str, Any]:
    """FINAL_REVIEW_REQUIRED: launch / wait for the reviewer; RESUME once a review is on record (twice at most
    per request, so a producer that keeps stopping here goes to the agent instead of looping)."""
    path = run_dir(episode) / "final_reviewer" / "reviewer.json"
    state = read_json(path)
    if alive(state.get("pid")):
        return {"status": "RUNNING"}
    code = review_status_code(episode)
    if code != REVIEW_REQUIRED_CODE:
        request_sha = _file_sha(_review_paths(episode)[0])
        resumes = state.get("resumes") or {}
        if int(resumes.get(request_sha) or 0) >= MAX_RESUMES_AFTER_REVIEW:
            return {"status": "PRODUCER_STILL_STOPPED", "review_status_code": code}
        resumes[request_sha] = int(resumes.get(request_sha) or 0) + 1
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, {**state, "resumes": resumes})
        return {"status": "RESUME_PRODUCER", "review_status_code": code}
    return launch_reviewer(episode)


def provider() -> dict[str, str] | None:
    _, runtime = roots()
    cred = runtime / "credentials"
    p = read_json(cred / "llm_provider.json")
    if p.get("api_key"):
        return {k: str(v) for k, v in p.items()}
    try:
        key = (cred / "codex_api_key").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return {"api_key": key} if key else None


def codex_env() -> dict[str, str] | None:
    p = provider()
    if not p:
        return None
    engine, runtime = roots()
    env = dict(os.environ)
    # provider keys stay out of Codex's process; paid_stage.sh loads them from .env for the paid child
    for name in SECRET_ENV_NAMES:
        env.pop(name, None)
    env[KEY_ENV] = p["api_key"]
    env.setdefault("NALU_ENGINE_ROOT", str(engine))
    env.setdefault("NALU_RUNTIME_ROOT", str(runtime))
    env.setdefault("NALU_WORK_ROOT", str(engine / "workflow" / "nalu"))
    env.setdefault("NALU_QA_WORKERS", "1")
    env.setdefault("NALU_Q2_WORKERS", "1")
    lookup = ":".join([*tool_dirs(), env.get("PATH", "")])
    # codex is `#!/usr/bin/env node`: the first node on PATH runs it, so the newest node's directory goes first.
    # …1101: a recorded /usr/bin (node v12) sat ahead of nvm's v22 and every cron resume died at codex.js:2.
    # The codex executable itself is still resolved in the original order (CODEX_LOOKUP_PATH).
    best = newest_node_dir(lookup.split(":"))
    env["PATH"] = ":".join([best, lookup]) if best else lookup
    env[CODEX_LOOKUP_ENV] = lookup
    return env


CODEX_LOOKUP_ENV = "NALU_CODEX_LOOKUP_PATH"


def codex_exe(env: dict[str, str] | None) -> str | None:
    """The first codex on the lookup path that actually starts (`codex --version` exits 0).  Field device …1101
    2026-11-11: ~/.npm-global/bin/codex was a broken install ("Missing optional dependency
    @openai/codex-linux-x64") ahead of the working nvm one, so every cron resume died at once."""
    env = env or dict(os.environ)
    lookup = env.get(CODEX_LOOKUP_ENV) or env.get("PATH") or ""
    candidates = [str(Path(d) / "codex") for d in dict.fromkeys(lookup.split(":"))
                  if d and os.access(Path(d) / "codex", os.X_OK) and not (Path(d) / "codex").is_dir()]
    for exe in candidates:
        try:
            if subprocess.run([exe, "--version"], env=env, capture_output=True, timeout=30).returncode == 0:
                return exe
        except (OSError, subprocess.SubprocessError):
            continue
    return candidates[0] if candidates else None


def tool_dirs() -> list[str]:
    """Where codex / node live on this host: the user bins, the directories setup_host.sh recorded in
    ~/.nalu_tool_path while the agent's full PATH was visible, and any nvm node bin (the system cron runs with a
    bare PATH; …1037 / …0899 2026-11-10 fleet resume failed CODEX_NOT_INSTALLED)."""
    home = Path.home()
    dirs = [str(home / ".local/bin"), str(home / ".npm-global/bin")]
    try:
        dirs += [d for d in (home / ".nalu_tool_path").read_text(encoding="utf-8").strip().split(":") if d]
    except OSError:
        pass
    dirs += sorted((str(p) for p in home.glob(".nvm/versions/node/*/bin")), reverse=True)
    dirs += gateway_path_dirs()
    return list(dict.fromkeys(dirs))


def newest_node_dir(candidates: list[str]) -> str:
    """The directory holding the highest-version `node` among the candidates ("" if none answers)."""
    best, best_version = "", (0,)
    for d in dict.fromkeys(c for c in candidates if c):
        node = Path(d) / "node"
        if not node.exists():
            continue
        try:
            out = subprocess.run([str(node), "-v"], capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
        m = re.match(r"v(\d+)\.(\d+)\.(\d+)", out)
        version = tuple(int(x) for x in m.groups()) if m else (0,)
        if version > best_version:
            best, best_version = d, version
    return best


def gateway_path_dirs() -> list[str]:
    """PATH entries of this user's running OpenClaw gateway (Linux /proc).  The gateway runs the agent with the
    node that codex needs; under the system cron /usr/bin/node was an old one and codex.js died at line 2
    (…0899 / …1037 / …1101 2026-11-10: every cron resume "STARTED" and exited at once)."""
    out: list[str] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return out
    uid = os.getuid()
    for pid_dir in proc.iterdir():
        if not pid_dir.name.isdigit():
            continue
        try:
            if pid_dir.stat().st_uid != uid:
                continue
            cmd = (pid_dir / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
            if "openclaw" not in cmd:
                continue
            env = (pid_dir / "environ").read_bytes().split(b"\0")
        except OSError:
            continue
        for item in env:
            if item.startswith(b"PATH="):
                out += [d for d in item[5:].decode(errors="ignore").split(":")
                        if d and (Path(d) / "node").exists()]
        if out:
            break
    return out


def runner(episode: str, log: str, last: str, argv_json: str) -> int:
    """Background runner: run codex, then append its last message verbatim as a Claude-compatible result line."""
    argv = json.loads(argv_json)
    env = codex_env() or dict(os.environ)
    engine, _ = roots()
    with open(log, "a", encoding="utf-8") as out:
        rc = subprocess.call(argv, cwd=engine, stdout=out, stderr=subprocess.DEVNULL, env=env,
                             stdin=subprocess.DEVNULL)
    thread_id = None
    usage: dict[str, int] = {}
    err_msg = None
    for line in Path(log).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "thread.started":
            thread_id = ev.get("thread_id")
        if ev.get("type") == "turn.completed":
            for k, v in (ev.get("usage") or {}).items():
                if isinstance(v, int):
                    usage[k] = usage.get(k, 0) + v
        if ev.get("type") == "turn.failed":
            err_msg = json.dumps(ev.get("error"), ensure_ascii=False)[:500]
    try:
        last_text = Path(last).read_text(encoding="utf-8")
    except FileNotFoundError:
        last_text = ""
    result = {"type": "result", "engine": "codex", "session_id": thread_id, "exit_code": rc,
              "is_error": bool(rc != 0 or err_msg), "error": err_msg,
              "result": last_text[-3000:], "usage": usage,
              "finished_at": datetime.now(timezone.utc).isoformat()}
    with open(log, "a", encoding="utf-8") as out:
        out.write(json.dumps(result, ensure_ascii=False) + "\n")
    d = run_dir(episode)
    s = read_json(d / "session.json")
    if thread_id and not s.get("codex_thread_id"):
        s["codex_thread_id"] = thread_id
        s["session_id"] = thread_id
        write_json(d / "session.json", s)
    return rc


def launch(episode: str, prompt: str, resume_id: str | None) -> dict[str, Any]:
    env = codex_env()
    exe = codex_exe(env)
    if not exe:
        return {"status": "BLOCKED", "reason": "CODEX_NOT_INSTALLED"}
    if env is None:
        return {"status": "BLOCKED", "reason": "LLM_PROVIDER_MISSING"}
    d = run_dir(episode)
    session = read_json(d / "session.json")
    if alive(session.get("pid")):
        return {"status": "ALREADY_RUNNING", "pid": session.get("pid"), "log": session.get("log")}
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log = d / f"run_{ts}.jsonl"
    last = d / f"run_{ts}.last.txt"
    pfile = d / f"run_{ts}.prompt.md"
    pfile.write_text(prompt, encoding="utf-8")
    common = ["--json", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check", "-o", str(last)]
    argv = [exe, "exec", "resume", *common, resume_id, "-"] if resume_id else [exe, "exec", *common, "-"]
    # the contract is long: feed the prompt on stdin from a file instead of argv
    argv = ["/bin/sh", "-c", 'exec "$0" "$@" < "$NALU_CODEX_PROMPT_FILE"', *argv]
    env["NALU_CODEX_PROMPT_FILE"] = str(pfile)
    log.write_text("", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_run", "--episode", episode,
                             "--log", str(log), "--last", str(last), "--argv", json.dumps(argv)],
                            cwd=roots()[0], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, env=env, start_new_session=True)
    session.update({"episode": episode, "engine": "codex", "pid": proc.pid, "log": str(log),
                    "started_at": datetime.now(timezone.utc).isoformat(), "resumed_from": resume_id})
    if not resume_id:
        session.pop("codex_thread_id", None)
        session["session_id"] = None
        session["no_status_resumes"] = 0
    write_json(d / "session.json", session)
    return {"status": "STARTED", "engine": "codex", "pid": proc.pid, "log": str(log), "resumed_from": resume_id}


def parse_log(log: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"session_id": None, "result": None, "is_error": None, "nalu_status": None,
                            "last_assistant_text": None, "events": 0, "usage": {}, "last_error": None}
    if not log.is_file():
        return info
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        info["events"] += 1
        t = ev.get("type")
        if t == "thread.started":
            info["session_id"] = ev.get("thread_id")
        elif t == "item.completed":
            it = ev.get("item") or {}
            if it.get("type") == "agent_message" and it.get("text"):
                info["last_assistant_text"] = it["text"][-1500:]
        elif t == "turn.completed":
            for k, v in (ev.get("usage") or {}).items():
                if isinstance(v, int):
                    info["usage"][k] = info["usage"].get(k, 0) + v
        elif t in ("error", "turn.failed"):
            info["last_error"] = (ev.get("message") or json.dumps(ev.get("error"), ensure_ascii=False))[:300]
        elif t == "result":
            info["result"] = str(ev.get("result") or "")[-3000:]
            info["is_error"] = ev.get("is_error")
            info["session_id"] = ev.get("session_id") or info["session_id"]
            if ev.get("engine") != "codex":  # a Claude Code run (before the switch)
                for k in ("input_tokens", "output_tokens"):
                    v = (ev.get("usage") or {}).get(k)
                    if isinstance(v, int):
                        info["usage"][k] = info["usage"].get(k, 0) + v
    text = info["result"] or info["last_assistant_text"] or ""
    found = STATUS_RE.findall(text)
    if found:
        try:
            info["nalu_status"] = json.loads(found[-1])
        except ValueError:
            info["nalu_status"] = {"raw": found[-1]}
    return info


def pipeline_status(episode: str) -> dict[str, Any]:
    _, runtime = roots()
    state = read_json(runtime / "runtime" / "pipeline_state" / f"{episode}.json")
    stages = state.get("stages") or {}
    return {sid: {"status": row.get("status"), "blockers": (row.get("blockers") or [])[:3]}
            for sid, row in stages.items()}


def build_prompt(episode: str, brief: str) -> str:
    return (f"你是 NALU 短剧生产线的生产执行者。严格按照下面的生产合同执行集 {episode}。\n\n"
            + contract_path().read_text(encoding="utf-8") + "\n" + CODEX_ADAPTER
            + (f"\n\n## 本次线主/编排代理附加说明\n{brief}" if brief else ""))


def start(episode: str, brief: str = "") -> dict[str, Any]:
    if not contract_path().is_file():
        return {"status": "BLOCKED", "reason": f"CONTRACT_MISSING:{contract_path()}"}
    out = launch(episode, build_prompt(episode, brief), None)
    if out.get("status") == "STARTED":
        series = roots()[1] / "series"
        series.mkdir(parents=True, exist_ok=True)
        (series / "CURRENT_EPISODE").write_text(episode + "\n", encoding="utf-8")
    return out


def next_episode_id(episode: str) -> str:
    m = re.fullmatch(r"([A-Za-z]*)(\d+)", episode.strip())
    if not m:
        return ""
    return f"{m.group(1)}{int(m.group(2)) + 1:0{len(m.group(2))}d}"


NEXT_EPISODE_BRIEF = """本集由引擎在上一集出片后自动接续（线主 + 老板 2026-11-10：下一集的派单与叙事正典交给你写，不再由编排代理写）。先写派单，再生产：
1. 读上一集派单 `{prev}`，以及上一集 {ep} 的叙事正典与剧本层的结尾、`{status}` 最近几条。
2. 按上一集派单的条款写 `{brief}`：`order_text` 里的集号与上限改成 {nxt}，章节范围从上一集结束处接上；生产简报里的
   `episode_display_number`（片头片尾与 X2C 发行用的「本剧第几集」）必须是 **{display}**，不得沿用上一集的值；剧名、风格、单集时长
   （`target_seconds`）、X2C 分类与简介、语言、预算上限等其它条款逐字沿用，不自行改动。
3. 原著已经改编完，或已达到线主在派单里指定的总集数：不生产，写 `{done}`（一行说明），在 `{status}` 记一行「SERIES_DONE」，
   最后一行输出 `NALU_STATUS: {{"episode":"{nxt}","state":"SERIES_DONE"}}`。
4. 否则按 `{skill}` §4 写本集叙事正典与生产简报（承接上一集结尾，角色、地点沿用，按合同 §8），然后按合同生产 {nxt}。
"""


def start_next_episode(episode: str) -> dict[str, Any]:
    """FINAL_CUT_READY -> scripted engine update (between episodes is the only safe moment), then a new Codex
    session that writes the next dispatch from the previous one and produces it.  No model on the routine path."""
    engine, runtime = roots()
    nxt = next_episode_id(episode)
    briefs = runtime / "briefs"
    prev = briefs / f"{episode}_DISPATCH.md"
    if not nxt:
        return {"status": "BLOCKED", "reason": "EPISODE_ID_UNPARSEABLE", "episode": episode}
    if read_json(run_dir(nxt) / "session.json"):
        return {"status": "BLOCKED", "reason": "NEXT_EPISODE_ALREADY_HAS_A_SESSION", "episode": nxt}
    if not prev.is_file():
        return {"status": "BLOCKED", "reason": "PREVIOUS_DISPATCH_MISSING", "episode": nxt, "expected": str(prev)}
    update: dict = {}
    try:
        import fleet_sync  # noqa: PLC0415
        ok, update, _ = fleet_sync.scripted_update(sys.modules[__name__], "")
        note(f"{episode}→{nxt} 集间升级：{'OK' if ok else 'SETUP_NOT_READY'} 引擎 {update.get('before')}→{update.get('after')}")
    except Exception as exc:  # noqa: BLE001 -- an update failure must not stop the line; the old engine keeps working
        update = {"error": f"{type(exc).__name__}: {exc}"}
    briefs.mkdir(parents=True, exist_ok=True)
    # 本剧第几集: the previous brief's display number + 1 (…1284 E04 copied E03's 3 and X2C refused the release as
    # EPISODE_NUMBER_TAKEN); without a previous number, the EP number
    prev_brief = read_json(briefs / f"{episode}_PRODUCTION_BRIEF.json")
    try:
        display = int(prev_brief.get("episode_display_number")) + 1
    except (TypeError, ValueError):
        display = int(re.sub(r"\D", "", nxt) or 0)
    brief = NEXT_EPISODE_BRIEF.format(display=display,
        prev=prev, ep=episode, nxt=nxt, brief=briefs / f"{nxt}_DISPATCH.md", done=runtime / "series" / "SERIES_DONE",
        status=runtime / "series" / "STATUS.md", skill=engine / "skills" / "nalu-claude-code" / "SKILL.md")
    out = start(nxt, brief)
    if out.get("status") == "STARTED":
        note(f"{nxt} 由引擎自动启动（Codex 写派单与叙事正典后生产），上一集 {episode}")
    return {**out, "episode": nxt, "update": {k: update.get(k) for k in ("before", "after", "setup_status", "error")}}


def resume(episode: str, message: str) -> dict[str, Any]:
    d = run_dir(episode)
    session = read_json(d / "session.json")
    if session.get("engine") != "codex":
        return {"status": "BLOCKED", "reason": "EPISODE_WAS_NOT_STARTED_WITH_CODEX_USE_start"}
    sid = session.get("codex_thread_id") or parse_log(Path(session.get("log") or "")).get("session_id")
    if not sid:
        return {"status": "BLOCKED", "reason": "NO_CODEX_SESSION_TO_RESUME_RUN_start_FIRST"}
    session["codex_thread_id"] = sid
    write_json(d / "session.json", session)
    return launch(episode, message + "\n（提醒：本轮最后一行仍须是 NALU_STATUS 单行 JSON。）", sid)


def status(episode: str) -> dict[str, Any]:
    session = read_json(run_dir(episode) / "session.json")
    info = parse_log(Path(session.get("log") or ""))
    return {"status": "RUNNING" if alive(session.get("pid")) else "IDLE", "episode": episode,
            "engine": session.get("engine") or "claude", "pid": session.get("pid"), "log": session.get("log"),
            "session_id": session.get("codex_thread_id") or session.get("session_id"),
            "codex": info, "pipeline": pipeline_status(episode)}


# ------------------------------------------------------------------------------------------------ tick
def note(line: str) -> None:
    path = roots()[1] / "series" / "STATUS.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:  # a deferral repeats every heartbeat: write it once, not every 15 minutes
        last = [x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()][-1]
        if last.split(" ", 3)[-1] == line:
            return
    except (FileNotFoundError, IndexError):
        pass
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"- {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%MZ')} {line}\n")


def episode_key(ep: str) -> tuple[int, str]:
    m = re.search(r"(\d+)", ep)
    return (int(m.group(1)) if m else 0, ep)


def current_episode() -> str | None:
    runtime = roots()[1]
    try:
        ep = (runtime / "series" / "CURRENT_EPISODE").read_text(encoding="utf-8").strip()
        if ep:
            return ep
    except FileNotFoundError:
        pass
    eps = [p.parent.name for p in (runtime / "claude_code").glob("*/session.json")]
    return max(eps, key=episode_key) if eps else None


def ensure_poster(ep: str, brief: dict[str, Any]) -> dict[str, Any] | None:
    """The series poster cover (tools/series_poster.py) right before an episode goes to X2C: key art once per
    series (one paid gpt-image-2 image, only with generation.paid_requests_enabled + HopsAPI), the title set
    locally.  Never blocks the publish: without a cover the publisher falls back to its frame grab."""
    engine, runtime = roots()
    try:
        if str(engine / "tools") not in sys.path:
            sys.path.insert(0, str(engine / "tools"))
        import series_poster  # noqa: PLC0415
        result = series_poster.ensure_series_cover(engine, runtime, ep, brief)
    except Exception as exc:  # noqa: BLE001
        result = {"status": "ERROR", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    art = (result.get("art") or {}).get("status") if isinstance(result.get("art"), dict) else None
    if art in ("ART_GENERATED", "ART_ADOPTED") or result.get("status") == "RENDERED":
        note(f"系列海报封面 {ep}：{result.get('status')}（{art or '缓存'}，{result.get('placement') or ''}）")
    elif art in ("ART_RESPONSE_LOST", "ART_FAILED") or result.get("status") == "ERROR":
        note(f"系列海报封面 {ep} 未生成（{art or result.get('error')}），本集用成片取帧作封面")
    return result


def publish_next() -> dict[str, Any] | None:
    """Send the earliest finished-but-unsent episode (one per tick, in episode order).

    The file sent is publish_x2creel.default_video: <EP>_final_9x16_AD.mp4 (S7 tail-ad version) when
    present, else <EP>_final_9x16.mp4; the result carries published_video / published_variant."""
    _, runtime = roots()
    sys.path.insert(0, str(HERE))
    import publish_x2creel as px  # noqa: E402
    import publish_x2c_matrix as mx  # noqa: E402
    matrix = mx.matrix_mode()  # X2C 设备矩阵 API: clean final, series_key + episode_number from the brief
    sent = mx.sent_episodes() if matrix else (px.load_state().get("episodes") or {})
    ready = []
    for sess in (runtime / "claude_code").glob("*/session.json"):
        ep = sess.parent.name
        s = read_json(sess)
        st = (parse_log(Path(s.get("log") or "")).get("nalu_status") or {}).get("state")
        mp4 = runtime / "deliverables" / ep / f"{ep}_final_9x16.mp4"
        if st == "FINAL_CUT_READY" and mp4.is_file() and ep not in sent and not alive(s.get("pid")):
            ready.append(ep)
    if not ready:
        return None
    ep = min(ready, key=episode_key)
    brief = read_json(runtime / "briefs" / f"{ep}_PRODUCTION_BRIEF.json")
    poster = ensure_poster(ep, brief)
    args = argparse.Namespace(episode=ep, title=str(brief.get("title") or ""),
                              description=str(brief.get("synopsis") or ""), category=str(brief.get("genre") or ""),
                              lang=str(brief.get("genre_lang") or brief.get("dialogue_language") or "zh"), video="", cover="")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            out = mx.cmd_publish(args) if matrix else px.cmd_publish(args)
    except SystemExit as exc:  # the publisher reports API failures as SystemExit(<json>)
        try:
            out = json.loads(str(exc.code))
        except ValueError:
            out = {"status": "ERROR", "detail": str(exc.code)[:300]}
    out.setdefault("episode", ep)
    if poster is not None:
        out.setdefault("series_poster", {k: poster.get(k) for k in ("status", "placement") if poster.get(k)}
                       | ({"art": poster["art"].get("status")} if isinstance(poster.get("art"), dict) else {}))
    st = out.get("status")
    if st == "PUBLISHED":
        variant = "含尾贴广告版" if out.get("published_variant") == "AD" else "正片版（无广告版）"
        note(f"X2C 发行 {ep}：第 {out.get('episode_number')} 集（{out.get('x2c_status')}），{variant} "
             f"{Path(str(out.get('published_video') or '')).name}")
    elif st == "DEFERRED_PENDING_REVIEW":
        nums = [str(v.get("episode_number")) for v in out.get("pending_videos") or [] if isinstance(v, dict)]
        note(f"X2C 发行暂缓 {ep}：等待第 {','.join(nums) or '?'} 集过审，避免追加时重复发号顶掉它")
    elif st == "EPISODE_NUMBER_COLLISION":
        note(f"【需要处理】X2C {ep} 拿到第 {out.get('episode_number')} 集，与 {out.get('collides_with')} 撞号（见 SKILL.md §6）")
    elif str(out.get("reason") or "").startswith("CATEGORY_NOT_IN_X2C_LIST"):
        note(f"【需要处理】X2C {ep} 未发行：简报 genre「{brief.get('genre')}」不在 X2C 该语言的分类列表里，"
             f"按 publish_x2creel.py categories --lang <剧集语言> 的显示名改简报后再发（见 SKILL.md §6）")
    elif str(out.get("reason") or "").startswith("CATEGORY_LANGUAGE_MISMATCH"):
        note(f"【需要处理】X2C {ep} 未发行：分类「{brief.get('genre')}」的语言与剧集语言不符，"
             f"从 categories --lang <剧集语言> 里重选（见 SKILL.md §6）")
    else:
        note(f"X2C 发行 {ep} 失败：{json.dumps(out, ensure_ascii=False)[:300]}（下次心跳重试）")
    return out


def engine_modification() -> dict[str, Any] | None:
    """Tracked engine files changed on this host (the executor must never patch the engine).

    The full diff is kept in ``$NALU_RUNTIME_ROOT/engine_patches/<sha12>.patch`` so it survives the
    ``git stash`` setup_host.sh does at the next engine switch and can be reported upstream.  Returns
    {files, patch, sha} or None when the checkout is clean."""
    engine, runtime = roots()
    try:
        files = subprocess.run(["git", "-C", str(engine), "diff", "--name-only", "HEAD"],
                               capture_output=True, text=True, timeout=60).stdout.split()
        if not files:
            return None
        diff = subprocess.run(["git", "-C", str(engine), "diff", "HEAD"], capture_output=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    import hashlib
    sha = hashlib.sha256(diff).hexdigest()[:12]
    out = runtime / "engine_patches" / f"{sha}.patch"
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(diff)
    return {"files": files, "patch": str(out), "sha": sha}


# 0.9, not 1.0: the heartbeat fires every 15 min, so a strict hour slipped a whole extra cycle when the previous hand-off
# was a few seconds late (field device …1324, 2026-11-08: a fix took ~2 h to land)
BLOCKED_RECHECK_HOURS = 0.9
#: idle states handed back to the agent every BLOCKED_RECHECK_HOURS (state -> reason the agent receives)
RECHECK_STATES = {"BLOCKED": "BLOCKED_RECHECK_UPDATE", "FINAL_REVIEW_REQUIRED": "FINAL_REVIEW_REQUIRED"}


def _hours_since(stamp: Any) -> float:
    try:
        then = datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return float("inf")
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600


def tick(system: bool = False) -> dict[str, Any]:
    _, runtime = roots()
    did: list[str] = []
    res: dict[str, Any] = {"action": "NONE", "did": did}
    if not system:  # the agent heartbeat sees the full PATH: remember where codex / node live for the cron
        found = [str(Path(w).parent) for w in (shutil.which("codex"), shutil.which("node")) if w]
        if found:
            try:
                (Path.home() / ".nalu_tool_path").write_text(":".join(dict.fromkeys(found)) + "\n", encoding="utf-8")
            except OSError:
                pass
    task_path = runtime / "series" / "FLEET_AGENT_TASK.json"
    if not system and task_path.is_file():  # a maintainer instruction for the agent (fleet agent_task)
        task = read_json(task_path)
        if task.get("message") and not task.get("delivered"):
            task.update(delivered=True, delivered_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            write_json(task_path, task)
            res.update(action="AGENT", reason="FLEET_AGENT_TASK", fleet_agent_task=task["message"])
            return res
    if (runtime / "series" / "PAUSED").exists():
        res["reason"] = "PAUSED"
        return res
    modified = engine_modification()
    if modified:
        seen = runtime / "engine_patches" / ".reported"
        reported = set(seen.read_text(encoding="utf-8").split()) if seen.is_file() else set()
        if modified["sha"] not in reported:
            seen.write_text("\n".join(sorted(reported | {modified["sha"]})) + "\n", encoding="utf-8")
            note(f"【需要处理】引擎源码被改（{len(modified['files'])} 个文件），完整 diff 已存 {modified['patch']}；"
                 "不要在本机保留补丁，交给维护者修上游")
            res.update(action="AGENT", reason="ENGINE_MODIFIED_ON_HOST", engine_modification=modified)
    pub = publish_next()
    if pub:
        did.append(f"publish:{pub.get('episode')}:{pub.get('status')}")
        if pub.get("status") in ("BLOCKED", "EPISODE_NUMBER_COLLISION"):
            res.update(action="AGENT", reason=f"PUBLISH_{pub.get('status')}", publish=pub)
    ep = current_episode()
    res["episode"] = ep
    if not ep:
        res.setdefault("reason", "NO_EPISODE_STARTED")
        return res
    d = run_dir(ep)
    session = read_json(d / "session.json")
    if alive(session.get("pid")):
        res["state"] = "RUNNING"
        return res
    if session.get("engine") != "codex":  # an earlier Claude Code run, now idle: continue it with Codex
        out = start(ep, "本集此前由 Claude Code 生产、已中断；已完成的阶段流水线会自动跳过，从第一个未 PASS 的阶段继续。")
        did.append(f"start_codex:{out.get('status')}")
        if out.get("status") != "STARTED":
            res.update(action="AGENT", reason=f"START_FAILED:{out.get('reason')}")
        return res
    info = parse_log(Path(session.get("log") or ""))
    ns = info.get("nalu_status") or {}
    state = ns.get("state")
    res["state"] = state
    res["nalu_status"] = ns or None
    notify_key = f"{session.get('log')}|{state}"
    if state is not None and (session.get("no_status_resumes") or session.get("rate_limit_resumes")):
        session["no_status_resumes"] = 0
        session["rate_limit_resumes"] = 0
        write_json(d / "session.json", session)
    if state is None:
        err = " ".join(str(x) for x in (info.get("last_error"), info.get("result")) if x)
        if RATE_LIMIT_RE.search(err) and not HARD_QUOTA_RE.search(err):
            n = int(session.get("rate_limit_resumes") or 0)
            if n < RATE_LIMIT_MAX_RESUMES:
                due = session.get("rate_limit_resume_after")
                if due is None:
                    session["rate_limit_resume_after"] = time.time() + rate_limit_backoff_s(n + 1)
                    write_json(d / "session.json", session)
                if time.time() < float(session["rate_limit_resume_after"]):
                    res["reason"] = f"PROVIDER_RATE_LIMIT_BACKOFF:{int(float(session['rate_limit_resume_after']) - time.time())}s"
                    return res
                out = resume(ep, "上一轮模型接口限流（429）退出，属临时限流。请从当前阶段继续，已完成/已绑定的任务只收割不重提。")
                session = read_json(d / "session.json")
                session["rate_limit_resumes"] = n + 1
                session.pop("rate_limit_resume_after", None)
                write_json(d / "session.json", session)
                did.append(f"resume_after_rate_limit:{out.get('status')}")
                return res
            reason = f"PROVIDER_ERROR:{err[:200]}"
        elif QUOTA_RE.search(err):
            reason = f"PROVIDER_ERROR:{err[:200]}"
        elif int(session.get("no_status_resumes") or 0) < MAX_NO_STATUS_RESUMES:
            out = resume(ep, "继续，并在最后输出 NALU_STATUS 行")
            session = read_json(d / "session.json")
            session["no_status_resumes"] = int(session.get("no_status_resumes") or 0) + 1
            write_json(d / "session.json", session)
            did.append(f"resume_no_status:{out.get('status')}")
            return res
        else:
            reason = f"NO_STATUS_AFTER_{MAX_NO_STATUS_RESUMES}_RESUMES"
    elif state == "WAITING_REMOTE":
        out = resume(ep, "继续")
        did.append(f"resume_waiting_remote:{out.get('status')}")
        if out.get("status") == "STARTED":
            return res
        # the resume itself failed (e.g. CODEX_NOT_INSTALLED under the cron): surface it instead of silently
        # retrying every 3 min (…1101 sat at WAITING_REMOTE for hours)
        reason = f"RESUME_FAILED:{out.get('reason') or out.get('status')}"
    elif state == "FINAL_REVIEW_REQUIRED":
        step = final_review_step(ep)
        res["final_review"] = step
        if step["status"] in ("STARTED", "RUNNING"):
            did.append(f"final_reviewer:{step['status']}")
            return res
        if step["status"] == "RESUME_PRODUCER":
            out = resume(ep, "独立终审已由引擎启动的审核者提交（runtime/reviews/<EP>/final_audience_answers.json，"
                             "你没有写、也不要改）。按合同继续 S7：通过就放行；判拒按 §7 记 FINAL-RELEASE-DEFAULT-ACCEPTANCE 订单后放行。")
            did.append(f"resume_after_final_review:{out.get('status')}")
            return res
        reason = f"FINAL_REVIEW_REQUIRED:{step['status']}"  # reviewer exhausted / blocked: the agent takes over
    elif state == "FINAL_CUT_READY" or state == "SERIES_DONE":
        if state == "SERIES_DONE" or (runtime / "series" / "SERIES_DONE").exists():
            res["reason"] = "SERIES_DONE"
            return res
        last = session.get("next_episode_attempt_at")
        if last and _hours_since(last) < 1:
            res["reason"] = "NEXT_EPISODE_RETRY_WAIT"
            return res
        session["next_episode_attempt_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        write_json(d / "session.json", session)
        out = start_next_episode(ep)
        res["next_episode"] = out
        did.append(f"next_episode:{out.get('episode')}:{out.get('status')}")
        if out.get("status") == "STARTED":
            res["reason"] = "NEXT_EPISODE_STARTED"
            return res
        reason = f"NEXT_EPISODE_{out.get('reason') or out.get('status')}"  # the agent takes over once
    else:
        reason = state
    if session.get("tick_notified") == notify_key:  # already handed to the agent once; wait
        # BLOCKED waits on a maintainer fix that arrives as a new agent version.  An idle heartbeat never runs
        # self_update, so a blocked machine would never pick the fix up (field device …1324 E02, 2026-11-07):
        # hand BLOCKED back once an hour; the agent checks for an update and resumes when the engine changed.
        # FINAL_REVIEW_REQUIRED the same way: the review is the agent's job and a missed hand-off left E02 idle for
        # hours (field device …1324, 2026-11-07).
        if not (state in RECHECK_STATES and _hours_since(session.get("tick_notified_at")) >= BLOCKED_RECHECK_HOURS):
            res["reason"] = f"WAITING_ON_AGENT_OR_OWNER:{reason}"
            return res
        reason = RECHECK_STATES[state]
    if system:  # the system cron never consumes a hand-off meant for the agent heartbeat
        res.update(action="AGENT_PENDING", reason=reason)
        return res
    session["tick_notified"] = notify_key
    session["tick_notified_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_json(d / "session.json", session)
    res.update(action="AGENT", reason=reason)
    return res


def report() -> dict[str, Any]:
    _, runtime = roots()
    ep = current_episode()
    out: dict[str, Any] = {"episode": ep}
    if ep:
        st = status(ep)
        out.update(run=st["status"], nalu_status=st["codex"].get("nalu_status"),
                   tokens=st["codex"].get("usage"), pipeline={k: v["status"] for k, v in st["pipeline"].items()})
    spent: dict[str, Any] = {}
    for row in read_json(runtime / "runtime" / "budget" / "ledger.json").get("entries") or []:
        if row.get("episode"):
            spent[row["episode"]] = row.get("recorded_total_credits")
    out["local_spent_credits"] = spent
    sys.path.insert(0, str(HERE))
    import publish_x2creel as px  # noqa: E402
    import publish_x2c_matrix as mx  # noqa: E402
    if mx.matrix_mode():
        out["x2c_local"] = {e: {"number": r.get("episode_number"), "status": (r.get("receipt") or {}).get("review_status")}
                            for e, r in mx.sent_episodes().items()}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                st = mx.cmd_status(argparse.Namespace(series=None))
            out["x2c_remote"] = {"routing": st.get("routing_status"), "blocked": st.get("blocked_reason"),
                                 "episodes": [(e.get("episode_number"), e.get("review_status"),
                                               (e.get("matrix_jobs") or {}).get("status")) for e in st.get("episodes") or []]}
        except SystemExit as exc:
            out["x2c_remote"] = {"error": str(exc.code)[:200]}
        x2c: dict[str, Any] = {}
    else:
        x2c = px.load_state()
        out["x2c_local"] = {e: {"number": r.get("episode_number"), "status": r.get("status")}
                        for e, r in (x2c.get("episodes") or {}).items()}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            if x2c.get("project_id"):
                q = px.call("distribution/query", project_id=x2c["project_id"])
                out["x2c_remote"] = {"episodes": [(e.get("episode_number"), e.get("status")) for e in q.get("episodes") or []],
                                     "pending": [(e.get("episode_number"), e.get("status")) for e in q.get("pending_videos") or []
                                                 if isinstance(e, dict)]}
    except SystemExit as exc:
        out["x2c_remote"] = {"error": str(exc.code)[:200]}
    try:
        lines = (runtime / "series" / "STATUS.md").read_text(encoding="utf-8").splitlines()
        out["status_md_tail"] = [x for x in lines if x.strip()][-5:]
    except FileNotFoundError:
        out["status_md_tail"] = []
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start"); s.add_argument("--episode", required=True); s.add_argument("--brief", default="")
    r = sub.add_parser("resume"); r.add_argument("--episode", required=True); r.add_argument("--message", required=True)
    t = sub.add_parser("status"); t.add_argument("--episode", required=True)
    k = sub.add_parser("tick")
    k.add_argument("--system", action="store_true",
                   help="run by the system cron (setup_host.sh): advance production, fleet report/commands; "
                        "AGENT hand-offs are left for the agent heartbeat")
    sub.add_parser("report")
    x = sub.add_parser("_run")
    for k in ("--episode", "--log", "--last", "--argv"):
        x.add_argument(k, required=True)
    a = ap.parse_args()

    if a.cmd == "_run":
        return runner(a.episode, a.log, a.last, a.argv)
    if a.cmd == "tick":
        # one tick at a time: the system cron (every 3 min) and the agent heartbeat share this lock
        import fcntl  # noqa: PLC0415
        lock_dir = roots()[1] / "claude_code"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock = open(lock_dir / ".tick.lock", "w")  # noqa: SIM115
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("NALU_TICK: " + json.dumps({"action": "NONE", "reason": "TICK_ALREADY_RUNNING"}))
            return 0
        res = tick(system=a.system)
        # fleet channel (line owner 2026-11-09): report this machine and run the superadmin's whitelisted commands
        sys.path.insert(0, str(HERE))
        import fleet_sync  # noqa: PLC0415
        res.update(fleet_sync.sync(sys.modules[__name__], res))
        print("NALU_TICK: " + json.dumps(res, ensure_ascii=False))
        return 0
    if a.cmd == "start":
        out = start(a.episode, Path(a.brief).read_text(encoding="utf-8") if a.brief else "")
    elif a.cmd == "resume":
        out = resume(a.episode, a.message)
    elif a.cmd == "status":
        out = status(a.episode)
    else:
        out = report()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 2 if out.get("status") == "BLOCKED" else 0


if __name__ == "__main__":
    sys.exit(main())
