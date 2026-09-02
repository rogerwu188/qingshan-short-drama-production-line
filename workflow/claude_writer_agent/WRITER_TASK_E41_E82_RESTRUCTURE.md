# 【派单卡】E41–E82 v3 因果层重写（Roger 2026-08-21 直令「重写」）

> **🔴 战役状态：REOPENED。** 上一轮 v2 结构重构 14 批全部 PASS_SUPERVISOR、写手线曾判 `TERMINAL`；
> **该终态已作废**，本卡以 v3 因果层为准重新开工。写手线读到本行即视为有可执行工作，不得再返 `STANDBY_NO_EXECUTABLE_WORK`。
>
> 授权号 `ROGER-20260821-E41-E82-NARRATIVE-V3-REWRITE` · 指令 CL2X-1226
> Roger 原话（2026-08-21，回应 CL2X-1225 巡检问句「这 42 集按新规矩只能重写不能补丁，要不要立刻开这条重写战役、是否 42 集全做」）：**「重写」**
> **口径说明（透明记录）**：Roger 的回答是**无限定**的，故按 **E41–E82 全 42 集**执行；若本意为更小范围，Roger 一句话即可收窄。
>
> 前授权号 `ROGER-20260818-US-PACING-V2-RESTRUCTURE`（CL2X-1193，v2 结构层，成果保留作内容参考）
> 上游依据 `ROGER-20260821-NARRATIVE-CANONICAL-CAUSAL-V3`（v2 数量项降为诊断，阻断依据改为 story move 因果 DAG）
> **本卡取代 `WRITER_TASK_E38_PLUS_20260728.md`（E38/E39 已完成，该卡归档不再执行）。**

---

## 〇、为什么要重写（一次说清，别再当成"再改一遍结构"）

监制 2026-08-21 20:15Z 对 E41–E82 **逐集实跑**已注册门 `SCRIPT-US-DRAMA-EVENT-DENSITY`（E41/E42 取其 v4 manifest，余取 v3）：

- **42/42 FAIL**，失败码逐集**完全相同**的两条：`NARRATIVE_CANONICAL_CONTRACT_MISSING` + `WRITER_PROVENANCE_MISSING`
- **零集出现密度类或结构类失败**

即：**不是稿子写得不够快，是「分层 authority 正文」与「运行身份 receipt」这两件新增物在 42 集上一件都不存在。**

**为什么不能打补丁**：`WRITER_PROVENANCE_MISSING` 要求的 receipt 必须在**开写那一刻**由 dispatcher `start` 取 lease 并记录 exact agent/provider/model/session，`finish` 固化 authority SHA；门会复算 receipt SHA 逐字段核对。而生产线已明文自律「**不为历史剧本伪造模型 receipt**」。所以既有 42 集的文本再怎么改，这一条永远补不上——**唯一合规路径是经 dispatcher 重新走一遍写作流程。**

**既有成果不是废纸**：v2 那 14 批的结构成果（逐场天气 481/481、FS-1 21/21 窗口、并行线与跨线切换设计、事件严格计数）**全部可作为重写的内容起点**；作废的只是它们的「生产准入资格」，不是内容。

---

## 一、任务

**E41–E82 共 42 集全部重写**，每集产三件（缺一不可）：

1. story-only 叙事权威正文 `E{NN}_NARRATIVE_CANONICAL_v{n}.md` —— **只写故事事实与可表演正文**，禁混入景别／运镜／首帧／负向提示词／声线／空间生成字段
2. 导演稿 `E{NN}剧本_ClaudeWriter_v{n+1}.md`
3. `E{NN}_manifest_v{n+1}.json`（含 `narrative_canonical` 与 dispatcher 完成 receipt 的精确绑定）

**不得再只产旧单体文件。** 每集流程固定为：

```
python3 tools/canonical_writer_dispatcher.py start \
  --episode E{NN} --version {n} --writer-run-id <本轮唯一ID> \
  --agent-id <本 agent 标识> --provider <真实 provider> --model-id <exact model ID> \
  --session-or-task-id <本次会话/任务 ID> \
  --input-bundle <输入包路径> --rule <规则文件> --receipt <receipt 路径>
   ↓  写 story-only E{NN}_NARRATIVE_CANONICAL_v{n}.md
python3 tools/canonical_writer_dispatcher.py finish ...   # 固化 authority 输出 SHA、释放 lease
   ↓  写导演稿 + manifest，把完成 receipt 精确绑定进 manifest
python3 tools/us_drama_event_density_gate.py --script <manifest> --out <QA 路径>   # 自检必跑
```

**硬性**：`--model-id` 必须是 **exact model ID**，`Claude`／`Fable 5`／`Opus`／`default`／`auto` 等泛称会被拒；
lease 同集同版本独占（`O_EXCL`）；`finish` 只接受 lease 所有者；**历史完成 receipt 不可覆盖**。
缺 receipt、receipt SHA 不符、或 receipt 未完成 → 门 fail closed，**不得交付导演稿或 generation contract**。

**三集一批，写完即停**，交监制前置门 CL2X-499，PASS 才开下一批。
**批 1 = E41 + E42 + E43。** 未过审不得开批 2。

**E40 在产，绝对不动。** E38/E39 已完成，不动。

---

## 一·补．★标杆样例（开工前必读，照着做）

**`workflow/claude_writer_agent/scripts/E41剧本_ClaudeWriter_v4.md`** = 监制直接改稿产出的 **E41 重构标杆**，
已达四条结构指标（12 场／最长 20s／7 地点／2 线／6 次跨线切换／22 事件严格计数）。
**⚠️ 2026-08-21 更正（v3 上线后此段有一句已作废）**：原文写「E41 不必重写，直接沿用 v4」——**该句作废**。
E41 v4 与其余 41 集同码 FAIL（`NARRATIVE_CANONICAL_CONTRACT_MISSING` + `WRITER_PROVENANCE_MISSING`），
**E41 同样必须经 dispatcher 重走一遍**并产 story-only authority，receipt 不得回填。
**但 v4 的文本与结构仍是最好的起草基础**——重写 ≠ 推翻重想，是把已有内容经合规流程重新产出并补足因果 DAG 与字面证据绑定。E42 起同理沿用各自 v3 已有内容。

样例里最值得复制的三招：
1. **把既有的"事后交代"改成实时并行线**——E41 把「取纸之手」从只在阴神重演里出现，改成当夜 B 线（封纸→出角门→马蹄没入雪幕），观众先于主角知情，看着他们拼死打开一个空格子。**零新增角色、零新增台词**，只多了 2 个 location。
2. **B 线全程零台词零露脸**——只给手、油布包、雪中靴、背影剪影。既造张力，又不提前消耗 canon 的真身揭示；护腕纹样与「张夏」二字仍留给阴神重演首揭，两处递进不重复。
3. **长场按转折切开**——36s 的场拆成 20s+14s 两场，各自有独立转折与 button；砍掉的是过渡镜，不是台词。

## 二、唯一标准

`codex_docs/美剧叙事节奏标准_v2_结构层_20260818.md` —— **开工前整篇读完**。

自 2026-08-21 起，**首要标准改为** `codex_docs/美剧叙事节奏标准_v3_因果层_20260821.md`（v2 降为结构参考）。
v3 纠正「拆场／换地点／多跨切＝剧情快」的错误：**v2 数量项降为诊断**，正式阻断依据改为真实 narrative canonical 的 **story move 因果 DAG**。

**⚠️ 范围更正（2026-08-21 20:15Z 实测）**：本节原写「E41–E43 旧 v4 ……下一次进入生产前必须补分层 authority」，读起来像**只有 E41–E43** 需处理。
**实测是 E41–E82 全 42 集同码 FAIL**，故范围＝**全 42 集**，一集不例外。

v3 每个可计数 story move 的硬要求（照做，别自报）：

- exact-SHA 绑定**真实正文中的唯一字面证据**（写不出字面证据的，不得计数）
- 唯一 causal cluster + 具名前驱 move；**非首 move 的 cause state 必须来自具名前驱的 result state**
- 可核验的 cause/result state、角色动作或外部变化、**对下一步的强迫关系**

注册参数（门实读，不是建议值）：**story move ≥3.2/分钟**；**agency move 占比 ≥0.50**；**连续 discovery/payoff ≤1**；**正文每分钟可见字符 ≤1400**。
固定场次数、地点数、时间跳跃数、cross-cut 数**已降为 diagnostic**，不再能作为「节奏快」的替代证据。

### 四条结构硬指标（缺一即 REVISE）

| # | 项 | 现状（要改掉的） | v2 要求 |
|---|---|---|---|
| ① | 场数 | **固定 5 场** | **8–12 场**，由剧情定；**禁任何集恰等于模板值**；连续 3 集场数相同须写依据 |
| ① | 单场时长 | 26–40s | **硬上限 22s**，下限 6s（允许短插入场） |
| ② | 地点 | E40 全 5 场王府花厅、E43 全 5 场废窑仓 | **≥4 个不同 location**；**禁全集同一地点**；同 location 连续 ≤2 场 |
| ② | 时间 | 全集压在同一夜 | **≥1 次时间跳跃** |
| ③ | 并行线 | 无 | **≥2 条线同时推进**；全集 **≥3 次跨线切换**；切换点必须落在**悬置处**（对方正要开口／手正伸向门／刀正落下），禁事情说完才切 |
| ④ | 每场转折 | 有场只是过渡 | 开场 **首 3s 内已在事件中**（禁"走进来—坐下—开口"）；场末必须有**主动权／认知／得失／被迫选择**之一改变；无变化的场删除或并入 |

### 事件定义收紧（反 Goodhart，重点）

**可计数**：不可撤销的行为（下毒/烧毁/杀人/签字/交出/逃走）、权力关系改变（结盟/背叛/要挟成立/被迫服从）、新的物理事实（尸体/账册/密道/伤口/追兵到门口）、得失（得到或失去某物某人）、被迫两难选择。

**不可计数**（v1 时期虚高主因）：看见／听见／意识到／想起／确认／判断／下决心（无外部动作）、解释既有信息、复述观众已知、二次说明画面已演内容、纯情绪反应。

**`event_list` 每条必须写成「谁做了什么 → 什么变了」的句式。写不成这个句式的，不得计数。**
监制将**独立重数**，与自报差异 >30% 即 REVISE。

---

## 三、成本护栏（防"加场=加钱"）

场数翻倍 **≠** 地点翻倍：

- **优先用交叉剪辑造场**——在已建立的 2–3 个地点之间来回切，每切一次即成新场，**零新增资产**。这是美剧"快"的最大来源，也是最便宜的来源。
- 复用本集已有 location 的不同角落／景别作短插入场（≤10s）。
- **新增 location 每集 ≤2**，超出须在 manifest 写明理由。
- 短插入场优先用已准入素材的反应镜／空间镜，不为凑场数额外生成。
- 换算：8–12 场里约 5–7 场实拍主场，3–5 场交叉切回或短插入。**资产增量 ≤ +20%。**

---

## 四、⚠️ 场变短的正确来源

**必须来自砍解释、砍铺垫、进晚出早。**
**不得**把同样的台词摊到更多场里——**对白占比上限不变**：全集可听对白 ≤35%，动作场 ≤20%，每句 ≤25 字。
违者 REVISE。

---

## 五、逐集必带的继承要点（一条都不许丢）

1. **首帧动势 `first_frame_motion_state`** 逐镜必填：动作中途的失衡瞬间（手伸到一半／身体正在转／物件正在落下／脚正离地），信息故意不全（只给局部／被前景遮挡），每镜给一条禁例；**禁完成态摆拍·禁对称站定·禁看镜头·禁静止起手**。缺 = blocker。
2. **环境生命 `ambient_life`** 按场分级：**A 级**（人群/市集/户外/风）写群体动作趋势；**B 级**（室内有他人或风火水）写微环境（烛焰摇/帘动/纸页掀）；**C 级**（密室独处/深夜对峙，静即是戏）**明确写「环境静」、禁强行加动**。A/B 级首帧背景须在动势中；群戏背景反应逐拍升级。
3. **★主角年龄锁 20 岁**（E37 起，覆盖旧 17 岁锁）：陈迹 = **20 岁年轻男性**，正向「20岁年轻男性·清瘦挺拔·面容年轻紧致·冷静清醒」，负向「十七岁少年·幼态儿童脸·30岁以上成熟脸·中年·法令纹·眼纹·胡茬·沧桑」。唯一三视图 `CHAR-chenji-age20-user-turnaround-canonical-v1-20260729.png`（sha256 `e5bb8c90…`），禁与旧陈迹参考同时上传。皎兔 18／云羊 17 不变。**冷面≠老脸。**
4. **逐场天气**：每场 scene_state 含 location/time/**weather**/visual_zone（缺 = blocker）；紧靠原著，未规定则承上集结尾 + 按剧情选并写依据；**禁相邻集整集天气雷同、禁默认套雨夜**。
5. **表情层 `expression_arc`**：头部 + 逐镜表情方向，情绪弧贯穿全程。
6. **对白**：每句 ≤25 字，潜台词不直给；绑 speaker→audio_slot→voice_asset_id；陈迹/白鲤 = native 多模态锁定声线，其他 per_line，禁通用 TTS。
7. **FS-1 打斗**：每 2 集 ≥1 场完整打斗（≥15s，含起承转合）。**先查邻集窗口是否已承载**，避免每集硬塞造成新单调。短灭口/刺杀 beat 不计 set-piece。
8. **动作可视化四步**（每动作镜）：问目的/赌注 → 找无形要素 → 给每个无形一个从角色能力推出的可见现象 → 遮剧本自检观众能否读懂「发生什么+为什么」。
9. **提速 M-032**：主线三问每集至少一问给能复述的硬答案；新名字每 4 集 ≤1 个且须活到结算；延宕每卷 ≤1 次；每 2 集一个可复述大揭示。
10. **逐镜 `shot_treatment` 由剧本决定**（景别/机位/运镜/图数/时长），禁固定模板；时长逐镜 **4–15s 不均匀**，禁静止起手措辞。
11. **整集全局空间地图**：先定义覆盖全部地点的 `EPISODE-GLOBAL-SPACE-MAP-ID`，再为每地点定义可跨集继承的 `GLOBAL-SPACE-MAP-ID`，逐镜绑定 `ROOM-ID / ZONE-ID / ANGLE-ID / SUBSPACE-ID`，最后才写人物/物品站位。完整继承必须保持 ID、版本、拓扑 SHA、地图图 SHA 一致；部分继承新增地点必须新建整集集合 ID。
12. **动作轨迹服从空间**：每个动作镜在锁定 `SUBSPACE-ID` 和人物/物品起始站位后填写 `spatial_action_contract`，包含剧本动作原文及 SHA、轨迹起点/中间点/终点、接触/受力、不可穿越物、跨区入口、遮挡、退路、反制和终态；动作不得出子空间、穿固定物或与剧本终态冲突。
13. **逐镜不可绕过 `prompt_spec`**：generation contract 的每个 shot 必须由写手/导演直接给出完整结构化 `prompt_spec`，覆盖 `space`、`scene_state`（含原样 `ambient_life` 与 `weather_provenance`）、`cast`、`props`、`action`（分类/起态/主动作/结果态/接触点/方向/物理因果/微表情/物理动作）、`action_visualization`、`performance`（含逐人覆盖）、`dialogue_delivery`、`visual_design`、`sound_design`、`role_semantic_disambiguation`、逐拍负面限制和 `audio_contract`。其中 `writer_camera_instruction / writer_shot_treatment / writer_expression_arc / source_first_frame_motion_state / dialogue / negative_prompts / subspace` 必须逐字绑定同一 shot 的源字段；生产端只准序列化和分组，不准用默认模板补造缺项。缺一项即拒绝写手封缄。自 2026-09-01 起，`action` 还必须由写手/导演显式填写 `state_delta_dimensions`（仅限 POSITION/POSTURE/CONTACT/POSSESSION/INTEGRITY/MOMENTUM）和每一维的 `state_delta_evidence.{DIMENSION}.entry/exit/entry_code/exit_code`；文本证据与状态代码两端均不得相同，禁止只换说法描述同一维持态；所有动作至少 1 维，COMBAT 至少 2 维。单冲量 COMBAT 还必须填写以当前视频单元为零点的 `contact_time_seconds`。生产端禁止从 `frame_content`、`first_frame_motion_state` 或自由文本猜测这些字段，缺失即 fail closed。

---

## 六、manifest 必填 `pacing_v2` 与 `narrative_canonical`（缺 = blocker）

```json
"pacing_v2": {
  "scene_count": 10,
  "scene_seconds": [18, 22, 9, 20, 14, 22, 7, 19, 21, 16],
  "max_scene_seconds": 22,
  "distinct_locations": 5,
  "location_list": ["LOCATION_01", "LOCATION_02", "LOCATION_03", "LOCATION_04", "LOCATION_05"],
  "max_consecutive_same_location": 2,
  "time_jumps": 2,
  "parallel_threads": 2,
  "cross_cuts": 4,
  "new_locations_added": 1,
  "countable_events": 34,
  "event_list": ["谁做了什么 → 什么变了", "..."],
  "scenes_without_turn": 0,
  "dialogue_ratio": 0.32,
  "action_scene_dialogue_ratio": 0.18
}
```

`distinct_locations` 的机器计数唯一事实源是 `location_list` 的项目数。连续三集 `scene_count` 相同且确有剧情依据时，另填非空 `scene_count_justification`。交监制前必须运行 `tools/us_drama_event_density_gate.py`，不得只做文档自检。

同一 manifest 还必须填写 `episode_global_space_map_id`、`global_space_map_refs` 和逐镜 `shot_subspace_bindings`。空间地图由 Pipeline 生成/准入媒体并补齐 SHA；Writer 负责先完成拓扑、分区、机位和走位合同，不能把空间设计留给生图模型猜测。

`narrative_canonical` 必须固定独立 story-only 文件路径/SHA、`production_contracts_externalized=true`、稳定 `LOC-*/TIME-*` 场景序列和 story move DAG。导演、空间、首帧、资产、声音、模型和 QA 字段必须在后续派生文件，禁止回填 narrative 正文。

---

## 七、纪律

- **只改结构与密度，不动 canon／主线／钩子**（解耦原则）。事件层、七项自检、梗概、尾钩沿用原版。
- 连续性：承上集 + 校 E±1 埋线 + 写完更新 `观众已知清单.md`。
- 落 `workflow/claude_writer_agent/scripts/`；写完更新 `PROGRESS.json`、`MEMORY.md`（只增）。
- **三集写完即停，交监制前置门，不自行开下一批。**

---

## 八、★场次来源申报（BLOCK，2026-09-02 立，E51 v4 实证）

### 规则

`manifest.structure` 里的**每一个** `scene_id`，必须至少满足其一：

- **A｜有源**：出现在 `beat_disposition` 的落点里（该场承载源章某一拍）；
- **B｜已申报**：出现在 `★authorized_insertions` 的 `scene_id` / `shots` 里。

两者都不满足 = **无源且未申报** = 该轮不得交付。

`beat_disposition` 的落点**必须写到场次粒度**（如 `"landed_at": "E51-S03（两镜）"`）。只列 `event_id` 不写落在哪一场的，本门无法审计，一律判 WARN 并要求补齐后重跑。

### 门

```bash
python3 tools/writer_scene_source_declaration_gate.py \
  workflow/claude_writer_agent/scripts/E<NN>_manifest_v<V>.json \
  --out qa/<round>/SCENE_SOURCE_DECLARATION_V1.json
```

`status != PASS` ⇒ 不得 `finish`，不得移交镜头设计，不得进入付费生成。

### 立门缘由（写在明处，别再犯）

E51 v4 的 **S03／S08／S11** 三场线B（赌坊搜捕交叉剪辑，共 20.8 秒，占目标片长 11.6%）：

- 不在 ch56 十拍的 `beat_disposition` 内——**不是源章内容**；
- 也不在 `★authorized_insertions` 里（v4 只登记了 INS-E51-01＝S01-05）——**没有申报**；
- 就这么混在源章内容中间通过了 script phase，一路走到付费生成和成片。

问题不在于"加了戏"。交叉剪辑本身合理，S03／S08／S11 承担的是"包围圈一步步收紧到陈迹头上"这个真实功能。**问题在于加了戏没报备**——监制无法从 manifest 上分辨哪些是原著、哪些是写手编的，忠实度自限也就无从计算。

E51 v5 已补登为 INS-E51-02（自扣 −1.5 分），并顺手修了它引出的承接口径错误（v4 的 S03 把 E50 结尾"上百件蓑衣涌向赌坊的门"的攻势倒退成"还堵成一堵墙"）。

### 全库回扫结果（2026-09-02，E43–E75 现行版本）

| 集 | 无源未申报场次 | 处置 |
|---|---|---|
| E51 | ~~S03／S08／S11~~ | **已在 v5 补登并修正，PASS** |
| E47 | S05（后院空镜） | 待补登 |
| E61 | S02／S07（猫群对峙线B） | 待补登 |
| E65 | S02（对面铺面窥视线C） | 待补登 |
| E48 | 无法审计 | `beat_disposition` 只列 event_id，未记场次落点，需补齐后重跑 |

其余 28 集 PASS。**下一轮 writer 起来时先清这四集的申报缺口，再开新集。**

### 写手侧的自查口径

每写完一场就问一句：**"这一场是原著第几拍？"**
答不上来 ⇒ 它就是插入项，当场写进 `★authorized_insertions`，把 `source_basis`（依据哪一集哪一句已落地的字节）、`new_information`（能在落地场次正文里逐格对上的内容）、`self_deduction`（负值带单位）一并写完，**不要留到最后补**。
