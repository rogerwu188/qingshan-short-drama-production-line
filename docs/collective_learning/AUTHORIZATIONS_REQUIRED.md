# 需要线主决定的事项（集中列出）

需求 §16 规定：只在下列四类事项上集中提出决策；其余本地代码、模拟服务与测试照常推进。
本文件是唯一的授权清单；每项标注「缺它阻塞什么」与「不缺它已完成什么」。

## A. 云部署目标、账户、域名、凭证

| 事项 | 缺它阻塞 | 不缺它已完成 |
|---|---|---|
| 云端运行位置与域名 | **不需要：S3 即云端（2026-10-29 线主）**。设备只与对象存储通信（`s3_sync.py device-sync`），关系库跟随收集器（`s3_sync.py collect`）跑在任一台能读环境变量凭证的机器上；HTTP 服务代码保留为可选模式 | S3 模式对真实桶完整闭环通过（`DELIVERY_REPORT.md` §S3 模式）；nalu 租户已在本机 bootstrap（`~/nalu_runtime/runtime/collective/`，trust 已上传 `collective/nalu/trust.json`） |
| 管理员根凭证 | **已自动生成**：`s3_sync.py bootstrap` 在 `<runtime>/runtime/collective/admin.token`（0600，不入库）；S3 模式下设备不需要 token，收集器按批次对象里的 device/line 身份入库 | 本机已生成（tenant `nalu`） |
| 发布者签名私钥（Ed25519） | **已自动生成**：`<runtime>/runtime/collective/publisher.key.json`（0600，不入库，key_id `pub-nalu`）；公钥在 `trust.json` 并已上传到桶，设备从桶取 trust | 本机已生成；换钥用 `bootstrap --rotate-key` |
| 对象存储（证据与发布包） | **已决定（2026-10-29）**：自建 S3 `https://s3api.arkfs.co` / bucket `drama01` / us-east-1，所有生产线共用，按 `<line>/<batch_id>/<artifact>` 分前缀。见 `DEPLOYMENT_OPERATIONS.md` §3a。密钥只走环境变量。 | `object_store.py`：预检（PUT/GET/DELETE/验证）、线前缀命名、仅标准 API、公开读防泄露门、包镜像、证据上传与登记；本机对真实网关的预检结果见交付报告 |
| TLS 终止方式 | 公网暴露 | 服务只监听 127.0.0.1；文档要求反向代理终止 TLS |

## B. 预算：新云资源、付费评审、新增生成实验

| 事项 | 缺它阻塞 | 不缺它已完成 |
|---|---|---|
| 云端主机 + 数据库 + 对象存储月费 | 真实部署 | 费用测量方法：`service.py` 记录每批次字节数与行数；`LOADTEST_BASELINE.json` 给出每 10 万事件的存储增量，可按设备数外推 |
| 独立模型评审费用（成片 DIRECTOR_SCORE 独立评审每集一次） | 独立评审的真实运行（现由会话内 Claude 评审员填写，不额外计费） | 评审答案格式、盲评包、覆盖证明已实现；无预算时用会话内评审员 |
| 小范围试用需要的新增付费生成（§9） | 创作类候选的 CANARY 实证 | 工程不变量类候选用免费编译回放验证；创作类候选停在 VALIDATED(STRUCTURE/DETERMINISTIC) 不进 CANARY |
| 试点剧集生成额度 | 真实 `OUTCOME_OBSERVED` 回执 | 演示中保持待观察（`outcome_observed=false`），不用模拟视频冒充 |

**本任务未动用任何剧集生成额度，没有向任何付费接口 POST**（见 `docs/collective_learning/DELIVERY_REPORT.md` 的无付费 POST 证明）。

## C. 私有素材上传与可见范围

| 事项 | 默认 | 需要决定 |
|---|---|---|
| 结构化脱敏经验（症状、门名、sha、时间码） | 自动上传（visibility=LINE） | 是否放宽到 TENANT |
| 完整剧本、原始人脸/声音参考、私人媒体、签名 URL、API 密钥、本机绝对路径 | **不上传**（设备端 `sensitive_findings` 拒绝进入 outbox） | 无 |
| 成片片段作为证据（时间码对应的 2–6 s 切片） | **已决定（2026-10-29，线主：「上传」）**：允许。nalu 线配置 `allow_media: true`；共享代码默认仍 `false`，每条线自行开启 | 保存期限未定（`retention_until` 由上传方填）。**线主已知悉：bucket 整体公开读，上传的切片任何人永久可下载** |
| 缩略总表 / 关键帧 | 同上：允许（2026-10-29） | 同上（公开读） |
| 《夜无疆》nalu 线的事件是否可被其它租户的线检索 | 否（租户隔离） | 无 |

## D. 发布权限、试用范围、既有付费授权

| 事项 | 默认 | 需要决定 |
|---|---|---|
| 谁是发布者（publisher 角色） | 无人；候选停在 VALIDATED | 指定一个人/账户 |
| 低风险类别的条件式自动推广 | 关闭（首版维护者确认） | 以后再议 |
| 试点生产线 | 仅 nalu 线新运行（新批次才带知识锁） | 扩大到 Codex 线需另行决定 |
| 既有付费授权 | **不变**：`--paid` + `paid_requests_enabled` 两把锁、每集上限、同指纹不重发 | 无（本系统不新增也不放宽任何付费条件） |

## 不需要决定、已自行处理

- 接口命名、路由、错误码、测试组织（见 `openapi.json`、各测试模块）。
- 在制剧集零影响：所有新接线只在运行带知识锁时生效。
- E11/E12 的状态、合同、媒体、交易记录、预算未被触碰（独立 worktree）。
