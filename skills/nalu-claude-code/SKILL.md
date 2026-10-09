---
name: nalu-claude-code
description: Install the Qingshan/NALU short-drama line on an OpenClaw host, wire Claude Code to the host's own LLM relay, prepare the episode's narrative script, and hand S1-S7 to an unattended Claude Code run that the agent monitors.
---

# NALU 生产线 · OpenClaw 编排 + Claude Code 执行

分工（线主 2026-10-09 定）：OpenClaw 代理负责安装、配置 Claude Code、取原著、写叙事正典与生产简报、
与线主沟通、监控进度；Claude Code 负责四层剧本结构化与 S1→S7 全部生产。全程无人值守，线主不需要
登录机器或在终端里输入任何东西。本目录脚本路径下文记作 `$S`（安装后为
`$TALENTHUB_WORKSPACE/skills/nalu-claude-code/scripts`；引擎克隆后也在 `$NALU_ENGINE_ROOT/skills/nalu-claude-code/scripts`）。

## 0. 一键准备（每次唤醒先跑）
```bash
bash $S/setup_host.sh --pin <PIN>
```
幂等：已就绪的机器 1–2 秒内返回；否则自动补齐 §1 系统依赖与引擎、Python 环境、运行时初始化，安装 Claude Code 并运行
`configure_claude_code.py --verify`（从 `~/.openclaw/openclaw.json` 读 StoryClaw provider 写入 Claude Code 配置）。
旧部署残留会被安全处理：引擎切到钉住的提交（有本地改动先 `git stash`），不是本脚本建的 `~/nalu_runtime` 改名为
`~/nalu_runtime_old_<时间>` 保留。只读最后一行 `NALU_SETUP: {...}`：`status=READY` 才继续；`BLOCKED` 时 `failed_step`
和 `~/.nalu_setup.log` 末尾说明原因（缺免密 sudo 编译 insightface、网络、relay 校验失败等），如实告诉用户。
`notes` 里有改名/切换记录时告诉用户一句。下面 §1–§2 是脚本做的事，供排障参考。

## 1. 安装生产线（代理执行）
以 OpenClaw 的普通用户运行（不要 root）。`<PIN>` 为 IDENTITY.md 里钉住的提交。
```bash
export NALU_ENGINE_ROOT=$HOME/nalu_engine NALU_RUNTIME_ROOT=$HOME/nalu_runtime NALU_WORK_ROOT=$HOME/nalu_engine/workflow/nalu
export NALU_QA_WORKERS=1 NALU_Q2_WORKERS=1          # 8G 内存：每个 QA worker 约 1.2 GB
# 系统依赖：有免密 sudo 就 sudo apt-get install -y git ffmpeg fonts-noto-cjk build-essential python3-dev；
# 没有时：ffmpeg 用 johnvansickle 静态包解压到 ~/.local/bin，Noto CJK 字体下载到 ~/.local/share/fonts（设 QINGSHAN_CJK_FONT）
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/rogerwu188/qingshan-short-drama-production-line.git $NALU_ENGINE_ROOT
cd $NALU_ENGINE_ROOT && git checkout --detach <PIN>
uv python install 3.12 && uv venv --python 3.12 --seed .qingshan-venv && export VIRTUAL_ENV=$PWD/.qingshan-venv
uv pip install -r requirements-core.txt -r requirements-media.txt && uv pip install -e .
uv pip install insightface onnxruntime rapidocr-onnxruntime faster-whisper opencc "av==18.1.0"
cp -n .env.example .env && chmod 600 .env
python3 lines/nalu/runtime/tools/bootstrap_runtime_root.py --runtime-root $NALU_RUNTIME_ROOT --line-id <项目 id> --work "<剧名>"
cp configs/pipeline.example.json $NALU_RUNTIME_ROOT/qingshan.json
```
把上面的 export 写进 `~/.bashrc`。不要设 `NALU_POLICY_PROFILE`。不需要 AgentCut、不需要角色照片（无照片走文生图）。

## 2. 安装并配置 Claude Code（代理执行）
```bash
npm install -g @anthropic-ai/claude-code || curl -fsSL https://claude.ai/install.sh | bash
python3 $S/configure_claude_code.py --verify     # 读 ~/.openclaw/openclaw.json 的 storyclaw provider，写 ~/.claude/settings.json
```
必须输出 `"status": "VERIFIED"`。脚本只显示 key 末 4 位，绝不要把 key 打印、转述或写进聊天。provider 名不是 `storyclaw`
时用 `--provider <名>`；中转不认默认模型名时用 `--model <中转支持的 Claude 模型 id>`。

## 3. 线主提供的信息（只通过对话）
- Giggle API key：线主在对话里发来时，直接写入 `$NALU_ENGINE_ROOT/.env` 的 `GIGGLE_API_KEY=`（保持 600），只回复「已配置 GIGGLE_API_KEY」。
- 原著：网址/文件/粘贴正文/大纲。网址直接抓取（翻页、目录逐章、必要时无头浏览器）；需要登录就向线主要账号或 Cookie；
  抓不全时如实报 `SOURCE_ACQUISITION_BLOCKED`，不凭搜索摘要补写。原文存 `$NALU_RUNTIME_ROOT/sources/<作品>/`，记 URL、时间、SHA-256。
- 线主 id、剧名、风格、单集时长、预算：没给就用默认值，写进简报，付费前由 Claude Code 统一报给线主确认。

## 4. 剧本交接（代理执行，免费）
每集写两个文件，然后跑运行时修复：
1. `$NALU_ENGINE_ROOT/workflow/claude_writer_agent/scripts/<EP>_NARRATIVE_CANONICAL_v1.md`：按仓库模板
   `agent_factory/claude_writer_v2/templates/NARRATIVE_CANONICAL.template.md`。只写事实、可表演的动作和**逐字台词**，按
   `## <EP>-S01｜<LOC-ID>｜<时间>｜线A` 分场；不写机位、灯光、资产。一集 2–4 场、20–60 秒为宜；台词决定时长（每 4 个汉字约 1 秒）。
2. `$NALU_RUNTIME_ROOT/briefs/<EP>_PRODUCTION_BRIEF.json`：
   `{"episode","title","owner_id","style","target_seconds","budget_cap","characters":[{"character_id":"CHAR-XXX","name","slug","role":"protagonist|supporting","sex","apparent_age_range","appearance","wardrobe","voice_brief"}],"locations":[{"location_id":"LOC-XXX","label","description","fixed_elements":[]}],"owner_words":{"<日期>":"<线主原话>"}}`
3. `python3 $S/apply_runtime_fixups.py --runtime-root $NALU_RUNTIME_ROOT --character <名>=<CHAR-ID>:<slug> ... --cap <预算>`
   以及 `$NALU_ENGINE_ROOT/.qingshan-venv/bin/python $S/make_endcard.py --runtime-root $NALU_RUNTIME_ROOT --title <剧名> --subtitle "第一集 · <集名>"`。
写剧本时避开这些已知坑：首帧要看得见的道具别设计成「从怀里掏出」；古装灯写「无罩敞口油盏」；每个说话角色男女/音色要能区分；不写全黑画面。

## 5. 交给 Claude Code 并监控
```bash
python3 $S/claude_production.py start  --episode <EP>                 # 后台启动；生产合同见 ../CLAUDE_CODE_PRODUCTION.md
python3 $S/claude_production.py status --episode <EP>                 # 读最后一行 NALU_STATUS 与流水线状态
python3 $S/claude_production.py resume --episode <EP> --message "<文本>"
```
心跳（建议每 5 分钟）按 `status` 输出行动：
- `RUNNING`：不打扰。
- `IDLE` + `OWNER_DECISION_REQUIRED`：把 `question` 原样转给线主；线主回复后用 `resume --message "线主原话：<逐字>"`。不得替线主回答。
- `IDLE` + `WAITING_REMOTE`：5 分钟后 `resume --message "继续"`。
- `IDLE` + `BLOCKED` / `ERROR`：把 note 和日志末尾告诉线主；属于安装/环境问题的由代理修好后 `resume --message "继续"`。
- `IDLE` + `FINAL_CUT_READY`：告诉线主成片路径 `$NALU_RUNTIME_ROOT/deliverables/<EP>/<EP>_final_9x16.mp4`、积分花费和待线主处理的事项（独立终审 / S8 看片）。
- `IDLE` 但没有 NALU_STATUS 行（会话异常结束）：`resume --message "继续，并在最后输出 NALU_STATUS 行"`。
只读 `status` 的结构化输出；不要改 Claude Code 写的剧本、订单、审核或事务文件。

## 6. 不做的事
不发布、不上传；不 git push；不把 key、Cookie 写进聊天、日志或仓库；不伪造线主订单；不删事务文件。
