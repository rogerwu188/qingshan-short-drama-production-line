# 从 v1 迁移

## 要带的

| 来源 | 去向 | 说明 |
|---|---|---|
| `tools/{9 个门}.py` | `gates/` | 已带，E75 v4 实测 9/9 PASS |
| `tools/canonical_writer_dispatcher.py` 等 4 个 | `runtime/` | 已带 |
| `workflow/claude_writer_agent/tools/{2 个}.py` | `gates/` | 已带 |
| `scripts/E*_NARRATIVE_CANONICAL_v*.md` 等四层产物 | 另行决定 | **57M，是资产不是代码**，建议单独仓库或 LFS |
| `SUPERVISOR_ORDERS.json` | `state/` | 是运行时状态，建议入库但单独目录 |
| `PROGRESS.json` / `MEMORY.md` | `state/` | 同上，**只带当前版，不带 100+ 份 .bak** |

## 不要带的

| 东西 | 体量 | 原因 |
|---|---|---|
| `production/` | **1.4G** | 中间产物，可重建 |
| `PROGRESS.json.bak_before_r*` | 100+ 份 × 2.4M | 历史快照，git 本身就是历史 |
| `tools/_batch13_*.py` `_batch14_*.py` `_batch15_*.py` | — | 一次性批次脚本，已失效 |
| `tools/build_e47_v4_layers.py` `emit_e47_v*.py` 等 | — | 单集一次性构建器；每集重写一份是 v1 的坏习惯，v2 应统一模板 |
| `tools/__pycache__` | — | — |
| `SUPERVISOR_ORDERS.json.pre_seq*.bak` | 40+ 份 | 同上 |

## `.gitignore` 必须改

v1 的 `.gitignore:20` 有一条：

```
/workflow/claude_writer_agent/*
```

**整个写手目录被排除在版本控制之外。** 全剧 33 集的权威剧本、治理台账、监制订单、封缄记录——**从来没进过 GitHub，只存在于一台 Mac 的磁盘上**。

v2 必须反过来：**代码入库，产物与大文件按类型排除。**

```gitignore
# writer agent：代码入库
!writer_agent/**
# 产物与历史快照不入库
writer_agent/state/*.bak*
production/
**/__pycache__/
```

## 上传前必须先清的存量缺口

第 10 门对 E43–E75 现行版本回扫的结果：

| 集 | 无源且未申报 | 是什么 | 处置 |
|---|---|---|---|
| E51 | ~~S03／S08／S11~~ | 赌坊搜捕交叉剪辑 | **已在 v5 补登为 INS-E51-02 并修正承接口径，现 PASS** |
| E47 | S05 | 后院空镜 | 待补登 |
| E61 | S02、S07 | 猫群对峙线B | 待补登 |
| E65 | S02 | 对面铺面窥视线C | 待补登 |
| E48 | 无法审计 | `beat_disposition` 只列 event_id，未记场次落点 | 补齐落点后重跑 |

其余 28 集 PASS。**这 4 集 + 1 集不阻塞本包上传，但下一轮写手起来必须先清。**

## 已知：两个 agent 的改动都还没提交

上传前的盘上状态（2026-09-02）：

- 当前分支 `codex/wuxia-combat-library-v1`，与 origin 同步（0 ahead）
- Codex 的 V3 编译器整改：15 个文件 `M`，**未提交**（`video_execution_plan_compiler.py` +94 行等）
- 写手侧 v2 门与合同修改：**未提交**
- `.git/index.lock` 存在且不可删 —— **不清掉谁也提交不了**

建议：**分两条分支两个 commit**，编译器整改归 Codex（等它把 21 个坏掉的旧测试迁移完再提），写手包单独一条立刻可提。
