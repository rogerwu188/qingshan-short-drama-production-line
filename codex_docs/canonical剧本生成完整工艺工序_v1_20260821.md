# Canonical 剧本生成完整工艺工序 v1

版本：`1.0.0`
日期：`2026-08-21`
审核状态：`PENDING_ROGER_REVIEW`
适用范围：E41 起新写、重写及尚未锁定的剧本；E40 和已绑定生产任务不追溯改写。
叙事节奏授权：`ROGER-20260821-NARRATIVE-CANONICAL-CAUSAL-V3`

---

## 0. 本文的目的

本文定义从“接到一集编剧任务”到“锁定唯一剧情事实源”的完整工艺、工序、责任边界、输入输出、状态、门禁和失败处理，供 Roger 或外部 AI 逐项审核。

本文只定义 canonical 剧本生成。关键帧、视频、声音、剪辑和发行属于后续层，不得反向污染剧情 authority。

---

## 1. 当前接入的 Writer 到底是谁

### 1.1 角色定义

当前生产线登记的 canonical Writer 是：

- 本地 Agent ID：`qingshan-claude-writer-agent`
- 本地宪章声明运行体：`Claude / Fable 5`
- 本地主备关系：本地 Writer 为主，StoryClaw Writer 为备
- 云端 Agent ID：`qingshan-claude-writer`
- 云端 logical agent：`factory.writer.v1`
- 云端角色：`canonical_writer`
- 云端 roster 模型：`storyclaw/claude-opus-4-8`
- 云端权限：只写 `writer / authority`，不能花生成积分，不能发行

从 E29 起的项目规则把 Claude Writer 版定义为唯一 canonical 剧本源。Codex 不是当前登记的 canonical Writer。

### 1.2 Codex 的实际职责

Codex 当前负责：

- 生产主管与依赖图推进；
- 编剧规则、schema 和注册门的代码实现；
- Writer 产物的 SHA、门禁和下游绑定；
- 生产、后期、QA、发行及 GitHub 代码同步；
- 收到 Roger 明确修改剧本指令时，执行被授权的修订。

因此，“规则由 Codex 写入生产线”不等于“canonical 剧本默认由 Codex 创作”。

### 1.3 当前可审计性缺口

现有文件能证明 Writer 的**角色定义是 Claude**，最近 `PROGRESS.json` 也记录本地 Writer 自动轮；但当前本地路径没有统一的 Writer 调用器强制保存以下运行证据：

- 实际 provider；
- 实际 model ID；
- conversation/session/task ID；
- 提交时间、完成时间；
- 输入包 SHA；
- 输出原始响应 SHA；
- 宪章与规则包 SHA。

所以目前不能仅凭目录名 `claude_writer_agent`，对任意历史剧本做密码学意义上的“确由某个 Claude 型号生成”证明。

审核结论应区分：

1. **设计身份**：明确是 Claude Writer；
2. **当前操作事实**：本机 Claude 应用和 Writer 自动状态存在；
3. **单份产物的模型溯源**：尚缺强制 receipt，不能完全证明。

### 1.4 禁止双写

- 同一集同一版本只能有一个 `writer_run_id` 和一个写锁持有者。
- 本地主写时，云端必须待命；云端接管时，本地必须退回待命。
- Codex 不得在 Claude Writer 已持锁时并行生成另一份同版本 canonical。
- 监制建议只能形成修订请求，不能直接覆盖已锁 authority。

---

## 2. 权威分层

每集必须依次生成四件套：

1. `E{NN}_NARRATIVE_CANONICAL_v{n}.md`
   - 唯一剧情事实源；
   - 只包含剧情、角色行动、外部变化、必要对白和集尾新状态。
2. `E{NN}_DIRECTING_SCRIPT_v{n}.md`
   - 从 narrative authority 派生；
   - 包含镜头、表演、声音、节奏和剪辑设计。
3. `E{NN}_GENERATION_CONTRACT_v{n}.json`
   - 从导演稿派生；
   - 包含资产、空间、关键帧、动作轨迹、模型和提交字段。
4. `E{NN}_manifest_v{n}.json`
   - 固定三层路径、SHA、story move DAG、版本和依赖。

旧文件 `E{NN}剧本_ClaudeWriter_v{n}.md` 只能作为导演稿兼容名，不能继续同时承担 narrative canonical、导演稿和生成合同。

### 2.1 Narrative canonical 禁止内容

以下内容不得进入 narrative authority：

- 景别、机位、镜头焦段、运镜；
- `shot_treatment`；
- 首帧动势和关键帧提示词；
- `ambient_life` 生成说明；
- palette、灯光模型参数；
- 角色图片、道具图片和空间地图引用；
- `GLOBAL-SPACE-MAP-ID / SUBSPACE-ID`；
- 动作轨迹和视频时间窗口；
- 声线 ID、TTS、BGM、音效分层；
- 图片或视频模型名；
- 正向/负向提示词；
- QA 自检、门结果和生产注记。

---

## 3. 输入合同

Writer 开工前必须拿到一个 `WRITER_INPUT_BUNDLE`，至少包含：

### 3.1 项目级输入

- 原著全文或本集对应章节；
- 原著 ingest manifest 与 SHA；
- canon facts；
- 83 集信息节点总表；
- 全剧角色弧、谜底和结局锁；
- 角色表演圣经；
- 时代、世界观、能力归属规则；
- 已注册的项目特殊口径，例如“乌云=当前棕色虎斑猫”。

### 3.2 相邻集输入

- 上一集锁定 narrative canonical 与 SHA；
- 下一集已锁事件锚或不可冲突条件；
- 观众已知清单；
- 尚未回收的伏笔；
- 上集终态和本集必须达到的终态；
- 最近已发布集的有效观众反馈；
- 不得重复的信息和场面。

### 3.3 任务级输入

- episode ID；
- 目标时长；
- 版本号；
- `writer_run_id`；
- writer Agent ID、provider、model ID；
- 输入 bundle SHA；
- 授权范围；
- 是否新写、局部修订或整集重写；
- 允许改动的 canon 范围；
- 截止条件和审核人。

### 3.4 输入准入

缺任一必要输入时不得靠猜测补齐。状态应为：

- `BLOCKED_SOURCE_MISSING`
- `BLOCKED_PREVIOUS_EPISODE_NOT_LOCKED`
- `BLOCKED_CANON_CONFLICT`
- `BLOCKED_WRITER_PROVENANCE_MISSING`
- `BLOCKED_WRITE_LOCK_UNAVAILABLE`

---

## 4. 状态机

合法状态如下：

```text
DISPATCHED
  → INPUT_ADMITTED
  → SOURCE_BOUND
  → CONTINUITY_SNAPSHOT_LOCKED
  → TERMINAL_CHANGE_LOCKED
  → STORY_MOVE_DAG_DRAFTED
  → NARRATIVE_DRAFTED
  → MANIFEST_BOUND
  → SCRIPT_GATES_RUNNING
  → REVISION_REQUIRED | CANONICAL_ADMITTED
  → CANONICAL_LOCKED
  → DIRECTING_DERIVATION_ALLOWED
```

禁止跳过状态。`NARRATIVE_DRAFTED` 不等于 `CANONICAL_LOCKED`，门通过前下游不得引用。

---

## 5. 完整工艺工序

## 工序 C00：派单与写锁

执行者：生产主管。
输入：任务卡、当前 work queue、Writer 状态。
动作：

1. 确认 episode、版本、授权范围；
2. 确认没有同集同版本的本地/云端双写；
3. 生成唯一 `writer_run_id`；
4. 记录 Agent ID、provider、model ID 和规则包 SHA；
5. 持久化写锁。

产物：`E{NN}_WRITER_RUN_RECEIPT_v{n}.json`。
通过条件：写锁唯一，模型与输入包均可追溯。

## 工序 C01：源材料绑定

执行者：Writer。
动作：

1. 读取原著对应区间；
2. 读取 canon facts、章节 beat map 和全剧事件图；
3. 将本集允许使用的事实、人物、地点、能力和道具列入 source ledger；
4. 将每项事实绑定源文件路径、SHA 和定位；
5. 标记原著明确事实、项目改编事实、Roger 明确覆盖项。

禁止：依靠模型记忆补原著；把未经授权的新设定写成 canon。

对应注册门：

- `SOURCE-READ-COMPLETENESS`
- `SCRIPT-SOURCE-CANON-BINDING`
- `FULL-SERIES-SOURCE-FIDELITY`

## 工序 C02：连续性快照

执行者：Writer。
动作：

1. 读取上一集结尾的角色、地点、道具、关系和信息状态；
2. 读取观众已知清单；
3. 读取 E±1 的已锁承接；
4. 列出本集开场不可违反的状态；
5. 列出本集不能重复证明的信息；
6. 列出必须回收或推进的线。

产物：`continuity_snapshot`，进入 manifest，不进入剧情正文。

## 工序 C03：锁定本集不可撤销终局变化

执行者：Writer。
先写一句话：

> 到本集结束，哪个外部状态已经改变，导致下一集无法回到本集开场？

终局变化必须至少属于一种：

- 权力转移；
- 关系改变；
- 不可撤销行动；
- 被迫选择；
- 重大事实公开并立刻改变行动条件；
- 已铺设承诺的兑现。

纯“发现了更多线索”“更加怀疑”“气氛更危险”不构成合格终局变化。

## 工序 C04：建立 8–12 个候选 story move

执行者：Writer。
每个候选必须包含：

- `story_move_id`
- `causal_cluster_id`
- `move_type`
- `cause_state_token`
- `action`
- `external_change`
- `result_state_token`
- `predecessor_move_ids`
- `forces_next_story_move_id`

允许类型：

- `IRREVERSIBLE_ACTION`
- `POWER_SHIFT`
- `RELATIONSHIP_SHIFT`
- `FORCED_CHOICE`
- `MATERIAL_FACT`
- `PAYOFF`

合并规则：同一调查链、同一因果簇只能计一次。看见、判断、确认、解释和情绪反应不能分别刷成多个 move。

## 工序 C05：因果 DAG 编译

执行者：Writer。
动作：

1. 从终局变化向前倒推；
2. 确认每个非首 move 有具名前驱；
3. 确认其 `cause_state_token` 来自某个前驱的 `result_state_token`；
4. 确认除终局外每个 move 都逼出后续 move；
5. 删除没有改变外部状态的节点；
6. 合并重复 causal cluster；
7. 防止连续两个 discovery/payoff；
8. 确保 agency 型 move 不少于 50%。

硬线：150 秒至少 8 个真实推进，即至少 `3.2/min`。

## 工序 C06：场景分配

执行者：Writer。
先有 story move，再有场景。场数不得反向决定剧情数量。

每场必须有：

- 稳定 `scene_id`；
- 稳定 `LOC-*`；
- 稳定 `TIME-*`；
- `thread_id`；
- 一个或多个 `story_move_id`；
- 开场状态；
- 角色行为；
- 外部变化；
- 场尾 button。

同一建筑内的案边、帘后、门口不是新 location。场数、地点数、时间跳跃数和 cross-cut 数只作诊断，不能证明节奏快。

## 工序 C07：写 story-only narrative canonical

执行者：Writer。
写作原则：

- 进入尽可能晚，离开尽可能早；
- 只保留可表演的行为和必要对白；
- 解释必须被行动打断或立刻改变行动；
- 同一事实只让观众学会一次；
- 每场结束时局势必须不同；
- 每个场尾必须给下一场施加压力；
- 集尾形成新局面，不只抛一句悬念话。

正文可见字符不得超过 `1400/min`；150 秒不得超过 3500 个可见字符。

## 工序 C08：正文与 story move 逐字绑定

执行者：Writer。
对每个 story move，从真实 narrative 正文截取恰好出现一次的 `evidence_text`。禁止 manifest 自述一个正文里不存在的事件。

要求：

- evidence 必须逐字匹配；
- 每条 evidence 在正文中只出现一次；
- move 的 scene ID 必须与 scene sequence 一致；
- scene 上声明的 move 集合必须与 move 反向引用一致。

## 工序 C09：锁正文 SHA，生成 manifest

执行者：Writer。
顺序：

1. 写完 narrative 文件；
2. 计算 SHA-256；
3. 将路径和 SHA 写入 manifest；
4. 写入完整 `narrative_canonical` 结构；
5. 写入 Writer provenance；
6. manifest 自身再计算 SHA。

任何正文改动都会使旧 manifest 失效，必须重新计算 SHA 和重跑全部脚本门。

## 工序 C10：统一脚本门

执行者：生产线 stage runner。
唯一入口：`tools/episode_stage_gate_runner.py --phase script`。

正式 script phase 包含：

1. `SCRIPT-SOURCE-CANON-BINDING`
2. `FULL-SERIES-SOURCE-FIDELITY`
3. `SCRIPT-READINESS-EXCITEMENT-SHA`
4. `SCRIPT-US-DRAMA-EVENT-DENSITY`
5. `SCRIPT-COUNCIL-DRAMATIC-QUALITY`
6. `SCRIPT-SCENE-DIVERSITY-PREFLIGHT`
7. `MECHANICAL-DEFAULT-META-GATE`
8. `COMMON-SENSE-CAUSALITY-COUNTERFACTUAL`
9. `PERIOD-ANACHRONISM-LOCK`

所有门必须：

- 从注册表读取 gate authority；
- 绑定同一 canonical script SHA；
- 保存 `invoked=true` 和真实输出；
- 没有证据时 fail closed；
- 不允许临时 harness 冒充注册门；
- 不允许某一个 PASS 代替整个 script phase PASS。

## 工序 C11：失败归因和修订

执行者：Writer；生产主管只路由，不代写未授权内容。
修订应针对失败类型：

- `NARRATIVE_CANONICAL_CONTRACT_MISSING`：补独立 authority 和 manifest 合同；
- `NARRATIVE_CANONICAL_SHA_MISMATCH`：重新绑定真实正文；
- `CAUSAL_CLUSTER_FRAGMENTED`：合并同一调查链；
- `STORY_MOVE_CAUSE_STATE_NOT_FROM_PREDECESSOR`：修正因果状态交接；
- `CONSECUTIVE_DISCOVERY_CHAIN_TOO_LONG`：让发现立即触发行动，或删除解释；
- `AGENCY_MOVE_RATIO_BELOW_MINIMUM`：改为主动出招、反制、交换、背叛或选择；
- `STORY_MOVE_EVIDENCE_NOT_EXACTLY_ONCE`：修正正文证据；
- `NARRATIVE_CANONICAL_TEXT_BLOAT`：删除复述、说明、冗余表演和生产元数据；
- `PRODUCTION_METADATA_INSIDE_NARRATIVE_CANONICAL`：移到导演或 generation 层；
- source/canon 失败：回到源材料，不得只改措辞骗过门；
- common-sense 失败：修复因果，而不是增加解释台词；
- period 失败：修复剧情中真实时代错误；生成模型幻觉不应反改剧本。

修改后回到 C08，重新绑定正文证据和 SHA，再运行整个 script phase。

## 工序 C12：Canonical admission 与锁定

执行者：具备 authority admission 权限的主管/审计角色。
必须同时满足：

- 九个 script gates 全部实际执行；
- 所有阻断门 PASS；
- 路径和 SHA 一致；
- Writer provenance receipt 完整；
- 没有未裁决 canon 冲突；
- 没有本地/云端双写冲突；
- 上下集依赖已经固定。

产物：`E{NN}_CANONICAL_ADMISSION_v{n}.json`。
状态：`CANONICAL_LOCKED`。

锁定后禁止静默覆盖。任何内容改动必须升版本，并声明 `supersedes`、变更理由和受影响下游。

## 工序 C13：派生导演稿

只有 `CANONICAL_LOCKED` 后才允许执行。

导演稿可以增加：

- 镜头结构；
- 表演和微表情；
- 声音事件；
- 打斗回合与剪辑点；
- 场景气氛；
- 首帧动势；
- 选择性 BGM 意图。

不得新增或改变 canonical 事实。若导演设计发现剧情不可拍，必须发回 Writer 升版，不能在导演稿里偷偷改剧情。

## 工序 C14：派生生成合同并移交 Pipeline

只有导演稿绑定 canonical SHA 后才允许生成 generation contract。

该层才加入：

- 原生资产 registry；
- 整集全局空间地图；
- 子空间和人物/道具站位；
- 关键帧合同；
- 动作轨迹；
- 图片/视频模型适配；
- 多模态原声策略；
- QA 与付费提交字段。

Pipeline 只能读取 `CANONICAL_LOCKED` 的 SHA，不得读取未锁草稿。

---

## 6. Manifest 最小结构

```json
{
  "episode": "E41",
  "runtime_target_seconds": 150,
  "writer_provenance": {
    "writer_run_id": "WRITER-E41-V5-...",
    "agent_id": "qingshan-claude-writer-agent",
    "provider": "anthropic-or-storyclaw",
    "model_id": "exact-model-id",
    "session_or_task_id": "provider-task-id",
    "input_bundle_sha256": "64-hex",
    "writer_rules_sha256": "64-hex",
    "started_at": "ISO-8601",
    "completed_at": "ISO-8601"
  },
  "narrative_canonical": {
    "schema": "qingshan.narrative_canonical.v3",
    "authority_path": "workflow/claude_writer_agent/scripts/E41_NARRATIVE_CANONICAL_v5.md",
    "authority_sha256": "64-hex",
    "production_contracts_externalized": true,
    "scene_sequence": [],
    "time_blocks": [],
    "story_moves": []
  },
  "derivatives": {
    "directing_script": null,
    "generation_contract": null
  }
}
```

`narrative_canonical_v3.schema.json` 已强制 `writer_provenance`；`SCRIPT-US-DRAMA-EVENT-DENSITY` 同时读取真实 receipt 文件并核对其文件 SHA，manifest 自报不能代替 receipt。

---

## 7. 责任矩阵

| 环节 | Claude Writer | Codex/生产主管 | 监制/审计 | Pipeline |
|---|---:|---:|---:|---:|
| 原著读取与剧情创作 | 主责 | 不代写 | 可审 | 禁写 |
| story move DAG | 主责 | 执行门 | 可审 | 只读 |
| canonical 正文 | 唯一默认作者 | 仅按明确授权修订 | 提意见/准入 | 只读 |
| SHA 与 manifest | 生成 | 验证 | 审核 | 消费 |
| 注册门执行 | 提供证据 | 主责 | 复核 | 不绕过 |
| canonical admission | 无自批权 | 汇总 | 批准/审计 | 等待 |
| 导演稿 | 派生 | 可工具化 | 审核 | 消费 |
| 生成合同 | 提供剧情依据 | 主责接线 | 审核 | 执行 |
| 付费生成与发行 | 禁止 | 按授权执行 | 审计 | 按权限执行 |

---

## 8. 并行和串行规则

- 同一集：source → canonical → directing → generation 必须串行。
- story move DAG 内按因果顺序校验，不允许并行写互相依赖的节点。
- 不同集可以并行做 source ingest 和 continuity 预制，但上一集终态未锁时，下一集 canonical 不得终态化。
- 同一集本地 Writer 和云端 Writer 禁止并行创作。
- script QA 的独立机器门可并行执行，但 admission 必须汇总所有结果。

---

## 9. Canonical 完成定义

以下任一项都不算完成：

- 写出一份看起来完整的 Markdown；
- manifest 自报 PASS；
- 只通过节奏门；
- 只通过原著忠实门；
- 监制说“方向可以”；
- 已开始派生镜头稿。

只有同时具备以下事实才算完成：

1. 独立 story-only authority 文件存在；
2. exact SHA 固定；
3. manifest v3 合同完整；
4. Writer provenance 可核验；
5. 九个 script gates 全部实际执行并通过；
6. admission receipt 持久化；
7. 状态为 `CANONICAL_LOCKED`。

---

## 10. 当前实现与目标工艺的差距

| 项目 | 当前实际状态 | 风险 | 建议 |
|---|---|---|---|
| Writer 角色 | 本地定义 Claude/Fable 5；云端 Opus 4.8 | 本地/云端型号口径不一致 | 使用 exact provider/model ID，不再用营销别名 |
| 单次生成溯源 | E41+ 已强制完成 receipt；历史剧本仍无补造依据 | 历史剧本不能追溯补证 | 历史保持 UNKNOWN，不伪造 receipt |
| 本地调用入口 | `canonical_writer_dispatcher.py` 已成为唯一运行登记、写锁和收口入口；实际模型 turn 仍由 Claude/Cowork 或 StoryClaw 执行 | 若宿主绕开 dispatcher，script gate 会因缺 receipt 阻断 | 保持入口覆盖测试 |
| 四层分离 | 新 v3 已定义；旧 E41–E82 多数仍是单体 `剧本_ClaudeWriter` | 旧文件不能自动视为 v3 canonical | 进入生产前按 v3 重建 authority，不改 E40 已绑定任务 |
| 节奏门 | 已实现真实正文/SHA + 因果 DAG | 已闭合旧数字灌水路径 | 保留回归测试 |
| 全部 script 门 | stage runner 已列九门 | 是否每集都由唯一入口调用仍依赖 evidence bundle | admission receipt 必须列出 invoked 状态 |
| v2 旧文案 | 本地宪章已将机械场数/地点/cross-cut 数量降为诊断 | 旧历史文档仍可能被误读 | v3 文档与现行宪章优先 |
| 主备切换 | dispatcher 使用同集同版本 `O_EXCL` lease | 跨设备必须把 lock dir 放在同一共享根 | StoryClaw 部署时配置共享 lease 目录 |

---

## 11. Roger 审核建议逐项回答

1. 是否同意 canonical 只包含故事事实，不含镜头与生成参数？
2. 是否同意 Claude Writer 继续作为唯一默认 canonical Writer，Codex 只执行规则和明确授权修订？
3. 是否要求所有新 canonical 强制保存 exact provider/model/session receipt？
4. 是否同意 E41+ 未分层的旧单体剧本不得直接视为 v3 canonical？
5. 是否同意清除宪章中仍残留的 v2 机械场数/地点硬线表述？
6. 是否同意本地/云端 Writer 通过共享写锁防止双写？
7. 是否同意九个 script gates 必须由统一 runner 全量执行，单门 PASS 不得准入？

---

## 12. 依据文件

- `workflow/claude_writer_agent/宪章_ClaudeWriterAgent_v1.md`
- `workflow/claude_writer_agent/青山编剧Claude_云端可移植宪章_v1.md`
- `workflow/cloud_factory_migration_v1_20260724/AGENT_ROSTER.json`
- `codex_docs/美剧叙事节奏标准_v3_因果层_20260821.md`
- `configs/schemas/narrative_canonical_v3.schema.json`
- `configs/GATE_REGISTRY_v3_20260716.json`
- `tools/us_drama_event_density_gate.py`
- `tools/episode_stage_gate_runner.py`
- `workflow/claude_writer_agent/PROGRESS.json`
