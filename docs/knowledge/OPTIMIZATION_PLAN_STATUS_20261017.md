# 生产线优化方案实施状态（2026-10-17）

## 一、审计结论摘要

方案收到时（10-16）E12 已在产（10-13 开工、10-14 付费 S3/S4）。提交 `ce38308` 实现了方案第 2–4 步（预演、请求绑定审核、时序图），但自述「对每集关闭」。工作区有人（断电前该代理）在 E12 上提前启用了两项新语义，已退回（E12 沿用旧行为）。

### 1.1 已实现

| 方案章节 | 内容 | 位置 | 生产路径 |
|---|---|---|---|
| §3.3–3.5 | 运镜必须有目的、对白镜说话人/听者/口型、未解析角色生成前阻断 | `grouped_camera_contract.py`、`character_entity_contract.py`、`sd2_required_prompt_field_gate.py`、`prompt_scope_conflict_gate.py` | S1、S2、S6 付费 POST 前 |
| §4 | 零费用预演（机器检查5项、导演审查6问、最多2轮）| `tools/episode_previs.py` + `render_portable_timeline.py` | **未接线**（HEAD 无 `gate_active`、配置文件被 `.gitignore` 吞、`enabled_episodes: []`） |
| §6 | 节拍-镜头-请求-素材-剪辑时长映射（5个时长、标来源） | `tools/unit_timing_map.py` | **未接线**（库内完成、无生产代码调用） |
| §7 | 请求摘要（语义 SHA）+ 提交前绑定检查 | `tools/provider_request_digest.py` + 本轮补充的 `submit_giggle_character_asset_plan.py` 审核绑定 | S3 身份牌（本轮加）；S5 关键帧 / S6 视频走 `submit_giggle_image_manifest.py:470` `require_reviewed_request()` |
| §5.4 | 上游改变后旧事务 `superseded_by` 标记 | 本轮在 `submit_giggle_image_manifest.py:114` `prior_submission_result()` 和 `submit_giggle_character_asset_plan.py:78` `prior_submission()` 加扫描逻辑 | 每次提交前自动扫描同 task_key 旧事务 |

### 1.2 严重缺口（已在本轮补齐）

1. **独立提交入口审核绑定缺失**：`submit_giggle_character_asset_plan.py`（S3 身份牌生成）在本轮前从不检查 `reviewed_request_sha256`，已补齐（仿照 `submit_giggle_image_manifest.py:470`）。
2. **失效机制缺失**：合同改变后，旧事务与旧审核回执无法自动失效——本轮在两个提交器的 `prior_submission*()` 里加「扫描同 task_key 所有旧事务、标记 `superseded_by` 与 `superseded_at`」。

### 1.3 未接线（在库、未进生产）

- **预演（§4）**：`episode_previs.py` HEAD 无 `gate_active` / `policy_settings`，工作区有接线但未提交且默认关闭（`configs/EPISODE_PREVIS_V1.json` 被 `.gitignore` 吞、`enabled_episodes: []`）。
- **时序图（§6）**：`unit_timing_map.py` 完全未被生产代码调用（应在 S2 后、S6 收割后、S7 剪辑后各跑一次）。
- **场景导演意图（§3.1）**：`scene_intent` 在合同 schema / builder 无落点（18 集只有 E12 手填 18 场，其余 0 场）；S1 门不校验。

### 1.4 方案第 5 章（合同语义）

| 条 | 内容 | 状态 |
|---|---|---|
| §5.1 | 严格区分对白/动作/表演/姿态/场景/运镜 | **已实现**（合同字段分离、构建器 / 门分别校验） |
| §5.2 | 修正 v4 适配器默认填充画面描述→姿态的错误链 | **已修正**（K056 / K070，`adapt_v4_layers_to_runtime.py`、`build_nalu_preproduction.py`） |
| §5.3 | 合法「姿态不变」 | **已实现**（`editorial_pacing_contract.py` 允许姿态不变 + 对白/表演推进） |
| §5.4 | 上游字段改变后重建派生、撤销旧审核资格 | **本轮补齐失效标记**；审核回执撤销逻辑需加（见下文「尚需完善」） |

### 1.5 方案第 7 章（提交路径审核绑定）

| 条 | 内容 | 状态 |
|---|---|---|
| §7.1 | 绑定真正有效版本（源合同、模型、时长、最终提示词、有序素材列表 SHA） | **已实现**（`provider_request_digest.py` 生成语义 SHA） |
| §7.2 | 最终检查在序列化后、付费 POST 前 | **图片/视频已实现**（`submit_giggle_image_manifest.py:470` / `submit_giggle_video_manifest_v2.py` POST 前调）；**S3 身份牌本轮补齐** |
| §7.3 | 不破坏事务恢复 | **已实现**（指纹相同即恢复、新规则不触发历史重 POST） |

### 1.6 方案第 8 章（参考素材）

**已实现**（共享层 `identity_reference_admission_gate.py` / `seedance_reference_transport_gate.py` 校验文件存在/SHA/版本/角色 ID/用途一致；本地 `keyframe_q1_builder.py` / `video_q2_builder.py` 人工看图填答、回执绑定素材 SHA + 用途 + 任务）。

### 1.7 方案第 9 章（后期）

**已实现**（`render_final_cut.py` / `episode_assembly_runner.py` 对白唯一使用、剪辑依据真实落点、音频时基正确；BGM / 广告 / 片尾走现有配置；技术 QA 阻断、表演偏差 ADVISORY）。

---

## 二、尚需完善（按优先级）

1. **审核回执失效机制不完整**：事务已能标 `superseded_by`（本轮），但审核回执（`/preproduction/reports/qa/*`）在合同改变后未被自动撤销——需要在 `keyframe_q1_builder.py` / `video_q2_builder.py` 等审核构建器里加「读旧回执 → 检查被审核文件 SHA → 不匹配则标 `superseded_by` 并拒绝复用」。

2. **预演接线**：
   - 给 `.gitignore` 加 `!configs/EPISODE_PREVIS_V1.json` allowlist 行。
   - 提交工作区 `nalu_pipeline.py` 的 `previs_gate()` 接线（S5/S6 头部）。
   - 提交 `episode_previs.py` 的 `gate_active` / `policy_settings` 函数。
   - 配置 `enabled_episodes` 或 `enabled_from_episode`。
   - 提交 `test_previs_gate_wiring.py`（修 `_Paths` 桩让 `preprod_reports` 目录可写）。

3. **时序图接线**：在 `nalu_pipeline.py` 的 `stage_s2` 末尾 / `stage_s6` 收割后 / `stage_s7` 剪辑后调 `unit_timing_map.py`。

4. **场景导演意图落点**：在 `build_e0N_layers.py` 的 `scene_states` 推导里加七字段生成；在 `writer_production_field_gate` 或 `nalu_writer_selfcheck_seq29` 加「缺失即 FAIL」。

5. **预演机器检查缺三项**：声音跨镜一致性、道具权威 ID、动作-状态-镜头顺序冲突（后两项由别的门在 S1 做，但 previs 作为"付费前最后一道"未复跑）。

6. **previs CLI 无 `--dialogue-audio` 入口**（`main:302-317`），`MEASURED` 时长只能靠库 API 传入；`render_portable_timeline.py` 不出字幕。

---

## 三、测试验证状态

| 测试文件 | 覆盖条款 | 状态 |
|---|---|---|
| `test_previs_and_timing_map.py` | §4 §6 §10.5/7/8/12/13 | **HEAD 已提交、16 例全 PASS** |
| `test_previs_gate_wiring.py` | §4 预演门接线 | **未提交、未跟踪**；13 PASS / 2 FAIL（测试桩路径问题） |
| `test_submit_giggle_character_asset_plan.py` | S3 身份牌提交 | 已有（未覆盖本轮新增的审核绑定） |
| `test_submit_giggle_image_manifest.py` | 图片提交 | 已有（未覆盖本轮新增的失效标记） |
| 全套 `tools/tests/` | 离线验证 | **后台运行中**（已排除 `test_seedance_reference_transport_gate.py`） |

---

## 四、E12 当前状况与建议

E12 S5 卡在 8 个关键帧身份审 FAIL：

| 单元 | 失败角色 | 实测余弦 | 画面实况 |
|---|---|---|---|
| S01-01 / S07-01 / S11-01 / S18-01 | 秦铭 | 0.056–0.165 | 画面里两人都是中年短须男，秦铭被画成了许岳平那一类脸 |
| S13-01 | 秦铭 | 0.108 | 冯易安大胡子对、秦铭脸不对 |
| S15-01 / S15-05 / S17-03 | 冯易安 | 0.133 等 | 冯易安被画成另一个大胡子男 |

对照 S02-04 的秦铭（0.566 通过、干净无须年轻脸），说明**锁牌对、关键帧画错**。提示词已核查：S13/15/17 的冯易安行是「一脸浓密黑色大胡子」，没问题；秦铭行未声明胡须，但画面两人都长了须——这是 K059 类"身份信号沿链稀释"，不是阈值问题、不是测量噪声。秦铭是主角，脸画错属剧情级缺陷。

**建议**：重做这 8 个关键帧（8×11 = 88 积分，在 8000 上限内），而非发订单硬放行。等线主授权。

---

## 五、推送计划

1. 本轮修改（审核绑定 + 失效标记）提交为一个 commit，标题「engine: plan §5.4 §7.2 supersession + char-asset review binding」。
2. 推送到 origin/main 前：全套测试 PASS、`deployment_code_integrity.py` PASS、`knowledge_registry.py --validate` PASS。
3. 同步到 Codex 线前：线主确认这两处修改不破坏 Codex 既有行为（Codex 无 `reviewed_request_sha256` 字段时检查静默通过；失效标记只写、不读，不影响恢复）。
