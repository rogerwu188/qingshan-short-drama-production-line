# 部署、配置、备份恢复、凭证轮换、升级回滚与运维

状态：**LOCAL_INTEGRATION_VERIFIED**。下面每条命令都在本机隔离环境实际跑过；"云端"一节描述真实部署需要做的事，尚未执行（阻塞项见 `AUTHORIZATIONS_REQUIRED.md`）。

## 1. 组件

| 组件 | 代码 | 运行位置 | 依赖 |
|---|---|---|---|
| 云端服务 | `tools/collective_learning/service.py` + `http_api.py` | 一台主机，一个进程 | Python 3.12 标准库 + SQLite；签名校验需 `cryptography`（`pip install -e '.[cloud]'`） |
| 后台处理 | 同一进程（候选去重/结构校验在写入时同步完成；无独立 worker） | — | — |
| 设备端客户端 | `device_store.py`（SQLite + outbox）、`sync_client.py`（上传/拉包）、`bundles.py`（缓存/校验/运行锁） | 每条生产线的运行时根目录 | 标准库；校验签名需 `cryptography` |
| 管理界面 | `http_api.py` 的 `/admin`、`/admin/candidates/{id}`（服务端渲染、只读，需 reviewer/publisher/admin bearer） | 同服务 | — |

## 2. 云端服务：安装与启动

```bash
# 初始化租户，打印一次性 admin token（只打印一次，立即存进密钥管理）
python3 tools/collective_learning/http_api.py bootstrap --db /srv/collective/collective.sqlite --tenant <tenant_id>

# 启动（只监听回环；公网由反向代理终止 TLS 并转发）
python3 tools/collective_learning/http_api.py serve --db /srv/collective/collective.sqlite --host 127.0.0.1 --port 8787 --max-batch 500 --ready-file /run/collective.port

# OpenAPI
python3 tools/collective_learning/http_api.py openapi > openapi.json   # 与 docs/collective_learning/openapi.json 相同
curl -s http://127.0.0.1:8787/v1/health
```

数据库迁移：`service.py` 启动时按 `migrations/*.sql` 顺序执行，记录在 `schema_migrations` 表；重复启动幂等。换 PostgreSQL 时见 `migrations/0001_init.sql` 头部注释（类型与自增语法差异）。

注册设备（admin）：`POST /v1/devices` `{principal_id, role: device_writer, line_ids: [...]}` → 返回该设备 token（只返回一次）。设备 token 只能写自己 `line_ids` 内的事件，不能发布、不能读其它租户。

## 3. 设备端：开通一条生产线

1. 在运行时报告目录放 `COLLECTIVE_LEARNING_CONFIG.json`（没有此文件 = 完全关闭，所有钩子返回 `None`，生产行为字节不变）：

```json
{"tenant_id": "<tenant>", "line_id": "<line>", "device_store": true,
 "trust_store": "trust.json", "cache_dir": "bundle_cache", "channel": "RELEASED",
 "engine_api_version": "<engine commit or api tag>",
 "capabilities": {"model": "MiniMax-H3", "aspect_ratio": "9:16", "language": "zh"},
 "batch_id": "B1",
 "revocations": "revocations.signed.json",
 "baseline": {"path": "bundle_cache/baseline.json", "digest": "<sha256>"},
 "provider_model_version": "UNKNOWN", "rubric_version": "DIRECTOR_SCORE_V1"}
```

2. `trust.json`：`bundles.make_trust_store({key_id: {public_key: <b64>, roles: [publisher]}})`；只信任线主指定的发布者公钥。
3. 设备同步：`sync_client.BackgroundSync(SyncClient(store, HttpTransport(url, token)), interval).start()`，或 cron 调 `run_once()`。断网时事件留在 outbox；恢复后补传，幂等。
4. 每集开工：S1 的 `line_upgrade_gate.preflight` 自动解析缓存里已验证的包 → 写 `<line>.<episode>.<batch_id>` 运行锁 → 记 SELECTED 回执。**锁一旦写出，该 run 不再解析 latest**；新集或新 `batch_id` 才会换包。
5. 在制剧集：不要给正在跑的集加配置文件；它们没有锁，路径不变。

## 4. 备份与恢复

- 云端：`sqlite3 collective.sqlite ".backup /backup/collective-$(date -u +%Y%m%dT%H%M%SZ).sqlite"`（WAL 模式下在线备份安全）。恢复 = 停服务、换文件、起服务；`test_collective_service` 的 T26 用例验证重开同一文件后凭证、证据状态、包与通道、审计日志一致。
- 设备端：`reports/COLLECTIVE_DEVICE_STORE.sqlite` 同样 `.backup`；outbox 状态随库一起恢复，未送达项恢复后继续送（T08）。
- 发布包缓存 `bundle_cache/` 是内容寻址的，可随时从云端 `GET /v1/bundles/{id}/versions/{v}` 重拉；丢失缓存不丢锁（锁里有 digest，重拉后校验相同）。
- 证据对象：元数据在库里；字节在对象存储（待授权）。删除证据后相关候选自动变 `EVIDENCE_UNAVAILABLE` 并失去推广资格，恢复数据库不会把它变回"证据齐全"。

## 5. 凭证轮换与吊销

- 设备/评审/发布者 token：`POST /v1/devices/{id}:rotate`（返回新 token，旧 token 立即失效）、`POST /v1/devices/{id}:revoke`。库里只存 sha256(token)。所有拒绝写 `audit_log`。
- 发布者签名密钥：生成 `bundles.generate_keypair()`；私钥不进仓库、不进运行时目录；公钥加入每台设备的 `trust.json`。轮换 = 新 key_id 入信任文件 → 新包用新钥签 → 旧 key 从信任文件移除（旧包需重签或保留旧 key 只读）。签名只证来源，不证内容正确；包仍需评审与回归。
- 撤销：`POST /v1/revocations`（publisher）→ 通道指针事务性移走；设备端 `revocations.signed.json` 由发布者签名，下次 resolve 跳过被撤版本；已锁定的旧 run 不受影响，新 run 回退到仍有效的版本或基线。

## 6. 升级与回滚

| 对象 | 升级 | 回滚 |
|---|---|---|
| 引擎代码（含技能包） | 走仓库发布流程：`run_portable_ci.py` → `deployment_code_integrity.py --build` → tag；技能包 `bundles.verify_skill` 校验签名、权限声明（默认 shell/network/paid 全禁）| `git checkout <tag>`；运行锁里的 `engine_commit` 让旧 run 可追溯 |
| 知识包 | 发布者上传新版本（不可变）→ `POST /v1/releases` 把通道指针指过去 | `POST /v1/revocations` 或把指针指回旧版本；旧版本永不删除 |
| 评分标准 | 新版本号（`DIRECTOR_SCORE_V2.json`），旧评估保留；跨版本 `compare()` 拒绝 | 不需要回滚：版本并存 |
| 云端 schema | 新 `migrations/000N_*.sql`，向前兼容 | 用备份恢复 |

## 7. 费用测量方法与已知预算需求

- 存储：`LOADTEST_BASELINE.json` — 100,000 事件 ≈ 130 MB SQLite（含投递日志）。按每线每集 ≤ 200 事件估：100 线 × 1 集/周 ≈ 2 万事件/周 ≈ 26 MB/周。
- 网络：每批 ≤ 500 项，典型事件 2–4 KB；`sync-status` 接口按设备给出 accepted/rejected 计数。
- 计算：单进程 SQLite 在 M1 上 1,790 事件/s；百台设备的日常上报远低于此。P95 12.6 s 的尾延迟是 100 客户端同时压测时的排队，不是日常负载。
- 评审：独立成片评审若改用外部模型，每集一次调用；本任务没有产生任何模型评审费用。
- 剧集生成额度：**零**。见 `DELIVERY_REPORT.md` 的无付费 POST 证明。

## 8. 运维检查

- `GET /v1/health`、`GET /v1/sync-status`（每设备 last_seen/accepted/rejected）、`GET /v1/failures`（隔离队列，可诊断、不含密钥）。
- 设备端：`DeviceStore.outbox_status()` → PENDING/DELIVERED/QUARANTINED 与隔离原因。
- 三项仓库验证：`python3 tools/run_portable_ci.py`、`python3 tools/deployment_code_integrity.py`、`python3 tools/knowledge_registry.py --validate`。
- 端到端复演：`python3 tools/collective_learning_demo.py --out <dir>`（见 `E2E_DEMO.md`）。
