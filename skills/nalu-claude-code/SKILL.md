---
name: nalu-claude-code
description: Install the Qingshan/NALU short-drama line on an OpenClaw host, wire Claude Code to the host's own LLM relay, prepare the episode's narrative script, and hand S1-S7 to an unattended Claude Code run that the agent monitors.
---

# NALU 生产线 · OpenClaw 编排 + Claude Code 执行

分工（线主 2026-10-09/10 定）：OpenClaw 代理负责安装、配置 Claude Code、取原著、逐集写叙事正典与生产简报、
监控进度、把成片发行到 X2C、接着启动下一集；Claude Code 负责每一集的四层剧本结构化与 S1→S7 全部生产。机器放在机房里
连续产剧，全程无人值守，没有人实时看，线主不需要登录机器或在终端里输入任何东西。

本目录脚本路径下文记作 `$S`。只有 `setup_host.sh` 从 TalentHub 安装的 skill 目录（或 `~/.nalu_bootstrap`）运行；
`setup_host.sh` 返回 READY 后，其余所有脚本和 `CLAUDE_CODE_PRODUCTION.md` 一律用钉住版本引擎里的副本
`$NALU_ENGINE_ROOT/skills/nalu-claude-code/`——TalentHub 不会覆盖已安装的旧 skill，引擎副本才与钉住的提交一致。

## 0. 一键准备（每次唤醒先跑）
```bash
bash $S/setup_host.sh --pin <PIN>
```
幂等：已就绪的机器 1–2 秒内返回；否则自动补齐 §1 系统依赖与引擎、Python 环境、运行时初始化，安装 Claude Code 并运行
`configure_claude_code.py --verify`（从 `~/.openclaw/openclaw.json` 读 StoryClaw provider 写入 Claude Code 配置）。
旧部署残留会被安全处理：引擎切到钉住的提交（有本地改动先 `git stash`），不是本脚本建的 `~/nalu_runtime` 改名为
`~/nalu_runtime_old_<时间>` 保留。有一集还在生产中（Claude Code 在跑，或最后状态不是 `FINAL_CUT_READY`）时，
脚本不切换引擎和 venv（`engine=DEFERRED_IN_FLIGHT`），新钉住的提交等那一集完成后的第一次唤醒再生效。只读最后一行 `NALU_SETUP: {...}`：`status=READY` 才继续；`BLOCKED` 时 `failed_step`
和 `~/.nalu_setup.log` 末尾说明原因（缺免密 sudo 编译 insightface、网络、relay 校验失败等），如实告诉用户。
`notes` 里有改名/切换记录时告诉用户一句。`setup_host.sh` 自己也跟随钉住版本：引擎切到新提交后，若引擎里的 `setup_host.sh`
与正在运行的不同，会自动交给引擎里的那份重跑一次。下面 §1–§2 是脚本做的事，供排障参考。

READY 之后检查代理自身是否有新版本（有一集在生产中时自动跳过）：
```bash
bash $S/self_update.sh --agent-id <本代理 id> --restart
```
只读最后一行 `SELF_UPDATE: {...}`：`UPDATED` 表示 TalentHub 上的新版已装好（指令文件、skill），30 秒后重启 OpenClaw gateway，
新指令从下一次会话生效——此时不要再开始新的生产步骤，告诉用户「已更新到 <版本>，重启后按新版继续」后结束本轮；
`UP_TO_DATE` / `DEFERRED_IN_FLIGHT` / `SKIPPED` 照常继续；`ERROR` 记进 `series/STATUS.md` 后照常继续。

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
时用 `--provider <名>`。Claude Code 默认使用 Claude Opus 5.5（provider 列表里有它就用中转自己的写法，否则用
`claude-opus-5-5`）；中转不认这个名字导致 `VERIFY_FAILED` 时，用 `--model <中转里 Opus 5.5 的 id>` 重跑。

## 3. 线主提供的信息（只通过对话）
- Giggle API key：线主在对话里发来时，直接写入 `$NALU_ENGINE_ROOT/.env` 的 `GIGGLE_API_KEY=`（保持 600），只回复「已配置 GIGGLE_API_KEY」。
- 原著：**代理自己上网找、自己抓正文，不向线主索要原著。**
  - 线主给了网址、文件或粘贴正文：直接用。
  - 只给了作品名：自己搜索正文所在的网站（维基文库、古登堡、公版书库、各大小说站等），目录逐章抓取、自动翻页，必要时用无头浏览器；
    一个站抓不全就换下一个站，至少试 3 个来源再说抓不到。
  - 什么都没给（例如只说「开始生产」）：自己选一部**公有领域**的中文小说（作者去世超过 50 年，如晚清、民国作品），
    不选本机 `series/` 里已做过的，然后按上面的方法抓正文；选定后告诉线主一句剧名即可，不等回复。
  - 需要登录或会员的站点：先找有没有免登录的来源；都没有才向线主要账号或 Cookie。
  - 抓不全时不凭搜索摘要或记忆补写：线主指定的作品报 `SOURCE_ACQUISITION_BLOCKED`；自己选的作品就换一部重新选，不停下。
  - 兜底：线主没指定作品、连换 3 部都抓不全或机器无法上网时，代理自己写一部原创短剧（人物、设定、分集大纲），存为
    `sources/<剧名>/ORIGINAL_OUTLINE.md` 当作原著直接开工；不借用现有作品或示例剧的人物与情节。
    `rights_basis` =「原创剧本，由短剧工作流代理创作；角色为 AI 生成的虚构人物」。
  原文存 `$NALU_RUNTIME_ROOT/sources/<作品>/`，记 URL、时间、SHA-256。
- X2C（x2creel.ai）发行 API key：线主发来时写入 `$NALU_RUNTIME_ROOT/credentials/x2c_api_key`（`chmod 600`），只回复「已配置 X2C_API_KEY」。
  机房批量部署时也可以由运维预先放好这个文件。
- 线主 id、剧名、风格、单集时长、预算、目标集数：没给就用默认值写进简报（目标集数默认按原著能改编的集数做完），不再征求确认。

## 4. 剧本交接（代理执行，免费）
每集写两个文件，然后跑运行时修复（目录先建好：`mkdir -p $NALU_ENGINE_ROOT/workflow/claude_writer_agent/scripts $NALU_RUNTIME_ROOT/briefs $NALU_RUNTIME_ROOT/sources`）：
1. `$NALU_ENGINE_ROOT/workflow/claude_writer_agent/scripts/<EP>_NARRATIVE_CANONICAL_v1.md`：按仓库模板
   `agent_factory/claude_writer_v2/templates/NARRATIVE_CANONICAL.template.md`。只写事实、可表演的动作和**逐字台词**，按
   `## <EP>-S01｜<LOC-ID>｜<时间>｜线A` 分场；不写机位、灯光、资产。一集 2–4 场、20–60 秒为宜；台词决定时长（每 4 个汉字约 1 秒）。
2. `$NALU_RUNTIME_ROOT/briefs/<EP>_PRODUCTION_BRIEF.json`：
   `{"episode","title","owner_id"（用户没指定就填 "owner"）,"style","target_seconds","budget_cap"（用户指定了才填；不填时 Claude Code 按预估 ×1.6、不低于 1500 自定）,"genre"（X2C 分类名，见 §6）,"synopsis"（全剧简介，发行用）,"authorization":{"order_text","rights_basis","consent_ref"},"characters":[{"character_id":"CHAR-XXX","name","slug","role":"protagonist|supporting","sex","apparent_age_range","appearance","wardrobe","voice_brief"}],"locations":[{"location_id":"LOC-XXX","label","description","fixed_elements":[]}],"owner_words":{"<日期>":"<线主原话>"}}`
   `authorization` 按默认授权条款填写（见代理 AGENTS.md §6）：`order_text` = 「默认授权：用户已提供 Giggle API key，按短剧工作流条款同意本项目每集付费生产，每集上限 <budget_cap> 积分」+ 用户关于预算/授权的原话（去掉任何 key、Cookie、密码）；
   `rights_basis` = 「用户承诺对所提供的原著与素材有使用权（短剧工作流默认条款）」+ 用户关于版权的原话（如有）；代理自选的公有领域作品写「公有领域作品：<作者>，卒于 <年份>」；`consent_ref` = 用户提供 key 的对话时间。
3. `python3 $S/apply_runtime_fixups.py --runtime-root $NALU_RUNTIME_ROOT --character <名>=<CHAR-ID>:<slug> ... --cap <预算>`
   以及 `$NALU_ENGINE_ROOT/.qingshan-venv/bin/python $S/make_endcard.py --runtime-root $NALU_RUNTIME_ROOT --title <剧名> --subtitle "第N集 · <集名>"`
   （片尾每集重做一次，文件名固定，S7 直接用最新的）。
写剧本时避开这些已知坑：首帧要看得见的道具别设计成「从怀里掏出」；古装灯写「无罩敞口油盏」；每个说话角色男女/音色要能区分；不写全黑画面。

## 5. 交给 Claude Code 并监控
```bash
python3 $S/claude_production.py start  --episode <EP>                 # 后台启动；生产合同见 ../CLAUDE_CODE_PRODUCTION.md
python3 $S/claude_production.py status --episode <EP>                 # 读最后一行 NALU_STATUS 与流水线状态
python3 $S/claude_production.py resume --episode <EP> --message "<文本>"
```
心跳（建议每 5 分钟）按 `status` 输出行动：
- `RUNNING`：不打扰。
- `IDLE` + `OWNER_DECISION_REQUIRED`：只剩少数情况会出现（Giggle key 缺失/失效、追加一次后预算仍不够、新的付费类别）。
  把 `question` 原样转给线主，**本项目暂停**等回复；线主回复后用 `resume --message "线主原话：<逐字>"`。不得替线主回答。
- `IDLE` + `WAITING_REMOTE`：5 分钟后 `resume --message "继续"`。
- `IDLE` + `BLOCKED` / `ERROR`：属于安装/环境问题的由代理修好后 `resume --message "继续"`；修不了的把 note 和日志末尾记进
  `$NALU_RUNTIME_ROOT/series/STATUS.md` 并告诉线主，本项目暂停。
- `IDLE` + `FINAL_CUT_READY`：不要停，按 §6 发行，再按 §7 启动下一集。`note` 里的默认接受记录汇总进 `series/STATUS.md`。
- `IDLE` 但没有 NALU_STATUS 行（会话异常结束）：`resume --message "继续，并在最后输出 NALU_STATUS 行"`。
只读 `status` 的结构化输出；不要改 Claude Code 写的剧本、订单、审核或事务文件。

## 6. 发行到 X2C（x2creel.ai，每集成片后自动做）
```bash
P=$NALU_ENGINE_ROOT/.qingshan-venv/bin/python
$P $S/publish_x2creel.py categories                       # 可用分类：玄幻异能/悬疑惊悚/科幻末世/都市复仇/热门综合/霸总甜宠/仙侠古装 …
$P $S/publish_x2creel.py publish --episode <EP> --title "<剧名>" --description "<简报 synopsis>" --category "<简报 genre>"
$P $S/publish_x2creel.py status                           # 本地记录 + X2C 审核状态
```
- 第一集创建 X2C 项目（封面默认取成片第 1.5 秒画面，也可 `--cover <图>`）；之后每集自动追加到同一个项目，`--title/--description/--category`
  可省略。项目 id 与已发的集记在 `$NALU_RUNTIME_ROOT/distribution/x2creel.json`，同一集重跑返回 `ALREADY_PUBLISHED`，不会重复发。
- 分类按题材选（简报 `genre`）；找不到时脚本落到「热门综合」。
- 返回 `BLOCKED: X2C_API_KEY_MISSING` 时请线主发 X2C key（§3），收到后重跑；其余 `ERROR` 记进 `series/STATUS.md`，下一次心跳重试，不阻塞下一集生产。
- 只用 X2C 分发 API 的 1、2、3、4、5、6 步（分类、上传 URL、发布、追加、查询、列出），不用 3.5（Developer JWT 代发布）。

## 7. 连续产剧
一集 `FINAL_CUT_READY` 并发行后，立刻做下一集，直到原著改编完（或达到用户指定的集数）：
1. 读原著的下一段情节和上一集叙事正典的结尾，写 `<EP+1>_NARRATIVE_CANONICAL_v1.md`：开头承接上一集结尾状态，不重演上一集。
2. 写 `<EP+1>_PRODUCTION_BRIEF.json`：沿用上一集简报的 owner_id、剧名、风格、genre、synopsis、authorization（`order_text` 里的集号与上限改成本集）；
   `characters`/`locations` 里**已出现的角色和地点逐字沿用原 ID 和设定**，只追加新的。
3. 有新的说话角色时补跑 `apply_runtime_fixups.py --character …`；重做片尾（§4.3，副标题换成本集）。
4. `claude_production.py start --episode <EP+1>`（每集一个新的 Claude Code 会话）。
5. 每集结束更新 `$NALU_RUNTIME_ROOT/series/STATUS.md`：集号、时长、Giggle 积分、X2C 集号/状态、默认接受了哪些质量问题、Claude Code 会话费用（`status` 里的 `cost_usd`）。
全部集完成后在 `series/STATUS.md` 写「SERIES_DONE」并告诉线主。

## 8. 不做的事
除 §6 的 X2C 发行外不上传、不发布到任何平台；不 git push；不把 key、Cookie 写进聊天、日志或仓库；不伪造线主原话；不删事务文件。
