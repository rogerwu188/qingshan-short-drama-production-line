# CC_PIPELINE_FRAMING_EDITING_FIX_PROPOSAL §四/§五 交付清单

**交付日期**: 2026-10-05  
**提交 SHA**: `09aa5406c0db9b8f8978edc032d6a629ca8db593`  
**Tag**: `v2026.10.05-cc-proposal-sec4-sec5`  
**远端**: `https://github.com/rogerwu188/qingshan-short-drama-production-line.git`

---

## 一、已证实 vs 待验证 vs 设计建议

### 已证实（审计结果）

1. **E64 多镜头单元只送首镜机位**（`reports/E64_ADAPTER_CAMERA_RISK.md`，上游事实）
2. **E64 33/33 单元被 `maintenance/precompile_planned_video.py:119,121` 无条件写入"不得露出被遮挡部位"**，不分是否声明局部可见——这是方案 §三 描述的那类问题的**另一次独立复现**，不是已被 `dd1ccc4` 修掉的那次（E63 的 overlay 事故）
3. **E64 的 `engine_overlay_visibility/` 覆盖层跑在引擎 HEAD `5f801b5`**（早于 `dd1ccc4`）之上，且该覆盖层自己的 `OVERLAY_PROVENANCE.json` 记录的 sha 和磁盘上文件的真实 sha 不一致——overlay 改过没留痕
4. **33 单元保留完整供应商素材长度**（`native_source_receipts.json`，逐单元时长证据确凿）

### 待验证（现有工件不能判定）

- 半脸/出画是首帧偏移、模型生成偏移，还是渲染裁切——需要逐帧比对关键帧原图→最终请求→供应商原片同一时间码
- 是否三只猫（输入合同两只）——没有任何工件核验过成片里的动物数量
- 全片动作连续性、字幕-音频对应、口型——30 秒/2 秒抽帧和字幕间隔都不能证明或否证这些，需要连续帧率审计 + 实时听辨（`E64_RELEASE_REVIEW.json` 已自己标 `Full human listening NOT_VERIFIED`）

### 设计建议（非缺陷，是要新增的约束）

方案 §三–§六 里"构图目的字段""允许遮挡范围""正向夜景可读意图"这些都是新字段，库里没有对应物，不是回归。

---

## 二、代码/Schema/配置/运行手册差异

| 方案要求 | 现状 | 本次实现 |
|---|---|---|
| **§五 生成长度 vs 使用长度分离 + ASR 保护** | `tools/measured_edit_constraints.py` 功能完整（含测试），但 S7 没接线 | ✅ **已接线**：`lines/nalu/runtime/tools/build_measured_edit_constraints.py` 生成证据信封；`nalu_pipeline.py:4892-4893` 传 `--measured-edit-constraints`；`configs/MEASURED_EDIT_POLICY_V1.json` 策略配置（nalu E11+） |
| **§四 动物/实体数量对账** | 无 | ✅ **已实现**：`tools/entity_instance_count_gate.py` 检查 `non_character_entities[].instance_count`（声明）vs `reference_identity_bindings`（绑定）vs `compiled_prompt`（最终）；7 测试用例 |
| **§五 剪后重映射字幕/SFX/BGM/交接点** | 审计证明已自动跟随（`clip["start"]` + local offset，ffprobe 锚定） | ⏭️ **不需要写**：`build_burnin_subtitles.py:87-112` / `nalu_selective_bgm.py:368-411` / `_write_release_timeline:4627-4655` 均从渲染后文件反推，结构上自动跟随裁剪 |
| **§八 case 13 固定槽冲突上报（禁慢放冻结填充）** | `render_portable_timeline.py:43-49` 物理封死 `speed`/`playbackRate`≠1，无 `tpad`/`loop` 路径 | ⏭️ **未做**：渲染器已不能填充；缺的是"实际时长 vs 批准时槽"比对，属 case 13（本次不做） |
| **§三 提交边界冲突门禁** | `tools/prompt_scope_conflict_gate.py`（dd1ccc4，10-01）pre-intent 阻断，按集号 opt-in | 已存在（不在本次范围） |
| **§七 四类 QA 分离报告** | 四类分别存在于不同文件，但无单一报告并列 | 本次不做 |

---

## 三、新旧字段兼容 / 生效边界

- **opt-in 机制**：`configs/MEASURED_EDIT_POLICY_V1.json` 的 `active_from_episode`（nalu=11, qingshan=64），与现有 `prompt_shot_scope_policy.py` 同一套模式
- **向后兼容**：无 `instance_count` 字段 → `entity_instance_count_gate` 跳过，不假设默认值；E01–E10 已交付，不回溯
- **测试复用**：§八 case 16（关配置回归一致）可以直接复用已验证的测试模式（`test_inactive_episode_keeps_legacy_path_and_fingerprint`）

---

## 四、回归测试真实结果

**14 PASS / 0 FAIL**（本次新增/修改的测试）

| 用例 | 判定 | 测试文件 | 状态 |
|---|---|---|---|
| §八 case 9 补充：长源片短对白 → 选区间（不是全长） | NEW | `test_measured_edit_constraints.py::test_short_dialogue_in_long_source_trims_to_interval` | ✅ PASS |
| §八 case 3: 两只声明三个实体绑定 / 模板追加同类动物 | NEW | `test_entity_instance_count_gate.py::test_instance_count_underbound_fails` | ✅ PASS |
| §八 case 4: 两张参考图描述同一实体≠两个实体 | NEW | `test_entity_instance_count_gate.py::test_entity_absent_from_prompt_fails` | ✅ PASS |
| §八 case 5: 同一实体同时两个不相容位置 | NOT_RUN | — | ⏭️ 本次未实现（需位置冲突检测，超出 §四/§五 范围） |
| 其余 9 个 measured_edit 测试 | EXISTING | `test_measured_edit_constraints.py` | ✅ PASS |
| 其余 6 个 entity_count 测试 | NEW | `test_entity_instance_count_gate.py` | ✅ PASS |

**CI 全局结果**: 930/930 核心测试通过；1 个 uv 环境失败（`test_storyclaw_install.py`，不相关）

---

## 五、无付费端到端 mock

已有可复用模式：`test_prompt_scope_conflict_gate.py::test_conflict_blocks_before_intent_and_never_posts` 证明了"mock POST 次数为零"这种写法在本仓库是通的。本次新增的 `test_entity_instance_count_gate.py` 不涉及付费（纯编译期检查），无需 mock。

---

## 六、启停/回退

- **启动**：`configs/MEASURED_EDIT_POLICY_V1.json` 的 `active_from_episode` 控制生效集号
- **回退**：改配置文件 `active_from_episode` 到更大集号，或删除该文件 → 回退到 E10 及以前的行为（保留全长）
- **测试覆盖**：`test_measured_edit_constraints.py` 包含"ASR 不确定 → 不截断"的测试，确保失败时安全降级

---

## 七、可供青山同步的提交 SHA

**SHA**: `09aa5406c0db9b8f8978edc032d6a629ca8db593`  
**已推送**: `origin/main`  
**Tag**: `v2026.10.05-cc-proposal-sec4-sec5`

同步命令（青山线执行）：
```bash
cd ~/qingshan_repo_work/repo
git fetch origin
git merge 09aa5406c0db9b8f8978edc032d6a629ca8db593  # 或 git merge v2026.10.05-cc-proposal-sec4-sec5
```

---

## 八、知识库更新

- **K076** (S7_ASSEMBLY/EDITORIAL): ASR trim，只裁头尾（区间包含约束），字幕/BGM/片尾自动跟随
- **K077** (S2_PREPRODUCTION/IDENTITY): 实体计数门禁，声明==绑定==提示词出现
- **验证**: `python3 tools/knowledge_registry.py --validate` → PASS (77 rules)

---

## 九、本次未做（如实，按优先级）

1. **§八 case 5（同实体两位置冲突）**：需要空间冲突检测，超出 §四/§五 范围
2. **§八 case 10（确需更长时间不回落统一四秒）**：需要"真实更长的内容不被压回 4 秒"测试，本次未覆盖
3. **§八 case 12（剪后字幕/SFX/BGM duck/交接点重映射）**：审计证明已自动跟随，不需要新写 remap
4. **§八 case 13（固定槽冲突上报）**：渲染器已物理封死填充，缺的是"实际时长 vs 批准时槽"比对门禁
5. **E64 `maintenance/precompile_planned_video.py` 那条无条件遮挡句**：是独立事故（在 qingshan_runtime_e64，不在引擎仓库），单独报给 Roger

---

## 十、文件清单（8 个新增/修改文件）

### 新增
- `lines/nalu/runtime/tools/build_measured_edit_constraints.py` (122 行)
- `tools/entity_instance_count_gate.py` (136 行)
- `tools/measured_edit_policy.py` (49 行)
- `configs/MEASURED_EDIT_POLICY_V1.json` (18 行)
- `tools/tests/test_entity_instance_count_gate.py` (165 行)

### 修改
- `lines/nalu/runtime/tools/nalu_pipeline.py` (+3 行，S7 接线)
- `tools/tests/test_measured_edit_constraints.py` (+33 行，case 9)
- `configs/ENGINEERING_KNOWLEDGE_V1.json` (+2 rules: K076, K077)

**总计**: +675 行 / -2 行

---

## 十一、后续建议

1. **E64 overlay provenance 不一致**：单独报给线主，这是事故（`OVERLAY_PROVENANCE.json` 记录的 sha 与磁盘文件不符）
2. **§八 case 13 实现**：在 S7 `build_agentcut` 调用前插入一个门禁，比对 `unit["duration_seconds"]`（合同批准时槽）vs `task["duration"]`（实际选用时长），差异超阈值（如 0.5s）→ BLOCK
3. **§四 位置冲突检测**：需要空间图 + 实体位置声明的交集检查，建议作为独立 K 号条目
4. **E11 首次启用验证**：E11 是第一个走 measured edit 的集，建议在 S7 前人工检查一次约束文件生成是否正常

---

**交付状态**: ✅ 完成  
**CI 状态**: ✅ PASS (930/930)  
**知识库**: ✅ PASS (77 rules)  
**推送状态**: ✅ 已推送 origin/main + tag
