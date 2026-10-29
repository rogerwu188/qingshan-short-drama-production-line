# 接线清单（阶段 A 第一份交付）

基线：引擎提交 `1221d64abbbb70b08d1540105d361ca056e1bba8`（= 需求文档的审阅基线 = 本地 `origin/main` = 开工时工作树 HEAD，工作树干净，无他人未提交修改）。
核查日期：2026-10-28。核查方法：对每个模块找真实调用者（file:line）、它所在的生产入口，以及行为测试。
实施分支：`feat/collective-director-learning`（独立 worktree，不碰在制剧集的运行时）。

## 1. 需求点名的七个模块

| 模块 / 函数 | 真实调用者 | 入口 | 结论 |
|---|---|---|---|
| `tools/knowledge_event_log.py` `record_event:102` `attribute_event:179` `mark_inconclusive:216` | 无生产调用者；仅 `tools/tests/test_knowledge_event_log.py` 与自身 CLI。没有任何东西写 `reports/KNOWLEDGE_EVENTS.jsonl` | 无 | **已有但未接线**。存储是 read-all/rewrite-all 的 JSONL，无锁；`test_collective_device_store.MultiProcessTest` 复现了多进程丢行 |
| `tools/knowledge_consumption_ledger.py` `record_application:99`（APPLIED） `record_verification:156`（VERIFIED） `status_for_rule:226` | 无生产调用者；仅测试与 `docs/knowledge/LINE_UPGRADE_PROTOCOL.md:95` 的示例 | 无 | **已有但未接线**。无 EXPORTED 记录种类（`KINDS:59` 只有 APPLIED/VERIFIED）；"exported" 在 `status_for_rule:236-245` 里从简报文件 `rule_ids` 推导。行为回归测试写的 VERIFIED 行进临时目录，真实账本从不含 VERIFIED |
| `tools/knowledge_sync_core.py` `sync:211` | `lines/nalu/runtime/tools/knowledge_sync.py:74/90` → `nalu_pipeline.py:8404 knowledge_sync_summary` ← `stage_s8:8438`；`line_upgrade_gate.close:352` 也会调，但管线以 `--skip-sync` 调 close（`:1535`） | S8 | **已有且已接线**，仅 advisory，不阻断 |
| 同模块 `free_recheck_targets:151` | 仅 `sync:281` SYNCED 分支；结果只在 `write_checkpoint`（`nalu_pipeline.py:8566-8575`）打印 | S8 | 已接线，**只报告**；无显式影响范围，只按 argv 脚本名匹配 |
| `tools/line_upgrade_gate.py` `preflight:268`（含 `knowledge_briefing:221`） | 子进程：`_line_upgrade_gate_summary`（`nalu_pipeline.py:1521`）← `_record_line_upgrade` ← `stage_s1:1559` | S1 | **已接线，advisory**。`knowledge.status="READ"`（`:297`）在简报文件写完即置位；`verify_briefing` 只查文件存在 + sha。**没有任何写手/构建器/编译器读 `<EP>_KNOWLEDGE_BRIEFING.*`**，READ = "文件已写出"，不是"已理解/已应用" |
| 同模块 `close:342` `verify_briefing:321` | `stage_s8:8440`（`--skip-sync`） | S8 | 已接线，advisory |
| `lines/nalu/runtime/tools/nalu_prompt_rules.py` `apply:118` | 无受跟踪的调用者。只有 gitignored 的逐集构建器 `build_eNN_layers.py`（`.gitignore:144`；主 checkout 里 `build_e02_layers.py:703`…`build_e12_layers.py:1497`）手工运行时调用；没有一个传 `ctx["failure_memory"]`，所以 `KNOWLEDGE:<id>` 分支（`:208-217`）在生产中从未触发；无人调 `record_application` | 无（构建器不经管线） | **已有，仅库外手工调用**；`min_dialogue_seconds` / `BODY_VERBS` / `MOVING_CAMERA` 由 `static_design_gate.py:120-148`、`build_nalu_preproduction.py:948` 等使用（已接线） |
| `nalu_pipeline.py` `s7_final_audience_review:7172` | `stage_s7:8280`；非 PASS → S7 REVIEW_REQUIRED/BLOCKED（`:8282-8286`） | S7 | **已接线且阻断**。产出 `*_AUDIENCE_SCORE_REPORT.json` / `*_FINAL_CUT_EVENT_LEDGER.json` 进入 `final_qa_evidence_bundle.py:310-318`。**成片事件账本从不回流到 knowledge_event_log**。接线测试：`test_nalu_current_policy_profile.py:316` |

## 2. 需求要求特别核查的四点

1. **READ 兼容状态**：确认只表示简报文件已写出（见上表）。本任务：保留 READ 作兼容值，回执增加 `knowledge_status_semantics: "READ=BRIEFING_WRITTEN_NOT_APPLIED"`，采用证据来自采用回执（`tools/collective_learning/adoption.py`），`status_for_rule` 不把 EXPORTED/READ 显示成 APPLIED（T15）。
2. **事件日志并发**：`record_event` 与 `_update_attribution` 都是读全文件再 `tmp.replace()` 整写，无锁。`tools/tests/test_collective_device_store.py::MultiProcessTest::test_legacy_jsonl_log_loses_rows_under_the_same_load` 用 6 进程 × 40 条复现丢行（2026-10-29 实测，Apple M1：JSONL 文件最终**损坏不可读**，240 次写入中 210 次抛异常；同负载下 SQLite 存储 240/240 全部保留）。本任务：设备端改为 SQLite（WAL + `BEGIN IMMEDIATE`，事实与 outbox 同一事务）；`export_jsonl` 生成兼容视图，JSONL 不再是权威。
3. **`free_recheck_targets` 不是依赖影响分析**：只按 `state.stages[*].steps[*].argv[1]` 的脚本名匹配规则 `implementation`。本任务：规则显式 `impact_scope {free_checks, modules, stages}`（`tools/collective_learning/impact.py`），与原 argv 匹配取并集；付费步骤永远列在 `paid_never_resubmitted`，不自动重跑任何东西（T18）。
4. **旁路入口审计**（付费 POST 实际路径）：

| 入口 | 过 S1–S8？ | 发送前重校验提示词 sha？ | 结论 |
|---|---|---|---|
| S6 `_stage_s6_body` → `ctx.paid_step:6469` → `submit_giggle_video_manifest_v2.py` `main:1348` → `submit_one:1123/1256` | 是 | 是：文件 sha 对 `task["prompt_sha256"]`（`:1135`）、`require_reviewed_request(task_request_digest(prompt_text=payload["prompt"]))`（`:1185`）绑定实际 POST 文本；`prior_bound:1002` / `live_bound_elsewhere:1097` 对持久事务存档 | **唯一合规付费视频通道**；本任务在此接 `verify_lock_for_send` + PROVIDER_REQUEST 采用回执 |
| A/B `run_ab_variant:6092` | 部分（独立子命令，同一提交器） | 是（同 `submit_one`） | 同通道 |
| Q2 自动重做 `s6_q2_auto_redo:6608` | 是 | 是 | 同通道 |
| reroll：`tools/reroll_cost_guard.py` | 管线只打印命令（`:6552-6557`）；`post_generation_qa_runner.py:888` 引用（无 POST） | n/a | 无独立 reroll 运行器 |
| 断点恢复 / 丢响应 | 重进 `run` → `submit_one` 对 `workflow/tasks/giggle_video_submit_transactions/<EP>/`；`RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION`；`reconcile_*` / `recover_interrupted_image_submit.py` 只 GET 或离线 | 是 | T17 覆盖 |
| S3 `submit_giggle_character_asset_plan.py`（`:2597`）；S5 `submit_giggle_image_manifest.py`（`:3883`） | 是 | 是（`:148/:256`；`:359/:456/:489`） | 图片通道，本任务不改 |
| 逐集构建器 `build_eNN_layers.py`（gitignored） | 否（它们生成 S1 读的四层文件；管线不调用） | n/a（无 POST） | 调 `nalu_prompt_rules.apply`，不写账本；本任务改在 `build_nalu_preproduction` 的编译路径接线，使构建器是否记账不再决定证据 |
| 旧版即席视频提交脚本（`submit_e28_*`、`submit_e37_first_wave_*`、`submit_giggle_task_manifest.py`、`submit_e18_e19_*`、`submit_e38_*`） | 否 | 否 | **已被新版替代**，运行时被 `giggle_api_client._request:131` 守卫 / CLI 守卫 `:394` / shot-runner intent 检查拦住 |
| **真实旁路（raw urllib）**：`tools/giggle_omni_video_fallback.py:138`、`tools/submit_e20_static_visual_lock_batch.py:179-181`、`tools/giggle_asset_factory.py:36/50`；`submit_e37_v16_action_a02a.py:26` / `submit_e37_v17_long_a.py:26` 加载引擎外的 `generation_api.py` | 否 | 否，无守卫 | **已知旁路**。本任务不改它们（不在在制路径上），加清单测试断言它们不可从 `nalu_pipeline` / 正式提交路径到达，并在此记录 |

网络唯一卡口：`tools/giggle_api_client.py:130 _request`（视频端点需 `paid_video_submission_context()`；其它生成端点需 `durable_generation_context` 或 `QINGSHAN_DURABLE_SUBMITTER_CONTEXT=1`）。

最终提示词序列化位置：SD2 `tools/video_prompt_compiler.py:170 render_sd2_prompt`（`compile_grouped_seedance_manifest.py:671` 写文件，S2 4.4）；H3 `video_prompt_compiler.py:172 render_h3_prompt`，`build_nalu_preproduction.py:2576 render_h3_final_prompts`（`:2613` 写、`:2614` 记 sha，S2 4.5）；POST 前 `submit_giggle_video_manifest_v2.py:1161` 由提示词文件组 `payload["prompt"]`，`:1214` POST `/api/v1/generation/omni-video`。这条链上没有 `nalu_prompt_rules.apply` 或任何账本；`compile_grouped_seedance_manifest` 读的是自己的 `--failure-memory`（`GENERATION_PROMPT_FAILURE_MEMORY.json`，`:640`），不是 K 注册表。

## 3. 测试登记现状

正式集合 = `configs/PORTABLE_CORE_MANIFEST.json` 的 `portable_test_modules`（138 个），由 `tools/run_portable_ci.py:124` 以 `python -m unittest` 运行；`.github/workflows/portable-core.yml:24` 调用。

- 已登记：`test_knowledge_event_log`、`test_knowledge_consumption_ledger`、`test_knowledge_sync_core`、`test_knowledge_loop_behavioral_regression`、`test_nalu_prompt_rules_seq19`、`test_nalu_final_audience_review`、`test_submit_giggle_video_authoritative_gate`、`test_submit_giggle_image_manifest(_transactions)`。
- **未登记**（虽存在）：`test_line_upgrade_gate`（注册表规则 `ENGINEERING_KNOWLEDGE_V1.json:1402` 把它写成自己的回归）、`test_static_design_gate_motion`、`test_reroll_cost_guard`、`test_s6_resume_budget_and_tails`、`test_submit_giggle_video_generation_guard`、`test_video_submitter_shared_projection`、`test_submit_giggle_video_manifest_dialogue_transport`。
- 没有测试断言 S1/S8 真的调用了升级门与知识同步，也没有测试断言任何构建器写了消费账本。

三项仓库验证命令：`python3 tools/run_portable_ci.py`；`python3 tools/deployment_code_integrity.py`（对 `configs/DEPLOYMENT_CODE_SHA256.json` 逐文件 sha）；`python3 tools/knowledge_registry.py --validate`。

## 4. 确实缺失（本任务实现）

| 缺失 | 实现位置 |
|---|---|
| 全局 UUID 事件、tenant/line/device/run 三层身份、事实不能带根因/授权、修订链 | `tools/collective_learning/contracts.py`、`configs/schemas/collective_learning/*.schema.json` |
| 并发安全设备端存储 + 事务 outbox + 兼容导出 | `tools/collective_learning/device_store.py` |
| 后台上传、幂等确认、退避抖动、坏项隔离 | `tools/collective_learning/sync_client.py` |
| 云端：认证/角色、批量幂等接收、冲突审计、候选修订 ETag、发布状态机、不可变包、通道指针、设备同步状态、证据删除 | `tools/collective_learning/service.py`、`http_api.py`、`migrations/`、`docs/collective_learning/openapi.json` |
| 知识包签名/校验/缓存/兼容解析/运行锁；技能包校验（不经知识同步） | `tools/collective_learning/bundles.py` |
| 每单元建议选择、长度上限、冲突顺序、不改台词 | `tools/collective_learning/selection.py` |
| 采用回执五态 + 与消费账本合流 | `tools/collective_learning/adoption.py`、`tools/knowledge_consumption_ledger.py` |
| 显式影响范围 | `tools/collective_learning/impact.py`、`tools/knowledge_sync_core.py` |
| DIRECTOR_SCORE_V1、覆盖证明、自评/独立分离、下一集计划、效率报表 | `configs/DIRECTOR_SCORE_V1.json`、`tools/collective_learning/director_score.py`，接入 `final_audience_review.py submit` |
| 真实入口接线：S1 锁定 + SELECTED；编译 APPLIED；提交前锁校验 + PROVIDER_REQUEST | `line_upgrade_gate.py`、`build_nalu_preproduction.py`、`submit_giggle_video_manifest_v2.py` |

## 5. 设计决策

- 云端首版 SQLite + 标准库 HTTP（仓库核心零依赖的约定；Postgres 迁移只换 DDL 方言，`migrations/0001_init.sql` 已注明差异）。不引入 FastAPI/Kafka/K8s。
- 签名用仓库 `cloud` extra 已声明的 `cryptography`（Ed25519）；缺库时校验失败关闭，不是跳过。
- 知识包 = 纯数据；技能包必须走引擎发布流程（签名 + 回归），知识同步通道拒收任何带可执行内容的包。
- 在制剧集零影响：所有新接线以「运行是否带知识锁」为开关；没有锁（现有 E11/E12 运行）时路径字节不变。
