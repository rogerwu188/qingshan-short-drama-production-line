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

1. 在运行时报告目录放 `COLLECTIVE_LEARNING_CONFIG.json`（没有此文件 = 完全关闭，所有钩子返回 `None`，生产行为字节不变；S3 模式加 `"sync": {"mode": "s3"}` 与 `"object_store": {...}` 块，见 §3b）：

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

## 3b. S3 模式（默认，2026-10-29 线主：对象存储即云端）

没有 HTTP 主机。设备把 outbox 批次写成桶里的对象，收集器把它们入库并写回执，发布者把签名后的频道指针放进桶，设备从桶取包进本地缓存。布局（全部在 `collective/<tenant>/` 下）：`trust.json`、`revocations.json`、`inbox/<line>/<device>/<kind>/<batch>.json`、`acks/<line>/<device>/<batch>.json`、`processed/…`、`quarantine/…`、`bundles/<bundle_id>/<version>.json`、`channels/<CANARY|RELEASED>.json`。

```bash
# 凭证只在环境变量（AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY），其余非密参数：
export S3CTL_ENDPOINT_URL=https://s3api.arkfs.co S3CTL_BUCKET=drama01 S3CTL_PUBLIC_BASE_URL=https://v.arkfs.co/drama01
S3SYNC=".qingshan-venv/bin/python tools/collective_learning/s3_sync.py"

# 一次：租户根（sqlite + 发布者私钥 0600 + trust）并上传 trust
$S3SYNC bootstrap --runtime-root ~/nalu_runtime --tenant nalu

# 设备（每条线的 reports 目录放 COLLECTIVE_LEARNING_CONFIG.json，含 "sync": {"mode": "s3"} 与 "object_store" 块；cron 每 10 分钟）
$S3SYNC device-sync --config <reports>/COLLECTIVE_LEARNING_CONFIG.json      # 推 outbox，拉频道包进 bundle_cache

# 收集器（同一台或任一台机器；cron 每 10 分钟）
$S3SYNC collect --runtime-root ~/nalu_runtime --tenant nalu                  # inbox → 关系库 → acks/processed
$S3SYNC status  --runtime-root ~/nalu_runtime --tenant nalu

# 发布（候选在关系库里到 CANARY/RELEASED 后）
$S3SYNC publish-channel --runtime-root ~/nalu_runtime --tenant nalu --channel CANARY --bundle-id <id> --version <n>
```

### 后台收集器（本机即发布者；launchd 用户代理，轮询 300 s）

收事件、校验、入库、把已发布版本的频道指针写回桶——都由本机后台任务做，不依赖任何聊天会话。`s3_sync.py run-cycle` 一个周期 = 读 env 文件 → 文件锁（`collector.lock`，`flock` 非阻塞，重叠即 `SKIPPED_OVERLAP`）→ `collect` → 对账频道指针（关系库 `channels` 表里有、桶里指针缺或旧的，补发签名指针）→ 写 `status.json`（`status`、`last_ok_run_at`、`backlog_inbox_batches`、`latest_bundle_versions`、`collected` 计数、`interval_s`）；日志追加到 `<runtime>/runtime/collective/logs/collector.log`，launchd 的 stdout/err 在同目录。

凭证从 **仓库外** 的 `~/nalu_runtime/runtime/collective/env`（chmod 600）读取，文件缺失或缺任一行 → `status.json` 记 `CREDENTIALS_MISSING` 并退出 2，不做任何网络访问（失败关闭）。线主需放入这 5 行（值从密钥管理取）：

```
AWS_ACCESS_KEY_ID=<drama01 access key>
AWS_SECRET_ACCESS_KEY=<drama01 secret key>
S3CTL_ENDPOINT_URL=https://s3api.arkfs.co
S3CTL_BUCKET=drama01
S3CTL_PUBLIC_BASE_URL=https://v.arkfs.co/drama01
```

```bash
# 写 plist（~/Library/LaunchAgents/com.nalu.collective-collector.plist，StartInterval 300，RunAtLoad）并加载
$S3SYNC install-agent --runtime-root ~/nalu_runtime --tenant nalu --interval 300 --python ~/nalu/.qingshan-venv/bin/python --load
launchctl print gui/$(id -u)/com.nalu.collective-collector | grep -E "state|last exit"
$S3SYNC status --runtime-root ~/nalu_runtime --tenant nalu        # collector 段 = status.json
launchctl kickstart -k gui/$(id -u)/com.nalu.collective-collector  # 立刻跑一轮
launchctl bootout   gui/$(id -u)/com.nalu.collective-collector     # 卸载
```

**身份与隔离边界（Codex 验收 A，2026-10-29）**：S3 模式所有设备共用同一把桶写凭证，**没有逐设备认证**。收集器只接受「inbox 路径里的 `<line>/<device>` = 批次正文里的 line_id/device_id」且「该 device 已由管理员登记为该 line 的 device_writer」的批次：路径与正文不一致 → 隔离（`IDENTITY_PATH_MISMATCH`，并在路径身份下写 REJECTED 回执）；一致但未登记 → 留在 inbox 不入库（`DEVICE_NOT_REGISTERED`，状态里 `held_unregistered`），管理员 `register-device` 后下一周期入库。这是允许名单与一致性检查，**不是身份证明**：拿到桶凭证的人仍可冒用已登记的身份写入；HTTP 模式下「逐设备 token、写不了别人线」的隔离结论**不适用于** S3 模式。桶公开读：上传内容全部可被任何人下载。

```bash
# 每台设备先登记（device_id 见该设备 COLLECTIVE_DEVICE_STORE.sqlite / device-sync 输出）
$S3SYNC register-device --runtime-root ~/nalu_runtime --tenant nalu --device <device_id> --line <line_id>
# 设备端后台（install-agent 只装收集器；设备同步要单独装）：
$S3SYNC install-device-agent --config <reports>/COLLECTIVE_LEARNING_CONFIG.json --env-file <凭证文件> --interval 300 --python ~/nalu/.qingshan-venv/bin/python --load
```

**投递语义（Codex 验收 B）**：上传 ≠ 送达。设备把批次写进 inbox 后条目保持 PENDING（回执状态 `IN_FLIGHT`），每次 device-sync 先看 `acks/<line>/<device>/<batch>.json`：有收集器回执才按其逐条判定 DELIVERED / 本地隔离；没有就幂等地确认对象在（同样条目 → 同一个 batch 键，不重复 PUT）。收集器把读取超时、连接错误、网关 5xx/限流 视为暂时失败：对象留在 inbox，`deferred_batches` 计数，下一周期重试；只有确定性坏数据（非 JSON、schema、身份不符、未知 kind、服务拒绝）才隔离。重启后积压继续，事件去重照旧。

**撤销传播（Codex 验收 C）**：`run-cycle` 的对账除了补发指针，还把关系库里已不在频道表的包从签名指针里移除并重签（空指针也是合法指针），并按 `revocations` 表发布签名撤销列表 `collective/<tenant>/revocations.json`；设备 `device-sync`/`S3Channel.resolve` 先校验撤销列表再解析，已撤销摘要永不被选中。**已存在的运行锁不变**（锁记录该运行用过什么），只有新运行重新解析。

**run-cycle 的范围**只有两件事：入库 inbox 批次、对账签名指针与撤销列表。归因、候选整理、评审、构包、发布仍是发布者的显式动作（`publish-channel` 等），不会自动发生。

**运行边界**：本机关机时，候选处理与新包发布暂停；已发布的包与频道指针留在公开读的桶里，设备照常下载与锁定；本机重启后 launchd 拉起代理，收集器按顺序处理 inbox 积压（幂等，重复批次记 DUPLICATE）。不需要另一台服务器。

S1 仍只读本地缓存（`line_upgrade_gate.collective_preflight` 回执多一项 `sync_mode`），付费任务前没有任何云端等待；桶不通只意味着事件留在 outbox、设备继续用已锁定的本地包。桶公开读：上传前每个条目过 `sensitive_findings`，命中即 REJECTED 不上传；收集器隔离说明里的异常文本若含敏感片段会被脱敏。

## 3a. 对象存储（已定：自建 S3，MinIO / JuiceFS Gateway）

线主 2026-10-29 决定：所有生产线统一接入同一个自建 S3；对象存储不再是待授权项。

| 参数 | 值 | 来源 |
|---|---|---|
| Endpoint | `https://s3api.arkfs.co`（443） | 配置文件 / `AWS_ENDPOINT_URL` |
| Bucket | `drama01` | 配置文件 / `COLLECTIVE_OBJECT_BUCKET` |
| Region | `us-east-1` | 配置文件 / `AWS_DEFAULT_REGION` |
| 签名 / 寻址 | `s3v4`，path-style（`s3ForcePathStyle=true`） | 代码默认 |
| 公网下载 | `https://v.arkfs.co/drama01/<object-key>`（匿名可读，CloudFlare，支持 Range） | `public_base_url` |
| AccessKey / SecretKey | **只从环境变量读取**：`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`（放 `~/nalu/.env`） | 密钥管理，不写代码、不写文档、不写配置文件 |

**整个 bucket 公开读**：任何上传对象任何人都能下载，链接永久有效。因此代码里的正式上传路径（`ObjectStore.put_artifact`）对文本/JSON 负载与元数据跑 `sensitive_findings`，发现本机路径、签名 URL、密钥即拒绝；媒体类型（video/image/audio）在共享代码里默认拒绝，只有该线配置 `allow_media: true` 才放行。线主 2026-10-29 已决定 nalu 线允许上传成片切片与关键帧（`AUTHORIZATIONS_REQUIRED.md` §C），并知悉这些对象公开可读；完整剧本、人脸/声音参考、密钥、本机路径仍永远不上传（`sensitive_findings` 门不受此开关影响）。

兼容性与限制：标准 PUT/GET/HEAD/List/Delete/Multipart 可用；**不支持** Object Lock、Versioning、Object Tagging、Glacier 存储类。代码永不调用这些 API（`object_store.UNSUPPORTED_OPERATIONS` 列出，测试扫描源码），重命名用 copy+delete（`ObjectStore.rename` / `aws s3 mv`）。

对象命名：`<line>/<batch_id>/<artifact>`，全小写英文、无空格、不以 `/` 开头（`object_store.object_key` 强制，大写自动转小写，非法字符拒绝）。例：`nalu/e13/reports/digest.json`、`qingshan/e50/…`。云端服务镜像的知识包用 `collective/<tenant_id>/bundles/<bundle_id>/<version>.json`。`<line>/_preflight/` 保留给预检对象，正式路径不能写入。

### 预检（先过预检，再接正式路径）

```bash
# 凭证只在环境里（或 ~/.aws 的 profile drama01）；本命令不打印密钥
export AWS_ACCESS_KEY_ID=<从密钥管理取>  AWS_SECRET_ACCESS_KEY=<从密钥管理取>
export AWS_ENDPOINT_URL=https://s3api.arkfs.co AWS_DEFAULT_REGION=us-east-1
python3 tools/collective_learning/object_store.py --line nalu \
  --endpoint-url https://s3api.arkfs.co --bucket drama01 --region us-east-1 \
  --public-base-url https://v.arkfs.co/drama01 \
  preflight --receipt <runtime>/reports/COLLECTIVE_OBJECT_STORE_PREFLIGHT.json --verify-public
```

预检 = PUT 1 KB 随机对象到 `<line>/_preflight/` → GET 比对字节 → （`--verify-public`：经公网域名再下载比对）→ DELETE → HEAD 确认已删。回执 `COLLECTIVE_OBJECT_STORE_PREFLIGHT.json` 记录每步耗时与错误码（PASSED/FAILED），不含密钥。`put_artifact` 要求同 endpoint/bucket/line 的 PASSED 回执且不超过 24 h（`preflight_max_age_s`），否则 `PREFLIGHT_REQUIRED`。预检是运维命令，不在流水线 S1 里跑：付费任务前没有云端等待。

设备端配置（`COLLECTIVE_LEARNING_CONFIG.json` 新增可选块，不写密钥）：

```json
"object_store": {"endpoint_url": "https://s3api.arkfs.co", "bucket": "drama01", "region": "us-east-1",
                 "public_base_url": "https://v.arkfs.co/drama01", "allow_media": true, "profile": "drama01"}
```

云端服务：`Service(db, object_store=ObjectStore.from_env(cfg, line_id="collective"))` 后，`POST /v1/bundles` 在数据库提交后把包字节镜像到对象存储，响应与 `audit_log` 带 `object_mirror`（MIRRORED / MIRROR_FAILED / NOT_CONFIGURED）；数据库始终是事实源，镜像失败不会让上传失败。证据字节：`object_store.upload_evidence(store, batch_id=…, artifact=…, data=…, content_type=…, register=svc.register_evidence 绑定)` 先 PUT 再登记 `storage_key + sha256`，登记元数据里没有 URL。

### s3ctl（统一命令行，不用 AWS CLI）

线主 2026-10-29 决定不装 AWS CLI；所有生产线用 `tools/s3ctl.py` 操作对象存储。它只是 `object_store.py` 的薄封装：同样的键名规则、同样的预检门、同样的公开读防泄露门，每条命令输出一个 JSON，成功退出 0，拒绝/失败退出 2。

```bash
# 一次性放进 ~/nalu/.env（已 gitignore；密钥只在这里）：
#   AWS_ACCESS_KEY_ID=<从密钥管理取>
#   AWS_SECRET_ACCESS_KEY=<从密钥管理取>
#   S3CTL_ENDPOINT_URL=https://s3api.arkfs.co
#   S3CTL_BUCKET=drama01
#   S3CTL_PUBLIC_BASE_URL=https://v.arkfs.co/drama01
#   S3CTL_RECEIPT_DIR=<runtime>/reports        # 预检回执落在这里
S3=".qingshan-venv/bin/python tools/s3ctl.py"
$S3 config                                   # 看生效配置与凭证是否解析到（不打印密钥）
$S3 preflight nalu --verify-public           # 先过预检；回执 S3CTL_PREFLIGHT_nalu.json
$S3 ls nalu/e13/
$S3 put ./out/digest.json nalu/e13/reports/digest.json
$S3 sync ./out/ nalu/e13/reports/            # 同大小跳过，--force 全覆盖；非法文件名列在 refused
$S3 get nalu/e13/reports/digest.json ./digest.json
$S3 head nalu/e13/reports/digest.json
$S3 url nalu/e13/reports/digest.json         # 公网链接
$S3 mv nalu/e13/a.json nalu/e13/b.json       # copy + delete，不能跨线
$S3 rm nalu/e13/a.json ; $S3 rm nalu/e13/tmp/ --recursive --yes
```

`put`/`sync` 走正式路径：没有当天的 PASSED 预检回执 → `PREFLIGHT_REQUIRED`；JSON/文本里有本机路径、签名 URL、密钥 → `UPLOAD_REFUSED`；video/image/audio 需要 `--allow-media`（或 `S3CTL_ALLOW_MEDIA=1`）。2026-10-29 已对真实网关跑过完整序列（preflight → put → ls → url → get 字节一致 → mv → rm --recursive → ls 为空，公网 404），测试 `tools/tests/test_s3ctl.py`。

boto3 等价：`boto3.client('s3', endpoint_url='https://s3api.arkfs.co', region_name='us-east-1', config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}))`（`object_store.make_client` 就是这一行，凭证来自 `resolve_credentials`）。

## 4. 备份与恢复

- 云端：`sqlite3 collective.sqlite ".backup /backup/collective-$(date -u +%Y%m%dT%H%M%SZ).sqlite"`（WAL 模式下在线备份安全）。恢复 = 停服务、换文件、起服务；`test_collective_service` 的 T26 用例验证重开同一文件后凭证、证据状态、包与通道、审计日志一致。
- 设备端：`reports/COLLECTIVE_DEVICE_STORE.sqlite` 同样 `.backup`；outbox 状态随库一起恢复，未送达项恢复后继续送（T08）。
- 发布包缓存 `bundle_cache/` 是内容寻址的，可随时从云端 `GET /v1/bundles/{id}/versions/{v}` 重拉；丢失缓存不丢锁（锁里有 digest，重拉后校验相同）。
- 证据对象：元数据在库里；字节在对象存储（§3a，已接入；预检回执在运行时目录）。删除证据后相关候选自动变 `EVIDENCE_UNAVAILABLE` 并失去推广资格，恢复数据库不会把它变回"证据齐全"。

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
