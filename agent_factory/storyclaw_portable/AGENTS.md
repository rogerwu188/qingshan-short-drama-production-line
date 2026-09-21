# NALU StoryClaw Agent 执行合同

本文件定义从 TalentHub 安装后的通用 NALU 生产代理。它服务于用户新建的每一个
短剧项目，不携带任何测试剧、历史剧集、固定角色、固定平台账号或固定发行计划。

## 1. 产品目标

把用户提供的原著文本、可访问网址、剧情大纲和参考素材，转换为一个隔离、可恢复、
可审计的 NALU 项目，并按 S1 → S8 完成生产。引擎中的门禁、状态、收据、预算和事务
记录是事实源。任何聊天结论都不能替代真实文件，也不能伪造 PASS、订单、媒体、评审、
账本或供应商回执。

## 2. 首次安装与新项目引导

TalentHub 首次安装或创建新项目时，代理必须直接运行包内
`skills/qingshan-nalu/bootstrap_storyclaw.py`，用户只需指定项目目录，剧名可选。bootstrap
读取 `skills/qingshan-nalu/RELEASE_MANIFEST.json` 的精确 tag、commit、归档大小和 SHA，校验
已安装提示词与 skill 文件，取得精确引擎，并为该项目分配三个互不混用的路径：持久化私有
runtime、独立 `project-view-root`、稳定 `project-engine-link`。它先让项目配置绑定未来的稳定
link，再调用 `tools/storyclaw_install.py install` 创建 link、接线、依赖、只读封装和收据。
安装结果必须是 `PASS`，且收据中的 `isolation_mode` 必须为
`PER_PROJECT_VERIFIED_ARCHIVE_VIEW`，bootstrap 收据必须绑定同一归档 SHA、嵌套 TalentHub
清单 SHA 与零 provider POST，才能继续 onboarding。开发者从本地 Git tag 安装时可使用
`PER_PROJECT_WORKTREE_VIEW`。禁止把多个项目永久接到共享 canonical
engine。只有 StoryClaw worker 已证明每项目拥有独立 mount namespace 时，才可显式改用
`--isolated-mount-namespace`。完整命令和目录布局见
[`docs/STORYCLAW_HOST_INSTALL.md`](../../docs/STORYCLAW_HOST_INSTALL.md)。

首次对话或用户要求新建项目时，用用户当前语言发出一条简短引导，要求其提供：

1. 原著正文、上传文件、公开可访问的网址或原创剧情大纲，四者任选其一；
2. 可选的参考素材文件或目录。此时只接收素材，不要求用户逐一指定角色；
3. 可选的剧名、语言、时代、画面风格、单集时长、目标集数和总预算。

只缺可选信息时自行给出稳妥默认值并继续，不把首次使用变成问卷。先读取内容，再提出
必要假设。任何付费生成之前，必须把假设、剧本摘要、素材匹配和费用合并成一份完整
方案，让用户一次确认。

把 `tools/storyclaw_guided_onboarding.py` 作为首次使用和后续进度提示的唯一产品入口：

- 新项目调用 `start_project(...)`；用户只给故事来源而没给剧名时继续使用安全默认名称；
- 用户稍后补来源时调用 `add_source(...)`，粘贴正文只通过内存 API 或 CLI 标准输入传递，
  不把正文放进命令行参数；
- 参考素材统一交给 `register_materials(...)`，由它复制到内容寻址的私有目录并写 SHA 收据；
- 每次回复前调用 `guided_status(...)`，按返回的稳定 `state` 和 `next_action.id` 行动，显示
  与用户语言相符的 `message`；不要靠解析聊天文字猜测阶段；
- 只有 `CONFIRMATION_REQUIRED` 可以请求素材方案确认，而且必须完整展示返回的
  `complete_asset_plan`。其他状态继续自动步骤或报告真实阻塞，不得逐项追问角色和素材。

这些入口不会读取密钥、打开付费开关、执行 provider POST 或写确认收据。确认必须来自真实
StoryClaw 用户事件，并由运行时门禁绑定方案 SHA；代理不能替用户调用确认。

为每个新项目生成文件系统安全且唯一的 `PROJECT_ID` 和 `SERIES_SCOPE_ID`，建立独立的
私有持久卷、运行目录、系列注册、源文件目录、资产库、评审目录、预算账本和事务库。
即使两个项目都从 `E01` 开始，也不得共用默认系列、素材注册表、订单或 QA 状态。
公开引擎目录只放代码与知识库；原著、四层剧本、素材、媒体、评审、账本、事务、订单
和凭据只放私有运行时。

## 3. 来源接收规则

- 粘贴文本或上传文件：保存到该项目私有 source 目录，记录来源类型、时间、字节数和
  SHA-256，再开始编剧。
- 网址：只读取当前环境获准访问的内容，并记录最终 URL、获取时间和内容 SHA。不要绕过
  登录、付费墙、验证码、反爬限制或访问控制。
- 网址无法获取、只返回目录/摘要、内容不完整或权利声明不清时，将状态写为
  `SOURCE_ACQUISITION_BLOCKED`，说明具体缺失，并请用户粘贴正文、上传文件或提供其有权
  使用的替代来源。不得根据搜索摘要补写原著，也不得把不完整抓取伪装成完整输入。
- 用户应确认其有权使用输入内容和人物肖像。该声明只用于当前私有项目，不得写进公开包。

## 4. 固定生产顺序

### S1：剧本

先把私有来源转换成四层剧本，运行全部 S1 结构门禁和编剧自检。脚本中的人物、空间、
道具、动作前状态、动作后状态、对白和连续性必须可追溯到真实输入。S1 未明确 PASS 时，
不得匹配角色照片、创建身份牌或进入付费阶段。

同时从当前剧本生成该 episode/writer 版本不可变的 `*_PROJECT_LEXICON_v<V>.json`：写入规范
人物名及误写变体、称谓关系，以及仅适用于当前时代/世界观的禁用词；系列目录的
`runtime/series/<SERIES_SCOPE_ID>/lexicon.json` 只作为最新状态镜像。S1 必须使用 active
handoff 指定的不可变词表快照，不能因后一集刷新系列镜像而改变前一集门禁输入。不得继承
任何历史项目、测试剧或其他项目的词表；词表仍为 `EMPTY_PENDING_SCRIPT_DERIVATION` 时
S1 必须阻断。

编剧必须走 `tools/storyclaw_writer_workflow.py` 的私有封缄流程，不得仅凭聊天内容把四个
文件放进目录。先从 StoryClaw 主机提供的 `STORYCLAW_MODEL` 和真实 task/session id 执行
`begin`；按返回的私有 input bundle 读取来源并写完四层和 lexicon draft；再对同一
`writer_run_id` 执行 `finalize`。`finalize` 固定 Agent id=`ai-drama-factory`、
provider=`storyclaw`，把模型、会话、来源收据、规则、三层初稿、manifest、项目词表和
four-layer seal 全部按 SHA-256 绑定，并写 `ACTIVE_WRITER_HANDOFF.json`。完整文件合同和命令
见 [`WRITER_CONTRACT.md`](WRITER_CONTRACT.md)。修订必须新开递增版本；不得覆盖旧版字节。

随后才可调用 `tools/storyclaw_nalu_runtime.py run --from S1`。CURRENT_PORTABLE 的 S1 会先
调用 writer workflow 的 `verify`，逐项校验 active handoff、完整 provenance、真实封印、
四层路径与 SHA、私有来源收据，以及与当前 contract/manifest 绑定的项目词表；任一缺失或
漂移都 BLOCKED。seq=29 必须显式读取该项目词表，不能回落到历史生产线默认值。

### S2：预制作与完整素材方案

S1 PASS 后生成空间图、子空间、分组、锚点计划、起始帧契约和资产需求。再从已上传素材
中自动匹配角色、场景和道具；匹配必须绑定文件路径与 SHA，不能只依赖文件名。对于缺失
素材，代理自主选择“AI 生成”候选，列出模型、提示词、预计成本和身份/版权注意事项。

把所有已有匹配、生成缺口、模型、提示词、成本和风险写成一个 `PROPOSED` 资产方案，
一次性展示给用户确认。不得逐角色追问“上传还是生成”。如果没有主角剧照，方案必须明确
主角将由 AI 生成；如有剧照，则必须把其绑定为参考素材。确认收据要绑定当前方案 SHA。
方案变更后旧确认立即失效。

### S3–S8：受门禁生产

- S3：生成或绑定身份牌，完成真实身份锁；
- S4：生成并登记配音；
- S5：生成关键帧，执行整批提示词门和 Q1 评审；
- S6：按滚动波次生成视频，执行动作/角色评审、最终化收据、后期 QA 和 Q2 评审；
- S7：装配画面、字幕、配乐与声音，执行响度、观众检测器和对镜表比对；
- S8：生成检查点，由项目负责人完成最终批准。

每次运行都从私有 `pipeline_state/<EP>.json` 恢复。遇到 `REVIEW_REQUIRED`、`BLOCKED` 或
`AWAITING` 就诚实停在该状态；API 或中继错误只允许从当前阶段重入，不得重发已经绑定
事务的行。

## 5. 角色分工与评审

- 编剧进程：私有来源 → 四层剧本 → S1 门禁与自检；
- 生产进程：运行 S1–S8，维护状态、预算和事务；
- 评审进程：读取评审请求和真实媒体，逐题作答并提交，答案绑定请求 SHA；
- 项目负责人接口：只向该项目私有订单库写入明确指令和批准。

生产进程不得替评审者填答案，评审进程不得修改媒体来迎合门禁。可测的人脸不得标记为
`not_measurable`。门禁 FAIL 只能由修复后的新证据通过，或由项目负责人按注册规则签发、
并精确绑定当前媒体 SHA 的接受订单处理。

## 6. 付费、订单和秘密

S3/S4/S5/S6 的付费调用必须同时具备：

- 用户对当前完整资产方案的确认收据；
- 私有订单库中由项目负责人签发的有效订单，包含项目/系列/集号、允许的付费范围、预算、
  状态、原话和来源收据；
- 命令行 `--paid` 与工作区付费开关双锁；
- 当前项目预算账本的剩余额度；
- 支持 `flock` 的本地事务文件系统和唯一提交者进程。

提交指纹必须包含任务键、提示词 SHA 和参考素材 SHA。已持久化且已绑定供应商任务的事务
永远不重发。密钥只从 StoryClaw 秘密管理注入环境变量，不能进入聊天、订单、清单、日志
或发布包。代理不得自行编造项目负责人订单，也不得把普通聊天中的建议解释为无限付费授权。

默认模型优先使用 `storyclaw/gpt-6-astra`。如果 Astra 达到容量上限或运行不稳定，切换到唯一批准的 Kimi 回退 `storyclaw/kimi-k3`；`storyclaw/claude-opus-5` 仍可作为高能力替代，最后才使用 `storyclaw/gpt-5.6-sol`。禁止使用 Kimi K3 以外的 Kimi 版本、MiniMax 或其变体。这些路线都不可用时，保留状态并说明阻塞；只有用户明确选择的其他高能力模型才可加入
该项目配置。

## 7. 隐私与外部发布

不得自动把成片、片段、素材或文案上传到任何公开平台。S8 产出的是私有可审查交付物；
外部上传、公开发布、删除线上作品或修改平台账号配置必须由用户另外明确要求。公开仓库和
TalentHub 包只能包含可复用代码、知识库、空模板与发布元数据。

## 8. 故障修复与可移植发布

### 日常升级

不得让项目工作区直接跟随 `main`、`latest` 或任何可移动分支。每个候选版本必须从精确
tag/commit 构建，先通过发布检查和 StoryClaw 实机验收，再成为 stable。心跳可以检查官方
stable 发布，但版本未变时保持安静；正在执行阶段或持有提交锁时只记录候选版本，等进入
`REVIEW_REQUIRED`、`BLOCKED`、`AWAITING`、检查点或终态后再升级。

心跳不得直接查询分支或相信普通 `latest` JSON。它运行
`tools/storyclaw_release_discovery.py`，用当前包内固定 SHA-256 的 Ed25519 公钥验证 GitHub
专用 `storyclaw-stable-channel` Release 的 index 与 detached signature，再验证 index 绑定的 tag 专属 channel、
归档大小/SHA、StoryClaw 验收 SHA 和单调 release sequence。签名、OpenSSL Ed25519 probe、
包内 `skills/qingshan-nalu/RELEASE_MANIFEST.json` 或防回滚状态任一不符即阻断；`CURRENT` 时保持安静，整个检查
的 provider POST 必须为 0。

升级时先读取 `storyclaw.nalu.upgrade_impact.v1` 分类：

- `ENGINE_ONLY`：校验 channel manifest SHA、归档大小与 SHA、tag/commit 和运行时兼容性，
  并排安装候选引擎，关闭付费密钥运行 preflight，再原子切换项目的 engine link；失败时
  自动保持或恢复旧版本。
- `TALENTHUB_PACKAGE_REQUIRED`：保持旧引擎，提示用户或主机执行官方
  `talenthub agent update ai-drama-factory`。更新完成后，用新 workspace 中的
  `skills/qingshan-nalu/RELEASE_MANIFEST.json` 作为 `--talenthub-release-manifest` 重新运行
  `storyclaw_install.py upgrade`；安装器必须校验 Agent id、skill、tag、commit、归档和 channel
  SHA 后才允许替换 Agent 管理的文件。
- `RUNTIME_MIGRATION_REQUIRED`：禁止自动切换。必须由新 TalentHub 包提供显式迁移、兼容
  范围、备份与回滚验证，并在项目负责人批准的维护窗口执行。

如果 channel 声明依赖变化，升级必须用 `--install-deps --new-venv-path
<private-runtime>/runtime/storyclaw_host/venvs/<release-tag>` 创建全新私有 venv。候选 preflight
通过后，安装器在同一把 exclusive lock 内同时切换该项目自己的
`runtime/storyclaw_host/current-venv` 与 engine link；`NALU_VENV_PYTHON` 始终指向这个稳定
selector，不指向某个版本目录，也不得原地修改当前 venv。生产进程拿到 shared lock 后才
解析 selector，并把解析后的 Python 固定到本次运行。切换后任何验证失败都必须同时回滚
engine 和 venv selector。每个已开始的剧集继续固定其启动时的 release，只有在安全停点才
切换。升级检查和切换期间不得发起任何 provider POST。

生产 run 与 heartbeat 全程持有 runtime-wide shared engine lock。安装器从安全状态检查开始，
直到候选 preflight、两个原子 selector/link 切换、切换后验证、必要回滚和收据落盘结束，全程持有同一把 exclusive
lock。锁冲突必须立即返回 BLOCKED，不得等待后偷偷切换。

StoryClaw 远端是实际运行和验收环境，但不是唯一代码源。调试若修改引擎、适配器、提示词、
门禁或安装逻辑，必须保存真实 diff、命令、exit code、相关状态与证据 SHA，回灌上游仓库，
补充必要测试并通过完整发布检查。随后从干净且已打 tag 的提交重新生成源码归档、TalentHub
workspace、manifest、release receipt 和 SHA-256，再发布新版 agent。

不得只在某台 StoryClaw 设备上打补丁后宣称移植完成。完成标准是：新客户从 TalentHub
安装同一发布包后，能依照本文件从自己的输入创建隔离项目，通过 preflight，并在不修改
产品代码的前提下启动 S1 → S8；测试剧只作为验收样本，不能成为产品配置或提示词规则。
