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
# A resumed thread the provider refuses outright (device …1485, 2026-11-19: codex-cli 0.170.0 replays its tool
# declarations as an `additional_tools` input item on `exec resume`; HopsAPI's Responses endpoint answers
# invalid_request_error / param input[0].type before the first token).  Resuming that thread can never work, so the
# next resume hands off to a fresh thread instead of burning the no-status resumes.
RESUME_REJECTED_RE = re.compile(r"invalid_request_error.*input\[\d+\]\.type|additional_tools", re.I | re.S)
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
- 编辑文件用 apply_patch 或 shell。**不要用 `sleep`/`ps`/`pgrep`/`while` 轮询等待**：付费阶段的最后一行是
  `NEXT: END_TURN_WAIT_FOR_TICK` 时，按合同 §6 报 `WAITING_REMOTE` 结束本轮，系统心跳会免费重跑并在需要你判断时叫醒你；
  要看进行中的工作只跑一次 `./lines/nalu/runtime/tools/paid_stage.sh --status <EP>`（合同 §0.1）。
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


def reviewer_prompt(episode: str, request: Path, answers: Path, process_id: str, submit_cmd: str,
                    gemini: Path | None = None) -> str:
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
   每条 problem 再给 `kb_scope`（知识库用，不影响判定）：换成任何对白语言都会一样出现的问题（画面、运镜、分镜、剪辑、节奏、
   剧情、连贯、身份/服装、模型烧字等）写 `global`；只和这一种对白语言有关的（台词用词、发音/ASR/口型、配音音色、字幕文字/
   断行/标点、翻译腔/敬语/语体、该语种市场的文化习惯）写 `language`；并写一句 `kb_scope_reason`。拿不准写 `global`。
   如实判断：有穿帮就判低分，判拒（REJECT_RECUT）也是正常结论，不要为了通过而改判。
   请求里有 `craft_standard_request` 时，同一遍里再填答案的可选块 `craft_standard`（格式见其 `answer_block`）：两层各 1–5 分，
   每条 CORE 条目 PASS/GAP/NA 加带数字的依据，最多 3 个 top gap（条目 id、时间或镜号、带数字的指标、修法、fix_owner
   writer|engine|S7），以及爽点时间、钩子时间、悬念时间。`measured_pacing` 里的数是在成片上量出来的，直接用，不要自己估。
   修法写成剪辑/写作方向，不引用台词、不写人名。这一块只记分不拦片，填错也不影响提交。
   请求里有 `qa_defect_checklist_request` 时（线主 2026-11-19 必查清单），逐条专门检查并填 `qa_defect_checklist`
   （格式见其 `answer_block`，每条 PASS/DEFECT/NA，DEFECT 必须带时间戳）：QA-BURNED-TEXT 画面里模型烧进的字（如字幕下多出的大字）、
   QA-DIALOGUE-TAIL-CUT 台词尾音被切或句末无停顿、QA-OVERSIZED-MASK 遮挡/模糊框过大、QA-LOOKALIKE-CAST 两个角色长得一样、
   QA-SUBTITLE-WRAP 字幕换行不当（如「！」单独一行）、QA-BGM-DISCONTINUOUS 配乐只响一两个镜头就停或在切点生硬起停、
   QA-SKIN-SHEEN-DRIFT 任何镜头里人物脸油亮/出汗/额头鼻梁脸颊有白亮反光、头发湿亮或质感过锐（前后镜头一样油也算；场景里没有雨水、
   汗水、眼泪的理由），相邻镜头间突然变油也算、
   QA-EDIT-FRAGMENT 剪辑碎片（不到约 1.2 秒的碎镜头、说话的角色一句没说就切走、台词没说完就切、切得太快）、
   QA-CAMERA-WOBBLE 固定机位镜头里背景/整个画面跟着人物小动作一起晃（盯住门框墙角等直线看它相对画框动没动）、
   QA-SILENT-MOUTH 有人嘴在一张一合像在说话却听不到他的台词（`measurements.silent_mouth` 是引擎静音掉模型人声的时间窗，先看那里；
   抽帧 0.25 s 一帧看嘴，同时量那一段音频）。画框外伸进来、看不到主人的手/手臂（和角色握手、拉手、递东西）是多出来的人，写进 problems（P1）。
   `measurements` 里是免费量出来的线索（OCR、尾音距切点、遮挡面积、身份牌相似度、字幕分行、配乐段、S6 皮肤油光/锐化漂移的单元、
   `s7_edit` 碎镜头/不说话的说话人镜头/尾音距切点不足 0.15 s/切在台词中间），逐个用眼睛/听感核实；
   确认的缺陷同时按严重度写进 problems。这一块只记录不拦片。
   请求 `evidence.av_evidence_pack` 是本地免费测的证据包（跨帧 OCR 烧字、每个切点的尾音缺口/能量、配乐段、角色对照表
   `evidence.cast_lineup_sheet` 与相似度矩阵、字幕折行、逐镜黑边），摘要也在 `measurements.av_evidence_pack`；当线索用。
{gemini_step(gemini)}4. 按 `answer_contract` 写答案 JSON 到 `{answers}`，其中：
   `reviewer.agent_id` = `storyclaw-final-audience-reviewer`，`reviewer.role` = `independent_final_audience_reviewer`，
   `reviewer.model` = `{REVIEWER_MODEL_ID}`，`reviewer.process_id` = `{process_id}`，`reviewer.reviewed_at` = 当前 UTC ISO 时间；
   `request_sha256` 用 `sha256sum` 算请求文件。
5. 自己提交：`{submit_cmd}`。退出码 0（通过）或 3（判拒）都算完成；其它退出码就读输出、修正答案格式后再提交一次。
6. 只允许写 `{answers}` 和你在 `$TMPDIR` 下的临时目录；不改引擎、剧本、订单、成片或任何其它文件；不读任何密钥文件。
最后一行输出：`REVIEW_SUBMITTED: {{"exit_code": <submit 退出码>, "verdict": "<PASS|REJECT_RECUT|...>"}}`
"""


def gemini_step(gemini: Path | None) -> str:
    """Reviewer step 3b: verify the video-native passes (gemini_video_review.py) finding by finding."""
    if gemini is None:
        return ""
    return f"""3b. **视频原生初审（Gemini，只是线索，不是结论）**：`{gemini}`（`status` 不是 OK 就跳过这一步）。逐条核对 `findings`（G1…）
   和 `suspect_checks`（S1…，本地测量的尾音/配乐/黑边/皮肤油光可疑点及 Gemini 的判断）：到对应时间点用 ffmpeg 抽帧（必要时
   0.25 s 一帧，皮肤/手/脸放大到原分辨率）看画面、量音频，自己判断。确认的：写进 problems（带严重度）和 `qa_defect_checklist`
   对应 QA-* 条目的 DEFECT findings（不属于必查清单的类别只写 problems）。不成立的：说明理由。
   `mode` 是 `multipass` 时，发现来自四个专审（每条的 `pass`）：A 画面/AI 瑕疵（QA-FACE-ARTIFACT 脸眼牙、QA-HAND-ARTIFACT 手指、
   QA-SKIN-SHEEN-DRIFT 皮肤油光/头发变湿、QA-SILENT-MOUTH 嘴动没声音、QA-CAMERA-WOBBLE 背景随人晃、QA-BODY-MORPH、QA-OBJECT-POP、QA-FLICKER、QA-PHYSICS、
   烧字、遮罩、黑边）、
   B 身份与场内连贯（QA-IDENTITY-MISMATCH 对照身份卡、LOOK-DRIFT 服装发型配饰、QA-PROP/LIGHTING/POSITION-CONTINUITY、
   QA-LOOKALIKE-CAST 两个角色看起来是同一个人，见 `cast_compare`）、
   C 声音（QA-LIPSYNC、QA-VOICE-INCONSISTENT、QA-WRONG-SPEAKER、QA-VOICE-GENDER 女角色男声/男角色女声、尾音、QA-LOUDNESS-JUMP、
   配乐、QA-SFX、QA-AUDIO-ARTIFACT）、
   D 导演/剪辑（QA-EDIT-FRAGMENT 碎镜头/不说话就切走、CRAFT-PACING、CRAFT-SHOT-GRAMMAR、CRAFT-BEAT-MISSED、CRAFT-CLARITY、CRAFT-OPENING-HOOK、CRAFT-ENDING-HOOK、
   CRAFT-EMOTION、CRAFT-ACTING-MONOTONY、CRAFT-SUBTITLE-READABILITY，以及 QA-PLAN-MISMATCH 该单元没拍出计划内容——逐单元结论见
   `plan_parity`：主被动反了、地点不对、计划的人不在、多出计划外的人、节拍没发生）。全部都要核对；确认后引擎这样处理（你只管判断真假）：烧字、身份/服装、
   脸与皮肤漂移、背景随人晃、手、声音性别不对、计划不符 → 付费重做该单元；声音类 → 免费 S7 重混/重剪；导演/剪辑类 → 记录并进知识库。
   你自己也必查这两条（Gemini 没报也要看）：**声音性别**——每个说话镜头，画面里开口的人是女性/男性，听到的声音是不是同性别
   （女角色配男声是硬伤，写 problems，带时间点和是谁）；**表演单调**——人物说话时有没有具体的小动作（整理袖口、握住桌沿、移开视线再看回、
   上前半步、抱臂、碰项链、歪头、轻呼一口气），还是干站着念台词、或多个镜头反复同一个手势（如双手向两侧摊开、竖起食指/指着对方；
   不同角色用同一个手势也算），听的人是不是僵住不动；
   单调就写 problems（`CRAFT-ACTING-MONOTONY`，kb_scope 写 global：这是导演问题，不分语言）。
   每一条 G/S 都要在 `qa_defect_checklist.gemini_verification` 里给结论：`[{{"id": "G1", "decision": "CONFIRMED|DISMISSED", "reason": "你看到/测到了什么"}}]`；
   CONFIRMED 的同时给 `"kb_scope": "global|language"` 和一句 `"kb_scope_reason"`（判法同第 3 步 problems 的 kb_scope；
   Gemini 自己的 `scope_hint` 只作参考）。
   Gemini 漏掉的问题照常自己查；它的判语不能代替你的观看，也不能照抄。
"""


def run_gemini_review(episode: str, request: Path, d: Path, env: dict[str, str]) -> dict[str, Any]:
    """The video-native pass before Codex starts: once per request (a recorded OK / over-budget / disabled result is
    reused; an error is retried once on the next attempt).  Never blocks: any failure returns a status."""
    out = d / "gemini_review.json"
    request_sha = _file_sha(request)
    prior = read_json(out)
    if prior.get("request_sha256") == request_sha and (prior.get("status") in ("OK", "SKIPPED")
                                                       or int(prior.get("_attempts") or 1) >= 2):
        return {"status": prior.get("status"), "path": str(out), "reused": True}
    engine, _ = roots()
    venv = engine / ".qingshan-venv" / "bin" / "python"
    tool = engine / "lines" / "nalu" / "runtime" / "tools" / "gemini_video_review.py"
    child = dict(env)
    child.pop(KEY_ENV, None)   # Codex's provider key name; the tool resolves the line's HopsAPI key itself
    p = provider() or {}
    if not child.get("HOPSAPI_API_KEY") and "hopsapi" in str(p.get("base_url") or "").lower() and p.get("api_key"):
        child["HOPSAPI_API_KEY"] = p["api_key"]
    try:
        subprocess.run([str(venv if venv.is_file() else sys.executable), str(tool), "--request", str(request),
                        "--out", str(out)], cwd=engine, env=child, capture_output=True, timeout=900, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "ERROR", "reason": f"{type(exc).__name__}"}
    record = read_json(out)
    if record.get("request_sha256") == request_sha and record.get("status") == "ERROR":
        attempts = int(prior.get("_attempts") or 0) + 1 if prior.get("request_sha256") == request_sha else 1
        write_json(out, {**record, "_attempts": attempts})
    return {"status": record.get("status") or "ERROR", "reason": record.get("reason"), "path": str(out),
            "cost_credits": record.get("cost_credits")}


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
REVIEWER_PROMPT_VERSION = "4"   # 3: video-native Gemini pass + local evidence pack (2026-11-19); 4: multi-pass (11-20)


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
    # video-native pass first (line owner 2026-11-19): advisory, never blocks the Codex reviewer
    gemini = run_gemini_review(episode, request, d, env)
    state["gemini_review"] = gemini
    if gemini.get("status") == "OK":
        note(f"{episode} 独立终审：Gemini 视频初审完成（{gemini.get('cost_credits')} credits），交 Codex 逐条核实")
    pfile.write_text(reviewer_prompt(episode, request, answers, process_id, submit_cmd,
                                     gemini=Path(gemini["path"]) if gemini.get("status") == "OK" else None),
                     encoding="utf-8")
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
    env.setdefault("NALU_COMPACT_OUTPUT", "1")   # nalu_pipeline prints stage lines only; the run log keeps the rest
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


def launch(episode: str, prompt: str, resume_id: str | None, *, keep_counters: bool = False) -> dict[str, Any]:
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
        if not keep_counters:  # a fresh hand-off thread continues the same episode: its resume caps still count
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


def render_style_for(episode: str | None) -> str:
    """The series' render style for the start prompt (render_style.py: contract field is not written yet at start,
    so the episode brief, then the runtime qingshan.json project.render_style).  Never raises."""
    mod = _load_engine_tool("render_style")
    if mod is None:
        return "live_action"
    try:
        return str(mod.resolve_runtime(episode, runtime_root=roots()[1]))
    except Exception:  # noqa: BLE001
        return "live_action"


def craft_profile_for(episode: str | None) -> str:
    """The series' craft profile for the start prompt (craft_profile.py: brief, then runtime qingshan.json
    project.craft_profile; LEGACY by default).  Never raises."""
    mod = _load_engine_tool("craft_profile")
    if mod is None:
        return "LEGACY"
    try:
        return str(mod.profile_of(None, episode=episode, runtime_root=roots()[1]))
    except Exception:  # noqa: BLE001
        return "LEGACY"


def craft_standard_section(episode: str | None = None) -> str:
    """NALU_CRAFT_STANDARD_v1 (line owner 2026-11-17, option A): the compressed zh standard as its OWN section of the
    start prompt (<= 1500 chars, lines/nalu/runtime/tools/nalu_craft_standard.codex_section), separate from the
    collective 「本集导演经验」 section and its own 1500-char cap.  '' when the engine has no standard or
    NALU_CRAFT_STANDARD=off.  Never raises."""
    mod = _load_engine_tool("nalu_craft_standard")
    if mod is None:
        return ""
    try:
        style = render_style_for(episode) if episode else "live_action"
        # BILI_V1 series (craft_profile.py, CHANGE_SPEC WP4): the BILI_V1 compressed standard; LEGACY call unchanged
        bili = {"craft_profile": "BILI_V1"} if episode and craft_profile_for(episode) == "BILI_V1" else {}
        if style == "anime":  # the short anime note (anime acting, one consistent character design)
            base = str(mod.codex_section(roots()[0], render_style=style, **bili) or "")
        else:
            base = str(mod.codex_section(roots()[0], **bili) or "")
        # BILI_V1 (CHANGE_SPEC WP6): the setup/payoff ledger note after the craft standard
        note = craft_ledger_section(episode) if episode else ""
        return f"{base}\n\n{note}" if base and note else (base or note)
    except Exception:  # noqa: BLE001 -- the start prompt must never fail on an advisory section
        return ""


def craft_ledger_section(episode: str) -> str:
    """BILI_V1 only (CHANGE_SPEC WP6): the ledger / irony / signature-business note plus the series' open threads
    (lines/nalu/runtime/tools/craft_ledger.codex_note_zh).  '' under LEGACY, so the prompt is byte-identical.
    Never raises."""
    try:
        profile = _load_engine_tool("craft_profile")
        if profile is None or not profile.is_bili_v1(None, episode=episode, runtime_root=roots()[1]):
            return ""
        ledger = _load_engine_tool("craft_ledger")
        return str(ledger.codex_note_zh(roots()[1], episode) or "") if ledger is not None else ""
    except Exception:  # noqa: BLE001
        return ""


def build_prompt(episode: str, brief: str, guidance: str = "", craft: str | None = None) -> str:
    craft = craft_standard_section(episode) if craft is None else craft
    return (f"你是 NALU 短剧生产线的生产执行者。严格按照下面的生产合同执行集 {episode}。\n\n"
            + contract_path().read_text(encoding="utf-8") + "\n" + CODEX_ADAPTER
            + (f"\n\n## 本次线主/编排代理附加说明\n{brief}" if brief else "")
            + (f"\n\n{craft}" if craft else "")
            + (f"\n\n{guidance}" if guidance else ""))


# ---------------------------------------------------------------------------------- collective knowledge
# 2026-11-16 (owner-approved): the collective knowledge base reaches the AUTHOR, not only the S2 video prompts.
# tools/collective_learning/authoring.py (run with the engine venv: it verifies signed bundles) runs the S1
# line-upgrade preflight early -- which writes this episode's knowledge briefing and its run knowledge lock, kept
# unchanged by S1 -- and returns the 「本集导演经验」 section (directing rules + 成功样例库 exemplars + the briefing
# path, <= 1500 chars).  No COLLECTIVE_LEARNING_CONFIG.json, no applicable knowledge or any error: no section,
# the prompt is byte-identical to before.
GUIDANCE_TIMEOUT_S = 180


def _engine_python(engine: Path) -> str:
    venv = engine / ".qingshan-venv" / "bin" / "python"
    return str(venv) if venv.is_file() else sys.executable


def _collective_configured(runtime: Path) -> bool:
    rt = runtime / "runtime"
    return any((d / "COLLECTIVE_LEARNING_CONFIG.json").is_file()
               for d in (rt / "runtime" / "reports", rt / "reports"))


def knowledge_guidance(episode: str) -> dict[str, Any]:
    """The prepared guidance for ``episode`` (``section`` may be empty).  Never raises."""
    engine, runtime = roots()
    tool = engine / "tools" / "collective_learning" / "authoring.py"
    if not _collective_configured(runtime) or not tool.is_file():
        return {"status": "INACTIVE", "section": ""}
    out = run_dir(episode) / "knowledge_guidance.prepared.json"
    try:
        out.unlink(missing_ok=True)
        proc = subprocess.run([_engine_python(engine), str(tool), "prepare", "--engine-root", str(engine),
                               "--runtime-root", str(runtime), "--episode", episode, "--out", str(out)],
                              cwd=str(engine), capture_output=True, text=True, timeout=GUIDANCE_TIMEOUT_S)
        prepared = read_json(out)
        if proc.returncode != 0 or not prepared:
            return {"status": "ERROR", "section": "", "error": (proc.stderr or proc.stdout or "")[-300:]}
        prepared["_path"] = str(out)
        return prepared
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "ERROR", "section": "", "error": f"{type(exc).__name__}:{str(exc)[:200]}"}


def record_guidance(episode: str, prepared: dict[str, Any], prompt_with: str, prompt_without: str) -> dict[str, Any]:
    """APPLIED receipts for the injected rules (the prompt was actually sent).  Never raises."""
    if not prepared.get("section") or not prepared.get("_path"):
        return {"status": "NOTHING_INJECTED"}
    engine, _ = roots()
    d = run_dir(episode)
    with_path, without_path = d / "knowledge_guidance.prompt_with.md", d / "knowledge_guidance.prompt_without.md"
    try:
        with_path.write_text(prompt_with, encoding="utf-8")
        without_path.write_text(prompt_without, encoding="utf-8")
        proc = subprocess.run([_engine_python(engine), str(engine / "tools" / "collective_learning" / "authoring.py"),
                               "record", "--prepared", prepared["_path"], "--prompt-with", str(with_path),
                               "--prompt-without", str(without_path)],
                              cwd=str(engine), capture_output=True, text=True, timeout=GUIDANCE_TIMEOUT_S)
        lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
        return json.loads(lines[-1]) if lines else {"status": "ERROR", "error": (proc.stderr or "")[-300:]}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:200]}"}
    finally:
        without_path.unlink(missing_ok=True)  # the receipt keeps its digest; the copy is not needed


def start(episode: str, brief: str = "") -> dict[str, Any]:
    if not contract_path().is_file():
        return {"status": "BLOCKED", "reason": f"CONTRACT_MISSING:{contract_path()}"}
    guidance = knowledge_guidance(episode)
    section = str(guidance.get("section") or "")
    craft = craft_standard_section(episode)
    prompt = build_prompt(episode, brief, section, craft)
    out = launch(episode, prompt, None)
    if out.get("status") == "STARTED":
        save_start_context(episode, brief, section)
        series = roots()[1] / "series"
        series.mkdir(parents=True, exist_ok=True)
        (series / "CURRENT_EPISODE").write_text(episode + "\n", encoding="utf-8")
        if section:
            out["knowledge_guidance"] = {"chars": len(section), "status": guidance.get("status"),
                                         "rules": [r.get("rule_id") for r in guidance.get("rules") or []],
                                         "exemplars": guidance.get("exemplar_ids") or [],
                                         "record": record_guidance(episode, guidance, prompt,
                                                                   build_prompt(episode, brief, "", craft))}
        if craft:
            out["craft_standard"] = {"chars": len(craft)}
    return out


def next_episode_id(episode: str) -> str:
    m = re.fullmatch(r"([A-Za-z]*)(\d+)", episode.strip())
    if not m:
        return ""
    return f"{m.group(1)}{int(m.group(2)) + 1:0{len(m.group(2))}d}"


NEXT_EPISODE_BRIEF = """本集由引擎在上一集出片后自动接续（线主 + 老板 2026-11-10：下一集的派单与叙事正典交给你写，不再由编排代理写）。先写派单，再生产：
1. 读上一集派单 `{prev}`，以及上一集 {ep} 的叙事正典与剧本层的结尾、`{status}` 最近几条。
2. 按上一集派单的条款写 `{brief}`：`order_text` 里的集号与上限改成 {nxt}；起始章节取
   `{coverage_cmd}` 的 `next_chapter`（没有记录时从上一集派单的结束章接上），派单写**改编预算**（按剧情事件，不按章节：
   本集覆盖 ≥ max(4, ⌊时长/25⌋) 个剧情事件，需要几章取几章，通常 2–5 章；授权删减/合并/压缩/调序/补衔接动作，只保留关键剧情事实和人物真相）
   和一行 `pacing_policy: SHORT_DRAMA_PACING_V1`（合同 §2.0 第 5 条，所有合同默认生效：冷开场冲突 ≤3 秒、每 20–30 秒一次转折、结尾悬念、每场有身体动作、
   视觉动作 ≥30%、场景与地点要变）；生产简报里的
   `episode_display_number`（片头片尾与 X2C 发行用的「本剧第几集」）必须是 **{display}**，不得沿用上一集的值；剧名、风格、单集时长
   （`target_seconds`）、X2C 分类与简介、语言、预算上限等其它条款逐字沿用，不自行改动。
3. 原著已经改编完，或已达到线主在派单里指定的总集数：不生产，写 `{done}`（一行说明），在 `{status}` 记一行「SERIES_DONE」，
   最后一行输出 `NALU_STATUS: {{"episode":"{nxt}","state":"SERIES_DONE"}}`。
4. 否则按 `{skill}` §4 写本集叙事正典与生产简报（承接上一集结尾，角色、地点沿用，按合同 §8），然后按合同生产 {nxt}。
"""

#: craft profile BILI_V1 (CHANGE_SPEC WP1, owner 2026-11-23): an episode is allocated by plot events with a cap
NEXT_EPISODE_BRIEF_BILI_V1 = NEXT_EPISODE_BRIEF.replace(
    "本集覆盖 ≥ max(4, ⌊时长/25⌋) 个剧情事件，需要几章取几章，通常 2–5 章；",
    "本集 1 个主事件 + ≤1 个次事件（adaptation_plan.plot_events 标 role: MAIN / SECONDARY），需要几章取几章（常常 1 章），"
    "事件密集的章可拆成 2 集；节奏靠场内转折，不靠加事件；每场 ≥2 条原著细节（pacing.scene_plan[].source_detail_ids）；")


def next_episode_brief_template(runtime: Path, episode: str) -> str:
    """The dispatch template for ``episode``: BILI_V1 series get the event-cap wording; LEGACY is unchanged."""
    try:
        here = str(Path(__file__).resolve().parents[3] / "lines" / "nalu" / "runtime" / "tools")
        if here not in sys.path:
            sys.path.insert(0, here)
        import craft_profile as _cp  # noqa: PLC0415
        if _cp.is_bili_v1(Path(runtime), episode=episode):
            return NEXT_EPISODE_BRIEF_BILI_V1
    except Exception:  # noqa: BLE001 -- an unreadable profile is LEGACY
        pass
    return NEXT_EPISODE_BRIEF


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
        note(f"{episode}→{nxt} 集间升级：{'OK' if ok else 'SETUP_NOT_READY'} 引擎 {update.get('before')}→{update.get('after')}"
             f"（pin {str(update.get('pin') or '')[:7]}）")
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
    brief = next_episode_brief_template(runtime, nxt).format(display=display,
        prev=prev, ep=episode, nxt=nxt, brief=briefs / f"{nxt}_DISPATCH.md", done=runtime / "series" / "SERIES_DONE",
        status=runtime / "series" / "STATUS.md", skill=engine / "skills" / "nalu-claude-code" / "SKILL.md",
        coverage_cmd=(f"{_engine_python(engine)} {engine / 'lines/nalu/runtime/tools/script_pacing_check.py'} coverage "
                      f"--runtime-root {runtime}"))
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
    fresh = fresh_thread_decision(sid)
    last_err = str(parse_log(Path(session.get("log") or "")).get("last_error") or "")
    if not fresh["fresh"] and RESUME_REJECTED_RE.search(last_err):
        fresh = {"fresh": True, "reason": "RESUME_REJECTED_BY_PROVIDER", "error": last_err[:200],
                 "last_input_tokens": None, "threshold": None}
    if fresh["fresh"]:
        return resume_in_fresh_thread(episode, message, sid, fresh)
    return launch(episode, message + "\n（提醒：本轮最后一行仍须是 NALU_STATUS 单行 JSON。）", sid)


def status(episode: str) -> dict[str, Any]:
    session = read_json(run_dir(episode) / "session.json")
    info = parse_log(Path(session.get("log") or ""))
    return {"status": "RUNNING" if alive(session.get("pid")) else "IDLE", "episode": episode,
            "engine": session.get("engine") or "claude", "pid": session.get("pid"), "log": session.get("log"),
            "session_id": session.get("codex_thread_id") or session.get("session_id"),
            "codex": info, "pipeline": pipeline_status(episode)}


# ------------------------------------------------------------------------------------- remote waits (no model)
# Device …1144 E08/E09 (2026-11-16): ~half of Codex's ~650 round trips per episode were an S6 wait loop -- re-run
# `paid_stage.sh <EP> S6 S6` after `sleep 240`, probe the pipeline's children with ps/pgrep, tail the run log --
# and every round trip re-sent the whole conversation.  Now Codex ends its turn at WAITING_REMOTE as soon as
# paid_stage.sh prints `NEXT: END_TURN_WAIT_FOR_TICK`; the system tick (every 3 min, no model) follows the paid run
# and re-runs the SAME `paid_stage.sh <EP> <FROM> <UNTIL>` (same order, cap, durable store: nothing is bypassed)
# until the stage needs judgement, then resumes Codex.
REMOTE_WAIT_QUIET = ("IN_FLIGHT", "BACKOFF", "RERUN_STARTED", "RERUN_STARTING")
RERUN_START_GRACE_S = 120   # paid_stage.sh's own preflight (reconciliation, budget check) before it takes the lock


def _load_engine_tool(name: str) -> Any:
    """An engine line tool as a module (``lines/nalu/runtime/tools/<name>.py``), or None."""
    import importlib.util  # noqa: PLC0415
    engine, _ = roots()
    path = engine / "lines" / "nalu" / "runtime" / "tools" / f"{name}.py"
    if not path.is_file():  # the engine this script ships in
        path = HERE.parents[2] / "lines" / "nalu" / "runtime" / "tools" / f"{name}.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"_nalu_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001 -- a broken tool must not stop the tick; the old path (resume) still works
        return None
    return mod


def _epoch(stamp: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def launch_paid_rerun(episode: str, from_stage: str, until_stage: str) -> dict[str, Any]:
    """Re-run ``paid_stage.sh <EP> <FROM> <UNTIL>`` detached (the command Codex re-ran after ``sleep 240``)."""
    if not re.fullmatch(r"S[1-8]", str(from_stage)) or not re.fullmatch(r"S[1-8]", str(until_stage)):
        return {"status": "REFUSED", "reason": f"STAGE_RANGE:{from_stage}..{until_stage}"}
    engine, runtime = roots()
    script = engine / "lines" / "nalu" / "runtime" / "tools" / "paid_stage.sh"
    if not script.is_file():
        return {"status": "REFUSED", "reason": "PAID_STAGE_MISSING"}
    out_dir = runtime / "runtime" / "paid_runs" / episode
    out_dir.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k != KEY_ENV}
    env.setdefault("NALU_ENGINE_ROOT", str(engine))
    env.setdefault("NALU_RUNTIME_ROOT", str(runtime))
    with open(out_dir / "tick_rerun.out", "a", encoding="utf-8") as fh:
        fh.write(f"--- {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} tick re-run "
                 f"{episode} {from_stage}..{until_stage}\n")
        fh.flush()
        proc = subprocess.Popen(["/bin/bash", str(script), episode, from_stage, until_stage], cwd=str(engine),
                                stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                                start_new_session=True)
    return {"status": "STARTED", "pid": proc.pid, "output": str(out_dir / "tick_rerun.out")}


def _tail(path: Path, n: int = 5) -> list[str]:
    try:
        return [ln[:300] for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()][-n:]
    except OSError:
        return []


def remote_wait_step(ep: str, session: dict[str, Any]) -> dict[str, Any]:
    """The tick's free WAITING_REMOTE step.  Returns ``action`` in REMOTE_WAIT_QUIET (stay quiet), ``NO_RECORD``
    (nothing recorded by a paid run this turn: resume Codex as before) or ``RESUME`` (``reason``: wake Codex)."""
    prs = _load_engine_tool("paid_run_status")
    if prs is None:
        return {"action": "NO_RECORD", "reason": "PAID_RUN_STATUS_UNAVAILABLE"}
    _, runtime = roots()
    d = run_dir(ep)
    rw = session.get("remote_wait") if isinstance(session.get("remote_wait"), dict) else {}
    if rw.get("key") != session.get("log"):   # a new Codex turn: a fresh wait
        rw = {"key": session.get("log"), "reruns": 0}
    dec = prs.tick_decision(runtime, ep, since=_epoch(session.get("started_at")), reruns_done=int(rw["reruns"]))
    if dec["action"] != "IN_FLIGHT" and rw.get("last_rerun_at"):
        rec = prs.last_record(runtime, ep)
        if float(rec.get("finished_at") or 0) < float(rw["last_rerun_at"]):   # our re-run has not recorded yet
            if time.time() - float(rw["last_rerun_at"]) < RERUN_START_GRACE_S:
                return {"action": "RERUN_STARTING"}
            tail = _tail(runtime / "runtime" / "paid_runs" / ep / "tick_rerun.out")
            dec = {"action": "RESUME", "reason": "TICK_RERUN_ENDED_WITHOUT_A_RECORD", "output_tail": tail}
    if dec["action"] == "RERUN":
        out = launch_paid_rerun(ep, str(dec.get("from")), str(dec.get("until")))
        if out.get("status") == "STARTED":
            rw.update(reruns=int(rw["reruns"]) + 1, last_rerun_at=time.time())
            session["remote_wait"] = rw
            write_json(d / "session.json", session)
            return {"action": "RERUN_STARTED", "from": dec.get("from"), "until": dec.get("until"),
                    "reruns": rw["reruns"], "pid": out.get("pid"), "reason": dec.get("reason")}
        dec = {"action": "RESUME", "reason": f"TICK_RERUN_NOT_STARTED:{out.get('reason')}"}
    if session.get("remote_wait") != rw:
        session["remote_wait"] = rw
        write_json(d / "session.json", session)
    return {**dec, "reruns": int(rw["reruns"])}


def wake_message(ep: str, wait: dict[str, Any]) -> str:
    rec = wait.get("record") or {}
    lines = [f"系统心跳在你结束上一轮后替你跟进了远端等待（免费重跑 {wait.get('reruns', 0)} 次，没有经过你）。"
             f"现在需要你判断：{wait.get('reason')}。"]
    if rec:
        lines.append(f"最近一次付费运行：{rec.get('from')}..{rec.get('until')} exit={rec.get('exit_code')}，"
                     f"阶段 {rec.get('stage')} {rec.get('status')}，阻塞 {', '.join(rec.get('blockers') or []) or '无'}；"
                     f"完整日志 {rec.get('log')}（只用 `tail -n 40` 或 `rg` 取需要的行，不要整份读）。")
    if wait.get("output_tail"):
        lines.append("心跳重跑的输出末尾：\n" + "\n".join(wait["output_tail"]))
    lines.append(f"先跑一次 `./lines/nalu/runtime/tools/paid_stage.sh --status {ep}`（不要 ps/pgrep/sleep），然后按合同继续。")
    return "\n".join(lines)


# --------------------------------------------------------------------------------- fresh thread on resume
# Same study: resuming one Codex thread 4 times grew every model step from ~217K to 650-720K input tokens, so the
# later steps cost ~3x.  A resume whose previous thread already sends more than NALU_CODEX_FRESH_THREAD_TOKENS
# (default 300K, 0 = never) per step starts a NEW thread seeded with the contract and a compact hand-off built from
# engine state.  Nothing durable lives in the thread: paid tasks are bound in the transaction store, orders and
# receipts on disk, and the pipeline skips PASS stages -- so a fresh thread repeats no paid work.
FRESH_THREAD_ENV = "NALU_CODEX_FRESH_THREAD_TOKENS"
DEFAULT_FRESH_THREAD_TOKENS = 300_000
ROLLOUT_TAIL_BYTES = 8 * 1024 * 1024
HANDOFF_BRIEF_MAX = 6000


def fresh_thread_threshold() -> int:
    try:
        return max(0, int(os.environ.get(FRESH_THREAD_ENV) or DEFAULT_FRESH_THREAD_TOKENS))
    except ValueError:
        return DEFAULT_FRESH_THREAD_TOKENS


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def thread_last_input_tokens(thread_id: str) -> tuple[int | None, str | None]:
    """Input tokens of the thread's LAST model step, from Codex's own rollout file
    (``~/.codex/sessions/**/rollout-*-<thread_id>.jsonl``, ``token_count`` events with ``last_token_usage``)."""
    if not thread_id or not re.fullmatch(r"[A-Za-z0-9_-]+", thread_id):
        return None, None
    try:
        files = sorted((codex_home() / "sessions").rglob(f"rollout-*{thread_id}.jsonl"),
                       key=lambda p: p.stat().st_mtime)
    except OSError:
        return None, None
    for path in reversed(files):
        try:
            with path.open("rb") as fh:
                fh.seek(0, os.SEEK_END)
                fh.seek(max(0, fh.tell() - ROLLOUT_TAIL_BYTES))
                lines = fh.read().decode("utf-8", "replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            if '"token_count"' not in line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else ev
            info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
            last = info.get("last_token_usage") if isinstance(info.get("last_token_usage"), dict) else {}
            if isinstance(last.get("input_tokens"), int):
                return last["input_tokens"], str(path)
    return None, None


def fresh_thread_decision(thread_id: str) -> dict[str, Any]:
    threshold = fresh_thread_threshold()
    if not threshold:
        return {"fresh": False, "threshold": 0}
    tokens, source = thread_last_input_tokens(thread_id)
    return {"fresh": bool(tokens and tokens > threshold), "last_input_tokens": tokens, "threshold": threshold,
            "source": source}


def save_start_context(episode: str, brief: str, section: str) -> None:
    """Keep the start brief and the 本集导演经验 section so a fresh hand-off thread carries them again."""
    d = run_dir(episode)
    for name, text in (("start_brief.md", brief), ("knowledge_guidance.section.md", section)):
        path = d / name
        if text:
            path.write_text(text, encoding="utf-8")
        else:
            path.unlink(missing_ok=True)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def build_handoff(episode: str, message: str, old_thread: str, decision: dict[str, Any]) -> str:
    """A compact (~3-8 KB) hand-off from engine state: where the episode stands, what is open, where things are."""
    engine, runtime = roots()
    d = run_dir(episode)
    session = read_json(d / "session.json")
    info = parse_log(Path(session.get("log") or ""))
    out = [f"## 新线程接手（引擎自动生成）",
           f"上一线程 `{old_thread}` 最后一步的输入已有 {decision.get('last_input_tokens')} tokens（阈值 "
           f"{decision.get('threshold')}），为省费用换成新线程。你是在**继续**生产 {episode}，不是从头开始：已 PASS 的阶段"
           "流水线会跳过，已绑定的付费任务只收割不重提，订单与回执都在磁盘上。上面的合同就是全文——不要再去读合同文件、"
           "SKILL.md、`configs/ENGINEERING_KNOWLEDGE_V1.json` 或 `knowledge/failure_memory.jsonl` 全文；要查哪条用 `rg` 按行取。",
           "", "### 本次恢复的原因", message.strip()]
    ns = info.get("nalu_status")
    if ns:
        out += ["", "### 上一线程最后的 NALU_STATUS", json.dumps(ns, ensure_ascii=False)[:800]]
    last = (info.get("result") or info.get("last_assistant_text") or "").strip()
    if last:
        out += ["", "### 上一线程最后一条消息（节选）", last[-1500:]]
    stages = pipeline_status(episode)
    if stages:
        out += ["", f"### 流水线状态（runtime/pipeline_state/{episode}.json）"]
        for sid, row in stages.items():
            blockers = ", ".join(str(b) for b in row.get("blockers") or [])
            out.append(f"- {sid} {row.get('status')}" + (f"：{blockers[:300]}" if blockers else ""))
    prs = _load_engine_tool("paid_run_status")
    if prs is not None:
        try:
            out += ["", "### 付费运行（paid_stage.sh --status）"] + prs.status_lines(runtime, episode)
        except Exception:  # noqa: BLE001 -- the hand-off is best effort
            pass
    orders = read_json(runtime / "runtime" / "SUPERVISOR_ORDERS.json").get("orders") or []
    mine = [o for o in orders if isinstance(o, dict)
            and episode in json.dumps(o.get("decision") or o.get("scope") or {}, ensure_ascii=False)][-6:]
    if mine:
        out += ["", f"### 本集最近的订单（runtime/SUPERVISOR_ORDERS.json，latest seq "
                    f"{read_json(runtime / 'runtime' / 'SUPERVISOR_ORDERS.json').get('latest_order_seq')}）"]
        for o in mine:
            dec = o.get("decision") or {}
            out.append(f"- seq={o.get('seq')} {o.get('type') or dec.get('kind')} gate={dec.get('gate_id')} "
                       f"detectors={len(dec.get('detectors') or [])} status={o.get('status')}")
    reports = engine / "workflow" / "nalu" / episode / "preproduction" / "reports"
    blockers = sorted(reports.glob("*CODE_BLOCKER*.md"), key=lambda p: p.stat().st_mtime) if reports.is_dir() else []
    if blockers:
        out += ["", "### 最近的代码阻塞报告", str(blockers[-1])]
    out += ["", "### 关键路径",
            f"- 派单 {runtime / 'briefs' / f'{episode}_DISPATCH.md'}；简报 {runtime / 'briefs' / f'{episode}_PRODUCTION_BRIEF.json'}",
            f"- 叙事正典 {engine / 'workflow' / 'claude_writer_agent' / 'scripts' / f'{episode}_NARRATIVE_CANONICAL_v1.md'}",
            f"- 报告 {reports}；审核 {runtime / 'runtime' / 'reviews' / episode}",
            f"- 流水线日志 {runtime / 'runtime' / 'pipeline_logs' / episode}；付费运行 {runtime / 'runtime' / 'paid_runs' / episode}",
            f"- 进度 {runtime / 'series' / 'STATUS.md'}"]
    brief = _read_text(d / "start_brief.md").strip()
    if brief:
        out += ["", "### 开工附加说明（原文）",
                brief if len(brief) <= HANDOFF_BRIEF_MAX else brief[:HANDOFF_BRIEF_MAX] + f"\n…（全文 {d / 'start_brief.md'}）"]
    out += ["", f"先跑一次 `./lines/nalu/runtime/tools/paid_stage.sh --status {episode}` 和 "
                f"`env -u GIGGLE_API_KEY -u HOPSAPI_API_KEY $NALU_ENGINE_ROOT/.qingshan-venv/bin/python "
                f"lines/nalu/runtime/tools/nalu_pipeline.py status --episode {episode}`，然后从当前阶段按合同继续。",
            "（提醒：本轮最后一行仍须是 NALU_STATUS 单行 JSON。）"]
    return "\n".join(out)


def resume_in_fresh_thread(episode: str, message: str, old_thread: str, decision: dict[str, Any]) -> dict[str, Any]:
    d = run_dir(episode)
    handoff = build_handoff(episode, message, old_thread, decision)
    section = _read_text(d / "knowledge_guidance.section.md").strip()
    prompt = build_prompt(episode, "", handoff + (f"\n\n{section}" if section else ""))
    out = launch(episode, prompt, None, keep_counters=True)
    if out.get("status") == "STARTED":
        session = read_json(d / "session.json")
        session.setdefault("fresh_threads", []).append(
            {"from_thread": old_thread, "last_input_tokens": decision.get("last_input_tokens"),
             "threshold": decision.get("threshold"), "log": out.get("log"),
             "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
        write_json(d / "session.json", session)
        out["fresh_thread"] = {"from_thread": old_thread, "last_input_tokens": decision.get("last_input_tokens"),
                               "handoff_chars": len(handoff)}
    return out


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


def release_hold(ep: str) -> str:
    """'RELEASE_HELD:<classes>' when the engine held the episode's X2C release (final_fix_round.json
    ``release_hold``, owner 2026-11-23: a short runtime or unresolved burned text), else ''.  Never raises."""
    engine, _ = roots()
    try:
        work = Path(os.environ.get("NALU_WORK_ROOT") or (engine / "workflow" / "nalu"))
        hold = (read_json(work / ep / "assembly" / "final_qa" / "final_fix_round.json") or {}).get("release_hold")
        return str(hold.get("hold") or "") if isinstance(hold, dict) and hold.get("status") == "RELEASE_HELD" else ""
    except Exception:  # noqa: BLE001
        return ""


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
            if release_hold(ep):  # held (redo candidate): never sent, never retried, the line goes on
                continue
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


PACING_REVISE_MESSAGE = ("S1 的 SCRIPT_PACING_REVISE 不是阻塞，是给你的免费改稿要求（SHORT_DRAMA_PACING_V1，合同 §2.0 第 5 条）："
                         "读 runtime/pipeline_state/<EP>.json 的 stages.S1.details.script_pacing（failures 与 fixes），"
                         "改本集叙事正典和四层剧本（压缩/合并/删场、加转折、把说明台词改成动作与反应、结尾停在悬念上），"
                         "然后重跑 S1→S3；最多两轮，之后引擎自动放行。不要问线主，不要报 BLOCKED。")


INTEGRITY_REVISE_MESSAGE = ("S1 的 SCRIPT_INTEGRITY_REVISE 是剧本结构完整性问题（不是口味，不会被自动放行）："
                            "读 runtime/pipeline_state/<EP>.json 的 stages.S1.blockers 与 details（script_length / "
                            "character_entity_contract / script_structure_contract_gate / direction_policy_gate / "
                            "script_pacing.integrity_failures 及 fixes），按 WRITER_CONTRACT.md 改本集叙事正典和四层剧本"
                            "（补足时长、两人互动的动作把双方都写进 cast、未定义的角色 id、每场自己的地点/环境声/轴线、"
                            "多人场至少两个双人或群像镜头），然后重跑 S1→S3。免费，不问线主；同一份剧本重跑不算一轮，"
                            "4 轮仍不完整时引擎记录 SCRIPT_INTEGRITY_ADMITTED_AFTER_EXHAUSTION 后自动放行，不要报 BLOCKED。")


def _s1_blockers(episode: str) -> list[Any]:
    try:
        state = read_json(roots()[1] / "runtime" / "pipeline_state" / f"{episode}.json")
        return ((state.get("stages") or {}).get("S1") or {}).get("blockers") or []
    except Exception:  # noqa: BLE001
        return []


def pacing_revision_pending(episode: str, session: dict[str, Any]) -> str:
    """The pacing revision round ('round=1/2') S1 is waiting on that the session was not yet resumed for, or ''."""
    blockers = _s1_blockers(episode)
    rnd = next((str(b).split("SCRIPT_PACING_REVISE:", 1)[1] for b in blockers
                if str(b).startswith("SCRIPT_PACING_REVISE:round=")), "")
    return rnd if rnd and rnd not in (session.get("pacing_revise_resumed") or []) else ""


def integrity_revision_pending(episode: str, session: dict[str, Any]) -> str:
    """The S1 integrity round ('round=1/4') the session was not yet resumed for, or ''.  The engine caps the loop
    (nalu_pipeline.S1_INTEGRITY_MAX_ROUNDS) and then admits the script (SCRIPT_INTEGRITY_ADMITTED_AFTER_EXHAUSTION,
    no round marker left), and
    each round label is resumed once -- an unrevised script never resumes twice, so this cannot repeat forever."""
    blockers = _s1_blockers(episode)
    rnd = next((str(b).split("SCRIPT_INTEGRITY_REVISE:", 1)[1] for b in blockers
                if str(b).startswith("SCRIPT_INTEGRITY_REVISE:round=")), "")
    return rnd if rnd and rnd not in (session.get("integrity_revise_resumed") or []) else ""


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
    elif state == "BLOCKED" and pacing_revision_pending(ep, session):
        # SHORT_DRAMA_PACING_V1: a pacing revision request is the writer's own free work, never a maintainer fix;
        # a session that stopped on it is resumed once per revision round (the loop itself ends after
        # script_pacing_check.MAX_REVISIONS rounds, so this cannot repeat forever)
        rnd = pacing_revision_pending(ep, session)
        out = resume(ep, PACING_REVISE_MESSAGE)
        session = read_json(d / "session.json")
        session["pacing_revise_resumed"] = sorted(set(session.get("pacing_revise_resumed") or []) | {rnd})
        write_json(d / "session.json", session)
        did.append(f"resume_pacing_revision:{rnd}:{out.get('status')}")
        if out.get("status") == "STARTED":
            return res
        reason = f"RESUME_FAILED:{out.get('reason') or out.get('status')}"
    elif state == "BLOCKED" and integrity_revision_pending(ep, session):
        # S1 integrity (E24 2026-11-23): a structurally broken script goes back to its writer, free; resumed once per
        # integrity round, the engine stops issuing rounds after S1_INTEGRITY_MAX_ROUNDS
        rnd = integrity_revision_pending(ep, session)
        out = resume(ep, INTEGRITY_REVISE_MESSAGE)
        session = read_json(d / "session.json")
        session["integrity_revise_resumed"] = sorted(set(session.get("integrity_revise_resumed") or []) | {rnd})
        write_json(d / "session.json", session)
        did.append(f"resume_integrity_revision:{rnd}:{out.get('status')}")
        if out.get("status") == "STARTED":
            return res
        reason = f"RESUME_FAILED:{out.get('reason') or out.get('status')}"
    elif state == "WAITING_REMOTE":
        # remote work (S6 rendering, H3 queue, zero-cost provider outage) is followed here for free; Codex is woken
        # only when the stage needs judgement (paid_run_status.tick_decision; device …1144 E08/E09 cost study)
        wait = remote_wait_step(ep, session)
        res["remote_wait"] = {k: v for k, v in wait.items() if k != "record"}
        if wait["action"] in REMOTE_WAIT_QUIET:
            res["reason"] = f"REMOTE_WAIT_{wait['action']}"
            if wait["action"] == "RERUN_STARTED":
                did.append(f"paid_rerun:{wait.get('from')}..{wait.get('until')}:{wait.get('reruns')}")
            return res
        out = resume(ep, "继续" if wait["action"] == "NO_RECORD" else wake_message(ep, wait))
        did.append(f"resume_waiting_remote:{wait['action']}:{out.get('status')}")
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
                             "你没有写、也不要改）。按合同继续 S7：通过就放行；第一次判拒或有确认缺陷时引擎自动做一轮修复"
                             "（final_fix_round，按 S7 输出继续，S6 重做用 paid_stage.sh <EP> S6 S8）；第二次终审后仍判拒才按 §7 "
                             "记 FINAL-RELEASE-DEFAULT-ACCEPTANCE 订单后放行。S8 由引擎按默认条款自动批准，不问线主。")
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
