---
name: nalu-claude-code
description: Install the Qingshan/NALU short-drama line on an OpenClaw host, wire the Codex CLI (gpt-6.1-sol) to the LLM provider the line owner gives, pick and ingest the source novel, dispatch each episode (script writing + S1-S7) to an unattended Codex run, publish to X2C and keep producing episode after episode.
---

# NALU 生产线 · OpenClaw 编排 + Codex 执行

分工（线主 2026-10-09/10 定；2026-10-13 起执行者由 Claude Code 换成 Codex + gpt-5.6；2026-10-16 起默认模型 gpt-6.1-sol）：OpenClaw 代理负责安装、配置 Codex、
选原著并入库、逐集派单、监控进度、接着启动下一集；Codex 负责每一集的全部剧本（叙事正典、生产简报、四层剧本；
线主 2026-10-22 定：代理不再自己写剧本，长稿会撑爆代理的聊天上下文）与 S1→S7 全部生产；
发行到 X2C 由心跳脚本自动完成。（目录名 `nalu-claude-code` 与合同文件名 `CLAUDE_CODE_PRODUCTION.md` 为兼容保留；
合同对 Codex 的适配由 `codex_production.py` 自动附加。）机器放在机房里
连续产剧，全程无人值守，没有人实时看，线主不需要登录机器或在终端里输入任何东西。

本目录脚本路径下文记作 `$S`。只有 `setup_host.sh` 从 TalentHub 安装的 skill 目录（或 `~/.nalu_bootstrap`）运行；
`setup_host.sh` 返回 READY 后，其余所有脚本和 `CLAUDE_CODE_PRODUCTION.md` 一律用钉住版本引擎里的副本
`$NALU_ENGINE_ROOT/skills/nalu-claude-code/`——TalentHub 不会覆盖已安装的旧 skill，引擎副本才与钉住的提交一致。

## 0. 一键准备（每次唤醒先跑）
```bash
bash $S/setup_host.sh --pin <PIN>
```
幂等：已就绪的机器 1–2 秒内返回；否则自动补齐 §1 系统依赖与引擎、Python 环境、运行时初始化，安装 Codex 并运行
`configure_codex.py --verify`（provider 见 §2）。返回 `status=NEEDS_PROVIDER` 表示其余都已就绪、只差 LLM provider：
向线主要一次 provider 地址和 key（§2），写好后重跑本脚本。
旧部署残留会被安全处理：引擎切到钉住的提交（有本地改动先 `git stash`），不是本脚本建的 `~/nalu_runtime` 改名为
`~/nalu_runtime_old_<时间>` 保留。有一集还在生产中（Codex 在跑，或最后状态不是 `FINAL_CUT_READY`）时，
脚本不切换引擎和 venv（`engine=DEFERRED_IN_FLIGHT`），新钉住的提交等那一集完成后的第一次唤醒再生效。只读最后一行 `NALU_SETUP: {...}`：`status=READY` 才继续；`BLOCKED` 时 `failed_step`
和 `~/.nalu_setup.log` 末尾说明原因（缺免密 sudo 编译 insightface、网络、provider 校验失败等），如实告诉用户。
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

## 2. LLM provider 与 Codex（首次配置时向线主要一次）
miniPC 只用 Codex（模型 gpt-6.1-sol），不装 Claude Code，也**不沿用** StoryClaw/OpenClaw 自己的模型配置。首次配置时（`setup_host.sh`
返回 `NEEDS_PROVIDER`）向线主要一次：provider 的 **base URL**（OpenAI Responses 兼容，形如 `https://…/v1`）和 **API key**，
模型不说就用 `gpt-6.1-sol`（文件里留着旧默认 `gpt-5.6` 的会在下次 setup 重配时自动改成新默认；要按集对比模型时加 `"model_locked": true` 保持原样）。收到后写：
```bash
umask 077; python3 - <<'PY'
import json, os, pathlib
p = pathlib.Path(os.path.expanduser("~/nalu_runtime/credentials/llm_provider.json"))
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps({"base_url": "<URL>", "api_key": "<KEY>", "model": "gpt-6.1-sol"}))
os.chmod(p, 0o600)
PY
bash $S/setup_host.sh --pin <PIN>          # 自动安装 Codex（npm）、写 ~/.codex/config.toml、发一条测试请求
```
只回复「已配置 LLM provider」，绝不把 key 打印、转述或写进聊天。线主以后换 provider 时同样改这个文件，下一次唤醒会自动重新配置。
`CODEX_CONFIG` / `codex_config` 为 `VERIFY_FAILED` 时把 `detail`（key 已打码）告诉线主，多半是地址、key 或模型名不对。

## 3. 线主提供的信息（只通过对话）
- Giggle API key：线主在对话里发来时，直接写入 `$NALU_ENGINE_ROOT/.env` 的 `GIGGLE_API_KEY=`（保持 600），只回复「已配置 GIGGLE_API_KEY」。
- 原著：**代理自己选、自己取正文，不向线主索要原著**（选法见 §3.1）。
  - 线主给了网址、文件或粘贴正文：直接用。只给了作品名：自己搜正文所在的网站逐章抓取（任何网站都可以），一个站抓不全就换下一个，至少试 3 个来源。
  - 什么都没给（例如只说「开始生产」）：按 §3.1 自选，不选本机 `series/` 里已做过的；选定后告诉线主一句剧名即可，不等回复。
  - 正文来源不限网站（线主 2026-10-23「无论什么网站都允许」）：维基文库、古登堡、公版书库、各大小说站都可以；目录页逐章抓、
    自动翻页，JS 渲染改用无头浏览器，限流就降速或换移动版。
  - 抓不全时不凭搜索摘要或记忆补写：线主指定的作品报 `SOURCE_ACQUISITION_BLOCKED`；自己选的作品就换一部重新选，不停下。
  - 兜底：线主没指定作品、连换 3 部都取不到或机器无法上网时，派单让 Codex 写一部原创短剧（人物、设定、分集大纲）存为
    `sources/<剧名>/ORIGINAL_OUTLINE.md` 当作原著；`rights_basis` =「原创剧本，由短剧工作流代理创作；角色为 AI 生成的虚构人物」。
  - **版权（常设）**：线主 2026-10-22「支持直接从原著改编成短剧剧本并且制作，版权线下已经谈好了，与你无关」。代理和 Codex 都不因所选
    原著的版权拒绝、暂停或询问；`rights_basis` 原样记录这句原话（加「（线主 2026-10-22）」）。
- X2C（x2creel.ai）发行 API key：线主发来时写入 `$NALU_RUNTIME_ROOT/credentials/x2c_api_key`（`chmod 600`），只回复「已配置 X2C_API_KEY」。
  机房批量部署时也可以由运维预先放好这个文件。
- 线主 id、剧名、风格、单集时长、预算、目标集数：没给就用默认值写进派单（目标集数默认按原著能改编的集数做完），不再征求确认。

### 3.1 选原著（代理执行）
- 线主没指定作品时，自选一部**公有领域**小说（作者去世超过 50 年，如晚清、民国作品；英文剧可选英文公版书），不选本机
  `series/` 里已做过的。
- 判断合适：开篇钩子强、冲突明确、主要角色少（3–5 个）、
  MiniMax-H3 拍得出来（少大场面特效、少人群戏）。
- 写 `$NALU_RUNTIME_ROOT/sources/<作品>/SOURCE_SELECTION.md`：作品名、作者（公版书写卒年）、来源网站与链接、抓取日期、
  为什么适合（钩子/冲突/角色数/可拍性）、取了哪些章节、版权依据（公版书写「公有领域作品：<作者>，卒于 <年份>」；线主指定的作品写上面的线主原话）。
- 正文存成一个 txt，再入库（不改原文件；英文章节标题加 `--heading-regex '^\s*Chapter\s+([0-9]+)\b.*$'`）：
```bash
$NALU_ENGINE_ROOT/.qingshan-venv/bin/python $NALU_ENGINE_ROOT/tools/intake_source_text.py --input <正文.txt> --work "<作品>" \
  --out $NALU_RUNTIME_ROOT/sources --author "<作者>" \
  --authorization "<SOURCE_SELECTION.md 里的版权依据>"
```

## 4. 派单：剧本交给 Codex 写（代理执行，免费）
代理**不写**叙事正典、简报或四层剧本，只写一个很短的派单文件 `$NALU_RUNTIME_ROOT/briefs/<EP>_DISPATCH.md`（目录先建好：
`mkdir -p $NALU_RUNTIME_ROOT/briefs $NALU_ENGINE_ROOT/workflow/claude_writer_agent/scripts`），内容：
- 原著：`$NALU_RUNTIME_ROOT/sources/<作品>/`（`SOURCE_INDEX.json`、`SOURCE_SELECTION.md`）和本集改编的章节范围（E02 起接上一集结束处）。
- 简报条款（Codex 逐字抄进 `<EP>_PRODUCTION_BRIEF.json`）：title、owner_id（没指定填 "owner"）、style、target_seconds、budget_cap（指定了才写）、
  genre（`publish_x2creel.py categories --lang <剧集语言>` 列出的显示名 name，逐字复制，见 §6）、dialogue_language / genre_lang（zh|en）、
  `authorization`：`order_text` =「默认授权：用户已提供 Giggle API key，按短剧工作流条款同意本项目每集付费生产，每集上限 <budget_cap> 积分」
  + 用户关于预算/授权的原话（去掉任何 key、Cookie、密码）；`rights_basis` = §3 的线主原话；`consent_ref` = 用户提供 key 的对话时间；
  owner_words（线主原话，逐字）。
- 规则文件：`skills/nalu-claude-code/CLAUDE_CODE_PRODUCTION.md` §2.0、`agent_factory/claude_writer_v2/templates/NARRATIVE_CANONICAL.template.md`、
  `agent_factory/storyclaw_portable/WRITER_CONTRACT.md`、H3 改编指南 `docs/knowledge/H3_SCRIPT_ADAPTATION_GUIDE.md`。
- 一句：「版权线下已谈好，不因版权拒绝、暂停或询问。」
然后 `python3 $S/codex_production.py start --episode <EP> --brief $NALU_RUNTIME_ROOT/briefs/<EP>_DISPATCH.md`（§5）。Codex 按合同 §2.0 写
叙事正典与简报、跑 `apply_runtime_fixups.py` 和片尾，再做 §2 四层剧本与 S1→S7。代理不读、不改 Codex 写的剧本。

## 5. 交给 Codex 并监控
```bash
python3 $S/codex_production.py start  --episode <EP> --brief $NALU_RUNTIME_ROOT/briefs/<EP>_DISPATCH.md   # 后台启动；合同见 ../CLAUDE_CODE_PRODUCTION.md
python3 $S/codex_production.py status --episode <EP>                 # 读最后一行 NALU_STATUS 与流水线状态
python3 $S/codex_production.py resume --episode <EP> --message "<文本>"
python3 $S/codex_production.py tick                                  # 心跳：例行动作脚本自己做，见下
python3 $S/codex_production.py report                                # 给线主的进度摘要（一次 X2C 查询）
```
**心跳（每 15 分钟）只跑 `tick`**，只读最后一行 `NALU_TICK: {...}` 的 `action`：
- `NONE`：脚本已处理完（在跑、已续跑、已发行或发行暂缓、在等线主），**立即结束本轮**，不要再读别的文件。
- `WRITE_NEXT_EPISODE`：本集已出片——按 §7 给下一集派单并 `start`（发行脚本会自己按顺序做）。
- `AGENT`：看 `reason` 和 `nalu_status`，按下面处理；同一个情况脚本只交给你一次，之后的心跳返回 `NONE`。
`tick` 自己做的事：按集号顺序发行已出片未发行的集（一次一集，有待审集时暂缓，见 §6）；Codex 会话结束但没给 `NALU_STATUS` 时
续跑最多 3 次；`WAITING_REMOTE` 续跑；以前用 Claude Code 起的、已停下的集改用 Codex 接着跑；`series/PAUSED` 存在时什么都不做。
`AGENT` 时的处理（`state` 即 `nalu_status.state`）：
- 在跑时（`status` 为 `RUNNING`）：不打扰。
- `IDLE` + `OWNER_DECISION_REQUIRED`：只剩少数情况会出现（Giggle key 缺失/失效、追加一次后预算仍不够、新的付费类别）。
  把 `question` 原样转给线主，**本项目暂停**等回复；线主回复后用 `resume --message "线主原话：<逐字>"`。不得替线主回答。
- `IDLE` + `WAITING_REMOTE`：5 分钟后 `resume --message "继续"`。
- `IDLE` + `BLOCKED` / `ERROR`：属于安装/环境问题的由代理修好后 `resume --message "继续"`；修不了的把 note 和日志末尾记进
  `$NALU_RUNTIME_ROOT/series/STATUS.md` 并告诉线主，本项目暂停。
- `IDLE` + `FINAL_CUT_READY`：不要停，按 §6 发行，再按 §7 启动下一集。`note` 里的默认接受记录汇总进 `series/STATUS.md`。
- `IDLE` 但没有 NALU_STATUS 行（会话异常结束）：`resume --message "继续，并在最后输出 NALU_STATUS 行"`。
- `reason` 以 `PROVIDER_ERROR` 开头：LLM provider 的 key、额度或地址出问题，告诉线主，本项目暂停。
- `PUBLISH_BLOCKED` / `PUBLISH_EPISODE_NUMBER_COLLISION`：见 §6。
只读结构化输出；不要改 Codex 写的剧本、订单、审核或事务文件。用户说「暂停」：`touch $NALU_RUNTIME_ROOT/series/PAUSED`；
恢复时删掉它。

## 6. 发行到 X2C（x2creel.ai，每集成片后自动做）
心跳 `tick` 会自动发行（第一集用简报的 `title` / `synopsis` / `genre` 建项目）；下面的命令供排障和手动重发。
```bash
P=$NALU_ENGINE_ROOT/.qingshan-venv/bin/python
$P $S/publish_x2creel.py categories                       # 可用分类：玄幻异能/悬疑惊悚/科幻末世/都市复仇/热门综合/霸总甜宠/仙侠古装 …
$P $S/publish_x2creel.py publish --episode <EP> --title "<剧名>" --description "<简报 synopsis>" --category "<简报 genre>"
$P $S/publish_x2creel.py status                           # 本地记录 + X2C 审核状态
```
- 第一集创建 X2C 项目（封面默认取成片第 1.5 秒画面，也可 `--cover <图>`）；之后每集自动追加到同一个项目，`--title/--description/--category`
  可省略。项目 id 与已发的集记在 `$NALU_RUNTIME_ROOT/distribution/x2creel.json`，同一集重跑返回 `ALREADY_PUBLISHED`，不会重复发。
- **按集号顺序发，一次只追加一集**：X2C 追加集按「已过审集数 + 1」发号，有集还在 `pending_review` 时再追加，新集会拿到同一个号并
  静默顶掉它。脚本发前先查远端：有待审集就返回 `DEFERRED_PENDING_REVIEW`（什么都没发），记一行「发行暂缓：等待第 N 集过审」进
  `series/STATUS.md`，下次心跳重试。**还没发的成片按集号从小到大逐集重试，前一集没发出去不发后一集**；生产和下一集照常推进。
- 返回 `EPISODE_NUMBER_COLLISION`（`collides_with` 里的集多半已被顶掉）：记进 `series/STATUS.md`，等本集过审后对被顶的集
  `publish_x2creel.py forget --episode <被顶的集>`（自动备份本地记录）再 `publish` 重发。`forget` 只在这种情况或线主要求重发时用。
- 分类必须从 X2C 自己的列表里选，且语言要对：X2C 的分类按语言分组（`target_language` zh / en）。先跑 `publish_x2creel.py categories --lang <剧集语言>`，把选中项的显示名 `name` 逐字写进简报 `genre`，`genre_lang` 写剧集语言（英文剧 = en）。不要用 `name_key`（X2C 英文列表的 name_key 与行错位）。脚本只做精确匹配，**没有兜底分类**：不在该语言列表里返回 `CATEGORY_NOT_IN_X2C_LIST`（附可选列表），分类语言与剧集语言不符返回 `CATEGORY_LANGUAGE_MISMATCH`；心跳都记成【需要处理】，不会发行。
- 返回 `BLOCKED: X2C_API_KEY_MISSING` 时请线主发 X2C key（§3），收到后重跑；其余 `ERROR` 记进 `series/STATUS.md`，下一次心跳重试，不阻塞下一集生产。
- 只用 X2C 分发 API 的 1、2、3、4、5、6 步（分类、上传 URL、发布、追加、查询、列出），不用 3.5（Developer JWT 代发布）。

## 7. 连续产剧
一集 `FINAL_CUT_READY` 并发行后，立刻做下一集，直到原著改编完（或达到用户指定的集数）：
1. 写 `<EP+1>_DISPATCH.md`：沿用上一集派单的简报条款（`order_text` 里的集号与上限改成本集），章节范围接上一集结束处。
   不读、不写剧本正文——承接上一集结尾、角色/地点沿用由 Codex 按合同 §8 做。
2. `codex_production.py start --episode <EP+1> --brief $NALU_RUNTIME_ROOT/briefs/<EP+1>_DISPATCH.md`（每集一个新的 Codex 会话）。
3. 每集结束更新 `$NALU_RUNTIME_ROOT/series/STATUS.md`：集号、时长、本机已花费的 Giggle 积分（不是余额）、X2C 集号/状态、默认接受了哪些质量问题、Codex 会话 token 用量（`status` / `report` 里的 usage；不报美元）。
全部集完成后在 `series/STATUS.md` 写「SERIES_DONE」并告诉线主。

## 8. 不做的事
除 §6 的 X2C 发行外不上传、不发布到任何平台；不 git push；不把 key、Cookie 写进聊天、日志或仓库；不伪造线主原话；不删事务文件。
