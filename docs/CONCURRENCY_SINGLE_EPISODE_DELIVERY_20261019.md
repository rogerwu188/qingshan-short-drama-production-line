# 单集全流程并行：实施交付（2026-10-19）

范围：同一集内，无真实依赖的准备、检查、生成、收割任务并行推进。本轮不启用多集并发，不改多集授权，不扩大预算，未产生任何真实付费调用。

## 1. 基线与提交

| 项 | 值 |
|---|---|
| 实施前基线 | `11db19d` |
| 预算原子预留（K111） | `02f7bc5` |
| 便携 CI 防回归 + 审计 harness 修复 | `be9fa81` |
| 非付费逐镜编译并行（K112） | `0c9c6ee` |

## 2. 串行来源定位（真实调用位置）

| 位置 | 问题 | 结论 |
|---|---|---|
| `lines/nalu/runtime/tools/nalu_budget_ledger.py` `build_report()` | `--check` 只读，不记录预留；`projected = recorded + planned` | **真实复现**（两并发调用各 600、recorded 7000，双双通过 8000 上限） |
| 同上 + `tools/episode_video_generation_guard.py` | `SUBMITTED_TASK_ID_BOUND`（已 POST、未对账）计入 0 暴露 | **真实复现**（600 积分波次看起来没花钱） |
| `tools/submit_giggle_video_manifest_v2.py` `main()` | 曾按 `range(0, len, concurrency)` 整波切片 | **本已修复**（有界就绪队列 + `FIRST_COMPLETED`，测试锁住） |
| `lines/nalu/runtime/tools/nalu_pipeline.py` `stage_s6()` | 尾帧曾等整波 poll 后统一提取 | **本已修复**（逐单元落盘即提取） |
| `lines/nalu/runtime/tools/build_keyframe_manifest.py` `main()` | 逐镜编译为单线程列表推导；每镜读并 SHA 校验多张参考图 | **真实复现**（一镜慢读拖住其后所有镜） |
| `stage_s5()` 收割 | `harvest --watch` 等 `all_terminal` 才进 Q1 | **保留**：每轮已逐张下载完成项；Q1 是必须的汇合点 |
| `stage_s6()` 波次 | 冻结波次成员、开新波不整集等待 | **本已具备**（重叠波次 + 可选 `max_remote_inflight`） |
| `tools/build_measured_edit_constraints.py` | 只读 `POST_GENERATION_QA.json`，不跑 ASR/子进程 | **不是瓶颈**，未改 |
| `paid_stage.sh` | 单集锁覆盖整个付费运行 | **保留**：它防的是同集双进程 POST；跨进程去重另有事务指纹 |

## 3. 修改前后行为证据

修改前失败、修改后通过（`tools/tests/test_concurrent_dispatch.py`，便携清单内）：

- `test_two_concurrent_checks_cannot_both_admit_spend_beyond_cap` — 前 FAIL（`BUDGET_CHECK_THEN_ACT`），后 PASS
- `test_bound_task_whose_charge_is_not_yet_reconciled_counts_as_exposure` — 前 FAIL（`PENDING_EXPOSURE_NOT_COUNTED`），后 PASS
- `test_a_released_reservation_frees_its_credits` — 新增，PASS

`tools/tests/test_keyframe_compile_parallel.py`（新增 5 例，便携清单内）：

- 四镜用 `Barrier` 断言真实重叠（串行会死锁失败）
- 慢镜不改变 `dropped_prompt_segments` 归并顺序
- 单镜异常使整批失败（半套 prompt 不报成功）
- `workers=1` 输出顺序与原串行路径一致
- 空输入返回空

其他已存在的并发测试（审计文件，不入 CI 清单）：`tools/tests/test_concurrent_dispatch_audit_repro.py` 7 例全部通过。两个模块合计 15 例 PASS。

## 4. 入口验证

- `stage_s5()` 一次把整份关键帧清单交给一个提交器进程（`--concurrency min(ctx.max_parallel, 6)`），没有逐任务外层循环。
- `stage_s6()` 每个波次把该波全部就绪单元交给一个 `submit_giggle_video_manifest_v2.py` 进程；开新波只要求该波自身的就绪条件，不等全集。
- `paid_stage.sh <EP> <FROM> <UNTIL>` 是唯一付费 argv；它不拆分任务清单。
- `episode_parallel_batch_supervisor.py` 主循环每个 tick 重读提交范围、无整批屏障（`batch_barrier = False`），独立任务 + 每链一个头并发。
- 跨进程同指纹：提交器 per-task `flock` + 事务指纹，第二个进程读到 `SUBMITTED_TASK_ID_BOUND` 不再 POST（有跨进程复现测试，保持通过）。

## 5. 并发、锁、预算与恢复

| 控制项 | 取值与归属 |
|---|---|
| 提交线程上限 | `generation.max_parallel_tasks`（示例 6）→ 提交器 `--concurrency`，上限 6 |
| 远端在飞上限 | `generation.max_remote_inflight`（可选，未配置则不限；由部署按供应商账户能力定） |
| supervisor 线程 | `max_submit_workers=8`、`max_poll_workers=8`、`max_qa_workers=4` |
| 逐镜编译并发 | `min(8, 镜数)`，可用 `workers` 参数覆盖 |
| 事务锁 | per-task `flock`（事务文件同名 `.lock`），持锁范围 = 读事务→写 intent→POST→绑定 |
| 预算锁 | `workflow/nalu/<EP>/BUDGET_RESERVATION.jsonl` + 同名 `.lock`；锁内重扫后判定 |
| 预算判定 | `projected = recorded + active_reserved + pending_exposure + planned` |
| 预留释放 | 仅追加释放行（`release_reservation`）；超时不视为未扣费 |
| 恢复 | 事务指纹相同即恢复；`RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION` 先对账再决定；`--check` 保持只读 |

## 6. CI 与完整性

| 检查 | 结果 |
|---|---|
| 便携 CI | PASS，required_files 210，test_modules 112，failures 0 |
| 部署完整性 | PASS，2163 文件，missing 0，changed 0 |
| 知识库校验 | PASS，rule_count 112 |
| 失败记忆导出 | 71 行，与 registry export 逐字节一致 |

新增知识条目：K111（预算原子预留与 pending 暴露）、K112（非付费逐镜编译并行与有序归并）。

## 7. 未做与原因

- **多集并发**：本轮范围明确排除；`THREE_EPISODE_CONCURRENCY_POLICY` 维持单集调试覆盖，未改动。
- **S7 提前处理**：`build_measured_edit_constraints` 已是单遍文件读取；ASR 证据来自 S6 post-gen QA，不在 S7 重跑。最终装配仍要求全集素材齐备（门禁要求，不是性能取舍）。
- **S5 收割提前**：`--watch` 每轮已逐张下载；Q1 审核前必须汇总，未把审核拆成逐单元。
- **移除 `paid_stage.sh` 集锁**：预算预留已修正双进程竞态，但集锁仍承担跨进程互斥，本轮不冒险移除。

## 8. 后续轮次补充（K113–K115 与刻意未改项）

### 8.1 后续提交

| 项 | 提交 |
|---|---|
| 预算预留接线付费路径 + 按模型计价暴露 | `0157941` |
| 视频轮询按波并发（K113） | `39f9b1e` |
| 图片收割按批并发（K114） | `9903ce4` |
| S4 配音按角色并发（K115） | `585e659` |

### 8.2 新增的并发点与保留的串行点

| 位置 | 处理 | 原因 |
|---|---|---|
| `poll_giggle_submit_report.poll` | 并发查询+下载，`NALU_POLL_WORKERS` 限流 | S6 每个 tick 都轮询整波，旧实现逐任务串行往返 |
| `harvest_giggle_image_batch.poll_once` | 并发查询+下载，`NALU_HARVEST_WORKERS` 限流 | 50 任务量级、每 15 秒一轮，旧实现逐任务串行 |
| `nalu_pipeline.s4_generate_all` | 按角色并发；registry 行仍顺序写 | 角色间无依赖；voice_registry 是整份读改写，不能在线程里写 |
| `nalu_selective_bgm.cmd_generate` | **保留串行** | `--paid` 下失败或响应丢失即停止提交，是先对账再继续的金额安全规则 |
| `keyframe_q1_builder.measure_still_identity` | **保留串行** | 共享单个 FaceAnalysis 实例，并发推理有正确性风险；每集只跑一次 |
| `build_nalu_preproduction` 各 stage | **保留串行** | stage 之间有真实依赖（后一 stage 读前一 stage 产物） |
| 提交器逐任务 SHA 校验 | **保留串行** | 每批一次、属付费前门；收益小、风险不对称 |

### 8.3 并发上限（全部可配置，无硬编码）

| 控制项 | 默认 | 覆盖方式 |
|---|---|---|
| 逐镜关键帧编译 | `min(8, 镜数)` | `compile_tasks(workers=)` |
| 视频轮询 | 6 | `NALU_POLL_WORKERS` |
| 图片收割 | 6 | `NALU_HARVEST_WORKERS` |
| S4 配音 | `min(max_parallel, 角色数)` | `generation.max_parallel_tasks` |
| S6 提交线程 | `min(max_parallel, 6)` | `generation.max_parallel_tasks` |
| S6 远端在飞 | 未配置即不限 | `generation.max_remote_inflight` |
| 后期 QA | 4 | `NALU_QA_WORKERS` |
