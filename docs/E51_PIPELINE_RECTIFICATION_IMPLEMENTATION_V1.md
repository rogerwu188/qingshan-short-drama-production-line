# E51 生产线整改实施报告 V1

日期：2026-09-02
依据：`/Users/rogerwu/Downloads/E51_生产线整改指令_V1.md`
范围：生产线代码、硬门与 E51 只读/无生成回归；未重新生成、未重新发行 E51。

## 结论

附件 P0/P1/P2 所要求的执行路径已经落到代码。新合同从 E51 起强制执行；E50 及更早的不可变历史清单仍可读取，但不得作为 E51+ 模板绕过新门。地图、天气、镜头类型、身份、服装、声音模式等既有结构化合同没有被删除、放宽或重新解释。

E51 现有 27 条 provider 媒体经过新剪辑台逐帧 dry-run 后被正确判为 `FAIL`，原因不是内容审美复检，而是旧剪辑仍为整段直拼：中位镜头 7.0 秒、3 秒以下镜头占比 0%、只有 4/27 条存在尾裁。VU008 的 5.9167–6.0417 秒被逐帧扫描检出黑帧。该结果证明旧的五点抽样确实会漏掉短黑场。

## 逐项实现

### P0-1 同场景真实尾帧链

- `tools/build_video_unit_anchor_plan.py`
  - 场景首单元：`SCENE_FIRST_GENERATED_KEYFRAME`。
  - 同场景后续单元：首参考固定为 `PREVIOUS_UNIT_REAL_FINAL_FRAME`。
  - 不再为每个视频单元独立生成开场锚点。
  - 缺少 `scene_id` 直接失败，不能把每个单元偷偷当作新场景。
- `tools/opening_anchor_chain_gate.py`
  - 付费视频提交前核验上一单元真实尾帧路径、SHA 和第一参考图绑定。
  - 未物化或 SHA 不一致时禁止 POST。
- `tools/video_unit_anchor_count_gate.py`
  - schema 升级为 `qingshan.video_unit_anchor_count_gate.v2_previous_final_frame_chain`。
  - 锚点数量只对额外身份/道具重锚做判断，不再决定开场是否独立生成。

### P0-2 关键帧只表达 entry_state

- 新增 `tools/keyframe_entry_state_gate.py`。
- `source_shot_contract`：
  - 必须有 `entry_state`；
  - 禁止出现 `completion_state` 字段；
  - `entry_state` 禁止“持续/保持/连续”；
  - 不允许回退读取 `frame_content` 或 `first_frame_motion_state`；
  - 必须用独立的 `target_completion_state.state_delta_evidence` 证明起态与完成态至少一维不同。
- 三条图片付费入口在 E51+ 视频关键帧提交前都会重新执行此门，不能从旧批处理器绕过。

### P0-3 真实剪辑台与逐帧技术扫描

- 新增 `tools/media_frame_integrity.py`：逐帧读取全部视频帧，计算亮度、相邻帧差，登记黑帧、纯色帧、冻结区间；不再用五点抽样代替技术扫描。
- 新增 `tools/editorial_selection_gate.py`：
  - 每段必须显式写 `selected_in_seconds` / `selected_out_seconds`；
  - 禁止 `USE_FULL_PROVIDER_MEDIA`；
  - 头部 0.8 秒内的无有效状态变化 padding 可裁；
  - 尾部按“亮度低于全片中位数 40%”或“帧差低于中位数 30%”回溯；
  - 安全柄固定 0.25 秒；
  - 全部尾裁为 0、镜头中位数大于 4.5 秒、3 秒以下镜头不足 20%均失败；
  - 成片若有 YAVG<8 黑帧、纯色帧或冻结区间，技术门失败。
- `tools/edit_plan_integrity_gate.py` 已接入上述选段门，并继续保留禁止变速、补帧、循环、静帧延长的既有规则。

### P0-4 防止 COMBAT_EXCHANGE 类别洗白

- `tools/video_execution_plan_compiler.py` 与 `tools/sd2_motion_density_gate.py`：
  - `COMBAT_EXCHANGE` 仅允许 7–12 秒且接触/闪避/威胁临界点合计不超过 2 次；
  - 小于 7 秒且至少 2 次交互时强制归为 `COMBAT_IMPULSE`，同时输出 `UNIT_CLASS_LAUNDERING` 并要求拆分，不能靠改名放宽；
  - E51-VU-010（5.6 秒/3 次）和 E51-VU-011（6.2 秒/4 次）均已实测触发 `UNIT_CLASS_LAUNDERING`。

### P1-5 道具状态机

- 新增 `tools/prop_state_contract.py`。
- 每拍每个道具必须有 entry/exit 的 `owner / hand / position / disposition`。
- owner、手或持有形态发生变化时必须有 `transition_authorization.writer_authored=true`。
- 对话拍不得由编译器发明道具易手。
- 首帧必须有 `start_frame_visual_confirmation.status=PASS` 和 `evidence_ref`；语义声明不能代替画面证据。

### P1-6 受力者状态差

- 打斗拍中只要声明 `action_patient`，就必须提供独立的 `patient_state_delta_dimensions`，至少包含 `POSITION` 或 `POSTURE`，并有前后不同的证据。

### P1-7 镜头权威去冲突

- `camera_authority_gate` 明确唯一权威为 writer 的 `camera_plan`。
- provider renderer 只准序列化一次镜头合同；不得同时拼接第二份“摄影”与“打斗镜头语言”区块。
- `camera_language_selector` 的既有受保护字段继续保持不可变，没有修改 writer 原始运动方向、景别或轴线。

### P1-8 技术 QA 与内容 QA 分离

- 黑帧/纯色/冻结改为逐帧技术扫描。
- 五点采样仍可用于低成本基本剧情/身份内容检查，但不再承担黑帧发现职责。
- 没有恢复昂贵的生成后动作合理性、微表情精度或表演审美复检。

### P2-9 跨集事件连续性

- 新增 `tools/cross_episode_event_continuity_gate.py`。
- 首场必须声明 `CONTINUING / RESOLVED / ELAPSED`。
- `CONTINUING` 不得降级为 `STATIC / TABLEAU / QUEUE / POSE_HOLD / ATMOSPHERE`，并必须有 writer authored continuation action。
- `tools/video_execution_plan_compiler.py` 已在 E51+ 的 `episode_first_scene_unit` 编译阶段强制执行该门。
- 编译器不代写剧情，只负责阻止错误降级。

### 付费边界防绕过

- 三条视频提交入口全部重新执行 `opening_anchor_chain_gate`。
- 三条图片提交入口全部重新执行 `keyframe_entry_state_gate`。
- 静态覆盖测试会在任何提交入口遗漏硬门调用时直接失败。

## E51 回归证据

- 逐帧剪辑 dry-run：`qa/e51_v4_sd2_accepted_media/E51_V4_EDITORIAL_SELECTION_DRY_RUN_V1.json`
  - 27/27 源媒体扫描完成；
  - VU008 检出 0.125 秒黑尾；
  - 11 个视频单元检出至少一个冻结区间；
  - 旧剪辑节奏门失败：median=7.0s，under-3s ratio=0；
  - 未产生 provider 请求，积分消耗 0。
- E51 执行计划回归：VU010/VU011 均触发 `UNIT_CLASS_LAUNDERING`。
- 主工作区新旧核心回归：182 项定向单元测试通过。
- 从最新 `origin/main` 建立的干净发行工作树：181 项通过、1 项因未随源码发行 E51 私有 fixture 而跳过；覆盖三条视频入口、三条图片入口及并行 supervisor。
- 全仓 1510 项历史测试尝试运行；仓库原有环境/历史资产/pytest 缺失与 E40 固化测试存在失败，因此不将全仓结果冒充 PASS。与本次修改直接相关的定向测试均已独立通过。

## 明确未做

- 未重新生成 E51 任一视频；
- 未修改或发布 YouTube/抖音；
- 未更改地图、天气、镜头类型、身份、服装、声音模式等现有结构合同；
- 未通过增加提示词长度解决问题；
- 未放宽任何既有硬门。
