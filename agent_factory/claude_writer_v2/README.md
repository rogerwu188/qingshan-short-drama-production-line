# 青山 Writer Agent — 全新完整包 v2.0

给 Codex：**这是一份从零重整的写手 agent，不是旧目录的补丁。** 旧的 `workflow/claude_writer_agent/` 累积了一年多的一次性脚本、批次工具、几十份 PROGRESS 备份和 1.4G 中间产物，其中大部分不该进版本控制。本包只保留**真正在跑、且必须被版本控制的东西**。

## 这个 agent 干什么

把一部小说逐章改编成竖屏短剧的**权威剧本**。每集产出四层文件，全部必须过门才能移交下游生产线（关键帧、视频生成、剪辑）。

```
原著第 N 章
   ↓  写手（本 agent）
四层产物：narrative canonical / directing script / generation contract / manifest
   ↓  十门 fail-closed
   ↓  dispatcher start → finish（逐层）→ seal
下游生产线（不在本包内）
```

## 目录

```
writer_agent/
├── README.md                      ← 本文件
├── docs/
│   ├── CHARTER.md                 ← ★唯一规则源。旧的宪章＋3份 WRITER_TASK＋若干配方卡全部并进这一份
│   ├── GATE_REGISTRY.md           ← 十门的 ID、实现、失败含义
│   └── MIGRATION_FROM_V1.md       ← 从旧目录迁移：带什么、不带什么、为什么
├── schemas/
│   ├── manifest.schema.json       ← manifest 必填字段与类型
│   ├── beat_disposition.schema.json
│   └── authorized_insertion.schema.json
├── gates/                         ← 十一个门（九门 script phase ＋ 时长账 ＋ 交付绑定）
├── runtime/                       ← dispatcher / 门运行器 / 溯源 / 原子发布
├── templates/                     ← 四层产物的空模板
├── state/                         ← 空白运行时模板（不含《青山》历史数据）
└── tests/
```

## 立刻能跑

从仓库根目录运行；运行时会调用同一版本仓库内 `tools/` 和 `configs/` 中的公共生产线组件：

```bash
# 跑一集的全部 script-phase 门（fail-closed）
python3 agent_factory/claude_writer_v2/runtime/episode_stage_gate_runner.py --episode E76 --phase script \
        --out qa/e76_script_phase/run_001/

# 单独跑场次来源申报门（v2 新增，见 CHARTER 第 8 节）
python3 agent_factory/claude_writer_v2/gates/writer_scene_source_declaration_gate.py \
        workflow/claude_writer_agent/scripts/E76_manifest_v1.json
```

## 与 v1 的实质差别

| | v1（旧目录） | v2（本包） |
|---|---|---|
| 规则文件 | 宪章 + 3 份 WRITER_TASK + 4 份配方卡，互相引用、部分过期 | **一份 CHARTER.md** |
| 门 | 9 门，散落在 tools/，无注册表 | **11 门 + GATE_REGISTRY.md** |
| 场次来源 | 无门，可以加戏不报备 | **新增 SCRIPT-SCENE-SOURCE-DECLARATION，fail-closed** |
| 起止态 | `start_state = completion_state` 反填路径存在 | **禁止，见 CHARTER 4.3** |
| 关键帧 | 由 `completion_state` 生成 | **必须由 `entry_state` 生成，见 CHARTER 4.4** |
| 版本控制 | 整个目录被 `.gitignore` 排除 | **本包全部入库；产物与状态另行约定** |

## 已知待清（不阻塞上传）

`docs/MIGRATION_FROM_V1.md` 列了旧盘上 4 集的申报缺口（E47-S05、E61-S02/S07、E65-S02）与 1 集无法审计（E48），下一轮写手起来先清。

## 公共包与项目状态的边界

仓库中的 `state/` 只能保存空白初始模板。真实 `SUPERVISOR_ORDERS.json`、`PROGRESS.json` 和《观众已知清单》必须保存在部署工作区，不能回写到公共包。这样第三方 clone 后会从 `latest_order_seq=0` 和空剧情事实开始，不会继承《青山》的生产状态。
