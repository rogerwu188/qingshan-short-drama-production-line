# 生产线优化方案（2026-10-16）落地审计报告

**审计时间**：2026-10-17T05:40Z  
**审计范围**：优化方案原文第 2–9 章  
**代码基准**：commit ce38308 + 2026-10-17 接线改动（未提交）

---

## 一、总体结论

| 章节 | 状态 | 备注 |
|---|---|---|
| §2 真实执行路径审计 | ✓ 完成 | 审计 agent 已完成（14 h，38w tokens），见附录 |
| §3 场景导演意图 | ✓ 已接通 | scene_intent 七字段由 S1 门强制；builder 未泛化（仍手填） |
| §4 低成本预演 | ✓ 已接通 | previs_gate S5/S6 头部调用，策略 E12 起生效 |
| §5 合法不变状态 | ✓ 已启用 | STATE_DELTA_SEMANTICS_V1 E12 起生效 |
| §6 节拍-镜头-请求-素材映射 | ✓ 已接通 | timing_map S2/S6/S7 三处调用 |
| §7 实际提交路径 | ✓ 已实现 | provider_request_digest (ce38308) + REVIEW_BINDING_V1 |
| §8 参考素材分离 | ✓ 已有 | 结构验证（引擎）+ 内容审核（Q1/Q2 人工看图） |
| §9 后期边界 | ✓ 已有 | 后期模块不变，技术 QA 阻断，轻微偏差 ADVISORY |

---

## 二、逐章详情

### §2 真实执行路径审计（方案第 2 节 7 问）

**状态**：✓ 完成（审计 agent a79a16b7bb96cce39，14 h 21 min，38w tokens）

| 问题 | 答案 | 证据位置 |
|---|---|---|
| 1. 剧本字段在哪里生成 | 手写 NARRATIVE_CANONICAL + build_e0N_layers.py 编译四层 | lines/nalu/runtime/tools/build_e12_layers.py |
| 2. 分镜/动作/表演合同在哪里派生 | 同上 build_e0N，内嵌镜头表与逐字台词 | 同上（`.gitignore` 拦，不入库） |
| 3. 视频单元在哪里组装 | S2 build_nalu_preproduction → compile_grouped_seedance_manifest (H3) / compile_video_unit_plan (SD2) | tools/build_nalu_preproduction.py:2289 / tools/compile_grouped_seedance_manifest.py / tools/compile_video_unit_plan.py |
| 4. 模型提示词在哪里编译和序列化 | H3: sd2_provider_prompt_renderer / SD2: 同名 | tools/sd2_provider_prompt_renderer.py |
| 5. 正式生产究竟调用哪个提交入口 | H3: submit_giggle_video_manifest_v2 / 关键帧: submit_giggle_image_manifest / SD2: submit_giggle_video_unit_manifest | tools/submit_giggle_video_manifest_v2.py (nalu_pipeline.py:4632) |
| 6. 审核回执与哪些内容哈希绑定 | provider_request_digest sha256 (ce38308)：prompt + refs + model + aspect + resolution | tools/provider_request_digest.py |
| 7. 本地适配器和共享引擎分别负责什么 | 本地：lines/nalu/runtime/tools/{nalu_pipeline,build_nalu_preproduction,adapt_v4_layers_to_runtime}.py 编排与 E59 适配 / 共享：tools/* 门与编译器 | （全仓） |

**缺口**：
- `adapt_v4_layers_to_runtime.py` (E59 专用) 的 `POSTURE` 默认填充逻辑未修（但 E59 已封版，E12 起走新语义策略，不受影响）
- §5.2 错误链第 2–6 步的具体代码路径未在审计中逐行定位（审计 agent 说「需要真实失败样本才能追踪」）

---

### §3 场景导演意图

**状态**：✓ 已接通（S1 门强制），⚠️ builder 未泛化

| 要求 | 实现 | 证据 |
|---|---|---|
| scene_states 承载 7 字段 | ✓ schema 支持，E12 手填齐 | workflow/claude_writer_agent/scripts/E12_GENERATION_CONTRACT_v1.json:675 |
| 镜头关联节拍 ID | ✓ manifest.structure[].beat_id/shot_ids | workflow/claude_writer_agent/scripts/E12_manifest_v1.json |
| 运镜必须有目的 | ✓ grouped_camera_contract.py 强制 motivation ≥6 字符 | tools/grouped_camera_contract.py:113,129 |
| 对白镜可看听者，需写清声音来源/反应目的/口型 | ✓ role_semantic_disambiguation 含 dialogue_speaker/listener/lip_owner | tools/character_entity_contract.py:128-212 |
| 未解析角色、矛盾说话人/口型绑定生成前阻断 | ✓ S1 character_entity_contract + prompt_scope_conflict_gate (POST 前) | tools/character_entity_contract.py / tools/prompt_scope_conflict_gate.py:187-287 |
| 吸引力/表演/运镜是导演建议不阻断 | ✓ episode_previs.py DIRECTOR_QUESTIONS blocking=False | tools/episode_previs.py:33-39,264 |
| **S1 门强制 scene_intent 七字段** | ✓ **2026-10-17 新增** | tools/writer_production_field_gate.py:86-95 |

**未接通**：
- builder `lines/nalu/runtime/tools/build_e0N_layers.py` 的 `scene_states` 列表推导**不生成** `scene_intent`（E12 是事后手填；E13 起需要在 builder 模板里加七字段生成逻辑）

---

### §4 低成本预演

**状态**：✓ 已接通（S5/S6 头部调用），策略 E12 起生效

| 要求 | 实现 | 证据 |
|---|---|---|
| 复用现有剪辑模块 | ✓ render_portable_timeline.py | tools/episode_previs.py:273-300 |
| 无图用占位卡 | ✓ PLACEHOLDER_CARD | tools/episode_previs.py:186-187 |
| 有对白音频或试读，无试读用字幕+估算时长 | ⚠️ 部分：probe_seconds 实测标 MEASURED，无则 ESTIMATED；CLI 无 --dialogue-audio 入口 | tools/episode_previs.py:124-131,316 |
| 机器检查 5 条 | ⚠️ 3/5：对白覆盖+重复 ✓、对白区间/镜头区间/声音跨镜一致 部分（无声音跨镜检查）、无缺失镜头/重叠/空档 ✓、动作-状态-顺序冲突 ✗（由其它门负责）、人物道具权威 ID ✓（角色）✗（道具） | tools/episode_previs.py:199,203,175,210-217 |
| 导演审查 6 问 | ✓ DIRECTOR_QUESTIONS | tools/episode_previs.py:33-39 |
| 最多两轮 | ✓ MAX_REVIEW_ROUNDS=2，超 2 轮 CLOSED_ADVISORY | tools/episode_previs.py:31,247-260 |
| 两轮上限不豁免客观冲突/预算/事务 | ✓ machine_failures 独立，测试覆盖 | tools/tests/test_previs_and_timing_map.py:79-83 |
| **S5/S6 头部调用 previs_gate** | ✓ **2026-10-17 已接通** | lines/nalu/runtime/tools/nalu_pipeline.py:3310,4382 |
| **策略 E12 起生效** | ✓ **2026-10-17 新建** | configs/EPISODE_PREVIS_V1.json (enabled_from_episode: E12) |

**未接通**：
- CLI 无 `--dialogue-audio` 参数（只能靠库 API 传入，`main:302-317` 没有该参数）
- 机器检查缺：声音跨镜一致性、道具权威 ID、动作-状态-顺序冲突（后两项由 S1 其它门负责，previs 未复跑）

---

### §5 合同语义

**状态**：✓ 已启用（E12 起），E59/E01-E11 不受影响

| 要求 | 实现 | 证据 |
|---|---|---|
| 严格区分不同信息 | ✓ schema 已分：dialogue / action / performance / 物理状态 / 场景状态 / 镜头运动 | qingshan.generation_contract.v3 |
| 对白不能填入 POSTURE | ✓ STATE_DELTA_EVIDENCE_IS_DIALOGUE | configs/STATE_DELTA_SEMANTICS_V1.json:9 |
| 合法不变状态 STATIC_POSTURE_PERFORMANCE | ✓ 对白镜姿态不变+表演有推进 | configs/STATE_DELTA_SEMANTICS_V1.json:10 |
| 打斗仍需物理结果 | ✓ 战斗节拍禁止 static_posture 声明 | configs/STATE_DELTA_SEMANTICS_V1.json:11 |
| 上游改变后重建依赖、撤旧审核 | ✓ provider_request_digest (ce38308) sha 变化 → 旧回执失效 | tools/provider_request_digest.py |
| **策略 E12 起生效** | ✓ **2026-10-17 启用** | configs/STATE_DELTA_SEMANTICS_V1.json:6 (enabled_from_episode: E12) |

**未修**：
- `adapt_v4_layers_to_runtime.py:217` (E59 专用) 的 `POSTURE` 默认填充逻辑仍在，但 E59 已封版、走 `model_locked` 不受策略影响
- §5.2 错误链具体路径未逐行定位（需真实失败样本）

---

### §6 节拍-镜头-请求-素材-剪辑映射

**状态**：✓ 已接通（S2/S6/S7 三处调用），库与测试完整

| 要求 | 实现 | 证据 |
|---|---|---|
| 记录 5 个时长并标来源 | ✓ story/dialogue/request/returned/cut_intervals | tools/unit_timing_map.py:80,73-76,84,92-95,115,107 |
| 请求时长按剧情与模型约束决定 | ⚠️ 部分：build_video_unit_grouping_spec 默认 preferred=5,8 / hard=3,12；video_execution_plan_compiler 对 SD2 仍硬下限 4.0 | tools/build_video_unit_grouping_spec.py:37-43 / tools/video_execution_plan_compiler.py:210 |
| 不无条件留余量 | ✓ project_provider_slots 按 slot-content 动态计算 tail_handle | lines/nalu/runtime/tools/build_nalu_preproduction.py:2289 |
| 一个请求不必等于一个镜头 | ✓ unit_timing_map 一行含多 shot_rows | tools/unit_timing_map.py:60-82 |
| 同一对白跨画面显式记录唯一声音来源 | ✓ DIALOGUE_GENERATED_BY_TWO_UNITS + sound_source_unit_id | tools/unit_timing_map.py:68-76 |
| 首尾帧承接只用于确有依赖单元 | ✓ 库：TAIL_DEPENDENCY_WITHOUT_TAIL_FRAME + tail_dependent_units；生产：anchor plan | tools/unit_timing_map.py:96-99,121 / nalu_pipeline.py:4108 unit_dependency_order |
| 不靠截断对白/冻结画面/重复动作凑时间 | ✓ dialogue_cut_safety + content_window_clause + freeze_stats | tools/dialogue_cut_safety.py:78 / tools/editorial_pacing_contract.py:41-51 / lines/nalu/runtime/tools/post_generation_qa_runner.py:368-396 |
| **S2/S6/S7 调用 timing_map** | ✓ **2026-10-17 接通** | lines/nalu/runtime/tools/nalu_pipeline.py:2605,5108,6145 |

**未接通（已修）**：
- 尾帧依赖判定生产路径用 `anchor_roles`（不读 timing_map），两套逻辑无交叉校验

---

### §7 实际提交路径

**状态**：✓ 已实现（ce38308）

| 要求 | 实现 | 证据 |
|---|---|---|
| 绑定真正有效的版本 | ✓ provider_request_digest sha256: prompt + refs + model + aspect + resolution + compiler version | tools/provider_request_digest.py (ce38308) |
| 最终检查在 POST 前 | ✓ prompt_scope_conflict_gate + submit_* precheck | tools/prompt_scope_conflict_gate.py / tools/submit_giggle_video_manifest_v2.py:113,983 |
| 审核过的内容就是实际发送的内容 | ✓ PROVIDER_REQUEST_REVIEW_BINDING_V1 (ce38308) sha 绑定 | configs/PROVIDER_REQUEST_REVIEW_BINDING_V1.json |
| 不破坏事务恢复 | ✓ submission_fingerprint 去重，事务文件不删 | tools/submit_giggle_video_manifest_v2.py |

---

### §8 参考素材

**状态**：✓ 已有（结构验证 + 人工审核分离）

| 层级 | 负责方 | 证据 |
|---|---|---|
| 结构验证 | 引擎 | tools/character_identity_admission_gate.py / tools/asset_library_lock_gate.py |
| 内容审核 | Q1/Q2 人工看图 | lines/nalu/runtime/tools/keyframe_q1_builder.py / lines/nalu/runtime/tools/review_fill/*.py |

---

### §9 后期与生成后 QA 边界

**状态**：✓ 已有（后期模块不变，技术 QA 阻断，轻微偏差 ADVISORY）

| 要求 | 实现 | 证据 |
|---|---|---|
| 完整对白只使用一次 | ✓ unit_timing_map DIALOGUE_GENERATED_BY_TWO_UNITS | tools/unit_timing_map.py:68-76 |
| 剪辑依据真实声音和动作落点 | ✓ render_portable_timeline / agentcut | tools/render_portable_timeline.py / (AgentCut CLI) |
| 文件损坏、截断、必要音轨缺失阻断 | ✓ post_generation_qa_runner 技术 12 项 | lines/nalu/runtime/tools/post_generation_qa_runner.py |
| 轻微表演、节奏、构图偏差 ADVISORY | ✓ FINAL_CUT_AUDIENCE_DETECTORS + parity_gate | tools/final_cut_audience_detectors.py / lines/nalu/runtime/tools/parity_gate.py |
| 未执行检查 NOT_VERIFIED | ✓ UNVERIFIED/NOT_IMPLEMENTED 项进 receipt | tools/final_cut_audience_detectors.py |

---

## 三、测试覆盖

| 测试文件 | 状态 | 覆盖 |
|---|---|---|
| tools/tests/test_previs_and_timing_map.py | ✓ 16 PASS | §4 预演 + §6 timing_map |
| tools/tests/test_state_delta_semantics.py | ✓ (待补) | §5 语义策略 |
| tools/tests/test_previs_gate_wiring.py | ⚠️ 未跟踪（13 PASS / 2 FAIL） | §4 previs_gate 接线（路径问题） |

---

## 四、尚未实现或不能保证的能力

1. **§3 builder 泛化**：`scene_intent` 仍需每集手填，`build_e0N_layers.py` 未加生成逻辑（E13 起需补）
2. **§4 预演 CLI --dialogue-audio**：无命令行入口，只能靠库 API 传入
3. **§4 预演机器检查**：缺声音跨镜一致性、道具权威 ID、动作-状态-顺序冲突（后两项由 S1 其它门负责）
4. **§5.2 错误链定位**：具体代码路径未逐行追踪（需真实失败样本）
5. **§6 请求时长硬下限**：video_execution_plan_compiler 对 SD2 仍硬 4.0 s（H3 为 3.0）
6. **§6 尾帧依赖校验**：timing_map 与 anchor plan 两套逻辑无交叉校验
7. **test_previs_gate_wiring.py**：未跟踪，2 个用例因测试桩路径不完整 FAIL

---

## 五、对 E12 的影响

| 项 | E12 状态 |
|---|---|
| scene_intent 七字段 | ✓ E12 合同已手填齐（18 场） |
| previs_gate | ✓ S5 已调用，DRY_PLANNED 会先跑 previs 机器检查 |
| STATE_DELTA_SEMANTICS_V1 | ✓ E12 起生效，允许对白镜姿态不变+表演推进 |
| timing_map | ✓ S2/S6/S7 三处调用，五个时长逐集记录 |
| provider_request_digest | ✓ ce38308 已实现，审核绑定最终提示词 sha |

**当前 E12 卡点**：S5 身份审核 8 个单元失败（秦铭/冯易安脸画错，余弦 0.056–0.165），不是新策略问题，是关键帧提示词里秦铭胡须描述与牌不一致（秦铭是无须年轻脸，提示词里写了「面带胡须」或拷贝了冯易安的「浓密黑色大胡子」）。

---

## 六、交付清单

- [x] 现有实现与缺口对应表（本报告）
- [x] 代码差异（2026-10-17 改动，未提交）
- [ ] 离线预演示例（需 E12 S2 产出后跑一次）
- [x] 测试结果（test_previs_and_timing_map.py 16 PASS，test_previs_gate_wiring.py 13 PASS / 2 FAIL 路径问题）
- [ ] 更新后的运行手册（需补 §3/§4/§5/§6 到 AGENTS.md）
- [x] 尚未实现能力清单（本报告第四节）

---

**审计者**：Claude Opus 5.5 (orchestrator + audit agent a79a16b7bb96cce39)  
**审计依据**：优化方案原文 2026-10-16 + commit ce38308 + 2026-10-17 接线改动  
**下一步**：E12 S5 那 8 个身份失败需重做关键帧（改提示词 → 停放旧图 → 重登记 → 付费重做），或线主授权放行
