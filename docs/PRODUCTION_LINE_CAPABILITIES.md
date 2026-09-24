# 青山短剧生产线：完整流水线功能与能力

**版本基线：** 当前 `nalu` 引擎工作树（代码入口 `lines/nalu/runtime/tools/nalu_pipeline.py`）

**用途：** 给新代理、第三方部署者和线主说明这条生产线能做什么、每一步产生什么、哪些环节仍需要人工或外部系统。本文描述的是代码实际行为，不把未接入的能力写成“已支持”。

## 1. 生产线定位

这是一条“编剧四层合同 → 预制作 → 关键帧 → 视频 → 剪辑与 QA”的可恢复短剧生产线。它负责：

- 将叙事、导演、生成和集级 manifest 编译成可审计的机器合同；
- 为角色、声音、道具、地图、服装和镜头建立稳定 ID、SHA 与作用域；
- 按模型分别编译 Seedance 2.0（代码中常称 SD2）和 MiniMax-H3 提示词；
- 在付费 POST 前执行预算、权限、地图、身份、提示词、声音、时长和事务门禁；
- 记录 Giggle 任务 ID、请求指纹、响应、收割文件、费用和重试状态，避免重复扣费；
- 生成关键帧、视频、字幕、选择性配乐、混音、响度和最终 QA 证据；
- 在失败、断流或进程中断后从持久状态继续，而不是从头重复提交。

它不是授权、版权、肖像或平台发布的权威来源；也不会代替线主看片或替线主作版权/发布决定。仓库没有自动上传 YouTube/抖音的生产路径。

## 2. 部署架构与作用域

生产线由一个代码仓库和一个不入库的运行时组成：

| 根目录 | 内容 | 是否进入 Git |
|---|---|---|
| `ENGINE_ROOT` | 编译器、门禁、提交器、收割器、装配器、QA、写手规则 | 是（代码/通用配置） |
| `RUNTIME_ROOT` | `qingshan.json`、原文、人物照、音色、资产库、账本、事务、审核回执、状态、成片 | 否 |
| `NALU_WORK_ROOT` | 每集预制作、提示词、关键帧、视频、装配中间文件 | 通常否 |

必须显式绑定作用域：

```bash
export NALU_ENGINE_ROOT=/path/to/nalu
export NALU_RUNTIME_ROOT=/path/to/nalu_runtime
export NALU_WORK_ROOT=$NALU_RUNTIME_ROOT/workflow/nalu
export NALU_SERIES_SCOPES=$NALU_RUNTIME_ROOT/runtime/series_scopes.json
```

E59 使用独立作用域 `QINGSHAN-E59` 和 `/Users/rogerwu/nalu_runtime_e59`。不能把 E59 写入旧的 `NALU-YEWUJIANG` 运行时，也不能混用旧地图、旧资产库或旧事务目录。

凭据只从 `$ENGINE_ROOT/.env` 或部署环境读取：`GIGGLE_API_KEY`、`GIGGLE_API_BASE`。离线构建和 QA 必须去掉 API key；只有付费子进程才注入它。

## 3. 端到端阶段（S1–S8）

### S1：剧本就绪与合同门

输入是四层文件：

1. `NARRATIVE_CANONICAL`：源章事实、逐字对白、节拍和故事因果；
2. `DIRECTING_SCRIPT`：景别、机位、运动、起始/完成状态、节奏和声音设计；
3. `GENERATION_CONTRACT`：角色、服装、道具、地图、天气、声音、动作和模型约束；
4. `manifest`：集级镜头/场景索引、源文绑定和交付参数。

门禁包括：

- 源章/场次声明与 SHA；
- 角色实体唯一性、别名消歧、动作主语/承受者、对白说话人和唇形归属；
- 静态设计 R1–R8：机位运动、锁机位比例、远景后身份重新锚定、镜头长度；
- 剧本结构：前段钩子、对白密度、动作结果、对抗动机、道具来源、人物铺垫/回收和禁用词；
- 连续性状态：生死状态、群体数量、动物/生物卡、伏击空间、服装继承；
- 每镜、每场、每单元的时长可执行性。

S1 失败时只能修改剧本/合同层，不能带着 `AUTHORING_REQUIRED` 或未解析实体进入付费阶段。

### S2：预制作（免费）

`build_nalu_preproduction.py` 把四层合同编译为：

- 全局空间图、地点/房间/区域/相机/轴线和固定物绑定；
- 资产需求与新地点 place spec；
- 编辑镜头表、视频单元分组计划、波次计划；
- 关键帧锚点计划、起始帧语义合同和机器门报告；
- 视频交易清单的初始结构；
- 按单元的服装、道具、动作、声音、天气、生态、转场和时长合同。

新地点由 `extend_global_space_map.py` 扩展，不覆盖既有地图几何。自动选址可以输出合法地图，但如果是 `AUTO_SITED_REQUIRES_SPATIAL_REVIEW`，仍需人工确认。

### S3：身份/资产卡（付费）

功能：

- 角色三视图、道具卡、场景/构筑物卡的批量生成；
- 参考图 SHA 绑定和跨集复用；
- InsightFace 身份相似度、人数、OCR、时代/材质检查；
- 身份 QA、人工审阅和 `LOCKED_PRODUCTION_READY` 入库；
- 资产库按系列作用域隔离，已锁定且 SHA 一致的资产不重复 POST。

默认身份图模型/规格由当前配置决定（当前生产合同通常为 `gpt-image-2-pro`、2K）；供应商任务单价以预算计划和实际回执为准，不能在文档中硬编码为实际账单。

### S4：声音参考（付费）

功能：

- 从 `voice_catalog.json` 为每个说话实体建立稳定 voice entity；
- 生成/归一化/上传参考音；
- `voice_registry.json` 登记 remote asset ID、SHA、角色归属和用途；
- F0、采样率、单声道、音色共现重叠预检；
- 将 `character_id → voice_entity_id → speaker slot → lip owner` 编入视频合同。

H3 和 SD2 的声音传输格式不同：H3 使用公开参考 URL，SD2 使用已注册音频资产 ID；不能交叉套用。

### 整批提示词门（S5 之前）

关键帧提示词先规划编译、再做整批注册和 QA：

- `prompt_batch_register.py` 绑定每行提示词 SHA；
- `prompt_batch_qa.py` 做确定性、字段覆盖和失败记忆检查；
- 每次镜头文字改变必须生成新 SHA、撤下旧候选并重新登记；
- 失败一次后必须完整重写提示词/动作 IR，禁止对原失败提示词做同义词微调重试。

### S5：关键帧与 Q1（付费）

功能：

- 依据 entry state 生成关键帧，不提前渲染 completion state；
- 一镜多实体的参考图顺序、身份绑定和地图锚点校验；
- 关键帧收割、SHA 绑定、Q1 身份/空间/道具/时代/OCR 审核；
- 起始帧观察证据，确认画面只表现入口状态；
- 失败关键帧停放，旧提示词/旧收割副本不再进入当前目录；
- 跨集按精确 SHA 复用，不因“同一个人物”自动复用不兼容的场景或状态。

### S6：视频、原生音频和选择性 BGM（付费）

功能：

- 按视频单元提交多模态 I2V/参考图请求；
- SD2 与 H3 使用各自的 provider prompt renderer；
- 单元保留剧情授权时长、供应商时长、源素材区间和最终时间线区间；
- 滚动波次生成：已完成句柄立即收割和技术检查，不等待整批；
- 原生对白、环境声、动作声和音效随视频任务保留；
- 仅在生成合同明确声明时生成选择性 BGM 源；BGM 事务独立记账；
- post-generation QA：容器/编解码/黑帧/冻结/重复/时长/音频轨、ASR 基础检查和基本剧情结果；
- Q2：身份、OCR、出入画、动作结果、状态连续性和缺陷级别；
- 每个成功远端任务绑定任务 ID、请求指纹、模型、prompt SHA、参考 SHA 和费用回执。

动作单元使用共享 Action IR：锁定发起者、承受者、武器归属、力量路径、接触/闪避/威胁三选一、主反馈/次反馈和不可逆结果。H3 另有快速爆发、身体动力链、双方交换和声音同步约束；SD2 保留自己的 provider grammar。

### S7：剪辑、字幕、BGM、响度与最终 QA（不再 POST）

S7 只消费已准入素材，不产生新的 Giggle 视频任务。主要能力：

- 根据已准入 storyboard source 建立 AgentCut 项目；
- 按合同镜头顺序和时间线装配；
- 烧录逐字中文字幕和时间码；
- 追加品牌/片尾（默认 3 秒，如合同另有声明以合同为准）；
- 选择性 BGM：计划 → 生成结果核对 → 放置 → duck/mix → QA；
- 原生音频响度分角色处理、真峰限制、最终集成响度和静音间隔检查；
- 受控 H.264 VideoToolbox 编码，必要时回退到 libx264；
- final audience detectors：钩子、对白覆盖、静音间隔、音色区分、情绪动态、词表/OCR、吉祥物误入和响度；
- `final_qa_evidence_bundle.py` 汇总发布前全部适用门禁。

S7 不以“存在 AAC 音轨”冒充声音通过，也不以未执行的视觉检查冒充 PASS。

### S8：交付检查点与线主审批

S8 写入 `deliverables/<EP>/CHECKPOINT.md`、阶段汇总、费用和证据索引，并保持等待线主看片/审批。审批命令：

```bash
$PY lines/nalu/runtime/tools/nalu_pipeline.py approve \
  --episode E01 --by <configured-line-owner-id> --note "..."
```

发布到 YouTube/抖音不在 `nalu_pipeline.py` 中；需要线主另行授权并使用浏览器/平台流程。

## 4. 两种视频模型的能力边界

| 项目 | Seedance 2.0（SD2） | MiniMax-H3 |
|---|---|---|
| Giggle 路由 | `seedance-2.0-pro` | H3 专用路由/能力插件 |
| 当前原生竖屏 | 720p，9:16（720×1280） | 768p，9:16 |
| 提示词 | SD2 原有完整语法，负面词按 SD2 规则 | 独立原生视听编译器；正面文本更严格 |
| 参考绑定 | 机器实体/参考 SHA | `character_id → SUBJECT_N → @ImageN → SPEAKER_N → @AudioN` |
| 音频 | 注册音频 asset ID | 公开 HTTPS 参考音 URL |
| 绝对限制 | 禁止未声明人物、动作、声音、地图和天气 | 额外禁止隐式说话、缺失实体正面词、静态/推手式动作等 |

未注册的 `seedance-2.0-fast`、`mini`、无版本 `seedance-2.0` 不允许进入当前生产合同。H3 的官方提示/API 能力由执行环境插件提供，但不能绕过仓库的交易、预算、地图和 QA 门。

## 5. 费用、权限和幂等性

付费需要两把锁同时打开：

1. 命令行 `--paid`；
2. 运行时 `qingshan.json` 中 `generation.paid_requests_enabled=true`。

除此之外还必须有：

- 线主授权回执和订单序号；
- 当前集预算计划没有超限；
- 资产/声音/提示词/关键帧/视频合同全部 PASS；
- 事务清单允许该阶段 POST。

持久化防重复机制包括：

- 按模型、时长、画幅、prompt SHA、参考 SHA 的生成指纹；
- 图片/视频/BGM 独立事务目录；
- 断流先做账单窗口对账，确认未扣费后才可重提；
- 已绑定 task ID 永不重复 POST；
- 失败提示词登记 `do_not_repeat`，下一次必须使用新候选和新 SHA；
- 账本按系列/集作用域隔离，外来共享账号账单不得计入本集。

当前 nalu 线默认每集上限为 8000 credits、并发不超过 1；部署者可以在运行时配置不同上限，但不能绕过硬预算门。

## 6. 可恢复运行与命令

```bash
PY=$NALU_ENGINE_ROOT/.qingshan-venv/bin/python
PIPE=$NALU_ENGINE_ROOT/lines/nalu/runtime/tools/nalu_pipeline.py

# 免费前置 / 规划
$PY $PIPE run --episode E01

# 已明确授权后才开启付费阶段
$PY $PIPE run --episode E01 --paid

# 从具体阶段恢复（不会重发已绑定任务）
$PY $PIPE run --episode E01 --from S5 --until S6 --paid

# 查看状态
$PY $PIPE status --episode E01 --json

# 多集心跳循环（只在部署者明确允许时使用）
$PY $PIPE loop --start E01 --end E10 --paid --poll-seconds 60
```

阶段状态使用 `runtime/pipeline_state/<EP>.json`，日志使用 `runtime/pipeline_logs/<EP>/`。典型非成功状态：

- `DRY_PLANNED`：已生成付费计划但未 POST；
- `REVIEW_REQUIRED`：需要人工看图/看视频并提交结构化回答；
- `BLOCKED`：合同、资产、预算、证据或外部能力缺失；
- `ROUTE_MISSING`：仓库没有可以诚实产出该证据的实现；
- `HARD_STOP_BUDGET`：预算门拒绝继续。

## 7. 人工审核与外部依赖

机器能做的是结构、SHA、字段、媒体技术、OCR/ASR 辅助和门禁；以下不能被自动“猜通过”：

- 改编权、肖像权、发布权；
- 角色身份和源照冲突；
- Q1 关键帧是否符合入口状态；
- Q2 视频剧情/动作/身份观感；
- 整集作为观众是否连贯、是否有重复/突兀切换；
- 线主是否批准发布。

依赖 `ffmpeg/ffprobe`、CJK 字体、InsightFace/ONNX、RapidOCR、faster-whisper、OpenCC；缺失时应标记阻断而不是写 PASS。音频参考与选择性 BGM 还需要 Giggle 凭据和对应外部能力。

## 8. 当前 E59 运行实例（只作为实例，不是通用默认值）

E59 已采用独立运行时：

```text
ENGINE_ROOT=/Users/rogerwu/nalu
RUNTIME_ROOT=/Users/rogerwu/nalu_runtime_e59
WORK_ROOT=/Users/rogerwu/nalu_runtime_e59/workflow/nalu
scope=QINGSHAN-E59
```

已验证的阶段：S1、S2、S3、S4、S5。S5 复用了已审核且 SHA 一致的关键帧证据，避免重复生成。当前 S6 已完成 4.4 grouped prompt compile，仍需视频预检、真实视频 POST、收割、Q2、S7 装配和 S8 审批；因此不能把 E59 当前状态描述为“已成片”或“已发行”。

## 9. 证据与排障索引

优先查看：

- [AGENTS.md](../AGENTS.md)：部署、人工边界、失败分类和停机规则；
- [DEPLOY_NEW_MACHINE.md](../lines/nalu/docs/DEPLOY_NEW_MACHINE.md)：新机器逐步部署；
- `lines/nalu/runtime/tools/nalu_pipeline.py`：实际阶段编排和两把钱锁；
- `tools/submit_giggle_video_manifest_v2.py`：视频付费入口和事务守卫；
- `tools/production_video_submission_gate.py`：当前仓库自带视频提交门；
- `tools/provider_scope_projection.py`：E56+ provider-visible 实体作用域；
- `configs/VIDEO_MODEL_CAPABILITY_REGISTRY_v1.json`：模型能力白名单；
- `configs/ACTION_VIDEO_GENERATION_METHOD_V2.json`：动作 IR 与动作门；
- `runtime/pipeline_state/<EP>.json`：某一集的权威阶段状态；
- `runtime/reports/` 与 `preproduction/<EP>/reports/`：机器门、人工回执和费用证据。

任何报告引用的路径、SHA、模型、作用域或预算若与当前磁盘不一致，以当前运行时和最新一次状态/回执为准，并标记旧证据失效；不通过删除旧文件来“制造”通过。
