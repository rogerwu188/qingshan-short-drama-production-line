# 门注册表 v2.0

**全部 fail-closed。** 任一 `status != PASS` ⇒ 不得 finish、不得移交下游、不得进入付费生成。
**门限值只能改本表。任何 agent 不得在自己的构建器里放宽注册门。**

## script phase（十门，由 `runtime/episode_stage_gate_runner.py --phase script` 统一调起）

| # | gate_id | 实现 | 拦什么 |
|---|---|---|---|
| 1 | `SCRIPT-SOURCE-CANON-BINDING` | `gates/source_canon_binding_gate.py` | 源章绑定、逐拍落地、key_quote 逐字 |
| 2 | `FULL-SERIES-SOURCE-FIDELITY` | `gates/source_canon_binding_gate.py` | 全剧级忠实度与血统认证键 |
| 3 | `SCRIPT-READINESS-EXCITEMENT-SHA` | `gates/script_readiness_gate.py` | 四层齐备、SHA 自洽、可读性 |
| 4 | `SCRIPT-US-DRAMA-EVENT-DENSITY` | `gates/us_drama_event_density_gate.py` | 事件密度，反 Goodhart |
| 5 | `SCRIPT-COUNCIL-DRAMATIC-QUALITY` | `gates/dramatic_quality_gate.py` | FS-1 打斗簇 ≥15 秒等戏剧质量 |
| 6 | `SCRIPT-SCENE-DIVERSITY-PREFLIGHT` | `gates/script_scene_diversity_gate.py` | 场景多样性，防同一地点堆场 |
| 7 | `MECHANICAL-DEFAULT-META-GATE` | `gates/mechanical_default_gate.py` | 机械模板、默认套话 |
| 8 | `COMMON-SENSE-CAUSALITY-COUNTERFACTUAL` | `gates/common_sense_causality_gate.py` | 常识因果、反事实 |
| 9 | `PERIOD-ANACHRONISM-LOCK` | `gates/anachronism_lock_gate.py` | 时代错置 |
| **10** | **`SCRIPT-SCENE-SOURCE-DECLARATION`** | **`gates/writer_scene_source_declaration_gate.py`** | **★v2 新增：无源且未申报的场次** |

### 第 10 门（v2 新增）

**判据**：`manifest.structure` 里每个 `scene_id` 必须出现在 `beat_disposition` 落点里，或出现在 `★authorized_insertions` 里。两者都无 ⇒ FAIL。

**WARN 条件**：`beat_disposition` 未把落点写到场次粒度（只列 event_id）⇒ 本门无法审计该集，判 WARN，补齐后重跑。

**立门缘由**：E51 v4 的 S03／S08／S11 三场线B（20.8 秒，占目标片长 11.6%）既不在 ch56 十拍内，也未登记进 `★authorized_insertions`，混在源章内容中间通过了 script phase，一路走到付费生成和成片。问题不是"加了戏"——交叉剪辑本身合理——**问题是加了戏没报备，监制无法从 manifest 上分辨哪些是原著、哪些是写手编的，忠实度自限也就无从计算**。

```bash
python3 gates/writer_scene_source_declaration_gate.py scripts/E<NN>_manifest_v<V>.json \
        --out qa/<round>/SCENE_SOURCE_DECLARATION_V1.json
```

## 其余（非 script phase，按需单跑）

| gate_id | 实现 | 拦什么 |
|---|---|---|
| `MANIFEST-TIME-ACCOUNT` | `gates/validate_manifest_time_account.py` | 逐场时长之和 == total，且落在 target min/max 内 |
| `DELIVERY-BINDING` | `gates/delivery_binding_gate.py` | 交付台账与 receipt 逐字段绑定 |

## 建议新增（v2 尚未实现，留给 Codex）

| 建议 gate_id | 判据 | 依据 |
|---|---|---|
| `SCRIPT-STATE-DELTA` | 每拍 `entry_state != completion_state`，且 `state_delta_dimensions` 普通拍 ≥1、打斗拍 ≥2，同维 entry/exit 逐字不同 | CHARTER §4.1–4.2 |
| `SCRIPT-EXTEND-WORD` | 动作字段中 `持续/保持/连续` 计数 == 0 | CHARTER §4.3 |
| `SCRIPT-KEYFRAME-SOURCE` | 关键帧任务的 `source_shot_contract` 必须用 `entry_state`，不得出现 `completion_state` | CHARTER §4.4 |
| `SCRIPT-SCENE-DURATION-BUDGET` | 单场时长 ≤ 12s × 新信息条数 | CHARTER §5.1 |
| `SCRIPT-CARRY-IN-MONOTONIC` | 上一集未结事件在本集首次出现必须沿同一方向推进 ≥1 步 | CHARTER §3.3 |

这五条是 E51 事故复盘直接得出的，判据都可机器判定。**建议按此顺序实现，第一条收益最大。**
