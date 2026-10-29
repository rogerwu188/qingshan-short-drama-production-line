# 跨设备端到端演示（需求 §14，T27）

一条真实命令，全部本地、合成、作品无关：

```bash
cd $ENGINE_ROOT
.qingshan-venv/bin/python tools/collective_learning_demo.py --out /tmp/collective-demo
# 同一函数的逐步断言：
.qingshan-venv/bin/python -m unittest tools.tests.test_collective_e2e_demo      # 10 tests
```

产出 `transcript.json`（结构化）与 `transcript.md`（人读）。`--keep` 保留临时云端/设备目录以便查看。

## 环境

- 云端：`tools/collective_learning/service.py` 跑在真实 HTTP 服务（`http_api.start_server`，127.0.0.1 临时端口），配置信任库，Ed25519 签名由服务端真实校验。租户 `demo-tenant`；主体 `dev-a`（line-a）、`dev-b`（line-b，canary）、`dev-c`（line-c，canary）、`rev-1`（评审）、`pub-1`（发布者）。
- 设备 A / B / C：各自独立运行时根（SQLite 事实库 + outbox、信任文件、包缓存、运行锁目录），只经 HTTP 与云端通信（`sync_client.SyncClient` + `HttpTransport`）。评审/发布者在进程内直接调用服务对象（同一份代码）。
- 编译：引擎自己的 SD2 严格编译路径 `tools.compile_grouped_seedance_manifest.compile_final_prompts`，单元来自引擎共享的编译器测试夹具（对话单元，听者在画外）。
- 网络拦截：`socket.socket.connect` 对任何非回环主机抛异常并计数；`tools.giggle_api_client._request` 被替换为计数并抛异常。两者计数写进 transcript。

## 实际一次运行的摘要（2026-10-29T07:25:41Z）

| 步骤 | 事实 |
|---|---|
| 0 | 云端起动，5 个主体，签名校验 = Ed25519 via trust store |
| 1 | 设备 A 记录 `FAILURE_OBSERVATION` `4d166ac5-fcd0-48de-b9af-b0610411a63b`：时间码绑定合成成片 sha `63a2ed1f…7239a6`（FINAL_CUT 41200–44900 ms），机会数 6/1；事件无 `root_cause` 键，带该键校验被拒 `FORBIDDEN_KEY_ON_FACT:root_cause`；云端 ack DELIVERED=1，唯一事件数 1 |
| 2 | 真实编译两次：无规则 `14af2c37…`，有规则 `d76313f0…`；台词字节不变 = true。归因 `4ec7ce82-8d15-4734-9e07-8dadef17fa20`（basis REPRODUCED，置信 MEDIUM）。第二个事件（听者在画内）标 INCONCLUSIVE `ee3d3104-433b-4ffa-b097-ea2078a6ca69`，理由含 `REQUIRED_CONDITION_ABSENT:listener_offscreen`。云端 ack DELIVERED=4，QUARANTINED=0；归因链版本 [1] |
| 3 | 候选 `R-DLG-OFFSCREEN-LISTENER-EYELINE`，scope `{models:[seedance-2.0-pro], stages:[VIDEO_COMPILE], scene_types:[DIALOGUE], requires:[listener_offscreen]}`。状态 CANDIDATE → VALIDATED(DETERMINISTIC_REGRESSION) → 发布者试推 CANARY **被策略拒绝**：`VALIDATION_SCOPE_INSUFFICIENT:need_any_of=['REAL_MEDIA_REVIEW','CROSS_CASE_EFFECT']` → 评审补记 REAL_MEDIA_REVIEW（**演示注记：所审媒体是本演示的合成片段，不是真实成片**）→ CANARY。渲染正反例：有规则含条款 true / 无规则 false / 听者在画内单元 NOT_APPLICABLE。签名包 `directing-dialogue@2` 包摘要 `63e81be1…212059`，云端载荷 sha `afaa6295…843c16`，`SIGNATURE_VERIFIED:bundles.verify_bundle:key_id=pub-1`，发布到 CANARY |
| 4 | 设备 B：在制运行 `R-old` 发布前已锁定内置基线 `5c64fe64…ecf4d6`（标签 `BUILTIN_BASELINE_NOT_CLOUD_SYNCED`）；发布后再调 `lock_run` → `EXISTING_LOCK_KEPT`，锁文件 sha 不变。新运行 `R-new` 经 `pull_bundles(CANARY)` 拉取、校验、入缓存，锁摘要 `63e81be1…` == 发布包摘要 = true |
| 5 | B 带锁经真实入口编译：APPLIED 回执 `6cd6fa63-da98-4fab-835d-8faf247db53f`（scope COMPILED_REQUEST，入口 `compile_grouped_seedance_manifest.compile_final_prompts`，编译输出摘要 `d76313f0…` 与发送文本 sha 一致）；VERIFIED 回执 `af10c4c2-15cb-46df-ac8b-39054bc1ff29`（具名断言 `test_collective_e2e_demo.clause_in_locked_compile`）。B outbox PENDING=0；云端候选追溯中 dev-b 的采用状态 = [APPLIED, VERIFIED]。付费 POST 计数 0 |
| 6 | `outcome: PENDING_REAL_FILM`，OUTCOME_OBSERVED 回执 0 条（无真实获准成片，不用模拟视频冒充） |
| 7 | (a) 设备 C 以 `MiniMax-H3` 能力解析 → 无可用包，`not_applicable` 理由 `OUT_OF_SCOPE:model=MiniMax-H3`；(b) 重发事件 1 → HTTP 200 ack `DUPLICATE`，唯一事件 2→2，重复投递记录 1；(c) 关停云端：A 离线记录新事件 `d1eb3730-…` 耗时 0.0033 s（不阻塞），同步 retry=1；同一 DB 文件重启服务后补传：outbox DELIVERED=5 / PENDING=0 / QUARANTINED=0，唯一事件 3，重复投递仍为 1 |
| 8 | 发布者撤回 `directing-dialogue@2`（CANARY 指针回退为空）；B 的第三个运行 `R-next` 回退到内置基线 `5c64fe64…`；`R-new` 自己的锁对缓存 `verify_lock_for_send` 仍 PASS；云端追溯返回候选（状态 CANARY）、事件、归因、包（含 revoked）、2 条采用回执、独立来源 1（line-a/dev-a）；管理页 `/admin/candidates/<id>` 含候选 id 与事件 id |

`paid_post_count: 0`；`non_loopback_connect_attempts: 0`；`provider_client_calls: 0`。

## 诚实边界

- **演示模型是 SD2（seedance-2.0-pro）**而非 H3：引擎共享的对话夹具只在 SD2 严格路径上完整编译；H3 路径的采用接线由 `tools/tests/test_collective_real_entry_wiring.py::H3FinalRenderTest` 另行证明。「不适用模型」注入因此用 H3 能力的设备。
- 创作类候选进 CANARY 需要 `REAL_MEDIA_REVIEW` 或 `CROSS_CASE_EFFECT`；演示先展示仅凭确定性回归被拒，再由评审**显式**记录对合成片段的媒体审阅并在 transcript 中标注注记。生产中该 scope 必须来自真实成片审阅。
- 没有真实成片，`OUTCOME_OBSERVED` 保持待观察；没有付费接口调用，所以步骤 5 的 `PROVIDER_REQUEST` 回执不在本演示内（由 `SubmitBoundaryTest` 用拦截传输层证明）。
- 评审与发布者动作在进程内调用服务对象而非 HTTP 路由（同一实现；HTTP 路由由 `test_collective_service` 覆盖）。

## 本演示暴露并修复的两处

1. `sync_client.run_once` 按字典插入顺序发送 outbox 种类，归因评审可能先于其事件上传而被云端以 `EVENT_NOT_FOUND` 隔离；现按 `ROUTE_BY_KIND` 依赖顺序（EVENT → REVIEW → ADOPTION → EVALUATION）发送。
2. SD2 严格路径的 APPLIED 回执入口标签误为 `write_preflight_artifacts`；现为 `compile_grouped_seedance_manifest.compile_final_prompts`。
