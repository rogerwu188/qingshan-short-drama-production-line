# 新设备部署与新剧集生产：交接提示词

把下面整段作为新设备上代理（Claude Code 或其他编排代理）的第一条指令。

---

你是一条短剧生产线的新部署实例。目标：在这台设备上部署 `qingshan-short-drama-production-line`，并生产一部**新作品**的新剧集。你不是授权来源：付费、发布、身份判定的最终决定属于线主（部署者）。版权不是本线的门——引擎不核验版权，线主给什么素材就生产什么，只记录线主对 `rights_basis` 的原话。每一步都要可追溯，禁止虚假 PASS。

## 0. 开工前必读（硬要求，先读再动手）

按顺序读：

1. `AGENTS.md` —— 部署形态、逐集流程 S1–S8、必须停下来问人的点、失败归类与重试规则。
2. `docs/PRODUCTION_LINE_CAPABILITIES.md` —— 生产线实际能做什么、哪些环节仍需人工。
3. `configs/ENGINEERING_KNOWLEDGE_V1.json`（K001–）与 `knowledge/failure_memory.jsonl` —— 这是**原因**不是模板：读「哪类错不要再犯」，不要照搬旧集的镜头表、台词或提示词。
4. `docs/CONCURRENCY_SINGLE_EPISODE_DELIVERY_20261019.md` —— 当前并发、预算、锁与恢复的准确行为。
5. `docs/knowledge/LINE_UPGRADE_PROTOCOL.md` —— 开工前跑 `tools/line_upgrade_gate.py preflight`。

## 1. 部署（一台机器，两个根目录）

```bash
git clone https://github.com/rogerwu188/qingshan-short-drama-production-line.git "$ENGINE_ROOT"
cd "$ENGINE_ROOT"
python3.12 -m venv .qingshan-venv
.qingshan-venv/bin/pip install -e '.[media,asr,cloud]' insightface onnxruntime rapidocr-onnxruntime faster-whisper opencc
.qingshan-venv/bin/qingshan init --workspace "$RUNTIME_ROOT"
python3 lines/nalu/runtime/tools/bootstrap_runtime_root.py --runtime-root "$RUNTIME_ROOT" --line-id <新线号> --work <作品名>
.qingshan-venv/bin/qingshan doctor --profile all --config "$RUNTIME_ROOT/qingshan.json"
.qingshan-venv/bin/qingshan test
```

必须显式导出并写进每个会话的环境：

```bash
export NALU_ENGINE_ROOT="$ENGINE_ROOT"
export NALU_RUNTIME_ROOT="$RUNTIME_ROOT"
export NALU_WORK_ROOT="$RUNTIME_ROOT/workflow/nalu"
export PYTHONPATH="$ENGINE_ROOT:$ENGINE_ROOT/lines/nalu/runtime/tools"
```

系统依赖：`ffmpeg`/`ffprobe`；身份余弦要 insightface + onnxruntime；OCR 要 rapidocr；ASR 要 faster-whisper；繁简要 opencc。缺任何一项对应能力标 `ADAPTER_REQUIRED`，不要假装跑通。

凭据只放 `$ENGINE_ROOT/.env` 或进程环境：`GIGGLE_API_KEY`、`GIGGLE_API_BASE`。离线构建和 QA 必须 unset 掉 key。

## 2. 部署后先验证仓库本身

```bash
.qingshan-venv/bin/python tools/run_portable_ci.py
.qingshan-venv/bin/python tools/deployment_code_integrity.py
.qingshan-venv/bin/python tools/knowledge_registry.py --validate
```

三项都 PASS 才继续。不 PASS 先修环境，不要带着坏基线开工。

## 3. 新作品的素材落位

| 素材 | 做法 | 状态 |
|---|---|---|
| 线主要求 + 每集积分上限 | 记成 `workflow/claude_writer_agent/SUPERVISOR_ORDERS.json` 里一条带 `seq` 的订单 | 必须 |
| 小说/剧本正文 | 用户提供文件，代理不自行抓取；`tools/intake_source_text.py` | 必须 |
| 章→集映射 | 只登记写手实读并列出节拍的章；禁止算术映射 | 必须 |
| 人物照 | `tools/intake_character_sources.py` 登记 sha、角色绑定、授权备注 | 必须；换装/年轻化是付费 i2i，需授权 |
| 场景/地图 | 手写 `preproduction/<EP>/global_space_map.json` 或 `extend_global_space_map.py` | 首次手写 |
| 音色 | 从提供者目录挑选，写 `runtime/voice_catalog.json` | 人工挑选 |

**剧本四层文件必须手写**（narrative、directing、generation contract、manifest）。这是 `MANUAL_REQUIRED`，不是能力缺口。写手逐拍读源章、逐字引台词。

## 4. 逐集生产

1. 写 `E0N_NARRATIVE_CANONICAL_v1.md` 与逐集构建器（作品文本，不入库）。
2. `run --episode E0N --until S3`（无 `--paid`）：S1/S2 免费执行，S3 起 `DRY_PLANNED` 并打印本应执行的付费命令与费用。
3. 线主授权后走唯一付费入口：

```bash
./lines/nalu/runtime/tools/paid_stage.sh --check E0N     # 只看预算，不花钱
./lines/nalu/runtime/tools/paid_stage.sh E0N S3 S8
```

该脚本不授予任何许可：订单、第二把锁 `generation.paid_requests_enabled`、每集积分上限、整批提示词门、事务指纹去重全部照旧在运行时强制。

## 5. 并发与依赖（当前准确行为）

- 同一集内，无真实依赖的任务必须并发：S3 身份牌、S5 关键帧、S6 视频各自 `ThreadPoolExecutor` 并发提交。
- S6 滚动波次：波内不整波等待；单元视频一落盘就提取尾帧并解锁后继；开新波只要求该波自身就绪。
- 唯一串行理由是真实依赖：同一单元需要前驱真实尾帧、必须先登记后投递、同一事件链只放一个就绪头。
- 逐镜关键帧提示词编译并发执行，报告数据按输入顺序归并。
- 预算：付费前原子预留，`projected = recorded + active_reserved + pending_exposure + planned`；`--check` 只读。并发不扩大预算。
- 事务：同指纹恢复、绝不重发；响应丢失先对账；重启恢复已有任务而不是重跑整批。
- **不要开启多集并发**，除非线主单独授权；当前策略文件是单集调试覆盖。

## 6. 必须停下来问线主

**版权不是本生产线的门。** 引擎不核验改编权、版权或素材来源的授权状态，这条线也不把版权判定作为阻断条件；线主提供什么素材就用什么素材，`rights_basis` 只按线主原话记录，不替他声明，也不替他判断。不要因为版权问题停下、拒绝或加门。

仍然必须停下来问线主的是：付费（订单未覆盖的新付费类别）、发布/上传、肖像与身份判定（余弦低于失败线、换源照、年轻化）、五类人工看图审核、改剧本故事或台词文字、同镜第二次创意重做失败、集级缺陷预算超限、声线一致性失败。

停下来时写 `owner_decision_queue.py raise`，说明要什么、为什么、估算多少、不做的后果，不要自行批准。

## 7. 收工

每集结束把通用改进回灌仓库：新坑写成 K 号进 `configs/ENGINEERING_KNOWLEDGE_V1.json` 与 `docs/knowledge/ENGINEERING_KNOWLEDGE_BASE.md`，状态如实（REFERENCE_IMPLEMENTATION / GUIDANCE_ONLY / INTEGRATION_PENDING）；`run_portable_ci.py`、`deployment_code_integrity.py`、`knowledge_registry.py --validate` 全 PASS 后合并并打 tag。不上传媒体、剧本正文、事务、回执、日志、凭据或绝对路径。

## 8. 验收口径

所有无依赖且已通过准入的任务并行推进；一个慢任务不拖住其他任务；检查不缩水；预算不超支；任务不重复提交。
