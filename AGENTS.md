# AGENTS.md — 一个新代理怎样用这条生产线把一部新作品跑起来

本文件来自一条**真实跑通过 E01–E03**的部署（nalu 线，《夜无疆》改编，2026-09-09 → 09-15），
只写实际执行过的方式。写「已支持」的都在本仓库或它的伴生运行时仓库里有代码；
做不到全自动的一律标 **MANUAL_REQUIRED**（必须人做）或 **INTEGRATION_PENDING**（缺代码承接）。
读完本文件 + README.md 应能：部署、接入素材、把一集推进到每一道付费门前，并知道在哪必须停下来问人。

## 0. 我是谁，我能做什么

- 你是**生产线编排代理**（orchestrator）：写四层剧本、跑 S1–S8、做机器审核、记账、写回执。
- 你**不是**授权来源。付费、发布、版权、肖像、身份判定的最终决定属于**线主（部署者）**。
  引擎不核验版权与肖像授权；你只记录线主的声明（`rights_basis`），不替他声明。
- 每一步可被追溯：每份 QA 记录写明审核者身份（人 / 哪个模型），禁止虚假 PASS。
  缺依赖标 `ADAPTER_REQUIRED`，没跑标 `NOT_RUN`，跑了失败标 `CAPABILITY_FAIL` / `BLOCKED`。
- 钱的规则：`qingshan.json` 的 `generation.paid_requests_enabled` 与命令行 `--paid` 是**两把锁**，
  都开才会 POST；每集上限由线主定（nalu 线 8000 积分）；同指纹任务从持久事务存档恢复、永不重发。

## 1. 部署形态（一台机器，两个仓库，三个根目录）

| 角色 | 目录（本文用变量） | 内容 | 来源 |
|---|---|---|---|
| 引擎 clone | `$ENGINE_ROOT` | 本仓库：分阶段编译器、门、提交/收割/事务、装配、QA 工具、写手 v2 | `git clone` 本仓库；nalu 线跑在分支 `nalu-line`（= main + 补丁 e08–e20，见 §6） |
| 运行时工作区 | `$RUNTIME_ROOT` | `qingshan.json`、`sources/<作品>/`、`preproduction/<EP>/`、`runtime/`（编排器、线专属工具、runbook、登记表、账本、审核、状态）、`deliverables/<EP>/` | `qingshan init --workspace $RUNTIME_ROOT`，再把伴生仓库 **nalu-production-runtime** 的 `runtime/` 放进去 |
| 引擎侧工作树（gitignored） | `$ENGINE_ROOT/workflow/nalu/<EP>/{preproduction,identity,voice,video,assembly}`、`$ENGINE_ROOT/workflow/tasks/giggle_*_transactions/<EP>/`、`$ENGINE_ROOT/workflow/production_line/EPISODE_PROMPT_BATCH_POLICY.json` | 引擎工具的既有路径约定 | 自动生成 |
| 写手状态（gitignored） | `$ENGINE_ROOT/workflow/claude_writer_agent/{SUPERVISOR_ORDERS.json,PROGRESS.json,MEMORY.md,scripts/}` | 线主指令（带序号）、进度、四层剧本 | 代理维护 |

环境与凭据：
- `$ENGINE_ROOT/.env`：`GIGGLE_API_KEY`（只在付费步骤注入：`set -a; source .env; set +a`；离线构建器**必须** `unset GIGGLE_API_KEY`）、`GIGGLE_API_BASE`。
- `QINGSHAN_VOICE_REGISTRY=$RUNTIME_ROOT/runtime/voice_registry.json`（引擎分组编译读它；漏设 → `SPEAKER_CANONICAL_VOICE_NOT_REGISTERED`）。
- `QINGSHAN_UNIT_PREFERRED_SECONDS=4,6`、`QINGSHAN_UNIT_MIN_SECONDS=4`、`QINGSHAN_UNIT_MAX_SECONDS=8`（补丁 e16；每场镜长必须能切成 4–8 s 单元）。
- 系统依赖：ffmpeg/ffprobe；Python 3.12 venv `pip install -e '.[media,asr,cloud]'` **之外**还要装 `insightface onnxruntime rapidocr-onnxruntime faster-whisper opencc`（身份余弦、OCR、ASR、繁简转换）。
- AgentCut CLI（独立仓库 backlot-os 的组件，editable 装到 `$ENGINE_ROOT/.agentcut_env`）：S4 `speech-voices/speech-generate`、S7 `bgm-generate`。**ADAPTER_REQUIRED**：没有它 S4/S7 配乐不可用。
- 编排器与线专属工具已随本仓库发布在 `lines/nalu/runtime/tools/`，路径由 `nalu_paths.py` 解析（环境变量 `NALU_ENGINE_ROOT` / `NALU_RUNTIME_ROOT` / `NALU_VENV_PYTHON`，未设则自动探测）；新机器按 `lines/nalu/docs/DEPLOY_NEW_MACHINE.md` 走。原部署实例仍从自己的运行时副本运行，切换后再删副本。

从 clone 到第一次 dry-run 的实际命令：

```bash
git clone https://github.com/rogerwu188/qingshan-short-drama-production-line.git $ENGINE_ROOT
cd $ENGINE_ROOT && git checkout nalu-line          # 或 main + 手动打 runtime/engine_patches/*.diff
python3.12 -m venv .qingshan-venv && .qingshan-venv/bin/pip install -e '.[media,asr,cloud]' insightface onnxruntime rapidocr-onnxruntime faster-whisper opencc
.qingshan-venv/bin/qingshan init --workspace $RUNTIME_ROOT
.qingshan-venv/bin/qingshan doctor --profile all --config $RUNTIME_ROOT/qingshan.json
.qingshan-venv/bin/qingshan test
git clone https://github.com/rogerwu188/nalu-production-runtime.git /tmp/npr && cp -R /tmp/npr/runtime $RUNTIME_ROOT/runtime
# 手工：.env、qingshan.json（title / paid_requests_enabled=false / 只留 seedance-2.0-pro）、runtime/voice_registry.json（空表）、runtime/voice_catalog.json
.qingshan-venv/bin/python $RUNTIME_ROOT/runtime/tools/nalu_pipeline.py run --episode E01     # 无 --paid：S1/S2 免费执行，S3 起 DRY_PLANNED 并打印本应执行的付费命令
```

## 2. 素材进来先做什么（四类素材 → canonical 前的落位）

用户只给：短剧要求与集数预算 / 小说网址或剧本文件 / 图片（人物照、场景、历史地图）/ 其它素材。
**代理不从网络抓取小说正文**；网址只用于登记出处，正文由用户以文件提供。

| 素材 | 最低要求 | 落位（`$RUNTIME_ROOT` 相对） | 做法 | 状态 |
|---|---|---|---|---|
| 短剧要求 + 集数预算 | 画风、节奏口径、每集积分上限、模型、哪些事要停下来问 | `$ENGINE_ROOT/workflow/claude_writer_agent/SUPERVISOR_ORDERS.json`（带 `seq`，每条含 body + conditions） | 代理把用户原话记成一条有序号的指令；之后每个付费/审核记录都引用 seq | 已验证（nalu seq=1…14） |
| 小说/剧本 | 一个文本文件；编码可以是 GB18030/UTF-8、繁/简都行 | `sources/<作品>/{zh-Hant,zh-CN}/chNNNN.md` + `SOURCE_INDEX.json`（origin sha、编码、授权声明） | `python3 tools/intake_source_text.py --input <file> --work <名> --out $RUNTIME_ROOT/sources`（本仓库，从 nalu 的一次性脚本泛化：按章号切分、重复标题取最长、去广告行、可选繁→简） | REFERENCE_IMPLEMENTATION（泛化版未在生产跑过；nalu 用的是作品专用脚本） |
| 章→集映射 | 一集一章（可改），只登记**写手实读并列出节拍表**的章 | `runtime/episode_source_map_<work>_v1.json`（`derivation=OBSERVED`） | 禁止算术映射 ch N → E N | 已验证 |
| 人物照 | 每角色一张正脸；肖像授权由线主线下处理并在 map 里声明 | `runtime/character_sources/<CHAR-ID>__SOURCE_V2_TANG.png`（生产用）；原图与裁切 `runtime/character_sources_hold/`（永不入库） | `python3 tools/intake_character_sources.py --folder <照片目录> --map $RUNTIME_ROOT/runtime/character_source_map.json`：登记 sha、角色绑定、用途、授权备注；换装/年轻化要付费 i2i（nalu 用 `generate_period_look.py`，作品专用） | 登记脚本 REFERENCE_IMPLEMENTATION；换装 MANUAL_REQUIRED + 付费 |
| 场景/历史地图图片 | 可选 | `runtime/reference_images/`（只作提示词参考） | nalu 没有外部地图：E01 手写 `preproduction/E01/global_space_map.json`，之后每集 `extend_global_space_map.py` 按合同新地点 + 作者命名的 `preproduction/<EP>/new_location_place_spec.json` 自动布局 | 地图素材→空间图 **INTEGRATION_PENDING**（无自动接入） |
| 品牌/片尾等 | 9:16 PNG | `brand/` | 手放；装配时追加 3 s 片尾 | MANUAL_REQUIRED |
| 音色 | 无素材：从提供者目录挑 | `runtime/voice_catalog.json`（实体→voice_id）、`runtime/voice_registry.json` | `agentcut speech-voices` 列表 → 代理按角色气质挑，写目录；S4 才付费 | MANUAL_REQUIRED（挑选） |

素材进入 canonical 的边界：**写手层的 narrative 是手写的**（代理逐拍读源章、逐字引台词），素材脚本只把文件放到位并登记来源与 sha。

## 3. 逐集流程（写手 → S1…S8 → S7-SYNC）

| 阶段 | 前置 | 产出 | 门（免费） | 人工点 | 费用 | 停下来问人 |
|---|---|---|---|---|---|---|
| 写手 | 源章 zh-CN、上一集合同末镜 `completion_state`、SUPERVISOR_ORDERS | `scripts/<EP>_NARRATIVE_CANONICAL_v1.md`（手写）；`build_e0N_layers.py` → `DIRECTING_SCRIPT`、`GENERATION_CONTRACT`、`manifest` | 构建器自检：单镜 3–7 s、无对白 ≤5 s 且机位必动、R7/R8 台词时长、单场 ≤22 s、道具名出现在 action 就必须在 entry/exit、远景之后露脸镜声明 `identity_reanchor`、key_quote 逐字在源章、每场能切成 4–8 s 单元 | 写 narrative 与镜头表 | 0 | 需改剧本**文字**（非排版）时停 |
| S1 | 四层文件 | gate10、实体合同、静态设计门报告 | `writer_scene_source_declaration_gate --warn-is-fail`；`character_entity_contract`（非人物主体 id 留空、别名跨角色唯一）；`static_design_gate` R1–R8（E03 起阻断） | 无 | 0 | — |
| S2 | 合同+manifest+`preproduction/<EP>/{asset_requirements_overlay,new_location_place_spec,view_reference_policy}.json` | D-10：空间图扩展 + 需求文件 + 提示词；引擎编辑清单/分组/锚点计划/关键帧清单 | 布局门、分组门、锚点计数门 | 新地点的作者命名（place spec）、覆盖文件里的服装/年龄/音色简述 | 0 | — |
| S3 | 需求文件、角色源照、`runtime/asset_library.json`（跨集复用：LOCKED + sha 匹配即跳过） | 身份牌三视图 + 道具/构筑物卡 | precheck、预算守卫、身份审（缩略总表 + InsightFace 余弦）、非板类锁、`initial_asset_library gate` | **MANUAL_REQUIRED 身份审**：代理实际看图，`review_fill/e0N_fill_identity_answers.py` 填答 | 11/张 | 余弦 <0.30 的主角、源照与剧本年龄冲突 → 问线主 |
| S4 | `voice/speech_task_payloads.json`（由 voice_catalog 生成） | 参考音 + registry 行 | ffprobe 48k mono、上传回执 | 挑音色 | 2/角色 | — |
| 整批提示词门 | 关键帧提示词 + 规划编译（`compile_grouped_seedance_manifest.py --planning-only --planned-prompt-dir`） | `EPISODE_PROMPT_BATCH_POLICY.json` 登记 + 每行回执 | `prompt_batch_register` sha 绑定 + `prompt_batch_qa digest` 确定性检查 | **MANUAL_REQUIRED**：通读摘要写逐行答案 → `receipts` → 再 `register` | 0 | 确定性检查 FAIL 且非误报时改合同 |
| S5 | 关键帧清单 | `preproduction/keyframes/<shot>-keyframe-v1.png` | entry_state 门、预算守卫、Q1（RapidOCR + 身份余弦 + 人工）、起始帧证据 | **MANUAL_REQUIRED Q1**：缩略总表看图填答；REJECT → 改镜头文字 → 重建 → 停放旧提示词/旧图 → S5 干跑 → 规划编译 → 重登记 → S5 付费 | 11/张 | 同镜第 2 次创意重做失败 |
| S6 | 关键帧 + 上一单元真实尾帧（波次） | 单元 mp4 | 波次循环脚本、reroll 守卫、post-gen QA（技术 12 项 + ASR + 剧情 5 项）、Q2（5 帧 OCR/身份 + 人工）、缺陷容忍门 | **MANUAL_REQUIRED**：post-gen 剧情审、Q2 审 | 20/s | 重做超守卫上限、集级缺陷预算超限 |
| S7 | 全部单元 ADMITTED_FOR_ASSEMBLY | `deliverables/<EP>/<EP>_final_9x16.mp4`（烧录字幕、3 s 片尾、-16 LUFS；选择性配乐：plan → generate → reconcile → qa → mix，solo stem 归档） | `final_qa_evidence_bundle`（两键无生产者 → N/A）；配乐账单按提交窗隔离（K032） | 无 | 配乐 8/段 | 首次配乐付费；配乐窗口标签是否被发布门接受（线主决定） |
| S8 | 成片 | `CHECKPOINT.md` + 审批标志 | — | **线主看片** | 0 | 总是停 |
| S7-SYNC | S8 通过 | 仓库：代码泛化回灌、K 号经验、README/AGENTS 改到与生产一致、新 tag | `knowledge_registry --validate`、`run_portable_ci.py`、`deployment_code_integrity.py` | 改动清单给线主确认后 push | 0 | push/合并前 |

## 4. 必须停下来问人的点（不问就是越权）

1. **付费**：翻 `paid_requests_enabled`、第一次 `--paid`、每集上限、超守卫的重做、任何新的付费种类（首次配乐、换装 i2i）。
2. **发布/上传**：本线没有发布代码路径；任何平台上传都要线主另行授权（`release-preflight` 是失败关闭门，不是许可）。
3. **版权/肖像**：源作品改编权、真人照片肖像权由线主声明；引擎不核验，代理只登记 `rights_basis` 原话与日期。
4. **身份判定**：主角源照与剧本年龄/形象冲突、余弦低于失败线（0.30）、换源照、年轻化——任一都问。
5. **人工审核**：身份审 / 整批提示词审 / Q1 / post-gen 剧情审 / Q2 由代理**实际看图**后填答，记录审核者身份；不能看图就不填。
6. **改剧本文字**：合同/导演稿的生产文字（机位、起止态措辞）代理可改；narrative 的故事与对白文字要问（排版拆行属可自行处理但必须申报）。
7. **同镜第 2 次创意重做失败**、**集级缺陷预算超限**、**预算投影超上限**：停，汇报。
8. **配乐账单只能按提交窗隔离**（提供者不给音乐任务精确的逐任务 id）：证据打 window-isolated 标签；发布门是否接受该标签是线主的政策决定，代理不得自行改门。

## 5. 失败怎么归类、什么时候重试、什么时候停

| 现象 | 归类 | 动作 |
|---|---|---|
| POST 无任务标识、HTTP 断流 | 事务 `RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION` | **先对账**（账单窗口 Pay 行数 == 已知 task 数）→ `NOT_CHARGED_RETRYABLE` 才可重提；绝不删事务文件 |
| 提供者明确拒单（code 500 payment failed 等） | `NOT_CHARGED_RETRYABLE`（补丁 e18） | 直接重跑同阶段，指纹相同不重发已绑定行 |
| 提交前门拦下（`WHOLE_BATCH_PROMPT_QA_REQUIRED…`、precheck） | `NOT_CHARGED_NO_INTENT_RECORDED`（补丁 e17） | 修门的输入（多数是回执 sha 与文件不一致 → 重做 digest/receipts/register）再跑 |
| 403 invalid api key | 凭据 | 停，问线主换 key；恢复后先对账再重提 |
| Q1/Q2 人工 REJECT | 创意重做 | 改镜头文字（不改故事）→ 重建 → 停放旧提示词/旧图/旧收割副本 → 重登记 → 付费重做；同镜第 2 次失败停 |
| 身份余弦 0.30–0.45 `BOUNDARY_REQUIRES_HUMAN` | 引擎人工窗（15 min） | 代理看图给出观察；引擎超时后 ≥0.375 尽力准入、<0.375 换覆盖（=重做）；Q1 构建器已把超时时钟跨轮携带 |
| 黑帧/静止/字幕烧录 | post-gen 技术 QA | 剧本不得写全黑；儿童对白特写用双人同框；重做受守卫 |
| 相邻单元方向冲突、单元 4–8 s 不可分 | 构建器自检 | 改镜长/机位，不上生产 |
| API/中继断流（代理自身） | 会话 | 心跳定时任务每 17 min 检查并从中断处续跑；长输出分段写 |
| 重做后 `WHOLE_BATCH_PROMPT_QA_REQUIRED:QA_INPUT_MISMATCH` | 提示词批次 sha 漂移 | 关键帧提示词每次 `build_keyframe_manifest` 都重写；改镜后**第一次付费跑**前后字节会变一次 → 用当前文件重做 digest/receipts/register，再跑；不重发已绑定行（提交前失败不扣费） |
| Q1 身份 `FACE_COUNT_NOT_ONE` | 裁切含第二张脸（动物/旁人） | Q1 构建器逐级收窄裁切边距（0.7→0.2）直到恰好一张脸；阈值不变 |
| 重做后旧图仍在 `keyframes/` | 物化 `ALREADY_PRESENT` | 停放旧 png + 旧收割副本（含 `_raw` json），再跑 S5 |
| 付费子进程报 `GIGGLE_API_KEY not set` | 钱锁剥掉了密钥（子进程没带付费标志） | 子进程以 paid 标志启动；无 POST、无事务文件，不需对账（K032） |
| HTTP 403 `error code: 1010`（任务创建前） | Cloudflare 拒绝裸 urllib User-Agent → `NOT_CHARGED_PRE_TASK_HTTP_403` | 发浏览器 User-Agent；用免费 GET 任务查询测鉴权，绝不用 POST 探测；账单窗口为空即为证据（K030/K032） |
| 对账窗口里出现不属于本线的行（共享账号） | 外来账单 | 隔离到 `_foreign_account_activity/`，永不入账，重跑对账（K029） |
| 音乐扣费 project id 为空，精确对账 INCOMPLETE | 只能按任务自身半开提交窗 [intent, response) 隔离 | `tools/credit_window_isolation.py`；标签 `PASS_WINDOW_ISOLATED_LEDGER_NET`（非 exact）；发布门接受与否问线主（K032） |
| 视频身份一帧侧脸/背影拖垮整单元（WORST_FRAME） | 姿态案例，不是边界案例 | 审核者姿态豁免，理由写帧号与两个分数；补交要签发新审核请求（K026） |
| 成片/单元 OCR 命中烧录字幕 | 客观、不可仲裁 | 动作文字前置禁文字条款后重做；重做后重登记提示词批次（K027/K031） |
| 同一批 action_role 项在 PASS 后被循环反复重发 | 回执写入器阻塞（生物发起者 id 为空） | 读 s6_are_write_receipts 日志；词表含资产库道具/场景 id，Expectations 加载生成合同（K035） |
| 对白门『无普通话语音』或『尾音截断』但耳听台词完整 | whisper 引导解码退化/幻觉时间轴 | runner 无引导复核 + 在复核片段上重测尾音（K036/K037）；末 120 ms 仍在语音电平或无对白镜有真实说话声 → 客观失败，制作文本重做（K038） |
| Q2 物化 PARTIAL_0_OF_N，每单元 DEFECT-TIER 失败 | 全集开场 10 s/结尾 5 s 内有 P2 | 该单元重做，不是备注；重做后签发新 video_q2 请求整批重填（K039） |
| 视频 Q2 身份低分/OCR 拉丁字母 P0 | 裁切框落在旁人脸上/纹理噪声 | 先看 face_crops 再写豁免（帧号+分数）；`NOISE:<文本>` 申报（K040）；提示词链先登记再摘要（K041） |
| S1 `SCRIPT_STRUCTURE_CONTRACT_FAIL`（HOOK_MISSING / DIALOGUE_STARVATION_* / BEAT_TYPE_UNDECLARED / ANTAGONIST_* / PROP_NO_SOURCE / ENTITY_NO_SETUP_OR_PAYOFF / MODERN_LEXICON） | 合同本身不成立（K042–K045、K051、K052） | 改剧本层：前 5 s 钩子、台词密度、beat type+outcome、对抗方动机、道具来源/回顾镜、实体铺垫或回收、词表；不改阈值，不进生成 |
| S1 `CONTINUITY_STATE_CONTRACT_FAIL`（LIFE_STATE_UNDECLARED / DEAD_THEN_ALIVE / GROUP_COUNT_DRIFT / CREATURE_* / AMBUSH_*） | 状态机/生物卡/伏击空间未声明（K046、K048） | 每镜 cast[].life_state、group_counts、creature_card、ambush_contracts；观感由 Q2 必答问题把关 |
| S4 `VOICE_CAST_REQUIRES_HUMAN`（同场角色参考音音区重叠 >50%） | 参考音本身分不开（K049） | 线主决定：换参考音（重生成 2 cr/角色）或接受；不能静默通过 |
| S7 `FINAL_CUT_AUDIENCE_DETECTORS_FAIL`（hook_present / dialogue_coverage / silence_gap_max / voice_distinctness / emotion_dynamics / lexicon_violation / mascot_in_story / loudness） | 成片观众级检测（K042、K049–K052） | 按检测器修：结构类回剧本层重做，音色类换参考音并重做该单元，词表类改台词/字幕，响度类重跑发布响度；`UNVERIFIED/NOT_IMPLEMENTED` 项进 receipt，不算 PASS |
| S3 `ASSET_LIBRARY_GATE_FAIL` 配音 `upload_receipt_asset_id_matches_registry` | 重铸配音多集有回执，锁库器取了最旧集（K055） | 新配音先跑 S4 再回 S3；锁库按注册表 remote_asset_id 选回执；账本检查不与流水线并发 |
| 视频提交提供者拒单（code 500 payment failed、无任务标识）却整批 `CHARGE_STATE_UNRESOLVED_BATCH` | 账单 Pay 行数 == 已知 task 数时是 e24 漏判（K054） | 事务离线重分类为 NOT_CHARGED_RETRYABLE，重跑同阶段只 POST 该单元；BLOCKED 运行的账单摘要用 `giggle_credit_statements.py` 按提交窗重建后再跑下一波 |
| 说话生物要过身份锁 | 生物没有人脸（K053） | 角色登记 identity_source.mode=VOICE_ONLY_NO_PLATE：只建 voices 行，画面为道具生物卡，镜表 presence OFFSCREEN_VOICE_ONLY、lip_owner 空 |
| Q1 坐/站跳变、独处镜漏人、生物独镜『道具：无/空镜』、生成后人物突然入画 | 镜文字状态泄漏（K056） | 逐镜写姿态；场景光线不提人物；道具用注册表名；start_framing 含在场人物；改文字→停放→重登记→受守卫重做 |
| 加了姿态标记身份仍 FAIL；Q2 P2 被拒收 | 标记只随新审核请求生效；P2 需 1-based shot_index（K057） | 停放旧 request/submitted 重新签发；豁免写帧号与分数、先看 face_crops；OCR 噪声 `NOISE:<文本>` |
| S7 parity 报 SHOT_STRETCHED / STATIC_HOLD_IN_DIALOGUE / BLANK_SCREEN | seq=27 §六 诊断（K058），不阻断 | 写入 CHECKPOINT 给线主审片；阈值与是否返修由线主裁定；不新增 gate_id |
| 视频/关键帧主角脸走样，而身份牌互比余弦很高 | 身份信号沿链被稀释（K059）：牌没对原照测、关键帧脸参考只有小脸全身牌、视频单元没带头像牌、Q1 给 3/4 脸豁免 | 锁定时逐牌对源图 ≥0.45；关键帧头像牌打头（非角色参考 ≤5）；每单元追加在场角色头像牌；Q1 只豁免背影/仅手/出画/远小 |

## 6. 现在做不到全自动的步骤（如实）

人物参考与外观验收补充规则：阅读 `docs/knowledge/IDENTITY_REFERENCE_POSE_AND_ACCEPTANCE.md`。新关键帧采用人物参考优先、实际数组同步重编号、已有批准角度图补充与缺口记录；空间解析顺序不等于参考图传输顺序。侧脸低分不得单独触发付费重做，用户明确接受的图保持原 SHA 和原测量记录。

- **MANUAL_REQUIRED**：narrative 手写；五类人工审核看图填答；音色挑选；新地点命名（place spec）；覆盖文件（服装/年龄/音色简述）；品牌片尾；每集 Roger 看片；改动清单确认后 push。
- **INTEGRATION_PENDING**：整批提示词门并入 S5（现为手动 5 步）；地图素材→空间图；D-9/D-12 两个最终 QA 证据键无生产者；引擎 `pose_transition_anchor_gate` 需要的结果锚点关键帧角色（现靠措辞避开）；引擎补丁 e08–e21 已在 `integration/e03-sync` 分支（待合 main），e22 在 backlot-os；`bgm_authenticity_gate` 对窗口隔离账单标签的接受（线主决定，K032）；产品化的素材接入 CLI 子命令；原部署实例切换到仓库内 `lines/nalu` 副本。
- **ADAPTER_REQUIRED**：AgentCut（语音、配乐）；InsightFace/RapidOCR/faster-whisper 运行时；ffmpeg。
- **需付费才能验证**：S3 起的一切；dry-run 只能走到每个付费门前（DRY_PLANNED）。

## 7. 起新集 checklist（E0N，从 E0N-1 克隆）

1. 读源章、写 `E0N_NARRATIVE_CANONICAL_v1.md`（头部逐字引上一集 canonical 末段 5 行；声明观众已知不复证；选择性配乐节点）。
2. `cp build_e0N-1_layers.py build_e0N_layers.py`，重写数据块（SHOTS/SCENES/CAMERA_PLANS/TRANSITION_NOTES/BEATS/PROPS/SETS/WARDROBE/CHARACTER_ROWS/BGM_CUES），跑通自检。
3. 写 `preproduction/E0N/asset_requirements_overlay.json`、`new_location_place_spec.json`、`view_reference_policy.json`；新说话角色先进 `voice_catalog.json`；复用角色靠 `asset_library.json` 的 LOCKED 行（换代重做时把状态改成 `SUPERSEDED_…_PENDING_REGENERATION` 并保留 `superseded_locks`）。
4. `run --episode E0N --until S3`（无 --paid）→ 看 DRY_PLANNED 的计划与费用；`sed s/E0N-1/E0N/g` 生成审核填答脚本与 S6 循环脚本。
5. 线主授权后：S3 付费 → 身份审 → S4 → S5 干跑 → 规划编译 → 登记 → 摘要 → 答案 → 回执 → 登记 → S5 付费 → Q1 → S6 波次 → post-gen/Q2 → S7 → S8 → S7-SYNC。
6. 每次改了合同/提示词：停放旧的空间图/提示词（write-if-missing），`--force` 重跑 S1–S3，重登记提示词批次。

## 8. 收工：S7-SYNC（线主常设规则）

集收工 = 生产收工 + 仓库收工。把本集新增/修改的工具以通用形态（参数化路径、无集次实值）回灌本仓库；每个坑写成 K 号条目进 `configs/ENGINEERING_KNOWLEDGE_V1.json` 与 `docs/knowledge/ENGINEERING_KNOWLEDGE_BASE.md`（状态如实：REFERENCE_IMPLEMENTATION / GUIDANCE_ONLY / INTEGRATION_PENDING）；README/AGENTS 改到与生产一致；`python3 tools/knowledge_registry.py --validate`、`tools/run_portable_ci.py`、`tools/deployment_code_integrity.py` PASS 后合并 main 并打 tag `vYYYY.MM.DD-…`。不上传媒体、canonical、事务、回执、日志、凭据、绝对路径、作品正文。

## 9. 本文件的验证记录（2026-09-15，只用仓库内容 + 本文件，dry-run，不付费）

1. 隔离目录 clone main（edafc51）→ `qingshan init --workspace <ws>` PASS → `qingshan doctor --profile core` PASS → `python3 tools/run_portable_ci.py` PASS（376 tests）→ `tools/deployment_code_integrity.py` PASS。
2. `tools/intake_source_text.py`、`tools/intake_character_sources.py` 在合成 fixture 上 dry-run/写入 PASS（未在真实作品上跑）。
3. **第一次卡住**：走到「S1」需要四层剧本文件 + 逐集编排器 `nalu_pipeline.py`；编排器与线专属工具现已随本仓库发布在 `lines/nalu/runtime/tools/`（路径参数化，`tools/tests/test_nalu_runtime_port.py` 离线验证 bootstrap + status 可跑）；剩下的卡点是剧本四层本身必须手写（MANUAL_REQUIRED），本文件如实标注。
4. 真实边界：S3 起必须凭据 + 付费；每集有 5 处人工看图审核；发布无代码路径。

## 10. 尾贴广告（可选，按集 opt-in；codex_docs/ROGER-20260925-AD-TAIL-INTEGRATION.md）

- **默认关闭**：`manifest.ad_slot` 不存在 = 本集无广告，`final_9x16.mp4` 逐字节不受影响。写手层四层文件封缄之后、S1 之前，编排器写 `ads/prompts/<EP>_AD_PROMPT.json` 问一次「本集是否植入尾贴广告？」，60 秒墙钟轮询 `ads/prompts/<EP>_AD_ANSWER.json`（文件问答，不用 `input()`，避免无人值守 heartbeat 挂死）；超时/未答默认走 `ads/policy.json` 的 `default`（当前策略：默认植入 demo 广告 `INBOX:giggle_tail5s`，除非当集显式答 `NONE` 或指定别的 sku/brief——Roger 2026-09-25/26 明确要求）。答案写入 `manifest.ad_slot` **仅一次**（该文件被 S2 等阶段指纹绑定，二次改写会使后续阶段的缓存失效）；S7 开始前若晚到答案会被采纳（记 state 不改 manifest），S7 已开始则记入下一集。
- **两种输入方式，同一个槽**：方式 A `ads/inbox/<sku>.mp4`（现成成片，允许已自带「广告」角标/CTA字幕）；方式 B `ads/briefs/<sku>.json`（url/idea/assets/brand_docs/cta，走 `tools/adforge_adapter.py` 调外部 AdForge，`ADFORGE_ROOT` 未配置即 `ADAPTER_REQUIRED`，本线照常出无广告成片）。两种都进 `tools/ad_tail_package.py`（唯一技术门：格式/时长/响度/角标/OCR/口播字数与CTA不念，全部 fail-closed），再进 `tools/ad_tail_insert.py` 拼进 `content | ad | endcard`，产物 `<EP>_final_9x16_AD.mp4` 与原片分开存放，绝不覆盖。
- **不走剧集创意门**：广告只过技术门，不算镜头分母、不占缺陷预算、不进 FS-1；六项诊断（AD_TAIL_FORMAT/DURATION/LOUDNESS/LABEL_PRESENT/SHA_BOUND/OCR_CLEAN）挂在既有 `FINAL-AUDIT-COMPLETENESS` 之下，任一不过就是本集没有广告版，正片版完全不受影响。
- **独立账本**：`ads/transactions/` 与集内制作积分账本分开；配乐/视频以外的这笔新付费类别（首次投放广告）已按 seq=... 记入私有 SUPERVISOR_ORDERS。
- Mode B 顺序硬规则（demo 踩过的坑）：先出旁白测真实时长，再按时长定镜长喂给视频生成；CTA 网址只上字幕不念；spoken_chars 按 CJK 字符数，不按原始字符串长度。
- MANUAL_REQUIRED：brief 撰写（idea/assets/brand_docs/cta）、AdForge `.env` 凭据（线主手填，代理不写密钥）。ADAPTER_REQUIRED：`~/adforge` 未部署或缺三处本地补丁（`.env` 读取、`project.json` 规格读取、`verify_media` 接受期望时长/比例）时 Mode B 不可用，Mode A 不受影响。

