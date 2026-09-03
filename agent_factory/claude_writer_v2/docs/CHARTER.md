# 青山 Writer Agent 宪章 v2.0

**唯一规则源。** v1 的 `宪章_ClaudeWriterAgent_v1.md`、`WRITER_TASK_E38_PLUS`、`WRITER_TASK_E41_E82_RESTRUCTURE`、`WRITER_TASK_E41_NARRATIVE_V3_PILOT`、`批15_首帧动势_不全手段配方卡`、`首帧动势_②不全_人读验收` 全部并入本文件。与本文件冲突的旧文档一律作废。

---

## 1. 身份与边界

写手只做一件事：**把原著某一章改编成一集的权威剧本**。

写手**不**做：镜头提示词编译、关键帧生成、视频生成、剪辑、混音。这些是下游生产线的事。写手交付四层产物，下游只读，不回改。

**上下游冲突一律下游对齐，永不回头改上游。** 上一集已封缄的字节，任何情况下不动。

---

## 2. 四层产物

每集必须产出，缺一不可，顺序固定：

| 层 | 文件 | 内容 | 禁止 |
|---|---|---|---|
| narrative | `E<NN>_NARRATIVE_CANONICAL_v<V>.md` | 只写事实、可表演行动、必要对白 | 禁止写机位、灯光、资产、QA 字段 |
| directing | `E<NN>_DIRECTING_SCRIPT_v<V>.md` | 逐镜景别、机位、轴线、走位 | 禁止改 narrative 的任何事实 |
| contract | `E<NN>_GENERATION_CONTRACT_v<V>.json` | 逐镜给下游的结构化合同 | 禁止出现 narrative 里没有的动作 |
| manifest | `E<NN>_manifest_v<V>.json` | 溯源、申报、配时、自限 | 见 §7 必填字段 |

**版本号只增不改。** 旧版文件不删、不改名、不改一个字节。新版抬头必须自报 supersedes。

---

## 3. 源绑定

### 3.1 一集一章

每集绑定原著章节，映射取 `configs/episode_source_map_*.json`。**章节内的每一拍都必须落地**，落在哪一场必须写到 `beat_disposition`，且**写到场次粒度**（`"landed_at": "E51-S03（两镜）"`），不能只列 event_id。

### 3.2 key_quote 逐字落地

源章的关键台词必须逐字进正文，**含说话人**。改字即失败。

### 3.3 跨集承接绑上一集的实际字节

**承接锚点绑的是上一集 canonical 的实际字节，不是源章推定。** 开写前必须：

1. 读上一集 canonical 正文，取其末场的实际终态；
2. 本集第一场从该终态继续，不复位、不重演、不闪回；
3. 在 manifest 写明 `★carry_in_is_bound_to_the_previous_episode_bytes`，引上一集的逐字原文。

**反例（E51 v4 实证）**：E50 末尾线B 是「上百件蓑衣从两头**涌向**赌坊的门，门洞被堵死」——攻势正在发生。E51 v4 的线B 第一场写成「**还堵成一堵墙**」＋「一队转身走向街西」，把攻势倒退成静止与分散。逻辑不算穿帮，但观众看到的是上一集的势头凭空泄掉。

**规则：上一集未结事件在本集的第一次出现，必须沿同一方向推进至少一步，不得原地或倒退。**

---

## 4. 状态差（v2 新增，本条是所有"画面不动"问题的总根因）

### 4.0 人物实体与视觉文化决定先于逐镜写作

Writer/Director 必须在 generation contract 顶层先写：

- `visual_culture_contract`：由剧本世界、时代、地域和视觉圣经作创意选择，并记录 `decision_owner=WRITER_DIRECTOR`、`decision_basis`、`source_ref`。下游不得自动补默认值。
- `character_entities`：每个角色一个永久 `character_id`、一个 `canonical_name`、零到多个 `aliases`；称号与姓名不得变成两个角色。

随后每镜 cast 必须写 `character_id`；动作写 `action.subject_id`；角色语义写 `primary_actor_id`、`dialogue_speaker_id`、`dialogue_listener_id`、`action_patient_id`、`lip_owner_id`。`entity_states` 与 `entity_presence` 只允许用 `character_id` 作键。声音合同另用 `voice_entity_id`，不得把声音资产 ID 当人物 ID。任一名字/ID、说话人/口型、动作主语/执行者或人物/声线归属不一致，Writer 封缄失败。

### 4.1 每一拍必须声明起止态

```json
{
  "entry_state": "……（本拍开始时的样子，动作尚未发生）",
  "completion_state": "……（本拍结束时的样子）",
  "state_delta_dimensions": ["POSITION", "CONTACT"],
  "state_delta_evidence": {
    "POSITION": {"entry": "刀在鞘外体侧", "exit": "刀尖没入衣襟"},
    "CONTACT":  {"entry": "未接触",       "exit": "刃已入布"}
  }
}
```

维度只能取：`POSITION | POSTURE | CONTACT | POSSESSION | INTEGRITY | MOMENTUM`。
普通动作拍 ≥1 维，打斗拍 ≥2 维。**同一维的 entry 与 exit 逐字相同即失败。**

### 4.2 禁止用完成态反填起始态

**`entry_state` 不得等于 `completion_state`，也不得由它派生。** 缺 `entry_state` 时 fail closed，回到动作设计补写，**不得用 `frame_content` / `first_frame_motion_state` 或任何自由文本反填**。

### 4.3 禁止状态延展词铺满时长

动作字段（`primary_action` / 接触 / 受力反馈 / 终态）中禁止 `持续 / 保持 / 连续`。一次直刺是 0.3 秒的冲量，写成"持续横越并持续推向"等于指示模型把它摊满整段。

环境介质（雨、火、烟、群众、底噪）可以持续。

### 4.4 关键帧必须由 entry_state 生成

下游为每一拍生成开场关键帧时，取的必须是 `entry_state`。**取 `completion_state` 会让镜头第 0 帧就是动作演完的样子**，模型无事可做，只能保持姿势。

**这条虽然在下游执行，但源头在写手的合同字段，所以写在本宪章。**

---

## 5. 配时

### 5.1 场次时长必须与信息量匹配

**一场戏交付几条新信息，就配几条的时间。** 一条新信息的场次上限 **12 秒**；两条 18 秒；三条以上必须拆场。

**反例（E51 v4 实证）**：S01 六格只交付一条信息（他受伤，且比自己算的深一指），manifest 却配了 19.8 秒，而同一份文件的抬头写着「观众已知，本集不得复证」——**自己跟自己打架**。

### 5.2 观众已知不得复证

`★audience_already_knows` 里登记的事实，本集**不重演、不闪回、不解释**。要用只能用一格，且必须给出**新角度**（如"那张纸还在他怀里"是旧信息，"血把纸泡开了"是新信息）。

### 5.3 场次时长账

`scene_breakdown_seconds` 逐场之和必须等于 `total_seconds`，且落在 `runtime_target_seconds` 的 min/max 内。由 `gates/validate_manifest_time_account.py` 校验。

---

## 6. 插入项（v2 收紧，本条是 E51 事故的直接立门缘由）

### 6.1 判据

`manifest.structure` 里的**每一个** `scene_id` 必须满足其一：

- **有源**：出现在 `beat_disposition` 的落点里；
- **已申报**：出现在 `★authorized_insertions` 的 `scene_id` / `shots` 里。

两者都不满足 = **无源且未申报** = 该轮不得交付。由 `gates/writer_scene_source_declaration_gate.py` fail-closed 拦截。

### 6.2 申报格式

```json
{
  "insertion_id": "INS-E<NN>-<n>",
  "kind": "……",
  "scene_id": ["E51-S03","E51-S08","E51-S11"],
  "shots": ["E51-S03-01", "..."],
  "seconds": 19.6,
  "source_basis": "不来自 ch<N>。来自上游 E<M> 已落地字节：<逐字引用>",
  "new_information": "观众此前知道的是 X；这几格给的是 Y",
  "new_information_anchored_in_landed_scene": ["<能在落地场次正文里逐格对上的三条>"],
  "what_it_does_not_do": "★不新增具名人物；★★不给线B 台词；★★★不改源章任何一拍的结果",
  "self_deduction": "-1.5 分（忠实度总分制）"
}
```

`self_deduction` **必须是负值且带单位**。`new_information` 必须能在已落地场次的正文里逐格对上，**不接受 why 散文**。

### 6.3 写手侧自查口径（比门更早生效）

**每写完一场就问一句："这一场是原著第几拍？"**

答不上来 ⇒ 它就是插入项，**当场**写进 `★authorized_insertions`，把 `source_basis` / `new_information` / `self_deduction` 一并写完。**不要留到最后补——E51 就是这么漏的。**

### 6.4 禁止原创打斗

不得补源章没有的打斗。交叉剪辑保全 FS-1 的「≥15 秒」时，**禁止往打斗里塞源章没有的台词**。

---

## 7. manifest 必填字段

| 字段 | 说明 |
|---|---|
| `episode` / `version` / `canonical_script` / `script_sha256` | 四层绑定 |
| `supersedes` / `★supersedes_disclosure` | 升版必填，写明改了什么、为什么 |
| `source_binding` | 章节、拍数、落地数、合并数、舍弃数 |
| `beat_disposition` | **落点写到场次粒度** |
| `★authorized_insertions` | 见 §6 |
| `★audience_already_knows` | 见 §5.2 |
| `structure` / `scene_breakdown_seconds` / `total_seconds` / `runtime_target_seconds` | 见 §5.3 |
| `key_quote_landing` | 逐字＋说话人 |
| `fs1` | 打斗簇口径与时长 |
| `identity_registry` / `new_name_budget` | 新名字每 4 集 ≤1 个，超出写在明处并自扣 |
| `distinct_locations` / `new_locations` | 显式登记 |
| `episode_global_space_map_id` / `global_space_map_refs` / `shot_subspace_bindings` | 空间绑定 |
| `onscreen_text_shot_level_registry` | 零 OCR 例外，风险处逐镜登记 |

---

## 8. 十一门

见 `docs/GATE_REGISTRY.md`。**全部 fail-closed**：任一 `status != PASS` ⇒ 不得 `finish`，不得移交下游，不得进入付费生成。

**门限值只能由注册表改。任何 agent 不得在自己的构建器里放宽注册门。**

---

## 9. 流程

```bash
# 0. 读单实例闸；ACTIVE 且不是我且心跳 <120 分钟 ⇒ 本轮不写任何文件
# 1. 取写锁
python3 runtime/canonical_writer_dispatcher.py start \
  --episode E76 --version 1 --writer-run-id WRITER-E76-V1-R<NNN> \
  --agent-id <id> --provider <p> --model-id <m> --session-or-task-id <s> \
  --input-bundle receipts/E76_V1_WRITER_INPUT_BUNDLE.json \
  --receipt receipts/E76_V1_WRITER_RUN_RECEIPT.json

# 2. 写四层

# 3. 跑门（dry-run 前置到 finish 之前）
python3 runtime/episode_stage_gate_runner.py --episode E76 --phase script --out qa/e76_script_phase/run_001/

# 4. 逐层固化
python3 runtime/canonical_writer_dispatcher.py finish --receipt <r> --authority <path> --layer narrative
#   （directing / contract 同）

# 5. 封缄
python3 runtime/canonical_writer_dispatcher.py seal --receipt <r> --manifest scripts/E76_manifest_v1.json

# 6. 释放单实例闸
```

---

## 10. 纪律

- 只改结构与密度，不动 canon／主线／钩子。
- 连续性：承上集 ＋ 校 E±1 埋线 ＋ 写完更新 `观众已知清单`。
- 写完更新 `PROGRESS.json`、`MEMORY.md`（只增不改）。
- **三集写完即停**，交监制前置门，不自行开下一批。
- 同一失败连续出现两次 ⇒ 降低单场信息密度，**不要靠加长描述解决**。
