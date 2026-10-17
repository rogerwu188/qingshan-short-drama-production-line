# 生成前一致性与付费重试闭环：通用层边界与本地适配清单

本轮修复（共享引擎，2026-10-16）把「生成前一致性」与「付费重试闭环」的通用缺陷修在引擎里。
本文件记录三件事：改了什么、哪些能力**故意不在**通用层（必须由各线本地适配）、以及尚未解决的限制。
判读与操作口径以本文件为准，不要再从代码反推意图。

## 一、本轮修改的通用行为

| 缺陷 | 原行为 | 现行为 | 文件 |
|---|---|---|---|
| 背景人数与实体例数是常量 | `background_population_count` 字面量 0、例数恒 `{id: 1}`；任何非零背景人数判 FAIL | 由入参声明；校验器查字段存在与自洽（`unbound ≥ background`、例数 ≥1）；缺字段 FAIL | `tools/provider_scope_projection.py` |
| 人数条款只在 E56+ 生效 | `ACTIVE_FROM_EPISODE = 56` 是源码常量，低于它的集无从开启 | 常量不动；unit 或投影写 `provider_scope_prompt_checks: ENFORCED/DISABLED` 可逐集开启/关闭 | 同上 |
| 渲染器静默补人数 | 字段缺失时回退 `len(scope_bindings)` | 无投影时按历史语义渲染 0；投影存在但未声明人数 → `H3_PROVIDER_SCOPE_POPULATION_UNDECLARED` | `tools/h3_provider_prompt_renderer.py` |
| 开关三处拼法 | 投影/渲染 `provider_scope_prompt_mode`、镜像预检 `scope_mode`、视频提交 `h3_prompt_profile` | 经 `normalize_prompt_mode` 归一；未知值保持原样不吞成默认 | 三处调用点 |
| 参考图不分角色 | 所有绑定一律 `exclusive identity of X`，拓扑图也能当身份锚 | 身份位声明 `exclusive_identity_owner`，非身份位 `may_define_identity=false`；预检比对声明角色与 id 命名空间 | `tools/provider_scope_projection.py`、`tools/shot_media_admission_gate.py` |
| 预检链是死代码 | 校验只在 `exec_deployed_submitter()` 内，而生产走 `main()` | 抽出 `validate_task_submission_gates()`，两条入口都调；AST 测试断言 `main()` 必须调用 | `tools/submit_giggle_video_manifest_v2.py` |
| 重抽账本无写入方 | 守卫读 `events` 但无人 append → 序号恒 1、预算永不推进 | 写入器与读取器同址（`reroll_cost_guard`）；构建请求记 `outcome=REQUESTED`（不消耗预算） | `tools/reroll_cost_guard.py`、`post_generation_qa_runner.py` |
| 策略键无人读 | `block_failure_classes`、`advise_margin_fraction` 仅存于文件 | 前者参与判定，后者参与告警，两者都进结论 | `tools/reroll_cost_guard.py` |
| 无置信度字段 | 只有 `failure_attribution` | 增加 `cause_confidence`：`DETERMINATE` / `INFERRED` / `NOT_APPLICABLE` | `tools/shot_media_admission_gate.py` |
| 匿名角色无层级 | 无名过场只能落进 forbidden absent terms | 角色表可标 `identity_tier`：`ANONYMOUS_FUNCTIONAL` / `BACKGROUND_CROWD` 进 `anonymous_role_descriptors`，不比脸 | `tools/provider_scope_projection.py` |

回归测试：`tools/tests/test_pregen_consistency_retry_closure.py`（41 例，全免费），已登记进
`configs/PORTABLE_CORE_MANIFEST.json`。

## 二、故意不在通用层的能力（本地适配清单）

### 2.1 环境文字泛化模板 — **不在共享仓，须本地提供**

「把作者写的地点/物件描述泛化到不锁定具体剧情」的模板，在共享仓 `tools/ configs/ docs/` 全量检索与
历史提交中均不存在，nalu 运行期也没有。它属于**线本地适配产物**：

- **保留（KEEP）**：本线自己维护的模板与覆盖文件继续留在本线，不要为了「统一」搬进共享仓——
  它是作品语汇，进通用层会把一条线的世界设定写死成所有线的默认。
- **不要复制（DO NOT COPY）**：不要照搬另一条线（如青山）的逐集脚本或词典；
  共享仓不放任何线私有剧情、资产、账本。
- **迁移（MIGRATE，可选）**：若要把某条线的泛化能力抽成通用件，前提是它能参数化到
  「无集次实值、无作品名词」，并在提交前通过 `run_portable_ci.py`。未参数化前不要提交。

### 2.2 逐集构建器 — **不入库**

`lines/nalu/runtime/tools/build_e0N_layers.py` 内嵌本集镜头表与逐字台词，属作品文本，
`.gitignore` 已拦。这一边界本轮未变。

## 三、尚未解决的限制（如实）

1. **无参考图视觉内容校验（能力缺口）**。`precheck_submission_inputs` 现在能查**声明**是否自洽
   （角色与命名空间冲突、两个身份共用一张脸牌），但**不能**判断图像内容是否与声明的用途相符——
   一张贴错的图只要文件名与 SHA 对得上仍会放行。真正的内容校验需要视觉模型比对，本轮不实现。
   兜底：人工看图（五类审核），并在绑定参考图时如实填 `role`，让声明层的不一致至少能被机器抓住。
2. **`population_scope_verification` 的生产端在多条线各自实现**。校验器与 schema 在通用层，
   写入方按线实现（本轮的写入器是 nalu 侧的 `post_generation_qa_runner.py`）。
   判定条件已放宽为「投影声明了即检查」，不再只看集次阈值。
3. **`SWITCH_COVERAGE_REQUIRED` 的消解策略需要产品裁定**。该码现在可由既有的
   `coverage_redesign_contract` / `execution_prompt_redesign_contract`（status PASS）满足，
   但「同一归因连续两次后究竟该重跑覆盖还是该放开重抽」是政策问题，不是代码问题。
4. **`MODEL_STOCHASTIC` 是「原样重抽」而非「必须变」**。这一条经复核**是本来的设计意图**
   （随机性归因意味着输入无过错，重抽即重掷骰子），并非缺陷；本轮未改，其测试
   `test_model_stochastic_retry_keeps_input_unchanged` 保留。
   「只改提示词就抽卡」的拦截由 `retry_cap_gate.validate_video_coverage_redesign` 负责，
   它要求内容失败后必须交出一份从头重写的执行提示词契约，而不是改措辞。
5. **`material_change_from_prior_attempt` 仍是自由文本**。机器只能检查它非空，无法判断
   「实质变更」是否真的发生；真正的证据是重设计契约里的 SHA 对（前后提示词、动作 IR、
   不可变契约），这是当前可用的最强机器判据。
6. **内容失败重抽的长度约束**：同一失败连续两次时要求 `action_budget_reduced` 且提示词不得变长。
   这条对「删掉一点东西就能过」的场景有效，但对「必须加约束才能过」的场景是反向压力，
   遇到时按线主裁定的例外处理，不要自行放宽。

## 四、变更历史

- 2026-10-16：首版。基线与归属见 `docs/knowledge/ENGINEERING_KNOWLEDGE_BASE.md` 的 K093–K100。

## 五、合同语义：状态差（STATE_DELTA_SEMANTICS_V1，2026-10-16）

**修的错误链**（生产线优化方案 §5.2）：v4 适配器缺声明时把维度默认成 POSTURE、把画面描述填进结束态 →
画面描述有时是一句台词 → 动作密度门只比较两段字符串与两个代码 → 台词被当成姿态变化放行。
同时构建器把 `action_kind` 写死 `NON_COMBAT`，而 `is_combat_unit` 在每拍都有声明时只信声明 → 全线打斗检查失效。

| 改动 | 文件 |
|---|---|
| 证据/端点等于本拍台词 → `STATE_DELTA_EVIDENCE_IS_DIALOGUE` / `STATE_ENDPOINT_IS_DIALOGUE` | `tools/sd2_motion_density_gate.py` |
| 非打斗对白镜可声明 `state_delta_mode=STATIC_POSTURE_PERFORMANCE`，须有表演证据；打斗镜声明即失败且两维下限不免 | 同上 |
| 适配器缺状态证据报 `STATE_DELTA_UNDECLARED`，不再编造；`ACTION_COMBAT` 统一为 `COMBAT` | `adapt_v4_layers_to_runtime.py` |
| `action_kind`、`physical_action_design`、`state_delta_mode` 透传作者值；未声明时输出与旧版逐字节相同 | `build_nalu_preproduction.py`、`video_execution_plan_compiler.py` |

**启用**：`configs/STATE_DELTA_SEMANTICS_V1.json` 的 `enabled_episodes` 列出集号（或 `enabled_from_episode`），
或合同在 action 上写 `state_delta_semantics: "V1"`。**默认一个集都不启用。**
**回退**：从 `enabled_episodes` 删掉集号即可，旧规则原样恢复；无需改代码。
**在产兼容**：未启用的集走旧规则（测试 `InactiveEpisodesKeepLockedBehaviourTest`）。已离线验证：用新代码重建 E12 的 S2，
111 镜中本次涉及的字段逐字节不变。透传类改动对不声明这些字段的合同无效果，因此不会改变任何已锁定任务的提示词或指纹。

**仍不能保证**：
- 状态代码（`entry_code/exit_code`）仍由作者手写，门只能查"不同"与"不是台词"，不能证明代码与文字语义一致。
- 打斗只有作者声明 `action_kind=COMBAT` 才会被当作打斗；没声明的打斗仍只靠文字线索兜底。

## 六、零费用预演（优化方案 §4，`tools/episode_previs.py`）

```bash
python3 tools/episode_previs.py --contract <EP>_GENERATION_CONTRACT_v1.json \
  --grouping-plan <EP>_VIDEO_UNIT_GROUPING_PLAN_V1.json --keyframe-dir <keyframes> \
  --out <reports>/<EP>_PREVIS.json [--review-round N] [--render previs.mp4]
```
- 不调任何付费图片/视频/语音接口，不加视觉模型。`--render` 用已有 `render_portable_timeline.py` 出片（关键帧或占位卡）。
- **机器检查（阻断）**：对白未授权重复（`repeat_reason` 可声明合理重复）、对白装不进本镜、镜头缺失/重复/未入单元/顺序错、说话人或演员未登记。
- **导演审查（不阻断）**：六个问题，最多两轮；第三轮起转 `CLOSED_ADVISORY`，不再请求、不自动重生成。轮数上限永远不豁免机器失败、预算或事务检查。
- 对白时长无实测音频时一律 `ESTIMATED`。场景导演意图（§3 七项）未声明只报 `SCENE_INTENT_NOT_DECLARED` 建议项。
- 预演通过只表示可以进入后续生产，不是动作、身份或口型通过的证据。

## 七、审核绑定实际发送的请求（优化方案 §7，`tools/provider_request_digest.py`）

- 摘要覆盖：提示词正文、模型、时长、比例、分辨率、按顺序的参考图（盘上 sha + 角色）、音频列表。发送时压缩后的图片字节另记 `sent_reference_sha256`，不进摘要。
- 检查位置：两个提交器内，所有适配与序列化之后、记意图之前。不符即 `REVIEWED_REQUEST_MISMATCH`，零 POST、无事务。
- **启用**：`configs/PROVIDER_REQUEST_REVIEW_BINDING_V1.json` 列集号。顺序：审核 → `python3 tools/provider_request_digest.py --manifest <manifest>` 写入 `reviewed_request_sha256` → 付费授权（D-11 绑定的是写入后的清单 sha）→ 提交。
- 启用的集里，同一 `task_key` 已按另一指纹提交过，须声明 `supersedes_submission_fingerprints` 才能再 POST（`BOUND_UNDER_OTHER_FINGERPRINT`）。
- 携带 `reviewed_request_sha256` 的任务无论是否启用都会被比对。
- **在产兼容**：未启用、未写摘要的任务只多记两条证据字段，不改指纹、不改恢复逻辑；已绑定任务仍按 task_id 恢复。

## 八、节拍—镜头—请求—剪辑映射（优化方案 §6，`tools/unit_timing_map.py`）

- 每单元记录剧情时长、对白时长（来源）、请求时长、返回素材时长（实测或 `NOT_YET_GENERATED`）、剪辑入出点。
- 失败：同一句台词由两个单元生成、尾帧依赖缺尾帧、剪辑区间为空或超出返回素材。请求超出剧情内容只记 `REQUEST_EXCEEDS_STORY`（附声明的余量）。
- 只有真有尾帧依赖的单元串行，报告列出 `tail_dependent_units`，其余并发。
- 分组门新增硬上下限：例外原因只能解释离开建议窗口，不能越过 `duration_policy_seconds`。已回放 E09–E12 均 PASS。

## 九、仍未实现或不能保证

1. 合同里没有场景导演意图字段（§3）；预演只能报"未声明"，写手层需要补写，代码不替作者生成。
2. 分组规格构建器仍会给建议窗口外的单元自动贴 `CONTINUOUS_CAUSAL_ACTION`；改它会改分组计划字节与指纹，本轮只在门上加硬限，不改标签。
3. 对白时长目前全是估算；接入 S4 参考音或试读后才有 `MEASURED`。
4. 状态代码仍由作者手写，门不能证明代码与文字语义一致。
5. 相邻镜头换人换道具后是否无依据复制上一镜状态（§10.4），依赖既有的 `entity_state_scoping`，本轮未加新检查。
6. 参考图内容是否符合声明，仍靠人工看图（线主已决定不加视觉模型）。
