# 交付报告：多设备 AI 导演评估与群体学习系统

需求：《给Claude_多设备AI导演评估与群体学习系统实施需求》v1.0（Roger / Codex，2026-10-28）。
交付日期：2026-10-29。分支 `feat/collective-director-learning`，基线 `1221d64`（= 需求审阅基线 = `origin/main`）。

## 0. 状态一句话

**LOCAL_INTEGRATION_VERIFIED**。代码、测试、真实入口接线、迁移、部署说明、端到端演示全部在本机隔离环境完成并通过；**CLOUD_DEPLOYED / PILOT_OBSERVED / ROLLOUT_VERIFIED 均未达到**，阻塞项只有线主决策（`AUTHORIZATIONS_REQUIRED.md`）。**对象存储已定并接入**（2026-10-29）：自建 S3 网关的预检（PUT 1 KB / GET 比对 / 公网 GET / DELETE / 确认已删）对 `nalu` 与 `collective` 两个前缀在本机真实通过；密钥只在环境变量里。在制剧集（E11 已批、E12 在 S6）未被触碰：工作在独立 worktree，所有新接线在没有知识锁的运行上字节不变。

## 1. 提交

| SHA | 阶段 | 内容 |
|---|---|---|
| `89eb883` | A | 契约、设备端 SQLite 存储 + outbox、DIRECTOR_SCORE_V1、成片评审接入、JSON schema、接线清单 |
| `bd95d4c` | B | 云端服务、HTTP API + OpenAPI、同步客户端、负载基线、授权清单 |
| `dc21e1d` | C | 知识包签名/缓存/运行锁、技能包校验、选择、采用回执、影响范围、真实入口接线 |
| `9b6128b` | — | 测试登记、运维文档 |
| `1543a11` | D | 跨设备端到端演示 + 两个由演示暴露的集成修复 |
| `be8703c` | — | 部署完整性清单重建 |
| `96c1543` | — | 交付报告 |
| `6960b8d` | E | 对象存储：`object_store.py` 预检 / 线前缀命名 / 仅标准 API / 公开读防泄露门 / 包镜像 / 证据上传，22 个测试，运维文档 §3a |

48 个文件，+13,826 / −39 行。

## 2. 交付清单对照（需求 §15）

| # | 要求 | 位置 | 状态 |
|---|---|---|---|
| 1 | 基线 SHA、实际入口图、复用清单、设计决策 | `WIRING_INVENTORY.md`（含 file:line）、`BUNDLES_ADOPTION_AND_ENTRY_WIRING.md` | 完成 |
| 2 | schema、迁移、权限模型、OpenAPI | `configs/schemas/collective_learning/*.schema.json`、`tools/collective_learning/migrations/0001_init.sql`、`service.py`（四角色）、`docs/collective_learning/openapi.json` | 完成 |
| 3 | 设备客户端、云端服务、管理界面、隔离演示环境 | `device_store.py` `sync_client.py` `bundles.py`；`service.py` `http_api.py`（`/admin` 只读追溯页）；`tools/collective_learning_demo.py` | 完成（管理界面为只读追溯页，无登录流） |
| 4 | 评分标准、人读报告、结构化评估、下一集计划 | `configs/DIRECTOR_SCORE_V1.json`、`director_score.py`（接入 `final_audience_review.py submit` 的可选 `director_evaluation` 块） | 完成 |
| 5 | 知识选择、版本锁定、采用回执、影响范围复查、发布回滚 | `selection.py` `bundles.lock_run/verify_lock_for_send` `adoption.py` `impact.py`；`service.release/revoke_bundle` | 完成 |
| 6 | 单元/集成/并发/故障注入/安全/兼容/真实入口回归 | 9 个新测试模块 + 4 个扩展的既有模块，全部登记进 `PORTABLE_CORE_MANIFEST.json` | 完成 |
| 7 | 可复现跨设备演示 + 无付费 POST 证明 | `E2E_DEMO.md`（真实命令与真实 transcript 摘要；`paid_post_count: 0`，拦截 `socket.connect` 非回环 + `giggle_api_client._request`） | 完成（本地） |
| 8 | 部署、配置、备份恢复、凭证轮换、升级回滚、运维 | `DEPLOYMENT_OPERATIONS.md` | 完成（文档 + 本地验证；云端未执行） |
| 9 | 费用测量方法与预算需求 | `DEPLOYMENT_OPERATIONS.md §7`、`LOADTEST_BASELINE.json`、`AUTHORIZATIONS_REQUIRED.md §B` | 完成 |
| 10 | 提交 SHA、测试登记、完整性清单、未完成项 | 本文件 §1、§3、§6 | 完成 |

三项仓库验证（2026-10-29，worktree HEAD `be8703c`）：
- `tools/run_portable_ci.py`：见 §3 末行。
- `tools/deployment_code_integrity.py`：PASS，2,261 文件，missing=[]。
- `tools/knowledge_registry.py --validate`：PASS，127 条规则。

## 3. 测试矩阵（需求 §13）

| 编号 | 覆盖测试 | 结果 |
|---|---|---|
| T01 | `test_collective_device_store.MultiProcessTest`（6 进程 × 40，SQLite 240/240；对照旧 JSONL 损坏、210/240 写入抛异常） | PASS |
| T02 | `CrashConsistencyTest`：事实与 outbox 之间模拟崩溃 → 两者皆回滚；子进程写入后新对象重开 | PASS |
| T03 | 单测 20 客户端 × 200；负载 100 × 1000（`LOADTEST_BASELINE.json`）：100,000 唯一行 | PASS |
| T04 | 20 % 重复投递：唯一数不变，`delivery_log` 可追踪 20,000 次重复 | PASS |
| OS2 | `test_s3ctl`（9）：统一命令行封装（config/preflight/ls/put/sync/get/head/url/mv/rm），预检门、媒体与敏感内容拒绝、跨线移动拒绝、递归删除需确认；真实网关完整序列通过 | PASS |
| OS | `test_collective_object_store`（22）：键命名、凭证只来自环境、预检四步与回执过期、媒体/敏感内容拒绝、copy+delete、源码不含不支持 API、包镜像失败不影响上传、文档无密钥 | PASS |
| T05 | 服务端提交后丢响应 → 重传 ack=DUPLICATE，不重复计数 | PASS |
| T06 | 同 ID 不同内容 → CONFLICT 审计，原事实保留；乱序修订保留 | PASS |
| T07 | 批次夹一条坏数据 → 其余确认，坏项双端隔离 | PASS |
| T08 | 云端停机 → 子进程照常记录 → 重启同一库 → 精确一次送达 | PASS |
| T09 | 伪造设备/越线/跨租户 → 拒绝 + 审计；设备凭证不能发布 | PASS |
| T10 | 恶意经验文本惰性存储；敏感字段出不了设备；API 不回显 token；admin HTML 转义 | PASS |
| T11 | 篡改包/未知密钥 → 拒绝，缓存不污染（设备端 + 服务端） | PASS |
| T12 | H3 规则对 SD2 能力不解析（演示中反向：SD2 规则对 H3 设备 OUT_OF_SCOPE） | PASS |
| T13 | 锁定后同路径替换 → `verify_lock_for_send` 拒绝新 POST，旧绑定不变 | PASS |
| T14 | 撤销 → 新 run 回退，锁定 run 仍可校验，历史可查 | PASS |
| T15 | READ/EXPORTED/SELECTED 永不显示为 APPLIED（`status_for_rule`） | PASS |
| T16 | 真实 SD2 严格编译 + 真实 H3 渲染调用点；发送内容 digest == 校验 digest；0 POST | PASS（H3 渲染调用点测试对编译器做了确定性桩，与既有 `H3FinalRenderReceiptTests` 同法） |
| T17 | `prior_bound` / `live_bound_elsewhere` 在知识检查前返回，不重 POST | PASS |
| T18 | 显式 `impact_scope` 只让免费检查过期；付费步骤列为 `paid_never_resubmitted` | PASS |
| T19 | 邻接只读声明的过渡合同与真实首末镜 | PASS |
| T20 | 仅接触表 → PARTIAL，总分与声音/剪辑/节奏 UNASSESSED | PASS |
| T21 | 换成片 sha / 评分版本 → 新评估 id，旧保留，`compare` 拒绝 | PASS |
| T22 | `source_event_id` 链 + 克隆重放 + 重复投递 → 1 个独立来源 | PASS |
| T23 | 冲突/过量建议按范围与上限处理；台词字节相同 | PASS |
| T24 | 云端不可达不阻塞记录；慢单元不阻塞其它单元（线程计时） | PASS |
| T25 | 声称付费重做的规则 → 预算、授权、重试数不变，POST=0 | PASS |
| T26 | 删证据 → EVIDENCE_UNAVAILABLE、失去推广资格；重开库后一致 | PASS |
| T27 | `test_collective_e2e_demo`（10） | PASS |

历史回归：严重半脸、无动机重复摇镜、对镜头讲话、错误人物、对白缺失、动作重复起步 —— 每类各带一个合理创作反例，反例不被判错（`test_collective_selection_adoption`）。

新测试模块：`test_collective_device_store`(18) `test_collective_director_score`(17) `test_collective_service`(17) `test_collective_sync_client`(8) `test_collective_bundles`(19) `test_collective_selection_adoption`(26) `test_collective_real_entry_wiring`(15) `test_collective_e2e_demo`(10)；扩展：`test_nalu_final_audience_review`(+4)、`test_knowledge_consumption_ledger`、`test_knowledge_sync_core`、`test_line_upgrade_gate`（首次登记进正式集合）。

负载基线（不是性能承诺）：Apple M1 / 8 GB / SQLite 3.53；100 × 1000、20 % 重复、批 100：55.9 s，1,790 唯一事件/s，P50 0.83 s，P95 12.6 s，P99 20.0 s，错误 0，服务端峰值 RSS ≈ 654 MB，库 130 MB。尾延迟来自 SQLite 单写者 + 每批 fsync + 每线程独立连接；换 Postgres 或连接池后需重测。

**全量 portable CI（148 个登记模块）**：`PASS`，1,645 tests OK (skipped=11)，268.3 s，failures=[]（2026-10-29，HEAD `6960b8d` 加本报告）。

## 4. 现有模块对应关系（需求 §5「允许映射现有等价结构」）

| 需求契约 | 现有等价 | 处理 |
|---|---|---|
| ObservationEvent | `knowledge_event_log.record_event` 的行 | 新契约是超集；`device_store.export_jsonl` 生成旧格式视图，旧 `events()/unattributed()` 可照常读；旧 JSONL 不再是权威 |
| AttributionReview | `attribute_event` / `mark_inconclusive` 的 `attribution` 字段 | 改为不可变修订链（`revisions` 表）；导出视图取最新修订 |
| KnowledgeCandidate | `knowledge_sync_core` 的候选行（K 号） | 并存：K 注册表仍由 S8 同步写；新候选经云端状态机；`impact_scope` 字段两边通用 |
| AdoptionReceipt | `knowledge_consumption_ledger` APPLIED/VERIFIED | 账本保留；`status_for_rule` 合并读取采用回执；SELECTED/OUTCOME_OBSERVED 为新增态 |
| 评估记录 | `final_audience_review` 的报告/事件账本 | 不替换：`director_evaluation` 作为可选块挂在同一提交流程上，不影响既有门 |
| 运行快照 | `line_upgrade_gate` preflight 回执 | 回执新增 `collective` 段 + 运行锁文件 |

## 5. 边界遵守（需求 §2.2）

1. 在制剧集：worktree 隔离；无锁运行字节不变（`test_pipeline_child_env_exports_only_a_locked_run`）。
2. 不授予扣费/预算/重提/发布/上传权限：契约层拒绝授权键（`CANDIDATE_CANNOT_GRANT_AUTHORITY`）；`--paid` + `paid_requests_enabled` 两把锁未动。
3. 新知识只让免费检查过期（`impact.py`）。
4. 云端同步不是付费前的远程等待：`verify_lock_for_send` 只读本地缓存；T24。
5. 不改原著、不统一缩短对白：`selection.py` 断言台词字节相同。
6. 共享代码作品无关：`test_collective_director_score` 扫描禁止作品专名；`contracts.sensitive_findings` 拒绝绝对路径。
7. 候选不自动成硬规则：`CANDIDATE_CANNOT_SELF_DECLARE_STATE`；发布只能 publisher；创作类候选 CANARY 需 REAL_MEDIA_REVIEW 或 CROSS_CASE_EFFECT。
8. 不以裁脸/冻结掩盖缺陷记为成功：`OUTCOME_KINDS` 无 DEFECT_FIXED；只有 ACCEPTED_IMPERFECTION。
9. 无预算不用付费：本任务零 POST，零模型评审费。
10. 旧版本与回滚：包版本不可变；评估按 sha 版本并存。

## 5a. S3 模式（2026-10-29，线主：对象存储即云端）

`tools/collective_learning/s3_sync.py`：`S3Transport`（outbox 批次 → inbox 对象，敏感条目上传前拒绝）、`Collector`（inbox → `Service.ingest_*` → acks → processed/quarantine，可重入）、`S3Channel`（签名频道指针、设备端取包校验入缓存、吊销列表）、CLI `bootstrap / device-sync / collect / publish-channel / status`。`line_upgrade_gate.collective_preflight` 回执新增 `sync_mode`，S1 仍只读本地缓存。测试 `test_collective_s3_sync`（7）：批次入箱与入库回执、重复上传不重复计数且收集器重跑幂等、敏感条目拒绝与坏对象隔离、桶断连只重试不崩、频道发布/清洁设备解析校验、篡改指针与陌生签名者拒绝、换包字节被 payload sha 拦下、CLI 全链。

**真实桶闭环（租户 `loop-test`，独立 scratch 运行根，纯合成 JSON）**：bootstrap → `collective/loop-test/trust.json`（公网 200）→ 设备 A 记一条合成事件 → `device-sync` 推 1/1 → `collect` 入库 created 1、unique_events 1 → 再 sync/collect：sent 0、items 0、unique 仍 1 → 候选 CANDIDATE→VALIDATED→CANARY → 签名包 `directing-dialogue@2`（bundle digest `d07dc92f…`）镜像到 `bundles/directing-dialogue/2.json` → `publish-channel` 写 `channels/canary.json`（sequence 1）→ 干净设备目录从桶取 trust 与包：FETCHED、`resolve_local` 选中同一摘要 → 运行锁 CREATED，第二次 `EXISTING_LOCK_KEPT` → SELECTED 采用回执 → `device-sync` 推 1 → `collect` 入库 → `trace_candidate` 显示该回执（SELECTED）。清理：`s3ctl rm collective/loop-test/ --recursive --yes` 删 7 个对象，ls 为 0。

生产租户 `nalu` 已在本机 bootstrap：`~/nalu_runtime/runtime/collective/`（sqlite、`publisher.key.json` 0600、`admin.token` 0600、trust），trust 已上传 `collective/nalu/trust.json`。**没有**给任何剧集写 `COLLECTIVE_LEARNING_CONFIG.json`：在制剧集仍完全关闭。

## 6. 未完成 / 诚实标注

- **CLOUD_DEPLOYED**：按线主 2026-10-29 的定义（S3 即云端）已达到：桶在线，S3 模式闭环对真实桶通过（§5a），nalu 租户已 bootstrap。未做：任何生产线的 `COLLECTIVE_LEARNING_CONFIG.json`（需要线主指定首个带知识锁的批次）、cron 的安装、第二台设备。HTTP 服务模式保留但无人运行。
- **PILOT_OBSERVED**：无真实 `OUTCOME_OBSERVED`；演示保持 `PENDING_REAL_FILM`。需要一个带知识锁的真实新批次（建议 E13 或 E12 的新 batch_id）并由线主决定。
- **演示模型为 SD2**：唯一能走严格编译的共享对话夹具是 SD2；H3 的接线由 `H3FinalRenderTest` 证明（编译器打桩）。真实 H3 全链路需要在试点集上观察。
- **创作类候选的 CANARY**：演示里评审员对合成片段记了 `REAL_MEDIA_REVIEW`，transcript 标注 `canary_basis_caveat`；不是真实成片评审。
- **证据字节上传**：已实现（`object_store.upload_evidence`：先 PUT 再登记 storage_key + sha256），真实网关预检 PASSED（nalu、collective，2026-10-29，回执不入库）。bucket 整体公开读；共享代码默认拒绝媒体类型（`allow_media: false`），线主 2026-10-29 决定 nalu 线允许上传成片切片/关键帧（配置 `allow_media: true`），完整剧本、人脸/声音参考、密钥、本机路径仍被 `sensitive_findings` 门拒绝。预检发现并已处理两个真实差异：网关对 boto3 ≥ 1.36 默认的 aws-chunked 上传回 `MissingContentLength`（客户端改 `request_checksum_calculation=when_required` + 显式 Content-Length）；公网域名前的 CDN 对默认 `Python-urllib` UA 回 403（预检用显式 UA）。云端服务与真实设备尚未长期跑在它上面：状态仍是 LOCAL_INTEGRATION_VERIFIED。
- **管理界面**：只读追溯页 + bearer，无登录/会话。
- **未接线的入口**：S3/S5 图片提交器；gitignored 逐集构建器仍直接调 `nalu_prompt_rules.apply`；三个 raw-urllib 旁路（`giggle_omni_video_fallback.py`、`submit_e20_static_visual_lock_batch.py`、`giggle_asset_factory.py`）未改，有测试钉住它们不在正式路径上。
- **效率报表**：`efficiency_report` 已实现，但成片评审提交点没有费用/等待数据可喂，需从 S7 账本调用方传入。
- **基线中发现、未修**：`compile_grouped_seedance_manifest.write_preflight_artifacts` 在 `1221d64` 若被触达会 `NameError: event_decision`（legacy 路径，v4 运行时不走）。
- **ETag 更新权限**：评审者可把候选移到 VALIDATED/REJECTED/NEEDS_EVIDENCE；只有 publisher/admin 能到 CANARY/RELEASED/DEPRECATED/REVOKED（§10 定义了评审角色，故比需求表格的「仅发布者」多了评审者前半段）。

## 7. 下一步（需线主决定后）

1. 批准 `AUTHORIZATIONS_REQUIRED.md` §A 其余项（主机、admin 凭证、发布者私钥）→ 部署云端（`Service(..., object_store=…)`）→ 把 nalu 线的新批次加 `COLLECTIVE_LEARNING_CONFIG.json`（含 `object_store` 块）并在该机器跑一次 `object_store.py preflight`。
2. 在该批次成片评审时填写 `director_evaluation` 块 → 产生第一份真实 DIRECTOR_SCORE_V1 与下一集计划。
3. 第一条真实 `OUTCOME_OBSERVED` 之后，才把状态升到 PILOT_OBSERVED。
